# -*- coding: utf-8 -*-
"""
Production NautilusTrader Live Service for WOO-USDT-SWAP (accountbot4)
- Instrument: WOO-USDT-SWAP (ctVal: 10.0)
- Architecture: Stoikov Micro-price + Top-5 OFI + Regime-Switching Gamma (0.35/1.20)
- Hard Fee Hurdle: Min Spread >= 8.5 bps (Half spread >= 4.25 bps)
- 5s Single-Sided Fill Cooldown & Strict Post-Only Maker Execution
"""

import socket
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
SHARED_DIR = os.path.abspath(os.path.join(SERVICE_DIR, "../../shared"))
sys.path.append(SHARED_DIR)

from gateway_okx_client import OKXGatewayClient
from okx_ws_manager_v3 import OKXWebSocketManager

CONFIG_FILE = os.path.join(SERVICE_DIR, "config/accountbot4_credentials.env")
LOG_DIR = os.path.join(SERVICE_DIR, "logs")
STATUS_FILE = os.path.join(LOG_DIR, "accountbot4_status.json")
LOG_FILE = os.path.join(LOG_DIR, "accountbot4_runtime.log")

os.makedirs(LOG_DIR, exist_ok=True)

def load_credentials():
    creds = {}
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
    line = f"[{ts}] [accountbot4_WOO] {msg}"
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

def compute_gk_vol(candles):
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
    ma_dev = (cur_c - ma20) / max(atr, 0.0001)
    
    return float(annual_gk), float(ma_dev), float(cur_c)

def main():
    log_msg("=== Starting NautilusTrader WOO-USDT-SWAP (accountbot4) Production Live Service ===")
    creds = load_credentials()
    simulated = (creds.get("OKX_SIMULATED_TRADING", "0") == "1")
    inst_id = creds.get("INST_ID", "WOO-USDT-SWAP")
    
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
    
    # Parameters
    lot_sz = float(creds.get("LOT_SZ", 10.0))
    max_inv = float(creds.get("MAX_INVENTORY", 100.0))
    min_spread_bps = float(creds.get("MIN_SPREAD_BPS", 8.5))
    gamma_calm = float(creds.get("GAMMA_CALM", 0.35))
    gamma_vol = float(creds.get("GAMMA_VOL", 1.2))
    price_tol = float(creds.get("PRICE_TOLERANCE", 2e-05))
    
    # State
    inventory = 0.0
    init_positions = client.get_positions(inst_type="SWAP", inst_id=inst_id)
    if init_positions:
        inventory = float(init_positions[0].get("pos", 0))
        log_msg(f"Synced initial live position: {inventory} contracts")
        
    loop_count = 0
    last_mid = 0.0
    cached_gk = 0.50
    cached_ma_dev = 0.0
    vol_median = 0.55
    cached_funding_rate = 0.0
    last_funding_fetch = 0.0
    
    last_fill_time_bid = 0.0
    last_fill_time_ask = 0.0
    FILL_COOLDOWN_SEC = 5.0
    last_pos = inventory
    
    real_matched = 0
    real_volume = 0.0
    real_fees = 0.0
    
    time.sleep(1)
    
    while running:
        loop_count += 1
        t_start = time.time()
        try:
            # 1. Process real fills from WebSocket
            new_fills = ws_mgr.pop_new_fills()
            for f in new_fills:
                real_matched += 1
                notional = float(f['fillSz']) * float(f['fillPx']) * 10.0
                real_volume += notional
                real_fees += float(f.get('fee', 0))
                log_msg(f"⭐ [REAL FILL] {f['side']} {f['fillSz']} contracts @ {f['fillPx']} | Fee: {f['fee']} {f['feeCcy']}")
                
            # Cooldown trigger (5-second single side pause)
            if inventory > last_pos:
                last_fill_time_bid = time.time()
                log_msg(f"⚡ Buy Fill detected ({last_pos} -> {inventory}), bid cooldown 5s")
            elif inventory < last_pos:
                last_fill_time_ask = time.time()
                log_msg(f"⚡ Sell Fill detected ({last_pos} -> {inventory}), ask cooldown 5s")
            last_pos = inventory
            
            cd_bid = (time.time() - last_fill_time_bid) < FILL_COOLDOWN_SEC
            cd_ask = (time.time() - last_fill_time_ask) < FILL_COOLDOWN_SEC
            
            # 2. Funding rate periodic fetch
            if time.time() - last_funding_fetch >= 60.0:
                fr_data = client.get_funding_rate(inst_id)
                if fr_data:
                    cached_funding_rate = float(fr_data.get("fundingRate", 0.0))
                    last_funding_fetch = time.time()

            # 3. Streaming 1m candles
            stream_candles = ws_mgr.get_streaming_candles()
            if len(stream_candles) >= 10:
                cached_gk, cached_ma_dev, _ = compute_gk_vol(stream_candles)

            # 4. Orderbook and Micro-price
            book = ws_mgr.get_latest_book()
            mid_px = book["mid"]
            if mid_px <= 0:
                mid_px = last_mid if last_mid > 0 else 0.0
            micro_px = book["micro"] if book["micro"] > 0 else mid_px
            if mid_px > 0:
                last_mid = mid_px
            
            rolling_ofi = ws_mgr.get_rolling_ofi()
            ofi_norm = np.clip(rolling_ofi / 50.0, -3.0, 3.0)
            
            # 5. Pricing Engine
            gamma = gamma_vol if cached_gk > (vol_median * 1.5) else gamma_calm
            base_half_spd = max(mid_px * (min_spread_bps * 0.5 / 10000.0), (1.0 / gamma) * math.log(1.0 + gamma / 2.1346) * (mid_px * 0.0004))
            
            inv_ratio = np.clip(inventory / max(max_inv, 1e-6), -1.0, 1.0)
            inv_bias = inv_ratio * base_half_spd * 0.85
            
            mu_pred = np.clip(0.35 * ofi_norm - 0.20 * cached_ma_dev, -2.0, 2.0)
            drift_adj = 0.5563 * mu_pred * (mid_px * 0.0003)
            
            # Funding carry drift: if FR < 0 (shorts pay longs), holding long is profitable, shift r down to accumulate long
            funding_drift = -cached_funding_rate * (mid_px * 0.5)
            
            r = micro_px - inv_bias + drift_adj + funding_drift
            
            calc_bid = round(r - (base_half_spd + inv_bias), 5)
            calc_ask = round(r + (base_half_spd - inv_bias), 5)
            
            # Strict Post-Only Clamp: NEVER cross market
            calc_bid = min(calc_bid, round(mid_px - base_half_spd * 0.5, 5))
            calc_ask = max(calc_ask, round(mid_px + base_half_spd * 0.5, 5))
            
            allow_bid = (inventory < max_inv) and not cd_bid
            allow_ask = (inventory > -max_inv) and not cd_ask
            
            # 6. Order Management with Queue Priority Hold
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
                for item in cancel_list:
                    client.cancel_order(inst_id=item["instId"], ord_id=item["ordId"])
                    
            actions = []
            if allow_bid:
                if exist_buy is None:
                    res_b = client.place_order(
                        inst_id=inst_id,
                        td_mode="cross",
                        side="buy",
                        ord_type="post_only",
                        px=f"{calc_bid:.5f}",
                        sz=str(lot_sz)
                    )
                    actions.append(f"BID_POST({calc_bid:.5f})")
                else:
                    actions.append(f"BID_HOLD({float(exist_buy.get('px', 0)):.5f})")
            else:
                actions.append("BID_CUT")
                
            if allow_ask:
                if exist_sell is None:
                    res_a = client.place_order(
                        inst_id=inst_id,
                        td_mode="cross",
                        side="sell",
                        ord_type="post_only",
                        px=f"{calc_ask:.5f}",
                        sz=str(lot_sz)
                    )
                    actions.append(f"ASK_POST({calc_ask:.5f})")
                else:
                    actions.append(f"ASK_HOLD({float(exist_sell.get('px', 0)):.5f})")
            else:
                actions.append("ASK_CUT")
                
            # Periodically sync inventory
            if loop_count % 10 == 0:
                pos_list = client.get_positions(inst_type="SWAP", inst_id=inst_id)
                if pos_list:
                    inventory = float(pos_list[0].get("pos", 0))
                else:
                    inventory = 0.0
                    
            if loop_count % 5 == 0:
                log_msg(f"Heartbeat #{loop_count}: Mid={mid_px:.5f}, Inv={inventory}, Matched={real_matched}, Vol=${real_volume:.2f}, Actions={' | '.join(actions)}")
                
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
        ws_mgr.tick_event.wait(timeout=0.5)
        ws_mgr.tick_event.clear()
        
    log_msg("Main loop stopped. Cancelling all orders...")
    try:
        pending_final = client.get_pending_orders(inst_type="SWAP", inst_id=inst_id)
        for p in pending_final:
            client.cancel_order(inst_id=inst_id, ord_id=p.get("ordId"))
    except Exception as e:
        log_msg(f"Error cancelling orders upon shutdown: {e}")
    ws_mgr.stop()
    log_msg("Service successfully terminated.")

if __name__ == "__main__":
    main()
