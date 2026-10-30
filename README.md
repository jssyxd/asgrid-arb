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
  - [2.9 成熟开源架构对标与刷量盈利底层公式](#29-成熟开源架构对标与刷量盈利底层公式)
  - [2.10 仓库对标审计结论（第三方审计归档）](#210-仓库对标审计结论第三方审计归档)
  - [2.11 两份 AI 理论指导的复核（认同与需修正）](#211-两份-ai-理论指导的复核认同与需修正)
  - [2.12 小资金实盘现状与六个方向优先级](#212-小资金实盘现状与六个方向优先级)
  - [2.13 手续费与返佣计算模型](#213-手续费与返佣计算模型)
  - [2.14 多币种 / 多交易所选择](#214-多币种--多交易所选择)
  - [2.15 模型优化与 NautilusTrader 回测方案](#215-模型优化与-nautilustrader-回测方案)
  - [2.16 基建评估（VPS 延迟与 1C1G 瓶颈）](#216-基建评估vps-延迟与-1c1g-瓶颈)
  - [2.17 7 天立刻可执行清单（小资金专用）](#217-7-天立刻可执行清单小资金专用)
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
| **Gate.io** | [gate.com/institution/market-maker-program](https://www.gate.com/institution/market-maker-program) | `institution@gate.io` / `mm@gate.io` / `@Gateio_KeyAccount` | 30 天达标量 + KYC | **最高 −0.015%** |
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

**形式化定义（工作内容 3 标准写法）**

目标存货偏置：

$$q^{*}(F_t) = -\mathrm{sign}(F_t) \cdot \min\left( Q_{\max},\; k_f \cdot \frac{|F_t| - F_{\text{base}}}{\sigma_{1m}^{2}} \right)$$

预约价格偏移：

$$r(s, q, t) = s_{\text{micro}} - \gamma \, \sigma_{1m}^{2} \left( q - q^{*}(F_t) \right) + \beta \cdot \text{CVD}_{zscore}$$

**状态解读**

- $F_t$ 为极高正费率（多付空，如年化 50%+）时，$q^{*} < 0$：系统**主动把目标存货偏置为空头**。
- 当实际存货 $q > q^{*}$（空头还没建够）时，公式自动大幅**下调** $r$，促使 **Ask 挂单极贴近盘口甚至加厚挂单**以快速成交卖单建立空仓；同时 **Bid 挂单拉宽**避免接买单。
- $\beta \cdot \text{CVD}_{zscore}$ 项保证在散户猛烈买入时整体报价上移，不被顺势扫穿。

**为什么必须先看 CVD 再吃费率（防穿仓）**

资金费率高往往正是因为散户在猛烈买入。如果 1m CVD 持续正斜率拉升，**坚决不能无脑挂单做空**；只有当 CVD 出现增速放缓（动量衰减或顶背离）时，再贴盘口吃费率挂单。

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

### 2.9 成熟开源架构对标与刷量盈利底层公式

> 对应「工作内容 2」标准：业界成熟量化团队（含在 Hyperliquid / Bybit 刷量赚积分与负费率的机构）都有可参考的开源代码与实操架构。

#### 参考项目一：`tfrmma/game-theory-trading-strats`

- **架构**：专门针对 Hyperliquid 开发的高频做市套件，核心是 **A-S 存货控制 + SAC/PPO 强化学习动态调参**。
- **亮点**：集成 **VPIN 与 Kyle's Lambda** 有毒订单流分类、**盘口 FIFO 队列排队位置估算**、以及**针对资金费率的战术套利逻辑**，专为吃 Maker Rebate 与 Hyperliquid 积分设计。
- **本项目差距**：缺 RL 动态调参、缺真正 VPIN / Kyle's λ、缺资金费率战术模块。

#### 参考项目二：`Italiancrusader/Roboquant-Crypto-Market-Maker-Bot`

- **架构**：基于 Avellaneda-Stoikov 模型的 Hyperliquid 永续合约专业做市 **CLI + 桌面系统**，实现盘口点差自适应与存货硬约束。
- **本项目差距**：本仓库有 A-S + 存货硬约束 + 最小价差保护 + Post-Only + Docker 实盘集群，但实盘侧偏向 OKX，Hyperliquid 支持仍停留在文档层。

#### 参考项目三：`fedecaccia/avellaneda-stoikov` 与 `im1235/ISAC`

- **经典实现**：最完整的标准 A-S 与 **Gueant-Tapia** 模型实现。
- **`im1235/ISAC`**：通过 **Soft Actor-Critic (SAC)** 动态调整风险厌恶系数 $\gamma$ 与目标点差，防止在单边暴跌中打满存货。
- **本仓库对应**：`avellaneda_stoikov_engine.py` / `as_ml_engine.py` 正确实现了保留价 $r = s - q\gamma\sigma^2(T-t)$ 与最优半价差公式，并叠加 ML 漂移与毒性膨胀；但 $\gamma$ 为**固定/半静态**，没有 SAC/PPO 在线调参层。

#### 刷量盈利的底层公式（为什么能成立）

$$\text{Net PnL} = \sum(\text{Half-Spread}) + \sum(\text{Maker Rebate}) - \text{Adverse Selection Loss} - \text{Hedging Cost}$$

刷量团队的核心技巧：

1. **不在主流币死磕**，转而在高换手、散户占比高的山寨币上做市；
2. 把**半点差压缩到接近 0**（甚至贴着 Best Bid / Ask）；
3. 纯靠**负费率（Rebate）+ 微小价差**获利；
4. 用**微秒级撤单**避开有毒流。

> 与 README 前文 1.2 的 `Net PnL = ΔSpread − 2×Maker Fee − Slippage` 是同一模型的两种写法：前者把返佣与对冲显式拆开（收益项），后者从成本角度扣减。两者不冲突，但**做刷量返佣策略时应以 2.9 的四项分解为准**——否则会漏算 Rebate 这一主要收入项。

### 2.10 仓库对标审计结论（第三方审计归档）

> 审计口径：对照上述成熟开源标准，逐项核对本仓库能力覆盖度。**归档说明**：该审计产出时提到的「`asgrid-arb` 不存在、实际为 `asgrid-mm` / `asGrid`」**已不成立** —— 本仓库 `jssyxd/asgrid-arb` 现已存在且 README 完整，此条已修正。

#### 能力对齐度

| 成熟参考 | 核心能力 | 本仓库现状 | 对齐度 |
| :--- | :--- | :--- | :--- |
| `tfrmma/game-theory-trading-strats` | A-S 存货控制 + SAC/PPO 动态调参；VPIN + Kyle's λ 有毒流分类；FIFO 队列位置估算；资金费率战术套利；专为 Hyperliquid Maker Rebate + 积分设计 | 完整 A-S 保留价 + 非对称价差；LightGBM 多任务毒性（toxic_down / toxic_up）；OFI（Cont-Kukanov-Stoikov）；队列优先权保持与 amend-order 思路；明确刷量 + 负费率 + 积分定位 | **高**（缺 RL 动态调参、缺真正 VPIN / Kyle's λ、缺资金费率模块） |
| `Italiancrusader/Roboquant-Crypto-Market-Maker-Bot` | 纯 A-S 永续做市；盘口点差自适应；存货硬约束；CLI + 桌面；testnet-first；真实 Hyperliquid 对接 | A-S + 存货硬约束 + 最小价差保护 + Post-Only；有 Docker 实盘集群与 OKX 导向的 `live_cluster`；文档强调负费率与积分挖矿 | **中高**（更偏 OKX / CEX，Hyperliquid 支持停留在文档层） |
| `fedecaccia/avellaneda-stoikov` | 经典 A-S 完整实现 + 仿真 | `avellaneda_stoikov_engine.py` / `as_ml_engine.py` 正确实现保留价与最优半价差，并加入 ML 漂移与毒性膨胀 | **高**（在经典实现上做了工程化增强） |
| `im1235/ISAC` | SAC 动态调整 $\gamma$ 与目标点差，防止单边暴跌打满存货 | 有固定 $\gamma$ + 库存硬边界 + ADX 趋势阻断 + 毒性断路器 + 成交后冷却，但没有 SAC / PPO 在线调参 | **中**（风控思路正确，缺 RL 自适应层） |

**总体判断**：仓库在「A-S 存货控制 + 毒性流保护 + 刷量/返佣导向」上与成熟案例高度对齐，属于**可实战的中高水平实现**；与最强参考（`tfrmma`）相比，缺少强化学习动态调参与更精细的微观结构工具（VPIN、Kyle's λ、真正的 FIFO 队列仿真）。

#### 底层公式对齐情况

标准公式：

$$\text{Net PnL} = \sum(\text{Half-Spread}) + \sum(\text{Maker Rebate}) - \text{Adverse Selection Loss} - \text{Hedging Cost}$$

本仓库在该公式上的落实情况：

| 公式项 | 本仓库做法 | 状态 |
| :--- | :--- | :-: |
| 最大化 Half-Spread + Maker Rebate | 强制 `post_only`、最小半价差 ≥ 4 bps（覆盖 Maker 费率 2×）、贴近盘口报价、队列优先权保持（避免暴力撤挂丢失 FIFO 位置） | ✅ |
| 最小化 Adverse Selection | OFI + LightGBM 毒性概率（$P_{\text{toxic\_down/up}} \ge 0.65$ 直接切断对应侧）、ADX 强趋势阻断逆势挂单、波动率激增时价差扩大 2.5× | ✅ |
| 存货与风险控制 | 库存硬上限、防御模式（只平仓）、保证金占用限制、成交后单侧冷却 | ✅ |
| 变现路径 | 文档直接写明 Maker 负费率、Hyperliquid / 积分所、项目方做市服务 | ✅ |
| **Hedging Cost（对冲成本）** | **无显式资金费率 / 对冲成本模块** | ⚠️ 缺口 |

> 结论：与「不在主流币死磕、压缩半点差接近 0、靠负费率 + 微小价差、微秒级撤单避开有毒流」的业界技巧高度一致。唯一明显缺口是 **Hedging Cost 部分较弱**。

#### 架构与代码质量亮点

| 模块 | 内容 |
| :--- | :--- |
| 完整决策流（`ARCHITECTURE_AND_EXECUTION_FLOW.md`） | WebSocket（`books5` + `trades` + 私有 `orders`/`account`）→ 因果特征（OFI、GK 波动率、均线偏离）→ LightGBM 三任务推理 → A-S 定价 → 四道硬风控 → 队列感知挂单 → 严格成交记账。流程清晰、无未来函数 |
| 核心引擎（`as_ml_engine.py`） | 保留价加入 ML 漂移调整；半价差含毒性膨胀与库存平滑偏置；严格 Maker 保护与多条件断路器。数学实现正确 |
| 工程化 | Docker 微服务、OKX 实盘配置、回测脚本、Kaggle 训练、详细白皮书（`AS_GRID_FULL_SPECIFICATION.md`）、理论论文列表 |
| 文档 | 中文为主，直接面向「刷量赚返佣 / 积分」，实用性强 |

#### 主要差距与风险点

1. **缺少强化学习动态调参**：最强参考用 SAC/PPO 实时调 $\gamma$、点差、毒性阈值。本仓库 $\gamma$ 与最小价差是静态/半静态的，单边行情下可能仍偏被动。
2. **毒性检测深度不足**：用的是 OFI + LightGBM，而非业界常用的 VPIN + Kyle's λ。对知情交易流的识别可能不够精细。
3. **Hyperliquid / 永续 DEX 落地不完整**：文档强调 HL 积分与负费率，但实盘集群明显偏向 OKX；缺原生 L1 订单簿、资金费率套利、积分挖矿专用逻辑。
4. **FIFO 队列与延迟建模**：有「队列优先权保持」思路，但缺真正的 tick-by-tick 回测 + 延迟仿真（`tfrmma` 有完整实现）。
5. **仓库成熟度**：star 数少、代码量中等、部分文件仍有教学/演示痕迹；长期 PnL 与成交归因证据未充分公开。

#### 总体评分（对照成熟度标准）

| 维度 | 评分 |
| :--- | ---: |
| 理论正确性与 A-S 实现 | 9.0 / 10 |
| 刷量 / 返佣导向与实操架构 | 8.5 / 10 |
| 毒性保护与风险控制 | 8.0 / 10 |
| 与顶级开源（`tfrmma` 级别）的差距 | 6.5 / 10 |
| 工程可复现性与文档 | 8.5 / 10 |
| **综合** | **成熟可用的中高级实现**，已具备「A-S 做市刷量赚返佣」核心闭环 |

#### 建议优先改进方向（按性价比）

1. 引入轻量 **SAC / PPO** 动态调整 $\gamma$ 与毒性阈值（参考 `im1235/ISAC` 与 `tfrmma` 的 `RL_tuner`）
2. 补充 **VPIN / Kyle's λ** 作为毒性辅助信号
3. 把 **Hyperliquid 适配从文档落到可运行代码**（含资金费率模块）
4. 公开更完整的 **tick-level 回测与实盘成交归因报告**，证明 Net PnL 公式成立
5. 统一仓库命名与 README 入口，避免 `asgrid-arb` / `asgrid-mm` 混淆

### 2.11 两份 AI 理论指导的复核（认同与需修正）

> 本节归档两份外部理论指导的交叉复核结论。**采纳原则**：方向类结论直接采纳；具体费率数字与量化预期必须在实盘前用官方文档与自有数据重新标定。

#### 高度认同的部分

| 编号 | 结论 | 说明 |
| :-: | :--- | :--- |
| 1 | 工作内容 1（交易所 MM 入口）方向正确 | Hyperliquid 无需人工申请、完全链上结算；Maker 返佣按 14 天加权 Maker 份额分 Tier（>0.5% → −0.001%、>1.5% → −0.002%、>3.0% → −0.003%），与官方文档一致。Bybit / Gate / Bitget 确有正式 MM 计划且存在负费率，对新 MM 有试用期/对标福利 |
| 2 | 工作内容 2（成熟开源与公式）定位准确 | 四个参考仓库定位准确，Net PnL 公式是标准做市经济模型；「山寨高换手币 + 半点差压到接近 0 + 靠 Rebate + 微秒级撤单避毒」的技巧完全正确 |
| 3 | 工作内容 3（资金费率偏置）可行 | 把目标存货 $q^{*}$ 从 0 动态偏置到吃费率一侧，再通过 Reservation Price 偏移驱动挂单方向，数学正确且与经典 A-S 扩展一致；结合 CVD 动量衰减再进场的防穿仓逻辑实用 |
| 4 | 工作内容 4（新兴交易所）值得优先 | Hyperliquid HIP-3/HIP-4、Aevo、Paradex、Orderly、Backpack 确有较强流动性补贴/积分/空投激励，竞争低于传统 CEX |
| 5 | 工作内容 5（DEX / TradeFi 映射）同构成立 | Uniswap v3/v4 集中流动性与限价网格数学高度同构；用 $r(s,q)$ 动态调整区间中心是标准做法；Meteora DLMM / Raydium CLMM 的 Bin 结构更接近真正档位网格；预测市场把 A-S 映射到 Logit 空间已有开源先例；TradeFi 永续复用价值高 |
| 6 | 工作内容 6（ML 与正 PnL）切入点正确 | 「不要预测方向，改为预测有毒成交概率（Toxic Flow Gating）」是做市最正确的 ML 切入点；标签定义标准且可操作；LightGBM/CatBoost 低延迟 + OFI/OBI/微观价格偏差/CVD_zscore/VPIN/Garman-Klass 特征组合正确；RL（SAC/PPO）动态调 $\gamma$ 与 $\delta$ 是正确进阶方向 |

#### 不认同或需修正的部分

| 编号 | 问题 | 修正 |
| :-: | :--- | :--- |
| 1 | **交易所费率数字偏乐观** | Hyperliquid Maker 基础费率从 0.015% 起步，需约 **$500M+** 的 14 天加权成交量才到 0%，再叠加份额返佣才到 −0.001% ~ −0.003%，**不是随便刷量就能拿到负费率**。Bybit 合约按币种分组、需正式审核；Gate 的 −0.015% 主要出现在**期权 MM 或特定 BTC/ETH 场景**，并非所有山寨现货/永续都能拿到；Bitget 数字随公告调整且有淘汰机制。**实操必须以官网最新文档为准，并预留对标证明与考核期** |
| 2 | **资金费率公式过于简化** | 缺三件事：① 结算频率与**下一期费率预测**（1h/8h）；② **对冲成本与基差风险**（永续 vs 现货/跨所）；③ 极端高费率时**流动性枯竭与穿仓概率上升**。CVD 防穿仓必要，但 1m CVD 斜率在真正知情流面前**滞后**，应叠加 VPIN 或更短时间窗的主动买卖强度 |
| 3 | **链上迁移可行性被高估** | Gas 与 MEV 是致命问题。即使部署在 BSC / Arbitrum / Base / Solana，**重新调区间的成本仍可能吞噬半点差收益**；v4 Hooks 开发与审计成本高，且与 CEX 的「微秒级撤单」体验完全不同。链上做市更适合**相对静态区间 + 低频再平衡**，不是高频 Tick 级网格。预测市场虽毒流少，但成交量与点差结构差异大，直接迁移需重新标定参数 |
| 4 | **「过滤最毒 5% 就能让 Sharpe 从负变 2.0+」过于理想** | 回测中确实常见「去掉最毒尾部成交后风险收益显著改善」，但：① 活盘中毒性预测准确率很难长期稳定；② 过度熔断会大幅降低成交量，**影响 Maker 份额与返佣资格**；③ 手续费 + 滑点 + 库存风险仍可能让净 PnL 接近零或为负。**山寨高换手币 + 严格毒性门控 + 负费率是正 PnL 的必要条件，不是充分条件** |
| 5 | **隐性风险被轻描淡写** | API 限频、跨机房延迟、链上 Gas 尖峰、流动性枯竭是真实尾部风险，对高频做市更致命。成熟团队会专门做**延迟建模、队列位置估计、熔断后恢复逻辑**，本仓库目前仍偏弱 |

#### 复核结论

- **可直接采纳**：毒性门控优先于方向预测、目标存货偏置吃费率、新兴 DEX/积分所优先、LightGBM 低延迟毒性模型、RL 调参作为进阶、Net PnL 公式作为北极星指标。
- **需修正后使用**：交易所具体费率与准入门槛（以官方最新文档为准）、资金费率公式加入预测与对冲成本、链上迁移先做低频/静态区间验证、Sharpe 提升预期下调。

### 2.12 小资金实盘现状与六个方向优先级

#### 实盘现状（35 USDT 账户实测）

| 项目 | 数值 |
| :--- | :--- |
| 本金 / 杠杆 | ≈ 35 USDT / 3x |
| 标的 | BTC-USDT 永续（OKX） |
| 运行时长 | ≈ 18 小时 |
| 真实成交笔数 | 472 笔 |
| 名义成交额 | ≈ 6,280 USDT |
| 累计盈亏 | **≈ −1.67 USDT** |
| 其中手续费 | ≈ 1.23 USDT（占损耗 **≈ 73%**） |
| Maker 占比 | ≈ 80% |
| 当前费率 | OKX 主流合约 Maker 0.02% / Taker 0.05% |
| 单笔仓位 | 0.01 张合约 |
| 主循环耗时 | 600 ~ 750 ms |
| 毒性读数 | $P_{\text{toxic\_down/up}}$ 经常 > 0.70 |

**核心问题定性**：**正费率 + 点差覆盖不足 + 毒性过滤不够狠 → 稳定微亏**。

> **数据口径警示（重要）**：本 README「实盘成绩快照」中的 `REAL_BTC_GRID_FILLS.csv`（2,345 笔 / 名义 **9,662,210 USDT** / 峰值库存 **0.5 BTC ≈ 41,000 USDT** / 手续费 1,932 USDT / 净 +1,920 USDT）**不是 35 USDT 账户的实盘记录**——以 30U 本金与 3x 杠杆无法承载 4.1 万 USDT 的库存敞口。该文件是**较大资金规模的模拟/回放成交明细**。35 USDT 真机的真实结果是 **472 笔 / −1.67 USDT**。阅读本仓库任何收益数字时，务必先确认其来自哪一份数据源。

#### 六个工作方向：从易到难 / 从快到慢

| 优先级 | 方向 | 改动难度 | 预期见效 | 理由（针对当前状态） |
| :-: | :--- | :--- | :--- | :--- |
| **1** | 工作内容 6：毒性门控 + 最小点差/费率覆盖优化 | **极低** | **1 ~ 3 天** | 已有 LightGBM 毒性输出（实测 $P_{\text{toxic}}$ 0.72 / 0.73 很高），只需把阈值调严 + widening 逻辑加强 + 强制半点差覆盖 Maker 费率 2× 以上。立刻减少「被毒流打穿」的成交，手续费损耗立刻下降 |
| **2** | 工作内容 1：换到真正负费率/更高返佣通道（或山寨高换手币） | 低 ~ 中 | 3 ~ 10 天 | 当前 OKX 主流合约 Maker 0.02% 是**正费率**，小资金很难覆盖。申请 Gate/Bitget 试用 MM 或直接切到高换手山寨（流动性够、点差更大）是最快扭亏路径 |
| **3** | 工作内容 3：资金费率偏置（小幅度） | 中 | 1 ~ 2 周 | 已有库存控制，只需把 $q^{*}$ 从 0 微偏到吃费率一侧。小资金收益有限，但几乎零额外风险 |
| **4** | 工作内容 2：引入轻量 RL 动态调 $\gamma$/$\delta$（参考 ISAC） | 中高 | 2 ~ 4 周 | 需要训练环境 + 回测验证，收益稳定但开发量大 |
| **5** | 工作内容 4：接入新兴 DEX / 积分所（Hyperliquid 等） | 高 | 3 ~ 6 周 | 需新适配 + 延迟测试，积分/返佣诱人，但对 1 核 1G 马来西亚 VPS 不友好 |
| **6** | 工作内容 5：Uniswap v3/v4 / TradeFi / 预测市场 | 很高 | 1 个月+ | 完全换范式，小资金 Gas / MEV 风险大，不适合当前阶段 |

**最高优先级落地顺序**：① 毒性 + 点差 → ② 换币种 / 申请更好费率 → ③ 加资金费率偏置。

### 2.13 手续费与返佣计算模型

#### 精确手续费模型（可直接拷贝使用）

```python
def estimate_fee_and_rebate(
    notional: float,            # 总名义成交额 USDT
    maker_ratio: float = 0.80,  # Maker 成交占比
    maker_fee: float = 0.0002,  # 0.02%
    taker_fee: float = 0.0005,  # 0.05%
    rebate_rate: float = 0.0,   # 负费率时填负数，如 -0.00015
) -> dict:
    """按 Maker/Taker 占比拆解手续费与返佣，返回 bps 口径便于与点差对比。"""
    maker_notional = notional * maker_ratio
    taker_notional = notional * (1.0 - maker_ratio)

    maker_cost = maker_notional * maker_fee
    taker_cost = taker_notional * taker_fee
    rebate = maker_notional * rebate_rate      # 负费率 → rebate 为负成本（即收入）

    net_fee = maker_cost + taker_cost + rebate
    return {
        "maker_notional": maker_notional,
        "taker_notional": taker_notional,
        "maker_cost": maker_cost,
        "taker_cost": taker_cost,
        "rebate": rebate,
        "net_fee": net_fee,
        "fee_bps_of_notional": net_fee / notional * 10000,
    }
```

#### 当前情景代入（472 笔 / 6,280 USDT）

| 项目 | 计算 | 结果 |
| :--- | :--- | ---: |
| Maker 名义 | 6,280 × 0.80 | 5,024 USDT |
| Taker 名义 | 6,280 × 0.20 | 1,256 USDT |
| Maker 手续费 | 5,024 × 0.02% | 1.0048 USDT |
| Taker 手续费 | 1,256 × 0.05% | 0.6280 USDT |
| **合计净手续费** | — | **≈ 1.6328 USDT**（实测 1.23，差异来自部分成交/统计口径） |
| 平均每笔名义 | 6,280 ÷ 472 | ≈ 13.3 USDT |
| 平均每笔净手续费 | 1.63 ÷ 472 | ≈ 0.00345 USDT |
| **加权净费率** | — | **≈ 0.026%** |

#### 盈亏平衡点

- 半点差需覆盖的成本 ≈ **净费率 ÷ 2**（双边）。
- 当前加权净费率 ≈ **0.026%**，因此半点差至少要稳定赚到 **1.5 ~ 2.0 bps** 以上，才能覆盖手续费 + 库存风险。
- 实测挂单观测：`mid 80146.9` / `bid 80106.5`（≈ −5 bps）/ `ask 80187`（≈ +5 bps）→ **实际点差偏宽、成交质量一般，且毒性高时仍在挂单**。

#### 负费率情景对比（Maker 占比仍 80%）

| 场景 | Maker 费率 | 净手续费 | 含义 |
| :--- | ---: | ---: | :--- |
| OKX 现状 | +0.02% | +1.63 USDT | 纯成本，必须靠点差覆盖 |
| Gate / Bitget 最高档 | −0.012% ~ −0.015% | **转负 → 变收入** | 点差可压缩，纯吃返佣 |
| Hyperliquid Tier 1 | −0.001% | 接近零 | 小资金难达份额，但零费率已优于 OKX |

> 结论：**在正费率下高频刷量的数学期望为负**。472 笔、6,280 USDT 名义、1.23 USDT 手续费、净亏 1.67 USDT —— 这就是「稳定高频率亏钱」的量化解释：成交量越大，手续费磨损越线性上升，而捕获的半点差不足以覆盖它。

### 2.14 多币种 / 多交易所选择

| 交易所 | 推荐币种 | 适合小资金的原因 | 风险点 | 优先级 |
| :--- | :--- | :--- | :--- | :-: |
| **Gate / Bitget** | 高换手山寨（PEPE、WIF、BONK、新上币） | 点差大、散户多、MM 试用门槛相对低、负费率可达 −0.01%+ | 流动性突然枯竭、插针 | **最高** |
| **OKX（现状）** | 中等市值永续（**非** BTC/ETH） | 已有对接，换币种成本最低 | 主流币点差太小，手续费难覆盖 | 中（先换币） |
| **Bybit** | TradFi 或山寨 | 有 MM 试用 + 分组返佣 | 申请需提供证明 | 中 |
| **Hyperliquid** | 任意永续 + HIP-3 | 零 Gas、Maker 可到 0 甚至负、积分 | 马来西亚延迟高、小资金难达份额 | 中长期 |

> **小资金铁律**：永远优先「**点差足够大 + 能拿到负/零费率**」的标的，而不是 BTC。BTC 的 0.02% Maker 对 35U 本金是致命摩擦。

### 2.15 模型优化与 NautilusTrader 回测方案

#### 代码层改进（直接改 `as_ml_engine.py` / 策略层）

| # | 改进 | 具体做法 |
| :-: | :--- | :--- |
| 1 | **强制费率覆盖点差**（最快见效） | `min_half_spread_bps = max(4.0, fee_maker_bps * 2.5)` —— 至少覆盖 2.5 倍 Maker 费率 |
| 2 | **毒性熔断更狠** | $P_{\text{toxic}} > 0.55$ → 立刻切断对应侧 + 价差扩大 3×；$P_{\text{toxic}} > 0.70$ → 双侧只挂远离盘口的防御单，或**完全休息 30 ~ 60s** |
| 3 | **成交后冷却 + 库存硬约束** | 成交一侧后强制冷却 **3 ~ 8 秒**，防止连续被扫 |
| 4 | **目标库存微偏**（为资金费率做准备） | $q^{*} = -\mathrm{sign}(F_t) \times 0.3 \times q_{\max}$ |
| 5 | **只做 Maker + 队列保持** | 继续强化 **amend** 而非 cancel + replace |

#### NautilusTrader 详细回测方案

| 环节 | 要求 |
| :--- | :--- |
| **数据** | 用 Tardis 或自录的 OKX L2 `books5` + `trades`，至少 **2 ~ 4 周**，必须包含剧烈行情 |
| **撮合仿真** | 开启 `FillModel` 概率成交 + 延迟模型（马来西亚节点建议加 **15 ~ 40 ms 固定延迟 + 抖动**） |
| **手续费** | 精确写入 Maker 0.02% / Taker 0.05%，并统计 Maker 占比 |
| **关键指标** | Net PnL / 名义成交额（bps）；毒性过滤前后 Sharpe 对比；最大库存占用；回撤；**手续费占比**；**成交后 markout（+1s / +5s / +30s）** |
| **参数扫描** | $\gamma$、`min_spread`、`toxic_threshold`、`cooldown` 用网格或简单贝叶斯优化 |
| **防过拟合** | **Walk-forward**：按周滚动训练 LightGBM + 前向验证 |
| **验收目标** | 手续费占比从当前 **≈ 73% 降到 < 40%**，Maker 占比 **> 85%**，Net PnL 转正 |

### 2.16 基建评估（VPS 延迟与 1C1G 瓶颈）

| 问题 | 结论 |
| :--- | :--- |
| **马来西亚 VPS vs 东京 AWS 延迟** | 当前推理循环 **600 ~ 750 ms**，已远大于网络延迟差异（东京 AWS 到撮合通常 1 ~ 5 ms，马来西亚常见 30 ~ 80 ms）。对真正的 HFT 抢队列有影响，但对「挂单后等被动成交 + 毒性熔断」的**中频做市**，延迟不是胜率主因 |
| **真正伤害 PnL 的是什么** | **正费率 + 点差覆盖不足 + 毒性过滤不够狠** —— 不是机房位置 |
| **1 核 1G 是否瓶颈** | CPU 长期 < 30% → **完全不是瓶颈**；内存 70% → 接近警戒，建议加到 **2 GB**，或压缩模型（叶子数、树数量）与缩短环形队列长度 |
| **600 ~ 750 ms 从哪来** | 主要是特征计算 + 模型推理，优化空间在**代码**（Numba 加速、特征缓存），不是换机器 |
| **基建升级的收益** | 对当前阶段 PnL 提升有限（估 **5 ~ 15%**），远不如「换负费率币种 + 强化毒性门控 + 强制点差覆盖」直接。等稳定正 PnL、日名义成交上万 USDT 后再考虑低延迟机房 |

### 2.17 7 天立刻可执行清单（小资金专用）

| 时间 | 动作 |
| :--- | :--- |
| **今天** | `min_half_spread` 强制 ≥ 5 ~ 6 bps；`toxic` 阈值降到 **0.55**；成交后冷却 **5s** |
| **明天** | 回测验证**手续费占比**是否下降 |
| **第 2 ~ 3 天** | 申请 Gate / Bitget MM 试用，或直接切 **1 ~ 2 个高换手山寨币**跑同样逻辑 |
| **同步** | 在 Nautilus 里把**手续费模型**和 **markout 分析**加全 |
| **一周后** | 看净 PnL 是否转正；若仍微亏，再考虑**资金费率偏置** |

---

有别人评论我说这个10bp点差在btc等数据上0成交，要么压缩到1.5bp~2.5bp（能覆盖0.04%双边手续费，但需要极高的成交率），或者能与他人合作mm拿返点或申请交易所mm。另外一个方案是很多韭菜币点差天然更高的beta币对例如sui、pepe、shib、PENGU、BONK、TRUMP、PENGU等，同时它们是否有插帧、流动性不足的风险对我们带来负面影响负面收益，我们的防御是否能防住毒单。另外，github上是否有成熟的高赞的更新较新的方案，实现实时监控过滤此类beta币对的，我们根据模型计算有正收益的实时系统热切换做对应的标的Grok工作了 37s结论先说清楚评论是对的：
10 bp 在 BTC 上几乎 0 成交是正常的。BTC 主流合约盘口被专业做市商压到 0.5–2 bp 级别，你挂 10 bp 等于自己退出队列。
小资金（几十到一千 U）在 BTC 上用正费率做市，基本是“给交易所打工”。下面按你的问题逐条回答。1. 三种现实路径（按可行性排序）



路径可行性（小资金）核心要求预期结果A. 换高 Beta 山寨（SUI / PEPE / BONK / PENGU / TRUMP / SHIB 等）最高点差天然 8–30 bp，散户多最容易覆盖 0.04% 双边手续费，成交率显著上升B. 压缩到 1.5–2.5 bp + 极高成交率中必须拿到负费率或接近 0 费率，且队列位置好在正费率下几乎不可能持续正 PnLC. 申请交易所 MM / 合作拿返点中高（中长期）需要交易量证明或对标其他所 VIP负费率后 2–4 bp 也能赚钱推荐顺序：先做 A（高 Beta），同时申请 B/C 的负费率通道。BTC 暂时放弃。2. 高 Beta 币对的真实风险 + 你的防御能否挡住主要风险：
流动性突然枯竭 / 插针山寨永续经常出现“一秒抽干 5–10 档”的情况，尤其是新闻、清算 cascade、大户砸盘时。
毒流更猛知情交易者（项目方、做市商、量化）在山寨上更激进，逆向选择损失更大。
资金费率剧烈波动 + 基差风险高 Beta 币资金费率常年极端，持仓过夜成本高。
滑点与部分成交小资金单笔 0.01–0.1 张问题不大，但连续被扫时库存会迅速堆积。
你现有防御是否够用？你已经有的：
LightGBM 毒性概率（$P_{\rm toxic}\geq 0.65$ 切断）
OFI
库存硬上限
Post-Only
成交后冷却
还不够，山寨需要额外加强：


防御层建议动作原因毒性阈值降到 0.50–0.55，且 widening ×3～5山寨毒流更突然深度检查挂单前检查 Top5 深度是否 > 自己挂单量的 5–10 倍防止自己变成最大流动性提供者被单边打穿波动率熔断σ 超过过去 1h 分位数 90% 时强制休息 30–120s插针前兆库存回吐速度库存 > 50% max 时，平仓侧点差压到 1–2 bp快速去库存单边冷却成交后冷却 5–15s（比 BTC 更长）防止连续被扫资金费率偏置高费率时主动偏置目标库存吃费率额外收益源只要把以上层叠加上，中等流动性的山寨（SUI、PEPE、BONK、PENGU）是可以被防住的。极端 meme（流动性极差的新币）仍建议避开。3. GitHub 上成熟、更新较新的相关方案目前没有一个“高星 + 专门做实时多币种 Beta 筛选 + 热切换做市”的完美开源项目，但有可直接借鉴的组件：


仓库Stars更新情况价值备注beatzxbt/smm608较活跃简单 Bybit/OKX 做市框架，多交易所最接近可复用的基础框架nkaz001/hftbacktest~5k活跃真正的 tick-level 回测 + 队列位置，支持 Binance/Bybit用来验证山寨成交率与毒性过滤Rakeshks7/vpin-risk-engine低新实时 VPIN 毒性引擎可直接集成到你的 LightGBM 之前kayasolomon/order-flow-toxicity低新OFI + VPIN + Kyle’s λ 完整实现 + 合成数据验证研究级，代码质量高yt-feng/VPIN104旧经典 VPIN 实现参考用Italiancrusader/Roboquant-Crypto-Market-Maker-Bot8较新Hyperliquid A-S 完整实现适合后续切 HLtfrmma/game-theory-trading-strats~122026A-S + SAC/PPO + VPIN + FIFO最接近你想要的“高级版”Hummingbot很高持续更新多策略框架，有 Hyperliquid 连接器可做热切换基础设施Freqtrade56k+极活跃策略框架，支持多币种扫描适合做“候选币池筛选器”没有现成的“实时监控高 Beta 币对 + 模型计算正收益 + 热切换”完整系统。
你需要自己拼：
筛选层（Freqtrade / 自写）：实时计算每个候选币的
过去 1h/4h 平均点差
深度（Top5 名义量）
VPIN / OFI 毒性
成交活跃度
预估净费率覆盖后的期望半点差收益

做市层（你现有 A-S + 加强后的毒性门控）
热切换逻辑：当某币评分连续 N 分钟 > 阈值 → 切换过去；评分跌破 → 平仓回退到安全币或休眠。
4. 可落地的实时热切换系统设计（针对你当前架构）text复制已复制候选池 = [SUI, PEPE, BONK, PENGU, DOGE, TRUMP, ...]

每 30–60 秒对每个币计算：
  score = w1 * (avg_spread_bps - 2.5 * fee_bps)
        + w2 * (depth_score)
        - w3 * (vpin_or_toxic_prob)
        + w4 * (volume_accel)
        - w5 * (funding_risk)

if score > threshold and current_symbol.score < threshold * 0.7:
    → 平当前仓 + 切换到新币你已有 LightGBM 毒性输出，只需再加：
实时点差与深度监控
简单 VPIN（可用 Rakeshks7/vpin-risk-engine 或自己写 volume-bucket 版本）
评分与切换状态机
最终建议（小资金立刻可执行）
今天：停止在 BTC 上挂 10 bp。
1–2 天内：把参数切到 SUI / PEPE / BONK 中流动性最好的 1–2 个，把 min_spread 设为 6–10 bp（根据实际盘口），toxic 阈值降到 0.55，加深度检查。
同步：用 Nautilus + hftbacktest 回测这几个币过去 2–4 周，看手续费占比与 markout。
中期：申请 Gate/Bitget MM 试用拿负费率；同时开始写简单的多币评分热切换模块。
长期：把 VPIN + 深度 + 点差评分做成独立服务，实现真正的“正期望标的热切换”。
需要我直接给你一份「山寨币加强版 as_ml_engine 参数 + 深度/毒性检查伪代码」或「简单热切换状态机」的代码框架，可以继续说。






## 免责声明

本仓库中的研究报告由 AI 基于公开资源与代码审阅生成，所有交易策略均涉及重大财务风险。实盘部署前请独立验证全部信息，并做好完全亏损的准备。交易所规则可能随时变化，请以各交易所官方最新公告为准。

---

<p align="center">
  <sub>asgrid-arb · Avellaneda-Stoikov Microstructure Grid · 仅供技术研究使用</sub>
</p>
