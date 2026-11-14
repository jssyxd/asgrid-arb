# 05 · Kaggle / GitHub 可移植成熟方案调研

> 切片：在 Kaggle / GitHub 上是否已有**足够优质、足够健壮**的成熟方案，可以直接移植或借鉴，用于本项目的微观做市（AS-MM / GLFT-MM）体系。
> 口径：只列**能真正动手移植**的项目；星标低、多年未更新的玩具仓库不列。
> 与 `03-queue-aware-backtest-engine.md` 的关系：03 已经定了「自研 Numba 事件引擎为主」的路线，本稿**不改这条路线**，只回答「哪些外部资产值得拿、拿什么、怎么拿、代价多少、许可证风险在哪」。

---

## 0. 调研方法与核实口径

| 项 | 说明 |
|---|---|
| 核实时间 | 2026-11-14（本文所有「实测」均为该日核实） |
| 核实方式 | GitHub REST API（`gh api`，已认证）、PyPI JSON API、仓库内文件直接读取（`contents` API）、PR/Issue 全文 |
| 核实字段 | 仓库是否存在、star、fork、SPDX 许可证、最后推送时间、最新 release 与发布日期、最近 2 条提交、open issue/PR 状态、open issue 最后更新时间、关键源文件内容 |
| 标注规则 | **实测** = 本次实际访问 API/文件确认；**推断** = 基于实测数据的合理外推，未直接观测；**建议** = 我的工程判断，无外部事实支撑 |
| 未核实 | 访问不到、仓库不存在于该镜像、或信息不足以判断，明确写「未核实」，不做补全 |

**一个重要结构性事实（实测）**：GitHub 侧存在若干「本项目相关方」的仓库——`hmate9/*`（cryptohftdata 作者）、`dominolu/titan`（基于 hftbacktest 的中文高频框架）。这类仓库与官方上游的活跃度、质量差异极大，必须分开评估，不能混为一谈。

---

## 1. TL;DR 结论

### 1.1 一句话答案

**有，但只有一个项目达到「可以直接动手移植」的门槛：`hftbacktest`（MIT），并且已经有人把本项目正在用的 `cryptohftdata` 数据源接进了它——那段代码现存于一个已关闭未合并的 PR 分支里，MIT，可直接拿来用。** 其余绝大多数项目属于「借鉴思路」级别，不属于「移植代码」级别。

### 1.2 决策表

| # | 问题 | 结论 |
|---|---|---|
| 1 | 有没有现成的队列感知回测引擎？ | 有：`hftbacktest`（MIT，★5084）。但它**不作为本项目生产引擎**，只作**语义基准 + 离线校准真值**（与 03 稿一致） |
| 2 | 本项目的数据源能不能直接喂给它？ | **能**。PR #307「Add CryptoHFTData.com orderbook/trades support」已写好完整转换器（423 行 + 240 行测试），2026-11-10 关闭未合并，代码仍在 fork `hmate9/hftbacktest@cryptohftdata` 分支，MIT，可直接移植 |
| 3 | 有没有现成的事件驱动交易平台？ | 有：`nautilus_trader`（LGPL-3.0，★31520）。但 PyPI 稳定版仍是 **1.231.0（2026-08-02）**，v2 只到 **rc9 标签**，v2 未 GA；且本机已装的 1.221.0 与 v2 API 不同。**不整体引入** |
| 4 | 它的实盘适配器值得抄吗？ | **值得抄**：`crates/adapters/hyperliquid/` 里明确支持 **HIP-3 builder-deployed perp dex** + `builder_fee`，且有 L2 book 的 `recovery.rs` / `sync.rs`。这是 HIP-3 接入的现成范式 |
| 5 | 有没有官方 Python SDK 能对接 cryptohftdata？ | **有**：`cryptohftdata` PyPI **0.8.1（2026-11-09 上传）**，MIT。可替换我们手搓的 REST 下载 |
| 6 | vectorbt / backtrader / zipline 能做微观做市吗？ | **都不能**，理由见 §2.4 |
| 7 | 有没有现成的 LOB 深度学习实现？ | 有，但**全是论文实验代码**（DeepLOB/TransLOB 官方仓库均无 LICENSE 或 4 年未更新），且需要 GPU。**放弃**，本项目走 LightGBM 路线 |
| 8 | Hummingbot 值得借鉴什么？ | 值得借鉴**费率感知 + 仓位执行的工程结构**，不移植代码（Apache-2.0 但架构与我们完全不同） |
| 9 | 交易所 SDK 现状 | **OKX 无官方 Python SDK 仓库（未核实/不存在于该镜像）**；Hyperliquid 官方 SDK 明确支持 HIP-3；Lighter 无一方 SDK；Robinhood 加密只有社区 demo，**无官方 HFT 级接口** |
| 10 | 1 核 1G 约束下，ML 推理怎么加速？ | LightGBM C API / ONNX Runtime 单线程即可；**不需要 GPU、不需要 TabPFN、不需要 Feast** |

### 1.3 Top 5 移植清单（先给结论，详见 §7）

1. **`hftbacktest` + cryptohftdata 转换器**（fork `hmate9/hftbacktest@cryptohftdata`）→ 作为离线校准真值
2. **hftbacktest 的概率队列模型数学**（SquareProb / LogProb / PowerProb）→ 照抄进 Numba 引擎，对应 03 稿 §5 方案 B
3. **`nautilus_trader` 的 hyperliquid adapter 范式**（HIP-3 perp dex 寻址 + builder fee + L2 book recovery）→ 移植进我们的 V2 WS 引擎
4. **cryptohftdata 官方 Python SDK 0.8.1**（MIT）→ 替换手搓 REST 客户端
5. **hftbacktest 的 `feed_order_latency` 延迟标定工具** → 用真实行情延迟反推我们的 45–75 ms 下单延迟假设

---

## 2. A 区：回测与撮合引擎（最高优先级）

### 2.1 `nkaz001/hftbacktest` — 本次调研中**唯一**达到「可直接移植」门槛的项目


> **与 03 稿的一处事实修正（实测）**：03 稿把 hftbacktest 的编译链描述为「Cython 编译链 + 数据适配成本 > 收益」。实测当前 PyPI 上的 **2.4.4 是 Rust + maturin 的预编译 wheel**（`py-hftbacktest/pyproject.toml` 实测：`build-backend = "maturin"`，依赖 `numpy` / `numba~=0.61` / `polars` / `holoviews`），**不需要 Cython 编译**。Cython 是 v1.x（tag `v1.8.4`）的历史形态。因此 03 稿「编译链成本」这一条对当前版本**不再成立**，实际成本只有「Python ≥3.11 + numba 版本约束 + 隔离 venv」三项。结论方向（不作生产引擎）不变，但 Top 1「离线校准器」的落地成本比 03 稿预估更低。
#### 实测档案

| 项 | 实测值 | 核实方式 |
|---|---|---|
| 仓库 | `nkaz001/hftbacktest`（注意：**不是** `nkanazawa/hftbacktest`，后者 404） | GitHub API |
| Star / Fork | ★5084 / 963 | API |
| 许可证 | **MIT**（仓库 `LICENSE` + `pyproject.toml` 分类器 `License :: OSI Approved :: MIT License`） | 文件 |
| 主语言 | Rust（`Cargo.toml` workspace：`hftbacktest` / `hftbacktest-derive` / `py-hftbacktest` / `collector` / `connector`） | 文件 |
| Python 包 | `hftbacktest` **2.4.4**，PyPI 上传 **2025-12-10**，`requires_python >=3.11`，依赖 `numpy>=2.0,<2.3` + `numba~=0.61` + `polars` | PyPI API |
| GitHub release | 最新 `rust-v0.9.4`（2025-12-10）；tag 列表停在 `v1.8.x` | API |
| **master 最后提交** | **2025-12-23**（`fix: update the order status to Status::New when the order is modified`） | API |
| 最近提交 | 2025-12-23 / 2025-12-22（bybit feed stream collection） | API |
| **Issue/PR 活跃度** | **issue #325 更新于 2026-11-14**、#342 于 2026-11-04、#323 于 2026-11-03；近 10 个 PR 全部 `open` 或 `closed-unmerged`，**无一合并** | API |
| Open issue 数 | 23 | API |
| 非 master 分支 | `ci`(2024-11-20)、`ipc`(2024-09-29)、`eventhandler`(2025-05-03) | API |

> **活跃度判读（实测 + 推断）**：维护者的 issue 响应仍在 2026-11（说明人还在），但 **master 分支 11 个月无提交**，且 2026 年下半年收到的 10 个 PR **全部未合并**。推断：v2（Rust 重写）的后续开发发生在未推送到本镜像 master 的分支上，或维护者合并意愿显著下降。**结论：可以用，但必须锁版本，且不能指望它跟进 OKX / HIP-3 / 新交易所。**

#### 数据格式（实测，读 `docs/data.rst` 与 `examples/Data Preparation.ipynb`）

**规范输入 = numpy 结构化数组**，8 字段固定顺序：

```
ev(u64) exch_ts(i64) local_ts(i64) px(f64) qty(f64) order_id(u64) ival(i64) faval(f64)
```

- `ev` 是位标志：`BUY_EVENT | DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT` 等组合；快照用 `DEPTH_CLEAR_EVENT` + `DEPTH_SNAPSHOT_EVENT`。
- **不支持直接读 Parquet**。官方提供的是「原始交易所 gzip → numpy」的转换器（`data/utils/`）。
- master 上已有的 provider 转换器（实测目录清单）：`binancefutures` / `binancehistmktdata` / `bybit` / `bybithistmktdata` / `databento` / `hyperliquid` / `mexc` / `tardis` / `difforderbooksnapshot` / `feed_order_latency` / `snapshot` / `migration2`。
- **没有 OKX 转换器**（实测）。
- `data/utils/snapshot.py` 的 `create_last_snapshot(...)` 可以从增量流重建日终快照，用于次日开盘初始状态。

**⚠ 关键发现（实测）**：PR **#307**「Add CryptoHFTData.com orderbook/trades support and full workflow notebook」

| 事实 | 实测值 |
|---|---|
| PR 号 / 状态 | #307，`state=closed`，`merged=false`，closed 于 **2026-11-10** |
| 提交者 | `hmate9`（cryptohftdata 方） |
| head 仓库 | `hmate9/hftbacktest`，分支 `cryptohftdata` **仍然存在** |
| 改动量 | 12 个文件：转换器 423 行、测试 240 行、CLI 51 行、教程 97 行、Notebook 1440 行 |
| 许可证 | hftbacktest 侧 MIT；依赖的 `cryptohftdata` SDK MIT → **双向可商用移植** |
| 新增 API | `hftbacktest.data.utils.cryptohftdata.{download, convert, download_and_convert}` |
| 依赖 | 可选 extra `hftbacktest[cryptohftdata]`，要求 `cryptohftdata>=0.4.0`（实测当前 PyPI 为 0.8.1） |

转换器的字段映射（实测，代码逐行核对）：

| cryptohftdata 列 | → hftbacktest 事件字段 |
|---|---|
| `received_time` | `local_ts`（订单簿与成交均是） |
| `coalesce(transaction_time, event_time) * 1_000_000` | `exch_ts`（订单簿） |
| `coalesce(trade_time, event_time) * 1_000_000` | `exch_ts`（成交） |
| `side ∈ {bid,buy}` / `{ask,sell}` | `BUY_EVENT` / `SELL_EVENT` |
| `event_type='update'` | `DEPTH_EVENT` |
| `event_type='snapshot'` | `DEPTH_CLEAR_EVENT` + `DEPTH_SNAPSHOT_EVENT` 序列 |
| `is_buyer_maker=True` | `SELL_EVENT \| TRADE_EVENT`（反之 `BUY_EVENT \| TRADE_EVENT`） |
| `price` / `quantity` | `px` / `qty` |

且内置 `correct_local_timestamp` → `correct_event_order`（mergesort 稳定排序）→ `validate_event_order` 三步流水线。

> **对本项目的直接价值**：这段代码的列名映射与 03 稿 §3.2 独立整理的映射**完全一致**（`received_time`/`event_time`/`transaction_time`/`final_update_id`/`prev_final_update_id`/`order_count`/`is_buyer_maker`）。这构成一次**独立第三方交叉验证**：我们的 schema 契约不是拍脑袋写的。**这是本次调研最有价值的产出。**

#### 队列模型与延迟模型（实测）

- v2 内置**概率队列模型**：`SquareProbQueueModel`、`LogProbQueueModel2`、`PowerProbQueueModel3`（见 `examples/Probability Queue Models.ipynb`）。→ 03 稿 §5「方案 B」可直接照抄其公式。
- `data/utils/feed_order_latency.py` 提供 `generate_order_latency(...)`：用**行情延迟**合成订单延迟，模型为
  ```
  order_entry_latency  = mul_entry  * feed_latency + offset_entry
  order_response_latency = mul_resp * feed_latency + offset_resp
  ```
  输出 `order_latency_dtype(req_ts, exch_ts, resp_ts)`，可直接喂给 `BacktestAsset().intp_order_latency(...)`。
- 官方提供 `examples/Order Latency Data.ipynb`（实测存在）。
- 还有 `examples/GLFT Market Making Model and Grid Trading.ipynb`、`examples/High-Frequency Grid Trading.ipynb`、`examples/Queue-Based Market Making in Large Tick Size Assets.ipynb`——**这些正是本项目 AS-MM / GLFT-MM 的对标物**。

#### 采集与实盘连接器（实测）

- `collector/` 支持：**binance（spot/futures/cm）、bybit、hyperliquid**（Rust 采集器）。**无 OKX**。
- `connector/` 实盘连接器：**binance、binancefutures、bybit**。**无 OKX、无 Hyperliquid 实盘**。

#### 性能特征

- Rust 核心 + Numba 辅助，事件数组列式存储。官方示例用 `multiprocessing.Pool(16)` 对多资产并行（实测 Notebook 代码）。
- **本项目 1 核 1G 约束下**：单线程跑 1 天 OKX L2（42.5 M 行，实测自 03 稿 §3.3）应可接受（推断，Rust 事件回放通常 >10 M event/s，单核 1 天 ≈ 数十秒级）；但 30 天 × 42.5 M = 12.8 亿事件在单核上仍需数小时（推断），只能用于**离线一次性校准**，不能进 VPS。

#### 已知限制（实测归纳）

1. master 11 个月无提交；2026 下半年 PR 全部未合并。
2. 无 OKX 采集/转换/实盘连接器。
3. 无 HIP-3 / builder-perp-dex 支持。
4. 数据输入只吃 numpy 结构化数组，**Parquet 必须自己转**。
5. 数据质量依赖上游：cryptohftdata 的 Binance USD-M futures orderbook 在 2026-03-01→05-20 期间实测 `pu` 链断口率 **2.48 / 1M 事件**，2026-05-21→06-20 降到 **0.22 / 1M**，2026-05-28 起到 06-20 零断口（以上为 PR #307 评论区 hmate9 2026-06-20 的自测数据，非我方独立验证）→ **用于回测前必须自建序列连续性校验**，这与 03 稿 §4.4 的硬断言一致。

#### 移植难度与结论

| 维度 | 评估 |
|---|---|
| 移植难度 | **2/5**（作为校准器：拉 fork 分支 + pip 装 `cryptohftdata` + 跑 `convert`）；**4/5**（作为生产引擎：数据适配 + 定价层重写 + 与现有 `as_nautilus_strategy.py` 分歧风险） |
| 许可证风险 | **无**（MIT，含 cryptohftdata SDK MIT） |
| 结论 | **采用（仅离线校准器角色）**。不作为生产引擎——与 03 稿结论一致，但 03 稿当时**不知道 cryptohftdata 转换器已存在**，本稿补上这一块 |

---

### 2.2 `nautechsystems/nautilus_trader`

#### 实测档案

| 项 | 实测值 |
|---|---|
| 仓库 | `nautechsystems/nautilus_trader` |
| Star / Fork | ★31520 / 4274 |
| 许可证 | **LGPL-3.0**（仓库 `LICENSE` 首行「GNU LESSER GENERAL PUBLIC LICENSE Version 3」；PyPI `license=LGPL-3.0-or-later`） |
| 主语言 | Rust（Python 绑定用 pyo3） |
| **PyPI 稳定版** | **1.231.0，上传 2026-08-02**，`requires_python >=3.12,<3.15` |
| GitHub release | 最新 `v1.231.0`（2026-08-02） |
| **v2 状态** | tag 列表含 `v2.0.0rc9` … `v2.0.0rc5`，**v2 未 GA** |
| master 最后提交 | **2026-11-14**（当天连续多条：「Fix Hyperliquid order queries without venue order ID」等） |
| Open issue | 105；近期 issue 全部 2026-11-14 更新 |
| 商标 | README 明确写「NautilusTrader™」，并链接 `nautilustrader.io/legal/disclaimer/` |

> **许可证核实结论（任务要求重点）**：**当前版本（v1.231.0 及 master）许可证仍是 LGPL-3.0，没有变成商业闭源**。README 的 License 段落明确指向 GNU LGPL v3.0。我未在仓库中找到任何「企业版许可」或「核心改闭源」的证据文件（未核实：官网商业条款）。→ **许可证风险等级：低-中**。LGPL 的实际约束：动态链接/独立进程调用无强制开源义务；**若把其代码直接复制进我们的 Python/Numba 源码，则触发「修改文件本身需以 LGPL 发布」**。因此我们只能「借鉴思路 + 抄公式 + 抄适配范式」，**不能整段粘贴 Rust/Python 源码**（除非整个项目开源并以 LGPL 兼容方式发布）。→ **实操建议：抄思想、抄协议字段、不抄代码体。**

#### L2 增量与撮合保真度（实测，读 `docs/concepts/backtesting/fill-models.md` 与 `fill-prices-and-matching.md`）

- **L2/L3 走记录下来的订单簿**撮合引擎逐档吃单；`prob_fill_on_limit` 控制「被 touch 的限价单是否可成交」；`prob_slippage` 在 L2 下**不适用**（价格冲击由盘口决定）。
- 11 种内置 fill model：`DefaultFillModel` / `BestPriceFillModel` / `OneTickSlippageFillModel` / `ProbabilisticFillModel` / `TwoTierFillModel` / `ThreeTierFillModel` / `LimitOrderPartialFillModel` / `SizeAwareFillModel` / `CompetitionAwareFillModel` / `VolumeSensitiveFillModel` / `MarketHoursFillModel`。
- **`queue_position` 开关**（实测 `crates/execution/src/matching_engine/config.rs`）：
  ```rust
  #[builder(default = true)] pub queue_position: bool,
  ```
  文档原文（实测）：
  > 「Consumption tracking estimates **available size**, not **order priority**. Set `queue_position=True` with book and trade data for displayed-queue tracking, or use `prob_fill_on_limit` for a probabilistic approximation.」

  → **这就是与 hftbacktest 的关键差异**：nautilus v2 的队列跟踪是「显示队列」级别，**不是 hftbacktest 那种「FIFO 前置量精确判定」**。03 稿 §5 方案 A（保守，队列前置量）必须自己写。

- **订单簿不可变 + 流动性消耗**：文档警告历史盘口成交后不变，若 `liquidity_consumption=False` 同一显示量可被多笔模拟单吃掉 → 需 `liquidity_consumption=True`。这是 03 稿必须实现的硬规则。
- 另有 `order_priority_reset_policy`（`PriceChange` / `OrderPriorityResetPolicy` 变体）控制改单后队列优先权是否重置——对应我们的「成交后 5 秒单侧冷却 + FIFO 优先权保留」。

#### Parquet / 持久化（实测）

- `crates/persistence/src/backend/parquet/` 存在完整 Parquet catalog / consolidation / intervals / migration 实现；另有 `feather_session`。
- → **可借鉴**：nautilus 的 Parquet 目录式 catalog（session / coverage / consolidation state）是我们长期归档 L2 数据的组织方式参考。

#### 实盘适配器列表（实测，目录扫描 `crates/adapters/`）

```
architect_ax  betfair  binance  blockchain  bybit  coinapi  coinbase
databento  deribit  dydx  finfeed  hyperliquid  interactive_brokers
kalshi  kraken  lighter  okx  polymarket  sandbox  tardis
```

- **本项目关心的三个**：`okx`（OKX 现货+永续+期权）、`hyperliquid`、`lighter`。
- **Hyperliquid adapter 关键能力（实测）**：
  - `crates/adapters/hyperliquid/src/book/recovery.rs` 与 `sync.rs` → **L2 订单簿恢复与增量同步**，直接对应我们 `okx_ws_manager.py` 的增量深度拼接。
  - `crates/adapters/hyperliquid/src/http/models.rs` 第 206 行注释实测：
    > `/// Descriptor for a builder-deployed perp dex from POST /info with`
    → **明确建模 builder-deployed perp dex（HIP-3）**。
  - 同一文件实测有 `builder_fee: Option<Decimal>`（serde rename `builderFee`），并有针对 `builderFee` 的反序列化测试。
- `docs/api_reference/adapters/hyperliquid.md` 存在。

#### 结论

| 维度 | 评估 |
|---|---|
| 移植难度 | **整体引入 5/5**；**只抄 hyperliquid adapter 的「perp dex 寻址 + builder fee + book recovery」思路 2/5** |
| 许可证风险 | LGPL-3.0：**抄代码 = 传染**；抄协议字段/思路 = 无风险 |
| 结论 | **借鉴（不采用）**。借鉴点：(a) HIP-3 perp dex 寻址与 builder fee 建模；(b) L2 book recovery/sync 的工程结构；(c) fill model / liquidity consumption 的规则清单；(d) Parquet catalog 的归档组织方式 |

---

### 2.3 其他回测/撮合相关

| 项目 | 实测状态 | 结论 |
|---|---|---|
| `dominolu/titan`（★10，2026-11-14 推送） | 「基于 HFTbacktest 的机构级高频交易回测与实盘框架，Rust 核心 + Python 策略」 | **放弃**：★10、fork 0、无社区验证、中文项目。与我们需求重叠但成熟度为零 |
| `mirkovicdev/HFTENGINE`（★340，2026-09-17） | 「Replay console for hftbacktest market-making backtests」 | **放弃**：只是 hftbacktest 的控制台外壳，我们不需要 UI |
| `mileswangs/pm-hftbacktest`（★131，2026-11-11，MIT） | Polymarket 高频回测 | **放弃**：Polymarket 与我们的 OKX/HIP-3 场景无关 |
| `mansoor-mamnoon/limit-order-book`（★93，C++ core + Python SDK，20M+ msgs/sec，最后提交 2025-08-30，**无 LICENSE 文件**） | 高性能 LOB 引擎 | **放弃（本次仅列名，未深查）**：★93、无许可证文件（NOASSERTION）、15 个月无提交 |
| `LeonardoBerti00/DeepMarket`（★117，MIT，最后提交 2026-01-27） | 「基于深度学习的市场微观结构模拟框架」，论文《TRADES: Generating Realistic Market Simulations with Diffusion Models》官方仓库 | **放弃**：这是**合成数据生成器**，与「严禁合成白噪声/必须真实数据」的项目红线冲突 |

### 2.4 vectorbt / backtrader / zipline-reloaded — 明确不适合微观做市

| 项目 | 实测状态 | 为什么不适合（针对本项目） |
|---|---|---|
| `polakowo/vectorbt` | ★9843；最新 release **v1.2.1（2026-11-11）**，最近提交 2026-11-11 → **活跃**；许可证实测为 **「Apache 2.0 with Commons Clause」**（`LICENSE.md` 明写 "the License does not grant to you the right to Sell the Software"） | ① **向量化 bar 级**引擎，撮合是「按 bar 的 OHLC + 数组布尔运算」，**没有订单簿、没有队列、没有档位**，做市收益无法建模；② Commons Clause **不是 OSI 开源**，含「不得用于销售」的附加限制，商用/对外交付有法律摩擦；③ 与我们「同一份定价代码跑回测和实盘」的红线冲突。**结论：放弃** |
| `mementum/backtrader` | ★23740；**最后提交 2023-04-19**（约 3.5 年无更新）；GPL-3.0；无 GitHub release | ① 维护停滞；② GPL-3.0（比 LGPL 更强的传染性）；③ bar 级撮合，`cheat_on_open` 之类的近似对微观做市无意义。**结论：放弃** |
| `stefan-jansen/zipline-reloaded` | ★2017；**v3.2.1（2026-10-25）**，最近提交 2026-11-02 → **活跃**；Apache-2.0 | ① 引擎是 **日频 bundle + 分钟 bar**，面向股票日频因子回测，无 tick/L2 撮合；② 数据源是 equities bundle（`quandl`/`quandl` bundle），与 crypto L2 无关；③ 依赖链重（numpy/pandas/scipy 全家桶），1 核 1G 上不划算。**结论：放弃**（但其 **Apache-2.0** 值得作为「规范 schema + point-in-time 数据集」设计参考，零风险借鉴） |

> 补充实测：03 稿已记录本机装了 `nautilus_trader 1.221.0` 但 `live_cluster/` 里的 "nautilus" 只是命名借用，实际未使用该库 → **引入真 Nautilus 是新增能力，不是复用**，这一点必须写进任何落地计划。

---

## 3. B 区：微观结构特征与订单簿重建

### 3.1 候选清单（实测）

| 项目 | Star | 最后提交 | 许可证 | 内容 | 结论 |
|---|---|---|---|---|---|
| `alpacahq/example-hftish` | ★876 | 2023-07-25 | **无 LICENSE 文件**（NOASSERTION） | Alpaca 官方「Order Book Imbalance 算法」示例 | **借鉴**（仅思路：OBI 做不平衡信号）。**不可复制代码**（无许可证 = 默认保留所有权利） |
| `hanxixuana/flowrisk` | ★100 | 2021-01-01 | **MIT** | VPIN / Order Flow Risk 的 Python 实现（Notebook） | **借鉴**（VPIN 公式是公开文献，MIT 授权，可直接实现）。**不作为依赖**（6 年未更新） |
| `orphancongdong/orderbook-l2-ofi` | ★5 | 2026-11-06 | MIT | 「Sequence-aware Level-2 Order Book Reconstruction & Cont's OFI」 | **借鉴**（Cont OFI 的实现范式；★5 说明用的人少，需自己验证） |
| `cameronscarpati/lob-regime-scanner` | ★19 | 2026-11-13 | MIT | 「30+ 特征 + 隐马尔可夫 HMM 状态识别 + C++ pybind11 订单簿引擎 + Dash 面板」 | **借鉴（最值得看的特征清单）**：明确宣称是 crypto LOB 的 30+ 工程化特征。需自己核实特征定义是否因果 |
| `LeonardoBerti00/DeepMarket` | ★117 | 2026-01-27 | MIT | LOB 模拟 + 扩散模型生成 | **放弃**（合成数据，与红线冲突） |
| `Jeonghwan-Cheon/lob-deep-learning` | ★162 | 2022-12-11 | **lic=null（无许可证）** | DeepLOB / TransLOB / DeepFolio 各种实现 | **放弃**（无许可证 + 4 年未更新） |
| `zcakhaa/DeepLOB` | ★622 | 2021-07-15 | NOLIC | DeepLOB 论文官方 Notebook | **放弃**（仅 Notebook、5 年未更新、无许可证、无训练管线） |
| `S-razmi/DeepLOB` | ★32 | 2023-08-07 | MIT | Bitcoin 永续数据上的 DeepLOB 实现 | **借鉴**（唯一有 MIT 的 DeepLOB 实现，可参考其数据切片方式） |
| `hudson-and-thames/mlfinlab` | ★4973 | **最后提交 2021-12-01**（pushed 2023-10-02） | **NOASSERTION** | 三重障碍法、purged K-fold、分数阶差分等 | **放弃（许可证硬伤）**：`LICENSE.txt` 实测为「Copyright Protection Notice and Licensing Agreement」，明示订阅制、非业务许可默认、需购买企业许可。**不是开源**。此外代码 5 年未更新 |

### 3.2 `mementoback` / `deepmarket` / 通用 orderbook 类库——本次未找到合格候选（实测）

- 按 `deepmarket`、`orderbook reconstruction + lmdb`、`lmdb market data rust` 等多组关键词检索 GitHub，**未找到**「星标 ≥100 且近 2 年活跃」的专用订单簿重建/存储库。
- 结论：**「mementoback」在本镜像的 GitHub 上不存在**（404）。订单簿重建这件事**没有现成库可用**，03 稿 §4 的自研订单簿状态机是必需的。

### 3.3 特征层结论

> 微观结构特征（OFI / OBI / VPIN / Kyle λ）**全部需要自己写**，但有 MIT 授权的参考实现与公开文献公式。工作量集中在 03 稿配套的特征表里，不在选型里。

---

## 4. C 区：机器学习训练框架

### 4.1 CPU 推理加速路径（实测）

| 项目 | Star | 版本 / 发布日 | 许可证 | 用途 | 1 核 1G 结论 |
|---|---|---|---|---|---|
| `microsoft/LightGBM` | ★18977 | **v4.7.0（2026-07-18）**，最近提交 2026-11-12 | MIT | 本项目现有三模型（`checkpoints/lgb_*.txt`）的训练/推理 | **保持现状**。本项目已经是 LightGBM，不换 |
| `microsoft/onnxruntime` | ★22305 | **v1.32.0（2026-11-13）**，master 2026-11-14 仍有提交 | MIT | 通用推理加速 | **可选**。单线程 CPU EP 在 1 核上对 3 个小模型收益有限 |
| `dmlc/treelite` | ★832 | **4.8.1（2026-10-27）** | Apache-2.0 | 树模型专用编译/序列化 | **可选**。收益在于把 tree 编译成紧凑二进制，**省内存**比省 CPU 更有意义 |
| `skl2onnx`（PyPI） | — | **1.20.0（2026-01-30）**，Apache-2.0 | Apache-2.0 | LightGBM → ONNX 转换 | **可选**，见 §4.2 的降级路径决策 |
| `dmlc/xgboost` | ★28972 | v3.4.2（2026-09-15） | Apache-2.0 | 备选 GBDT | **放弃**（无理由换） |
| `catboost/catboost` | ★9202 | v1.2.10（2026-02-19） | Apache-2.0 | 备选 GBDT | **放弃**（无理由换） |

#### 关于 LightGBM 推理的三个可选路径（建议 + 推断）

| 路径 | 做法 | 预期收益 | 风险 | 建议 |
|---|---|---|---|---|
| **P0：现状** | `lightgbm.Booster.predict()` 直接用 `.txt` 模型 | 基线 | 无 | **先用这个**，把特征对齐和因果性做对 |
| **P1：LightGBM C API** | 加载 `Booster` → `LGBM_BoosterPredictForMat` | 省掉 Python→C 的 dataframe 转换与 pandas 开销 | 需要 ctypes 绑定，接口不稳 | 值得，**优先于 ONNX** |
| **P2：ONNX Runtime** | `skl2onnx` 导出 → `onnxruntime.InferenceSession`（单线程 EP） | 免 LightGBM 运行时依赖，VPS 镜像更小 | 转换有精度/算子覆盖坑 | **仅在 P1 收益不足时做** |

**明确不推荐**：GPU 路径。VPS 1 核 1G 无 GPU；且我们的模型是 3 个小树模型，瓶颈不在推理算力，在**事件循环抖动**（实测 10–50 ms）。

### 4.2 LOB 深度学习模型的可复现实现（全部实测）

| 项目 | Star | 最后提交 | 许可证 | 训练管线完整性 | 推理延迟 | 结论 |
|---|---|---|---|---|---|---|
| `zcakhaa/DeepLOB` | ★622 | 2021-07-15 | NOLIC | 仅 Notebook，无环境固定、无数据管线 | 未核实 | **放弃** |
| `Jeonghwan-Cheon/lob-deep-learning` | ★162 | 2022-12-11 | **无** | 有多种模型实现，但是实验代码 | 未核实 | **放弃** |
| `S-razmi/DeepLOB` | ★32 | 2023-08-07 | MIT | Notebook，含 BTC 永续数据切片 | 未核实 | **借鉴数据切片**，不采用模型 |
| `jwallbridge/translob` | ★125 | 2020-08-09 | NOLIC | TransLOB 原作者仓库，5 年未更新 | 未核实 | **放弃** |
| `zelinwang123/translob` | ★4 | 2021-09-09 | BSD-3-Clause | PyTorch TransLOB | 未核实 | **放弃**（★4） |

**共性结论（实测归纳）**：

1. **没有一套是「完整训练管线」**：普遍只有 Notebook + 论文超参，没有固定依赖、没有数据版本、没有 checkpoint 规范、没有复现脚本。
2. **普遍无许可证或仅 Notebook 许可** → 即使想抄也无处可抄。
3. **LOBSTER 数据集**相关训练代码分散、且 LOBSTER 是付费数据集（免费只开放 sample），与我们已有的 cryptohftdata 数据源**重复且更差**。
4. **训练需 GPU**：DeepLOB/TransLOB 的原始设定是 LOBSTER 10 档 × 100 事件窗口的 CNN/Transformer，在 1 核 1G 上不可行。**降级路径**：把「深度模型」替换成「LOB 特征 + LightGBM」，这正是本项目现状；或把 DeepLOB 蒸馏成小模型（不建议，收益不明确）。

### 4.3 `TabPFN`（`PriorLabs/TabPFN`）

- 实测：★8459 / 824 forks，**Apache-2.0**，最新 release **v10.0.0（2026-11-13）**，master 2026-11-13 仍活跃。
- **1 核 1G 可行性**：TabPFN 是 tabular foundation model，**单次推理需 GPU**（官方主推 GPU/CPU 混合），CPU 推理虽存在但延迟与内存都不适合 5 分钟级看门狗的 1 核 VPS（推断）。
- **更关键的问题**：TabPFN 是**表格分类/回归**模型，其核心假设是「特征间无序、无时序因果结构」。我们的特征是**严格因果的时序量**（60 秒滚动 OFI、ADX(14)、库存偏置），TablePFN 的归纳偏置与「未来函数禁入」并不冲突，但：
  - 它**无法表达时序依赖**，只能把窗口拍平成一行的静态特征；
  - 我们的训练样本量（百万级行、但有效独立样本按天算只有数百）**远低于** TabPFN 期望的表格数据规模。
- **结论：放弃**。作为「探索性基线」在 Kaggle 上跑一次可以（Kaggle 有 GPU），但**不进生产**，不作为看门狗决策依据。
- 备选：`PriorLabs/nanoTabPFN`（★221，Apache-2.0，轻量教学重实现）—— 若要在本地做无 GPU 的最小验证，用它而非原版。

### 4.4 特征存储（Feature Store）

| 项目 | 实测 | 结论 |
|---|---|---|
| `feast-dev/feast` | ★7362 / 1499 forks，**Apache-2.0**，最新 release **v0.68.0（2026-11-10）**，master 2026-11-14 活跃，open issue 382 | **放弃**。Feast 需要 Redis / SQL store 等在线存储组件，**在 1 核 1G 上是负担**；我们只有 3 个模型 + 5 分钟级 cron 看门狗，特征窗口是滚动计算的，不需要 point-in-time 特征库 |
| `oom-ai/oomstore` | ★91，Apache-2.0，最后提交 **2022-02-28** | **放弃**（停更 4 年） |
| `thanhauco/zephyr-ml-feature-store` | ★0，2026-08-04 | **放弃**（无验证） |
| 「Kanesh」 | **本次检索未找到任何以此命名且合格的 feature store 项目（未核实）** | — |

> **建议（本文档）**：本项目的特征存储就是 **Parquet 特征快照 + 版本化 JSON schema**，落到 `lake/features/{date}/{symbol}.parquet`，配一个 `feature_contract.json` 声明列名、dtype、因果窗口、产出版本。已有的 `cron_accountbot3_ml_guard.py` 只需保证「特征产出时间 < 决策时间 < 特征快照里的 `feature_ts`」三者单调。**不引入任何框架。**

---

## 5. D 区：实盘执行与交易所接口

### 5.1 各交易所 SDK 实测对比

| 交易所 | 一方 SDK（实测） | 活跃度 | 许可证 | HIP-3 / RWA 相关 | 结论 |
|---|---|---|---|---|---|
| **OKX** | **未找到官方 Python SDK 仓库**：`okx/okx-py`、`okx/okx-api-v5`、`okx/okx-api-v5-demo` 均 404；`okx` org 下全是链上/cosmos 相关仓库 | — | — | OKX 有 RWA 现货（如 xAUT/USDT 类），但本项目当前是 OKX 永续 | **放弃依赖官方 SDK**：我们已有 `live_cluster/gateway_okx_client.py`（HMAC-SHA256、IPv4 强制、批量撤单、限频重试），继续自研即可。第三方 SDK（`iaping/go-okx` ★53 等）质量参差，不引入 |
| **Hyperliquid** | **`hyperliquid-dex/hyperliquid-python-sdk`**（★1886，**MIT**，最新 release **0.24.0（2026-06-04）**，最后提交 2026-06-04） | 约 5 个月未提交 | MIT | ✅ **明确支持 HIP-3**：实测 `hyperliquid/info.py` 有 `perp_dexs: Optional[List[str]] = None` 参数，并构造 `perp_dex_to_offset`（`builder-deployed perp dexs start at 110000`，即 `110000 + i*10000`）；`hyperliquid/exchange.py` 的 `bulk_orders(..., builder: Optional[BuilderInfo])` 支持 builder 手续费；官方示例 `examples/basic_order_with_builder_deployed_dex.py`、`examples/basic_spot_to_builder_deployed_perp_dex.py` | **采用（借鉴 + 局部移植）**。这是本次调研中**唯一**明确支持 HIP-3 的一方 SDK |
| **Lighter** | 无一方 SDK。社区：`robustfengbin/lighter-sdk`（★13，Rust，NOLIC，2025-11-26）、`defi-maker/pylighter`（★39，NOLIC，2025-09-29）、`blackcubeio/lighter-sdk`（★0，TS，BSD-3-Clause） | ★13 / ★39 / ★0 | 多为 NOLIC | — | **谨慎**。但 **`nautilus_trader` 有 `crates/adapters/lighter/`**（实测，含 `benches/`、`fuzz/`、`signing/`），是比社区 SDK 更可信的协议实现参考 → **借鉴 nautilus 的 lighter adapter**（`未核实`其完备性） |
| **Robinhood** | **无官方加密交易 API 仓库**。仅社区 demo：`hackingthemarkets/robinhood-official-crypto-api`（★25，2025-02-28，NOLIC）、`jamestford/pyhood`（★25，MIT，2026-11-09，社区逆向 API） | — | — | — | **放弃**。加密 API 现状**未核实**（无法确认官方文档现状）；即便存在，社区逆向实现不适合做市实盘，且**与 HIP-3/RWA 无关** |
| **Bybit** | `bybit-exchange/api-usage-examples`（★222，2026-09-09）、`bybit-exchange/trading-mcp`（★44，MIT，2026-11-13） | 活跃 | 官方 examples 无 LICENSE | — | **不引入**（我们当前主战场是 OKX + Hyperliquid HIP-3） |
| **Binance** | `binance/binance-connector-python`（★257，2026-11-14 活跃）；`sammchardy/python-binance`（★7224，**MIT**，最新 v1.0.37 **2026-06-08**，约 5 个月未提交） | 社区库略滞 | MIT | — | **放弃**（我们不用 Binance 实盘；仅作为 cryptohftdata 数据源被使用） |

### 5.2 `ccxt` / `ccxt.pro` / `async_ccxt`

- 实测：`ccxt/ccxt` ★44880 / 8979 forks，**MIT**，最新 release **v4.5.92（2026-11-04）**，master 2026-11-13 活跃。
- **`ccxt.pro` 独立仓库已不存在**（`ccxt/ccxt.pro` → 404），但 **`ts/src/pro/` 在主仓库内**（实测目录：`cs/ccxt/exchanges/pro/alpaca.cs` 等），即 **ccxt.pro 已并入主仓库**，WebSocket 实现在 `ts/src/pro` 与 `python/ccxt/pro`。
- **高频场景适用性判断（推断 + 建议）**：
  - ccxt 的 REST 调用是**统一抽象层**，每次调用都有参数校验、符号解析、隐式 HTTP 客户端选择 → 单次往返额外开销在**几十到几百毫秒量级**（推断），对 45–75 ms 的下单链路是**不可接受的量级放大**。
  - ccxt.pro 的 WS 封装按交易所差异抹平，反而**掩盖了**「增量序列号连续性」「快照对齐」这类我们必须自己处理的语义。
  - **结论：放弃 ccxt 作为执行通道**。但它有**两个真实用途**：
    1. **交易所能力矩阵的参考**（哪个所支持什么下单类型、费率、批量撤单上限）——查文档用，不进代码；
    2. **若将来要接一家没写过客户端的小交易所**，ccxt 是合理的「一次性适配」工具，但那时也应直接抄 REST 协议而非引入整个框架。

### 5.3 Hummingbot（重点：仓位控制与费率感知）

- 实测：`hummingbot/hummingbot` ★21207 / 5148 forks，**Apache-2.0**，最新 release **v2.17.0（2026-09-22）**，master 最后提交 2026-09-22（pushed 2026-11-13），open issue 204。
- **连接器覆盖面（实测目录扫描）**：`exchange/` 下含 **okx、hyperliquid、lighter、bybit、binance、kraken、kucoin、okx_perpetual、hyperliquid_perpetual、lighter_perpetual、bybit_perpetual、dydx_v4_perpetual、injective_v2、kalshi、polymarket 生态** 等 40+ 个。
  → **本项目的目标交易所全覆盖**（OKX / Hyperliquid / Lighter）。
- **v2 架构（实测）**：
  - `hummingbot/strategy_v2/controllers/`：`market_making_controller_base.py`、`directional_trading_controller_base.py`、`controller_base.py`
  - `controllers/market_making/`：`pmm_simple.py`、`pmm_dynamic.py`、`dman_maker_v2.py`
  - `hummingbot/strategy_v2/executors/`：`position_executor`、`grid_executor`、`dca_executor`、`arbitrage_executor`、`executor_orchestrator.py`
  - `hummingbot/strategy_v2/backtesting/`：**v2 控制器自带回测模拟器**（`executor_simulator_base.py`、`order_executor_simulator.py`、`position_executor_simulator.py`、`grid_executor_simulator.py`）
- **费率感知（实测）**：
  - `hummingbot/core/data_type/trade_fee.py` —— 费率的数据类型
  - `hummingbot/core/utils/estimate_fee.py` —— 费率估算
  - `hummingbot/client/config/trade_fee_schema_loader.py` —— 费率表加载
  - `position_executor.py` 实测有 `cum_fees_quote` / `cum_fees_base` / `get_cum_fees_quote()`，并显式处理「手续费以 base 计价时换算」（第 90–91 行：`if self._open_order.fee_asset == ... base: open_filled_amount = executed_amount_base - cum_fees_base`）
  - → **这是最值得借鉴的一块**：费率不是「手续费率常量」，而是**订单级、币种级、需要换算**的对象。我们当前的「≥9.0 bps 总价差门槛」是硬编码常数，应升级为「按名义额动态计算门槛」。
- **仓位控制**：`position_executor.py` 负责开仓/平仓/止盈止损；`market_making_controller_base.py` 有 `get_spreads_and_amounts_in_quote`（按 quote 计价分档）、`get_required_base_amount`（算清 base 需求再下单）、`PositionMode` 校验、`triple_barrier_config`（三重障碍）。
- **借鉴点清单**：
  1. `trade_fee` 数据类型 + `estimate_fee` 的**订单级费率语义** → 改造我们的手续费门槛计算；
  2. `get_required_base_amount` 的**先算后下单**顺序 → 对应我们 30U 本金下 0.01 张 = 8.08 USDT（占总资产 27%）的离散粒度问题（03 稿 §本金粒度）；
  3. `position_executor` 的**手续费归集与 PnL 拆分**（`trade_pnl_quote` vs `cum_fees_quote`）→ 让我们的小时级绩效报告口径与 Hummingbot 一致，便于横向对标；
  4. `strategy_v2/backtesting/` 的**控制器回测模拟器**思路 → 若我们要把 03 稿的自研引擎做成「策略层可复用」，可参考其分层。

### 5.4 Freqtrade

- 实测：`freqtrade/freqtrade` ★56874 / 11752 forks，**GPL-3.0**，最新 release **2026.10（2026-10-30）**，master 2026-11-12 活跃，open issue 仅 24 → 维护质量高。
- **定位**：K 线级现货/杠杆交易机器人，带 hyperopt 参数优化、freqai ML 模块。
- **结论：放弃**。① GPL-3.0（传染性最强，抄代码必须整体 GPL）；② 交易循环是 **candle 级**（`--timeframe` 最小 1m），做市需要 tick/事件级；③ FreqAI 的 ML 流程是「特征 → 分类器 → 信号 → 仓位」，与我们的「A-S 定价 + 队列优先权」模型不同层。

### 5.5 NautilusTrader 的 live adapter 列表

见 §2.2「实盘适配器列表（实测）」。补充要点：

- 21 个适配器，含 `okx`、`hyperliquid`、`lighter`、`databento`、`tardis`、`bybit`、`binance`、`kraken`、`deribit`、`dydx`、`polymarket`、`kalshi` 等。
- **HIP-3 支持确认（实测）**：`crates/adapters/hyperliquid/src/http/models.rs` 第 206 行注释 `Descriptor for a builder-deployed perp dex from POST /info with`，同文件含 `builder_fee: Option<Decimal>`（`rename = "builderFee"`）及其反序列化测试。
- **L2 订单簿恢复（实测）**：`crates/adapters/hyperliquid/src/book/{recovery.rs,sync.rs}`。

---

## 6. E 区：数据基础设施

### 6.1 `cryptohftdata` 本体（已有文档，此处补「本次新增核实」）

| 项 | 实测 |
|---|---|
| 官方 Python SDK | **存在**：`cryptohftdata` PyPI **0.8.1，上传 2026-11-09**，**MIT**，`requires_python >=3.8`，summary「Python SDK for accessing cryptocurrency high-frequency trading data」 |
| 文档 | `https://www.cryptohftdata.com/developers`，OpenAPI：`https://www.cryptohftdata.com/.well-known/openapi.json` |
| 版本历史 | 0.2.2 / 0.3.0 / 0.4.0 / 0.6.0 / 0.6.1 / 0.7.0 / 0.8.0 / 0.8.1 |
| 生态扩展（实测） | `hmate9/vnpy_cryptohftdata`（★0，MIT，2026-07-13，VeighNa 数据源）；`hmate9/Lean.DataSource.CryptoHFTData`（★0，Apache-2.0，2026-07-13，QuantConnect LEAN 数据源）→ **SDK 已被第三方框架采纳，是成熟度信号** |
| 与 hftbacktest 的集成 | PR #307（见 §2.1），转换器要求 `cryptohftdata>=0.4.0` |

> **结论：采用官方 SDK**。理由：(a) MIT；(b) 免鉴权 free tier 已够用（PR #307 实测：keyless 下载，`CRYPTOHFTDATA_API_KEY` 可选）；(c) SDK 内部已实现「按小时 parquet 分块 + 并发下载（`max_workers`，默认 10）」，正是我们手搓 `GET /v1/download` 时最容易写错的部分（分段重试、文件名拼装、302 签名 URL 跟随）；(d) 已被 hftbacktest / vnpy / LEAN 三方采纳。

**未核实**：SDK 的具体并发/重试实现细节（未读源码）；免费 tier 的速率限制具体数值。

### 6.2 替代数据源对比（实测）

| 数据源 | 仓库 / Star | 最后提交 | 许可证 | L2 增量覆盖 | 结论 |
|---|---|---|---|---|---|
| **Tardis.dev** | `tardis-dev/tardis-python` ★149 | **2026-10-28** | **MPL-2.0** | 有（tick 级），多交易所 | **备用**。MPL-2.0 是文件级 copyleft（改了就必须以 MPL 开源该文件），**比 MIT 更严格但比 GPL 弱**。可作为交叉校验源（同一时刻两个源的盘口是否一致） |
| **Databento** | `databento/databento-python` ★312 | **2026-11-14** | Apache-2.0 | 有（CME 等传统资产为主） | **备用**。已实测 nautilus 内置 `databento` 转换器 → 若将来做美股/期货做市，是首选数据源；对 crypto 覆盖弱 |
| **dxFeed** | `dxFeed/dxfeed-python-api` ★47 | 2025-08-18 | MPL-2.0 | 有（商业级） | **放弃**：★47、15 个月未提交、MPL-2.0、商业授权另计 |
| **Nasdaq Data Link** | `Nasdaq/data-link-python` ★629 | 2026-09-15 | MIT | ❌ 无 crypto L2 | **放弃**：只有股票/基金/宏观，无法覆盖本项目场景 |
| **Hugging Face crypto datasets** | 实测存在若干：`AdamAtractor/Crypto-L2-Orderbook-Depth-24-Instruments`（467 下载，2026-04-06）、`AdamAtractor/24_crypto_orderbook_30lvl`（336，2026-09-02）、`rameez543/crypto_orderbook_snapshots`（125，2026-05-09）、`THULab/crypto_orderbook_30lvl`（81，2026-09-10） | — | 各自 | 有 L2 快照 | **放弃作为主源**。下载量 30–467，来源与采集方式不透明，**无法核实序列连续性**。可作为「第三方独立快照」做交叉校验的一票 |
| `hmate9/vnpy_cryptohftdata` / `hmate9/Lean.DataSource.CryptoHFTData` | ★0 | 2026-07-13 | MIT / Apache-2.0 | — | **借鉴**：看别人怎么把同一数据源接进成熟框架，可借鉴其数据契约设计 |

### 6.3 订单簿增量数据的 Parquet/ZSTD 存储实践

> 以下为**建议 + 推断**（我没有对 cryptohftdata 全部历史文件做压缩比实测，仅基于 Parquet/Arrow 的通用机制给出参数与验收方法）。

#### 参数建议

| 参数 | 建议值 | 理由 |
|---|---|---|
| `compression` | **`zstd`，level 6** | 层级增量数据里 price/size 高度重复，zstd 的字典匹配比 snappy 强得多；level 6 是速度/压缩比甜点（推断） |
| `compression_level` | 6（存储）/ 1（热缓存读写） | 冷存用 6，热层用 1 |
| `row_group_size` | **262144 行（256K）或按「每文件 1–4 个行组」反推** | 太小 → 元数据膨胀、谓词下推粒度差；太大 → 单行组解码内存尖峰。**在 1 核 1G 上，单行组解码峰值内存 ≈ row_group_size × 展开后行宽**，256K 行 × ~100 B ≈ 25 MB，可接受（推断） |
| `data_page_size` | **1 MB**（`data_page_size=1048576`） | 默认 1 MB 合适；配合 ZSTD 让页内熵编码生效 |
| `write_batch_size` | 65536–262144 | 与行组对齐，避免行组边界碎片化 |
| `dictionary_pagesize_limit` | 1 MB（默认即可） | `side` / `event_type` / `src` 是低基数列，字典编码收益大 |
| `use_dictionary` | `['side','event_type','src']` 显式开 | 其余数值列用 RLE/DELTA 更划算 |
| `sorting_columns` | 不设（数据已按 ts 排序，Parquet 不支持排序列） | — |
| **落盘粒度** | **按交易所 × 数据族 × 小时**（与 cryptohftdata 原始归档一致：`{exchange}/{date}/{HH}/{SYMBOL}_{dtype}.parquet`） | 单文件小时级 ≈ 1.77 M 行 / ~7.4 MB（03 稿实测推算），任何机器都能整块读进内存 |
| 规范化层 | `{symbol}/{date}/events.parquet` + 预编译 `.npy` 列式缓存 | 03 稿 §3.3 已定 |

#### 验收方法（建议）

落盘后必须跑一次压缩比与内存审计：

```python
import pyarrow.parquet as pq
f = pq.ParquetFile(path)
md = f.metadata
print("rows", md.num_rows, "row_groups", md.num_row_groups,
      "bytes", md.serialized_size)
for i in range(md.num_row_groups):
    rg = md.row_group(i)
    print(i, rg.num_rows, rg.total_byte_size / 1e6, "MB uncompressed")
print("file MB", path.stat().st_size / 1e6,
      "ratio", md.total_byte_size / path.stat().st_size)
```

- **建议验收阈值**：压缩比 ≥ **8×**（层级增量数据的合理区间，推断）；单 row group 解码后内存 < **64 MB**。
- 写入骨架：

```python
import pyarrow as pa, pyarrow.parquet as pq

def write_events(path, tbl: pa.Table, row_group_size: int = 262_144):
    pq.write_table(
        tbl, path,
        compression="zstd",
        compression_level=6,
        use_dictionary=["side", "event_type", "src"],
        data_page_size=1 << 20,
        row_group_size=row_group_size,
        write_batch_size=131_072,
        version="2.6",
        store_schema=True,
    )
```

---

## 7. 推荐移植清单（Top 5，按优先级）

> 优先级判据：**(对本项目短板的补齐程度) ÷ (移植成本 + 许可证风险)**。

### 🥇 第 1 名：`hftbacktest` + cryptohftdata 转换器 —— 作为**离线校准真值**

- **为什么是它**
  - 它是本次唯一达到「可直接移植」门槛的回测引擎（MIT，★5084，Rust 核心，队列感知，延迟模型内置）。
  - **PR #307 已经把我们的数据源接进去了**：转换器 423 行 + 测试 240 行 + CLI + 教程，代码在 `hmate9/hftbacktest@cryptohftdata` 分支（**实测分支仍存在**），MIT。
  - 它提供了我们自研引擎**最缺的两样东西**：① 概率队列模型的**可对照语义**（`SquareProbQueueModel` / `LogProbQueueModel2` / `PowerProbQueueModel3`）；② **延迟模型的现成实现**（`feed_order_latency`，用真实 feed latency 反推订单延迟）。
  - **关键交叉验证价值**：它的 cryptohftdata 转换器与我们 03 稿独立整理的字段映射**逐字段一致**，等于第三方对我们的 schema 契约做了背书。
- **第一步怎么动手**
  1. 拉分支：
     ```bash
     git clone --branch cryptohftdata https://github.com/hmate9/hftbacktest.git /tmp/hftb-chd
     # 取文件：py-hftbacktest/hftbacktest/data/utils/cryptohftdata.py
     #        py-hftbacktest/tests/test_cryptohftdata.py
     ```
  2. 在**开发机**（不是 VPS）建独立 venv：`pip install "hftbacktest==2.4.4" "cryptohftdata>=0.8.1" polars`（`hftbacktest` 是 maturin 编译的 wheel，Python ≥3.11，依赖 numba ~0.61 → 与我们现有 numba 环境可能冲突，**必须隔离 venv**）。
  3. 取 OKX 永续 1 天 L2：`download_and_convert("BTC-USDT-SWAP", "okx_futures", "2026-11-01", "2026-11-02", output_filename="...")`（注意：exchange 标识必须是 `okx_futures`，共享上下文已实测 `exchange=okx` 返回 count=0）。
  4. 跑 `examples/GLFT Market Making Model and Grid Trading.ipynb` 的简化版 → 得到 **hftbacktest 视角的 A-S/GLFT 参数表现**。
  5. 用我们的 Numba 引擎跑**同一份数据、同一套参数** → 输出**差异对照表**（成交笔数、成交均价、maker 成交率、库存轨迹）。
- **预计工作量**：**1.5–2 人日**（含环境隔离 0.5 日、跑通 0.5 日、对照报告 1 日）。**不进入 VPS**，只在开发机离线跑。
- **与 03 稿的一致性**：03 稿结论「hftbacktest 不引入」指的是**不作为生产引擎**；本稿补的是「**可以引入为离线校准器**」，两者不冲突，且 03 稿当时不知道 cryptohftdata 转换器的存在。
- **交付物**：`reports/hftbacktest_calibration_2026-11-xx.md`（同数据同参数的差异表 + 结论：我们引擎乐观偏差是多少）。

### 🥈 第 2 名：hftbacktest 的**概率队列模型数学** → 照抄进 Numba 引擎

- **为什么是它**：03 稿 §5「方案 B（概率模型）」需要一套**可引用、可复核**的公式。hftbacktest 的三种模型命名与形式明确（`SquareProbQueueModel` 等），且 MIT 授权，可以合法照抄公式。
- **第一步怎么动手**：读 `hftbacktest` Rust 源码中的 `SquareProbQueueModel` / `LogProbQueueModel` / `PowerProbQueueModel` 实现（`crates/hftbacktest/src/models/queue.rs` 附近，具体路径需在 clone 后确认）→ 写成 Numba `@njit` 函数 → 用 03 稿 §5.3 的公式做一致性断言测试。
- **预计工作量**：**0.5–1 人日**（读源码 0.5 日 + Numba 实现与单测 0.5 日）。
- **注意**：**只抄公式，不抄 Rust 代码体**（虽然 hftbacktest 是 MIT，抄 Rust 也要保留 MIT 许可声明；抄数学公式无此问题）。

### 🥉 第 3 名：`nautilus_trader` 的 **hyperliquid adapter 范式** → 移植进我们的 V2 WS 引擎

- **为什么是它**
  - **HIP-3 是本项目的硬需求**（RWA 资产），而 nautilus 是本次调研中**唯一实测确认支持 builder-deployed perp dex** 的成熟框架：`crates/adapters/hyperliquid/src/http/models.rs` 第 206 行起有 perp dex 描述符，`builder_fee` 有完整 serde 定义与测试。
  - 它还有 `book/recovery.rs` 与 `book/sync.rs` → **L2 订单簿恢复与增量同步**的工程范式，正是我们 `okx_ws_manager.py` 的短板（我们目前只拼 `books5`）。
  - 它的 `order_priority_reset_policy`（改单后队列优先权是否重置）对应我们「成交后 5 秒单侧冷却 + FIFO 优先权保留」的规则化表达。
- **第一步怎么动手**
  1. 只读 3 个文件：`crates/adapters/hyperliquid/src/http/models.rs`（perp dex + builder fee 数据结构）、`src/book/recovery.rs`、`src/book/sync.rs`。
  2. 提炼成我们的实现规格（写进 `docs/design/06-hyperliquid-hip3.md`）：**perp dex 寻址表**（名称 → `110000 + i*10000` 偏移，实测自官方 SDK）、**builder fee 协商流程**、**L2 快照+增量对齐算法**。
  3. **不复制代码**（LGPL 传染性），只提炼协议字段与算法步骤，重写实现。
- **预计工作量**：**1–1.5 人日**（读源码 + 写规格 + 我们的实现）。
- **许可证风险**：**零**（只借鉴思路与协议字段）。
- **附加**：Hyperliquid 官方 SDK（MIT）里 `perp_dexs` 参数 + `perp_dex_to_offset` 的具体构造逻辑，可以直接对照抄（MIT，允许复制，保留版权声明即可）。

### 4️⃣ 第 4 名：`cryptohftdata` 官方 Python SDK 0.8.1（MIT）

- **为什么是它**：我们目前手搓 `GET /v1/download` + 302 跟随 + 免鉴权 free tier，这部分「轮询、文件名拼装、失败重试」是纯重复劳动且易错；SDK 已经处理了「按小时分块 + `max_workers` 并发 + 可选 API Key」，而且**已被三方框架采纳**（hftbacktest PR #307、VeighNa 数据源、QuantConnect LEAN 数据源）。
- **第一步怎么动手**
  ```python
  from cryptohftdata import CryptoHFTDataClient
  client = CryptoHFTDataClient(api_key=None)          # free tier
  ob = client.get_orderbook(symbol="BTC-USDT-SWAP", exchange="okx_futures",
                            start_date="2026-11-01", end_date="2026-11-02",
                            max_workers=4)
  tr = client.get_trades(symbol="BTC-USDT-SWAP", exchange="okx_futures",
                         start_date="2026-11-01", end_date="2026-11-02",
                         max_workers=4)
  ```
  → 与我们现有 `download_real_btc_1m.py` / 03 稿 §3.3 的规范化管道对接，做**双跑对比**（SDK 下载 vs 手搓下载，校验文件字节或行数一致）后再切换。
- **预计工作量**：**0.5 人日**（含双跑校验）。
- **风险**：SDK 是新的（0.x），**API 可能变** → 必须把 SDK 调用**封装在一个 adapter 函数后面**，且**保留手搓 REST 客户端作为 fallback**（这与我们已有的「多容器/弱网」环境相符）。
- **未核实**：SDK 的实际重试与限流行为。

### 5️⃣ 第 5 名：hftbacktest 的 `feed_order_latency` → **用真实行情延迟反推我们的下单延迟假设**

- **为什么是它**：我们实测 RTT 到 OKX 撮合约 **45–75 ms**，单核多容器导致事件循环抖动 **10–50 ms**。但回测里「下单延迟」目前是拍脑袋的常数。hftbacktest 的 `generate_order_latency(feed_file, ...)` 用**真实行情的 feed latency**（`local_ts - exch_ts`）反推：
  ```
  order_entry_latency    = mul_entry  * feed_latency + offset_entry
  order_response_latency = mul_resp   * feed_latency + offset_resp
  ```
  再以 1 秒为重采样间隔落成 `(req_ts, exch_ts, resp_ts)` 数组喂给撮合器。→ 这正是我们要的：**延迟不是常数，而是随行情繁忙度波动的**，能直接解释「波动大时成交质量差」。
- **第一步怎么动手**
  1. 在开发机上用第 1 名已转换好的 npz 事件数组跑 `generate_order_latency(...)`。
  2. 用我们 03 稿的规范化 schema（`local_ts`/`exchange_ts`）自己算一版 `feed_latency`，对比两条曲线。
  3. **标定参数**：`offset_entry` 设为 **45 ms**（实测 RTT 下界），`offset_resp` 设为 **10–50 ms**（实测事件循环抖动范围），`mul_entry`/`mul_resp` 先设 1.0 起步；然后做**双参数网格扫描**（`offset_entry ∈ {30,45,60,75} ms` × `offset_resp ∈ {10,30,50} ms`），找「回测 maker 成交率 ≈ 实盘」的组合。
  4. 把标定结果写进 03 稿 §7 延迟模型。
- **预计工作量**：**0.5–1 人日**。
- **为什么排第 5 而不是更高**：它只解决「延迟」这一个维度，且最终要落回我们自己的引擎；价值明确但覆盖面窄。

---

### 备选（值得做但排在 Top 5 之后）

| 备选 | 动作 | 工作量 | 价值 |
|---|---|---|---|
| Hummingbot `trade_fee` / `estimate_fee` 语义 | 把我们的「≥9.0 bps 硬门槛」升级为**订单级、币种级、动态计算**（含 base 计价手续费换算） | 0.5 人日 | 直接对应实测「手续费占亏损 72.6%」的历史教训 |
| Hummingbot `get_required_base_amount` 的「先算后下单」 | 对应 30U 本金下 0.01 张 = 8.08 USDT（占 27%）的离散粒度问题 | 0.5 人日 | 防止「数学上连续、现实中爆仓」 |
| LightGBM C API 推理（P1 路径） | ctypes 绑定 `LGBM_BoosterPredictForMat`，去掉 pandas 开销 | 0.5 人日 | 1 核下省 CPU = 降事件循环抖动 |
| nautilus Parquet catalog | 借鉴其 session/coverage/consolidation 三件套，做长期 L2 归档目录 | 1 人日 | 数据生命周期管理 |
| Tardis.dev 作为交叉校验源 | 同源同一时刻对比盘口，检测 cryptohftdata 的缺口 | 0.5 人日 | 数据可信度（实测已存在 0.22–2.48/1M 事件断口） |

---

## 8. 明确放弃清单（请勿浪费时间）

> **这一节和 Top 5 同样重要。**

| 项目 | 放弃理由（一句话） | 硬证据 |
|---|---|---|
| **vectorbt** | bar 级向量化引擎，没有订单簿/队列，做市收益无法建模；且许可证是 **Apache 2.0 + Commons Clause**（禁止「Sell」），非 OSI 开源 | 实测 `LICENSE.md` 首行「Commons Clause License Condition v1.0」 |
| **backtrader** | 最后提交 2023-04-19（3.5 年前），GPL-3.0 传染性最强，bar 级撮合 | 实测 API |
| **zipline-reloaded** | 日频 bundle + 分钟 bar 引擎，无 tick/L2，数据是 equities bundle，依赖链重 | 实测 v3.2.1 / Apache-2.0，但定位不符 |
| **mlfinlab (Hudson & Thames)** | **不是开源**：`LICENSE.txt` 是订阅制「Copyright Protection Notice and Licensing Agreement」，非业务许可需购买企业许可；代码最后提交 2021-12-01 | 实测读 `LICENSE.txt` |
| **DeepLOB / TransLOB 全部实现** | 全是论文实验代码：无固定依赖、无数据版本、无 checkpoint 规范；多数无 LICENSE；需 GPU | 实测各仓库 LICENSE/最后提交 |
| **TabPFN** | tabular foundation model，需 GPU，归纳偏置与严格因果时序特征不匹配，1 核 1G 不可行 | 实测 Apache-2.0 / v10.0.0，但定位不符 |
| **Feast** | 需要 Redis/SQL 在线存储，1 核 1G 上是负担；我们只需 3 个模型 + 5 分钟级窗口特征 | 实测 v0.68.0 / Apache-2.0 |
| **ccxt / ccxt.pro** | REST 抽象层每次调用的额外开销在几十到数百毫秒量级，放大 45–75 ms 的下单链路；WS 封装抹平了序列号连续性语义 | 实测 ccxt.pro 已并入主仓库 `ts/src/pro` |
| **python-binance** | 我们不做 Binance 实盘（仅作数据源）；社区库最后发布 2026-06-08（5 个月前），open issue 534 | 实测 v1.0.37 |
| **Freqtrade** | GPL-3.0；candle 级交易循环（最小 1m），FreqAI 的 ML 流程与 A-S 定价 + 队列优先权不同层 | 实测 ★56874 / 2026.10 / GPL-3.0 |
| **Robinhood 加密** | 无官方加密交易 API 仓库，仅社区 demo（★25）与逆向库；且与 HIP-3/RWA 无关 | 实测检索结果；API 现状未核实 |
| **Lighter 社区 SDK** | `robustfengbin/lighter-sdk` ★13 无许可证；`defi-maker/pylighter` ★39 无许可证。**改用 nautilus 的 lighter adapter 作协议参考** | 实测 |
| **任何 lmdb 行情存储方案** | 检索未找到「星标 ≥100 且近 2 年活跃」的 lmdb 行情库；且 Parquet + 预编译 `.npy` 已足够（03 稿 §3.3） | 实测检索无合格候选 |
| **Hugging Face crypto L2 数据集** | 下载量 30–467，采集方式不透明，序列连续性无法核实 | 实测各 dataset 下载量 |
| **Nasdaq Data Link / dxFeed** | 前者无 crypto L2，后者 ★47 + 15 个月未更新 + MPL-2.0 + 商业授权另计 | 实测 |
| **`dominolu/titan`、`mirkovicdev/HFTENGINE`、`mileswangs/pm-hftbacktest`** | ★10 / ★340(仅控制台外壳) / ★131(Polymarket 方向)，成熟度不足或方向不符 | 实测 |
| **DeepMarket** | 是**合成数据生成器**（扩散模型），与项目红线「严禁合成数据」冲突 | 实测仓库描述与论文定位 |
| **`nanogpt`/`quantconnect/LEAN` 等大框架** | 1 核 1G 上不可部署；且 LEAN 的数据源适配（`hmate9/Lean.DataSource.CryptoHFTData` ★0）只是接入示例，价值在**契约设计参考**而非代码 | 实测 ★0 / Apache-2.0 |

---

## 9. 必须自研的边界（现成方案 vs 自研）

### 9.1 判定原则

> **凡是与「A-S 定价状态机的逐笔一致性」强相关的代码，一律自研；凡是与「数据 I/O、协议适配、统计口径」相关的代码，尽量复用。**

理由（来自共享上下文实测）：现有 `live_cluster/as_nautilus_strategy.py` 已经跑在实盘上（10.38h，maker 比例 99.5%）。回测若用外部引擎，就必须**重写一遍定价层**，两份代码必然漂移，「回测 ≠ 实盘」的问题会原样重现。

### 9.2 边界表

| 层 | 归属 | 具体内容 | 依据 |
|---|---|---|---|
| **订单簿状态机** | 🟢 **自研**（必须） | 增量应用、档位聚合、序列连续性硬断言、快照重建 | 无现成库（§3.2 实测）；03 稿 §4 |
| **撮合与排队判定** | 🟢 **自研**（必须）+ 🟡 **公式借鉴** | 方案 A/B/C 的实现自研；方案 B 的概率公式借鉴 hftbacktest（MIT） | 03 稿 §5 |
| **A-S 定价 / 保留价 / 最优半价差 / 库存偏置 / ADX 状态机 / 冷却** | 🟢 **自研**（已有，勿动） | `live_cluster/as_nautilus_strategy.py` | 已在实盘验证 |
| **手续费门槛** | 🟢 **自研** + 🟡 **语义借鉴** | 动态门槛算法自研；「订单级费率 + 币种换算」语义借鉴 Hummingbot `trade_fee` | 实测教训：手续费曾占总亏损 72.6% |
| **订单延迟模型** | 🟢 **自研实现** + 🟡 **工具借鉴** | 参数化模型自研；用 hftbacktest 的 `generate_order_latency` 做标定 | 03 稿 §7 |
| **数据下载** | 🔵 **复用 SDK** | `cryptohftdata` PyPI SDK 0.8.1（MIT） | §6.1 |
| **数据格式转换（cryptohftdata → 引擎事件）** | 🔵 **复用/移植** | 移植 PR #307 的 423 行转换器（MIT），或按它校核我们的规范化管道 | §2.1 |
| **L2 订单簿恢复与增量同步（HIP-3）** | 🟡 **借鉴范式 + 自研实现** | 读 nautilus `book/recovery.rs` / `sync.rs` 与官方 SDK 的 `perp_dex_to_offset`，重写进我们的 `okx_ws_manager.py` | §5.1 |
| **交易所 REST/WS 接入（OKX）** | 🟢 **自研**（已有） | `gateway_okx_client.py` / `okx_ws_manager.py`；无官方 Python SDK 可用（§5.1 实测 404） | 已有实现 |
| **交易所 REST/WS 接入（Hyperliquid）** | 🟡 **借用官方 MIT SDK** | `hyperliquid-python-sdk`（MIT），直接复制代码需保留 MIT 声明 | §5.1 |
| **ML 训练** | 🟢 **自研**（已有）+ 🔵 **复用库** | 训练逻辑自研（Kaggle `trainer.py`）；LightGBM 库复用 | 已有实现 |
| **ML 推理部署** | 🔵 **复用库** | LightGBM 原生或 C API（P1）；ONNX（P2，可选） | §4.1 |
| **特征存储** | 🟢 **自研**（极简） | Parquet 特征快照 + `feature_contract.json` 版本契约 | §4.4 |
| **特征计算（OFI/OBI/VPIN/Kyle λ）** | 🟢 **自研**（公式公开、参考实现 MIT） | 借鉴 `hanxixuana/flowrisk`（MIT）、`alpacahq/example-hftish`（思路）、`orderbook-l2-ofi`（MIT） | §3.1 |
| **监控与看门狗** | 🟢 **自研**（已有） | `cron_accountbot3_ml_guard.py` | 已有实现 |
| **风控（回撤熔断 / 保证金占用）** | 🟢 **自研**（已有） | `src/as_risk_guard.py` | 已有实现 |
| **L2 数据长期归档** | 🟡 **借鉴 + 自研** | 借鉴 nautilus Parquet catalog 的 session/coverage/consolidation；自研适配我们的 schema | §2.2 |
| **参数寻优** | 🟢 **自研**（已有） | `src/alpha_gpt_evolution_engine.py`（已改用真实 BTC 数据） | 已有实现 |

### 9.3 明确「不自己写」清单（省钱清单）

- 不自己写交易所签名/HMAC/RSA 逻辑 → 用官方 SDK（Hyperliquid MIT）或沿用现有客户端（OKX）。
- 不自己写 Parquet 压缩/行组/页大小调优 → 用 pyarrow + 本文 §6.3 的参数。
- 不自己写概率队列模型的**公式推导** → 抄 hftbacktest（MIT）。
- 不自己写 HIP-3 的 perp dex 寻址表 → 从 Hyperliquid 官方 SDK 抄（MIT）。
- 不自己写费率换算语义 → 抄 Hummingbot `trade_fee` / `estimate_fee`（Apache-2.0，需保留声明）。
- 不自己写订单簿重建的**通用框架** → 但没有可用的通用库，仍须自研（§3.2 实测）。

---

## 10. 落地顺序（与 03 稿并行，不冲突）

| 周次 | 动作 | 依赖 | 交付 |
|---|---|---|---|
| W1 | 建隔离 venv；clone `hmate9/hftbacktest@cryptohftdata`；跑通 `download_and_convert` 对 OKX 永续 1 天 | 开发机（12 核 14 GB） | 1 天 OKX L2 的 npz 事件数组 + 转换器跑通报告 |
| W1 | 移植 `cryptohftdata.py` + `test_cryptohftdata.py` 到我们仓库 `tools/hftb_cryptohftdata/`（保留 MIT 头） | W1 | 我们的仓库里有一份可跑的转换器 |
| W2 | 我们的 Numba 引擎 vs hftbacktest，同数据同参数 → 差异表 | W1 + 03 稿 P1 | `reports/hftbacktest_calibration_*.md` |
| W2 | 用 `generate_order_latency` 做延迟网格扫描（`offset_entry × offset_resp`） | W1 | 延迟标定表，写进 03 稿 §7 |
| W3 | 抄概率队列模型公式 → Numba 实现 + 单测 | W2 | `src/queue_models.py` |
| W3 | 读 nautilus hyperliquid adapter + Hyperliquid SDK `perp_dex` → 写 HIP-3 接入规格 | — | `docs/design/06-hyperliquid-hip3.md` |
| W4 | Hummingbot 费率语义 → 动态手续费门槛 | — | 改造 `as_nautilus_strategy.py` 的门槛计算 |
| W4 | LightGBM C API 推理路径 P1 | — | 推理延迟对比（改造前/后） |

> **红线提醒（沿用共享上下文）**：W1–W4 的所有产出必须走**真实数据 + 真实撮合**。不得用合成白噪声拟合任何指标（`src/alpha_gpt_evolution_engine.py` 的历史教训）。校准报告里若出现「差异率 < 0.1%」这类断言，必须附逐笔明细，不得只给汇总数字。

---

## 11. 未核实清单（明确标注，供后续补查）

| 项 | 状态 |
|---|---|
| OKX 官方 Python SDK 仓库是否存在于上游 GitHub（`okx/okx-py`、`okx/okx-api-v5`） | **未核实**（本次访问均 404，可能仅是本镜像未收录）。但我们的方案不依赖它，故不影响结论 |
| nautilus_trader 是否有「企业版/核心闭源」的商业条款 | **未核实**（仓库 README 只指向 LGPL-3.0 + 官网 disclaimer）。**建议**：落地前读 `nautilustrader.io/legal/` |
| cryptohftdata SDK 的重试/限流/免费 tier 具体速率 | **未核实**（未读 SDK 源码，只读了 PyPI 元数据） |
| cryptohftdata 免费 tier 的 L2 历史覆盖边界（多早、多深、哪些交易所） | **未核实**（共享上下文已实测 14 个交易所的 `/v1/status`，但未逐个测下载配额） |
| `cryptohftdata` 数据在 OKX 上的 `pu`/序列连续性表现 | **未核实**（PR #307 评论区只有 Binance USD-M 的自测数据；**OKX 需我们自测**）—— 这是 W1 的第一个验收项 |
| `mansoor-mamnoon/limit-order-book`（★93，C++ LOB 引擎）的实现质量与许可（无 LICENSE 文件） | **未核实**（仅记录，未读源码） |
| `cameronscarpati/lob-regime-scanner`（★19）的 30+ 特征是否严格因果 | **未核实**（仅读描述，未读特征实现） |
| `czakhaa/DeepLOB`、`Jeonghwan-Cheon/lob-deep-learning` 的实际训练耗时与推理延迟 | **未核实**（无许可/无环境，理由已足以放弃，无需深查） |
| hftbacktest v2 后续开发是否在未推送的分支上 | **未核实**（仅能确认 master 停在 2025-12-23、2026 下半年 PR 全部未合并） |
| `Kanesh` 特征存储 | **未核实**（本次检索未找到任何以此命名且合格的项目） |
| Nasdaq Data Link / dxFeed 的 crypto 覆盖 | **未核实**（按定位判断为无覆盖，理由充分） |
| LightGBM → ONNX 转换在**我们这三个具体模型**上的数值一致性 | **未核实**（需实际导出对比，属 W4 之后） |
| `hftbacktest` 2.4.4 与我们现有 numba 环境的依赖冲突程度 | **未核实**（已知约束：`hftbacktest` 要求 `numba~=0.61` + `numpy>=2.0,<2.3`，我们需隔离 venv） |

---

## 12. 附录：本次核实用到的可复现命令

```bash
# 仓库元信息（含最后推送、最新 release、许可证）
gh api repos/<owner>/<repo> --jq '{stars:.stargazers_count,lic:(.license.spdx_id),pushed:.pushed_at}'

# 最近提交
gh api "repos/<owner>/<repo>/commits?per_page=3" --jq '.[]|"\(.commit.author.date) \(.commit.message)"'

# 最近 PR（含是否已合并）
gh api "repos/<owner>/<repo>/pulls?state=all&per_page=10&sort=updated&direction=desc" \
  --jq '.[]|"#\(.number) \(.state) merged=\(.merged) \(.updated_at) \(.title)"'

# 单个 PR 的文件与 diff 体量
gh api repos/<owner>/<repo>/pulls/307/files --jq '.[]|"\(.filename) +\(.additions)/-\(.deletions)"'

# 从 fork 的非默认分支取文件（本次用于取 cryptohftdata 转换器）
gh api "repos/hmate9/hftbacktest/contents/py-hftbacktest/hftbacktest/data/utils/cryptohftdata.py?ref=cryptohftdata" \
  --jq '.content' | base64 -d

# PyPI 元信息
curl -s https://pypi.org/pypi/<pkg>/json | jq '.info|{version,license,requires_python}'
```

> **所有"实测"结论均可用上述命令在 2026-11-14 复现。** 仓库活跃度会变，复核时请以复核当日为准；本稿中带日期的数据点即为该日的快照。
