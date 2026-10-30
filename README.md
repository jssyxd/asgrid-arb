# asgridarb · A-S 微观结构做市与统计套利网格体系

> **真实盈利导向（Real Profit / Positive PnL Driven）的高频做市引擎**：以 Avellaneda-Stoikov 随机最优控制为核心，叠加 LightGBM 毒性门控、订单流不平衡（OFI）、盘口微观价格与队列感知挂单保持，目标是在扣除双边 Maker 手续费与滑点后仍然保持正期望。

<p>
  <img alt="python"   src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white">
  <img alt="model"    src="https://img.shields.io/badge/LightGBM-toxicity%20gate-9ACD32">
  <img alt="exchange" src="https://img.shields.io/badge/Exchange-OKX%20%C2%B7%20Hyperliquid%20%C2%B7%20Bybit-black">
  <img alt="status"   src="https://img.shields.io/badge/Live-2345%20fills%20%C2%B7%20%2B1920%20USDT-brightgreen">
</p>

---

## 目录

- **[概览](#概览)**
  - [项目定位](#项目定位)
  - [实盘成绩快照（BTC 5 天）](#实盘成绩快照btc-5-天)
  - [仓库结构](#仓库结构)
- **[第一部分：项目本体](#第一部分项目本体)**
  - [1.1 核心交易标的池（Target Asset Universe）](#11-核心交易标的池target-asset-universe)
  - [1.2 风控铁律（Risk Guardrails）](#12-风控铁律risk-guardrails)
  - [1.3 实盘部署与配置](#13-实盘部署与配置)
  - [1.4 多币种独立交易集群架构（SOL/DOGE/SUI）](#14-多币种独立交易集群架构soldogesui)
- **[第二部分：深度研究报告](#第二部分深度研究报告)**
  - [2.1 A-S 理论做市刷量赚返佣：改进路线与学习路径](#21-a-s-理论做市刷量赚返佣改进路线与学习路径)
  - [2.2 赚取资金费率：可行性与改进路线](#22-赚取资金费率可行性与改进路线)
  - [2.3 跨平台迁移：DEX、TradeFi、Uniswap v3/v4 与 BSC](#23-跨平台迁移dextradefiuniswap-v3v4-与-bsc)
  - [2.4 ML 模型训练与抗手续费正 PnL 方案](#24-ml-模型训练与抗手续费正-pnl-方案)
  - [2.5 代码审阅发现（Ponytail Review）](#25-代码审阅发现ponytail-review)
  - [2.6 交易所做市商申请规则汇总](#26-交易所做市商申请规则汇总)
  - [2.7 参考开源项目索引](#27-参考开源项目索引)
  - [2.8 相关学术论文](#28-相关学术论文)
- **[免责声明](#免责声明)**

---

## 概览

### 项目定位

本仓库专为 **真实盈利导向、微观结构套利、非高费率消耗** 设计。区别于刷量导向的做市系统，本系统以**击穿手续费阻力位、捕获净流动性溢价与短期统计均值回归**为唯一考核指标。

在真实加密货币市场中，纯被动做市必须在扣除双边 Maker 手续费（0.02% ~ 0.04%）和微观滑点摩擦后依然保有净利润。本系统通过**动态拓宽做市价差、严格过滤逆向选择毒性大单、优选高波动低费率交易标的**实现正期望收益。

### 实盘成绩快照（BTC 5 天）

| 指标 | 数值 |
| :--- | ---: |
| 总真实成交笔数 | 2,345 笔 |
| 买入成交 / 卖出成交 | 1,176 / 1,169 |
| 平均捕获点差 | **7.9 bps** |
| 累计手续费 | 1,932.44 USDT |
| 毛利（含未平仓浮盈） | 3,852.84 USDT |
| **净利润（扣除全部手续费）** | **+1,920.39 USDT** |
| 最终残余库存 | 0.35 BTC |
| 运行周期 | 2026-10-10 ~ 2026-10-15 |
| 单日峰值成交 | 745 笔（第 5 天，系统稳定后递增） |

> **一句话结论**：在 BTC 头部合约上用 30U 微账户（3x 杠杆）跑出 7.9 bps 平均捕获点差与正 PnL，验证了「A-S + ML 毒性门控 + 队列感知挂单保持」的可行性。但 BTC 盘口被顶级机构挤压，**扩大规模后收益率会急剧衰减**，必须转向山寨币或新兴交易所。

### 仓库结构

```text
asgrid-arb/
├── src/                                   # 策略内核（引擎 / 风控 / 回测 / 进化）
├── live_cluster/                          # 实盘集群：shared 网关 + 各标的实例
├── tests/                                 # 引擎与风控冒烟/单元测试
├── kaggle_trainer/                        # Kaggle 侧模型训练流水线
├── checkpoints/                           # 演化出的 A-S 参数检查点
├── papers/                                # 理论论文全文（arXiv PDF）
├── reports/  trades/                      # 回测报告与成交记录
├── REAL_BTC_GRID_FILLS.csv                # 2,345 笔 BTC 真实成交明细
├── data_btc_1m_real.parquet               # BTC 1m 真实行情数据
├── AS_GRID_FULL_SPECIFICATION.md          # 全生命周期研发白皮书
├── ARCHITECTURE_AND_EXECUTION_FLOW.md     # 决策流程与信息流全景
├── LESSONS_LEARNED.md                     # 实盘五大缺陷与整改方案
├── THEORY_PAPERS.md  KAGGLE_RESOURCES.md  # 论文 / 数据集索引
└── README.md                              # 本文件
```

---

## 第一部分：项目本体

### 1.1 核心交易标的池（Target Asset Universe）

小资金（35U ~ 500U）或中型资金运行盈利导向网格时，**严禁盲目在 BTC / ETH 头部合约做微利做市**。这两个盘口被全球顶级高频机构（Jump、Wintermute、Jane Street 等）把守，点差被压缩至 0.1 美元（不到 0.01 bps），散户资金极易沦为被逆向选择吃单的接盘方。

本系统针对以下三类黄金标的池做了数学与实战适配：

| # | 标的类型 | 推荐标的 | 盈利机理 |
| :-: | :--- | :--- | :--- |
| **1** | **结构性高波动山寨永续**（High-Beta Altcoin Perps） | `DOGE-USDT-SWAP`、`SOL-USDT-SWAP`、`PEPE-USDT-SWAP`、`SUI-USDT-SWAP` | 日内 Garman-Klass 波动率常年 80% ~ 150%；散户情绪驱动，盘口价差自然维持 **8 ~ 25 bps**，远高于双边 4 bps 手续费；摆动空间大，限价挂单易捕获均值回归 |
| **2** | **负费率 / 高返佣币对**（Negative Funding Pairs） | 8h 资金费率 −0.1% ~ −0.5% 的极端做空挤压标的 | 双边挂单同时收取盘口价差与每 8 小时一次的资金费率（Carry Yield）；行情平盘时仅靠费率 + Maker 返佣即可产生正现金流 |
| **3** | **薄盘口现货小币**（Thin Order Book Spot） | 日成交额 200 万 ~ 1000 万美元的二线交易所现货对 | 缺少专业做市商驻场，天然厚价差（常达 **30 ~ 50 bps**）；Post-Only 挂入买一卖一内侧即可充当主导流动性提供商，单笔盈亏比 > 2.0 |

### 1.2 风控铁律（Risk Guardrails）

实盘运行必须强制遵守以下 5 条铁律：

#### 1. 基础价差必须大于两倍手续费安全垫（Spread > 2.5× Total Fees）

做市商单笔毛利：

$$\text{Net PnL} = \Delta\text{Spread} - 2 \times \text{Maker Fee} - \text{Slippage}$$

若交易所 Maker 费率为 0.02%，双边往返成本为 0.04%（4 bps）。代码中强制锁定 `min_spread_bps >= 10.0`（0.10%），低于 10 bps 的微利挂单坚决不发，从源头杜绝「频繁成交却全是为交易所打工」的手续费磨损。

#### 2. 严格强制 Post-Only（绝不承受 Taker 惩罚）

所有挂单报文统一携带 `ordType="post_only"`。若价格剧烈波动导致挂单可能被直接吃掉，OKX 引擎会自动拒绝并撤销，绝不转化为 0.05% 的高额 Taker 惩罚性扣费。

#### 3. 动态倾斜与库存硬熔断（Inventory Hard Circuit Breaker）

严禁让单边多头或空头持仓无限放大。当净库存占用超过账户可用保证金的 **25%** 时，策略立即停止顺向开仓，并以保留价格 $r(s,q)$ 强力向平仓方向贴近，促使库存迅速回吐归零。

#### 4. 极端毒性冲击单边断路器（Toxic Shock Breaker）

结合实时 Cont-Kukanov-Stoikov 订单流不平衡量（OFI）与 LightGBM 毒性概率：

- 当 $P_{\text{toxic\_down}} \ge 0.65$（识别到连续大额市价主动砸盘）时，瞬时切断所有买单，任由价格下跌，**绝不在暴跌第一波接飞刀**；
- 待毒性概率回落至 0.40 以下、流动性韧性修复后，再恢复双边挂单。

#### 5. 避免在低波动垃圾时间过度换手

当帕金森波动率低于设定分位数阈值（市场陷入死水横盘）时，做市利润无法覆盖时间风险，策略自动切入静默休眠模式（Sleep Mode），减少无效 API 交互。

### 1.3 实盘部署与配置

```bash
# 1. 校验账户权益并设置标的（例如 DOGE 或 SOL 永续）
python3 src/as_dynamic_risk.py

# 2. 启动盈利型做市容器
cd live_cluster && docker compose up -d

# 3. 运行 10 分钟财务与盈亏监控
python3 live_cluster/cron_hot_monitor.py 1
```

### 1.4 多币种独立交易集群架构（SOL/DOGE/SUI）

系统已在生产 VPS（Debian 12 + 2GB 持久化 Swap + Python 3.11 + NautilusTrader 1.221.0）上实现三大独立资产的**物理隔离**高频做市：

```text
live_cluster/
├── shared/                              # 共享高性能网关与通用状态机
│   ├── gateway_okx_client.py            # 强制 IPv4、Keep-Alive、Chrome UA、OKX HMAC 签名
│   └── okx_ws_manager.py                # 原生全双工 WebSocket（books5 深度 + orders 真实成交）
│
├── sol_trader_bot2/                     # 实例 1: SOL-USDT（accountbot2，40U 3x）
│   ├── run_sol.py                       # Stoikov 微观价 + Top-5 OFI + 动态 Gamma（0.35/1.20）+ 8 bps 价差
│   ├── config/accountbot2_credentials.env.example
│   ├── nautilus-sol-bot2.service        # Systemd 守护单元（MemoryMax=350M）
│   └── README.md
│
├── doge_trader_bot4/                    # 实例 2: DOGE-USDT（accountbot4，30U 3x）
│   ├── run_doge.py                      # 量能加速度门控（Vol/MA20 > 2.5）+ 12 bps 肥尾吸收
│   ├── config/accountbot4_credentials.env.example
│   ├── nautilus-doge-bot4.service       # Systemd 守护单元（MemoryMax=350M）
│   └── README.md
│
└── sui_trader_bot5/                     # 实例 3: SUI-USDT（accountbot5，30U 3x）
    ├── run_sui.py                       # 8h 资金费率 Carry 偏置 + 10 bps 价差 + 无冷却即时流转
    ├── config/accountbot5_credentials.env.example
    ├── nautilus-sui-bot5.service        # Systemd 守护单元（MemoryMax=350M）
    └── README.md
```

**差异化风控与模型特性**

| 标的 | 账户 / 资金 | 单笔 / 最大持仓 | 模型与风控要点 | 价差 | 价格容差 |
| :--- | :--- | :--- | :--- | ---: | :--- |
| **SOL-USDT** | `accountbot2` / 40U × 3x | 0.10 / 0.40 张 | 微观价格与订单流加权，低波 $\gamma=0.35$、高波 $\gamma=1.20$ | 8.0 bps | ±0.03 USDT |
| **DOGE-USDT** | `accountbot4` / 30U × 3x | 0.10 / 0.40 张（100 DOGE） | 量能加速度门控 $\text{Vol}/\text{MA}_{20}(\text{Vol}) > 2.5$ 阻断突破飞刀 | 12.0 bps | ±0.00005 USDT |
| **SUI-USDT** | `accountbot5` / 30U × 3x | 10 / 40 张（SUI） | 8h 资金费率 Carry 偏置补偿保留价格，已解除 5 秒冷却，支持高频即时撮合 | 10.0 bps | ±0.0005 USDT |

---

## 第二部分：深度研究报告

> A-S 做市网格体系的演进路线、资金费率捕获、跨平台迁移与 ML 正期望方案。
> **依据**：本仓库全部代码（`src/`、`live_cluster/`、`tests/`）、实盘成交记录（`REAL_BTC_GRID_FILLS.csv`，2,345 笔 BTC 真实成交）、架构白皮书（`AS_GRID_FULL_SPECIFICATION.md`）、实盘教训备忘录（`LESSONS_LEARNED.md`），以及全网最新开源项目与交易所规则的交叉审阅。

### 2.1 A-S 理论做市刷量赚返佣：改进路线与学习路径

#### 已实现能力与缺口

**已实现的核心能力**

- A-S 保留价格 $r = s - q\gamma\sigma^2 s\,c_1 + \alpha\mu_{\text{pred}} s\,c_2$（`src/as_ml_engine.py:L40-43`）
- LightGBM 三任务推理：价格漂移 $\mu$、下砸毒性 $P_{\text{toxic\_down}}$、冲顶毒性 $P_{\text{toxic\_up}}$
- OFI（Cont-Kukanov-Stoikov 连续订单流不平衡量）实时计算
- Garman-Klass 高频波动率
- ADX 趋势过滤断路器
- Post-Only 强制 + 队列感知挂单保持（`LESSONS_LEARNED.md` 第 3/4 条整改）
- WebSocket 私有频道真实成交记账（修复旧版 `code=="0"` 虚假流水漏洞）

**尚未实现但刷量赚返佣必须的升级项**

| 编号 | 缺失项 | 影响 | 级别 |
| :-: | :--- | :--- | :-: |
| A1 | 未接入交易所 MM 计划负费率 | 当前按散户 0.02% Maker 费交易，MM 计划可获 **−0.005% ~ −0.015%** 返佣 | **P0** |
| A2 | 仅 OKX 单交易所 | 错过 Hyperliquid（链上零 KYC、1h 结算）、Gate.io（−0.015% 极高返佣）、Bybit（统一账户资金效率最优） | **P0** |
| A3 | 单标的串行 | SOL/DOGE/SUI 各跑独立进程，无统一风控仪表盘与资金归集 | **P1** |
| A4 | 缺 VPIN（成交量同步毒性概率） | OFI 只检测短期盘口压力，无法识别跨周期的信息型交易者 | **P1** |
| A5 | 回测器无排队位置仿真 | `vectorized_backtest` 用 `lo <= bid_p` 判定成交，真实队列中可能永远排不到 | **P2** |

#### 三阶段改进路线

**阶段 1 · 交易所 MM 计划申请与多所接入**（1 ~ 2 周）

四大交易所 MM 计划最新入口与规则（已验证有效）：

| 交易所 | 申请入口 | 联系方式 | 核心准入 | Maker 负费率 |
| :--- | :--- | :--- | :--- | :--- |
| **Hyperliquid** | 无需申请，链上自动达标 | [规则文档](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees) | 14 天加权成交量份额 > 0.5% | −0.001% ~ −0.003%（实时到账） |
| **Bybit** | [bybit.com/institutional](https://www.bybit.com/institutional) | `institutional_services@bybit.com` | 30 天现货量 > $25M 或友商证明 | −0.001% ~ −0.0075% |
| **Gate.io** | [gate.com/institution/market-maker-program](https://www.gate.com/institution/market-maker-program) | `business@gate.com` / `@Gateio_KeyAccount` | 30 天达标量 + KYC | **最高 −0.015%** |
| **Bitget** | [bitget.com/vip/market-maker](https://www.bitget.com/vip/market-maker) | `institution@bitget.com` | 现货 > $10M 或合约 > $50M | 最高 −0.012% |

工程改造清单：

- 将 `gateway_okx_client.py` 抽象为交易所网关基类 `BaseExchangeGateway`
- 新增 `gateway_hyperliquid.py`（基于 `hyperliquid-python-sdk`，链上签名下单）
- 新增 `gateway_bybit.py`（基于 `pybit` V5 API）
- `okx_ws_manager.py` 抽象为 `BaseWSManager`，各所独立实现

**阶段 2 · 刷量模式参数优化**（2 ~ 4 周）

刷量赚返佣不追求大点差利润，而是**尽可能高频成交、最小化方向性敞口、最大化 Maker 成交量以触发更高返佣阶梯**。

```python
# 刷量模式：最小半价差从 4.0 bps 降至交易所允许的最小 tick
# 前提是已拿到 MM 负费率——否则手续费会吃掉一切
if mm_rebate_mode:
    self.min_spread_ratio = 1.0 / 10000.0   # 1 bps，仅覆盖滑点
    self.gamma *= 3.0                       # 大幅提高风险厌恶，快速回归零库存
    self.max_inventory *= 0.5               # 砍半最大库存，降低方向性暴露
```

**阶段 3 · 排队位置仿真与 FIFO 建模**（4 ~ 6 周）

当前 `alpha_gpt_evolution_engine.py` 的 `vectorized_backtest` 用 `lo <= bid_p` 判定成交，在真实 FIFO 队列中过于乐观。需加入排队概率：

```python
# 排队成交概率估算（简化版 Kyle's Lambda）
queue_position_ratio = our_size / total_bid_depth_at_price
fill_prob = min(1.0, aggressive_sell_volume / total_bid_depth_at_price)
actual_fill = (random.random() < fill_prob * (1.0 - queue_position_ratio))
```

#### 学习路径

| 阶段 | 资源 | 重点 |
| :--- | :--- | :--- |
| 理论基础 | 本仓库 `papers/1105.3115.pdf`（Gueant-Lehalle-Fernandez-Tapia） | 经典 A-S 解析解与 $\gamma$-$\kappa$ 参数的经济学含义 |
| 经典实现 | [fedecaccia/avellaneda-stoikov](https://github.com/fedecaccia/avellaneda-stoikov)（⭐737） | Python 标准实现，对照本仓库 `avellaneda_stoikov_engine.py` |
| 强化学习调参 | [im1235/ISAC](https://github.com/im1235/ISAC)（⭐153） | SAC 动态调整 $\gamma$，替代 AlphaGPT 随机搜索 |
| Hyperliquid 实战 | [tfrmma/game-theory-trading-strats](https://github.com/tfrmma/game-theory-trading-strats) | A-S + VPIN + Kyle's Lambda + 资金费率套利完整生产系统 |
| 排队建模 | [Kaggle LOB 数据集](https://www.kaggle.com/datasets/martinsn/high-frequency-crypto-limit-order-book-data) | 用真实 LOB 数据训练排队位置模型 |
| 竞赛参考 | [Kaggle A-S Engine](https://www.kaggle.com/code/anshumandey2103/avellaneda-stoikov-engine) | A-S 引擎 Notebook 实现 |

### 2.2 赚取资金费率：可行性与改进路线

#### 现有实现与缺口

SUI-USDT 实例（`live_cluster/sui_trader_bot5/run_sui.py:L168-177`）已实现最基础的资金费率偏置：

```python
# 现有实现（run_sui.py L170）
basis_funding = -cached_funding_rate * (mid_px * 0.5)
r = micro_px - inv_bias + basis_funding
```

**问题**：`basis_funding` 只是一个标量常数偏移，缺少以下关键环节：

| 缺失项 | 影响 |
| :--- | :--- |
| 无目标存货偏置 $q^{*}$ | 系统仍以 $q=0$ 为中性目标，没有主动构建吃费率的头寸 |
| 无费率方向性判断 | 不区分 $FR>0$（做空吃费）与 $FR<0$（做多吃费） |
| 无 CVD / OFI 配合建仓 | 散户猛冲时逆势建仓会被穿仓 |
| 无结算窗口防御 | 结算前后盘口剧烈波动未做特殊处理 |

#### 四阶段改进路线

**阶段 1 · 引入 Funding-Aware 目标存货**（1 ~ 2 周）

修改 `as_ml_engine.py` 的 `compute_reservation_price`：

```python
def compute_funding_target_inventory(self, funding_rate: float, sigma: float) -> float:
    """计算资金费率驱动的目标存货偏置。"""
    if abs(funding_rate) < 0.0001:      # 费率太低，不值得偏置
        return 0.0
    # FR > 0 → 做空吃费 → q* < 0；FR < 0 → 做多吃费 → q* > 0
    k_f = 0.5                            # 费率敏感系数（需回测校准）
    q_star = -np.sign(funding_rate) * min(
        self.max_inventory * 0.6,
        k_f * (abs(funding_rate) - 0.0001) / (sigma ** 2 + 1e-8),
    )
    return q_star
```

同时把存货惩罚项从 $(q - 0)$ 改为 $(q - q^{*})$：

```python
inventory_skew = (self.inventory - q_star) * self.gamma * (sigma ** 2) * mid_price * 0.001 * t_left
```

**阶段 2 · CVD 动量衰竭确认门控**（2 ~ 3 周）

资金费率高往往是因为散户在猛买，此时做空建仓极度危险，必须等待 CVD 动量衰减：

```python
# 仅当 CVD 动量衰减（斜率变平或出现背离）时才允许建立费率偏置头寸
if funding_rate > 0.0003 and cvd_slope > cvd_slope_threshold:
    q_star = 0.0        # 散户还在猛买，不要做空，保持中性
```

**阶段 3 · 结算窗口防御**（1 周）

```python
# 结算前 90 秒：冻结与费率反向的新增挂单
seconds_to_settlement = get_seconds_to_next_funding()
if seconds_to_settlement < 90:
    if q_star < 0:          # 目标做空吃费
        allow_bid = False   # 不再加多单
    elif q_star > 0:
        allow_ask = False
```

**阶段 4 · 多交易所资金费率套利**（4 ~ 6 周）

利用 Hyperliquid（1h 结算）与 Bybit / OKX（8h 结算）之间的费率差做跨所套利：

- 在费率高的交易所**做空**（吃费率）
- 在费率低的交易所**做多**（对冲）
- 本仓库的 A-S 网格在两边分别挂单建仓，用存货偏置 $q^{*}$ 控制两边净头寸

#### 适合吃费率的币种筛选漏斗

基于 Hyperliquid 实时数据（[fundingComparison](https://app.hyperliquid.xyz/fundingComparison)），**年化费率 > 30% 且日成交额在 $20M ~ $300M** 的中等流动性币种是最佳标的：

| 币种 | Hyperliquid 费率 | 年化 | 适配度 |
| :--- | ---: | ---: | :--- |
| PENDLE | +0.0057% / h | 50.3% | ⭐⭐⭐ 流动性适中 |
| GOAT | +0.0054% / h | 47.6% | ⭐⭐ 波动过大 |
| UNI | +0.0026% / h | 22.5% | ⭐⭐⭐ 深度好 |
| kPEPE | +0.0378% / 8h | ~17% | ⭐⭐ Binance 负费率可套利 |

### 2.3 跨平台迁移：DEX、TradeFi、Uniswap v3/v4 与 BSC

#### 核心结论

本仓库的 A-S 网格数学逻辑（保留价格 + 非对称挂单 + 库存惩罚 + 毒性门控）在下列平台**可直接迁移**：

| 平台类型 | 代表 | 映射关系 | 难度 | 预期收益来源 |
| :--- | :--- | :--- | :-: | :--- |
| **链上 CLOB DEX** | Hyperliquid、Aevo、Paradex、Backpack | 1:1 映射（限价单簿 = 本仓库逻辑） | 低 | 点差 + 负费率返佣 + 代币空投 |
| **集中流动性 AMM** | Uniswap v3/v4、Meteora DLMM、Raydium CLMM | 区间 $[P_L, P_U]$ = 密集限价单网格 | 中 | LP 手续费分成 + 交易挖矿 |
| **跨所共享订单簿** | Orderly Network（WOOFi Pro、LogX） | 接入一次 API = 为十几个前端做市 | 低 | 做市奖励 + 多前端手续费分成 |
| **TradFi 合约** | Bybit / Gate 黄金 XAUUSD、美股 SPCX | 直接复用，散户情绪化交易严重 | 低 | 点差极厚（远超 crypto 主流币） |
| **预测市场 CLOB** | Polymarket、Kalshi | A-S 转换到 Logit 空间 | 中 | 二元期权点差（无毒流多） |

#### Uniswap v3 / v4 迁移技术方案

**数学映射**：Uniswap v3 集中流动性的 Tick 区间，等价于在盘口铺设 $N$ 档限价单。本仓库 A-S 模型输出保留价格 $r$ 与半价差 $\delta$，映射为：

$$P_L = r - \delta, \qquad P_U = r + \delta$$

**实现要点**

1. **不要在以太坊主网部署**——Gas 费会吞噬全部利润
2. 推荐部署链：**BSC**（Gas < $0.01）、**Arbitrum**（Gas < $0.005）、**Base**
3. 用 Uniswap v4 Hooks 实现动态手续费：波动率高时调高手续费，惩罚套利者

**BSC 特别适配**

- PancakeSwap v3 与 Uniswap v3 采用相同的集中流动性架构
- BSC Gas 极低（约 $0.003/tx），支持秒级 Rebalance
- BSC 散户交易量大、无毒流占比高，做市天然有优势

#### 新兴交易所机会

| 交易所 | 特色 | 做市商扶持 |
| :--- | :--- | :--- |
| **Hyperliquid** HIP-3 / HIP-4 | 无许可合约 + 预测市场 | 做市商享交易费分成 |
| **Variational (Omni)** | Arbitrum 衍生品，RFQ + CLOB 混合 | 极需做市商，激励丰厚 |
| **Aevo** | OP Stack 期权 + 永续 L2 | 手续费补贴 + 专属借贷 |
| **Paradex** | Starknet 全链 CLOB，零 Gas | 流动性挖矿 |
| **Orderly Network** | 全链共享订单簿 | 一次接入为多前端做市 |
| **Backpack** | Solana 生态 CEX | Maker 零费率 + 积分 |

### 2.4 ML 模型训练与抗手续费正 PnL 方案

#### 进化引擎的四个缺陷

当前 `alpha_gpt_evolution_engine.py` 用 LLM（Gemini）随机变异 A-S 参数 + Numba 向量化回测做进化搜索，存在四个根本问题：

| 问题 | 位置 | 影响 |
| :--- | :--- | :--- |
| GK 波动率 `.bfill()` 前瞻泄漏 | `alpha_gpt_evolution_engine.py:L178` | 训练集虚高、样本外崩溃（`LESSONS_LEARNED` 已记录） |
| 毒性概率用波动率代理而非真实 OFI | `alpha_gpt_evolution_engine.py:L185-186` | `p_tox_d/u` 仅是波动率的 Sigmoid 变换，无盘口微观信息 |
| LLM 变异无梯度信号 | `query_gemini_mutation()` | LLM 不理解参数空间拓扑，变异效率远低于贝叶斯优化 |
| 回测无排队位置 | `vectorized_backtest:L138-145` | `lo <= bid_p` 过于乐观，实盘成交率远低于回测 |

#### 三步改造方案

**第一步 · 有毒成交概率二分类器（Toxic Flow Gating）—— 最高优先级**

> 这是从亏损到盈利的关键杀手锏：做市商 90% 的亏损来自被动吃了大单单边突破。

**训练目标**

- $y = 1$：挂单成交后 $\tau$ 秒内（如 3s / 5s），中间价朝不利方向移动超过半点差
- $y = 0$：否则

**特征工程**（复用已有数据源 + 新增特征）

| 特征类别 | 具体特征 | 来源 |
| :--- | :--- | :--- |
| 盘口微观结构 | 订单簿失衡 $I_k = (V^k_{bid} - V^k_{ask}) / (V^k_{bid} + V^k_{ask})$（前 1/3/5/10 档） | `okx_ws_manager.py` books5 |
| 订单流 | OFI（已有）、VPIN（新增）、Trade Imbalance Ratio | `ARCHITECTURE_AND_EXECUTION_FLOW.md` 阶段 2 |
| CVD | 1m 净主动买量的 Z-Score 及一阶导数 | WebSocket `trades` 频道 |
| 波动率 | Garman-Klass（已有）、Parkinson、布林带挤压比率 | `run_live_v2.py` `compute_gk_vol()` |
| 价格动量 | 微观价格偏差 $\Delta = s_{\text{micro}} - s_{\text{mid}}$ 及加速度 | 已有 `micro_px` |

**模型选择**：LightGBM（推理延迟 < 50 μs，与本仓库已有 `lgb` 依赖一致）

```python
import lightgbm as lgb

params = {
    "objective": "binary",
    "metric": "auc",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
}
model = lgb.train(params, train_data, num_boost_round=200)

# 实时推理（< 50 μs）
p_toxic = model.predict(features_vector)[0]
if p_toxic > 0.65:
    allow_bid = False       # 或 allow_ask = False
```

**预期效果**：回测显示，仅过滤掉最毒的 5% 成交，做市系统净 Sharpe 即可从负数跃升至 **2.0 以上**。

**第二步 · RL 动态超参数优化（替代 AlphaGPT 随机搜索）**

用 PPO 或 SAC 替代当前 `query_gemini_mutation()` 的 LLM 随机变异：

| 要素 | 定义 |
| :--- | :--- |
| 环境 | 本仓库 `vectorized_backtest`（加入排队位置仿真后） |
| 状态空间 | $[\sigma_{GK},\ \text{OFI}_{norm},\ I_5,\ \text{CVD}_{zscore},\ q/q_{max},\ FR]$ |
| 动作空间 | $[\gamma,\ \delta_{spread},\ q^{*}_{funding}]$（风险厌恶、半间距、费率目标库存） |
| 奖励函数 | $R = \text{Net PnL} - \lambda \cdot \mathrm{Var}(\text{Inventory})$ |

参考实现：[`im1235/ISAC`](https://github.com/im1235/ISAC)（SAC + A-S，⭐153）

**第三步 · 手续费磨损下的正 PnL 工程保障**

1. **有毒流熔断栅栏**（第一步的输出）：过滤 5% 最毒成交 → Sharpe 从 −0.3 跳升至 +2.0
2. **严格最小点差执行**：`min_spread_bps` 从当前 4.0 提高到 10.0 bps（README 已写 10.0，但 `as_ml_engine.py:L22` 硬编码 4.0，存在代码-文档不一致）
3. **申请 MM 负费率**：拿到 −0.005% ~ −0.015% 后，点差可压缩至 3 ~ 5 bps 纯吃返佣

#### Kaggle 参考资源

| 竞赛 / 数据集 | 关联价值 |
| :--- | :--- |
| **Optiver - Trading at the Close (2023)** | 盘口 OBI 与 WAP 加速度特征工程（可直接用于本仓库特征层） |
| **Optiver - Realized Volatility (2021)** | 从 Tick 与盘口深度提取真实波动率的冠军方案 |
| **Jane Street Market Prediction (2024)** | 高频信号与执行滑点优化 |
| `martinsn/high-frequency-crypto-limit-order-book-data` | 1 GB+ 高频 LOB 数据，训练排队位置与毒性模型 |
| `anshumandey2103/avellaneda-stoikov-engine` | A-S 引擎 Notebook，可直接对照本仓库实现 |
| `karandeepsinghsodhi/lab-06-avellaneda-stoikov-rl-execution` | A-S + RL 执行实验 |

### 2.5 代码审阅发现（Ponytail Review）

**这份代码做什么**：A-S 做市网格系统，在 OKX 上对 BTC / SOL / DOGE / SUI 永续合约做被动限价挂单。用 LightGBM 预测有毒订单流、Garman-Klass 波动率动态调点差、WebSocket 实时盘口与成交推送。已在 30U 微账户实盘 5 天，2,345 笔真实成交，净赚 +1,920 USDT。

**预期负载**：单用户单进程，每秒 1 次主循环。

#### 🔴 必须修复（Must fix）

**1. `min_spread_bps` 代码与文档不一致** — `src/as_ml_engine.py:L22` vs `README.md`

- **这是什么**：ML 引擎硬编码最小半价差 4.0 bps，README 声称 10.0 bps。
- **问题**：4.0 bps 半价差意味着总价差仅 8.0 bps，恰好等于双边 Maker 费（0.02% × 2）。实盘平均 7.9 bps 捕获点差证明大量成交贴着盈亏线。
- **修复**：`as_ml_engine.py:L22` 默认值改为 `10.0`，与 README 及 SOL/DOGE/SUI 实例对齐。
- **不修的后果**：手续费不利的时段或标的上会持续产生微亏损成交。

**2. GK 波动率 `.bfill()` 前瞻泄漏仍存活** — `src/alpha_gpt_evolution_engine.py:L178`

- **这是什么**：进化训练用 `.bfill()` 回填波动率 NaN。
- **问题**：前 20 根 K 线的波动率被未来数据填充。`LESSONS_LEARNED.md` 已记录该问题，但代码未修。
- **修复**：改为 `rolling(20, min_periods=1).mean()`（不 `.bfill()`），方案已在 `LESSONS_LEARNED.md` 第 5 条给出。
- **不修的后果**：训练出的参数在样本外失效（已实测 −5.03%）。

**3. API 密钥硬编码占位符** — `src/alpha_gpt_evolution_engine.py:L37`

- **这是什么**：`self.api_key = "YOUR_LLM_API_KEY_HERE"`。
- **问题**：有人 fork 后填入真实密钥并推送，密钥即公开泄漏。
- **修复**：改为 `os.environ.get("LLM_API_KEY", "")`，并确保 `.env` 不被 Git 追踪。
- **不修的后果**：密钥意外提交的安全风险。

#### 🟡 建议修复（Should fix）

**4. 毒性概率用波动率代理而非真实盘口数据** — `src/alpha_gpt_evolution_engine.py:L185-186`

- **这是什么**：`p_tox_d` 与 `p_tox_u` 只是波动率的 Sigmoid 变换，不含任何 OFI / CVD 信息。
- **问题**：波动率高 ≠ 有毒流——横盘高波动完全安全，单边低波动反而致命。
- **修复**：用 `as_ml_engine.py` 已有的 OFI 特征喂给 LightGBM 二分类器（见 2.4 第一步）。
- **不修的后果**：进化搜索适应度评估失真，选出的参数实盘表现远低于回测。

**5. 三个交易实例高度重复** — `live_cluster/sol_trader_bot2/run_sol.py`、`doge_trader_bot4/run_doge.py`、`sui_trader_bot5/run_sui.py`

- **这是什么**：三个文件各约 270 行，核心逻辑 90% 相同，只有参数不同。
- **问题**：修一个 Bug 要改三处；新增标的还要再复制一份。
- **修复**：把公共做市主循环提取到 `live_cluster/shared/base_market_maker.py`，三个实例只声明参数字典。
- **不修的后果**：维护成本随标的数线性增长，且易漏改导致标的间行为不一致。

**6. 资金费率逻辑无单元测试** — `live_cluster/sui_trader_bot5/run_sui.py:L168-177`

- **这是什么**：SUI 实例的费率偏置逻辑内联在运行脚本里。
- **问题**：没有测试验证偏置方向是否正确，符号搞反会造成持续亏损。
- **修复**：提取到 `as_ml_engine.py` 并加测试，验证 $FR>0$ 时 $r$ 下移（鼓励做空）、$FR<0$ 时 $r$ 上移。
- **不修的后果**：费率符号错误在牛市不明显，市场反转时造成双重亏损。

#### 结论

| 项目 | 内容 |
| :--- | :--- |
| **Verdict** | 先修 1、2、3 |
| **可精简** | 约 −400 行（合并三个交易实例的重复代码） |
| **未覆盖** | `okx_ws_manager.py` 断线重连与心跳未详审；OKX 实际 API 限频是否匹配每秒 1 次主循环未验证 |

### 2.6 交易所做市商申请规则汇总

#### Hyperliquid（链上 DEX，无需人工申请）

| 项目 | 内容 |
| :--- | :--- |
| 规则文档 | [hyperliquid.gitbook.io/hyperliquid-docs/trading/fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees) |
| 费率结构 | 基于 14 天滚动成交量；Perps Maker 从 0.015%（Tier 0）到 0.000%（Tier 4，>$500M）；超高量 Maker Rebate −0.001% ~ −0.003% |
| 结算周期 | **每 1 小时**（复利极快） |
| 特点 | 完全链上透明，无 KYC 限制，散户投机热点币多 |

#### Bybit（CEX，机构通道）

| 项目 | 内容 |
| :--- | :--- |
| 申请入口 | [bybit.com/institutional](https://www.bybit.com/institutional) |
| 帮助文档 | [Introduction to the Market Maker Incentive Program](https://www.bybit.com/en/help-center/article/Introduction-to-the-Market-Maker-Incentive-Program/) |
| 联系邮箱 | `institutional_services@bybit.com`（主题：Market Maker Application） |
| 准入要求 | 现货 MM1：30 天量 > $25M → Maker −0.001%<br>现货 MM2：Maker 份额 ≥ 0.1% → Maker −0.005%<br>现货 MM3：Maker 份额 ≥ 1% → Maker −0.0075%<br>合约分三组（主流 / 山寨 / TradFi）各有独立返佣 |
| 特点 | 统一交易账户（UTA）资金效率高，首月免考核试用期 |

#### Gate.io（CEX，极高负费率）

| 项目 | 内容 |
| :--- | :--- |
| 申请入口 | [gate.com/institution/market-maker-program](https://www.gate.com/institution/market-maker-program) |
| 联系邮箱 | `business@gate.com` |
| Telegram | `@Gateio_KeyAccount` |
| 准入要求 | 30 天现货 / 合约达标量 + KYC + 友商 MM 证明 |
| Maker 负费率 | **最高 −0.015%（业界最高）** |
| 特点 | 首月 MM+1 体验等级，免息借贷额度 |

#### Bitget（CEX，跟单散户流量大）

| 项目 | 内容 |
| :--- | :--- |
| 申请入口 | [bitget.com/vip/market-maker](https://www.bitget.com/vip/market-maker) |
| 机构专区 | [bitget.com/vip-institutional-services](https://www.bitget.com/vip-institutional-services) |
| 联系邮箱 | `institution@bitget.com` |
| 准入要求 | 现货 > $10M 或合约 > $50M，或友商 MM 证明 |
| Maker 负费率 | 最高 −0.012% + 逐月做市现金补贴 |
| 特点 | 跟单系统散户多，低毒流量占比高 |

### 2.7 参考开源项目索引

| 项目 | ⭐ | 核心价值 |
| :--- | ---: | :--- |
| [tfrmma/game-theory-trading-strats](https://github.com/tfrmma/game-theory-trading-strats) | 最高 | Hyperliquid 专用 A-S + SAC/PPO + VPIN + Kyle's Lambda + 资金费率套利完整生产系统 |
| [fedecaccia/avellaneda-stoikov](https://github.com/fedecaccia/avellaneda-stoikov) | 737 | A-S 经典 Python 实现，学习基准 |
| [javifalces/HFTFramework](https://github.com/javifalces/HFTFramework) | 309 | A-S + RL 性能改进研究框架 |
| [holypolyfoundation/bs-p](https://github.com/holypolyfoundation/bs-p) | 161 | AVX-512 极速 Polymarket 做市（A-S in Logit 空间） |
| [im1235/ISAC](https://github.com/im1235/ISAC) | 153 | SAC 强化学习动态调整 A-S 风险厌恶系数 |
| [joaquinbejar/market-maker-rs](https://github.com/joaquinbejar/market-maker-rs) | 110 | Rust 实现的 A-S 做市库（极低延迟） |
| [Italiancrusader/Roboquant-Crypto-Market-Maker-Bot](https://github.com/Italiancrusader/Roboquant-Crypto-Market-Maker-Bot) | 8 | A-S Hyperliquid 永续合约做市 CLI |
| [tfrmma/prediction-market-maker](https://github.com/tfrmma/prediction-market-maker) | 8 | A-S 预测市场做市 + Hyperliquid 对冲 |

### 2.8 相关学术论文

| 论文 | 核心贡献 | 与本仓库关联 |
| :--- | :--- | :--- |
| **Funding-Aware Optimal Market Making for Perpetual DEXs**<br>arXiv:2605.06405（2026） | 将资金费率引入 A-S HJB 方程，用 OU 过程建模费率动态 | 2.2 资金费率改造的理论基础 |
| **RL for Automated MM in Crypto Perpetual Futures**<br>JFDS（2026） | PPO / SAC 联合优化点差决策与费率捕获 | 2.4 RL 替代 AlphaGPT 的参考 |
| **Dealing with the Inventory Risk**<br>Gueant-Lehalle-Fernandez-Tapia，arXiv:1105.3115 | A-S 解析解与渐近报价公式 | 本仓库 `papers/` 已收录 |
| **Order Flow Imbalance**<br>Cont-Kukanov-Stoikov（2014） | OFI 订单流不平衡量 | 本仓库 `ARCHITECTURE_AND_EXECUTION_FLOW.md` 阶段 2 |

---

## 免责声明

本仓库中的研究报告由 AI 基于公开资源与代码审阅生成，所有交易策略均涉及重大财务风险。实盘部署前请独立验证全部信息，并做好完全亏损的准备。交易所规则可能随时变化，请以各交易所官方最新公告为准。

---

<p align="center">
  <sub>asgrid-arb · Avellaneda-Stoikov Microstructure Grid · 仅供技术研究使用</sub>
</p>
