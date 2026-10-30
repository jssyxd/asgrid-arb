# -*- coding: utf-8 -*-
"""
run_sui.py - Production NautilusTrader Live Service for SUI-USDT (accountbot5)
- Instrument: SUI-USDT-SWAP (ctVal: 1 SUI)
- Capital: 30.0 USDT (3x leverage)
- Architecture: Funding Rate Carry Augmented Reservation Price + High-Beta Spread (10.0 bps)
- Unconstrained Immediate Flow: 5-second post-fill cooldown completely removed
- Strict Post-Only Maker Execution & Queue Priority Preservation
"""

import socket
# Force IPv4 socket resolution globally for OKX requests
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(*args, **kwargs):
    responses = _orig_getaddrinfo(*args, **kwargs)
    ipv4_res = [r for r in responses if r[0] == socket.AF_INET]
    return ipv4_res if ipv4_res else responses
socket.getaddrinfo = _ipv4_getaddrinfo

import os
import sys
import time
import json
import math
import signal
import numpy as np
import pandas as pd
from datetime import datetime, timezone

SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
for cand in [
    os.path.abspath(os.path.join(SERVICE_DIR, "../shared")),
    os.path.abspath(os.path.join(SERVICE_DIR, "../../shared")),
    os.path.abspath(os.path.join(SERVICE_DIR, "..")),
    "/opt/nautilus_cluster/shared"
]:
    if os.path.exists(cand) and cand not in sys.path:
        sys.path.append(cand)

from gateway_okx_client import OKXGatewayClient
from okx_ws_manager import OKXWebSocketManager

CONFIG_FILE = os.path.join(SERVICE_DIR, "config/accountbot5_credentials.env")
LOG_DIR = os.path.join(SERVICE_DIR, "logs")
STATUS_FILE = os.path.join(LOG_DIR, "03_sui_status.json")
FILLS_FILE = os.path.join(LOG_DIR, "03_sui_fills.json")
LOG_FILE = os.path.join(LOG_DIR, "03_sui_runtime.log")

os.makedirs(LOG_DIR, exist_ok=True)

def load_credentials():
    creds = {
        "OKX_API_KEY": os.environ.get("OKX_API_KEY", ""),
        "OKX_API_SECRET": os.environ.get("OKX_API_SECRET", ""),
        "OKX_API_PASSPHRASE": os.environ.get("OKX_API_PASSPHRASE", ""),
        "OKX_SIMULATED_TRADING": os.environ.get("OKX_SIMULATED_TRADING", "0"),
        "ACCOUNT_LABEL": os.environ.get("ACCOUNT_LABEL", "accountbot5"),
        "INST_ID": os.environ.get("INST_ID", "SUI-USDT-SWAP"),
        "INITIAL_CAPITAL": os.environ.get("INITIAL_CAPITAL", "30.0"),
        "LOT_SZ": os.environ.get("LOT_SZ", "10"),
        "MAX_INVENTORY": os.environ.get("MAX_INVENTORY", "40.0"),
        "MIN_SPREAD_BPS": os.environ.get("MIN_SPREAD_BPS", "10.0"),
        "PRICE_TOLERANCE": os.environ.get("PRICE_TOLERANCE", "0.0005"),
        "GAMMA": os.environ.get("GAMMA", "0.35"),
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
    line = f"[{ts}] [03_SUI_accountbot5] {msg}"
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
    log_msg("=== Starting NautilusTrader SUI-USDT (accountbot5) Production Live Service ===")
    creds = load_credentials()
    simulated = (creds.get("OKX_SIMULATED_TRADING", "0") == "1")
    inst_id = creds.get("INST_ID", "SUI-USDT-SWAP")
    
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
    
    lot_sz = creds.get("LOT_SZ", "10")    # 10 contracts = 10 SUI
    max_inv = float(creds.get("MAX_INVENTORY", 40.0)) # 40 contracts = 40 SUI
    min_spread_bps = float(creds.get("MIN_SPREAD_BPS", 10.0))
    price_tol = float(creds.get("PRICE_TOLERANCE", 0.0005))
    gamma = float(creds.get("GAMMA", 0.35))
    
    inventory = 0.0
    init_positions = client.get_positions(inst_type="SWAP", inst_id=inst_id)
    if init_positions:
        inventory = float(init_positions[0].get("pos", 0))
        log_msg(f"Synced initial live position: {inventory} contracts")
        
    loop_count = 0
    last_funding_fetch = 0.0
    cached_funding_rate = 0.0001
    last_pos = inventory
    
    real_matched = 0
    real_volume = 0.0
    
    time.sleep(2)
    
    while running:
        loop_count += 1
        t_start = time.time()
        try:
            # 1. Process real fills from WebSocket (No artificial post-fill cooldown)
            new_fills = ws_mgr.pop_new_fills()
            for f in new_fills:
                real_matched += 1
                notional = float(f['fillSz']) * float(f['fillPx'])
                real_volume += notional
                log_msg(f"⭐ [REAL FILL] {f['side']} {f['fillSz']} contracts @ {f['fillPx']} | Fee: {f['fee']} {f['feeCcy']}")
                
            last_pos = inventory
            
            # 2. Fetch funding rate every 60s
            if time.time() - last_funding_fetch >= 60.0:
                fr_data = client.get_funding_rate(inst_id)
                if fr_data:
                    cached_funding_rate = float(fr_data.get("fundingRate", 0.0001))
                    last_funding_fetch = time.time()
                    
            # 3. Retrieve orderbook from WS
            book = ws_mgr.get_latest_book()
            mid_px = book["mid"]
            if mid_px <= 0:
                t_data = client.get_ticker(inst_id)
                mid_px = float(t_data.get("last", 0.88))
            micro_px = book["micro"] if book["micro"] > 0 else mid_px
            
            # 4. SUI Pricing Engine with Funding Carry Basis
            # Basis_funding: If holding long and funding < 0 (shorts pay longs), holding inventory is profitable
            basis_funding = -cached_funding_rate * (mid_px * 0.5)
            
            base_half_spd = max(mid_px * (min_spread_bps * 0.5 / 10000.0), (1.0 / gamma) * math.log(1.0 + gamma / 2.1346) * (mid_px * 0.0004))
            
            inv_ratio = np.clip(inventory / max(max_inv, 1e-6), -1.0, 1.0)
            inv_bias = inv_ratio * base_half_spd * 0.75
            
            r = micro_px - inv_bias + basis_funding
            
            calc_bid = round(r - (base_half_spd + inv_bias), 4)
            calc_ask = round(r + (base_half_spd - inv_bias), 4)
            
            # Strict Post-Only clamp
            calc_bid = min(calc_bid, round(mid_px - base_half_spd * 0.5, 4))
            calc_ask = max(calc_ask, round(mid_px + base_half_spd * 0.5, 4))
            
            # Continuous unconstrained quote permissions (No 5-second cooldown)
            allow_bid = (inventory < max_inv)
            allow_ask = (inventory > -max_inv)
            
            # 5. Order Management with Queue Priority Hold
            pending = client.get_pending_orders(inst_type="SWAP", inst_id=inst_id)
            exist_buy = None
            exist_sell = None
            cancel_list = []
            
            for p in pending:
                side_p = p.get("side", "").lower()
                px_p = float(p.get("px", 0))
                ord_id = p.get("ordId")
                
                if side_p == "buy":
                    if allow_bid and abs(px_p - calc_bid) <= price_tol:
                        exist_buy = p
                    else:
                        cancel_list.append({"instId": inst_id, "ordId": ord_id})
                elif side_p == "sell":
                    if allow_ask and abs(px_p - calc_ask) <= price_tol:
                        exist_sell = p
                    else:
                        cancel_list.append({"instId": inst_id, "ordId": ord_id})
                        
            if cancel_list:
                try:
                    client.cancel_batch_orders(cancel_list)
                except Exception:
                    pass
                    
            actions = []
            now_ms = int(time.time() * 1000)
            
            if allow_bid:
                if exist_buy:
                    actions.append(f"BID_HOLD({exist_buy.get('px')})")
                else:
                    cl_id = f"asb{now_ms}"[-32:]
                    res = client.place_order(inst_id, "cross", "buy", "post_only", str(calc_bid), lot_sz, cl_id)
                    actions.append(f"BID_POST({calc_bid})" if res.get("code") == "0" else f"BID_REJ({res.get('msg')})")
            else:
                actions.append("BID_CUT")
                
            if allow_ask:
                if exist_sell:
                    actions.append(f"ASK_HOLD({exist_sell.get('px')})")
                else:
                    cl_id = f"asa{now_ms}"[-32:]
                    res = client.place_order(inst_id, "cross", "sell", "post_only", str(calc_ask), lot_sz, cl_id)
                    actions.append(f"ASK_POST({calc_ask})" if res.get("code") == "0" else f"ASK_REJ({res.get('msg')})")
            else:
                actions.append("ASK_CUT")
                
            if loop_count % 10 == 0:
                pos_list = client.get_positions(inst_type="SWAP", inst_id=inst_id)
                if pos_list:
                    inventory = float(pos_list[0].get("pos", 0))
                    
            if loop_count % 5 == 0:
                log_msg(f"Heartbeat #{loop_count}: Mid={mid_px:.4f}, Inv={inventory}, FR={cached_funding_rate:.6f}, Fills={real_matched}, Actions={' | '.join(actions)}")
                
            status_data = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": inst_id,
                "mid_price": mid_px,
                "micro_price": micro_px,
                "inventory": inventory,
                "max_inventory": max_inv,
                "funding_rate": cached_funding_rate,
                "real_matched": real_matched,
                "actions": actions
            }
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(status_data, f, indent=2)
                
        except Exception as e:
            log_msg(f"Exception in loop: {e}")
            
        t_elapsed = time.time() - t_start
        time.sleep(max(0.1, 1.0 - t_elapsed))
        
    ws_mgr.stop()
    log_msg("SUI Live Service stopped cleanly.")

if __name__ == "__main__":
    main()
