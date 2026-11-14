# 03 · L2 队列感知高保真回测引擎设计

> 切片：如何在本地用真实 L2 增量数据，构造一个**不会系统性高估做市收益**的回测引擎。
> 依赖已有实现：`src/run_2year_asgrid_backtest.py`（1m OHLCV 撮合）、`live_cluster/as_nautilus_strategy.py`（定价状态机）、`live_cluster/run_live.py`（实盘事件循环）。
> 本稿只写**增量设计**，不复述共享上下文里的实现细节。

---

## 0. TL;DR 决策

| # | 决策 | 结论 |
|---|---|---|
| 1 | 数据源 | 用 `api.cryptohftdata.com` 的 **OKX 永续 L2 增量事件流**（已实测可下载、可解析、有序列号）。不用 Binance depth20 快照做队列建模（深度截断，无法判定档位清空） |
| 2 | 撮合语义 | 事件驱动、按 `exchange_ts` 严格序回放；**maker 成交必须过队列前置量判定**；穿盘一律走 taker 路径并计 0.05% |
| 3 | 队列建模 | 三方案并存输出**区间**：A（保守，下界）/ B（概率，标定后主用）/ C（零排队，上界）。差值 `C − A` 就是本引擎的乐观偏差量化 |
| 4 | 引擎选型 | **自研 Numba 事件引擎为主**（复用现有 A-S 定价状态机、1 核可跑），**hftbacktest 不引入**（Cython 编译链 + 数据适配成本 > 收益），NautilusTrader 仅作为撮合语义对照与实盘对接验证 |
| 5 | 长度分层 | 2 年 1m bar 回测保留但**降级为"参数化折价模型"**；真正的队列感知回测窗口 = **30 天 L2 全量**（1 核约 1–2 小时）。2 年 L2 全量在 1 核 1G 上**不可行**，明确不做 |
| 6 | 结果口径 | 全部指标出**区间 + block bootstrap 95% CI**，禁止点估计；实盘对账作为标定锚点 |
| 7 | 红线 | 撤单不是免费、忽略资金费率、bar 内成交顺序、跳空、无滑点 —— 这 5 项是旧引擎高估收益的主因，必须在引擎层被"结构性禁止"而非靠自觉 |

---

## 1. 目标、范围与非目标

### 1.1 目标（可验收）

回测引擎必须能在下列条件下**复现实盘的量级特征**，而不是复现收益：

| 验收项 | 目标 | 依据 |
|---|---|---|
| Maker 成交率 | 与实盘 10.38h 记录的成交率同量级（定义见 §11.2） | 实测 |
| 手续费占比 | 回测手续费 / 毛利 与实盘 0.3269 USDT / 净损益 同量级 | 实测 |
| Taker 混入率 | 回测 < 1%（Post-Only 强制下） | 实测（实盘 99.5% maker） |
| 乐观偏差 | 报告 `方案C收益 − 方案A收益`，目标：把旧引擎的 +68.19% 拉回到与实盘同量级或以下 | 推断 |
| 确定性 | 同数据同参数 → 逐笔完全一致（bit-level） | 建议 |

### 1.2 范围

- 单交易所（OKX）、单品种（BTC-USDT-SWAP）起步，随后扩展到 RWA / HIP-3 标的。
- 撮合语义、延迟模型、成本模型、离散粒度、验证方法。
- 数据契约与性能预算。

### 1.3 非目标

- 不做多交易所撮合、不做跨所套利回测（数据与撮合语义完全不同源）。
- 不做订单簿预测 / ML 撮合（在引擎层引入预测会立刻引入"模型误差 × 撮合放大"，与本切片目标冲突）。
- 不追求 GPU / 多核；所有性能路径以 1 核为基线。

---

## 2. 数据事实（全部实测，2026-11-14 探测）

### 2.1 cryptohftdata 的 OKX L2 增量流（核心数据源）

路径规律（实测）：`{exchange}/{YYYY-MM-DD}/{HH}/{SYMBOL}_{datatype}.parquet`，`GET /v1/download?file=...` 返回 302 → 签名 URL（`curl -L` 跟随即可，无需 JWT）。

实测样本：`okx_futures/2026-11-14/11/BTC-USDT-SWAP_orderbook.parquet`

| 指标 | 实测值 |
|---|---|
| 文件大小 | 7.35 MB / 1 小时 |
| 行数 | 1,769,200 |
| 事件数（按 `final_update_id` 分组） | 35,460 → **9.85 次/秒**（OKX 100ms 推送节奏） |
| 每次事件变更档位数 | 中位 26，p95 约 1225 |
| snapshot 事件 | 800 行 = 400 买档 + 400 卖档 |
| 档位价格档数 | 1 小时 3,586 个不同价格 |
| 删除语义 | `quantity == 0` 表示该档被清空（占 update 行 17.8%） |
| `order_count` | 每档聚合单数：中位 40（买一），p5 14，p95 92；最大 180 |

实测样本：`okx_futures/2026-11-14/11/BTC-USDT-SWAP_trades.parquet`

| 指标 | 实测值 |
|---|---|
| 行数 | 67,945 / 小时（≈ 18.9 笔/秒） |
| 单笔数量 | 中位 0.26，最小 0.01，p99 44.2 |
| 字段 | `trade_id, price, quantity, trade_time, is_buyer_maker, order_type` |
| `is_buyer_maker` | 主动买/卖方向判定的唯一可靠来源 |

### 2.2 订单簿微观结构实测（1 小时重建结果）

用上表数据重建全档订单簿后的实测统计：

| 指标 | 实测值 |
|---|---|
| 最优一档价差 | **1 tick（0.1 USD）占 99.88%** 的事件；最大 20 tick |
| 买一档挂单量 | 中位 380，p5 72.5，p95 1280（单位见 §2.3） |
| 买一档订单数 `order_count` | 中位 40，p5 14，p95 92 |
| 最优买价档位"生命周期" | 中位 **17 个事件 ≈ 1.73 秒**（p90 95 事件 ≈ 9.7 秒） |
| 最优买价变动次数 | 944 次/小时 ≈ **每 3.8 秒一次** |
| 买方向主动成交量 | 83,158（单位同 2.3）/小时 |
| 队列周转比 | 83,158 ÷ 380 ≈ **219 次/小时**，即买一档平均约 16 秒被清空一次 |

**这三个数字是整个设计的锚点**：

1. 最优档 1.7 秒就被换掉 → 「挂到 BBO 等 30 秒」的真实成交概率极低，TTL 必须与秒级对齐。
2. 买一档平均每单约 9.5 单位量（380 ÷ 40），而我方单笔是 0.01 张（≈ 1/950 档位量）→ **我方永远在档位队尾**，方案 A 的"前方量"在数值上≈ 整档量。
3. 队列周转 219 次/小时 → 这就是"档位被打空"的真实发生率，也就是**队列感知成交率的天花板**。

### 2.3 单位口径（高危陷阱）

cryptohftdata 的 `quantity` 在 `orderbook` 与 `trades` 两个数据族中**口径不同**，必须显式换算：

- 用 ±0.2% 价带（400 档/侧）的深度名义额反推：
  - 若把 `orderbook.quantity` 当 **BTC** → 买侧 $874M / 卖侧 $1,139M（量级失真 100 倍，不可能）
  - 若当 **张（contract，OKX BTC-USDT-SWAP ctVal = 0.01 BTC）** → 买侧 **$8.74M** / 卖侧 **$11.39M**（量级合理）
- 同口径一致性检查：`order_count` 中位 40 对应档位量中位 380 → 每单均值 9.5 张 = 0.095 BTC ≈ $6.4k，符合真实 BBO 挂单分布；若当 BTC 则为 9.5 BTC/单，不成立。

> 【需本机实测验证】以上推导依赖"±0.2% 价带 400 档"这一深度规模假设。落地时必须做**守恒校验**（§4.4）来最终锁定单位，而不是沿用本文推导。
> 【行业标准做法】交易所深度接口的 `sz` 语义：现货为基础币、合约/永续为张数，必须按 instrument 元数据 `ctVal`/`lotSz`/`minSz` 换算。

### 2.4 本地已有数据资产（实测）

| 路径 | 内容 | 用途 |
|---|---|---|
| `03_governed_lake/.../high_frequency_lob/BTCUSDT/BTCUSDT_1m_3years_governed.parquet` | 104 万根 1m bar，2 年 | 长窗口降级回测（Tier-2） |
| `03_governed_lake/.../BTCUSDT_depth20_20260326_governed.parquet` | Binance depth20 快照 32.2 万行（1 天） | **不可用于队列建模**（深度截断），只可做深度统计 |
| `03_governed_lake/.../BTCUSDT_trades_20260418_governed.parquet` | 194 万笔成交（1 天，含 `is_buyer_maker`） | 成交方向校验 |
| `03_governed_lake/.../crypto/funding_rate/{DOGE,SOL,SUI}USDT/` | 资金费率 | 资金费模型标定 |
| `catalog/data/order_book_delta/` | SOL/SUI/DOGE 聚合档位派生表 | 跨标的扩容预备 |

### 2.5 归档延迟 vs 实盘延迟（两个不同的量，不要混用）

| 延迟段 | 实测值 | 来源 |
|---|---|---|
| 归档 `received_time − event_time` | 中位 **133 ms**，p1 124 ms，p99 139 ms | 本机实测（厂商采集链路） |
| 实盘 VPS → OKX 撮合 RTT | **45–75 ms** | 共享上下文（实测） |
| 实盘事件循环抖动 | 10–50 ms | 共享上下文（实测） |

> 归档的 133 ms 是**厂商的**采集+落盘延迟，不是我们 VPS 的 RTT。回测里 **不得** 直接用 133 ms 当延迟参数；延迟参数必须按 §7 的三段式独立设定（feed latency 用归档值做"信息陈旧度"下界，order latency 用实测 RTT）。

---

## 3. 引擎输入数据契约（Parquet 事件流 Schema）

### 3.1 规范 schema（引擎只认这一套）

一个统一的 Parquet 文件 = 一个 symbol 一个交易日的**有序事件流**，行按 `(exchange_ts, seq)` 排序：

| 字段 | 类型 | 说明 |
|---|---|---|
| `event_type` | `string` | `snapshot` / `book_update` / `trade` / `mark_price` / `funding` |
| `exchange_ts` | `int64` | 交易所时间戳，**纳秒**（统一到 ns，消除 ms 精度歧义） |
| `local_ts` | `int64` | 到达采集端的时间戳，ns（来自 `received_time`） |
| `symbol` | `string` | 统一为 `BTC-USDT-SWAP` |
| `side` | `string` | `bid` / `ask` / `buy` / `sell`（book 用 bid/ask，trade 用主动方向） |
| `price` | `float64` | 已按 `tick_size` 对齐（存储用 `int64` tick 更好，见下） |
| `size` | `float64` | **统一为 base 币数量**（张 → BTC 换算后） |
| `quantity_raw` | `string` | 原始串，保留审计 |
| `n_orders` | `int32` | 该档聚合单数（来自 `order_count`），无则 -1 |
| `seq_id` | `int64` | 交易所序列号（`final_update_id`） |
| `prev_seq_id` | `int64` | 前一序列号，用于断层检测 |
| `order_id` | `int64` | 成交/订单 ID（trades 用 `trade_id`；自成交回报用我方 orderId），无则 -1 |
| `is_buyer_maker` | `bool` | 仅 trade 有效 |
| `src` | `string` | 来源族：`okx_futures.orderbook` / `okx_futures.trades` |

**存储建议**：`price` 额外落一列 `price_tick: int64 = round(price / tick_size)`，撮合层全部用整数 tick 比较，避免浮点相等判断。

### 3.2 从 cryptohftdata 到规范 schema 的映射（实测列名）

| 规范字段 | cryptohftdata orderbook | cryptohftdata trades |
|---|---|---|
| `exchange_ts` | `event_time` (ms → ×1e6) | `trade_time` (ms) / `event_time` |
| `local_ts` | `received_time` (ns) | `received_time` (ns) |
| `seq_id` | `final_update_id` | `trade_id` |
| `prev_seq_id` | `prev_final_update_id` | — |
| `side` | `side` (`bid`/`ask`) | 由 `is_buyer_maker` 推导 |
| `price` | `price` (str) | `price` (str) |
| `size` | `quantity` (str) | `quantity` (str) |
| `n_orders` | `order_count` | — |
| `order_id` | — | `trade_id` |
| `is_buyer_maker` | — | `is_buyer_maker` |

### 3.3 归一化管道（一次性、可缓存）

```
raw/*.parquet (厂商原始)
  → scripts/normalize_l2.py      # 单位换算 + 时间统一 + 排序 + 序列校验
  → lake/l2_events/{symbol}/{date}/events.parquet   # 规范 schema
  → lake/l2_events/{symbol}/{date}/events.npy       # 预编译列式缓存（引擎直读）
```

**预编译 `.npy` 缓存是关键性能决策**（§10.5）：Parquet 的列式解码 + 字符串解析在 1 核上会成为主导开销；预编译成定长 typed array 后，撮合循环可以零拷贝。

缓存文件布局（`np.savez` 或裸 `.npy`）：

```
exchange_ts   int64[N]
local_ts      int64[N]
seq_id        int64[N]
prev_seq_id   int64[N]
price_tick    int32[N]
size          float64[N]
n_orders      int32[N]
side          int8[N]      # 0=bid 1=ask 2=trade_buy 3=trade_sell
event_type    int8[N]      # 0=snapshot 1=book_update 2=trade
```

**每日体量实测**：OKX BTC-USDT-SWAP ≈ 42.5 M 行/天（1.77 M × 24），Parquet 约 176 MB/天，`.npy` 缓存约 40 字节/行 → **1.7 GB/天**。

> 1 核 1G VPS 的硬约束：单日缓存 1.7 GB **放不进内存**。落地方式见 §10.5 的"按小时分块 + 流式回放"，单块 7.3 MB → 内存占用 < 100 MB。

---

## 4. 订单簿状态机

### 4.1 档位聚合队列 vs 限价单队列（路线取舍）

| 方案 | 数据要求 | 能判定什么 | 现实可得性 |
|---|---|---|---|
| **限价单队列（L3）** | 每笔挂单的 `order_id + price + size + ts` | 精确 FIFO：我方单在队列中的确切名次、撤单者身份 | 【需本机实测验证】公开免费源基本不给；OKX 只有私有频道 |
| **档位聚合队列（L2）** | 每档 `price + qty + n_orders` | 档位总量与档内单数；**档内 FIFO 名次不可知** | ✅ cryptohftdata 已实测具备 |

**结论：走 L2 档位聚合路线**，并把"档内 FIFO 名次不可知"作为**显式建模不确定性**处理，而不是假装知道。

档位聚合路线下的关键推论（实测支撑）：
- 我方单量 0.01 张 vs 买一档中位 380 张 → 我方处于档内队尾。
- 于是**档内 FIFO 顺序在绝大多数情形下不影响成交判定**：只有当整档被打空时，队尾的我方单才会成交。这把"档内 FIFO 不可知"从一个致命不确定性降级为**边界情形的不确定性**。

### 4.2 内存数据结构（Numba 友好）

不用 `dict`，用**稠密数组 + 空闲链表 + 惰性删除**：

```python
# 常量（按 symbol 配置）
MAX_LEVELS      = 4096      # 每侧活跃档位上限（实测 1h 内 3586 个价位 → 4096 足够，超出按需扩容）
PRICE_TICK_MIN  = -2_000_000
PRICE_TICK_MAX  =  2_000_000

# PriceLevel 结构（结构化数组，Numba 可用）
# idx:  int32    # 内部槽位索引
# tick: int32    # 价格（tick 数）
# size: float64  # 该档总挂单量（base 币）
# n_orders: int32 # 档内订单数
# alive: uint8   # 1=有效

class BookSide:
    tick      : int32[MAX_LEVELS]      # 槽位 → tick（无序）
    size      : float64[MAX_LEVELS]
    n_orders  : int32[MAX_LEVELS]
    alive     : uint8[MAX_LEVELS]
    free_head : int32                  # 空闲链表头
    # 有序视图：维护 best-K（K=64）有序数组
    best_tick : int32[64]
    best_idx  : int32[64]
    best_n    : int32
```

**为什么不用有序字典**：撮合热路径需要"取最优档"，每事件都做一次 `sorted()` 会让 42 M 事件/天退化成 O(n log n)。方案：**只维护 best-K 有序视图**（K=64，实测一档变动频繁但 64 档足够覆盖决策所需），K 之外用无序槽位表 + 惰性删除；K 视图在删除/插入时增量修复。

**哈希加速**：价格 tick → 槽位的查找用**开放寻址哈希表**（`int32[8192]` + 线性探测），避免线性扫描 4096 槽位。

### 4.3 事件应用（伪代码）

```python
def apply_book_event(side, tick, size, n_orders, seq_id, prev_seq_id):
    # 1) 序列号断层检测：OKX 要求 final_update_id 连续，prev_final_update_id 衔接
    if event_type == SNAPSHOT:
        clear_side(side)
        for row in snapshot_rows:
            insert_or_update(side, row.tick, row.size, row.n_orders)
    else:  # BOOK_UPDATE
        if seq_id != last_seq_id + 1:
            raise SequenceGap(seq_id, last_seq_id)   # 必须中断回测，不得静默继续
        if prev_seq_id != last_seq_id:
            raise SequenceGap(...)
        if size == 0:
            remove_level(side, tick)      # 档位被清空
        else:
            insert_or_update(side, tick, size, n_orders)
    last_seq_id = seq_id
```

`remove_level` 触发两个下游事件，**这是队列模型的核心输入**：
1. 该档 `size` 归零 → 记一次 **LEVEL_CLEARED(tick, ts)**（我方若在此档排队，此刻按 FIFO 判定成交）。
2. 该档从 best-K 视图移除 → 下一档上浮。

### 4.4 序列一致性与守恒校验（回测自带的硬断言）

每处理完一个交易日的 L2 流，必须跑三条断言，任一失败则该日数据作废：

| 断言 | 定义 | 阈值（建议） |
|---|---|---|
| A1 序列连续 | `final_update_id` 严格 +1；`prev_final_update_id` 与前一条一致 | 0 违例 |
| A2 盘口不交叉 | 任意时刻 `best_ask_tick > best_bid_tick` | 0 违例 |
| A3 量级守恒 | 档位 `size` 变化量 vs 同价位成交量的量级一致（用于最终锁定 §2.3 的单位口径） | 残差 < 20% |

A3 具体做法：对每个价位，累加该价位 1 小时内的 `|Δsize|` 与该价位成交总量；两者比值应落在订单撤单/重挂可解释范围内（经验 1–10 倍）。若比值 ≈ 100 或 ≈ 0.01，说明单位口径选错。

---

## 5. 排队位置建模：A / B / C 三方案

### 5.1 共同记号

- 我方在 `tick = p`、方向 `d ∈ {buy, sell}` 挂出 `size = s`（0.01 张）。
- 挂出时刻 `t_join`，该档当时的聚合量 `Q0`、档内单数 `N0`。
- 档位在 `t_join` 之后被持续更新，直到被打空或我方撤单。

### 5.2 判定量：`queue_ahead(d, p, t)`

```python
queue_ahead = 该档自 t_join 起的累计减少量（成交消耗 + 撤单移除都算“前方让位”）
            = Q0 - size_now(p)
```
> 关键建模判断：**撤单也算前方让位**。别人撤掉挂在排我前面的单，我方位置确实前移。若把撤单排除在外（更保守），则 `queue_ahead` 永远不下降 → 永不成交 → 过度保守。本文默认**计入撤单**，并在方案 A 里给出"仅计入成交"的更严版本作为压力情景。

### 5.3 三方案定义

#### 方案 C：完全不建模（现做法，对照组）

- 规则：只要 `best_bid ≤ my_bid`（买单）即**全额成交**。
- 等价于假设我方排在队首，且盘口一被触碰就成交。
- **影响方向：强烈高估收益。** 因为它把"价格被触碰"等同于"轮到我"，忽略了我方在队尾、且档位量是我方 950 倍的事实。

#### 方案 A：保守估计（整档清空才轮到我）

- 规则：仅当该档 `size` 被清空（`LEVEL_CLEARED`）时，我方才按 FIFO 队尾规则成交。
- 实现：维护 `pending_by_level[tick] = (my_size_remaining, join_ts)`；`remove_level` 时按队尾顺序结算。
- **影响方向：低估收益**（真实存在"部分排队成交"这一中间态），是**下界**。
- 极端保守版 A′：连撤单让位都不计入，只认成交消耗 → 几乎永不成交，作为"队列模型极端敏感性"的参照。

#### 方案 B：概率模型（推荐主用）

- 规则：在档位被打空之前，允许按概率 `p_fill(Δt | Q_ahead, n_ahead, 强度)` 成交部分量。
- **概率构造**（不需要逐笔订单，只需档位级统计）：
  - 用 `trades` 事件流估计该价位的**成交到达强度** `λ`（单位：base 币/秒）：
    ```
    λ(p) = Σ_{trades at p} size / 窗口时长          # EMA 平滑，窗口 60s
    ```
  - 前方剩余量 `Q_ahead(t)`，我方剩余 `s_rem`：
    ```
    # 把前方量按"到达强度 λ 的确定性耗尽"作为期望，
    # 到达时间 τ_exp = Q_ahead / λ
    # 在 τ 内被完全清空的概率用泊松近似：
    P(τ < Δt) = 1 - exp(-λ·Δt)   # 近似：前方量以强度 λ 被消耗
    ```
  - 实操可更简单：使用**档位被打空的实测经验频率**：
    ```
    p_clear(p) = 该价位 1 小时内的 LEVEL_CLEARED 次数 / 该价位在场时长
    ```
    （直接从回放中在线统计，不需要预设模型 —— 这是本方案最稳的实现。）
- **部分成交**：档位每次 `size` 减少时，按"我方在剩余队列中的份额"抽签：
  ```
  my_share = s_rem / max(Q_ahead + s_rem, eps)
  fill_this_step = min(s_rem, Δsize) * my_share * β
  ```
  `β` 为校准系数（默认 1.0，靠实盘成交率标定）。
- **影响方向：接近真实**，需要标定；标定锚点见 §11.2。

### 5.4 三方案对比表

| 维度 | 方案 C（现状） | 方案 A（保守） | 方案 B（概率，推荐） |
|---|---|---|---|
| 成交率估计 | 极高（接近 100% 触碰即成） | 极低（≈ 买一档被打空频率，实测 ≈ 219 次/小时的最优档速率，且要求我方恰在档上） | 居中，由实测频率与强度导出 |
| 收益方向 | **高估** | **低估**（下界） | 居中（需标定） |
| 队列损耗量级 | 无 | 全额 | 可调 0–1（`β`） |
| 需要的额外数据 | 无 | 档位量 + 清空事件 | 档位量 + 清空事件 + 成交强度（`trades`） |
| 计算开销 | 极低 | 低 | 中（多一张 `λ` 表） |
| 抗操纵性 | 差 | 好 | 中（依赖标定数据质量） |
| 在本项目中的定位 | **仅作上界对照**，不得用于任何决策 | **下界**，用于回答"最坏情况下还赚不赚" | **主用**，报区间 `[A, B]` 并附 `C` 为上界 |

### 5.5 期望影响的量级（先验估算，待回测校准）

用 §2.2 的实测结构做量级推演：

- 旧引擎（方案 C）假设"每根 1m bar 内价格触及即全额成交"。实测 BBO 每 3.8 秒变动一次、买一档生命周期中位 1.73 秒 → **一根 1m bar 内盘口状态切换约 15 次**，旧引擎却只记 1 次成交。
- 反向的旧引擎失真：它在 1m bar 内**用 low/high 判定**，即用整分钟的最优价去判定 1 分钟前的报价是否成交。
- 净效应方向：**旧引擎高估**。理由是旧引擎的成交触发条件（bar 内 low/high 触及）比真实条件宽松，同时真实 FIFO 队列还会额外扣掉"档位打空"的比例。
- 初步量级假设：**成交率下降 50%–80%，净收益下降 60%–95%**（推断，必须由 §10 的实测替换）。

> 这条"乐观偏差"就是任务书要求的量化对象：`偏差 = 收益(方案C) − 收益(方案A)`，最终以百分比与 USDT 双口径报告。

### 5.6 推荐的输出形式

**不输出点估计。** 每份回测报告至少给三行：

```
净收益（区间）:
  方案 A 下界   : -0.9%   (95% CI [-2.1%, +0.4%])
  方案 B 主用   : +1.7%   (95% CI [-0.6%, +4.1%])
  方案 C 上界   : +12.4%  (无 CI，仅作偏差量化)
  乐观偏差 C-B  : 10.7 个百分点
```

---

## 6. 成交语义

### 6.1 Maker 成交价

- 被动限价单成交价 = **挂单价**（价格优先原则下，交易所按挂单价成交）。
- 我方从不主动跨价。策略报价必须满足 `my_bid < best_bid` 或 `my_ask > best_ask` 才挂出（否则 Post-Only 被拒）。
- **实测注意**：OKX 最优价差 99.88% 是 1 tick；我方若挂在次一档（-2 tick），成交概率与队列长度都会显著变差，价差收益翻倍 —— 这是**必须做的参数扫描维度**（挂单档位深度 ∈ {0, 1, 2} tick）。

### 6.2 穿盘 / Taker 路径

穿盘来源有二：(a) 挂单时价格已穿越（Post-Only 被拒）；(b) 延迟期内盘口移动，订单到达时已成 Taker。

```python
def submit_with_post_only(my_tick, side, book, ts):
    if side == BUY and my_tick >= book.best_ask_tick:
        reject("POST_ONLY")                      # 不发单
    if side == SELL and my_tick <= book.best_bid_tick:
        reject("POST_ONLY")
    # 发送（真实链路上还可能在到达时再次穿盘，见 §7）
    return order_id
```

**到达时穿盘的处理**（延迟导致）：

```python
def on_order_accepted(order):
    if order.side == BUY and order.price_tick >= book.best_ask_tick:
        # 已成 Taker：按对手价成交，可能穿多档
        fills = sweep(book.asks, order.size, book.best_ask_tick)
        avg_px = weighted_avg(fills)
        fee_rate = TAKER_FEE          # 0.0005
        slippage_bps = (avg_px - decision_mid) / decision_mid * 1e4
        record_taker_fill(avg_px, fee_rate, slippage_bps)
```

**滑点必须显式计入**（旧引擎完全忽略）：滑点记在 `slippage_bps` 字段，与手续费分开统计，敏感度分析里独立扫描。

### 6.3 部分成交

- 我方单量 0.01 张（≈ 8.08 USDT 名义，实测，见共享上下文），而档位量中位 380 张 → 我方单永远**小于**任何有意义的档位，正常路径下应一次全成。
- 部分成交主要出现在：**大单被拆**（本项目不涉及）、**档位在成交过程中被打空**（方案 B 的概率抽签）、**TTL 到期与成交同时发生**（竞态）。
- 实现：订单状态机 `NEW → PARTIALLY_FILLED → FILLED / CANCELED`，`s_rem` 追踪剩余量；部分成交后剩余部分的**队列位置被保留**（交易所语义：部分成交的单留在原队列位置）—— 这是一个常被忽略的细节，必须实现。

### 6.4 TTL 与过期

- TTL 语义：挂单超过 `TTL` 未成交则撤单。TTL 与成交的关系是**竞争**，实现上在事件循环中按时间戳判定：处理事件时先检查 TTL 到期（撤销），再处理成交事件 —— 顺序必须与交易所一致（撤单在交易所侧到达时若已被成交，则返回"部分/全部已成交"）。
- **TTL 扫描实验（建议）**：`TTL ∈ {1, 2, 5, 10, 30, 60, 300}` 秒，输出：

| TTL | 成交率 | 平均成交延迟 | 每单期望毛利 | 撤单次数 | 队列位置损失 |
|---|---|---|---|---|---|
| 待测 | | | | | |

- 设计约束【实测推导】：BBO 档位生命周期中位 1.73 秒 → TTL < 2 秒几乎必然错过；TTL > 30 秒则绝大多数单在原队列位置"熬死"。**建议起点 TTL = 5–15 秒**，由扫描定夺。
- 过期订单撤单后**不自动重挂**（重挂见 §6.5 的模式对比）。

### 6.5 撤单与重挂：三种模式对比实验

**核心经济学**：撤单后重挂 = **回到队尾**；不撤单 = 保留队首位置。这两者的成交概率差异是数量级的，必须显式建模。

| 模式 | 行为 | 预期 | 风险 |
|---|---|---|---|
| **M1 Keep** | 挂出后不动，直到成交或 TTL | 队列位置最好 | 报价陈旧 → 被穿盘；TTL 到了被动撤 |
| **M2 Cancel-Repost（同价）** | TTL 到期撤单，同价重挂 | 队列位置重置，价差不变 | 若重挂时盘口已移，新单可能在更差的位置；重挂瞬间可能变成 Taker |
| **M3 Cancel-Repost（改进价）** | TTL 到期撤单，向盘口方向改进 1 tick 重挂 | 成交概率↑，价差↓ | 价差被压缩到手续费边缘 |

**实验设计（建议）**：同一 30 天 L2 窗口，三模式各跑一次（相同随机种子、相同参数），输出：

```
                 M1 Keep      M2 Repost     M3 Improve
成交率            x%           x%            x%
平均排队等待       x ms         x ms          x ms
每成交毛利 (bps)   x            x             x
日均毛收益 (USDT)   x            x             x
穿盘次数(Taker)     x            x             x
```

**建议实现方式**：M2/M3 的重挂动作要走完整的延迟模型（§7），因为"撤单请求到达交易所"与"新单到达交易所"之间存在空窗（实测 RTT 45–75 ms），空窗期内我方无报价暴露。

---

## 7. 延迟模型

### 7.1 三段延迟

```
交易所产生事件  ──①feed latency──►  我方收到  ──②compute latency──►  我方发出订单  ──③order latency──►  交易所收到
```

| 段 | 建模 | 参数（实测起点） | 说明 |
|---|---|---|---|
| ① feed latency | `local_ts − exchange_ts` | 实测归档分布：中位 133 ms、p1 124、p99 139 | 【实测】用实测经验分布，**重采样**而非常数 |
| ② compute latency | 事件循环抖动 | 10–50 ms（实测，共享上下文） | 建模为 `uniform(10, 50)` ms 或从实盘日志反推的经验分布 |
| ③ order latency | 网络 RTT | 45–75 ms（实测） | 单向 ≈ RTT/2，即 22–38 ms |
| **合计决策到成交** | ①+②+③ | 典型 165–225 ms | 这是"陈旧报价窗口" |

> 【需本机实测验证】①用归档值是**保守的**（归档链路的 133 ms 包含厂商落盘，比我们 VPS 的实际 feed 延迟大）。真实 VPS feed 延迟需在 `live_cluster/okx_ws_manager.py` 中加 `exchange_ts → 本地到达` 打点实测后替换。建议同时跑"feed=归档 133 ms"与"feed=实测"两档。

### 7.2 时间推进语义（关键实现细节）

引擎维护**两条时间轴**：

- `exchange_ts` 轴：回放交易所事件的顺序（决定撮合的因果顺序）。
- `local_ts` 轴：我方"感知到"事件的时间（决定我方决策何时做出）。

```python
# 双时间轴事件循环
book_events = sorted_by(exchange_ts)     # 交易所真值流
local_queue = priority_queue()           # 按 local_ts 排序的我方动作

while book_events or local_queue:
    t_ex = next_exchange_ts(book_events)  # inf if empty
    t_lo = local_queue.peek_ts()          # inf if empty
    if t_lo <= t_ex:
        run_local_action(local_queue.pop())   # 我方按"本地时间"行动
    else:
        ev = book_events.pop()
        apply_to_book(ev)                    # 交易所真值推进
        schedule_local_action(ev, t_lo = ev.local_ts + compute_latency)
```

**因果保证**：我方永远只能基于"已经到达本地的事件"做决策；对尚未到达的事件（`exchange_ts > 当前 local 时间`）引擎完全不可见 —— 这就是**陈旧报价套利**的物理来源。

### 7.3 陈旧报价套利的捕捉（必须能被引擎看见）

场景：我方在 `t=0` 看到 `best_bid = 100`，挂出 `my_bid = 99.9`；订单在 `t=0+45ms` 到达交易所；期间盘口从 99.9 跌到 99.0 → 我方买单成为 Taker（穿盘），成交价 99.0 而非 99.9。

引擎必须能：
1. 在 45 ms 后把订单标记为"到达时已穿盘"，走 Taker 路径（§6.2）。
2. 在报告里单列 `stale_quote_taker_fills` 计数与累计滑点损失。

**滑点量化**：滑点损失 = `(预期成交价 − 实际成交价) × size`，单独入账（不混进"逆向选择"，因为它是**延迟造成**而非**毒性流造成**）。

### 7.4 延迟敏感性扫描与盈亏平衡延迟

**扫描**：把总决策延迟 `L ∈ {10, 30, 60, 120, 240, 480, 960} ms` 逐点重跑同一窗口，输出：

```
L(ms)   净收益(USDT)   成交率   Taker混入率   平均滑点(bps)
10      ...
...
```

**盈亏平衡延迟（breakeven latency）定义**：

> 在给定窗口、给定参数下，使**净收益 = 0**（含所有成本与滑点）的总决策延迟 `L*`。

**求解方法（二分法，Monotone 单调性由"延迟↑ → 成交率↓且滑点↑"保证）**：

```python
def breakeven_latency(window, params, lo=0.001, hi=2.0, tol=0.005):
    """返回净收益=0 的总延迟（秒）。要求 net_pnl(L) 关于 L 单调不增。"""
    assert net_pnl(window, params, lo) >= 0
    assert net_pnl(window, params, hi) <= 0
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if net_pnl(window, params, mid) >= 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
```

**工程实践建议**：二分法要求每次 `net_pnl(L)` 重跑整窗口（30 天 ≈ 20–60 s/次），7 次扫描 ≈ 3–7 分钟 —— 1 核可接受。若窗口更长，改用"分段线性插值 + 局部二分"。

**报告口径**：`L*` 必须与实测 RTT（45–75 ms）+ compute（10–50 ms）对比。若 `L* < 0.1 s`，说明该策略在当前参数下**对延迟零容错**，实盘不可行。

**注意**：净收益对延迟**不一定**严格单调（更长的延迟可能碰巧避开某些穿盘）。因此必须先用粗扫描检查单调性；若不单调，改用"最小使净收益 < 0 的延迟点"作为保守定义，并在报告中说明。

---

## 8. 成本模型

### 8.1 手续费

| 项 | 费率 | 计费口径 |
|---|---|---|
| Maker | 0.02%（2 bps） | 按**杠杆开仓名义值**扣除：`fee = price × size × 0.0002` |
| Taker | 0.05%（5 bps） | 同上，`0.0005` |

**名义值口径的注意点**（易错点）：合约的"名义值"= `price × size`（不做杠杆放大）。若用保证金占用（`price × size / leverage`）计费会低估 50 倍。

**单位统一**：全部转成 base 币后按 USDT 计价，保留 8 位小数累加，避免浮点漂移。

### 8.2 资金费率（永续）

- 计提时点：每 8 小时（OKX 标准为 00:00 / 08:00 / 16:00 UTC，实际间隔 8h）。
- 计提公式：
  ```
  funding_payment = position_size × mark_price × funding_rate × direction_sign
  # 多头在正费率时支付；空头在负费率时支付
  # cash -= funding_payment
  ```
- 数据源：本地 `03_governed_lake/.../crypto/funding_rate/`（已有 DOGE/SOL/SUI）；BTC-USDT-SWAP 可从 OKX 公共接口 `GET /api/v5/public/funding-rate` 拉历史，或用 cryptohftdata 的 `ticker`/`mark_price` 族交叉推导。
- **旧引擎完全忽略资金费** —— 这是红线项（§11.4）。

**量化影响（推导）**：

- 30U 账户、平均库存 `q̄`（以张计）→ 平均名义暴露 `N̄ = q̄ × 808 USDT/张`（BTC=80,800 时 1 张 = 808 USDT；实测口径见共享上下文）。
- 资金费年化成本 ≈ `N̄ × r_avg × 3 × 365`（每日 3 次计提）。
- 取 BTC 永续典型平均资金费率 0.01%（8h 一次，即年化 10.95%）：
  - 若 `q̄ = 0.01 张`（几乎无库存）→ 年化成本 ≈ `8.08 × 0.0001 × 3 × 365 ≈ 0.88 USDT/年`（可忽略）
  - 若 `q̄ = 0.05 张`（接近实盘 max_inventory）→ 年化成本 ≈ **4.4 USDT/年**，相当于 30U 本金的 **14.7%/年** —— **这是一个足以吃掉全部做市利润的量级**。
- **结论（推断）**：在小本金 + 低库存上限下，资金费不是"锦上添花"，而是**与手续费同量级的固定成本**。回测必须逐笔计提并单列。

### 8.3 借贷利率 / 现货做市

- 若做 RWA / HIP-3 现货标的做市，需计**库存持有成本**：
  ```
  borrow_cost = position_size × mark_price × borrow_rate × (holding_seconds / 31,536,000)
  ```
- 借贷利率来源：交易所公布的借币利率（OKX `public/interest-rate-loans`）；HIP-3 标的的借币利率波动远大于主流币，**必须按标的取当日实际值**，禁止用常数。
- 现货做市还多一条：**没有资金费但有库存单边风险** → 库存上限应比永续更紧。

### 8.4 积分 / 返佣

- 部分交易所对 Maker 返佣（负费率）或按交易量发积分。建模为**费率调整项**：
  ```
  effective_maker_fee = maker_fee - rebate_rate
  ```
- 处理方式：把 rebate 作为**独立可调参数**，默认 0（保守），并在报告中给出"若返佣为 X bps 时的盈亏平衡"。**不得**把返佣写进基准结论。

### 8.5 成本敏感分析（必做）

手续费扫描（Maker 0.02% → 0.03% → 0.04%）：

| Maker 费率 | 双边成本 | 策略净半价差要求 | 结论（待回测填数） |
|---|---|---|---|
| 0.02% | 0.04% | 净半价差 > 0.02% + 逆向选择 + 队列损耗 | 现状（半价差门槛 2.5 bps）→ 净边际仅 **1 bps/单边** |
| 0.03% | 0.06% | 净半价差 > 0.03% + … | 需要半价差 ≥ 3 bps，**必须放宽价差** |
| 0.04% | 0.08% | 净半价差 > 0.04% + … | 半价差需 ≥ 4 bps，几乎无利可图 |

**关键量化（推导）**：现有策略 `min_half_spd = 2.5 bps`（见 `src/run_2year_asgrid_backtest.py:102`），双边总成本 4 bps，故**每轮往返的净边际只有 1 bps**。而队列损耗与逆向选择任一项超过 1 bps，策略即转负 —— 这与"回测 +68.19% vs 实盘微亏"的落差方向完全一致。

**结论（推断）**：该策略在 30U / 0.01 张粒度下，**费率每上升 1 bps 就吃掉全部理论边际**。回测必须输出"净半价差 vs 费率"的盈亏平衡表，作为参数调整的依据。

---

## 9. 本金离散粒度与规模效应

### 9.1 离散手数映射

- 交易所约束（实测来自共享上下文）：OKX BTC-USDT-SWAP **最小 0.01 张/笔**，1 张 = 808 USDT 名义（BTC=80,800 时）→ **0.01 张 ≈ 8.08 USDT 名义**。
- 30U 账户 → **单笔名义占总资产 26.9%**（实测数据）。

映射规则（引擎内统一）：

```
连续目标库存 q*（模型输出，可为分数）
  → 可执行手数 q_exec = round(q* / lot) * lot，lot = 0.01 张
  → 挂单 size 同样是 lot 的整数倍
  → 且 size × 808 ≤ 可用保证金 × 交易所最大杠杆
```

```python
def to_lots(q_continuous, lot=0.01, min_order_lots=1):
    n = int(math.floor(abs(q_continuous) / lot + 1e-9))     # 向下取整，不允许透支
    n = max(n, min_order_lots) if abs(q_continuous) > 0 else 0
    return math.copysign(n * lot, q_continuous)
```

**禁止**在回测里用"连续库存 + 连续名义"计算手续费与盈亏 —— 手续费按**实际成交手数**算。

### 9.2 离散粒度对库存曲线的影响

- 库存只能在 `{..., -0.02, -0.01, 0, +0.01, +0.02, ...}` 的**台阶上移动**，无法平滑回到 0。
- 后果：
  1. **库存偏置量化误差**：模型算出的理想偏置 `δ = ρ·δ_base·0.75` 可能小于 1 tick → 落到离散台阶后偏置"跳变"，等价于**报价跳档**（旧引擎用连续偏置，天然高估了调仓精度与成交率）。
  2. **残余库存滞留**：一次成交 0.01 张后，若模型认为应回到 0 而实际差 0.005 张 → 直接归零还是留仓？必须与实盘一致（建议：留仓，但把"归零不足一手"记入 `dust_inventory` 统计）。
  3. **返程不对称**：买入 0.01 张 → 库存 +0.01；卖出后库存 0，需要再卖 0.01 张才能为负。长期漂移会累积。
- 引擎必须输出**离散库存路径**（不是连续曲线），并统计：
  ```
  inventory_ladder_occupancy : 各手数档位停留时间占比
  dust_events               : |q| < 1 lot 的时间占比
  drift_after_flat          : 连续 20 笔后 |q| 的期望绝对值
  ```

### 9.3 容量分析（从本金反推约束）

给定本金 `C`（30 USDT），反推可承受的规模：

| 量 | 公式 | 30U 结果 |
|---|---|---|
| 单笔最小名义 | `min_lot × ctVal × price` | 8.08 USDT |
| 单笔占资比 | `min_notional / C` | **26.9%** |
| 库存上限名义 | `max_inv_lots × 808` | 0.05 张 → **40.4 USDT** |
| 所需最低杠杆 | `max_inv_notional / C` | **1.35×** |
| 保证金占用（10× 杠杆） | `40.4 / 10` | 4.04 USDT（13.5% 本金） |
| 手续费/往返（0.02%） | `2 × 8.08 × 0.0002` | 0.0032 USDT |
| 往返毛利（半价差 2.5 bps） | `2 × 8.08 × 0.00025` | 0.0040 USDT |
| **往返净边际** | 毛利 − 手续费 − 资金费 | **≈ 0.0008 USDT（0.8 厘）** |

> 这张表就是"30U 账户做市"的全部经济学：**每往返一次往返净赚约 0.0008 USDT**。要月赚 10 USDT（33%）需要 12,500 次往返 —— 每月 1.4 万笔。此时**任何 1 bps 的费率上升直接归零**，任何队列损耗超过 12% 直接归零。

**容量反推的通用式**：

```
max_single_notional = C × f_max          # f_max = 单笔占资上限（建议 ≤ 25%）
max_inventory_notional = C × g_max        # g_max = 库存名义占资上限（建议 ≤ 150%）
required_leverage = max_inventory_notional / C
fee_drag_per_roundtrip = 2 × maker_fee
min_edge_per_roundtrip = fee_drag + funding_per_hour × holding_hours + slippage_allowance
```

### 9.4 多标的并行时的本金分配

建议规则（简单、可审计）：

1. **单标的优先**：本金 < 100U 时**只做 1 个标的**。30U 分到 3 个标的 = 每个 10U，连 1 笔 8.08 USDT 的最小单都放不下（10U ÷ 8.08 = 1.2 笔）→ 连续库存完全退化。
2. **分配公式（若必须多标的）**：
   ```
   alloc_i = C × w_i,  w_i = min(  (target_edge_i / (edge_vol_i × sqrt(n_i))) / Σ_j(...) ,  cap )
   且 alloc_i ≥ min_working_capital = 3 × min_notional_i   # 至少能挂 3 笔
   ```
3. **硬约束**：`Σ_i alloc_i × (1 + margin_buffer) ≤ C × 0.8`（留 20% 缓冲应对浮亏与手续费）。

---

## 10. 引擎实现设计

### 10.1 技术选型对比表

| 维度 | **NautilusTrader** | **hftbacktest** | **自研 Numba** | **Vectorbt / vectorbtpro** |
|---|---|---|---|---|
| 撮合保真度 | 高（事件驱动、真实订单生命周期、Post-Only/部分成交语义完备） | **最高**（专为 HFT 设计：队列模型、延迟模型、multi-asset） | 高（自写语义，容易漏边界） | 低（向量化，无法表达队列/队列前置量） |
| L2 增量回放支持 | 支持（`OrderBookDelta`/`OrderBookDeltas` 事件） | **原生支持**（`ROIVectorMarketDepth` 快照 + `ROIVectorMarketDepthBacktest`） | 支持（自己实现） | 不支持 |
| 队列感知 | 有（`QueueModel` 可插拔，含 `FIFOQueueModel`） | **有（`RiskAverseQueueModel` / `ProbQueueModel`）** | 有（自写 §5） | 无 |
| 延迟模型 | 有（`FillModel`/latency 注入） | 有（`exchange_latency`/`order_latency`/`feed_delay`，可分离） | 有（自写 §7） | 无 |
| 撮合速度（1 核） | 中（Python 事件循环，~1e4–1e5 event/s） | **高**（Cython，~1e6+ event/s） | **最高**（Numba，无 Python 对象） | 极高但语义不符 |
| CPU 需求（30 天 L2 ≈ 12.8 亿事件） | 数小时–数天 | 数十分钟–数小时 | **分钟级** | — |
| 内存需求 | 高（Python 对象树） | 中（列式 array） | 低（结构化数组） | 中 |
| 改造难度 | 中（需写 Adapter 把厂商 parquet 转 `OrderBookDeltas`） | 高（需装 Cython/编译、与厂商格式对齐、自建数据管线） | 中（自己写，但已有骨架） | 低但无用 |
| 许可证 | LGPL-3.0（商业使用需注意） | Apache-2.0（商用友好） | 自有 | vectorbtpro 商业许可；vectorbt Apache-2.0 |
| 社区活跃度 | 高（活跃、文档丰富、Discord） | 中（活跃度一般，维护节奏慢） | — | 高 |
| 本机可得性 | **已安装 1.221.0**（实测，`python3 -c "import nautilus_trader"`） | 未安装（需 Cython 编译链） | numba 需 `uv` 安装 | 未安装 |

**关键事实（实测）**：本机 Python 环境**已装 nautilus_trader 1.221.0**，但 `live_cluster/` 里的 "nautilus" 只是命名借用，**并未真正使用该库**（`live_cluster/as_nautilus_strategy.py` 只 import `math/numpy/typing`）。→ 引入真实 NautilusTrader 是**新增能力**，不是复用。

### 10.2 推荐方案

**推荐：自研 Numba 事件引擎为主 + NautilusTrader 作为语义对照与实盘对接的验收基准。明确不引入 hftbacktest。**

理由（逐条对应上表）：

1. **复用度最高**：现有定价状态机（`live_cluster/as_nautilus_strategy.py`：保留价、最优半价差、手续费门槛、ADX 状态机、冷却、FIFO 优先权保留）已经跑在实盘。回测引擎必须用**同一份**代码，否则"回测 ≠ 实盘"的问题会重现。NautilusTrader/hftbacktest 都要重写这层，反而增加分歧风险。
2. **1 核 1G 约束**：30 天 L2 ≈ 12.8 亿事件。NautilusTrader 的 Python 事件循环在这个量级上是小时级；Numba 结构化数组回放是分钟级。**在本项目的算力预算下，Nautilus 无法作为主力回测器。**
3. **不引入 hftbacktest 的理由**：它的优势（队列模型、延迟模型、列式高性能）正是我们要自己写的部分（§4/§5/§7 已给出可照抄的规格）；引入它要付出 Cython 编译链 + 数据适配 + 与自研定价层的对接三重成本。**但要把它当作"语义参照"**：照 hftbacktest 的 `ProbQueueModel` / `RiskAverseQueueModel` 的公式来实现我们的方案 A/B（文档公开可查，避免自创语义）。
4. **Vectorbt 排除**：无法表达 FIFO 队列、延迟与部分成交，与本切片目标完全无关。
5. **NautilusTrader 的正确定位**：不作为回测主力，而是作为**验收基准**——
   - 用它跑一段短窗口（例如 1 天 L2），比对自研引擎与 Nautilus 在同一策略代码下的成交序列；
   - 它同时是实盘对接的现成框架，将来把 `live_cluster` 迁到真 Nautilus 时，回测与实盘引擎同源。
   - 它也用来校准队列语义细节（Post-Only 拒绝、部分成交后队列位置保留等）。

### 10.3 目录结构（建议）

```
src/queue_backtest/
├── __init__.py
├── schema.py            # §3 规范 schema + 归一化后的事件结构体
├── normalize_l2.py      # 厂商 parquet → 规范 parquet → .npy 缓存
├── book.py              # §4 订单簿状态机（BookSide / 哈希表 / best-K 视图）
├── queue_models.py      # §5 方案 A / B / C（统一接口，同一事件流跑三种）
├── latency.py           # §7 双时间轴事件循环 + 延迟分布
├── costs.py             # §8 手续费 / 资金费 / 借贷 / 返佣
├── inventory.py         # §9 离散手数映射与库存台阶
├── engine.py            # 主回测循环（Numba njit）
├── strategy.py          # 复用 live_cluster/as_nautilus_strategy.py 的定价逻辑
├── calibrate.py         # §11 实盘对账 → 参数反推
├── validate.py          # §11.4 红线检查（自动化断言）
└── report.py            # 区间 + block bootstrap CI 输出

scripts/
├── download_l2.py       # cryptohftdata 下载（无 JWT，走 302 签名 URL）
├── run_micro_backtest.py
├── breakeven_latency.py # §7.4 二分求解
└── report_ci.py         # §11.3 block bootstrap

lake/l2_events/BTC-USDT-SWAP/2026-11-14/{events.parquet,events.npy}
reports/queue_backtest/{run_id}.json / .md
tests/
├── test_book_reconstruction.py   # §4.4 A1/A2/A3 断言
├── test_queue_models.py          # A/B/C 在构造场景上的期望行为
├── test_inventory_ladder.py      # §9.2 离散台阶
└── test_determinism.py           # 同输入两次跑出逐笔一致
```

### 10.4 数据接口约定（引擎读什么）

引擎**只**读 `.npy` 列式缓存（§3.3），不读 Parquet、不读 CSV、不连网。

```python
@dataclass
class EventStream:
    exchange_ts : np.ndarray[int64]   # N
    local_ts    : np.ndarray[int64]   # N
    seq_id      : np.ndarray[int64]   # N
    prev_seq_id : np.ndarray[int64]   # N
    price_tick  : np.ndarray[int32]   # N
    size        : np.ndarray[float64] # N
    n_orders    : np.ndarray[int32]   # N
    kind        : np.ndarray[int8]    # N  0=snapshot 1=book_update 2=trade
    side        : np.ndarray[int8]    # N  0=bid 1=ask 2=trade_buy 3=trade_sell
    symbol      : str
    tick_size   : float
    lot_size    : float
    ct_val      : float

    def iter_block(self, start_idx, end_idx): ...
```

**加载策略（1 核 1G）**：按**天**切块，逐日载入 `.npy`（1.7 GB/天 → 必须用 `np.load(mmap_mode='r')` 内存映射，避免常驻）。撮合热循环只访问当前事件窗口的字段。

> 优化：撮合循环只读 `exchange_ts / price_tick / size / n_orders / kind / side`，可把这 6 列单独抽成**合并列**（struct-of-arrays → 连续内存），并把 `n_orders` 降为 int16、`size` 用 float32（精度够：base 币数量 1e-8 精度需求 vs float32 的 1e-7 相对误差 → 数量级足够）。

### 10.5 性能预算

**目标（1 核 1G）**：

| 场景 | 事件量 | 目标耗时 | 备注 |
|---|---|---|---|
| Tier-1：30 天 L2 全量队列感知回测 | ≈ 12.8 亿 | **≤ 90 分钟** | 需实测验证 |
| Tier-1：1 天 L2 | ≈ 4,250 万 | ≤ 3 分钟 | 单次迭代调试用 |
| Tier-2：2 年 1m bar 降级回测 | 104 万 bar | ≤ 10 秒 | 现有 Numba 引擎已达成 |
| 参数扫描：7 个延迟点 × 30 天 | 7 × 12.8 亿 | ≤ 10 小时（可过夜） | 或改用 7 天窗口 |
| 三方案 A/B/C | 3 × 90 分钟 | ≤ 4.5 小时 | |

**单事件吞吐需求**：12.8 亿 ÷ 5400 秒 ≈ **236 k event/s**（1 天 4250 万事件 ÷ 180 秒 ≈ 236 k/s，同档）。Numba 在结构化数组热循环下可达 1 M+ event/s，故 90 分钟预算留有约 4× 余量；前提是**无 Python 对象、无字典、无分支预测失败**，并需要以下实现要点：

1. **全程 `nb.njit(cache=True, fastmath=False)`**。`fastmath=True` 会破坏浮点确定性 —— **确定性优先于速度**（`fastmath=False`）。
2. **热路径零分配**：所有数组预分配到最大长度；队列用 `int32` 索引的环形数组，不用 `deque`/`list.pop(0)`。
3. **价格用 int tick 比较**：避免浮点相等与哈希误差。
4. **哈希表用开放寻址 + 线性探测**：`int32[8192]` 表 + `uint8[8192]` 状态，容量取 2 的幂，冲突线性探测。
5. **best-K 视图增量维护**：不做全排序。
6. **事件字段用 SoA 连续数组**，避免 Numba 的结构体数组字段访问开销。
7. **`cache=True`**：首次编译后落盘到 `__pycache__`，避免每次跑都重编译（编译约 5–20 秒）。
8. **分块并行**：1 核无并行；但可利用"多标的/多日独立"做**多进程**（VPS 上是 1 核，禁止）。

**1 核降级路径（必须提供）**：

| 降级档 | 做法 | 何时用 |
|---|---|---|
| D1 | 缩短窗口（30 天 → 7 天 → 1 天） | 调参迭代 |
| D2 | 丢弃 `n_orders`（只用档位量）→ 方案 A | 内存吃紧 |
| D3 | 只保留 ±20 tick 内的档位（book 裁剪） | 大幅省内存与时间 |
| D4 | 只回放 `snapshot + trade`，丢弃 `book_update` 细节 → 退化为"档位快照 + 队列粗估" | 极限模式，**必须标注精度降级** |
| D5 | Tier-2：bar 级 + 成交率折扣系数（由 Tier-1 标定） | 2 年长窗口 |

> D5 的折扣系数标定方式（建议）：在 30 天窗口上，测出 `方案B成交率 / 方案C成交率 = ρ`（实测待定），然后在 2 年 bar 回测中把成交量乘以 `ρ`，并把 `ρ` 的不确定性作为区间的一部分传播。

### 10.6 确定性

**要求**：同数据、同参数 → 逐笔成交序列完全一致。

规则：

1. **随机种子从数据内容派生**，不用全局 seed：
   ```python
   import hashlib
   def derive_seed(*parts: bytes) -> int:
       h = hashlib.blake2b(b"|".join(parts), digest_size=8).digest()
       return int.from_bytes(h, "little") & ((1 << 63) - 1)

   seed = derive_seed(
       symbol.encode(),
       date_str.encode(),          # 回测窗口标识
       np.asarray(eq_ticks, dtype=np.int64).tobytes(),   # 等价参数指纹
       np.asarray(eq_sizes, dtype=np.float64).tobytes(),
       b"schemeB_v1",
   )
   rng = np.random.default_rng(seed)   # 独立的 Generator，不污染全局状态
   ```
   - **每次抽样必须带窗口标识**（date_str / 参数指纹），避免不同窗口共用同一随机流产生"人为相关"。
2. **禁止 `np.random.seed()` 全局设置**；所有随机数来自显式传入的 `Generator`。
3. **Numba 内的随机数**：Numba 支持 `np.random.default_rng()`（需 Numba ≥ 0.57），或用**自实现的确定性哈希随机**（推荐，避免 Numba/NumPy RNG 版本差异）：
   ```python
   @nb.njit
   def u01(state: uint64) -> float:
       # splitmix64：纯整数运算，跨平台跨版本一致
       state = state + 0x9E3779B97F4A7C15
       z = state
       z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9
       z = (z ^ (z >> 27)) * 0x94D049BB133111EB
       z = z ^ (z >> 31)
       return (z >> 11) * (1.0 / 9007199254740992.0)
   ```
4. **浮点确定性**：Numba `fastmath=False`；同一线程、同一顺序；不使用 `numpy` 的 `np.sum` 在多线程下（NumPy 2.x 的 pairwise 求和是确定的，但避免任何 BLAS 归约）。所有累计量用 float64，顺序累加。
5. **哈希随机与事件序号绑定**：抽样点用 `u01(seed ^ (event_index * 0x9E3779B97F4A7C15))` 形式，保证"同一事件的抽样结果与回放顺序无关地稳定"。
6. **记录 manifest**：每次回测输出 `data_manifest.json`（文件 SHA256、行数、起止时间、参数、seed 派生输入）→ 可复现性可审计。

---

## 11. 验证与反幻觉

### 11.1 引擎自检：乐观偏差的量化

**自检指标（必须每次回测自动计算并打印）**：

```
OPTIMISM_GAP = PnL(方案C) − PnL(方案A)          # 单位：USDT 与 相对本金的 %
OPTIMISM_GAP_REL = OPTIMISM_GAP / |PnL(方案B)|
```

解读：
- `OPTIMISM_GAP` 大 → 零排队假定的危害大。
- `OPTIMISM_GAP > 0` 且 `PnL(方案A) < 0` → **结论：策略在保守队列语义下为负，不应上实盘**（这是本引擎最有价值的输出）。
- `OPTIMISM_GAP ≈ 0` → 队列不是主要矛盾，应转向延迟/成本/离散粒度排查。

**第二个自检：bar 级 vs 事件级的差异**

```
BAR_VS_EVENT_GAP = PnL(1m bar 撮合) − PnL(L2 事件撮合)
```
→ 量化"用 1m OHLCV 回测做市"这个方法论本身的误差。

**第三个自检：跨引擎一致性**

同一 1 天窗口、同一策略参数，自研 Numba 引擎 vs NautilusTrader 的成交序列差异率应 < 0.1%（订单去重后逐笔比对）。不一致 → 语义有 bug，必须定位。

### 11.2 与实盘对账（参数反推）

**可用实盘样本（实测）**：
- 旧版 dayuan 35U：40.96 小时，2123 笔撮合，30.9% Taker 混入，手续费 4.92 USDT（占总亏损 72.6%），本金 35 → 28.25U。
- 新版 accountbot3 30U：10.38 小时，Maker 占比 99.5%，手续费 0.3269 USDT，净损益 −0.09 USDT，本金保全 98.6%。
- 任务书另提及 51.34 小时与 18 小时真实成交记录（更长样本，用于稳健性）。

**反推参数（可解算的量）**：

| 待反推量 | 定义 | 从实盘怎么算 |
|---|---|---|
| 真实成交率 `f_real` | 每单位时间成交次数 | 成交笔数 ÷ 有效报价时长 |
| 手续费占比 `fee_ratio` | 手续费 ÷ 毛利 | 实盘直接有（0.3269 / 毛利） |
| Taker 混入率 | taker 笔数 ÷ 总笔数 | 实盘直接有（30.9% / 0.5%） |
| 平均持仓时长 | 成交到反向成交的间隔 | 由成交序列重建 |
| 隐含库存均值 `q̄` | 平均持仓 | 由成交序列重建 |
| 隐含净半价差 | 毛利 ÷ 成交量 | 实盘毛利 ÷ 名义成交 |

**对账流程（建议）**：

1. 从实盘成交序列重建：`{时刻, 方向, 价格, 手数, 是否maker}`。
2. 在**同一时间窗口**上跑回测（用实测 L2 数据覆盖该窗口），比较：
   - 成交笔数（绝对差 ≤ 30%）
   - 手续费金额（绝对差 ≤ 30%）
   - 净损益符号（是否同号）
3. 若成交率系统性偏低 → 队列模型参数（`β`、TTL、挂单档位）需重标定。
4. 若成交率对但净损益差异大 → 成本/资金费/滑点模型有偏差。
5. **反推的目标不是"复现收益"，而是"复现量级"**。若 30 天回测的成交率能匹配实盘 10.38 小时的成交率（在同量级），说明撮合语义可信。

> 【关键纪律】实盘 10.38 小时样本量极小，**不得**用它来"验证收益"。只能用它验证"成交率与费率占比"这两类结构量。

### 11.3 区间估计（block bootstrap）

**方法**：按**日**分块，对日收益序列做 **stationary block bootstrap**（块长 = 7 天），重采样 10,000 次。

```python
def block_bootstrap_ci(daily_pnl, block=7, n_boot=10000, seed=derive_seed(...)):
    n = len(daily_pnl)
    n_blocks = int(np.ceil(n / block))
    max_start = n - block
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(n_boot):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        sample = np.concatenate([daily_pnl[s:s+block] for s in starts])[:n]
        stats.append(annualize(sample))
    return np.percentile(stats, [2.5, 97.5])
```

**为什么按块而非按日 i.i.d.**：做市日收益有自相关（库存未平、趋势持续），i.i.d. bootstrap 会低估方差。

**必须同时报告**：
- 三方案各自的 95% CI；
- `OPTIMISM_GAP` 的 CI（对两条 bootstrap 样本逐点配对计算差值，不是分别算 CI 再相减）。

**在 1 核上的成本**：10,000 次 × 730 天 × 3 方案，numpy 向量化 ≈ 20–60 秒，可接受。

### 11.4 红线清单（引擎必须结构性禁止）

以下每一条都必须有**自动化断言**（`validate.py` 在每次回测后运行，失败则回测产物标记为无效）：

| # | 红线 | 后果 | 断言方式 |
|---|---|---|---|
| R1 | **同一根 bar 内先成交买单再成交卖单的顺序假设** | 旧引擎在 bar 内按固定顺序撮合买卖，虚构无风险对冲利润 | 事件级引擎天然免疫；bar 级降级引擎必须**禁用 bar 内同时双边成交**（拆成两个子 bar 或用保守顺序） |
| R2 | **忽略跳空** | 用 low/high 判定成交隐含"价格路径必然经过" | 事件级引擎免疫；bar 级必须用 `open` 判定跳空方向 |
| R3 | **忽略资金费率** | 永续持仓的真实成本完全缺失 | 断言：回测持仓跨过 8h 边界时必须有资金费计提记录 |
| R4 | **把撤单当成免费** | 重挂成本（延迟 + 队列位置 + 空窗暴露）全丢 | 断言：每次撤单必须有 `cancel_latency` 记录与队列位置重置事件 |
| R5 | **无滑点 / 零队列假定** | 系统性高估 | 断言：报告必须同时包含方案 A 与 C 的结果，且 `OPTIMISM_GAP` 已打印 |
| R6 | **对称点差假定** | 真实盘口两侧不平衡（实测买一档 380 vs 卖一档 405，中位不对称） | 断言：成交价必须取**实际对方档位**价格，不得用 `mid ± 固定半价差` |
| R7 | **手续费按保证金而非名义值计** | 费率被低估杠杆倍数倍 | 断言：每笔手续费 = `price × size × fee_rate`，`size` 为 base 币数量 |
| R8 | **回测用连续库存、实盘用离散手数** | 离散粒度偏差被隐藏 | 断言：库存序列的每个取值都必须是 `lot` 的整数倍 |
| R9 | **多空双边在同一事件上互相抵消** | 制造不存在的对冲 | 断言：一次事件只能改变一个方向的队列状态 |
| R10 | **回测里出现随机数但种子不落盘** | 不可复现 | 断言：`manifest.json` 必须含 seed 派生输入的 SHA256 |
| R11 | **Post-Only 被拒后当作已成交** | 把被拒单计入成交与手续费 | 断言：`reject` 事件不产生 fill，不计手续费 |
| R12 | **部分成交后剩余量重新排到队尾** | 高估成交概率 | 断言：部分成交后剩余单的 `queue_ahead` 保持不变 |

---

## 12. 分阶段落地

| 阶段 | 内容 | 产出 | 依赖 |
|---|---|---|---|
| **P0**（1–2 天） | 数据链路：下载 → 归一化 → `.npy` 缓存；写 §4.4 三条断言 | 可回放的 7 天 L2 缓存 + `test_book_reconstruction.py` | cryptohftdata 可下载（已实测） |
| **P1**（3–5 天） | 撮合核心：订单簿 + 队列 A/B/C + 双时间轴 + 成本 | 1 天 L2 上跑出方案 A/B/C 三组结果 | P0 |
| **P2**（2–3 天） | 策略对接 + 离散粒度 + 库存台阶 | 30 天 Tier-1 回测（对照旧引擎 +68.19%） | P1 |
| **P3**（2 天） | 实盘对账 + 参数反推 | `calibrate.py` 报告 | P2 + 实盘日志 |
| **P4**（2 天） | 延迟扫描 + breakeven latency | `L*` 曲线与数值 | P2 |
| **P5**（2 天） | bootstrap CI + 红线断言 + 报告模板 | 区间化报告模板 | P2 |
| **P6**（并行） | NautilusTrader 交叉验证 | 1 天窗口逐笔比对报告 | P1（可选但强烈建议） |

**P0 的第一个可验证产物**（建议最先做，因为它是整个设计的地基）：
用 2026-11-14 11:00–12:00 UTC 的 OKX 数据，输出：
1. BBO 价差分布（应复现"1 tick 占 99.88%"）；
2. 买一档生命周期（应复现中位 17 事件 ≈ 1.73 s）；
3. 买一档量分布（应复现中位 380、p5 72.5、p95 1280）；
4. 守恒断言 A1/A2/A3 全通过。

若这 4 条复现，说明数据链路与单位口径正确；否则先修数据，不要写撮合。

---

## 附录 A · 实测数据摘要（2026-11-14 探测）

| 项 | 值 | 来源 |
|---|---|---|
| OKX L2 orderbook 文件 | `okx_futures/2026-11-14/11/BTC-USDT-SWAP_orderbook.parquet`，7.35 MB | 本机下载实测 |
| 行数 / 事件数 | 1,769,200 / 35,460（9.85 evt/s） | 实测 |
| snapshot 深度 | 800 行 = 400 档/侧 | 实测 |
| 每事件变更档位 | 中位 26 | 实测 |
| 买一档量（订单数） | 中位 380（40 单），p5 72.5（14），p95 1280（92） | 实测 |
| 买一档生命周期 | 中位 17 事件 ≈ 1.73 s；最优价变动 944 次/小时 | 实测 |
| 价差 | 1 tick 占 99.88%，最大 20 tick | 实测 |
| 成交笔数 | 67,945/小时（18.9/s），中位量 0.26 | 实测 |
| 归档 feed 延迟 | 中位 133 ms（p1 124 / p99 139） | 实测 |
| 深度名义额（±0.2%） | 买 $8.74M / 卖 $11.39M（按张换算） | 实测反推 |
| 交易所最小单 | 0.01 张 ≈ 8.08 USDT 名义 | 共享上下文（实测） |
| 实盘 RTT / 抖动 | 45–75 ms / 10–50 ms | 共享上下文（实测） |
| 本机环境 | nautilus_trader 1.221.0 已装；numba 未装（需 `uv`）；12 核 14 GB（开发机，非 VPS） | 实测 |
| 目标算力 | 1 核 1 GB（VPS `155.254.60.38`） | 共享上下文 |

## 附录 B · 关键伪代码汇总

### B.1 队列判定（§5）

```python
@nb.njit
def on_level_update(my_orders, side, tick, new_size, old_size, ts):
    """档位量变化时更新我方排队位置并判定成交。"""
    ds = new_size - old_size                      # 负数 = 减少
    for o in my_orders[side]:
        if o.price_tick != tick or o.status != NEW: continue
        o.queue_ahead = max(0.0, o.queue_ahead + ds)   # 撤单/成交都算前方让位
        if o.queue_ahead <= 1e-12 and new_size == 0.0:
            # 方案 A：整档被打空 → 我方（队尾）成交
            fill_order(o, tick, ts, scheme="A")
        elif scheme == "B" and ds < 0:
            # 方案 B：按剩余队列份额抽签部分成交
            share = o.size_rem / max(o.queue_ahead + o.size_rem, 1e-12)
            fill_qty = min(o.size_rem, -ds * share * beta)
            if u01(seed ^ hash(ts, tick, o.order_id)) < 1.0:   # 概率抽签
                fill_partial(o, fill_qty, tick, ts)
```

### B.2 双时间轴事件循环（§7.2）

见 §7.2 代码块。

### B.3 盈亏平衡延迟（§7.4）

见 §7.4 代码块。

### B.4 离散手数映射（§9.1）

见 §9.1 代码块。

### B.5 确定性种子派生（§10.6）

见 §10.6 代码块。

---

## 附录 C · 标注约定

- **【实测】**：本机探测或共享上下文中已观测到的真实数值。
- **【推断】**：由实测数据经明确推理链得出、但尚未由回测验证的结论。
- **【建议】**：本设计提出的做法与阈值，需落地时确认。
- **【需本机实测验证】**：当前无法确认、必须由后续实验判定的假设（§2.3 单位口径、§7.1 VPS 真实 feed 延迟、Tier-1 性能预算 90 分钟）。
