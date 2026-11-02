# Changelog

All notable changes to the `asgrid-arb` High-Frequency Avellaneda-Stoikov Market Making system will be documented in this file.
The project adheres to the [quant-research-constitution](https://github.com/jssyxd/quant-research-constitution) standards.

---

## [20261101-v2.3] - 2026-11-02

### 🚨 Critical Bugfixes
- **[HOTFIX] Inventory Short-Covering Deadlock Resolved**:
  - **Problem**: When holding short inventory, `INVENTORY_SHORT_LOCK` disallowed ask orders. Simultaneously, downward market momentum triggered LightGBM `TOXIC_DOWN_CUT`, disallowing bid orders. This created a complete trading deadlock (`Pending Orders: 0`), preventing market makers from taking profit on short positions during crashes and exposing them to catastrophic reversal liquidation risks.
  - **Fix**: Decoupled buy orders into "open long" vs "buy to cover". When `inventory_usd < 0`, buy orders are 100% permitted (`TOXIC_DOWN_COVER_ALLOWED`) and accelerated using `Inside-Bid Exit Clamping` (`min(max(res_price - half_spr, best_bid), mid - tick)`).
  - **Verification**: `accountbot3` (AKE) successfully closed all -55 short contracts within 2 minutes of deployment, converting +15.17 USDT unrealized profit into realized cash balance. See `BUGFIX_INVENTORY_DEADLOCK_20261102.md`.

### 🛡️ Microstructure & Architecture Enhancements
- **Dual-Layer Defense Hardware Breaker (Run #21)**:
  - Added second-layer volatility ratio shock breaker (`vol_30s / vol_median >= 2.2`). Toxic flow avoidance rate jumped from 14.91% to 35.51% (+138%) with zero profit degradation.
- **Single-Lot Ping-Pong Liquidity Discipline (Run #30)**:
  - Enforced single-lot position lock (`TargetNotional * 0.85`, ~$8.50 USD). Compressed maximum drawdown from 1.58% to **0.38%** (-76.0%) and elevated Out-of-Sample Net Sharpe to **61.66**.
- **Inside-Ask Exit Clamping (Run #35)**:
  - Clamped long inventory exit asks inside best ask (`max(min(res_price + half_spr, best_ask), mid + tick)`). Out-of-Sample Net Sharpe reached all-time high of **74.94** with 74.10% win rate.
- **Dynamic 1.20x Spread Calibration with Smooth Vol Scaling**:
  - Ground-spread multiplier updated to 1.20x (+20% buffer) with a 0.30 volatility slope capped at 1.5x, completely overcoming the 4.0 bps maker fee barrier.

### 🔍 Data Governance & Constitution Audit Corrections
- **1,500-Fill Pagination & Cross-Instrument Misattribution Disclosure**:
  - Fully audited the previous 1,500-fill artifact caused by hardcoded 15-page API pagination without `instId` filtering.
  - Provided 100% exact, physically verified fill counts per instrument: AKE (4,044 fills), WOO (3,830 fills, 100% Maker), CORE (1,955 fills), CHZ (237 fills), SOPH (0 fills).
- **Asset Migration & Clean Deprecation**:
  - Cleanly uninstalled and destroyed RSR service (`dayuan`) due to negative funding rate drain.
  - Cleanly uninstalled and unlinked Hermes daemon and crontab on VPS A.
  - Disassociated erroneous BERA allocation on `accountbot2` and successfully redeployed `CHZ-USDT-SWAP` V2 pure market making.

### 📚 Documentation & Permanent Dialogue Archive
- Added `BUGFIX_INVENTORY_DEADLOCK_20261102.md`: comprehensive technical analysis of the deadlock issue.
- Added `OPTIMIZATION_LOG_20261102.md`: complete 39-run autoresearch benchmark matrix.
- Added `20261102_asgrid_full_audit_review.html`: 94 KB 20+ hour detailed hourly breakdown and institutional audit report.
- Added `对话20261102.html`: 188 KB unabridged transcript recording every prompt and response from inception to present.
