# 生产级重大故障排查与修复报告：下砸单边行情中的平空死锁 Bug
## (Critical Production Bugfix Report: Inventory Short-Covering Deadlock)

> **审计状态**：已修复（HOTFIX VERIFIED IN PRODUCTION）  
> **修复文件**：`strategies_live/shared/robust_glft_engine.py` 及各币种实盘 runner  
> **涉及账户**：`accountbot3` (AKE)、`accountbot5` (CORE)、`accountbot2` (CHZ)  
> **修复验证**：AKE -55 张高危空头在修复部署后 2 分钟内成功全部平仓，持仓归零（Flat），浮盈全额锁定落袋。

---

## 一、 故障现象与触发环境 (Incident & Symptoms)

### 1. 现场故障现象
2026-11-02 18:30 UTC 现场对账检查中，发现持有大额空头浮盈的做市账户在交易所的挂单数异常归零：
- **`accountbot3` (AKE-USDT-SWAP)**：手握 -55 张空头（5,500 AKE，开仓均价 0.008828，现价暴跌至 0.0059，未实现浮盈一度高达 **+15.88 USDT**）；
- **OKX 现场挂单状态**：`Pending Orders on exchange: 0`（完全不挂单，处于无保护裸奔状态！）；
- **重大穿仓风险**：5,500 AKE 空头名义敞口达 $33.5 USD，而账户本金仅 18.1 USD，实际真实杠杆高达 **1.85 倍**。若 AKE 发生 40% 的超跌暴力反弹，+15.88u 浮盈将瞬间蒸发；若暴涨 90%，将**直接击穿可用资金引发交易所强平爆仓**！

---

## 二、 根因深度剖析 (Root Cause Analysis - RCA)

查阅 `accountbot3_status.json`，捕获到核心动作冲突：
```json
{
  "symbol": "AKE-USDT-SWAP",
  "mid": 0.006095,
  "inventory_contracts": -55.0,
  "inventory_usd": -33.52,
  "toxic_prob": 0.68,
  "actions": [
    "TOXIC_DOWN_CUT(p=0.68, vol_r=1.0)",
    "INVENTORY_SHORT_LOCK(-33.52)"
  ]
}
```

### 致命死锁逻辑链（Deadlock Chain）：
1. **卖单被单向限额锁死**：
   策略引入了单笔乒乓做市纪律，当持有空头名义价值超过阈值时：
   `if inventory_usd <= -single_lot_threshold: allow_ask = False`
   系统禁止继续挂卖单（防止空头仓位被动扩大），此逻辑完全正确；
2. **买单被毒性门控误杀**：
   与此同时，行情在低位剧烈下砸，LightGBM 毒性分类模型精准预测到了穿盘风险（$P(\text{toxic\_down}) = 0.68 \ge 0.65$）；
   原代码无脑执行了单边切断：
   `if p_toxic_down >= 0.65: allow_bid = False`
3. **死锁悲剧发生**：
   - 买单被 `TOXIC_DOWN_CUT` 封死（`allow_bid = False`）；
   - 卖单被 `INVENTORY_SHORT_LOCK` 封死（`allow_ask = False`）；
   - **做市商在价格砸到最低点、浮盈最丰厚的时候，被代码硬生生剥夺了挂买单平空止盈的权利！**
   - 原代码将“开多买单（接下砸飞刀）”与“平空买单（获利平仓兑现）”混为一谈，导致做市商坐在原地等待行情反弹被割。

---

## 三、 解决方案与代码解耦重构 (Architecture Solution)

### 1. 严格解耦开仓与平仓买单权限
`TOXIC_DOWN_CUT` 的物理初衷是**拒绝开新多头接飞刀**。
当持有空头（`inventory_usd < 0`）时，买入行为是**买入平仓（BUY TO COVER）**，在下砸行情中平空是加速兑现浮盈的最安全操作，必须 100% 放行！

```python
# strategies_live/shared/robust_glft_engine.py
# CRITICAL FIX: TOXIC_DOWN_CUT must only block OPENING NEW LONGS!
# When holding SHORT (inventory_usd < 0), buying is BUY TO COVER (take-profit), which must be allowed!
if p_toxic_down >= self.toxic_threshold or vol_ratio >= 2.2:
  if inventory_usd >= 0:
    allow_bid = False
    actions.append(
        f"TOXIC_DOWN_CUT(p={p_toxic_down:.2f}, vol_r={vol_ratio:.1f})"
    )
  else:
    # 强制放行平仓买单！
    actions.append(f"TOXIC_DOWN_COVER_ALLOWED(p={p_toxic_down:.2f})")
```

### 2. 引入反向内侧出货钳制 (Inside-Bid Exit Clamping)
持有空头需要平仓时，买单价格强制提升至 `max(calc_bid, best_bid)`，直接贴在买一档甚至盘口内侧排队，以最快速度被动成交平空：
```python
if inventory_usd < 0 and best_bid > 0:
  # Short inventory: clamp bid inside to accelerate buying to cover & lock profit!
  calc_bid = min(
      max(res_price - base_half_spd, best_bid), mid_px - self.tick_size
  )
```

### 3. 下单张数动态安全约束
在各 runner 中，买单挂单张数强制受到当前持仓量的上界约束，严禁平仓变成反向开多：
```python
if decision["allow_bid"] and exist_buy is None:
  sz_bid = int(decision["lot_sz"])
  if inventory < 0:
    sz_bid = min(sz_bid, abs(int(inventory)))
  if sz_bid > 0:
    client.place_order(
        ..., side="buy", ord_type="post_only", sz=str(sz_bid), ...
    )
```

---

## 四、 实盘验证战果 (Production Verification)

2026-11-02 18:50 UTC 修复代码热重载上线后：
1. **瞬间解除死锁**：
   `actions: ["TOXIC_DOWN_COVER_ALLOWED(p=0.68)", "INVENTORY_SHORT_LOCK(-33.58)", "BID_QUEUE_HOLD(0.00609)"]`
   买单平仓指令在 0.00609 档位成功挂出！
2. **2 分钟内平仓归零**：
   现场日志记录连续撮合 12 笔平仓买单，**AKE 持仓由 -55 张极速降为 0.0 张（Flat）**！
   `inventory_usd` 归零，+15.17 USDT 浮盈安全落袋变现，彻底根除了反弹强平风险！
