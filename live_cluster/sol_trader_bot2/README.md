# SOL-USDT (accountbot2) NautilusTrader 高频做市子交易程序

## 1. 资产与账户规格
- **交易标的**：`SOL-USDT-SWAP`（OKX 线性永续合约，面值 `ctVal: 1 SOL`，最小步长 `0.01` 张）
- **账户标识**：`accountbot2`
- **运行资金**：40.0 USDT（3x 杠杆）
- **单笔下单**：`0.10` 张（0.10 SOL，名义价值约 $9.65 USDT，占用保证金约 $3.21 USDT，占本金 8.0%）
- **最大持仓**：`0.40` 张（0.40 SOL，名义价值约 $38.6 USDT，占用保证金约 $12.86 USDT，占本金 32.1%，**保留 67.9% 缓冲垫**）

## 2. 微观定价与 ML 模型特异性
- **Stoikov 微观价格锚定**：采用前档挂单深度加权计算公允价值，消除 1 bps 离散微动噪声。
- **Top-5 连续订单流失衡 (OFI)**：动态平滑追踪盘口被动与主动消耗强度。
- **动态风险厌恶状态机 (Regime-Switching Gamma)**：
  - 平稳低波阶段：$\gamma = 0.35$，适度贴合盘口保证撮合效率；
  - 波动率激增阶段（$\sigma_{GK} > 1.5 \times \sigma_{\text{median}}$）：自动切换至 $\gamma = 1.20$，主动向外拉宽保护性价差。
- **硬性手续费门槛约束**：强制双边总价差 $\ge 8.0\text{ bps}$（单边半价差 $\ge 4.0\text{ bps}$），严格覆盖双向 Maker 0.02% 手续费成本的 2 倍以上。
- **排队优先权保护**：最新公允价格微动 $\le \pm 0.03\text{ USDT}$ 时保持挂单不动（`BID_HOLD` / `ASK_HOLD`），绝不频繁全撤全挂。
- **严格 Post-Only 守卫**：全量报单绑定 `ord_type = "post_only"`，杜绝被动穿盘交纳 0.05% Taker 惩罚性手续费。

## 3. 部署与守护
- 服务入口：`run_sol.py`
- Systemd 服务配置：`/etc/systemd/system/nautilus-sol-bot2.service`
- 内存硬限制：`MemoryMax=350M`，配合系统级 2GB Swap 分区防止 OOM。
