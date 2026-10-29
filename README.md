# asgridarb: 真实盈利导向的高频微观结构做市与统计套利网格体系 (Profit-Oriented MM & Micro-Arb)

本仓库专为 **真实盈利导向 (Real Profit & Positive PnL Driven)、微观结构套利、非高费率消耗** 设计。
区别于刷量导向的做市系统，本系统以**击穿手续费阻力位、捕获净流动性溢价与短期统计均值回归**为唯一考核指标。

---

## 核心定位：盈利导向 (Profit-Oriented Strategy)

在真实加密货币市场中，纯被动做市必须在扣除双边 Maker 手续费（0.02% ~ 0.04%）和微观滑点摩擦后依然保有净利润。
本系统通过**动态拓宽做市价差、严格过滤逆向选择毒性大单、优选高波动低费率交易标的**实现正期望收益。

---

## 一、 核心适应的交易标的池 (Target Asset Universe)

小资金（如 35U 至 500U）或中型资金在运行盈利导向网格时，**严禁盲目在 BTC / ETH 头部合约上进行微利做市**。
BTC / ETH 盘口被全球顶级高频机构（Jump、Wintermute、Jane Street 等）把守，点差被压缩至极致的 0.1 美元（不到 0.01 bps），普通散户资金极易沦为被逆向选择吃单的接盘方。

本系统针对以下三类黄金标的池进行了数学与实战适配：

### 1. 结构性高波动山寨代币永续合约 (High-Beta Altcoin Perps)
- **推荐标的**：`DOGE-USDT-SWAP`、`SOL-USDT-SWAP`、`PEPE-USDT-SWAP`、`SUI-USDT-SWAP`。
- **盈利机理**：
  - 日内实际波动率（Garman-Klass Volatility）常年超过 80% ~ 150%；
  - 散户情绪驱动严重，盘口买卖价差（Spread）经常自然维持在 **8 ~ 25 bps**，远远高于双边 4 bps 的手续费成本；
  - 摆动空间极大，限价挂单能轻松捕获均值回归利润。

### 2. 负费率代币与资金费率对冲币对 (Negative Funding / High-Rebate Pairs)
- **特征**：全网资金费率出现严重极化（8 小时资金费率达到 -0.1% 至 -0.5%）的极端做空挤压标的。
- **盈利机理**：
  - 利用做市商双边挂单同时收取双向盘口价差与每 8 小时一次的高额资金费率（Carry Yield）；
  - 即使行情平盘，仅靠费率与 Maker 返佣即可贡献正向净现金流。

### 3. 新兴现货与小币种盘口 (Thin Order Book Spot Pairs)
- **特征**：日成交量在 200 万至 1000 万美元之间的二线交易所现货对。
- **盈利机理**：
  - 缺少专业做市商驻场，盘口呈现天然的厚价差（点差常达 30 ~ 50 bps）；
  - 策略以 Post-Only 挂入买一卖一内侧，充当主导流动性提供商，单笔盈亏比天然大于 2.0。

---

## 二、 关键注意事项与风控铁律 (Risk Guardrails)

在实盘运行盈利导向做市网格时，必须强制遵守以下 5 条铁律：

### 1. 基础价差必须大于两倍手续费安全垫 (Spread > 2.5x Total Fees)
- 做市商单笔毛利公式：
  $$\text{Net PnL} = \Delta \text{Spread} - 2 \times \text{Maker Fee} - \text{Slippage}$$
- 若交易所 Maker 手续费为 0.02%，双边往返成本为 0.04%（4 bps）。
- 代码中强制锁定 `min_spread_bps >= 10.0`（0.10%）。低于 10 bps 的微利挂单坚决不发，从源头杜绝“频繁成交却全是为交易所打工”的手续费磨损。

### 2. 严格强制 Post-Only（绝不承受 Taker 惩罚）
- 所有挂单报文统一携带 `ordType="post_only"`。
- 若价格剧烈波动导致挂单可能被直接吃掉，OKX 引擎会自动拒绝并撤销，绝不转化为 0.05% 的高额 Taker 惩罚性扣费。

### 3. 动态倾斜与库存硬熔断 (Inventory Hard Circuit Breaker)
- 严禁让单边多头或空头持仓无限放大。
- 当净库存占用超过账户可用保证金的 **25%** 时，策略立即停止顺向开仓，并以保留价格 $r(s, q)$ 强力向平仓方向贴近，促使库存迅速回吐归零。

### 4. 极端毒性冲击单边断路器 (Toxic Shock Breaker)
- 结合实时 Cont-Kukanov-Stoikov 订单流不平衡量（OFI）与 LightGBM 毒性概率：
  - 当 $P_{\text{toxic\_down}} \ge 0.65$ 时（识别到连续大额市价主动砸盘），瞬时切断所有买单，任由价格下跌，绝不在暴跌第一波接飞刀；
  - 待毒性概率回落至 0.40 以下、流动性韧性修复后，再重新恢复双边挂单。

### 5. 避免在低波动垃圾时间过度换手
- 当帕金森波动率低于设定分位数阈值（如当前市场陷入死水横盘）时，做市利润无法覆盖时间风险，策略自动切入静默休眠模式（Sleep Mode），减少无效 API 交互。

---

## 三、 实盘部署与配置

```bash
# 1. 校验账户权益与设置标的（例如 DOGE 或 SOL 永续）
python3 src/as_dynamic_risk.py

# 2. 启动盈利型做市容器
cd live_cluster && docker compose up -d

# 3. 运行 10 分钟财务与盈亏监控
python3 live_cluster/cron_hot_monitor.py 1
```
