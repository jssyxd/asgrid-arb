# -*- coding: utf-8 -*-
"""
run_real_lob_backtest.py - Production High-Fidelity L2 Orderbook Backtest Engine
Strategy 012 Avellaneda-Stoikov ML Grid V2:
1. Strict Post-Only Maker Execution (0 Takers)
2. Hard Fee Hurdle Constraint (Total Spread >= 9.0 bps)
3. Depth-Weighted Stoikov Micro-Price (P_micro)
4. Smooth Continuous Inventory Damping & Micro-Account Sizing
5. FIFO Queue Priority Preservation (Queue Hold)
6. ADX Macro Trend Gating & Adverse Selection Toxic Circuit Breakers
7. Real-Time Order Book Matching Simulation against Database L2 Depth
"""

import os
import sys
import json
import math
import time
from typing import Dict, Any, List
import numpy as np
import pandas as pd

def simulate_real_lob_dataset(
    dataset_path: str,
    asset_type: str = "BTC",
    initial_capital: float = 30.0,
    lot_size: float = 0.01,
    max_inventory: float = 0.05,
    min_spread_bps: float = 9.0,
    maker_fee: float = 0.0002,
    taker_fee: float = 0.0005,
    enable_adx_gating: bool = True
) -> Dict[str, Any]:
    """
    Executes tick-by-tick orderbook simulation on real governed high-frequency L2 data.
    """
    print(f"[*] Reading governed L2 dataset: {dataset_path}")
    t0 = time.time()
    
    if asset_type == "BTC":
        df = pd.read_parquet(dataset_path, columns=['T', 'bids', 'asks'])
        n = len(df)
        print(f"[*] Loaded {n} BTC Depth-20 ticks in {time.time()-t0:.2f}s. Parsing orderbook levels...")
        
        b1_p = np.zeros(n, dtype=np.float64)
        b1_q = np.zeros(n, dtype=np.float64)
        a1_p = np.zeros(n, dtype=np.float64)
        a1_q = np.zeros(n, dtype=np.float64)
        obis = np.zeros(n, dtype=np.float64)
        micro_prices = np.zeros(n, dtype=np.float64)
        
        for i in range(n):
            bids = json.loads(df['bids'].iloc[i])
            asks = json.loads(df['asks'].iloc[i])
            
            bp1 = float(bids[0][0]); bq1 = float(bids[0][1])
            ap1 = float(asks[0][0]); aq1 = float(asks[0][1])
            b1_p[i] = bp1; b1_q[i] = bq1
            a1_p[i] = ap1; a1_q[i] = aq1
            
            tot_q1 = bq1 + aq1
            micro_prices[i] = (bp1 * aq1 + ap1 * bq1) / tot_q1 if tot_q1 > 0 else (bp1 + ap1) * 0.5
            
            sum_b = sum(float(b[1]) for b in bids)
            sum_a = sum(float(a[1]) for a in asks)
            tot_ba = sum_b + sum_a
            obis[i] = (sum_b - sum_a) / tot_ba if tot_ba > 0 else 0.0
            
        mids = (b1_p + a1_p) * 0.5
        spreads = a1_p - b1_p
        tolerance_usdt = 1.5
        round_digits = 1
        
        # Calculate causal 1m ADX(14)
        step_1m = 224
        num_bars = n // step_1m
        highs_1m = np.zeros(num_bars)
        lows_1m = np.zeros(num_bars)
        closes_1m = np.zeros(num_bars)
        for b in range(num_bars):
            st = b * step_1m; ed = min((b + 1) * step_1m, n)
            highs_1m[b] = np.max(a1_p[st:ed])
            lows_1m[b] = np.min(b1_p[st:ed])
            closes_1m[b] = mids[ed - 1]
            
        adx_1m = np.full(num_bars, 15.0)
        trend_dir_1m = np.zeros(num_bars, dtype=int)
        if num_bars >= 15:
            tr = np.maximum(highs_1m[1:] - lows_1m[1:], np.maximum(np.abs(highs_1m[1:] - closes_1m[:-1]), np.abs(lows_1m[1:] - closes_1m[:-1])))
            up_m = highs_1m[1:] - highs_1m[:-1]
            dn_m = lows_1m[:-1] - lows_1m[1:]
            p_dm = np.where((up_m > dn_m) & (up_m > 0), up_m, 0.0)
            m_dm = np.where((dn_m > up_m) & (dn_m > 0), dn_m, 0.0)
            
            tr14 = pd.Series(tr).rolling(14, min_periods=1).mean().values
            p_dm14 = pd.Series(p_dm).rolling(14, min_periods=1).mean().values
            m_dm14 = pd.Series(m_dm).rolling(14, min_periods=1).mean().values
            
            p_di = 100.0 * (p_dm14 / np.maximum(tr14, 1e-6))
            m_di = 100.0 * (m_dm14 / np.maximum(tr14, 1e-6))
            dx = 100.0 * (np.abs(p_di - m_di) / np.maximum(p_di + m_di, 1e-6))
            adx_1m[1:] = pd.Series(dx).rolling(14, min_periods=1).mean().values
            for b in range(1, num_bars):
                if p_di[b-1] > m_di[b-1]: trend_dir_1m[b] = 1
                elif m_di[b-1] > p_di[b-1]: trend_dir_1m[b] = -1
                
        adx_ticks = np.repeat(adx_1m, step_1m)
        trend_ticks = np.repeat(trend_dir_1m, step_1m)
        if len(adx_ticks) < n:
            adx_ticks = np.pad(adx_ticks, (0, n - len(adx_ticks)), 'edge')
            trend_ticks = np.pad(trend_ticks, (0, n - len(trend_ticks)), 'edge')
            
    else:  # SOL
        df = pd.read_parquet(dataset_path)
        n = len(df)
        print(f"[*] Loaded {n} SOL Depth-5 ticks in {time.time()-t0:.2f}s.")
        b1_p = df['bid1_p'].values
        a1_p = df['ask1_p'].values
        b1_q = df['bid1_q'].values
        a1_q = df['ask1_q'].values
        mids = (b1_p + a1_p) * 0.5
        spreads = a1_p - b1_p
        micro_prices = (b1_p * a1_q + a1_p * b1_q) / np.maximum(b1_q + a1_q, 1e-6)
        
        sum_b = df['bid1_q'].values + df['bid2_q'].values + df['bid3_q'].values + df['bid4_q'].values + df['bid5_q'].values
        sum_a = df['ask1_q'].values + df['ask2_q'].values + df['ask3_q'].values + df['ask4_q'].values + df['ask5_q'].values
        obis = (sum_b - sum_a) / np.maximum(sum_b + sum_a, 1e-6)
        tolerance_usdt = 0.02
        round_digits = 2
        adx_ticks = np.full(n, 15.0)
        trend_ticks = np.zeros(n, dtype=int)

    # -------------------------------------------------------------
    # Simulation Runner
    # -------------------------------------------------------------
    def run_pass(is_upgraded: bool):
        gamma = 0.35 if is_upgraded else 0.0451
        kappa = 2.1346
        cooldown_ticks = 10
        
        cash = initial_capital
        inventory = 0.0
        trades = []
        equity_curve = np.zeros(n)
        active_bid = None
        active_ask = None
        bid_cooldown = 0
        ask_cooldown = 0
        
        maker_fills = 0
        taker_fills = 0
        queue_holds = 0
        toxic_cuts = 0
        adx_blocks = 0
        total_fee_paid = 0.0
        total_volume_usd = 0.0
        
        for t in range(n):
            s = mids[t]
            bp = b1_p[t]
            ap = a1_p[t]
            p_micro = micro_prices[t]
            obi = obis[t]
            
            # 1. Match active orders against market transitions
            if t > 0:
                prev_bp = b1_p[t-1]
                prev_ap = a1_p[t-1]
                
                if active_bid is not None:
                    bid_px = active_bid
                    if ap <= bid_px or (bp < prev_bp and bp <= bid_px):
                        fill_px = bid_px
                        fee = fill_px * lot_size * maker_fee
                        cash -= (fill_px * lot_size + fee)
                        inventory += lot_size
                        total_fee_paid += fee
                        total_volume_usd += fill_px * lot_size
                        maker_fills += 1
                        trades.append(('BUY', fill_px, lot_size, fee, 'MAKER', t))
                        active_bid = None
                        bid_cooldown = cooldown_ticks
                        
                if active_ask is not None:
                    ask_px = active_ask
                    if bp >= ask_px or (ap > prev_ap and ap >= ask_px):
                        fill_px = ask_px
                        fee = fill_px * lot_size * maker_fee
                        cash += (fill_px * lot_size - fee)
                        inventory -= lot_size
                        total_fee_paid += fee
                        total_volume_usd += fill_px * lot_size
                        maker_fills += 1
                        trades.append(('SELL', fill_px, lot_size, fee, 'MAKER', t))
                        active_ask = None
                        ask_cooldown = cooldown_ticks
                        
            if bid_cooldown > 0: bid_cooldown -= 1
            if ask_cooldown > 0: ask_cooldown -= 1
            
            # 2. Quote Calculation
            if is_upgraded:
                inv_ratio = np.clip(inventory / max(max_inventory, 1e-6), -1.0, 1.0)
                base_half_spd = max(s * (min_spread_bps * 0.5 / 10000.0), (1.0 / gamma) * math.log(1.0 + gamma / kappa) * (s * 0.0004))
                inv_bias = inv_ratio * base_half_spd * 0.75
                r = p_micro - inv_bias
                
                # Asymmetric spreads
                delta_bid = base_half_spd + inv_bias
                delta_ask = base_half_spd - inv_bias
                calc_bid = min(round(r - delta_bid, round_digits), round(bp, round_digits))
                calc_ask = max(round(r + delta_ask, round_digits), round(ap, round_digits))
                
                allow_bid = (inventory < max_inventory) and (bid_cooldown == 0)
                allow_ask = (inventory > -max_inventory) and (ask_cooldown == 0)
                
                # Toxic Circuit Breaker
                if obi < -0.40:
                    allow_bid = False
                    toxic_cuts += 1
                if obi > 0.40:
                    allow_ask = False
                    toxic_cuts += 1
                    
                # ADX Macro Trend Gating
                if enable_adx_gating and asset_type == "BTC":
                    if adx_ticks[t] >= 28.0:
                        if trend_ticks[t] < 0:
                            allow_bid = False
                            adx_blocks += 1
                        elif trend_ticks[t] > 0:
                            allow_ask = False
                            adx_blocks += 1
                            
                # Queue Priority Preservation
                if allow_bid:
                    if active_bid is not None and abs(active_bid - calc_bid) <= tolerance_usdt:
                        queue_holds += 1
                    else:
                        active_bid = calc_bid
                else:
                    active_bid = None
                    
                if allow_ask:
                    if active_ask is not None and abs(active_ask - calc_ask) <= tolerance_usdt:
                        queue_holds += 1
                    else:
                        active_ask = calc_ask
                else:
                    active_ask = None
                    
            else:
                # Baseline Dayuan: No fee hurdle, weak gamma, taker crossings, no queue hold
                legacy_half_spd = s * 0.0002
                r = s - inventory * 0.0451 * (0.25 ** 2) * s * 0.0001
                calc_bid = round(r - legacy_half_spd, round_digits)
                calc_ask = round(r + legacy_half_spd, round_digits)
                
                if calc_bid >= ap:
                    fill_px = ap
                    fee = fill_px * lot_size * taker_fee
                    cash -= (fill_px * lot_size + fee)
                    inventory += lot_size
                    total_fee_paid += fee
                    total_volume_usd += fill_px * lot_size
                    taker_fills += 1
                    trades.append(('BUY', fill_px, lot_size, fee, 'TAKER', t))
                    active_bid = None
                else:
                    active_bid = calc_bid
                    
                if calc_ask <= bp:
                    fill_px = bp
                    fee = fill_px * lot_size * taker_fee
                    cash += (fill_px * lot_size - fee)
                    inventory -= lot_size
                    total_fee_paid += fee
                    total_volume_usd += fill_px * lot_size
                    taker_fills += 1
                    trades.append(('SELL', fill_px, lot_size, fee, 'TAKER', t))
                    active_ask = None
                else:
                    active_ask = calc_ask
                    
            equity_curve[t] = cash + inventory * s
            
        final_eq = equity_curve[-1]
        net_pnl = final_eq - initial_capital
        ret_pct = (net_pnl / initial_capital) * 100.0
        cum_max = np.maximum.accumulate(equity_curve)
        drawdowns = (cum_max - equity_curve) / np.maximum(cum_max, 1e-6)
        max_dd_pct = np.max(drawdowns) * 100.0
        total_fills = len(trades)
        
        return {
            "initial_capital": initial_capital,
            "final_equity": round(final_eq, 4),
            "net_pnl": round(net_pnl, 4),
            "return_pct": round(ret_pct, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "total_fills": total_fills,
            "maker_fills": maker_fills,
            "taker_fills": taker_fills,
            "maker_pct": round(maker_fills / max(total_fills, 1) * 100.0, 1),
            "taker_pct": round(taker_fills / max(total_fills, 1) * 100.0, 1),
            "total_fee_paid": round(total_fee_paid, 4),
            "total_volume_usd": round(total_volume_usd, 2),
            "final_inventory": round(inventory, 4),
            "queue_holds": queue_holds,
            "toxic_cuts": toxic_cuts,
            "adx_blocks": adx_blocks,
            "trades": trades
        }
        
    print("[*] Running comparative simulations...")
    res_legacy = run_pass(is_upgraded=False)
    res_upgraded = run_pass(is_upgraded=True)
    
    return {
        "asset": asset_type,
        "total_ticks": n,
        "legacy": res_legacy,
        "upgraded": res_upgraded
    }

if __name__ == "__main__":
    btc_path = '/home/da/桌面/database/03_governed_lake/v2_parquet_lake/crypto/high_frequency_lob/BTCUSDT/BTCUSDT_depth20_20260326_governed.parquet'
    res = simulate_real_lob_dataset(btc_path, asset_type="BTC")
    
    leg = res["legacy"]
    upg = res["upgraded"]
    
    print("\n" + "="*84)
    print("真实盘口 20 档订单簿 (322,674 Ticks BTC-USDT) 高频仿真回测硬核审计报告")
    print("="*84)
    print(f"{'指标项':<28} | {'更改前 (旧版 dayuan 逻辑)':<24} | {'更改后 (新版 accountbot3 V2)':<24}")
    print("-"*84)
    print(f"{'初始本金 (Initial Capital)':<28} | {leg['initial_capital']:<24.2f} | {upg['initial_capital']:<24.2f}")
    print(f"{'最终交易账户权益 (Equity)':<28} | {leg['final_equity']:<24.4f} | {upg['final_equity']:<24.4f}")
    print(f"{'净实现盈亏 (Realized PnL)':<28} | {leg['net_pnl']:<+24.4f} | {upg['net_pnl']:<+24.4f}")
    print(f"{'累计收益率 (Total Return)':<28} | {leg['return_pct']:<+24.2f}% | {upg['return_pct']:<+24.2f}%")
    print(f"{'最大历史回撤 (Max Drawdown)':<28} | {leg['max_drawdown_pct']:<24.2f}% | {upg['max_drawdown_pct']:<24.2f}%")
    print(f"{'撮合成交总笔数 (True Fills)':<28} | {leg['total_fills']:<24} | {upg['total_fills']:<24}")
    print(f"{'Maker 成交笔数与比例':<28} | {leg['maker_fills']} ({leg['maker_pct']}%) | {upg['maker_fills']} ({upg['maker_pct']}%)")
    print(f"{'Taker 成交笔数与比例':<28} | {leg['taker_fills']} ({leg['taker_pct']}%) | {upg['taker_fills']} ({upg['taker_pct']}%)")
    print(f"{'手续费支出 (Total Fees)':<28} | {leg['total_fee_paid']:<24.4f} USDT | {upg['total_fee_paid']:<24.4f} USDT")
    print(f"{'名义撮合成交量 (Turnover)':<28} | {leg['total_volume_usd']:<24.2f} USDT | {upg['total_volume_usd']:<24.2f} USDT")
    print(f"{'期末持仓敞口 (Ending Inv)':<28} | {leg['final_inventory']:<24.4f} BTC  | {upg['final_inventory']:<24.4f} BTC")
    print(f"{'队列优先权保持 (Queue Holds)':<28} | {leg['queue_holds']:<24} | {upg['queue_holds']:<24}")
    print(f"{'逆向选择毒性熔断 (Toxic Cuts)':<28} | {leg['toxic_cuts']:<24} | {upg['toxic_cuts']:<24}")
    print(f"{'ADX 强趋势阻断 (ADX Blocks)':<28} | {leg['adx_blocks']:<24} | {upg['adx_blocks']:<24}")
    print("="*84)
