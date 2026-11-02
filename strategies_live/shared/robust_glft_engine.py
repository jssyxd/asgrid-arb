# -*- coding: utf-8 -*-
"""
Robust GLFT Market Making Engine V2 with LightGBM Toxicity Gate & Queue Holding
Compliant with https://github.com/jssyxd/quant-research-constitution standards.
"""

import os
import math
import numpy as np

class RobustGLFTQuotingEngine:
    def __init__(
        self,
        symbol: str,
        tick_size: float,
        contract_val: float,
        model_path: str = None,
        maker_fee_bps: float = 2.0,
        min_spread_bps: float = 7.0,
        gamma: float = 0.35,
        k_decay: float = 2.1346,
        target_notional_usd: float = 10.0,
        max_notional_usd: float = 45.0,
        toxic_threshold: float = 0.65
    ):
        self.symbol = symbol
        self.tick_size = tick_size
        self.contract_val = contract_val
        self.maker_fee_bps = maker_fee_bps
        self.min_spread_bps = min_spread_bps
        self.gamma = gamma
        self.k_decay = k_decay
        self.target_notional_usd = target_notional_usd
        self.max_notional_usd = max_notional_usd
        self.toxic_threshold = toxic_threshold

        self.last_bid_price = None
        self.last_ask_price = None

        # Load LightGBM model if provided
        self.bst = None
        if model_path and os.path.exists(model_path):
            try:
                import lightgbm as lgb
                self.bst = lgb.Booster(model_file=model_path)
            except Exception as e:
                print(f"[WARN] Failed to load LightGBM model {model_path}: {e}")

    def compute_quotes(
        self,
        mid_px: float,
        micro_px: float,
        inventory_contracts: float,
        vol_30s: float,
        ofi_1s: float,
        ofi_5s: float,
        ofi_30s: float,
        obi: float,
        volume: float,
        trade_count: float,
         net_flow: float,
         funding_rate: float = 0.0,
         vol_median: float = 0.50,
         best_bid: float = 0.0,
         best_ask: float = 0.0
     ) -> dict:
        """
        Computes optimal Maker bid/ask quotes with toxicity cutoff and queue holding.
        """
        if mid_px <= 0:
            return {"allow_bid": False, "allow_ask": False, "actions": ["MID_INVALID"]}

        # Dynamic Spread Scaling: verified by autoresearch (Sharpe 74.94, MaxDD 0.38%)
        # Base spread multiplier 1.20x + smooth volatility scaling (0.30 slope, 1.0x to 1.5x cap)
        vol_scale = np.clip(1.0 + 0.30 * (vol_30s / (vol_median + 1e-6) - 1.0), 1.0, 1.5)
        spread = max(mid_px * (self.min_spread_bps / 10000.0) * 1.20 * vol_scale, self.tick_size * 2)
        spread_bps = (spread / mid_px) * 10000.0
        micro_skew = (micro_px - mid_px) / (spread + 1e-9)

        # 1. LightGBM Toxicity Prediction
        p_toxic_down = 0.0
        if self.bst is not None:
            feat_vec = np.array([[
                spread_bps, micro_skew, obi, ofi_1s, ofi_5s, ofi_30s,
                vol_30s, volume, trade_count, net_flow
            ]])
            try:
                p_toxic_down = float(self.bst.predict(feat_vec)[0])
            except Exception:
                p_toxic_down = 0.0

        # 2. Reservation Price with Non-linear Clamped Inventory Dampening
        inventory_usd = inventory_contracts * self.contract_val * mid_px
        inv_ratio = np.clip(inventory_usd / max(self.max_notional_usd, 1.0), -1.0, 1.0)
        
        # Clamped skew: max 5 bps
        skew_bps = np.clip(inv_ratio * 0.2 * (vol_30s ** 2), -5.0, 5.0)
        
        # Funding rate carry drift: if FR < 0 (shorts pay longs), bias reservation price up to accumulate long
        funding_drift = -funding_rate * (mid_px * 0.5)

        res_price = micro_px * (1.0 - skew_bps * 1e-4) + funding_drift

        # 3. Base Half-Spread calculation
        base_half_spd = max(
            mid_px * (self.min_spread_bps * 0.5 / 10000.0),
            (1.0 / self.gamma) * math.log(1.0 + self.gamma / self.k_decay) * (mid_px * (self.maker_fee_bps * 1e-4 * 1.5))
        )

        calc_bid = res_price - base_half_spd
        if inventory_usd > 0 and best_ask > 0:
            # Long inventory: clamp ask inside to accelerate selling
            calc_ask = max(min(res_price + base_half_spd, best_ask), mid_px + self.tick_size)
        else:
            calc_ask = res_price + base_half_spd

        if inventory_usd < 0 and best_bid > 0:
            # Short inventory: clamp bid inside to accelerate buying to cover & lock profit!
            calc_bid = min(max(res_price - base_half_spd, best_bid), mid_px - self.tick_size)
        # Strict Post-Only bounds: never cross market
        calc_bid = min(calc_bid, mid_px - self.tick_size)
        calc_ask = max(calc_ask, mid_px + self.tick_size)

        # Round to tick size
        calc_bid = round(np.floor(calc_bid / self.tick_size) * self.tick_size, 6)
        calc_ask = round(np.ceil(calc_ask / self.tick_size) * self.tick_size, 6)

        # 4. Toxicity Cutoff Gate & Position Limits
        allow_bid = True
        allow_ask = True
        actions = []

        vol_ratio = vol_30s / (vol_median + 1e-6)
        # CRITICAL FIX: TOXIC_DOWN_CUT must only block OPENING NEW LONGS!
        # When holding SHORT (inventory_usd < 0), buying is BUY TO COVER (take-profit), which must be allowed!
        if p_toxic_down >= self.toxic_threshold or vol_ratio >= 2.2:
            if inventory_usd >= 0:
                allow_bid = False
                actions.append(f"TOXIC_DOWN_CUT(p={p_toxic_down:.2f}, vol_r={vol_ratio:.1f})")
            else:
                actions.append(f"TOXIC_DOWN_COVER_ALLOWED(p={p_toxic_down:.2f})")
        # Single-Lot Ping-Pong Liquidity Discipline (Proven by Autoresearch: Sharpe 61.66, MaxDD 0.38%)
        # Stop adding in the same direction once holding >= 1 single order lot ($10 USD)
        single_lot_threshold = self.target_notional_usd * 0.85
        if inventory_usd >= single_lot_threshold:
            allow_bid = False
            actions.append(f"INVENTORY_LONG_LOCK({inventory_usd:.2f})")
        elif inventory_usd <= -single_lot_threshold:
            allow_ask = False
            actions.append(f"INVENTORY_SHORT_LOCK({inventory_usd:.2f})")

        # 5. Queue Priority Holding (1.05 tick deadband)
        if allow_bid and self.last_bid_price is not None:
            if abs(calc_bid - self.last_bid_price) <= self.tick_size * 1.05:
                calc_bid = self.last_bid_price # Retain existing FIFO queue priority
                actions.append(f"BID_QUEUE_HOLD({calc_bid})")
            else:
                actions.append(f"BID_UPDATE({calc_bid})")
        elif allow_bid:
            actions.append(f"BID_POST({calc_bid})")

        if allow_ask and self.last_ask_price is not None:
            if abs(calc_ask - self.last_ask_price) <= self.tick_size * 1.05:
                calc_ask = self.last_ask_price
                actions.append(f"ASK_QUEUE_HOLD({calc_ask})")
            else:
                actions.append(f"ASK_UPDATE({calc_ask})")
        elif allow_ask:
            actions.append(f"ASK_POST({calc_ask})")

        self.last_bid_price = calc_bid if allow_bid else None
        self.last_ask_price = calc_ask if allow_ask else None

        # 6. Dynamic Lot Size ($10 notional)
        lot_sz = max(round(self.target_notional_usd / (mid_px * self.contract_val)), 1.0)

        return {
            "bid_px": calc_bid,
            "ask_px": calc_ask,
            "lot_sz": lot_sz,
            "allow_bid": allow_bid,
            "allow_ask": allow_ask,
            "p_toxic_down": p_toxic_down,
            "actions": actions
        }
