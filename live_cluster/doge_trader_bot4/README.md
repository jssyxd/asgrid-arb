# DOGE-USDT (accountbot4) NautilusTrader 高频做市子交易程序

## 1. 资产与账户规格
- **交易标的**：`DOGE-USDT-SWAP`（OKX 线性永续合约，面值 `ctVal: 1000 DOGE`，最小步长 `0.01` 张）
- **账户标识**：`accountbot4`
- **运行资金**：30.0 USDT（3x 杠杆）
- **单笔下单**：`0.10` 张（100 DOGE，名义价值约 $7.58 USDT，占用保证金约 $2.53 USDT，占本金 8.4%）
- **最大持仓**：`0.40` 张（400 DOGE，名义价值约 $30.3 USDT，占用保证金约 $10.10 USDT，占本金 33.6%，**保留 66.4% 缓冲垫**）

## 2. 微观定价与 ML 模型特异性
- **量能加速度门控 (Volume Acceleration Gating)**：
  - 针对 Meme 币突发爆量拉升或踩踏跳水，实时监测高频量能脉冲：$\text{VolAccel} = V_t / (\text{MA}_{20}(V) + \epsilon)$；
  - 当 $\text{VolAccel} > 2.5$ 且伴随 1-bar 动量突破时，硬性切断逆势方向报单（暴涨切断卖单、暴跌切断买单），阻断知情零售大单的逆向选择。
- **宽价差肥尾吸收机制**：
  - DOGE 散户投机脉冲频繁，最优价差下限强制设定为 $\ge 12.0\text{ bps}$（单边半价差 $\ge 6.0\text{ bps}$），预留充足利润空间覆盖剧烈跳价与滑点。
- **排队优先权保护**：微观价格波动 $\le \pm 0.00005\text{ USDT}$ 时保持原单排队（`BID_HOLD` / `ASK_HOLD`）。
- **严格 Post-Only 守卫**：强制所有委托为 `post_only`，坚决消灭 Taker 吃单。

## 3. 部署与守护
- 服务入口：`run_doge.py`
- Systemd 服务配置：`/etc/systemd/system/nautilus-doge-bot4.service`
- 内存硬限制：`MemoryMax=350M`，配合系统级 2GB Swap 分区防止 OOM。
