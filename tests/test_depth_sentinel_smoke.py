# -*- coding: utf-8 -*-
"""
Smoke Test & Rigorous Verification Suite for OrderBook Depth Sentinel Gatekeeper
"""
import sys
import os
import unittest

sys.path.append(os.path.abspath("asgrid-arb/asgrid-arb-main/strategies_live/shared"))
from depth_sentinel import OrderBookDepthSentinel
from robust_glft_engine import RobustGLFTQuotingEngine

class TestOrderBookDepthSentinel(unittest.TestCase):
    def setUp(self):
        self.sentinel = OrderBookDepthSentinel(
            min_depth_usd=1500.0,
            inventory_depth_ratio=20.0,
            depth_levels=5,
            panic_depth_usd=500.0
        )
        self.engine = RobustGLFTQuotingEngine(
            symbol="TEST-USDT-SWAP",
            tick_size=0.0001,
            contract_val=10.0,
            maker_fee_bps=2.0,
            min_spread_bps=10.0,
            min_depth_usd=1500.0,
            panic_depth_usd=500.0
        )

    def test_depth_calculation_from_book(self):
        # 5 levels of bids and asks
        # Price 1.0, 50 contracts each level. Contract val = 10.0 -> Each level is 50 * 1.0 * 10 = $500 USD
        # Top-5 total per side = 5 * $500 = $2,500 USD
        bids = [(1.0 - i * 0.0001, 50.0) for i in range(1, 10)]
        asks = [(1.0 + i * 0.0001, 50.0) for i in range(1, 10)]
        
        eval_res = self.sentinel.evaluate_depth_from_book(bids, asks, contract_val=10.0)
        self.assertAlmostEqual(eval_res["bid_depth_usd"], 2499.0, delta=5.0)
        self.assertAlmostEqual(eval_res["ask_depth_usd"], 2501.0, delta=5.0)
        self.assertAlmostEqual(eval_res["min_side_usd"], 2499.0, delta=5.0)

    def test_healthy_depth_allows_quoting(self):
        # Healthy depth: $2,500 on both sides, inventory $10
        gate = self.sentinel.check_liquidity_gate(
            bid_depth_usd=2500.0,
            ask_depth_usd=2400.0,
            inventory_usd=10.0
        )
        self.assertTrue(gate["allow_quote"])
        self.assertEqual(gate["action"], "HEALTHY")

        # Engine quote generation
        res = self.engine.compute_quotes(
            mid_px=1.0,
            micro_px=1.0,
            inventory_contracts=0.0,
            vol_30s=0.50,
            ofi_1s=0.0, ofi_5s=0.0, ofi_30s=0.0, obi=0.0,
            volume=10.0, trade_count=5.0, net_flow=0.0,
            top5_bid_depth_usd=2500.0,
            top5_ask_depth_usd=2400.0
        )
        self.assertTrue(res["allow_bid"])
        self.assertTrue(res["allow_ask"])
        self.assertIn("HEALTHY", str(res["depth_gate"]))

    def test_insufficient_depth_intercepts_quotes(self):
        # Thin depth: $800 USD (< $1,500 hurdle)
        gate = self.sentinel.check_liquidity_gate(
            bid_depth_usd=800.0,
            ask_depth_usd=2000.0,
            inventory_usd=0.0
        )
        self.assertFalse(gate["allow_quote"])
        self.assertEqual(gate["action"], "DEPTH_INSUFFICIENT_HALT")

        # Engine must block both bid and ask
        res = self.engine.compute_quotes(
            mid_px=1.0,
            micro_px=1.0,
            inventory_contracts=0.0,
            vol_30s=0.50,
            ofi_1s=0.0, ofi_5s=0.0, ofi_30s=0.0, obi=0.0,
            volume=10.0, trade_count=5.0, net_flow=0.0,
            top5_bid_depth_usd=800.0,
            top5_ask_depth_usd=2000.0
        )
        self.assertFalse(res["allow_bid"])
        self.assertFalse(res["allow_ask"])
        self.assertTrue(any("DEPTH_GATE_HALT" in a for a in res["actions"]))

    def test_dynamic_inventory_hurdle(self):
        # Base hurdle is $1,500.
        # But if inventory is $100 USD, required depth = 100 * 20 = $2,000 USD!
        # If current depth is $1,800, it passes static $1,500 but FAILS dynamic $2,000!
        gate = self.sentinel.check_liquidity_gate(
            bid_depth_usd=1800.0,
            ask_depth_usd=1800.0,
            inventory_usd=100.0
        )
        self.assertFalse(gate["allow_quote"])
        self.assertEqual(gate["action"], "DEPTH_INSUFFICIENT_HALT")
        self.assertEqual(gate["required_depth_usd"], 2000.0)

    def test_panic_drain_shutdown(self):
        # If depth collapses to < $500 (e.g. $300), trigger panic drain shutdown
        gate = self.sentinel.check_liquidity_gate(
            bid_depth_usd=300.0,
            ask_depth_usd=300.0,
            inventory_usd=0.0
        )
        self.assertFalse(gate["allow_quote"])
        self.assertEqual(gate["action"], "PANIC_DRAIN_SHUTDOWN")

    def test_empty_book_resilience(self):
        eval_res = self.sentinel.evaluate_depth_from_book([], [], contract_val=10.0)
        self.assertEqual(eval_res["min_side_usd"], 0.0)
        gate = self.sentinel.check_liquidity_gate(0.0, 0.0, 0.0)
        self.assertFalse(gate["allow_quote"])
        self.assertEqual(gate["action"], "PANIC_DRAIN_SHUTDOWN")

    def test_zero_depth_book_collapse_intercepted(self):
        # Even if feed gives 0.0 and 0.0 (total book wipeout), compute_quotes must HALT!
        res = self.engine.compute_quotes(
            mid_px=1.0,
            micro_px=1.0,
            inventory_contracts=0.0,
            vol_30s=0.50,
            ofi_1s=0.0, ofi_5s=0.0, ofi_30s=0.0, obi=0.0,
            volume=10.0, trade_count=5.0, net_flow=0.0,
            top5_bid_depth_usd=0.0,
            top5_ask_depth_usd=0.0
        )
        self.assertFalse(res["allow_bid"])
        self.assertFalse(res["allow_ask"])
        self.assertEqual(res["depth_gate"]["action"], "PANIC_DRAIN_SHUTDOWN")

    def test_crossed_book_circuit_breaker(self):
        # Best bid (1.05) > Best ask (1.00) -> Crossed book anomaly
        bids = [(1.05, 10.0)]
        asks = [(1.00, 10.0)]
        eval_res = self.sentinel.evaluate_depth_from_book(bids, asks, contract_val=10.0)
        self.assertTrue(eval_res["is_crossed"])
        self.assertEqual(eval_res["min_side_usd"], 0.0)

    def test_soft_exit_holding_long_allows_ask_blocks_bid(self):
        # Depth $1,000 is between $500 panic and $1,500 hurdle
        # Holding long inventory: 1 contract * 10 ctVal * 1.0 px = $10 USD
        res = self.engine.compute_quotes(
            mid_px=1.0,
            micro_px=1.0,
            inventory_contracts=1.0,
            vol_30s=0.50,
            ofi_1s=0.0, ofi_5s=0.0, ofi_30s=0.0, obi=0.0,
            volume=10.0, trade_count=5.0, net_flow=0.0,
            best_bid=0.9999, best_ask=1.0001,
            top5_bid_depth_usd=1000.0,
            top5_ask_depth_usd=1000.0
        )
        self.assertFalse(res["allow_bid"]) # Block new buys
        self.assertTrue(res["allow_ask"])  # Allow post-only ask to sell/reduce inventory
        self.assertTrue(any("SOFT_EXIT" in a for a in res["actions"]))

    def test_soft_exit_holding_short_allows_bid_blocks_ask(self):
        # Holding short inventory: -1 contract = -$10 USD
        res = self.engine.compute_quotes(
            mid_px=1.0,
            micro_px=1.0,
            inventory_contracts=-1.0,
            vol_30s=0.50,
            ofi_1s=0.0, ofi_5s=0.0, ofi_30s=0.0, obi=0.0,
            volume=10.0, trade_count=5.0, net_flow=0.0,
            best_bid=0.9999, best_ask=1.0001,
            top5_bid_depth_usd=1000.0,
            top5_ask_depth_usd=1000.0
        )
        self.assertTrue(res["allow_bid"])   # Allow post-only bid to buy-to-cover
        self.assertFalse(res["allow_ask"])  # Block new sells
        self.assertTrue(any("SOFT_EXIT" in a for a in res["actions"]))

    def test_panic_drain_blocks_all_even_with_inventory(self):
        # Depth collapses to $300 (< $500 floor), holding +$10 USD
        res = self.engine.compute_quotes(
            mid_px=1.0,
            micro_px=1.0,
            inventory_contracts=1.0,
            vol_30s=0.50,
            ofi_1s=0.0, ofi_5s=0.0, ofi_30s=0.0, obi=0.0,
            volume=10.0, trade_count=5.0, net_flow=0.0,
            top5_bid_depth_usd=300.0,
            top5_ask_depth_usd=300.0
        )
        self.assertFalse(res["allow_bid"])
        self.assertFalse(res["allow_ask"])
        self.assertTrue(any("DEPTH_PANIC_SHUTDOWN" in a for a in res["actions"]))

if __name__ == "__main__":
    unittest.main()
