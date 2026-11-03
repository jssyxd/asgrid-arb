# -*- coding: utf-8 -*-
"""
Production NautilusTrader Live Service V2 for RECALL-USDT-SWAP (dayuan)
Powered by Robust GLFT Quoting Engine + Dedicated LightGBM Toxicity Gate
Compliant with https://github.com/jssyxd/quant-research-constitution
"""

import socket
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _ipv4_getaddrinfo

import os
import sys
import time
import json
import signal
import numpy as np
from datetime import datetime, timezone

SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED_DIR = os.path.abspath(os.path.join(SERVICE_DIR, "../shared"))
REPO_DIR = os.path.abspath(os.path.join(SERVICE_DIR, "../.."))
sys.path.insert(0, SHARED_DIR)
sys.path.insert(0, REPO_DIR)
sys.path.insert(0, "/opt/nautilus_cluster/shared")
sys.path.insert(0, "/opt/nautilus_cluster")

from gateway_okx_client import OKXGatewayClient
from okx_ws_manager import OKXWebSocketManager
from robust_glft_engine import RobustGLFTQuotingEngine

CONFIG_FILE = os.path.join(SERVICE_DIR, "config/dayuan_credentials.env")
LOG_DIR = os.path.join(SERVICE_DIR, "logs")
STATUS_FILE = os.path.join(LOG_DIR, "dayuan_status.json")
LOG_FILE = os.path.join(LOG_DIR, "dayuan_runtime.log")
MODEL_FILE = os.path.join(REPO_DIR, "models_v2/lgbm_toxicity_gate_RECALL.txt")
if not os.path.exists(MODEL_FILE):
    MODEL_FILE = "/opt/nautilus_cluster/models_v2/lgbm_toxicity_gate_RECALL.txt"

os.makedirs(LOG_DIR, exist_ok=True)

def load_credentials():
    creds = {
        "OKX_API_KEY": "776e25a5-be71-4c71-a183-ac8859789cfd",
        "OKX_API_SECRET": "E96F1B17DBD38ADFBD4C719E3231C124",
        "OKX_API_PASSPHRASE": "Auto111.",
        "OKX_SIMULATED_TRADING": "0",
        "INST_ID": "RECALL-USDT-SWAP",
        "MIN_SPREAD_BPS": "14.0",
        "TARGET_NOTIONAL_USD": "10.0",
        "MAX_NOTIONAL_USD": "45.0"
    }
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    creds[k.strip()] = v.strip().strip('"').strip("'")
    return creds

def log_msg(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] [dayuan_RECALL_V2] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

running = True
def handle_shutdown(signum, frame):
    global running
    log_msg("Received shutdown signal. Stopping gracefully...")
    running = False

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

def main():
    log_msg("=== Starting NautilusTrader RECALL-USDT-SWAP V2 (dayuan) Production Service ===")
    creds = load_credentials()
    simulated = (creds.get("OKX_SIMULATED_TRADING", "0") == "1")
    inst_id = creds.get("INST_ID", "RECALL-USDT-SWAP")

    client = OKXGatewayClient(
        api_key=creds["OKX_API_KEY"],
        api_secret=creds["OKX_API_SECRET"],
        passphrase=creds["OKX_API_PASSPHRASE"],
        simulated=simulated
    )

    bal = client.get_balance("USDT")
    avail_bal = float(bal.get("availBal", bal.get("cashBal", 0)))
    log_msg(f"Connected to OKX {'Demo' if simulated else 'Real'}. Available Capital: {avail_bal} USDT")

    ws_mgr = OKXWebSocketManager(
        api_key=creds["OKX_API_KEY"],
        api_secret=creds["OKX_API_SECRET"],
        passphrase=creds["OKX_API_PASSPHRASE"],
        inst_id=inst_id
    )
    log_msg(f"Starting OKX WebSocket streams for {inst_id}...")
    ws_mgr.start()

    inventory = 0.0
    init_positions = client.get_positions(inst_type="SWAP", inst_id=inst_id)
    if init_positions:
        inventory = float(init_positions[0].get("pos", 0))
        log_msg(f"Synced initial live position: {inventory} contracts")

    # Instrument: tick size 0.00001, ctVal 10.0 RECALL
    engine = RobustGLFTQuotingEngine(
        symbol=inst_id,
        tick_size=0.00001,
        contract_val=10.0,
        model_path=MODEL_FILE,
        maker_fee_bps=2.0,
        min_spread_bps=float(creds.get("MIN_SPREAD_BPS", 14.0)),
        target_notional_usd=float(creds.get("TARGET_NOTIONAL_USD", 10.0)),
        max_notional_usd=float(creds.get("MAX_NOTIONAL_USD", 45.0)),
        toxic_threshold=0.65,
        min_depth_usd=float(creds.get("MIN_DEPTH_USD", 1500.0)),
        panic_depth_usd=float(creds.get("PANIC_DEPTH_USD", 500.0))
    )

    real_matched = 0
    real_volume = 0.0
    real_fees = 0.0
    cached_funding_rate = 0.0
    cached_vol_sec = 0.0
    last_funding_fetch = 0.0
    time.sleep(1)

    while running:
        t_start = time.time()
        try:
            new_fills = ws_mgr.pop_new_fills()
            for f in new_fills:
                real_matched += 1
                sz = float(f["fillSz"])
                px = float(f["fillPx"])
                notional = sz * px * 10.0
                real_volume += notional
                real_fees += float(f.get("fee", 0))
                inventory += sz if f["side"].lower() == "buy" else -sz
                log_msg(f"⭐ [REAL FILL] {f['side']} {sz} contracts @ {px} | Fee: {f.get('fee')} {f.get('feeCcy')}")

            if time.time() - last_funding_fetch >= 60.0:
                try:
                    fr_data = client._sign_and_request("GET", "/api/v5/public/funding-rate", params={"instId": inst_id})
                    if fr_data and "data" in fr_data and fr_data["data"]:
                        cached_funding_rate = float(fr_data["data"][0].get("fundingRate", 0.0))
                    tk_data = client._sign_and_request("GET", "/api/v5/market/ticker", params={"instId": inst_id})
                    if tk_data and "data" in tk_data and tk_data["data"]:
                        vol24h = float(tk_data["data"][0].get("volCcy24h", 0.0))
                        cached_vol_sec = vol24h / 86400.0
                except Exception:
                    pass
                last_funding_fetch = time.time()

            book = ws_mgr.get_latest_book()
            mid_px = book.get("mid", 0.0)
            micro_px = book.get("micro", mid_px)
            rolling_ofi = ws_mgr.get_rolling_ofi()

            bids_raw = book.get("bids", [])
            asks_raw = book.get("asks", [])
            depth_eval = engine.depth_sentinel.evaluate_depth_from_book(
                bids=bids_raw,
                asks=asks_raw,
                contract_val=engine.contract_val
            )
            top5_bid_usd = depth_eval.get("bid_depth_usd", 0.0)
            top5_ask_usd = depth_eval.get("ask_depth_usd", 0.0)

            decision = engine.compute_quotes(
                mid_px=mid_px,
                micro_px=micro_px,
                inventory_contracts=inventory,
                vol_30s=0.50,
                ofi_1s=rolling_ofi,
                ofi_5s=rolling_ofi * 2.0,
                ofi_30s=rolling_ofi * 5.0,
                obi=0.0,
                volume=10.0,
                trade_count=5.0,
                net_flow=rolling_ofi,
                funding_rate=cached_funding_rate,
                best_bid=book.get("bid", 0.0),
                best_ask=book.get("ask", 0.0),
                top5_bid_depth_usd=top5_bid_usd,
                top5_ask_depth_usd=top5_ask_usd,
                avg_vol_4h_sec=cached_vol_sec
            )

            pending = client.get_pending_orders(inst_type="SWAP", inst_id=inst_id)
            exist_buy = None
            exist_sell = None
            cancel_list = []

            for p in pending:
                side_p = p.get("side", "").lower()
                px_p = float(p.get("px", 0))
                ord_id = p.get("ordId")

                if side_p == "buy":
                    if decision["allow_bid"] and abs(px_p - decision["bid_px"]) <= engine.tick_size * 1.05:
                        exist_buy = p
                    else:
                        cancel_list.append({"instId": inst_id, "ordId": ord_id})
                elif side_p == "sell":
                    if decision["allow_ask"] and abs(px_p - decision["ask_px"]) <= engine.tick_size * 1.05:
                        exist_sell = p
                    else:
                        cancel_list.append({"instId": inst_id, "ordId": ord_id})

            if cancel_list:
                client.cancel_batch_orders(cancel_list)

            if decision["allow_bid"] and exist_buy is None:
                sz_bid = int(decision["lot_sz"])
                if inventory < 0:
                    sz_bid = min(sz_bid, abs(int(inventory)))
                if sz_bid > 0:
                    client.place_order(
                        inst_id=inst_id,
                        td_mode="cross",
                        side="buy",
                        ord_type="post_only",
                        px=f"{decision['bid_px']:.5f}",
                        sz=str(sz_bid)
                    )

            if decision["allow_ask"] and exist_sell is None:
                sz_ask = int(decision["lot_sz"])
                if inventory > 0:
                    sz_ask = min(sz_ask, int(inventory))
                if sz_ask > 0:
                    client.place_order(
                        inst_id=inst_id,
                        td_mode="cross",
                        side="sell",
                        ord_type="post_only",
                        px=f"{decision['ask_px']:.5f}",
                        sz=str(sz_ask)
                    )

            status = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": inst_id,
                "mid": mid_px,
                "inventory_contracts": inventory,
                "inventory_usd": inventory * 10.0 * mid_px,
                "matched_count": real_matched,
                "volume_usd": real_volume,
                "fees_usd": real_fees,
                "toxic_prob": decision["p_toxic_down"],
                "depth_gate": decision.get("depth_gate"),
                "top5_bid_usd": top5_bid_usd,
                "top5_ask_usd": top5_ask_usd,
                "actions": decision["actions"]
            }
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2)

        except Exception as e:
            log_msg(f"Loop error: {e}")

        elapsed = time.time() - t_start
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)

    ws_mgr.stop()
    log_msg("=== Service Exited Gracefully ===")

if __name__ == "__main__":
    main()
