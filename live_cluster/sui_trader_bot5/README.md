# SUI-USDT (accountbot5) NautilusTrader 高频做市子交易程序

## 1. 资产与账户规格
- **交易标的**：`SUI-USDT-SWAP`（OKX 线性永续合约，面值 `ctVal: 1 SUI`，最小步长 `1` 张）
- **账户标识**：`accountbot5`
- **运行资金**：30.0 USDT（3x 杠杆）
- **单笔下单**：`10` 张（10 SUI，名义价值约 $8.85 USDT，占用保证金约 $2.95 USDT，占本金 9.8%）
- **最大持仓**：`40` 张（40 SUI，名义价值约 $35.4 USDT，占用保证金约 $11.80 USDT，占本金 39.3%，**保留 60.7% 缓冲垫**）

## 2. 微观定价与 ML 模型特异性
- **8h 资金费率 Carry 偏置（Basis Funding）**：
  - 针对 SUI 高 Beta 属性与剧烈资金费率摆动（$[-30\text{ bps}, +13\text{ bps}]$），保留价格扩展为：
    $$r^* = P_{\text{micro}} - \text{inv\_bias} + \text{Basis}_{\text{funding}}$$
  - 当市场深度贴水且做多能获取高额资金费率返利时，保留价格向下偏置容忍多头持仓，实现价差与资金费率双重捕获。
- **无冷却即时流转机制 (Unconstrained Immediate Flow)**：
  - **已彻底解除成交后 5 秒冷却限制**，在发生成交后状态机在下一轮主循环中立即根据最新加权微观价格刷新双向挂单，满足高频流动性做市需求。
- **最优价差下限**：$\ge 10.0\text{ bps}$（单边半价差 $\ge 5.0\text{ bps}$），严格覆盖双向 Maker 手续费与滑点。
- **排队优先权保护**：微观价格波动 $\le \pm 0.0005\text{ USDT}$ 时保持原单排队（`BID_HOLD` / `ASK_HOLD`）。
- **严格 Post-Only 守卫**：强制所有报单为 `post_only`，杜绝任何 Taker 吃单。

## 3. 部署与守护
- 服务入口：`run_sui.py`
- Systemd 服务配置：`/etc/systemd/system/nautilus-sui-bot5.service`
- 内存硬限制：`MemoryMax=350M`，配合系统级 2GB Swap 分区防止 OOM。
