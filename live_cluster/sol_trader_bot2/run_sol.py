# -*- coding: utf-8 -*-
"""
run_sol.py - Production NautilusTrader Live Service for SOL-USDT (accountbot2)
- Instrument: SOL-USDT-SWAP (ctVal: 1 SOL)
- Capital: 40.0 USDT (3x leverage)
- Architecture: Stoikov Micro-price + Top-5 OFI + Regime-Switching Gamma (0.35 calm / 1.20 vol)
- Hard Fee Hurdle: Min Spread >= 8.0 bps (Half spread >= 4.0 bps)
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

CONFIG_FILE = os.path.join(SERVICE_DIR, "config/accountbot2_credentials.env")
LOG_DIR = os.path.join(SERVICE_DIR, "logs")
STATUS_FILE = os.path.join(LOG_DIR, "01_sol_status.json")
FILLS_FILE = os.path.join(LOG_DIR, "01_sol_fills.json")
LOG_FILE = os.path.join(LOG_DIR, "01_sol_runtime.log")

os.makedirs(LOG_DIR, exist_ok=True)

def load_credentials():
    creds = {
        "OKX_API_KEY": os.environ.get("OKX_API_KEY", ""),
        "OKX_API_SECRET": os.environ.get("OKX_API_SECRET", ""),
        "OKX_API_PASSPHRASE": os.environ.get("OKX_API_PASSPHRASE", ""),
        "OKX_SIMULATED_TRADING": os.environ.get("OKX_SIMULATED_TRADING", "0"),
        "ACCOUNT_LABEL": os.environ.get("ACCOUNT_LABEL", "accountbot2"),
        "INST_ID": os.environ.get("INST_ID", "SOL-USDT-SWAP"),
        "INITIAL_CAPITAL": os.environ.get("INITIAL_CAPITAL", "40.0"),
        "LOT_SZ": os.environ.get("LOT_SZ", "0.10"),
        "MAX_INVENTORY": os.environ.get("MAX_INVENTORY", "0.40"),
        "MIN_SPREAD_BPS": os.environ.get("MIN_SPREAD_BPS", "8.0"),
        "PRICE_TOLERANCE": os.environ.get("PRICE_TOLERANCE", "0.03"),
        "GAMMA_CALM": os.environ.get("GAMMA_CALM", "0.35"),
        "GAMMA_VOL": os.environ.get("GAMMA_VOL", "1.20"),
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
    line = f"[{ts}] [01_SOL_accountbot2] {msg}"
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

def compute_sol_gk_vol(candles):
    arr = np.array(candles, dtype=object)[::-1]
    open_ = arr[:, 1].astype(float)
    high = arr[:, 2].astype(float)
    low = arr[:, 3].astype(float)
    close = arr[:, 4].astype(float)
    
    log_hl = np.log(np.maximum(high, 1e-6) / np.maximum(low, 1e-6))
    log_co = np.log(np.maximum(close, 1e-6) / np.maximum(open_, 1e-6))
    gk_var = 0.5 * (log_hl ** 2) - (2.0 * np.log(2.0) - 1.0) * (log_co ** 2)
    annual_gk = np.sqrt(np.maximum(np.mean(gk_var[-20:]), 1e-9) * (365.25 * 1440))
    
    ma20 = np.mean(close[-20:])
    cur_c = close[-1]
    atr = np.mean(high[-14:] - low[-14:]) if len(high) >= 14 else (cur_c * 0.002)
    ma_dev = (cur_c - ma20) / max(atr, 0.01)
    
    return float(annual_gk), float(ma_dev), float(cur_c)

def main():
    log_msg("=== Starting NautilusTrader SOL-USDT (accountbot2) Production Live Service ===")
    creds = load_credentials()
    simulated = (creds.get("OKX_SIMULATED_TRADING", "0") == "1")
    inst_id = creds.get("INST_ID", "SOL-USDT-SWAP")
    
    client = OKXGatewayClient(
        api_key=creds["OKX_API_KEY"],
        api_secret=creds["OKX_API_SECRET"],
        passphrase=creds["OKX_API_PASSPHRASE"],
        simulated=simulated
    )
    
    # Capital check
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
    
    lot_sz = creds.get("LOT_SZ", "0.10")
    max_inv = float(creds.get("MAX_INVENTORY", 0.40))
    min_spread_bps = float(creds.get("MIN_SPREAD_BPS", 8.0))
    gamma_calm = float(creds.get("GAMMA_CALM", 0.35))
    gamma_vol = float(creds.get("GAMMA_VOL", 1.20))
    price_tol = float(creds.get("PRICE_TOLERANCE", 0.03))
    
    # State
    inventory = 0.0
    init_positions = client.get_positions(inst_type="SWAP", inst_id=inst_id)
    if init_positions:
        inventory = float(init_positions[0].get("pos", 0))
        log_msg(f"Synced initial live position: {inventory} contracts")
        
    loop_count = 0
    last_candle_fetch = 0.0
    cached_gk = 0.40
    cached_ma_dev = 0.0
    vol_median = 0.45
    
    last_fill_time_bid = 0.0
    last_fill_time_ask = 0.0
    FILL_COOLDOWN_SEC = 5.0
    last_pos = inventory
    
    real_matched = 0
    real_volume = 0.0
    real_fees = 0.0
    
    time.sleep(2)
    
    while running:
        loop_count += 1
        t_start = time.time()
        try:
            # 1. Process real fills from WebSocket
            new_fills = ws_mgr.pop_new_fills()
            for f in new_fills:
                real_matched += 1
                notional = float(f['fillSz']) * float(f['fillPx'])
                real_volume += notional
                real_fees += float(f.get('fee', 0))
                log_msg(f"⭐ [REAL FILL] {f['side']} {f['fillSz']} contracts @ {f['fillPx']} | Fee: {f['fee']} {f['feeCcy']}")
                
            # Cooldown trigger
            if inventory > last_pos:
                last_fill_time_bid = time.time()
                log_msg(f"⚡ Buy Fill detected ({last_pos} -> {inventory}), cooldown 5s")
            elif inventory < last_pos:
                last_fill_time_ask = time.time()
                log_msg(f"⚡ Sell Fill detected ({last_pos} -> {inventory}), cooldown 5s")
            last_pos = inventory
            
            cd_bid = (time.time() - last_fill_time_bid) < FILL_COOLDOWN_SEC
            cd_ask = (time.time() - last_fill_time_ask) < FILL_COOLDOWN_SEC
            
            # 2. Update K-lines every 15s
            if time.time() - last_candle_fetch >= 15.0:
                candles = client.get_candles(inst_id, bar="1m", limit=30)
                if candles:
                    cached_gk, cached_ma_dev, _ = compute_sol_gk_vol(candles)
                    last_candle_fetch = time.time()
                    
            # 3. Retrieve orderbook from WS
            book = ws_mgr.get_latest_book()
            mid_px = book["mid"]
            if mid_px <= 0:
                t_data = client.get_ticker(inst_id)
                mid_px = float(t_data.get("last", 96.0))
            micro_px = book["micro"] if book["micro"] > 0 else mid_px
            
            rolling_ofi = ws_mgr.get_rolling_ofi()
            ofi_norm = np.clip(rolling_ofi / 50.0, -3.0, 3.0)
            
            # 4. SOL Pricing Engine
            gamma = gamma_vol if cached_gk > (vol_median * 1.5) else gamma_calm
            base_half_spd = max(mid_px * (min_spread_bps * 0.5 / 10000.0), (1.0 / gamma) * math.log(1.0 + gamma / 2.1346) * (mid_px * 0.0004))
            
            inv_ratio = np.clip(inventory / max(max_inv, 1e-6), -1.0, 1.0)
            inv_bias = inv_ratio * base_half_spd * 0.75
            
            mu_pred = np.clip(0.35 * ofi_norm - 0.20 * cached_ma_dev, -2.0, 2.0)
            drift_adj = 0.5563 * mu_pred * (mid_px * 0.0003)
            
            r = micro_px - inv_bias + drift_adj
            
            calc_bid = round(r - (base_half_spd + inv_bias), 2)
            calc_ask = round(r + (base_half_spd - inv_bias), 2)
            
            # Strict Post-Only Clamp: NEVER cross market
            calc_bid = min(calc_bid, round(mid_px - base_half_spd * 0.5, 2))
            calc_ask = max(calc_ask, round(mid_px + base_half_spd * 0.5, 2))
            
            allow_bid = (inventory < max_inv) and not cd_bid
            allow_ask = (inventory > -max_inv) and not cd_ask
            
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
                
            # Sync position from exchange every 10 loops
            if loop_count % 10 == 0:
                pos_list = client.get_positions(inst_type="SWAP", inst_id=inst_id)
                if pos_list:
                    inventory = float(pos_list[0].get("pos", 0))
                    
            # Heartbeat log every 5 loops
            if loop_count % 5 == 0:
                log_msg(f"Heartbeat #{loop_count}: Mid={mid_px:.2f}, Inv={inventory}, Fills={real_matched}, Vol=${real_volume:.2f}, Actions={' | '.join(actions)}")
                
            # Status export
            status_data = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": inst_id,
                "mid_price": mid_px,
                "micro_price": micro_px,
                "inventory": inventory,
                "max_inventory": max_inv,
                "gamma": gamma,
                "real_matched": real_matched,
                "real_volume_usd": real_volume,
                "actions": actions
            }
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(status_data, f, indent=2)
                
        except Exception as e:
            log_msg(f"Exception in loop: {e}")
            
        t_elapsed = time.time() - t_start
        time.sleep(max(0.1, 1.0 - t_elapsed))
        
    ws_mgr.stop()
    log_msg("SOL Live Service stopped cleanly.")

if __name__ == "__main__":
    main()
