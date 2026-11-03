# -*- coding: utf-8 -*-
"""
OrderBook Depth Sentinel & Liquidity Gatekeeper (盘口深度哨兵与流动性门禁)
Adapted from institutional crypto market-making frameworks (mg-market-maker & TickScope).
Compliant with https://github.com/jssyxd/quant-research-constitution standards.
"""

import math
from typing import Dict, Any, List, Tuple

class OrderBookDepthSentinel:
    """
    Microstructure Depth Sentinel:
    Enforces pre-trade liquidity hurdle and post-trade inventory protection.
    1. Pre-trade hurdle: Top-5 depth must be >= min_depth_usd ($1,500 USD) to quote.
    2. Dynamic hurdle: Top-5 depth must be >= 20x current inventory notional.
    3. Slippage protection: Prevents market-order suicide during book collapse.
    """

    def __init__(
        self,
        min_depth_usd: float = 1500.0,
        inventory_depth_ratio: float = 20.0,
        depth_levels: int = 5,
        panic_depth_usd: float = 500.0
    ):
        self.min_depth_usd = min_depth_usd
        self.inventory_depth_ratio = inventory_depth_ratio
        self.depth_levels = depth_levels
        self.panic_depth_usd = panic_depth_usd
        self.last_bid_depth_usd = 0.0
        self.last_ask_depth_usd = 0.0

    def evaluate_depth_from_book(
        self,
        bids: List[Tuple[float, float]], # List of (price, size_contracts)
        asks: List[Tuple[float, float]], # List of (price, size_contracts)
        contract_val: float
    ) -> Dict[str, float]:
        """
        Calculates cumulative notional USD for top N levels.
        """
        # Crossed Book Circuit Breaker
        if bids and asks and float(bids[0][0]) >= float(asks[0][0]):
            return {
                "bid_depth_usd": 0.0,
                "ask_depth_usd": 0.0,
                "total_top5_usd": 0.0,
                "min_side_usd": 0.0,
                "is_crossed": True
            }

        bid_depth_usd = 0.0
        for px, sz in bids[:self.depth_levels]:
            bid_depth_usd += float(px) * float(sz) * contract_val

        ask_depth_usd = 0.0
        for px, sz in asks[:self.depth_levels]:
            ask_depth_usd += float(px) * float(sz) * contract_val

        self.last_bid_depth_usd = bid_depth_usd
        self.last_ask_depth_usd = ask_depth_usd
        total_top5_usd = bid_depth_usd + ask_depth_usd
        min_side_usd = min(bid_depth_usd, ask_depth_usd)

        return {
            "bid_depth_usd": round(bid_depth_usd, 2),
            "ask_depth_usd": round(ask_depth_usd, 2),
            "total_top5_usd": round(total_top5_usd, 2),
            "min_side_usd": round(min_side_usd, 2),
            "is_crossed": False
        }

    def check_liquidity_gate(
        self,
        bid_depth_usd: float,
        ask_depth_usd: float,
        inventory_usd: float,
        mid_px: float = 0.0,
        avg_vol_4h_sec: float = 0.0
    ) -> Dict[str, Any]:
        """
        Gatekeeper check:
        Returns:
            allow_quote: bool (whether normal market making orders are allowed)
            action: str ('NORMAL', 'DEPTH_INSUFFICIENT_HALT', 'PANIC_DRAIN_EXIT')
            reason: str
        """
        min_side = min(bid_depth_usd, ask_depth_usd)
        abs_inv_usd = abs(inventory_usd)

        # Dynamic required depth: max(1500, inventory * 20, 4h_vol_per_sec * 15)
        required_depth = max(
            self.min_depth_usd,
            abs_inv_usd * self.inventory_depth_ratio,
            avg_vol_4h_sec * 15.0
        )

        # Case 1: Extreme Liquidity Drain / Vacuum
        if min_side < self.panic_depth_usd:
            return {
                "allow_quote": False,
                "allow_open": False,
                "action": "PANIC_DRAIN_SHUTDOWN",
                "required_depth_usd": round(required_depth, 2),
                "current_min_depth_usd": round(min_side, 2),
                "reason": f"Depth collapsed below emergency panic floor (${min_side:.1f} < ${self.panic_depth_usd:.1f})"
            }

        # Case 2: Insufficient Depth for safe market making
        if min_side < required_depth:
            return {
                "allow_quote": False,
                "allow_open": False,
                "action": "DEPTH_INSUFFICIENT_HALT",
                "required_depth_usd": round(required_depth, 2),
                "current_min_depth_usd": round(min_side, 2),
                "reason": f"Top-5 depth insufficient (${min_side:.1f} < required ${required_depth:.1f})"
            }

        # Case 3: Fully healthy
        return {
            "allow_quote": True,
            "allow_open": True,
            "action": "HEALTHY",
            "required_depth_usd": round(required_depth, 2),
            "current_min_depth_usd": round(min_side, 2),
            "reason": f"Top-5 depth healthy (${min_side:.1f} >= ${required_depth:.1f})"
        }
