# 01 — 标的监控流 + 微观数据采集/治理管线

> 切片归属：**数据与选品基础设施层**
> 覆盖问题：(1) 如何持续监控「符合做市要求」的标的流，形成自动发现/淘汰/扩容的标的池；(2) 如何从 cryptohftdata 或交易所 WebSocket 采集微观信息，落地为可回测、可训练的 L2 数据湖。
> 上游文档：`ARCHITECTURE_AND_EXECUTION_FLOW.md`（实时链路）、`README.md`（盈利导向标的池定义）、`LESSONS_LEARNED.md`（工程铁律）。
> 下游文档：`02-*`（定价/做市执行）、`03-*`（回测与 ML 训练）由其他切片负责。

**本文档中阈值的标注约定（全文强制）**

| 标记 | 含义 |
|---|---|
| `【实测】` | 本次设计时在真实环境/真实 API 上验证过的事实，附来源与时间 |
| `【建议起始值，需按实测校准】` | 由 A-S 理论 + 仓库既有实盘经验推导的起点值，必须用 7–14 天实盘/回测重新标定 |
| `【待实测】` | 明确列为待办，当前无可靠数值，禁止写进硬风控 |

**核心经济约束（贯穿全文，来自本仓库 README 铁律一）**

```
NetPnL_per_fill = ΔSpread − 2×MakerFee − E[AdverseSelection] − InventoryCost
做市可行 ⟺ 标的的「稳态可捕获价差」 > 2×MakerFee + 逆向选择成本 + 库存成本
```
本仓库 Maker 费率口径为 2 bps/边 → 往返成本 4 bps；README 强制总报价价差 ≥ 10 bps（2.5× 手续费垫）。
**推论（本文档所有流动性/点差阈值的锚）**：任何标的若「稳态中位点差 − 逆向选择损失」不足 10 bps，则无论成交额多大都不可做市，只能进观察池。

---

## 0. 环境事实基线（`【实测】`，2026-11-14 验证）

这些数字全部来自对真实 API 的调用，不是估计，后续实现必须以此为契约。

### 0.1 cryptohftdata REST API 事实

| 项目 | 实测结果 | 来源 |
|---|---|---|
| Base URL | `https://api.cryptohftdata.com/v1` | `GET /v1/status` |
| 符号发现 | `GET /v1/symbols?exchange=<ex>&data_type=<dt>` → `{"exchange","data_type","count","symbols":[...]}`，含已下架但有历史文件的标的 | `【实测】` |
| 文件下载 | `GET /v1/download?file=<key>` → **HTTP 302 跳转到对象存储**，必须 `-L` 跟随，否则拿到 0 字节 | `【实测】` |
| 文件 key 规范 | `{exchange}/{YYYY-MM-DD}/{HH}/{symbol}_{data_type}.parquet` | `【实测】` + 官方文档 |
| 发布延迟 | 每小时结束后约 **15 分钟**产出（官方文档）；`/v1/status` 的 `target.lookback_hours` 实测为 **2**，`target.prefix` 实测形如 `2026-11-14/11` | `【实测】` `/v1/status` |
| 匿名限流 | **60 请求 / 60 秒 / IP**；429 时读 `Retry-After` | 官方文档 |
| API Key | 查询参数 `api_key=` 或请求头 `X-API-Key` | 官方文档 |
| JWT | `POST /v1/jwt-token` + `X-API-Key` → `{"jwt_token": ...}`，**有效期 4 小时**，之后用 `Authorization: Bearer <jwt>` | 官方文档 |
| 无限速/直连 S3 | 登录后 dashboard 生成临时 S3 凭证，用 `aws s3 cp --recursive` 批量同步（**凭证会过期**） | 官方文档 |
| 错误格式 | `{"error": "...", "code": "bad_request\|not_found\|..."}`，429 另有 `RateLimit-*` 响应头 | `【实测】` |

### 0.2 cryptohftdata 数据语义（决定我们能否直接复用其文件）

统一事件结构（各数据类型共用前缀列，`【实测】` 下载并用 pyarrow 读取真实文件校验）：

```
received_time      INT64  not null   采集端接收时刻（纳秒）
event_time         INT64  not null   交易所生成时刻（单位随交易所而变，需归一）
transaction_time   INT64  nullable   交易所事务时间（部分场所有）
symbol             STRING not null
event_type         STRING not null   "snapshot" | "update"（仅 orderbook）
first_update_id    INT64  nullable   首个更新 ID
final_update_id    INT64  nullable   末个更新 ID（链尾）
prev_final_update_id INT64 nullable  链尾的上一个值 → 缺口检测的真正依据
last_update_id     INT64  nullable   交易所处理到的最后 ID
side / price / quantity / order_count
```

| 数据类型 | 独有列 | 关键坑（官方 venue notes + 本次核对） |
|---|---|---|
| `orderbook` | 上表全部 | 一行 = **一个价位**（不是一条消息）。`price`/`quantity` 存为 **字符串**以保精度。小时首可能无快照（需沿用上一小时盘口）。 |
| `trades` | `trade_id, trade_time, is_buyer_maker, order_type` | OKX 2026-09 之前是**聚合行**（一 taker 订单一价位），之后才是逐 fill。`is_buyer_maker=true` 表示买方是 maker（**主动方是卖方**）。 |
| `ticker` | `price_change_percent, last_price, high/low, base/quote_asset_volume, total_trades` | OKX 永续 `quote_asset_volume` 在 2026-10 之前为空；Bybit 历史 `price_change_percent` 是分数不是百分数。 |
| `mark_price` | `mark_price, index_price, estimated_settle_price, funding_rate, next_funding_time` | `funding_rate` 是**每期费率的小数**（0.0001 = 0.01%）。OKX 2026-09 之前 `event_time` 存的是**下次结算时间**（会造成前视偏差，必须改用 `received_time`）。 |
| `open_interest` | `sum_open_interest, sum_open_interest_value, timestamp` | Bybit 2026-09 之前是**变化量增量**，必须前向填充。OKX 单位是**张数**，要乘 `ctVal`。 |
| `liquidations` | — | OKX 用 `instType=SWAP` 一个订阅覆盖全部合约。 |

**逐交易所的单位陷阱（做市定价必须处理，否则盈亏全错）** `【实测】`：

- OKX 永续：**数量单位是「张」**，`ctVal` 决定真实币量。`【实测】` `DOGE-USDT-SWAP`: `ctVal=1000, ctValCcy=DOGE`；`AAPL-USDT-SWAP`: `ctVal=1, ctValCcy=AAPL`。
- BitMEX：原始单位（XBTUSD 是 USD 合约、XBTUSDT 是 1e-6 BTC…）。
- Kraken 反向合约：USD 合约。Lighter：2026-09 之前 `sum_open_interest` 存的是 USD 名义。
- Lighter orderbook：2026-09 起 `final_update_id` = `nonce`，`prev_final_update_id` = `begin_nonce`，链式连续；`last_update_id` 是 API 服务器 `offset`，**不连续、不能用来找缺口**；重连后 offset 会归零变小（正常）。
- Hyperliquid `tid` 是买卖双方 order id 的哈希，**不是序列号，不能用于缺口检测**。

### 0.3 交易所 WebSocket 事实

| 交易所 | 公共 WS | 盘口通道 | 序列号语义 | 元数据 REST |
|---|---|---|---|---|
| OKX v5 | `wss://ws.okx.com:8443/ws/v5/public`；逐 fill 的 `trades-all` 在 `wss://ws.okx.com:8443/ws/v5/business` | `books`（400 档，快照+增量，100ms）；`books50-l2-tbt`（VIP4+）；`books-l2-tbt`（VIP5+）；`books5`（5 档快照，100ms） | `seqId` / `prevSeqId`（快照 `prevSeqId=-1`），**连续可断点** | `GET /api/v5/public/instruments?instType=SWAP` |
| Lighter | `wss://mainnet.zklighter.elliot.ai/stream` | `order_book/<market_index>`：`subscribed/order_book`（快照）→ `update/order_book`（增量） | `nonce` / `begin_nonce` 链式；`offset` 不连续 | `GET https://mainnet.zklighter.elliot.ai/api/v1/orderBooks`（market index 表；1=BTC, 2048=ETH/USDC） |
| Hyperliquid | `wss://api.hyperliquid.xyz/ws` | `l2Book`：**每次推送全量快照（无增量）**，需本地 diff | 无序列号（`tid` 不可用） | `POST https://api.hyperliquid.xyz/info` |

**HIP-3 的实测命名空间**（`【实测】` `GET /v1/symbols?exchange=hyperliquid_futures&data_type=orderbook`，共 463 个符号）：
`XYZ:AAPL`、`XYZ:NVDA`、`CASH:AMZN`、`CASH:GOLD`、`CASH:USA500`、`CASH:WTI`、`FLX:CRCL`、`FLX:COPPER` …—
即 **HIP-3 每建一个 dex 就多一个前缀**，标的符号空间是**动态生成**的，不能硬编码。

**RWA / 代币化股票在 OKX 的实测流动性**（`【实测】` `GET /api/v5/market/ticker`，2026-11-14 14:43 UTC）：

| 标的 | last | 24h 成交额 | 点差 |
|---|---|---|---|
| `AAPL-USDT-SWAP` | 356.07 | 27897 张 × 1 股 ≈ **9.93e6 USDT** | **0.281 bps** |
| `DOGE-USDT-SWAP` | 0.06201 | 2.938e9 DOGE ≈ **1.82e8 USDT** | 1.612 bps |
| `BTC-USDT-SWAP` | 66434 | 98151 BTC ≈ **6.52e9 USDT** | 0.015 bps |
| `PEPE-USDT-SWAP` | 4.2081e-6 | 4.015e13 PEPE ≈ **1.69e8 USDT** | 0.237 bps |

> ⚠️ `volCcy24h` 对 OKX 永续是**基础币数量**（张数 × `ctVal`），**不是**计价币金额 —— 这是最容易读错的一个字段。

**这个实测结果是本文档最重要的一个结论**：
> OKX 上的 RWA/代币化股票合约**成交额并不算低**（AAPL 24h ≈ 993 万 USDT，与 DOGE 的 1.8 亿只差一个数量级），
> 但**点差极窄（0.281 bps）且成交极其稀疏**（`【实测】` 该小时仅 **704 笔**成交 ≈ 0.196 笔/秒）。
> 对做市商而言，**点差窄 = 手续费即成本**（2 bps × 2 = 4 bps ≫ 0.281 bps 价差）：每一次成交都是负期望。
> **RWA 在 OKX 目前不是「点差机会」，而是「资金费率 carry + 事件驱动」机会**，必须靠 funding carry 与节假日/除权事件建模，不能靠吃价差。
> 结论：RWA 必须**单独走一条漏斗分支**（阈值不同、指标不同），不能与山寨币共用同一套分数线。

**订单簿消息速率的实测基线**（`【实测】`，OKX 永续 400 档 `books` 通道，2026-11-13 10:00–11:00 UTC，归档按「价位行」计）：
| 标的 | 一小时行数 | 行速率 | 折合帧速率 | 压缩后大小 |
|---|---|---|---|---|
| `BTC-USDT-SWAP` | 2,483,801（4 次快照 + 2,482,201 增量行） | **690 行/s** | ≈ 1.7 帧/s | 9.98 MB/h ≈ **240 MB/天** |
| `DOGE-USDT-SWAP` | 330,226 | **92 行/s** | ≈ 0.23 帧/s | 3.08 MB/h ≈ **74 MB/天** |
| `AAPL-USDT-SWAP`（trades） | 704 笔 | — | 0.196 笔/s | 13 KB/h |

> ⚠️ **归档的行速率会系统性低估消息速率**（无价格变化的推送不产生行）。因此漏斗必须区分两个指标：
> `level_row_rate`（行速率，档案可得）与 `frame_rate`（帧速率，只有 live recorder 能测）。
> §2.1 的 G2 阈值已按此重新标定。

---

## 1. 总体架构：两个数据平面 + 一条标的流

```
                         ┌──────────────── 平面 A：历史回测平面（离线，可复现）────────────────┐
 cryptohftdata 归档 ───► │ archive_sync ──► bronze/chd/{exchange}/{date}/{hh}/{symbol}_{dt}.parquet │
 (按小时分片)            │   (增量同步/去重/缺口)      │  (原始不动，ZSTD)                       │
                         └────────────────────────────────────────────────────────────────────┘
                                                                 │ 统一事件 schema
                                                                 ▼
                                                      silver/events/{dt}/{exchange}/{symbol}/{date}/{hh}.parquet
                                                                 ▲
                         ┌──────────────── 平面 B：实盘自录平面（近实时，本地权威）──────────────┐
 OKX / Lighter / HL WS ─►│ recorder ──► bronze/live/{exchange}/{symbol}/{date}/{hh}/part-*.parquet│
 + 私有订单/成交流        │ (seq 连续性检查)   │                                               │
                         └────────────────────────────────────────────────────────────────────┘
                                                                 │
                                                                 ▼
                                              gold/features/{symbol}/{date}/features.parquet
                                              gold/labels/{symbol}/{date}/labels.parquet
                                                                 ▲
                                                                 │
                                    ┌────────────────────────┴────────────────────────────┐
                                    │  标的池漏斗 funnel（读 silver + gold + REST 元数据）    │
                                    │  CORE / WATCH / RETIRE 三档 + 滞回                 │
                                    └─────────────────────────────────────────────────────┘
```

**设计原则**

1. **bronze 不可变、silver 规范化、gold 特征化**。任何修复只发生在 silver/gold，bronze 永远保留原始字节（用于争议回溯）。
2. **一个事件 schema 贯穿两个平面**。平面 A 的文件在入库时做一次「字段补齐 + 单位归一」，落到 silver 后与平面 B 的行**结构完全一致**，因此回测与实盘用同一套特征代码（避免 `LOOKS_LEARNED` 第 5 条「回测/实盘不同源」的坑）。
3. **`source` 列区分来源**（`chd_archive` / `live_ws`），重叠时段做**交叉校验**（见 §5.6），不一致时以 `live_ws` 为准并告警。
4. **标的池是数据管道的下游，不是上游**。先有数据，再有指标，再有选品；选品结论写回 `pools.json`，驱动 recorder 的订阅集合。

---

## 2. A — 标的筛选漏斗（Symbol Selection Funnel）

### 2.0 漏斗总体形态

```
全市场符号（OKX 662 / Lighter 264 / HL-Futures 463 【实测】）
   │
 G0 域完整性 & 合约元数据可用          ──► 剔除：已下架/元数据缺失/ctVal 未知
   │
 G1 流动性门槛                        ──► 剔除：成交额 / 盘口深度不足
   │
 G2 微观结构适合度                    ──► 剔除：点差太薄、tick 太粗、消息速率过低
   │
 G3 波动率充足度                      ──► 剔除：波动不足以覆盖费用
   │
 G4 逆向选择风险                      ──► 剔除：毒性流过高（做市即送钱）
   │
 G5 库存风险承受度                    ──► 剔除：强单向趋势（库存无法自然出清）
   │
 G6 成本结构                          ──► 剔除：费率 / 资金费率 / 借贷成本吞掉价差
   │
 G7 交易所特有 & RWA/HIP-3 风险       ──► 剔除或降档：时段/赎回/除权/结算
   │
 G8 数据可得性与可回测性              ──► 降档：无可用历史 → 只能观察，不能上实盘
   │
 G9 组合层约束（相关性 / 敞口集中度）  ──► 降档：与已有持仓高度相关
   │
 ──► 评分 & 三档池（滞回迁入迁出）
```

### 2.1 完整漏斗表

> 阈值列中，`G1/G2/G3` 的默认口径针对**山寨币永续**分支；`G7` 之后对 **RWA/HIP-3 分支**有独立阈值，见 §2.6。
> 所有 `【建议起始值】` 阈值必须由 §2.7 的标定流程在 7–14 天内重算一次。

| 关卡 | 指标 | 公式 / 定义 | 阈值 | 数据依赖 | 采样频率 | 淘汰动作 |
|---|---|---|---|---|---|---|
| **G0** 域完整性 | 合约状态 | `GET /api/v5/public/instruments` → `state == "live"`；`ctVal`, `ctValCcy`, `ctType`, `settleCcy`, `listTime`, `expTime` 非空 | 全部可解析；`ctVal>0` | 交易所 REST 元数据 | 1 次/小时 + 每日全量 | 剔除（标记 `REJECTED_METADATA`） |
| | 符号生命周期 | `age = now - listTime` | `age ≥ 7d`（避免新币上/下架噪声）【建议起始值】 | 同上 | 日 | 降档至 WATCH |
| | 数据可得性 | cryptohftdata `/v1/symbols` 含该 symbol 且 `data_type=orderbook` | 存在且历史覆盖 ≥ 30 天 | cryptohftdata `/v1/symbols` | 日 | 降档至 WATCH（可实盘但不可回测 ⇒ 禁止进 CORE） |
| **G1** 流动性 | 日成交额 | `ADV_quote = mean(quote_asset_volume, 24h)`；OKX 永续该字段历史为空时用 `Σ(price×qty)` 逐笔重算 | `≥ 5,000,000 USDT/日`（CORE）/ `≥ 1,000,000`（WATCH）【建议起始值】 | ticker/trades | 1h 滚动 | < 1e6 剔除；1e6–5e6 仅 WATCH |
| | 盘口深度 | `D5 = Σ_{i=1..5} px_i×qty_i`（同侧），`D10` 同理；取当日 5 分钟采样的 **中位数** | `D5 ≥ 50,000 USDT` 且 `D10 ≥ 120,000 USDT`【建议起始值】 | orderbook（L2，必要时 50 档） | 5 分钟 | 不达标剔除 |
| | 有效深度（±10bps 带） | `D10_10bps = Σ_{levels within 10bps of mid} px×qty` | `≥ 3 × 单笔报价规模`（单笔 = `max_inventory × price`，见 §2.5）【建议起始值】 | orderbook | 5 分钟 | 不达标剔除 |
| | 点差中位数 | `spr_bps = (ask1 − bid1)/mid × 1e4`；取当日 1s 采样中位数 | `median(spr_bps) ≥ 10`（覆盖 2.5× 手续费垫）【仓库 README 铁律】 | orderbook / books5 | 1s 聚合 → 日 | 不达标剔除 |
| **G2** 微观结构 | 点差分布 | `p10 / p50 / p90`；`spread_stability = p90/p10` | `p50 ≥ 10`；`p90 ≤ 3×p50`（点差不稳定 = 流动性断裂）【建议起始值】 | orderbook | 1s → 日 | p90 过大 → 剔除 |
| | tick size | `tick = min(px_{i+1} − px_i)`（取近 7 天众数） | `tick/mid ≤ 1 bp`【建议起始值】 | 交易所 instruments + orderbook | 日 | 过大剔除（tick 太粗无法精细报价） |
| | 最小可报价价差 | `min_quote_spread = max(2×tick, 1bp)` | `min_quote_spread ≤ 0.3 × median_spr_bps`（不能被 tick 粒度吃掉） | 同上 | 日 | 不达标剔除 |
| | 消息速率（行） | `level_row_rate = 订单簿价位行数/秒`（归档与自录同口径） | `≥ 100 行/s`（CORE）/ `≥ 20`（WATCH）【建议起始值】；`【实测】` BTC 690 行/s、DOGE 92 行/s、DOGE 落在边界 → 需按 §2.7 校准 | orderbook | 1 分钟 | 过低剔除（样本不足以估微观结构） |
| | 消息速率（帧） | `frame_rate = 交易所推送帧数/秒`（**只有 live recorder 能测**，归档按行反推会低估） | `≥ 0.5 帧/s`（CORE）【建议起始值】；`【实测】` BTC ≈ 1.7 帧/s、DOGE ≈ 0.23 帧/s | live WS 帧计数 | 1 分钟 | 过低剔除 |
| | 成交稀疏度 | `trade_rate = 成交笔数/秒` | `≥ 0.2 笔/s`（CORE）【建议起始值】；`【实测】` AAPL ≈ 0.196 笔/s | trades | 1 分钟 | 过低剔除 |
| | 档位稳定性 | 每分钟 top-10 档位存活率 | `≥ 80%`【建议起始值】 | orderbook | 1 分钟 | 剔除 |
| **G3** 波动率 | Garman-Klass | `σ²_GK = 0.5·ln(H/L)² − (2ln2−1)·ln(C/O)²`（逐 5 分钟 bar），再取日内中位数 | `σ_GK(5m) ≥ 0.05%`（年化 ≈ 22%）；且 `σ_GK ≥ 1.5 × 2×MakerFee_bps`【建议起始值】 | trades / candles | 5 分钟 bar → 日 | 不足剔除（波动不够，价差赚不回时间风险） |
| | Parkinson 极值 | `σ²_P = (1/(4ln2))·ln(H/L)²` | `σ_P ≥ 0.7 × σ_GK`（两估计一致性）；`σ_P ≥ 0.04%`【建议起始值】 | trades | 5 分钟 bar → 日 | 不一致 → 数据可疑 → 剔除 |
| | 零波动占比 | `frac(σ_1min == 0)` | `≤ 20%`（静默时段太多） | trades | 1 分钟 | 超标剔除 |
| | 跳跃风险 | 单笔成交价格变动 > 3×tick 的占比 | `≤ 2%`【建议起始值】 | trades | 日 | 超标 → 降档 WATCH |
| **G4** 逆向选择 | OFI 自相关 | `ρ₁ = corr(ΔW(t), ΔW(t−1))`（Cont-Kukanov-Stoikov ΔW，仓库 `okx_ws_manager._handle_book` 已有同款实现） | `ρ₁ ≤ 0.35`【建议起始值】 | orderbook | 1 秒 tick | 过高（趋势化）→ 剔除 |
| | OFI 方向持续性 | `persistence = \|mean(sign(ΔW) over 60s)\|` | `≤ 0.25`【建议起始值】 | orderbook | 1 分钟 | 超标剔除 |
| | 毒性流占比 | VPIN（分桶成交量法，bucket = 1 分钟成交量）；或 `大单占比 = Σ(成交额 > p95 的成交) / Σ成交额` | `VPIN_mean ≤ 0.55` 且 `大单占比 ≤ 30%`【建议起始值】 | trades | 1 分钟 → 日 | 超标 → 剔除或强制单边挂单 |
| | 成交方向持续性 | `frac(consecutive same-side taker trades) − 0.5` | `≤ 0.10`【建议起始值】 | trades | 1 分钟 | 超标剔除 |
| | 冲击成本 | `冲击 = E[ \|mid(t+1s) − mid(t)\| ，条件为成交时刻 ]`（maker 视角：成交后立即对冲的滑点） | `≤ 0.4 × median_spr_bps`【建议起始值】 | orderbook + trades | 1 秒 | 超标剔除（这是「吃到毒单」的量化） |
| **G5** 库存风险 | 单边趋势率 ADX | `ADX(14)` on 5 分钟 bar（Wilder） | `ADX14 ≤ 25`（CORE）/ `≤ 32`（WATCH）【建议起始值】 | candles/trades | 5 分钟 bar | `> 32` 剔除；`25–32` WATCH |
| | Hurst 指数 | `H = DFA 斜率`（lag 16–256）或 `RS(100)`；`H>0.55` 表示持续性 | `0.35 ≤ H ≤ 0.55`【建议起始值】 | 5 分钟 bar | 日 | 越界剔除 |
| | 宏观方向暴露 | 24h 与 BTC 的相关系数（做空 BTC 方向） | `\|ρ\| ≤ 0.75`【建议起始值】 | trades | 日 | 过高 → 降档（实为方向交易而非做市） |
| **G6** 成本结构 | Maker/Taker 费率 | `GET /api/v5/account/trade-fee`（私有）或账户等级表 | `2×MakerFee ≤ 0.4×median_spr_bps`【建议起始值】 | 私有 REST / 账户配置 | 月 | 不达标剔除 |
| | 资金费率分布 | 8 小时费率 `f`；`f_p50, f_p99_abs, f_min, f_max`（近 30 天） | `\|f_p99\| ≤ 0.15%`（单期）【建议起始值】；**RWA 分支放宽到 ≤ 0.5%** | mark_price 归档 / OKX `public/funding-rate` | 1 小时 | 超标 → 剔除（费率不可预测 = 库存损益不可控） |
| | 资金费率方向一致性 | `frac(f < 0)` 与 `frac(f > 0)` | 长期单边（`frac(f>0) > 0.9`）→ 降档（做市商被迫持单边） | 同上 | 日 | 降档 WATCH |
| | Carry 贡献 | `daily_carry = f_p50 × 3`（每日 3 期） | `≥ 0`（不亏）| 同上 | 日 | 记录，不做硬门槛 |
| | 借贷利率 | RWA / HIP-3 标的的现货/永续借币利率 | `≤ 0.3%/日`【建议起始值】 | 交易所 / 借贷页面 | 日 | 超标剔除 |
| **G7** 交易所特有 | **交易时段** | 标的的撮合时段（美股 RWA：09:30–16:00 ET，周末闭市；加密永续：7×24） | 有效撮合时段 `≥ 6h/日`【建议起始值】；RWA 放宽到 `≥ 4h/日` 但**必须有 `closed` 标记** | 交易所 instrument 元数据 + 订单流（无更新时段） | 日 | 时段过短 → WATCH，且禁止跨时段持仓 |
| | 流动性断裂 | 撮合时段内 `spread/p50 > 3` 或 `msg_rate = 0` 的连续时长 | `≤ 15 分钟`【建议起始值】 | orderbook | 1 分钟 | 超标 → 剔除 |
| | 发行方 / 托管信用 | RWA 的发行方、赎回通道、赎回 T+时间 | 赎回 `≤ T+2`；有二级赎回方【定性，需人工维护清单】 | 人工/外部 | 月 | 剔除 |
| | 分红/除权 | 标的派息日 → 价格跳空 | 派息日前 **24h** 内禁止新开仓（只允许减仓）【建议起始值】 | 事件日历（人工维护） | 日 | 限制而非剔除 |
| | 结算机制 | 交割/结算时点与结算价来源 | 结算前 `2h` 禁止新开仓【建议起始值】 | 交易所公告 | 日 | 限制 |
| | 指数/预言机依赖 | 指数价来源（多源 vs 单一 CEX） | 单一来源 → 降档 | 交易所文档 | 月 | 降档 |
| **G8** 数据可得性 | 历史分片覆盖 | cryptohftdata 该 symbol 的 `orderbook`/`trades` 小时分片覆盖天数 | `≥ 30 天` 且缺口率 `≤ 5%`【建议起始值】 | cryptohftdata | 日 | 降档 WATCH |
| | 回放一致性 | 自录与归档重叠 24h 的 mid/价差比对 | `\|Δmid\| ≤ 2 tick`，价差 `Δ ≤ 20%`【建议起始值】 | silver 双源 | 日 | 数据管线告警，不影响选品 |
| **G9** 组合层 | 与现有池的相关性 | `\|ρ(1min returns)\| ≤ 0.6` 对任一已在池标的 | 否则不同时进 CORE | silver | 周 | 降档 |
| | 交易所集中度 | 单一交易所 CORE 标的名义占比 | `≤ 40%` | 池配置 | 日 | 降档 |
| | 资金占用 | `CORE` 单标的最大保证金占比 | `≤ 25%`（对齐 `LESSONS_LEARNED` 的保证金纪律）| 账户状态 | 实时 | 强制降档 |

### 2.2 关键公式补全

**OFI（Cont-Kukanov-Stoikov，与仓库 `live_cluster/okx_ws_manager.py:_handle_book` 完全一致，勿重写）**

```
ΔW_b =  v_b1        if b1(t) > b1(t−1)
        v_b1 − v_prev_b1   if b1(t) = b1(t−1)
        −v_prev_b1   if b1(t) < b1(t−1)
ΔW_a = −v_prev_a1   if a1(t) > a1(t−1)
        v_a1 − v_prev_a1   if a1(t) = a1(t−1)
        v_a1         if a1(t) < a1(t−1)
OFI  = Σ (ΔW_b − ΔW_a)      # 本文档按 1 秒窗聚合
```

**深度指标必须按「挂单金额」而非「挂单数量」**
```
D_k = Σ_{i=1..k} px_i × qty_i      （同一侧，qty 已乘 ctVal 归一到 base 币）
```

**冲击成本（maker 视角的核心指标，比 VPIN 更贴近真实盈亏）**
```
对每笔 maker 成交 c（时刻 t）：
   Impact(c) = |mid(t+Δ) − mid(t)|,  Δ = 1s
   扣除价差收益后净收益 = spread_captured − Impact(c) − fees
G4 的「冲击成本」门槛即为：mean(Impact) ≤ 0.4 × median_spr_bps
```

**资金费率口径**
```
f        = 每 8 小时费率（小数，0.0001 = 0.01%）
carry_8h = f × 库存名义
日 carry = 3 × f × 名义
极端值   = max(|f|) over 30d，以及 f 的 1% / 99% 分位
```
`【实测】` DOGE-USDT-SWAP 当前 `fundingRate = −0.0000253159…`，`min/maxFundingRate = ±0.0075`，
`interestRate = 0.0001`，`premium = −0.000879` → 负费率意味着**空头付多头**，是做市商库存天然偏空的理由之一。

### 2.3 评分与分档（从「通过/淘汰」到「排序」）

通过全部硬门槛的候选按加权分排序：

```
Score = 0.30·norm(median_spr_bps)
      + 0.20·norm(ADV_quote)
      + 0.15·norm(D10)
      + 0.15·norm(−VPIN_mean)
      + 0.10·norm(σ_GK)
      + 0.10·norm(−ρ₁)
```
`norm(x) = percentile_rank(x)`（在当批候选内归一，**不做跨批绝对化**，避免行情漂移导致分档抖动）。

### 2.4 三档池定义与滞回（防抖动）

| 池 | 准入条件 | 作用 | 采集资源 |
|---|---|---|---|
| **CORE 做市池** | 通过 G0–G9 全部硬门槛；`Score` 在候选前 30%；且连续 **2 个评估周期**（默认 24h）达标 | 实盘挂单 + 全量 L2 记录 | 全量 orderbook + trades + funding + OI + 私有订单流 |
| **WATCH 观察池** | 通过 G0/G8；未达 CORE 硬门槛（差 1 项）或 Score 后 30%；或从 CORE 掉下来未满冷却期 | 只记录不交易；用于训练数据积累与升级候选 | 中频采样（orderbook 5s 快照 + trades 全量 + ticker/mark） |
| **RETIRE 淘汰池** | 任一硬门槛失败且连续 **2 个周期**失败；或 `G0` 元数据失效（退市/下架）；或 `G9` 组合约束冲突 | 停止采集，保留历史 | 仅保留 bronze，不新增采集 |

**滞回（hysteresis）机制 —— 防止标的在边界反复横跳**

```
升级（→CORE）：需连续 N_up = 2 个评估周期全部硬门槛达标
降级（CORE→WATCH）：需连续 N_down = 3 个周期中至少 2 个周期不达标
                 或单次触发「致命门槛」（G0 元数据失效 / 单次成交额 < ADV 的 20%）
彻底淘汰（→RETIRE）：需连续 N_retire = 3 个周期不达标 + 冷却期 N_cool = 7 天
冷却期内禁止重新升级（除非硬性指标恢复至 >120% 阈值）
```

**评估周期**：CORE 24h；WATCH 6h；RETIRE 24h。
**评估窗口**：CORE 用滚动 24h；WATCH 用滚动 7 日（避免单日噪声）。**两套窗口的指标不可直接比较**，因此升级/降级使用各自窗口的阈值。

### 2.5 标的池如何反哺做市参数（本仓库已有能力）

进入 CORE 的标的，把漏斗指标直接喂给 A-S 引擎：

```
min_spread_bps = max( 2×maker_fee_bps×2.5,              # README 铁律：2.5× 手续费垫
                     median_spr_bps × 0.5,              # 不超过市场中位价差的一半，否则挂不上
                     4.0 + 20×σ_GK_bps )               # 波动保护
max_inventory  = min( 账户档位上限,  D10_10bps / (5 × px) )   # 深度能吸收的库存
gamma          = f(VPIN_mean, ρ₁)                     # 毒性高 → 风险厌恶高
```
**注意仓库内存在一处口径冲突，必须在本次改动中收敛**：
`README.md` 写死「总报价价差 ≥ 10 bps」，而 `live_cluster/as_dynamic_risk.py` 的 `min_spread_bps` 为 3.0–4.5（半价差口径，总价差 6–9 bps）。
建议：以**费率感知的公式**为准（`min_total_spread_bps = 2×maker_fee_bps + 逆向选择估计 + 2×tick_bps`），
在 `as_dynamic_risk.py` 中把 `min_spread_bps` 改为从漏斗配置读取，并在 `README` 补一条口径说明。

### 2.6 RWA / HIP-3 的独立漏斗分支（与山寨币的差异表）

| 维度 | 山寨币永续 | RWA / HIP-3（代币化股票、商品、FX） |
|---|---|---|
| 交易时段 | 7×24 | **有撮合时段**：美股 RWA 跟随美东 09:30–16:00，周末/节假日闭市；HIP-3 的 `CASH:`/`FLX:` 各自有独立时段。**闭市期间必须停止挂单**（否则价差无限大、盘口是假的） |
| 标的生命周期 | 长（数年） | **短且动态**：HIP-3 每次新建 dex 就是新前缀（`XYZ:` / `CASH:` / `FLX:`）；RWA 可能随时发行/赎回/下架 → 每日重建符号注册表 |
| 流动性 | 充足（`【实测】` DOGE 24h ≈ 1.82e8 USDT） | **薄而贵**（`【实测】` OKX `AAPL-USDT-SWAP` 24h ≈ 9.93e6 USDT 尚可，但点差仅 0.281 bps ≪ 4 bps 往返成本，且仅 704 笔/小时）→ 点差赚不到钱，只能靠 funding carry 与事件驱动 |
| 事件驱动 | 相对低频 | **高**：分红除权（价格跳空，做市商被瞬间打穿）、赎回窗口、发行方信用事件、指数成分调整、宏观数据（CPI/FOMC） |
| 结算机制 | 永续无到期 | 到期/结算价机制不同，结算前流动性形态变化 |
| 波动率来源 | 全天候噪声 | **有休眠期**，波动集中在开/收盘 ±15 分钟；G3 的 σ 统计必须按「有效时段」而非自然日切分 |
| 资金费率 | 与现货 basis 挂钩 | 与**标的股息率 / 融资成本**挂钩（RWA 的 funding 常被正确定价到年化股息率水平），极端值尾部更厚 |
| 库存风险 | 单边趋势（ADX） | **跳空风险**（除权/停牌/赎回暂停）→ ADX 不足以刻画，必须额外加 `gap_risk` 指标：过去 30 天日内最大跳空幅度 |
| 监控要求 | 常规 | 额外需要：**事件日历订阅**（派息/赎回/指数调整）、**时段感知**的挂单开关、**发行人/托管**信息人工维护 |

**RWA 分支的具体阈值覆盖（覆盖 G1/G2/G3/G4 的默认值）** `【建议起始值，需按实测校准】`

| 关卡 | RWA/HIP-3 阈值 | 理由 |
|---|---|---|
| G1 日成交额 | `≥ 1,000,000 USDT/日`（CORE）/ `≥ 200,000`（WATCH） | `【实测】` OKX `AAPL-USDT-SWAP` 24h ≈ 993 万 USDT，可达标；但 **成交笔数**（704 笔/小时）远不达标 → 见 G2 |
| G1 深度 | `D5 ≥ 20,000`、`D10 ≥ 50,000` | 同上 |
| G2 点差 | **不作为通过条件**，改为**收益来源判定**：`carry + 事件收益 > 2×费率` | `【实测】` RWA 点差 0.281 bps ≪ 4 bps 往返成本，吃价差必亏 |
| G2 消息速率 | `≥ 20 行/s`，`≥ 0.05 帧/s`，`≥ 0.1 笔/s` | RWA 天然稀疏（`【实测】` AAPL 0.196 笔/s） |
| G2 成交笔数 | `≥ 30 笔/小时` | 低于此值无法估计滑点与毒性分布，`【建议起始值】` |
| G3 波动率 | 按**有效时段**统计：`σ_GK(有效时段内 5m) ≥ 0.08%`；同时 `时段外 σ` 不参与统计 | 休眠期零波动会污染统计 |
| G4 逆向选择 | **改用事件驱动指标**：`gap_risk = max 日内跳空/ATR`，`≤ 3×ATR`；`派息日前后 24h 内不评 G4` | 毒性不再是逐笔的，而是事件级的 |
| G6 资金费率 | `\|f_p99\| ≤ 0.5%`；`carry_p50 × 3 ≥ 0.05%/日` 才算合格 | RWA 的持有收益主要来自 carry |
| G7 时段 | 有效撮合 `≥ 4h/日`，**且必须实现时段门控**（时段外强制撤单） | 硬要求 |
| G7 跳空 | `gap_risk ≤ 3×ATR`，且已把派息日纳入禁开仓日历 | 硬要求 |

### 2.7 阈值标定流程（必须做，否则阈值就是玄学）

1. **采集**：用 §3 管线对**全量候选**（非仅 CORE）连续采集 14 天 silver 数据（建议 3–5 个交易所 × 100–300 个标的，orderbook 只留 5 分钟抽样以控成本）。
2. **回放**：用归档 + 自录数据重放 A-S 做市器，逐标的计算**理论净收益率** `net_bps_per_fill = spread_captured − 2×fee − impact`。
3. **标定**：把漏斗指标的横截面（分位数）与 `net_bps_per_fill` 做单调性检验（Spearman ρ）：
   - 对每个指标，若 ρ < 0.2 说明该指标无判别力 → 从漏斗剔除或改阈值方向；
   - 若存在非单调关系（例如点差在 40 bps 后反而收益下降，因流动性太差）→ 阈值应取**区间**而非单点。
4. **固化**：把标定结果写回 `datapipe/config.py` 的阈值表，并记录标定日期与样本区间（`【实测】` 标记 + 日期）。

### 2.8 人工必须维护的清单（无法自动化）

| 清单 | 内容 | 更新频率 |
|---|---|---|
| `asset_class_map` | symbol → {RWA/DEX-EQUITY/COMMODITY/FX/CRYPTO} | 周 |
| `trading_sessions` | symbol → 撮合时段（含节假日日历） | 月 + 事件推送 |
| `corporate_actions` | symbol → 派息日/除权日/赎回窗口/指数调整 | 事件驱动 |
| `issuer_credit` | RWA → 发行方、托管方、赎回 T+N、赎回方 | 月 |
| `fee_schedule` | 账户等级 → maker/taker/借贷费率 | 变更事件 |

---

## 3. B — 微观数据采集管线

### 3.1 采集方式对比表

| 维度 | cryptohftdata 历史归档 | 交易所原生 WS 自录 | **建议** |
|---|---|---|---|
| 时间覆盖 | 历史（2025-06-28 起）+ 约 15 分钟滞后 | **仅从现在开始** | 归档做**回测训练**，自录做**实盘权威** |
| 延迟 | 小时级（准实时） | **ms 级** | 两者都要 |
| 单位/schema | 已统一（§0.2），但**有 venue 陷阱**（ctVal/百分比/聚合成交） | 各所原生，**必须自己归一** | 归一逻辑必须写两遍（→ 见 §5.7 双源交叉校验） |
| 带宽 | 归档下载：一次性批量，无实时带宽压力 | **实时占用**：见 §3.3 预算 | 自录是主要带宽消耗 |
| 存储 | 全量 L2 归档体积大；可按需只拉 CORE/WATCH | 只存自己订阅的标的 | 自录只订 CORE+WATCH（≤ 30 个标的） |
| 成本 | 免费档 60 req/min（限流明显）；免费账号 JWT 无限速；S3 直连需临时凭证 | 零 API 成本，付 VPS 带宽与磁盘 | **归档走 JWT（4h 刷新）**，不要匿名 |
| 覆盖 RWA/HIP-3 | **有**（`【实测】` OKX `AAPL-USDT-SWAP`、HL `XYZ:*`/`CASH:*`/`FLX:*` 都在归档里） | 需自己按 venue 订阅 | 归档是唯一能回测 RWA 历史的方式 |
| 序列号完整性 | 提供 `prev_final_update_id`，**已做链式校验**，且每小时回放校验 | 需要自己实现 | 归档阶段信任它；自录阶段必须自建校验 |
| 撮合回放 | **不可用**（只有公开行情，无自己的订单流） | **可用**（私有订单/成交流 + 自己的下单回报） | 精确回测撮合**只能靠自录** |
| 适用阶段 | Phase 1（模型研发/回测） | Phase 2（实盘/影子） | 两阶段并行 |

### 3.2 cryptohftdata 接入设计

**调用序列**

```
① POST /v1/jwt-token      (X-API-Key)            → jwt_token（4h 有效）
   进程内缓存 jwt + 本地 monotonic 过期时间；过期前 10 分钟刷新
② GET  /v1/symbols?exchange=<ex>&data_type=<dt> → 符号全集（含历史退市标的）
   结果缓存到 local SQLite/JSON，按 (exchange, data_type) 做 mtime 缓存，TTL 6h
③ GET  /v1/status                                  → target.prefix / target.lookback_hours
   用于确定「哪些小时已经可拉」
④ GET  /v1/download?file={ex}/{date}/{hh}/{symbol}_{dt}.parquet
   → 302 → 跟随重定向 → S3 文件
```

**增量同步算法（可拉哪些新分片）**

```
now        = utcnow()
target     = GET /v1/status
last_hh    = parse(target.prefix)          # 例 "2026-11-14/11"
lookback   = target.lookback_hours         # 【实测】= 2，表示状态覆盖最近 N 小时

候选小时窗口 = [last_hh - lookback, last_hh]   # 保守多拉 1 小时，代价 = 少量 404
对窗口内每个小时 hh:
    对每个 (exchange, symbol, data_type):
        key = f"{exchange}/{hh.date}/{hh.hour}/{symbol}_{data_type}.parquet"
        若 local_manifest[key].state == "done" 且 mtime 未变 → 跳过
        否则下载
```

**去重与幂等**

| 层级 | 键 | 处理 |
|---|---|---|
| 文件级 | `key = {exchange}/{date}/{hh}/{symbol}_{dt}` | 本地 manifest 表 `files(key PK, sha256, bytes, rows, downloaded_at, state)`。**官方对已发布文件会原地替换修正**（`【实测】` 官方文档：修正后的文件占用同一 key）→ 因此必须记录 `sha256`，定期（如每周）对近 30 天文件重校验，发现 hash 变化则**重下并重新入库 silver** |
| 行级（trades） | `(exchange, symbol, trade_id, trade_time)` | Bybit 重连回填、HL 重放、Lighter 二次投递会造成重复行 → 按上述键去重（官方已对 Lighter/HL 做过修正，但**新旧数据都可能有残留**） |
| 行级（orderbook） | 按 `(received_time, final_update_id)` 保序重放，**不要只按 event_time 排序**（官方明确要求：Binance 老文件含重复快照副本） | 官方文档要求"按发布消息顺序 + 原生序列 ID 重放" |

**缺口检测（三层）**

```
L1 文件级：期望小时 × (symbol, data_type) 笛卡尔积，与 manifest 中 "done" 集合求差 → 缺失文件
L2 序列级：orderbook 相邻行的 prev_final_update_id ≠ 上一行 final_update_id → 缺口
   （Lighter 用 nonce/begin_nonce；Hyperliquid 无序列号 → 只能靠时间连续性）
L3 时间级：同一 symbol 的 trades 按 trade_time 排序后，最大相邻间隔 > 60s → 疑似的采集空洞
```

**自动修复动作**

| 缺口类型 | 修复动作 |
|---|---|
| L1 缺文件（该小时已过发布延迟 15 分钟 + 10 分钟余量） | ① 重试下载 3 次（指数退避 2/4/8s）② 仍 404 → 标记 `MISSING`，写入 `gaps.csv`，**从评估窗口中剔除该小时**（不因数据缺失惩罚标的）③ 若连续 3 小时缺失 → 标的降档 WATCH 并告警 |
| L2 序列缺口 | 归档侧无法修复（官方已做重锚）；在 silver 层标记 `GAP` 并从该 gap 到下一个 snapshot 之间的盘口置为不可用；训练样本丢弃该窗口 |
| L3 时间空洞 | 同上 |

**限流处理**

```
免费档：60 req/min/IP → 客户端自限流到 50 req/min（留 20% 余量）
账号档：JWT 无限速，但仍加并发上限 8 + 令牌桶（避免把自己打挂）
429：读 Retry-After；若缺失则退避 30s * 2^n
5xx：退避重试 3 次；连续 5 次失败 → 告警并跳过该交易所 1 小时
```

### 3.3 交易所自录设计

**订阅矩阵**

| 交易所 | 通道 | 深度/频率 | 归一化要点 |
|---|---|---|---|
| OKX | `books`（公共） | 400 档，100ms 增量 | `seqId`/`prevSeqId` 链式；快照 `prevSeqId=-1`；数量单位 = **张**（×`ctVal`） |
| OKX | `books5` | 5 档快照，100ms | 作为「轻量监控流」，与 `books` 二选一 |
| OKX | `trades-all`（**business** WS） | 逐 fill | 走 `wss://ws.okx.com:8443/ws/v5/business`，需登录；聚合版 `trades` 会丢失逐笔信息 |
| OKX | `tickers` | 1s | 24h 统计；`volCcy24h` 才有意义 |
| OKX | `mark-price` / `funding-rate` / `open-interest` | 3s / 30s / 3s | `funding-rate` 给 `fundingRate/fundingTime/nextFundingTime/min/maxFundingRate` |
| OKX | `liquidation-orders` | `instType=SWAP` 一次覆盖全部 | 强平流是毒性尖峰的先行指标 |
| OKX | 私有 `orders` / `account` | 实时 | **只认 `state ∈ {filled, partially_filled}` 且 `fillSz>0`**（`LESSONS_LEARNED` 第 2 条铁律） |
| Lighter | `order_book/<market_id>` | 快照 + 增量 | `nonce`/`begin_nonce` 链；`offset` 不连续不可用于缺口；`last_updated_at`（µs）→ `transaction_time` |
| Lighter | `trade/<market_id>` | 逐笔 | 一帧多笔 → 展开多行；含 `maker_fee`、`is_maker_ask` |
| Lighter | `market_stats/all` | 市场统计 | 资金费率/标记价/OI 汇总通道；只有活跃市场才有行 |
| Hyperliquid | `l2Book` | **全量快照** | 无增量 → 本地 diff 生成 delta；`HIP-3` 需按 dex 订阅，`symbol` 带 `XYZ:` 前缀 |
| Hyperliquid | `trades` | 逐笔 | `tid` 不可用于去重序列（哈希）→ 用 `(coin, tid, time)` |
| Hyperliquid | `activeAssetCtx` | 持仓/资金费率/标记价 | 需 `dex` 参数 |

**落地为可回放的增量事件流**

```
交易所原始帧
   │ ① 帧级解析（保留原始 JSON 文本 → bronze/raw，压缩）
   ▼
规范化事件（统一 schema，§3.4）
   │ ② 序号化：给每条订单簿事件分配本地单调 seq（用于本地日志重放定位）
   ▼
writer 队列 → 按 (symbol, hour) 分桶 → 满 N 行或 T 秒 flush → bronze/live/*.parquet
   │ ③ 增量更新：同 (symbol, hour, data_type) 已存在 → 读出 → append → 重写
   ▼
silver（与归档同 schema）→ gold（特征）
```

**Bronze 写入策略（1 核 1G VPS 可承受）**

```
缓冲：内存 5,000 行 / 每 symbol 一个队列；内存上限 200 MB（硬上限，超出丢弃最旧并计数）
落盘：每 10 秒 或 每 20,000 行 flush 一次 → parquet
分区：live/{exchange}/{symbol}/{date}/{hh}/part-{seq}.parquet
压缩：ZSTD level 3（实测 orderbook 归档 zstd 后约 9.3 bytes/行，
      而原始 JSON 每价位约 60+ bytes → 6–8× 压缩比【实测】）
```
**不做的事**：不引入 Kafka / Flink / Redis。1 核 1G 上进程内 `queue.Queue` + 文件缓冲即可；进程之间用**文件 + SQLite** 传递。

### 3.4 统一事件 Schema（silver 层 Parquet 表结构）

**通用公共列（所有数据类型共享）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `received_time` | int64 | 本地接收时刻（ns，monotonic 校准后转 epoch） |
| `event_time` | int64 | 交易所时刻，**统一归一为纳秒**（归档源需按 venue 乘 1e6/1e3） |
| `transaction_time` | int64? | 交易所事务时刻（ns） |
| `local_seq` | int64 | **本地单调递增序号**，用于本机日志的精确重放定位（不回传交易所） |
| `exchange` | dictionary\<string\> | `okx` / `lighter` / `hyperliquid` / `chd_<venue>` |
| `symbol` | dictionary\<string\> | 统一符号（`BTC-USDT-SWAP` / `BTC` / `xyz:AAPL`） |
| `market_type` | dictionary\<string\> | `swap` / `spot` / `perp` / `hip3` / `rwa` |
| `data_type` | dictionary\<string\> | `orderbook` / `trades` / `ticker` / `mark_price` / `open_interest` / `liquidations` |
| `source` | dictionary\<string\> | `live_ws` / `chd_archive` |
| `event_type` | dictionary\<string\> | `snapshot` / `update` / `trade` / `fill` … |
| `seq_first` | int64? | 链首 ID（venue 语义，已归一为「同一命名空间内的整数」） |
| `seq_last` | int64? | 链尾 ID |
| `seq_prev` | int64? | 链尾的上一个 ID → **缺口检测唯一依据** |
| `seq_ns` | dictionary\<string\> | 序列号命名空间：`"okx_seqid"` / `"lighter_nonce"` / `"none"`（HL） |
| `gap_before` | bool | 本行之前是否检测到缺口（为 true 的行不可用于盘口重建） |

**订单簿表 `silver/orderbook`**（粒度：一行 = 一个价位 × 一条事件）

| 字段 | 类型 | 说明 |
|---|---|---|
| `side` | dictionary | `bid` / `ask` |
| `price` | decimal(38,12) / string | **原始字符串保留在 `price_raw`**；`price` 为数值列便于计算 |
| `price_raw` | string | 交易所原始字符串（精度无损） |
| `quantity` | decimal(38,12) | **已乘 `ctVal` 归一到 base 币** |
| `quantity_raw` | string | 原始数量（张 / 原始单位） |
| `order_count` | int64? | 该价位订单数 |
| `notional` | decimal(38,12) | `price × quantity`（**已归一为 USD/USDT 计价**，深度指标直接用） |
| `action` | dictionary | `snapshot` / `add` / `modify` / `delete`（archive 源从 qty=0 推断；live 源由 venue 原生语义给出） |

**成交表 `silver/trades`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `trade_id` | int64 | venue 成交 ID |
| `price` / `price_raw` | decimal / string | 成交价 |
| `quantity` / `quantity_raw` | decimal / string | **已归一 base 币**（OKX ×ctVal；BitMEX ×乘数） |
| `notional` | decimal | `price × quantity` |
| `side` | dictionary | `buy` / `sell`（**主动方方向**） |
| `is_buyer_maker` | bool | 与 `side` 互为校验（`is_buyer_maker=true` ⇒ 主动方是卖） |
| `order_type` | dictionary? | `LIMIT` / `MARKET` / null |
| `liquidation` | bool | 是否强平 |

**行情/衍生表**

`silver/ticker`：`last_price, high_24h, low_24h, base_volume, quote_volume, open_24h, trades_24h, price_change_percent`
`silver/mark_price`：`mark_price, index_price, estimated_settle_price, funding_rate, next_funding_time, funding_interval_sec`
`silver/open_interest`：`oi_qty, oi_value, timestamp`
`silver/liquidations`：`price, quantity, side, is_buyer_maker`

**自有交易表 `silver/own_orders`**（**精确回放撮合的关键**）

| 字段 | 类型 | 说明 |
|---|---|---|
| `client_order_id` | string | 我方 clOrdId（唯一） |
| `exchange_order_id` | string? | 交易所 ordId |
| `symbol` | string | |
| `side` | dictionary | `buy` / `sell` |
| `order_type` | dictionary | `post_only` / `limit` / `market` |
| `price` | decimal? | 委托价 |
| `quantity` | decimal | 委托量（已归一） |
| `filled_quantity` | decimal | 累计成交 |
| `avg_fill_price` | decimal? | 均价 |
| `status` | dictionary | `live` / `partially_filled` / `filled` / `canceled` / `rejected` |
| `ts_sent` | int64 | **下单时刻（本地 ns）** |
| `ts_exchange_ack` | int64? | 交易所确认时刻 |
| `ts_filled` | int64? | 成交时刻 |
| `ts_cancel_sent` | int64? | **撤单时刻** |
| `ts_canceled` | int64? | 撤单确认 |
| `reject_reason` | string? | |
| `fee_paid` | decimal? | 实付手续费 |
| `fee_currency` | string? | |
| `client_seq` | int64 | 本地单调序号（保证下单/撤单/成交的**严格因果序**） |

> **回放撮合的正确性依赖**：① `client_seq` 全序；② 撤单有 `ts_cancel_sent`（发起）与 `ts_canceled`（确认）两个时刻；③ 成交有 `ts_filled`；④ 用**交易所事件时间**而非本地时间做因果判断（本地时间会被网络抖动打乱）。
> 这张表是本仓库 `LESSONS_LEARNED` 第 2 条（虚假流水）的根治方案：**只有它能证明成交真实发生**。

**分区与压缩**

```
分区键：data_type / exchange / symbol / date(=YYYYMMDD) / hour(=HH)
        → 目录形式 hive-style，避免 Parquet 单文件多分区带来的小文件问题
压缩：ZSTD level 3
排序：不强制全局排序（代价高），只在 row group 内保持写入序（= 交易所发布序）
```

### 3.5 存储与分层

| 层 | 内容 | 介质 | 保留 | 格式 |
|---|---|---|---|---|
| **bronze** | 归档原文件 + 自录原始帧 | NVMe SSD | 归档文件永久（冷备）；自录原始帧 3 天 | Parquet(zstd) / 原始 JSONL.gz |
| **silver** | 统一事件（可回放） | NVMe SSD（热）→ HDD（温） | 热 7 天 / 温 90 天 / 冷 永久 | Parquet(zstd) |
| **gold** | 特征 + 标签 | NVMe | 永久 | Parquet(zstd) |

**推荐参数** `【建议起始值，需按实测校准】`

| 参数 | 值 | 依据 |
|---|---|---|
| Parquet row-group 大小 | **64–128 MB**（未压缩计） | <64MB → 元数据开销与并行读取粒度变差；>256MB → 单行组解码内存峰值过高（1 核 1G 机器尤其致命） |
| 目标文件大小 | **256 MB – 1 GB** | 单文件 >1GB 时 pyarrow 单线程解码内存压力大；<64MB 时 S3/文件系统小文件问题 |
| 写缓冲 | 每分区 64 MB 或 60 秒 | |
| flush 时机 | 行数 > 1,000,000 或 时间 > 60s 或内存 > 200MB | 1 核 1G：内存上限优先 |
| 压缩 | ZSTD level 3 | `【实测】` 归档 orderbook 3.08MB / 330,226 行 ≈ **9.3 bytes/行**（zstd 后） |
| 分区键 | `data_type/exchange/symbol/date/hour` | 单分区目标 100MB–1GB：太小则文件碎，太大则扫描成本高 |
| 去重 | 见 §3.2 | |
| 冷存 | `zstd -19` 单文件 + tar 分卷（每卷 4GB） | 冷数据读取频率低，换压缩比 |

**实测存储基线（`【实测】`，2026-11-14，OKX 永续）**

| 数据 | 1 小时行数 | 1 小时压缩后大小 | 折算 |
|---|---|---|---|
| `BTC-USDT-SWAP` trades | 125,937 | 1.45 MB | ≈ 35 MB/天/标的 |
| `BTC-USDT-SWAP` orderbook（400 档增量） | 2,483,801 | 9.98 MB | ≈ **240 MB/天/标的** |
| `DOGE-USDT-SWAP` orderbook（400 档增量） | 330,226 | 3.08 MB | ≈ **74 MB/天/标的** |
| `AAPL-USDT-SWAP` trades | 704 | 13 KB | ≈ 0.3 MB/天/标的（RWA 稀疏度对照） |

> 压缩比参考：400 档原始 JSON 帧约 28 KB/帧，zstd+parquet 后归档约 **9.3 bytes/行**（`【实测】`），压缩比 ≈ 6–8×。

**1 核 1G VPS 的磁盘预算（`【建议起始值】`）**

```
磁盘 40 GB，保留 15% 系统余量 → 可用 ~32 GB
  bronze 自录解析事件（3 天）       : 3 GB   （原始帧只按 §4.2 的取证规则抽样）
  silver 热区（7 天，10 标的）     : 10 GB   （按 10 标的 × 140MB/天 ≈ 1.4 GB/天）
  silver 温区（90 天归档，按压缩）  : 12 GB
  gold 特征                        : 2 GB
  预留                             : 3 GB
```
> 结论：**单 VPS 只能承载 ≤ 10 个标的的全量 L2 自录**。更大规模必须：(a) 降低深度（`books5` 或 5 分钟抽样）；(b) 只对 CORE 存全量、WATCH 存抽样；(c) 把归档同步到对象存储而非本地。

### 3.6 数据质量闸门（自动检查 + 告警 + 修复）

| # | 闸门 | 检查方法 | 告警阈值 | 自动修复 |
|---|---|---|---|---|
| Q1 | 时间戳连续性 | 相邻 `received_time` 差值的 P99 | `> 1s` 持续 5 分钟（且 `msg_rate` 未同步下降）→ **疑似本地阻塞** | 无（记录并告警，检查 GC/磁盘 IO） |
| Q2 | 事件时间倒退 | `event_time` 单调性 | 出现倒退 `> 1 tick` → WARN；`> 1s` → ERROR | 排序时按 `(seq_last, received_time)` 而非纯 `event_time` |
| Q3 | 序列号跳变 | `seq_prev != 上一行 seq_last` | 出现即 WARN；`> 5 次/分钟` → ERROR | 标记 `gap_before=true`；向交易所请求新快照（OKX: 重订阅 `books` 触发快照；Lighter: 重连触发 `subscribed/order_book`） |
| Q4 | 盘口可重建校验 | 用 (snapshot + delta) 重放，检查：① 交叉盘 `best_bid ≥ best_ask` ② 负数量 ③ 单调性破坏 | 交叉盘 `> 0` → ERROR | 丢弃该 symbol 当前小时；重锚到下一快照 |
| Q5 | 中间价与官方 ticker 交叉校验 | `mid(t)`（自录）与 `last_price`（ticker 通道）/ `mid`（归档）比对 | `\|Δmid\| > 2×tick` 且持续 10 秒 → WARN | 检查是否单位/精度错误（如 OKX ctVal 未乘） |
| Q6 | 数量单位一致性 | `notional` 的量级 vs ticker `quote_volume` | 比值不在 `[0.5, 2]` → ERROR（典型的 ctVal 漏乘） | 阻断入库并告警 |
| Q7 | 行数合理性 | 每小时行数 vs 近 7 日同 symbol 的中位数 | 偏离 `[0.3×, 3×]` → WARN | 标记该小时 `PARTIAL`，评估窗口剔除 |
| Q8 | 重复行 | `trades` 按 `(symbol, trade_id, trade_time)` 去重后计数 | 重复率 `> 1%` → WARN | 去重（保留 `live_ws` 优先） |
| Q9 | 落盘完整性 | 已 flush 的 parquet 可读、行数与计数一致 | 任一不一致 → ERROR | 重写该 part 文件（保留 `.tmp` → 原子 rename） |
| Q10 | 磁盘水位 | `df` 使用率 | `> 75%` → WARN（开始清理 bronze 原始帧）；`> 88%` → ERROR（停止非核心采集、拒绝新标的） | 自动清理 bronze（>3 天）与临时文件 |
| Q11 | 采集器存活 | 心跳文件 mtime | `> 60s` 未更新 → ERROR | supervisor 5s 内重启 |
| Q12 | 双源一致 | `live_ws` vs `chd_archive` 重叠期 mid/价差/成交数比对 | 价差相对偏差 `> 20%` 或成交数偏差 `> 30%` → WARN | 记录 `source_discrepancy.csv`，人工裁定 |

**告警落地（1 核 1G，无 Prometheus）**
```
每个采集器写一个 /var/run/asgrid/health/{collector}.json（原子写）：
  {"ts":..., "alive":true, "msgs":N, "dropped":N, "p50_ms":..., "p99_ms":...,
   "seq_gaps":N, "disk_pct":..., "symbols":{...}}
一个 cron（每 60s）读取全部 health 文件 → 判定规则 → Telegram 推送（复用 cron_hot_monitor.py 的推送逻辑）
```
> 复用点：`live_cluster/cron_hot_monitor.py` 已有 Telegram 推送实现，但**它把 API Key 与 Telegram Token 硬编码在源码里**（`【实测】` 见该文件第 40–43 行），本次改动必须迁移到环境变量/`config.env`（凭据泄漏面最小化）。

### 3.7 多交易所对齐与时钟同步

**三种时间语义（必须全程区分，绝不可混用）**

| 时间 | 来源 | 用途 | 存储 |
|---|---|---|---|
| `event_time` | 交易所打的时间戳 | **因果顺序、跨所对齐、特征计算** | 归一为 ns |
| `received_time` | 本地收到帧的时刻 | **延迟建模、采集质量** | ns |
| `local_time` | 本地墙上时钟 | 仅用于日志与墙钟对齐 | ns（同时记录 monotonic） |

**时钟同步策略**
```
主机：chrony（不是 ntpd）—— chrony 对抖动/网络抖动的适应更好，且支持 `rtcsync`
配置：
  server ntp.pool.org iburst
  makestep 1.0 3          # 启动 3 次快速校正
  rtcsync               # 内核 1ms 时间戳（支持 SO_TIMESTAMPING）
采集器：
  每帧记录 CLOCK_REALTIME（ns）与 CLOCK_MONOTONIC（ns）两条
  定期（每 60s）计算 offset = realtime - monotonic（检测本地时钟跳变 → 记录 "clock_jump" 事件）
  帧时间戳优先用 SO_TIMESTAMPING（内核时间戳，绕过用户态延迟），退化到 time.time()
```

**跨交易所事件时间对齐方案**

1. **主时钟选择**：跨所研究以**各交易所自己的 `event_time`** 为主轴（它们都锚定各自的撮合引擎），用 `received_time − event_time` 估计「本机看到的到达延迟」。**不要用本地接收时间做跨所对齐**（各路径长度不同，误差可达几十 ms，会污染 lead-lag 估计）。
2. **统一网格**：以 1 ms 为最小对齐单位构建「事件时间轴」；对每个交易所，取 `event_time` 落在 `[t, t+Δ)` 的所有事件聚成一桶。`Δ` 建议 1ms（跨所套利研究）/ 100ms（微观结构特征）【建议起始值】。
3. **两阶段对齐**：
   - **粗对齐**：用同时段的 1 分钟收益计算跨所 **lead-lag 回归**（`r_A(t) ~ β·r_B(t−k)`，k ∈ [−50ms, +50ms]），得到每个交易所对的**系统偏移** `Δ̂_AB`（含网络路径差 + 撮合引擎差）。
   - **细对齐**：把 `Δ̂_AB` 作为初值，用高频互相关（cross-correlation）在 ±10ms 内精修，得到 `δ_AB`。
   - **应用**：`t_A_aligned = t_A − δ_AB`，对齐后重建统一的「同时刻盘口」，再计算价差与套利机会。
4. **对齐质量指标**：对齐后应满足
   ```
   |mid_A(t) − mid_B(t)| / mid  ≤ 中位点差 + 3×tick   （否则说明对齐错了或存在真实价差）
   领先性稳定：跨日重算的 δ_AB 的标准差 ≤ 2ms
   ```
   超过 → 告警（可能某所时钟漂移）。
5. **深度可对齐的先行者**：不同所的盘口更新频率不同（OKX 100ms，HL `l2Book` 事件驱动）。对齐时统一采用 **last-value carry-forward**，并在 gold 层生成 `staleness_ms` 特征（该所数据距今多久），下游模型必须能看到它。

---

## 4. C — 监控标的流的运行时设计

### 4.1 标的状态机

```
                    ┌──────────┐
                    │ UNKNOWN  │  （刚被发现，元数据齐全但无历史样本）
                    └────┬─────┘
                 采样达标 │ 元数据/样本就绪
                         ▼
                  ┌─────────────┐   连续 2 周期达标 + Score 进前 30%
   ┌─────────────▶│  CANDIDATE  │──────────────────┐
   │              └──────┬──────┘                   │
   │                     │ 连续 2 周期全部硬门槛达标 │ 连续 3 周期不达标
   │                     ▼                          ▼
   │             ┌─────────────┐            ┌──────────────┐
   │             │   ACTIVE    │───────────▶│  DEGRADED    │  （1–2 周期不达标）
   │             │  （做市 +   │            │ 只减仓不建仓 │
   │             │   全量采集）│            └──────┬───────┘
   │             └──────┬──────┘                   │ 连续 3 周期不达标
   │                    │ 元数据失效 / 致命门槛失败  │
   │                    ▼                          ▼
   │             ┌─────────────┐            ┌──────────────┐
   │             │ SUSPENDED   │            │   RETIRED    │（停止采集，冷却 7 天）
   │             │ 暂停挂单，   │            └──────────────┘
   │             │ 保留采集     │                   ▲
   │             └──────┬──────┘                   │ 元数据恢复 & >120% 阈值
   │                    │ 恢复                      │
   └────────────────────┴───────────────────────────┘
```

| 状态 | 挂单 | 采集 | 退出条件（进入） |
|---|---|---|---|
| UNKNOWN | 否 | 仅 ticker 1s | 元数据可解析 + 至少 1 小时样本 |
| CANDIDATE | 否 | orderbook 5s 抽样 + trades | 连续 2 周期硬门槛达标 → ACTIVE；连续 3 周期不达标 → RETIRED |
| ACTIVE | **是** | 全量 orderbook + trades + funding + OI + 私有流 | 单次致命门槛失败 → SUSPENDED；连续 3 周期不达标 → DEGRADED |
| DEGRADED | 只减仓 | 全量（降为 50% 采样） | 恢复 → ACTIVE；再连续 2 周期 → RETIRED |
| SUSPENDED | 否 | 5s 抽样 + ticker | 元数据恢复 + 连续 2 周期达标 → CANDIDATE（重新考察） |
| RETIRED | 否 | 无（仅保留历史） | 冷却 7 天后重新进入 CANDIDATE |

**状态文件**：`var/pools/{exchange}.json`，原子写（写临时文件 + `os.replace`），结构：
```json
{"version":3,"updated_at":"...","symbols":{
  "DOGE-USDT-SWAP":{"state":"ACTIVE","score":0.82,"hard_pass":{...},
    "gates":{"G1":{"value":..., "pass":true,"window":"24h"}, ...},
    "since":"2026-11-01T00:00:00Z","fail_streak":0,"pass_streak":3,"next_review":"2026-11-15T00:00:00Z"}}}
```

### 4.2 采集频率与资源预算

| 标的池 | 采集项 | 频率 | 带宽/标的（估） | CPU | 磁盘/天 |
|---|---|---|---|---|---|
| ACTIVE (CORE) | `books` 400 档增量 | 推送 ≤10 Hz | **典型 ≈ 50 KB/s**（`【实测】` BTC 1.7 帧/s × 400×2 价位 × ~35 B）；**峰值 ≈ 280 KB/s**（10 帧/s 上界，`【建议起始值】`） | 5–8% 单核（解析+压缩） | zstd 后 ≈ **74–240 MB/天**（`【实测】` DOGE 3.08 MB/h、BTC 9.98 MB/h，见 §3.5）；**原始 JSON 帧另计 ≈ 2–4 GB/天 → 故 bronze 不存原始帧** |
| ACTIVE | `trades-all` | 事件驱动 | ≈ 5–30 KB/s | 2% | ≈ 35 MB/天（实测 BTC trades） |
| ACTIVE | `tickers` / `mark-price` / `funding-rate` / `open-interest` | 1s / 3s / 30s / 3s | < 1 KB/s | <1% | < 5 MB/天 |
| ACTIVE | 私有 `orders` / `account` | 事件驱动 | < 2 KB/s | <1% | < 1 MB/天 |
| CANDIDATE / DEGRADED | orderbook 抽样快照 | 1/5 s | ≈ 2 KB/s | 2% | ≈ 80 MB/天 |
| WATCH | ticker + trades + 5 分钟 orderbook 抽样 | 1s / 事件 / 300s | ≈ 40 KB/s | 1% | ≈ 40 MB/天 |

**总量预算（1 核 1G VPS，`【建议起始值】`）**

```
活跃 WS 连接数：每所 1–2 条（OKX 公共 1 + business 1 + 私有 1；Lighter 1；HL 1）
                 → 总计 ≤ 6 条长连接
带宽：ACTIVE 5 个标的 典型 ≈ 250 KB/s ≈ 2 Mbps；峰值 ≈ 1.4 MB/s ≈ 11 Mbps → 建议 VPS 上行 ≥ 50 Mbps
      （若超限：先降深度 books 400 → books50 → books5，再降标的数）
CPU：解析 8% + 压缩 12% + 特征 10% = ~30% 单核；留 70% 给做市进程
内存：writer 缓冲 200 MB + parquet 写缓冲 128 MB + 盘口重建状态（每标的 ~2 MB）≈ 400 MB
磁盘：见 §3.5（40 GB 盘，热 7 天）
```
**降级方案（1 核 1G 显式路径）**：`ACTIVE` 标的数 > 5 或磁盘 > 80% → 自动把第 6 个及以后的 ACTIVE 降为 `books5` + 抽样；仍超限 → 降为 CANDIDATE 级采样。

> **bronze 不存原始帧的取舍**（重要）：400 档原始 JSON 帧约 **2–4 GB/天/标的**，1 核 1G / 40 GB 盘扛不住 3 个以上标的。
> 折中：**只把解析后未归一的事件写 bronze**（parquet，zstd，≈ 240 MB/天/标的），原始 JSON 仅在以下情况保留：
> ① 每次连接建立后的前 60 秒（协议握手取证）；② 序列号缺口触发时前后各 10 帧（现场取证）；③ 每日随机抽样 100 帧（协议漂移审计）。
> 这样磁盘占用降一个数量级，同时保留绝大部分排障能力。

### 4.3 WS 连接管理与故障恢复

```python
class VenueWsClient:
    async def run(self):                      # 主循环
        attempt = 0
        while not self.stopping:
            try:
                async with websockets.connect(self.uri, ping_interval=20, ping_timeout=10) as ws:
                    await self._subscribe(ws)
                    attempt = 0                # 连接成功即重置退避
                    await self._consume(ws)    # 内部负责心跳与序号校验
            except (ConnectionClosed, OSError, asyncio.TimeoutError) as e:
                attempt += 1
                delay = min(60, 2 ** min(attempt, 6)) + random.uniform(0, 1)   # 指数退避 + 抖动
                log.warning(f"{self.venue} ws down: {e}; retry in {delay:.1f}s")
                await asyncio.sleep(delay)
```

**要点**

| 项 | 做法 |
|---|---|
| 退避 | 指数退避 `2^n`（上限 60s）+ **随机抖动**（避免多客户端同步重连打爆交易所） |
| 订阅去重 | 重连后**全量重订阅**（venue 都会重发快照：OKX `books` 重发 400 档快照；Lighter 重发 `subscribed/order_book`；HL 重发 `l2Book`） |
| 快照重锚 | 收到快照 → **清空本地盘口状态** → 记录 `seq_prev` 为该快照的起点（OKX 快照 `prevSeqId=-1`） |
| 序列缺口恢复 | 检测到 `seq_prev != 上一条 seq_last` → ① 立即标记 gap ② **主动重订阅**该 symbol 以获得新快照（OKX: 再次 `subscribe` 同 channel 会推快照；Lighter: 断连重连；HL: 重新订阅 `l2Book`）③ gap 区间内的行标记 `gap_before=true`，**不可用于盘口重建** |
| 心跳 | 应用层 ping：OKX 用字符串 `ping`（服务端回 `pong`）；HL 用固定 30s 消息；Lighter 依赖 TCP keepalive + 消息活性 |
| 静默检测 | 任一频道 `> 5s` 无消息 → 主动 ping；`> 15s` 无消息 → 强制重连（比 TCP 超时更快发现半死连接） |
| 速率限制 | OKX 有 `op=limit` 订阅上限（每连接 args 数量有限）→ **按标的分批订阅**，每批 ≤ 30 个 channel，批间隔 200ms |
| 连接泄漏 | 每次重连必须 `close()` 旧连接；`asyncio` 中对未关闭的连接会在 GC 时报错 → 用 `async with` |

**多交易所同时监控的 WS 拓扑**
```
单进程 asyncio，N 个 VenueWsClient 任务 + 1 个 WriterTask
所有 client → asyncio.Queue(bounded=200_000) → WriterTask → parquet
背压：队列满 → client 侧 `await queue.put()` 自然阻塞 → 触发 TCP 背压 → 交易所侧慢
      （比丢消息好：丢消息会造成不可重建的盘口）
      但必须计数 `dropped_msg` 并在健康文件暴露（见 §4.4）
```

### 4.4 「监控监控本身」——自监控指标

**采集器健康文件** `/var/run/asgrid/health/{venue}_{collector}.json`（原子写，每 5s）

```json
{
  "ts": 1794664982451,
  "alive": true,
  "collector": "okx_books",
  "symbols": {"DOGE-USDT-SWAP": {"msgs": 123456, "bytes": 987654321,
                                  "last_msg_ts": 1794664982000, "stale_ms": 451,
                                  "seq_gaps_1m": 0, "reconnects_1h": 0,
                                  "p50_latency_ms": 12.4, "p99_latency_ms": 88.1,
                                  "rows_written": 123456, "dropped": 0}},
  "process": {"rss_mb": 312, "cpu_pct": 18.4, "disk_pct": 61.2,
              "disk_free_gb": 14.1, "queue_depth": 1203, "queue_max": 200000,
              "parquet_writes_1h": 42, "parquet_errors_1h": 0}
}
```

**必须暴露的自监控指标（每条都有告警阈值）**

| 指标 | 计算 | 告警阈值 | 动作 |
|---|---|---|---|
| 采集器存活率 | `alive` 心跳 mtime | 超过 60s 未更新 → ERROR | supervisor 自动重启（最多 3 次/10 分钟，之后告警转人工） |
| 消息延迟分位数 | `received_time − event_time`（仅当 venue 提供可信 event_time） | `p99 > 500ms`（WARN）/ `> 2s`（ERROR） | WARN 时检查网络；ERROR 时重建连接 |
| 本地处理延迟 | `flush_ts − received_time` | `p99 > 30s`（WARN）/ `> 120s`（ERROR） | ERROR 时丢弃非 CORE 标的的采集（保 ACTIVE） |
| 丢弃消息数 | `dropped` 计数 | `> 0` → WARN；`> 1000/小时` → ERROR | ERROR 时降低订阅数或升级带宽 |
| 序列号缺口 | `seq_gaps_1m` | `> 0/min` → WARN；`> 5/min` → ERROR | 触发快照重锚；持续 → 该标的降为 DEGRADED |
| 消息速率 | `msgs/s` | 相对 1 小时基线偏离 `±80%` → WARN | 可能是订阅丢失或行情枯竭（两者都要区分） |
| 队列深度 | `queue_depth` | `> 0.8×queue_max` 持续 1 分钟 → ERROR | 触发背压降级（减少订阅） |
| 磁盘水位 | `disk_pct` | `> 75%` WARN / `> 88%` ERROR | 清理 bronze / 停止非核心采集 |
| 内存 | `rss_mb` | `> 700MB`（1G 机）→ ERROR | 降低 writer 缓冲与 row-group 大小 |
| 落盘失败 | `parquet_errors_1h` | `> 0` → WARN；`> 5` → ERROR | 切换到备用目录；检查 inode |
| 标的数据陈旧度 | `stale_ms` per symbol | `> 5000ms` → WARN；`> 15000ms` → ERROR | 强制重连该 symbol |
| 时钟偏移 | `realtime − monotonic` 变化 | `\|Δ\| > 50ms` → WARN | 记录 clock_jump 事件；chrony 重新收敛 |

**「消息速率下降」的两种含义必须区分**（否则会误判）：
```
订阅丢失：多数 symbol 的速率同时归零，而交易所 ticker 正常 → 我们的连接问题
行情枯竭：单个 symbol 归零，其他 symbol 正常 → 真实的流动性断裂（→ 漏斗 G7）
```
实现：`msg_rate` 是 per-symbol 的，`venue_health` 是 per-connection 的，两者分开报警。

---

## 5. D — 落地到本仓库的具体改动

### 5.1 新增目录结构

```
as-grid-arb-research/
├── datapipe/                          # 新增：数据与选品管线包
│   ├── __init__.py
│   ├── config.py                      # 路径、阈值表（dataclass）、凭据加载（env）
│   ├── constants.py                   # venue 常量、符号规范化映射（OKX/Lighter/HL）
│   ├── metrics.py                     # 漏斗指标计算（纯函数，输入 silver → 输出标量）
│   ├── funnel.py                      # 漏斗编排 + 打分 + 硬门槛判定
│   ├── pools.py                       # 三档池状态机 + 滞回 + 原子写
│   ├── features.py                    # OFI/微价格/波动率/毒性特征（与引擎共用）
│   ├── quality.py                     # Q1–Q12 闸门实现
│   ├── clock.py                       # chrony/单调时钟/SO_TIMESTAMPING
│   ├── align.py                       # 跨所 lead-lag 与时间轴对齐
│   ├── cli.py                         # 子命令入口
│   ├── archive/
│   │   ├── __init__.py
│   │   ├── chd_client.py              # REST 客户端（JWT/限流/重试）
│   │   ├── sync.py                    # 增量同步 + 去重 + 缺口检测
│   │   ├── manifest.py                # SQLite manifest（files 表）
│   │   └── normalize.py               # 归档 → 统一 silver schema（含单位换算）
│   ├── recorder/
│   │   ├── __init__.py
│   │   ├── ws_client.py               # VenueWsClient 基类（退避/心跳/重订阅）
│   │   ├── okx.py                     # OKX v5
│   │   ├── lighter.py                 # Lighter
│   │   ├── hyperliquid.py             # Hyperliquid（含 HIP-3 dex 处理）
│   │   ├── sink.py                    # Parquet 写入器（分区/row-group/原子写）
│   │   └── own_orders.py              # 私有订单/成交流 → silver/own_orders
│   ├── schema.py                      # 统一 schema 定义（字段名/类型/字典编码）
│   └── monitor/
│       ├── __init__.py
│       ├── health.py                  # 健康文件写入 + 指标计算
│       ├── watchdog.py                # 判分 + 告警（cron/长驻）
│       └── notifier.py                # Telegram 推送（从 cron_hot_monitor 抽离）
├── var/                               # 运行期状态（gitignore）
│   ├── pools/{exchange}.json
│   ├── manifest.sqlite
│   └── health/*.json
├── data/                              # 数据湖（gitignore；.gitkeep 占位）
│   ├── bronze/{chd_archive,live}/...
│   ├── silver/{orderbook,trades,ticker,mark_price,open_interest,own_orders}/...
│   └── gold/{features,labels}/...
├── tests/
│   ├── test_funnel_metrics.py
│   ├── test_orderbook_rebuild.py      # 快照+增量重建 + 缺口检测
│   ├── test_pool_hysteresis.py        # 滞回状态机（含抖动序列）
│   └── test_chd_sync.py               # 增量同步/去重/gap（用本地假 server）
└── docs/design/01-data-pipeline-and-symbol-selection.md   # 本文档
```

### 5.2 关键接口签名

```python
# datapipe/config.py
@dataclass(frozen=True)
class FunnelThresholds:
    adv_quote_core_usd: float = 5_000_000.0
    adv_quote_watch_usd: float = 1_000_000.0
    depth5_usd: float = 50_000.0
    depth10_usd: float = 120_000.0
    min_spread_bps: float = 10.0
    min_msg_rate: float = 5.0
    max_ofi_acf1: float = 0.35
    max_vpin_mean: float = 0.55
    max_adx14: float = 25.0
    max_funding_p99_abs: float = 0.0015
    # 升级/降级/淘汰滞回
    upgrade_streak: int = 2
    degrade_streak: int = 3
    retire_streak: int = 3
    cooldown_days: int = 7

@dataclass(frozen=True)
class Paths:
    root: Path
    bronze: Path; silver: Path; gold: Path
    var_pools: Path; var_health: Path; manifest_db: Path

def load_config(env_file: str | None = None) -> tuple[FunnelThresholds, Paths]: ...
```

```python
# datapipe/metrics.py —— 全部为纯函数：输入 silver 切片，输出标量（便于测试与回测复用）
def median_spread_bps(book: pd.DataFrame) -> float: ...
def depth_notional(book: pd.DataFrame, levels: int, side: str) -> float: ...
def garman_klass_vol(trades: pd.DataFrame, bar: str = "5min") -> float: ...
def parkinson_vol(trades: pd.DataFrame, bar: str = "5min") -> float: ...
def ofi_series(book: pd.DataFrame) -> pd.Series: ...          # 与 okx_ws_manager._handle_book 同款
def ofi_acf1(ofi: pd.Series) -> float: ...
def vpin(trades: pd.DataFrame, bucket: str = "1min", n_buckets: int = 50) -> float: ...
def large_trade_share(trades: pd.DataFrame, q: float = 0.95) -> float: ...
def maker_impact(trades: pd.DataFrame, book: pd.DataFrame, delta: str = "1s") -> float: ...
def adx14(bars: pd.DataFrame) -> float: ...
def hurst_dfa(series: pd.Series, lags: tuple[int, ...] = (16, 32, 64, 128, 256)) -> float: ...
def funding_stats(mark: pd.DataFrame, days: int = 30) -> dict[str, float]: ...
def message_rate(book: pd.DataFrame) -> float: ...
def crossing_rate(book: pd.DataFrame) -> float: ...
```

```python
# datapipe/funnel.py
@dataclass
class GateResult:
    gate: str            # "G1" ...
    passed: bool
    value: float | None
    threshold: float | None
    reason: str

@dataclass
class SymbolEvaluation:
    exchange: str; symbol: str
    market_type: str      # crypto | rwa | hip3
    gates: list[GateResult]
    hard_pass: bool
    score: float
    evaluated_at: pd.Timestamp

def evaluate_symbol(exchange: str, symbol: str, silver: pd.DataFrame,
                    thresholds: FunnelThresholds, market_type: str) -> SymbolEvaluation: ...
def run_funnel(exchanges: list[str], window: str, thresholds: FunnelThresholds) -> list[SymbolEvaluation]: ...
```

```python
# datapipe/pools.py
class PoolState(str, Enum):
    UNKNOWN="UNKNOWN"; CANDIDATE="CANDIDATE"; ACTIVE="ACTIVE"
    DEGRADED="DEGRADED"; SUSPENDED="SUSPENDED"; RETIRED="RETIRED"

@dataclass
class PoolRecord:
    symbol: str; state: PoolState
    pass_streak: int; fail_streak: int
    score: float; last_fail: str | None
    since: str; next_review: str

def transition(rec: PoolRecord, ev: SymbolEvaluation, th: FunnelThresholds,
               fatal: bool = False) -> PoolRecord: ...
def load_pool(path: Path) -> dict[str, PoolRecord]: ...
def save_pool(path: Path, records: dict[str, PoolRecord]) -> None: ...   # 原子写
```

```python
# datapipe/archive/chd_client.py
class CHDClient:
    def __init__(self, api_key: str | None = None, base_url: str = "https://api.cryptohftdata.com/v1",
                 max_rpm: int = 50): ...
    def jwt(self) -> str: ...                       # 带缓存与过期前刷新
    def status(self) -> Status: ...                 # target.prefix / lookback_hours
    def symbols(self, exchange: str, data_type: str | None = None) -> list[str]: ...
    def download(self, key: str, dest: Path) -> Path: ...   # 302 跟随 → 原子落盘
    def _rate_limit(self) -> None: ...              # 令牌桶 + 429 Retry-After

# datapipe/archive/sync.py
@dataclass
class SyncPlan:
    keys: list[str]                 # 待拉的 {ex}/{date}/{hh}/{symbol}_{dt}
    skipped: int
    hours: list[str]

def plan_sync(client: CHDClient, exchanges: list[str], symbols: dict[str, list[str]],
              data_types: list[str], manifest: Manifest) -> SyncPlan: ...
def sync(plan: SyncPlan, client: CHDClient, manifest: Manifest) -> SyncReport: ...
def detect_gaps(manifest: Manifest, exchanges, symbols, data_types) -> list[Gap]: ...
```

```python
# datapipe/recorder/ws_client.py
class VenueWsClient(abc.ABC):
    def __init__(self, venue: str, uri: str, symbols: list[str], out_q: asyncio.Queue,
                 health: HealthReporter): ...
    async def run(self) -> None: ...                 # 退避重连主循环
    @abc.abstractmethod
    def subscribe_args(self) -> list[dict]: ...
    @abc.abstractmethod
    def handle(self, msg: dict) -> list[NormalizedEvent]: ...
    # 基类提供：_consume / _ping / _handle_gap / _snapshot_reset

# datapipe/recorder/sink.py
class ParquetSink:
    def __init__(self, paths: Paths, row_group_bytes: int = 128 * 1024 * 1024,
                 flush_seconds: int = 60, compression: str = "zstd"): ...
    def write(self, events: list[NormalizedEvent]) -> None: ...
    def flush(self) -> None: ...                     # 原子 rename 落盘
```

```python
# datapipe/quality.py
@dataclass
class QualityReport:
    passed: bool
    checks: dict[str, CheckResult]

def run_gates(silver_dir: Path, symbols: list[str]) -> QualityReport: ...
def rebuild_book(orderbook: pd.DataFrame) -> tuple[pd.DataFrame, list[Gap]]: ...
def cross_check_mid(live: pd.DataFrame, archive: pd.DataFrame, tick: float) -> float: ...
```

### 5.3 可直接复用的现有代码

| 现有文件 | 复用点 | 处理方式 |
|---|---|---|
| `live_cluster/okx_ws_manager.py` | ① **IPv4 强制解析补丁**（`_ipv4_getaddrinfo`）——API Key 有 IP 白名单，必须保留 | **抽到 `datapipe/constants.py`（或 `datapipe/net.py`）**，两处共用；`okx_ws_manager` 改为 import，避免两副本漂移 |
| | ② **OFI（Cont-Kukanov-Stoikov）实现** `_handle_book` | **抽到 `datapipe/features.py:ofi_step()`**，`okx_ws_manager` 与漏斗共用同一份实现（否则漏斗指标与实盘指标会出现口径漂移） |
| | ③ **micro-price 计算** | 同上抽到 `features.py` |
| | ④ **私有订单严格成交过滤**（`state ∈ {filled, partially_filled}` 且 `fillSz>0`） | 抽到 `datapipe/recorder/own_orders.py`，同时把 `unprocessed_fills` 落成 `silver/own_orders` |
| | ⑤ **重连骨架** `_public_ws_loop` | **不要照抄**：现在是固定 `sleep(2)`，必须换成 §4.3 的指数退避 + 抖动 + 静默检测；`recorder/ws_client.py` 提供新实现，`okx_ws_manager` 后续改为继承它 |
| | ⑥ `books5` + `trades` 订阅形态 | 保留，但 recorder 改用 `books`（400 档增量）以支持盘口重建；`books5` 保留给轻量监控 |
| `live_cluster/gateway_okx_client.py` | ① `_sign_and_request`（HMAC-SHA256 签名 + ISO8601 毫秒时间戳） | **直接复用**到 `datapipe/exchange_meta.py`（拉 `public/instruments`、`market/tickers`、`public/funding-rate`、`public/mark-price`、`public/open-interest`） |
| | ② `get_ticker` / `get_books` | 复用；新增 `get_instruments(inst_type)`、`get_funding_rate(inst_id)`、`get_open_interest(inst_id)` |
| | ③ `get_fills` / `get_order` | **重要**：用作 `silver/own_orders` 的**对账源**（WS 漏事件时用 REST 补齐），直接解决 `LESSONS_LEARNED` 第 2 条 |
| | ⚠️ 硬编码凭据 | `cron_hot_monitor.py` 第 40–43 行有明文 OKX API Key 与 Telegram Token → **必须迁移到环境变量**（`datapipe/config.py: load_config`），并在 `.gitignore` 加入 `config.env` |
| `src/as_ml_engine.py` | 毒性门控阈值（`p_toxic_down ≥ 0.65` 断买、`< 0.40` 恢复） | 作为 G4 的**互补**实时熔断（漏斗是"选标的"，它是"选方向"），两者共用 `features.py` 的特征，阈值从 `config.py` 读取 |
| `live_cluster/as_dynamic_risk.py` | 账户档位 → `max_inventory` / `min_spread_bps` | 改为**由漏斗配置驱动**（§2.5），消除与 README 的口径冲突 |
| `src/grid_risk_controller.py` | 波动率熔断逻辑 | 其中的 GK/Parkinson 计算应改为调用 `datapipe/metrics.py`，避免两套波动率定义 |
| `src/download_real_btc_1m.py` | 下载/落盘/去重范式 | 作为 `archive/sync.py` 的风格参考（但它用 `requests` + `pandas.to_parquet`，我们的归档侧应改为流式 + 原子落盘） |

### 5.4 最小可落地路径（Phase 0 → Phase 1 → Phase 2）

| 阶段 | 目标 | 交付 | 判定 |
|---|---|---|---|
| **P0（1 周）** | 目录骨架 + 配置外置 + 凭据迁移 | `datapipe/{config,constants,schema}.py`；`okx_ws_manager` 改 import 共享 IPv4 补丁与 OFI | 现有实盘行为**零变化**（回归：对同一段行情，新旧 OFI 序列逐点相等） |
| **P1（2 周）** | 归档接入 + 漏斗 v1 | `archive/{chd_client,sync,normalize}.py`；`metrics.py` + `funnel.py` + `pools.py`；对 3 个交易所跑 14 天历史，产出首版 CORE/WATCH 名单 | 漏斗打分与 `net_bps_per_fill` 的 Spearman ρ ≥ 0.4（§2.7 标定流程跑通） |
| **P2（2 周）** | 自录 + 数据湖 | `recorder/*` + `sink.py` + `quality.py`；`silver/own_orders` 开始落盘 | 盘口重建校验 Q4 交叉盘 = 0；双源比对 Q12 价差相对偏差 < 20% |
| **P3（1 周）** | 监控流 + 自监控 | `monitor/*` + `health.py` + `watchdog.py`；告警接入 Telegram | 连续 7 天 0 ERROR；自监控指标全部有采集 |
| **P4（2 周）** | 交叉所对齐 + 组合层约束 | `align.py` + G9 | lead-lag 估计跨日标准差 ≤ 2ms；CORE 池相关性约束生效 |

### 5.5 立即可执行的小改动（半天内，收益明确）

1. **凭据外置**：`live_cluster/cron_hot_monitor.py` 的硬编码 API Key / Telegram Token → `os.environ` + `.env`（防止泄漏；同时 Telegram token 已在 git 历史中，**建议轮换**）。
2. **`min_spread_bps` 口径统一**：`as_dynamic_risk.py` 改为读取 `datapipe/config.py` 的统一公式，并在 `README` 补口径说明。
3. **标的注册表动态化**：新增 `datapipe/asset_class_map.json` + `trading_sessions.json`，`run_live.py` 启动时读取；HIP-3 符号（`XYZ:` / `CASH:` / `FLX:`）**必须走注册表**，禁止硬编码。
4. **时段门控**：RWA/代币化股票标的在非撮合时段强制撤单并停用（`trading_sessions.json` 驱动）。这是当前最容易造成大额亏损的缺口（`【实测】` OKX `AAPL-USDT-SWAP` 在美股休市时段点差会异常放大或盘口冻结）。

---

## 6. RWA / HIP-3 与普通山寨币的根本差异（总结性陈述）

一句话：**山寨币的做市利润来自「点差 vs 手续费」，RWA/HIP-3 的做市利润只能来自「资金费率 carry + 事件驱动」，而它们的尾部风险来自「时段断裂 + 跳空 + 发行人信用」而不是「连续毒性流」。**

具体到数据与监控的差异：

1. **数据可得性**：RWA 的历史深度极短（`【实测】` OKX `AAPL-USDT-SWAP` 的 `listTime=1772612100000` → **2026-03-04**，即到本文档写作时只有约 8 个月），且成交样本量极稀（704 笔/小时）→ **不足以训练微观结构模型**，RWA 只能靠**事件驱动规则 + 少量参数**，不能靠 ML。
2. **「点差机会」在 RWA 上结构性不存在**：`【实测】` RWA 点差仅 0.281 bps，而 OKX 永续 Maker 往返成本 4 bps —— 差 14 倍。**每一次 RWA 成交都是负期望**；RWA 的正收益只能来自**资金费率 carry**（对冲掉库存方向成本）与**事件驱动**（派息/赎回窗口的价差）。因此 RWA 走独立分支（§2.6），用 carry 而非 spread 建模。
3. **流动性不是断的，是「薄而贵」的**：RWA 24h 成交额 ≈ 993 万 USDT（够 G1 门槛），但**成交笔数**只有 0.196 笔/秒 → 做市系统的「成交量/笔」类指标与「点差」类指标在 RWA 上给出**相反的信号**，这正是必须分叉漏斗的原因。
4. **时段**：山寨币 7×24 波动连续；RWA 只在美股时段有真实流动性，其余时间是**假盘口**（挂单稀疏、点差乱跳）。若不实现时段门控，做市器会在休市时段用陈旧价格持续挂单，开市瞬间全部被扫（这是本任务最危险的具体风险）。
5. **标的生命周期**：HIP-3 的符号空间是动态的（每次新 dex = 新前缀，`【实测】` `XYZ:` / `CASH:` / `FLX:`），符号注册表必须**每日自动重建**，且**前缀本身是 dex 标识**（不同 dex 的同名资产是不同标的，不能混）。
6. **事件驱动风险**：派息除权会造成**价格瞬时跳空**（RWA 的机制性事件），ADX/波动率指标完全无法提前刻画 → 必须有 `corporate_actions` 日历 + `gap_risk` 指标 + 「派息日前 24h 禁开仓」硬规则。
7. **结算/赎回机制**：到期结算价来源、赎回窗口与 T+N 决定「能否用现金平掉库存」，这直接影响能否承担库存风险；普通永续无此问题。
8. **监控频率不同**：山寨币可以 100ms 采；RWA 有效时段内可以 100ms 采，**时段外只需 1 条 ticker**（省 95% 带宽）→ 采集器必须**时段感知**，而不是无脑 7×24。

---

## 7. 未决问题与待办（明确写出，避免伪装成已解决）

| # | 问题 | 影响 | 计划 |
|---|---|---|---|
| 1 | 全部漏斗阈值目前都是 `【建议起始值】`，未经实测标定 | 直接决定选品质量 | §2.7 的 14 天采集 + 回放标定流程（P1 阶段） |
| 2 | RWA 有效撮合时段表未采集 | RWA 分支 G7 无法执行 | 从各交易所 instrument 元数据 + 行情稀疏性反推 + 人工校验 |
| 3 | 借贷利率无稳定数据源 | G6 对 RWA 的借贷门槛无法自动执行 | 人工维护 `borrow_rates.json`（月更） |
| 4 | 跨所 lead-lag 偏移是否会漂移 | 影响套利研究的有效性 | P4 阶段用 30 天数据监控 `δ_AB` 的日间标准差 |
| 5 | `own_orders` 表能否达到「精确回放撮合」 | 决定能否做撮合级回测 | 关键依赖：私有 WS 的 `client_seq` 全序 + 撤单双时刻；P2 阶段验证 |
| 6 | cryptohftdata 对已发布文件的**原地修正**（同 key 换内容） | 增量同步可能拿到过期数据 | manifest 记 `sha256`，周度校验近 30 天文件 |
| 7 | 1 核 1G 下 5 个标的 400 档 L2 的真实带宽与 CPU | 决定 ACTIVE 池上限 | 带宽已按 `【实测】` 帧速率（BTC 1.7 帧/s）折算为典型 50 KB/s、峰值 280 KB/s；**CPU 与实际网络吞吐仍需 P2 阶段实测** |
| 8 | 仓库内 `min_spread_bps` 口径冲突（README 10 bps vs `as_dynamic_risk` 3.0–4.5） | 直接影响实盘盈利 | §5.5 第 2 项，本周收敛 |

---

## 8. 参考

- cryptohftdata 官方文档（实测核对）：`/v1/status`、`/v1/symbols`、`/v1/download`、`/v1/jwt-token`、REST Introduction / Authentication / Order Book / Trades / Mark Price / Open Interest / Known Gaps & Corrections / Venue Wire Formats（OKX Futures、Lighter、Hyperliquid Futures）。
- OKX API v5：`wss://ws.okx.com:8443/ws/v5/public`、`wss://ws.okx.com:8443/ws/v5/business`、`GET /api/v5/public/instruments`、`GET /api/v5/market/ticker`、`GET /api/v5/public/funding-rate`。
- Lighter：`wss://mainnet.zklighter.elliot.ai/stream`、`GET https://mainnet.zklighter.elliot.ai/api/v1/orderBooks`。
- Hyperliquid：`wss://api.hyperliquid.xyz/ws`、`POST https://api.hyperliquid.xyz/info`。
- 仓库内：`ARCHITECTURE_AND_EXECUTION_FLOW.md`（OFI 公式、6 阶段流程）、`LESSONS_LEARNED.md`（5 条工程铁律）、`README.md`（盈利导向标的池与 10 bps 价差铁律）、`live_cluster/okx_ws_manager.py`、`live_cluster/gateway_okx_client.py`。
