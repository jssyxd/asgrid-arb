# 04 · 实盘上线、资金放大与运维监控方法论

> 切片归属：Strategy 012（Avellaneda–Stoikov 微观自适应网格做市）· 实盘与运维侧
> 定位：回答三个问题——(1) 怎样把回测通过的系统安全送上实盘；(2) 验证正期望后怎样逐级放大资金；(3) 怎样持续监控整个系统。
> 依赖前置文档：`04` 之前的设计稿（定价内核、回测引擎、ML 闭环）以及共享上下文 `_shared-context.md`。
>
> 标注约定：
> - 【实测】= 本项目 VPS / 交易所 / 回测中真实观测到的数字，可复算。
> - 【反推】= 由实测的成交流水与费率反算出来的量（含假设，见公式下方）。
> - 【建议起始】= 尚无实测支撑的工程初始值，必须在指定观察期内用实盘数据替换。
> - 【推断】= 由模型假设推出，未经验证。

---

## 0. 前提与不可逾越的物理约束

### 0.1 三条硬约束（决定后面所有设计的形状）

| 编号 | 约束 | 数值 | 后果 |
|---|---|---|---|
| C1 | **最小下单粒度** | OKX `BTC-USDT-SWAP` 最小 0.01 张 = 0.0001 BTC ≈ **8.08 USDT 名义**（按 BTC≈80,800）【实测，共享上下文】 | 30U 本金下 **单笔即 27% 权益**；库存无法做细 → 「做市」退化为「带库存的方向下注」 |
| C2 | **网络与算力** | RTT 到 OKX 撮合约 **45~75 ms**；单核多容器事件循环抖动 **10~50 ms**【实测】 | 任何依赖亚 100ms 精度的门控都不可靠；监控必须极轻量 |
| C3 | **撮合物理** | 限价单 FIFO 排队 | 回测「碰到即成交」系统性高估做市收益；实盘任何单位经济学指标只能用**每名义 bps**比较，不能用绝对收益比较 |

### 0.2 当前实盘基线（必须先算清楚，再谈放大）

accountbot3 实盘 10.38 h【实测，共享上下文】：Maker 比例 99.5%，手续费 0.3269 USDT，净损益 −0.09 USDT，本金保全率 98.6%。

由这四个数可以**反推出做市的单位经济学**（这是本文档所有阈值与公式的锚点）：

```
【反推 A】名义成交额
  假设：99.5% 为 Maker 成交，Maker 费率 0.02%，所有手续费均按名义值线性计费
  N_total = 0.3269 USDT ÷ 0.0002 = 1634.5 USDT 名义（10.38 h）
  → 日均名义 ≈ 3779 USDT/日
  → 单笔名义 8.08 USDT ⇒ 成交笔数 ≈ 202 笔（10.38 h）⇒ 468 笔/日

【反推 B】净捕获率 e（每名义 bp）
  e = (净损益 + 手续费) ÷ 名义成交额
    = (−0.09 + 0.3269) ÷ 1634.5 = 1.45 bp   ← 这一项是「毛利 − 逆向选择」
  但净损益本身为负，直接口径：
  e_net = 净损益 ÷ 名义 = −0.09 ÷ 1634.5 = **−0.55 bp/名义**

【反推 C】逆向选择成本 a（每名义 bp）
  报价半价差 δ = 4.5 bp（总价差 9 bp 门槛的一半）【实测，代码常量】
  δ − a − f = e_net  ⇒  4.5 − a − 2.0 = −0.55  ⇒  **a ≈ 3.05 bp/名义**
  ⇒ 逆向选择吃掉了报价半价差的 **67.8%**，手续费再吃掉 **44.4%**，合计 112%，边际为负。
```

> **口径警告（写在这里，避免后面被误引用）**：反推 B/C 假设 (i) 手续费全部按 2 bp 名义线性计费；(ii) 净损益全部归属于这 1634 USDT 名义成交（实际净损益含未实现盈亏与 BTC 价格变动的噪声）；(iii) 生效半价差恰为 4.5 bp（实际 `vol_surge` / 毒性门控 / ADX 过滤会把价差放宽，故真实 δ ≥ 4.5 bp，因而 **a 会被高估**）。
> 结论方向稳健：**逆向选择成本的量级在 2~3 bp/名义**，这不是噪声，这是结构性的。因此在 e 转正之前，任何「加资金」的动作都是加速亏损。

### 0.3 为什么回测收益不能直接当实盘预期

| 指标 | 回测（2 年，100k 本金）| 实盘反推（10.38 h，30U 本金）|
|---|---|---|
| 日均名义成交额 | 1,319,397 USDT【实测，`reports/asgrid_2year_metrics.json`】| 3,779 USDT【反推 A】|
| 换手倍数 k_v = 日均名义 ÷ 权益 | 13.19 /日 | **127.7 /日** |
| 每名义净捕获 | +0.71 bp（68,192 ÷ 962.87M）【实测反算】| **−0.55 bp**【反推 B】|
| 最大回撤 | 4.10%（但含零排队假定）【实测】| 本金保全 98.6%（含浮亏噪声）【实测】|

两个结论：

1. **换手倍数 k_v 实盘比回测高 10 倍**，因为实盘单笔只有 8.08 USDT 而回测单笔 4,300 USDT，回测靠「大单」压低换手。→ **绝对收益率不可跨环境比较**，只能用每名义指标。
2. **每名义捕获从 +0.71 bp 掉到 −0.55 bp**，落差来自零排队假定、对称点差假定、无滑点、以及 100k→30U 的粒度差异。这正是「关卡制」存在的理由：不能拿回测当上线许可，只能拿回测当**下界**。

---

## 1. 上实盘的分阶段推进（Gate 机制）

### 1.0 Gate 的四条通用规则

| 规则 | 内容 |
|---|---|
| G1 | **资金不早于证据**：任何一档资金的上线，必须先在上一档资金上跑满观察期并全项达标。资金可以不变，参数可以调；观察期不可压缩。 |
| G2 | **降级优先于停机**：系统出问题时优先降级（少开仓 → 只减不加 → 停机），而不是直接全停。全停会丢失队列位置，重启后逆向选择成本更高。 |
| G3 | **一次只动一个变量**：同一档内不要同时改资金、参数、标的数。否则指标变化无法归因。 |
| G4 | **关卡是门不是路标**：任一「不达标动作」触发后，资金档位自动回退到上一档并重置观察期计时。 |

### 1.1 关卡总表

| 关卡 | 名称 | 资金 | 标的数 | 观察期 | 准入 | 达标 | 不达标动作 | 退出 |
|---|---|---|---|---|---|---|---|---|
| 0 | 影子模式 shadow | 0 | 1 | **≥ 14 天**（含 3 次波动率事件）| 回测冻结版本 + 特征/模型文件可加载 | 见 1.2 | 修 bug，重跑 | 连续 7 天无 CRITICAL |
| 1 | OKX 模拟盘 demo | 0 | 1 | **≥ 7 天** | 关卡 0 达标 | 见 1.3 | 回关卡 0 | 见 1.3 |
| 2 | 实盘极小资金 | **30 USDT**【实测在跑】| 1 | **≥ 30 天** | 关卡 1 达标 + 券商/交易所 KYC 完成 | 见 1.4 | 缩回 0 / 停机 | 见 1.4 |
| 3 | 单标的小幅放量 | 30 → **150 USDT** | 1 | **≥ 30 天** | 关卡 2 达标（e>0）| 见 1.5 | 回退到关卡 2 资金 | 见 1.5 |
| 4 | 多标的并行 | 150 → **2,000 USDT** | 2~4 | **≥ 45 天**（每标的 ≥ 30 天独立样本）| 关卡 3 达标 + 各标的单位经济学各自达标 | 见 1.6 | 退回单标的 | 见 1.6 |
| 5 | 资金阶梯放大 | 2,000 → **30,000 USDT** | 4~8 | 每档 **≥ 30 天** | 关卡 4 达标 | 见 1.7 | 降一档 | 见 1.7 |

> 关卡 2 是当前所在阶段。关卡 3 之后的所有档位都以「上一档实测 e 值」重算阈值，不允许沿用回测参数。

### 1.2 关卡 0：影子模式（shadow）

**做什么**：跑完整决策链路，**不下单**。每 tick 生成假想订单（post-only would-be order），与真实盘口做纸上成交模拟。

**验证什么**（这一关专门抓回测抓不到的错误）：

| # | 验证项 | 方法 | 达标条件 |
|---|---|---|---|
| 0.1 | 特征因果性 | 影子模式下同一时刻的特征值与回测同 bar 特征值逐字段比对（容差 1e-9）| 完全一致，**且**未来 bar 注入后当前特征不变化（反事实检验）|
| 0.2 | 报价合法性 | 每 tick 断言 `bid < mid < ask`、`half_spread ≥ 4.5 bp`、`bid ≥ mid − max_spread` | 100% 通过 |
| 0.3 | 库存约束 | 断言 `|inventory| ≤ max_inventory` 恒成立 | 100% 通过，无一例外 |
| 0.4 | 队列生存模型 | 用 `cryptohftdata` 的 `orderbook` 归档（`okx_futures` / `binance_futures` 等，`exchange=okx` 会返回 count=0，必须用规范化 id）【实测 API 行为】回放，检验「假想单排队位置随时间变化」的估计器 | 队列位置估计与回放真值误差 ≤ 20% |
| 0.5 | 单位经济学首次成像 | 用影子成交 + 后续 1s/5s/30s mark-out 计算 e、ASR、FGR | 产出**第一版真实 e**，允许为负（这是它的价值）|
| 0.6 | 断线与缺口演练 | 主动 kill WS / 断网 60 s / 注入事件时间戳乱序 | 无未捕获异常，重连后状态可从交易所 REST 重建 |
| 0.7 | 算力画像 | 记录单核 CPU 占用、事件循环抖动 | 稳态 CPU < 60%，p99 循环抖动 < 100 ms【建议起始】|

**观察期**：≥ 14 天自然日 + 必须覆盖 ≥ 3 次日波动率超过中位数 2 倍的事件（`vol_surge` 计数 ≥ 3）。

**不达标动作**：修 bug 后观察期重新计时。影子模式不消耗真实资金，但**必须真实消耗时间**，不允许压缩。

**退出条件**：7 天连续无 CRITICAL + 0.1~0.3 全部达标。

### 1.3 关卡 1：OKX 模拟盘（demo）

**做什么**：`OKX_SIMULATED_TRADING=1`（`gateway_okx_client.py` 已支持该 header【实测：现有实现】），真实连 OKX 模拟盘，真实下单、真实撮合、真实拒单。

**验证什么**（与影子模式的差异点）：

| # | 验证项 | 达标条件 |
|---|---|---|
| 1.1 | **签名与权限链路** | 下单/撤单/查仓/查余额全部返回 `code=="0"`；错误码不出现 `50111`（签名）/ `50113`（权限）|
| 1.2 | **Post-Only 强制** | Maker 比例 ≥ 99.5%（当前实盘水平）【实测基线】；任何 taker 成交立即 WARN 并定位 |
| 1.3 | **拒单原因分布** | 建立 `reject_reason` 直方图；可接受集合 = {价格不匹配 post-only, 余额不足, 数量精度}；不可接受集合 = {限频, 鉴权, 未知} 出现即为 CRITICAL |
| 1.4 | **订单生命周期对账** | 本地订单账本 vs `GET /api/v5/trade/orders-pending` + `fills` 逐笔一致，差异 0 笔（每日抽样 100 笔）|
| 1.5 | **限频行为** | 模拟盘限频更严，正好用来压测下单速率上限；记录 429/限频错误码首次出现的下单速率 |
| 1.6 | **重启恢复** | `SIGTERM` → 撤单 → 退出；重启后从 REST 同步持仓与挂单，不留孤儿单（孤儿单数 = 0）|
| 1.7 | **模拟盘与实盘的差异** | 记录模拟盘成交频率与实盘（关卡 2）成交频率之比；若 < 0.5 或 > 2，说明模拟撮合不可用作容量参考，其数据不进入 e 统计 |

**观察期**：≥ 7 天，且累计成交 ≥ 200 笔（否则 e 的样本不足，统计上无法与噪声区分）。

**退出条件**：连续 5 天无 CRITICAL，1.1~1.6 达标，且模拟盘累计 e 的 95% 置信区间下界 > −0.2 bp/名义。

### 1.4 关卡 2：实盘极小资金（30 USDT）— **当前阶段**

**做什么**：真实资金 30 USDT，`BTC-USDT-SWAP`，0.01 张/笔，`max_inventory = 0.05` 张（占权益 135%，⚠ 已越界，见 2.4）。

**验证什么**：真实环境下的单位经济学、队列真实行为、逆向选择真实成本、运维链路。

**本阶段的核心产出（目前已有部分）**：

| 指标 | 当前实测 | 判读 |
|---|---|---|
| Maker 比例 | 99.5% | ✅ 达标（≥99.5%）|
| 手续费绝对额 | 0.3269 USDT / 10.38 h | ✅ 相比旧版 dayuan 4.92 USDT 降 93.3%【实测】|
| 本金保全率 | 98.6% | ⚠ 10.38 h 亏 0.42 USDT，噪声与真实亏损无法区分 |
| 净捕获率 e | −0.55 bp/名义【反推】| ❌ **不达标**：e 必须 > 0 才允许进入关卡 3 |
| 逆向选择率 ASR | ≈ 67.8%（占毛利）【反推】| ❌ 远超 40% 上限 |

**关键验收指标（关卡 2 全期）**：

| 指标 | 公式 | 达标阈值 |
|---|---|---|
| 净捕获率 e | `(Σgross_capture − Σadverse − Σfee) ÷ Σnotional` | **滚动 100 笔 > 0**，且 95% CI 下界 > −0.1 bp【建议起始】|
| 手续费占毛利比 FGR | `Σfee ÷ Σgross_capture` | ≤ 50%（理想 ≤ 30%）【建议起始】|
| 逆向选择损失率 ASR | `Σadverse ÷ Σgross_capture` | ≤ 40%（理想 ≤ 25%）【建议起始】|
| Maker 比例 | `maker_fills ÷ total_fills` | ≥ 99%（< 95% 触发 CRITICAL）|
| 拒单率 | `rejects ÷ (places + cancels)` | ≤ 2%（> 5% CRITICAL）|
| 队列保持率 | `queue_hold_cycles ÷ (queue_hold_cycles + repost_cycles)` | ≥ 80%【建议起始】|
| 断线率 | WS 重连次数 ÷ 运行小时 | ≤ 0.2 次/小时（> 1 次/小时 CRITICAL）|
| 决策延迟 | `决策时刻 − 最新盘口事件时刻` | p95 ≤ 300 ms（受 45~75 ms RTT + 10~50 ms 抖动约束）|
| 库存越界 | `max|inventory| ÷ max_inventory` | = 0（不允许越界）|
| 权益回撤 | `(peak_equity − equity) ÷ peak_equity` | ≤ 3%（关卡 2 的绝对上限）|

**观察期**：≥ 30 个自然日，且累计成交 ≥ 1,000 笔。

> ⚠ **当前 30U 本金下的一个事实必须写清楚**：按 C1，单笔 8.08 USDT = 27% 权益，`max_inventory 0.05` 张 = 40.4 USDT 名义 = 135% 权益。在这种配置下，任何一次 BTC 2% 反向波动都会吃掉约 0.81 USDT（2.7% 权益），而 10.38 h 的实测净收益是 −0.09 USDT。**换句话说：在 30U 上，跑得越久，浮亏尾巴越可能吞掉全部做市利润。**
> 因此关卡 2 的正确定位是：**测量单位经济学与运维链路，不是赚钱**。它的退出条件是「e 的估计足够可信」，而不是「赚到钱」。

**退出条件**：上述全项达标 + e 的滚动 100 笔均值 > 0 + 观察期 ≥ 30 天。

### 1.5 关卡 3：单标的小幅放量（30 → 150 USDT）

**准入**（全部满足才可动资金）：

1. 关卡 2 全部达标，e > 0 且连续 7 天滚动均值 > 0；
2. FGR ≤ 50%、ASR ≤ 40%、Maker ≥ 99%；
3. 拒单率 ≤ 2%、队列保持率 ≥ 80%、WS 重连 ≤ 0.2 次/小时；
4. 权益回撤 ≤ 3%；
5. 无未关闭的 CRITICAL；
6. 拟用的新参数（gamma / min_spread_bps / max_inventory / 档位数）已在影子模式重放 ≥ 3 天且不劣于关卡 2 参数。

**本关的主要动作**：资金 30 → 150 USDT，同时把 `max_inventory` 从 0.05 张提到 **0.15 张**（12.1 USDT 名义，λ = 0.08×E），并引入 **每侧 2 档**报价（每档 0.01 张）。

> 提库存上限而不提单笔规模，是为了把 λ 从 1.37 拉回 0.08。这是放大资金时**最容易被忽略的一步**：不加杠杆、不加单笔风险，只加库存缓冲的天花板。

**观察期**：≥ 30 天。

**退出条件**：本关全部指标达标，且 e（滚动 100 笔）不低于关卡 2 的 e（允许相对下降 ≤ 30%，超过说明规模引入了逆向选择，须回到单标的降档）。

### 1.6 关卡 4：多标的并行（150 → 2,000 USDT）

**准入**：

1. 关卡 3 达标；
2. **每个新标的单独过一遍关卡 2 的指标清单**（不是把 BTC 的达标当成全标的达标）——新标的的费率、盘口深度、波动率、跳动最小单位都不同，必须独立标定（见 §5.2）；
3. 新标的已积累 ≥ 30 天影子 + ≥ 7 天模拟盘的独立样本；
4. 跨标的相关性矩阵已计算，簇划分完成（见 §2.5）；
5. 拟分配的权重满足 §2.5 的全部约束（单标的 ≤ 25% E、簇 ≤ 40% E、合并库存名义 ≤ 权益）。

**本关的主要动作**：接入 2~4 个标的，单标的 E_i ∈ [400, 800] USDT，总 E 1,500~2,000 USDT。

**关键新增指标**：

| 指标 | 公式 | 阈值 |
|---|---|---|
| 跨标的库存相关性 | `corr(Δinventory_i, Δinventory_j)` | 任意一对 |ρ| > 0.8 时合并为一个簇，簇内均分资金【建议起始】|
| 跨交易所 mid 一致性 | `\|mid_A/mid_B − 1\|` | ≤ 0.30%【建议起始】（同标的跨所价差含资金费率与库存成本，超阈说明其中一边数据错位或市场分裂）|
| 组合换手倍数 | `Σ_i k_v,i·E_i ÷ E` | 与单标的关卡 3 的 k_v 偏差 ≤ 50% |
| 组合 ASR | `Σ_i ASR_i·E_i ÷ Σ_i E_i` | ≤ 40%，且不得比最差单标的差 > 10 pct |

**退出条件**：≥ 45 天，且**每个标的各自**满足关卡 2 的指标清单。

### 1.7 关卡 5：资金阶梯放大（2,000 → 30,000 USDT）

放大不是一次跳到位，而是**按 §2.6 的资金阶梯表逐档走**。每一档：

1. 资金上调幅度 **≤ 2 倍**（一次翻倍会让 k_v、ASR、深度占用同时跳变，无法归因）；
2. 观察期 ≥ 30 天；
3. 新档位重新标定 `max_inventory`、`sz`（每档手数）、`L_s`（每侧档位数）、刷新周期 T；
4. 触发 §2.8 任一禁止加仓信号 → 立即退回上一档。

**退出条件**：达到目标资金规模后转入常态运营，监控强度不降。

---

## 2. 资金放大方法论

### 2.1 三条单位经济学比率（本方法论的地基）

所有资金决策只认这三个数，不看绝对收益。

```
记号：
  N      单笔名义（USDT）
  δ      报价半价差（bp of mid），当前 4.5 bp【实测代码常量】
  a      逆向选择成本（bp of notional），成交后不利移动的成本
  f      手续费率（bp of notional，单边），Maker 2 bp【实测】
  V      成交名义（USDT）
  E      权益（USDT）
  k_v    日换手倍数 = 日成交名义 ÷ E

【定义 1】净捕获率
  e = (Σ gross_capture − Σ adverse − Σ fee) ÷ Σ V          [bp/名义]

【定义 2】逆向选择损失率
  ASR = Σ adverse ÷ Σ gross_capture                          [比例]

【定义 3】手续费占毛利比
  FGR = Σ fee ÷ Σ gross_capture                              [比例]

【恒等式】
  e = δ·φ − a − f          其中 φ = 实际捕获比例 = gross_capture ÷ (δ·V)
  ⇒ φ = (e + a + f) ÷ δ
  当前反推：e = −0.55, a = 3.05, f = 2.0, δ = 4.5 ⇒ φ = 1.0   ← 价差被完整捕获，问题全在逆向选择
```

> 拆成 δ·φ − a − f 三个分量后，改进路径是清晰的：**三条路同时可行**——(a) 提 φ（更好的队列位置、更短的报价陈旧度、Post-Only 深度优先）；(b) 降 a（更宽的价差、更强的毒性过滤、成交后冷却）；(c) 降 f（换 maker 返佣的交易所/账户层级）。**没有一条是「加更多钱」**。加钱只在 e>0 之后才有意义。

### 2.2 资金放大的根本约束：固定成本摊销 vs 手续费绝对额

手续费与利润都与名义额成比例，**手续费本身不构成最小资金约束**（比例相同）。真正的下限来自三处：

**约束 A：粒度下限（技术可行）**
```
单笔最小下单名义 N_min = 8.08 USDT【实测】
要求单笔风险 ≤ ρ_grain · E  ⇒  E ≥ N_min / ρ_grain
ρ_grain = 5%【建议起始】⇒ E ≥ **162 USDT**
（若换用最小名义更细的标的，如 BTC 现货 0.00001 BTC ≈ 0.81 USDT ⇒ E ≥ 16 USDT）
```
> 含义：**30 USDT 账户在 BTC-USDT-SWAP 上永远无法做「精细做市」**，因为交易所的最小单位决定了你的最小风险粒度是 27% 权益。这不是策略问题，是合约规格问题。
> 30U 账户的正确定位有两个：(a) 作为**测量账户**（关卡 2 的用途），(b) 换到最小名义 ≈ 0.5~1 USDT 的小币现货/小合约标的，用 30U 跑真正的细粒度做市。

**约束 B：信噪比（风险可行）**
```
日净收益   μ_d = E · k_v · e
日 PnL 波动 σ_d = E · λ · σ_1d · ρ_inv
  λ      = 库存名义 ÷ 权益
  σ_1d   = 日内中间价波动（BTC 取 1.5%【建议起始】）
  ρ_inv  = 库存实际占用因子（回测反推 0.85【实测反算】）
日信噪比  SNR_d = μ_d ÷ σ_d = k_v·e ÷ (λ·σ_1d·ρ_inv)
要求 SNR_d ≥ SNR_min = 0.15（日频，对应年化 Sharpe ≈ 2.8）【建议起始】
⇒ λ_max = k_v·e ÷ (SNR_min·σ_1d·ρ_inv) = k_v·e ÷ 0.0019125
```
把 λ_max 换算成资金下限（至少持有 1 手的 q_floor = 1）：
```
E ≥ N_min · q_floor ÷ λ_max
```
**λ_max 与 E 无关**——它由「单位经济性 e、换手 k_v、市场波动 σ_1d」决定，与资金量无关。这意味着：

> **信噪比约束不决定「投多少」，它决定「每个标的最多押多少」。** 资金变大时，正确动作是把同一 λ 摊到更多标的上（§2.5），而不是把单标的 λ 拉高。

**约束 C：运营固定成本摊销（经济可行）**
```
月固定成本 C_op【建议起始】= VPS 12 + 存储/监控 8 + 人工摊销 25 = **45 USDT/月**
月净收益 = E · k_v · e · 30
要求 ≥ C_op  ⇒  E ≥ C_op ÷ (30 · k_v · e)
```

**综合最小可行资金**
```
E_min = max( E_gran = N_min ÷ ρ_grain ,
              E_snr  = N_min · q_floor ÷ λ_max ,
              E_op   = C_op ÷ (30 · k_v · e) )
```

**数值表（ρ_grain=5%, q_floor=1, σ_1d=1.5%, ρ_inv=0.85, SNR_min=0.15, C_op=45, N_min=8.08）**：

| k_v | e (bp/名义) | λ_max | E_gran | E_snr | E_op | **E_min** | 备注 |
|---|---|---|---|---|---|---|---|
| 30 | −0.55（当前实测）| 负值 | 162 | 无解 | 无解 | **不可行** | e<0 ⇒ 放大即加速亏损，必须先修单位经济学 |
| 30 | 0.2 | 0.31 | 162 | 26 | 7,500 | **7,500** | 运营成本成为主导约束 |
| 30 | 0.5 | 0.78 | 162 | 10 | 3,000 | **3,000** | |
| 30 | 1.0 | 1.57 → 取 1.0 | 162 | 8 | 1,500 | **1,500** | λ_max>1 需靠杠杆或高 k_v |
| 30 | 2.0 | 3.14 → 取 1.0 | 162 | 8 | 750 | **750** | |
| 60 | 1.0 | 1.0（截断）| 162 | 8 | 750 | **750** | k_v 翻倍直接减半 E_op |
| 128 | 1.0 | 1.0（截断，实测 k_v）| 162 | 8 | 375 | **375** | 若实盘 k_v 能维持 128 |
| 128 | 0.5 | 0.67 | 162 | 12 | 750 | **750** | |

> **这张表的用途**：把「我要投多少钱」变成「我的 e 和 k_v 允许我投多少钱」。当前实测 e = −0.55 bp ⇒ **E_min 无解**，这不是保守，是数学。资金阶梯必须等 e 转正。
> 另外注意：**提高 k_v 比提高 e 对 E_min 的杠杆更大**（k_v 翻倍 ⇒ E_op 减半）。而 k_v 由「单笔名义 / 队列位置 / 刷新频率」决定，是一个纯工程量 —— 也就是说 **在 e 转正之前，改善 k_v 本身不会救活账户**（k_v 越大，亏损越快），它只有在 e>0 之后才是放大杠杆。

### 2.3 杠杆：什么时候合理，什么时候是自残

**原理**：杠杆放大的是**库存名义与权益之比 λ**，不是收益。收益按名义线性增长，风险也按名义线性增长，期望值不变：
```
μ_d = E·k_v·e         （与杠杆无关）
σ_d = E·λ·σ_1d·ρ_inv （λ 随杠杆线性放大）
⇒ Sharpe 与杠杆无关；杠杆只降低 SNR。
```
**结论 1：杠杆不能修复粒度问题。** 30U 下用 3× 杠杆，单笔仍是 8.08 USDT = 27% 权益（名义/权益比不变），只是保证金占用变成 9%。加杠杆不改变 C1 约束，只改变破产速度。

**结论 2：杠杆只在一个区间有意义**——当 λ_max > 1 时，说明「单位经济性允许的库存名义超过权益」，此时跨仓/杠杆是把闲置保证金变成可用保证金，**不增加风险预算**。由 §2.2 表：e=1 bp、k_v=30 时 λ_max = 1.57，即 λ_max > 1。

**杠杆使用规则（建议）**：

| 规则 | 内容 | 依据 |
|---|---|---|
| L1 | λ_max ≤ 1 时，**禁止使用杠杆**（`td_mode = cross`，leverage=1）| 杠杆无收益只有风险 |
| L2 | 目标 λ 取 `min(λ_max, 0.4)`，保留 60% 保证金缓冲 | 强平距离与保证金占用率（§3.2）留余量 |
| L3 | 允许 λ_max > 1 时，最大杠杆 `L_max = λ_max ÷ λ_target`，且 `L_max ≤ 2` | 2× 是跨仓实盘常见的舒适上限【建议起始】|
| L4 | 杠杆**不得**用于「放大收益」，只用于「在资金不足时把 λ 从粒度约束中解放出来」| §2.2 结论 |
| L5 | 提高杠杆的准入：E ≥ 500 USDT 且关卡 3 达标 | 小资金加杠杆是本项目历史踩坑区（旧版 dayuan 3× 下 40.96 h 亏 72.6% 源于手续费【实测】）|

**当前状态**：30U + `max_inventory 0.05`（λ=1.37）**已经等价于 1.37× 杠杆**，且是「被动杠杆」——由合约的 0.01 张粒度 + 库存上限强制产生，不是主动选择。关卡 3 的第一个动作就是把它降到 0.08。

### 2.4 多标的资金分配

**分配目标**：在总风险预算内最大化组合净收益，且不让单标的/单簇吃掉组合。

**方法：逆方差 + 相关性调整的风险平价（Risk Parity, 近似 ERC）**

```
输入：
  σ_i      = 标的 i 的滚动日 PnL 波动率（由实盘逐笔 PnL 聚合，窗口 30 个交易日）
  ρ_ij     = 标的 i,j 的库存变化相关性（Δinventory 序列，窗口 30 日）
  E_i      = 分配给 i 的权益
  λ_target = 目标库存名义比（统一取 min(λ_max, 0.4)）

步骤 1（粗配）：
  w_i = (1/σ_i²) ÷ Σ_j (1/σ_j²)                    # 逆方差

步骤 2（相关性聚簇）：
  对 |ρ_ij| > ρ_cluster = 0.8 的对做并查集聚类，得到簇 C_1..C_m
  簇内均分： w_i ← w_i ÷ |C(i)|

步骤 3（上限与再分配，迭代 ≤ 10 次）：
  若 w_i > w_max = 25%（单标的）或 簇权重 > 40%：
      把超出部分按 (1/σ²) 比例退回给未触顶的标的/簇

步骤 4（可行性校验）：
  对每个 i：E_i = E · w_i
  库存名义 = λ_target · E_i，必须能被该标的的挂单容量承载：
      L_s,i · sz_i · N_min,i ≥ λ_target · E_i
  否则该标的的 w_i 被下调，差额再分配。

输出：{E_i}, 且 Σ E_i = E
```

**σ_i 的可得性是关卡 4 的前置条件**：必须先有单标的 ≥ 30 天实盘样本（关卡 3 的产出）。没有 σ_i 就无法做风险平价，只能用等权（**等权是最差选择**，因为它把资金给了波动最大的标的）。

**额外约束**：
- 单标的 ≤ 25% E；单簇 ≤ 40% E【建议起始】；
- 我们在某标的的日均名义 ≤ 该标的日均成交额的 **1%**（流动性占用上限，避免自身成为逆向选择的来源）【建议起始】；
- 多标的共用同一保证金池时，**合并计算 λ**：`Σ_i λ_i·E_i ≤ E`；
- 同交易所有同一标的的多个账户 → 视为同一标的合并（否则相关性计算失效）。

### 2.5 资金阶梯表

参数说明：`L_s` = 每侧档位数，`sz` = 每档手数，`N_min` = 8.08 USDT（0.01 张），`λ` = 库存名义/权益，`T` = 刷新周期。

| 档 | E (USDT) | 标的数 | E_i | λ | max_inventory (手) | L_s × sz | 单笔名义（占权益）| 并发挂单 | T | 订单速率 | 预期日净收益 μ_d |
|---|---|---|---|---|---|---|---|---|---|---|---|
| T0 关卡2 | 30 | 1 | 30 | 1.37 ⚠ | 5【实测】| 1×1 | 8.08（27%）⚠ | 2 | 2 s | 1.0 /s | −0.21【实测反推】|
| T1 关卡3 | 150 | 1 | 150 | 0.08 | 1（0.15 张）| 2×1 | 8.08（5.4%）| 4 | 2 s | 2.0 /s | 150·k_v·e，k_v=30,e=1bp ⇒ **0.45** |
| T2 | 500 | 1 | 500 | 0.40 | 25 | 3×2 | 16.16（3.2%）| 6 | 3 s | 2.0 /s | **1.50** |
| T3 | 2,000 | 2 | 1,000 | 0.40 | 49 | 4×3 | 24.24（1.2%）| 8 | 4 s | 2.0 /s | **6.00** |
| T4 | 6,000 | 4 | 1,500 | 0.40 | 74 | 5×4 | 32.32（0.54%）| 10 | 6 s | 1.7 /s | **18.0** |
| T5 | 15,000 | 6 | 2,500 | 0.40 | 123 | 6×6 | 48.48（0.32%）| 12 | 8 s | 1.5 /s | **45.0** |
| T6 | 30,000 | 8 | 3,750 | 0.40 | 185 | 7×7 | 56.56（0.19%）| 14 | 10 s | 1.4 /s | **90.0** |

（μ_d 取 k_v=30、e=1.0 bp 为【建议起始】基准；每次换档必须用实测 k_v、e 重算。）

**同时受三条容量/物理约束夹逼**：

1. **下单速率**：OKX 登录限约 10 orders/2s【实测：需在 demo 实测校准】，保守取 **5 orders/s** ⇒ `2·L_s ÷ T ≤ 5`。
2. **报价陈旧度上限**（防止 stale quote 被毒性流打穿）：
   ```
   报价存活期内的预期不利移动 ≈ σ_1min · √(T/60)
   要求 ≤ 0.5·δ（允许损失一半价差）
   ⇒ T_max = 60 · (0.5·δ ÷ σ_1min)²
   σ_1min = 5 bp（BTC 1 分钟实现波动）【推断】
   δ = 4.5 bp ⇒ T_max = 60·(2.25/5)² = 12.1 s
   δ = 6.0 bp（加宽以承载规模）⇒ T_max = 60·(3.0/5)² = 21.6 s
   ```
   表中各档 T 均满足 T ≤ T_max。
3. **挂单容量**：单标的能承载的库存名义 = `L_s · sz · N_min`，必须 ≥ `λ·E_i`。表 T6：7×7×8.08 = 396 USDT ≫ 0.4×3,750 = 1,500 USDT ⇒ **容量不足**！因此 T6 单标的必须提高 sz 至 27 手（218 USDT/档，7×27×8.08 = 1,527 USDT ✓），此时单笔名义占权益 218/3750 = 5.8% ⇒ 触及 ρ_grain ⇒ **必须分散到更多标的或降低 λ**。
   > 这就是**关卡 4（多标的）存在的量化原因**：单标的的「档位数 × 速率 × 陈旧度」三约束合起来，给出了单标的资金天花板。

**可接受延迟水平（按档）**：

| 档 | 决策陈旧度上限（决策时刻 − 最新盘口事件） | 原因 |
|---|---|---|
| T0/T1 | p95 ≤ 300 ms | 小资金对延迟最敏感（半价差 4.5 bp，1 秒的 BTC 波动就吃掉 8 bp）【推断】|
| T2 | p95 ≤ 500 ms | 允许 3 s 刷新周期 |
| T3 | p95 ≤ 800 ms | |
| T4+ | p95 ≤ 1,200 ms | 大资金以更宽价差换队列位置，对陈旧度容忍度更高 |

超过上限的动作：**降低 L_s 或提高 T**（而不是继续放量）。

### 2.6 回撤预算与熔断阶梯

**回撤预算**（按权益百分比，锚定账户峰值权益）：

| 层级 | 回撤阈值 | 自动动作 | 恢复条件 | 人工介入 |
|---|---|---|---|---|
| L0 常态 | 0 ~ 0.5% | 全速运行 | — | 否 |
| L1 警戒 | 0.5 ~ 1.0% | **暂停新开仓**（只允许减仓/平仓），报价带加宽 50% | 回到 0.4% 且持续 1 h | 否 |
| L2 降级 | 1.0 ~ 2.0% | **只减不加**：撤掉所有买单/卖单，只留平库存的单 | 回到 0.8% 且持续 4 h | 否 |
| L3 熔断 | 2.0 ~ 3.0% | **完全停机**：撤单、平仓、进程退出 | 人工复核后重启 | **是** |
| L4 事故 | > 3.0% | 停机 + 冻结所有自动化 + 上报事故 | 人工 | **是** |

> 阈值按权益百分比定义 ⇒ **资金放大时绝对金额放大、百分比不变**，天然实现了「越大越保守的绝对缓冲」。
> 关卡 2 的绝对上限是 3%（30U 上 = 0.9 USDT），这是本项目最紧的一档；关卡 5 可放宽到 5%（因为分散度提高、单标的敞口占比下降）。

**熔断阶梯实现（伪代码，进 `run_live.py` 主循环，判据用 REST 拉的权益，不可用 WS 缓存）**：
```python
def drawdown_tier(equity: float, peak_equity: float) -> str:
    dd = (peak_equity - equity) / max(peak_equity, 1e-9)
    if dd >= 0.03: return "L4_STOP"
    if dd >= 0.02: return "L3_HALT"
    if dd >= 0.01: return "L2_REDUCE_ONLY"
    if dd >= 0.005: return "L1_NO_NEW"
    return "L0_NORMAL"
```
`peak_equity` 必须在每次降级/重启后**重新校准**（取重启后 1 小时内权益最大值），否则一次历史回撤会让系统永久停机。

### 2.7 何时不该放大（禁止加仓信号清单）

以下任一信号出现 ⇒ **立即冻结加仓**，并按括号内动作处理。阈值为【建议起始】，`e` 相关项需按关卡实测重标定。

| # | 信号 | 阈值 | 动作 |
|---|---|---|---|
| S1 | 手续费占毛利比 FGR | 连续 3 天 > 50% | 冻结加仓，回退一档，检查是否有 taker 混入 |
| S2 | 手续费绝对额 / 毛利 | 连续 3 天 > 100% | **降级 L2**，只减不加 |
| S3 | Maker 比例 | < 99%（WARN）/ < 95%（CRITICAL）/ < 90%（HALT）| <90% 立即停机 |
| S4 | 逆向选择损失率 ASR | 较关卡基线上升 > 20%（相对值）或 > 40%（绝对值）| 冻结加仓，加宽价差 / 收紧冷却 |
| S5 | 净捕获率 e | 滚动 100 笔 ≤ 0 | **冻结加仓**（这是最重要的一条）|
| S6 | e 的衰减 | e_live < 0.5 · e_backtest | 冻结加仓，回退一档重新标定 |
| S7 | 队列保持率 | < 70% | 冻结加仓：说明我们在打价格战而不是占位 |
| S8 | 拒单率 | > 5% | 冻结加仓，降低下单速率与档位数 |
| S9 | WS 断线率 | > 1 次/小时 | 冻结加仓，先修连接 |
| S10 | 决策延迟 p95 | 超过该档上限 | 冻结加仓 |
| S11 | 权益回撤 | 触达 L1/L2/L3 任一层 | 按 §2.6 熔断阶梯 |
| S12 | 库存越界 | `\|inventory\| > max_inventory` 一次 | CRITICAL，降级 L2 |
| S13 | 观察期未满 | 任一档位观察期未满 | 禁止进档 |
| S14 | 未关闭的 CRITICAL | 存在 | 禁止进档 |
| S15 | PSI / KS 漂移 | PSI > 0.25 或 KS p < 0.01 | 冻结加仓，重训或回退特征版本 |
| S16 | 单标的占比 | > 25% E（关卡 5）/ > 40% 簇 | 禁止加仓，先再平衡 |

**加仓决策函数（可执行）**：
```python
def may_scale(current: Tier, next_tier: Tier, health: Health) -> tuple[bool, str]:
    if any(s.triggered for s in health.blockers):          # S1..S16
        return False, f"blocked_by:{[s.id for s in health.blockers if s.triggered]}"
    if health.tier < current:                               # 已降级
        return False, "downgraded"
    if next_tier.observation_days < 30:
        return False, "observation_not_finished"
    if health.e_rolling_100 <= 0:
        return False, "e_not_positive"
    # 资金上限硬约束：E_next ≤ E_min(k_v_measured, e_measured)
    e_min = max(E_gran, E_snr, E_op)                       # §2.2 公式
    if next_tier.E > e_min:
        return False, f"below_min_viable_capital:{e_min:.0f}"
    return True, "ok"
```

### 2.8 放大路径小结（可执行清单）

1. 先把 e 从 −0.55 bp 打到 **> +0.5 bp**（手段：加宽报价降 a、提升队列位置提 φ、Post-Only 深度优先）。
2. 用 §2.2 公式算出 **E_min(k_v, e)**，这就是你最多能投到哪一级；不要凭感觉。
3. 按 §2.5 阶梯表逐档（≤ 2 倍/档），每档观察 ≥ 30 天。
4. 每档重测 k_v、e、ASR、FGR、队列保持率，**用实测值替换表中建议值**。
5. 任何 S1~S16 触发 → 冻结或降档。
6. 多标的扩展只在单标的关卡 3 达标后进行，且每标的独立达标。

---

## 3. 实时监控体系（三层）

### 3.0 架构（1 核 1G 可跑）

```
L1 交易进程层   ← 进程内埋点，写 JSON 状态文件（原子写：写 tmp + rename）
   ↓
L2 账户资金层   ← 独立守护进程每 30 s 拉交易所 REST，写账户 JSON
   ↓
L3 策略健康层   ← 每 5 min 跑一次统计（复用 cron_accountbot3_ml_guard.py 的形态）
   ↓
告警网关        ← 单个 Python 守护进程，读三层的 JSON，算规则，发 Telegram
```

**为什么不是 Prometheus + Grafana**：1 核 1G 上 Prometheus + Grafana + node_exporter 约需 700 MB~1.2 GB 常驻，会把交易进程挤出内存并制造 10~50 ms 的抖动（实测抖动来源）【实测：抖动 10~50 ms】。**降级方案就是本项目现有形态**：单个 Python 守护进程 + JSON 状态文件 + Telegram 告警。状态文件是唯一事实源，可被任何工具读取，也方便事后审计。

### 3.1 L1 交易进程层（进程内）

| # | 监控项 | 计算公式 | 采样/统计窗口 | 阈值 | 级别 |
|---|---|---|---|---|---|
| L1.1 | 心跳新鲜度 | `now − status_file_mtime` | 5 s | > 10 s → WARN；> 30 s → CRITICAL；> 120 s → HALT | WARN/CRIT/HALT |
| L1.2 | 主循环耗时 | `t_end − t_start`（每次迭代）| p50/p95/p99 滚动 100 次 | p95 > 200 ms → WARN；p99 > 500 ms → CRITICAL | WARN/CRIT |
| L1.3 | 事件循环抖动 | `实际唤醒时刻 − 期望唤醒时刻` | p99 | > 50 ms → WARN；> 150 ms → CRITICAL | WARN/CRIT |
| L1.4 | 消息处理延迟 | `本地接收时刻 − 交易所事件时间戳` | p50/p95/p99 | p95 > 300 ms → WARN（按档位上限调整）| WARN |
| L1.5 | 盘口快照陈旧度 | `now − last_book_update_ts` | 连续 | > 1,000 ms → WARN；> 5,000 ms → CRITICAL（视为断流）| WARN/CRIT |
| L1.6 | WS 连接状态 | `public_ws.connected ∧ private_ws.connected` | 1 s | 任一断开 → WARN | WARN |
| L1.7 | WS 重连次数 | 累计计数 + 滚动 1 h | 1 h 窗口 | > 1 次/h → WARN；> 3 次/h → CRITICAL | WARN/CRIT |
| L1.8 | 序列号缺口 | OKX `books5` 为快照无 seq【实测：订阅频道为 books5/trades】⇒ 改用 **事件时间戳单调性 + 心跳缺失** 判定：检测到 `uTime` 回退或 > 1 s 无事件 | 连续 | 检出 → CRITICAL（立即对账 REST 持仓/挂单）| CRIT |
| L1.9 | 下单数 | `places_total` | 5 min | — | INFO |
| L1.10 | 撤单数 / 撤改单数 | `cancels_total`；`repost = cancels ÷ max(places,1)` | 5 min | `repost > 1.5` → WARN（撤单多于下单说明报价频繁失效）| WARN |
| L1.11 | 成交数 | `fills_total`（仅私有 WS `state=="filled"` 计入）| 5 min | — | INFO |
| L1.12 | 拒单数与原因分布 | `rejects_total`；`reject_reason` 计数直方图 | 5 min | 拒单率 > 2% → WARN；> 5% → CRITICAL；出现鉴权/限频类原因 → 立即 CRITICAL | WARN/CRIT |
| L1.13 | **队列保持率** | `queue_hold_cycles ÷ (queue_hold_cycles + repost_cycles)`，`queue_hold` = 本轮发现原挂单仍在且偏离 ≤ 容差 | 滚动 1 h | < 80% → WARN；< 70% → 冻结加仓（S7）| WARN |
| L1.14 | **Maker 比例（实时）** | `maker_fills ÷ total_fills`，滚动 100 笔 | 实时 | < 99% WARN；< 95% CRIT；< 90% HALT | 多级 |
| L1.15 | 库存 | `inventory`（张）、`inventory_notional = |inv|·N_min` | 每 tick | `\|inv\| > max_inventory` → CRITICAL（立即撤单+只减不加）| CRIT |
| L1.16 | 库存周转 | `turnover = Σfill_notional ÷ (2·avg_abs_inventory)`，日频 | 1 d | < 1 /日 → WARN（库存粘住 = 持仓赌注）| WARN |
| L1.17 | 报价价差分布 | `half_spread_bps` 的 p5/p50/p95 | 滚动 1000 | p5 < 4.5 bp → WARN（门槛被绕过）；p95 > 12 bp → INFO（激增保护）| WARN |
| L1.18 | 报价相对盘口位置 | `bid_offset_bp = (mid − bid) ÷ mid`，`ask_offset_bp = (ask − mid) ÷ mid` | 每 tick | 任一 < 0（跨过中间价）→ CRITICAL（破坏 Maker 保证）| CRIT |
| L1.19 | 报价与中间价偏离 | `\|(bid+ask)/2 − mid\| ÷ mid` | 每 tick | > 5 bp → WARN（保留价格漂移过大）| WARN |
| L1.20 | 特征计算耗时 | `compute_gk_vol` 单次耗时 | 每 15 s | > 100 ms → WARN；> 300 ms → CRITICAL | WARN/CRIT |
| L1.21 | 模型推理耗时 | `infer_ms`（LGB 3 模型：drift/tox_down/tox_up） | 每 tick | p95 > 50 ms → WARN；> 200 ms → CRITICAL | WARN/CRIT |
| L1.22 | 模型文件可用性 | `os.path.exists(checkpoints/*.txt)` + 加载成功 | 每 5 min | 缺失 → CRITICAL（回退规则模型或停机）| CRIT |
| L1.23 | **mark-out（逆向选择直接测量）** | 成交后 Δmid（+1s/+5s/+30s），`adverse_bps = 方向·Δmid` | 每笔成交 | 滚动 100 笔均值 > 2 bp → WARN；> 3 bp → CRITICAL | WARN/CRIT |
| L1.24 | 捕获比例 φ | `gross_capture ÷ (δ·notional)` | 滚动 100 笔 | < 0.6 → WARN（价差没被完整捕获，队列位置差）| WARN |

**埋点实现要点（不增加进程数）**：在 `run_live.py` 现有 `status_data` 字典上扩展即可，写盘改成**原子写**：
```python
def atomic_write_json(path: str, payload: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)      # 读者永远看到完整 JSON
```
当前实现是直接 `open(..., "w")` 覆盖写，读者可能读到半截 JSON → 监控误报。这是 L1.1 心跳误报的常见来源，先修掉。

### 3.2 L2 账户与资金层（交易所 API）

数据源：OKX REST `GET /api/v5/account/balance`、`/api/v5/account/positions`、`/api/v5/trade/fills`、`/api/v5/public/funding-rate`、`/api/v5/public/funding-rate-history`；私有 WS `account` 频道（已订阅【实测：现有实现】）作为实时源，REST 作对账。

| # | 监控项 | 计算公式 | 频率 | 阈值 | 级别 |
|---|---|---|---|---|---|
| L2.1 | 权益 | `totalEq` | 30 s | 与上次变化 > 5% → WARN | WARN |
| L2.2 | 可用余额 | `availBal` | 30 s | `availBal / equity < 0.2` → WARN（无缓冲）| WARN |
| L2.3 | 保证金占用率 | `margin_used / equity`，`margin_used = equity − availEq`（cross 近似）| 30 s | > 30% WARN；> 50% CRITICAL；> 70% HALT | 多级 |
| L2.4 | 未实现盈亏 | `Σupl` | 30 s | `\|upl\| / equity > 5%` → WARN | WARN |
| L2.5 | 已实现盈亏（今日/累计） | 由 fills 逐笔 FIFO 归集 | 5 min | 日亏损 > 日预算（§2.6）→ 触发降级 | 多级 |
| L2.6 | 资金费率计提 | 累计 `funding_fee`；`funding_rate × notional × 8h` 预期值 | 8 h | 实际/预期 > 2 → WARN（持仓方向与费率方向不利）| WARN |
| L2.7 | 资金费率偏离 | `actual_funding − expected_funding` | 8 h | 绝对值 > 0.01% 名义 → INFO 记录 | INFO |
| L2.8 | 手续费累计（今日） | `Σfee`（fills 明细）| 5 min | — | INFO |
| L2.9 | **日成交名义（反推）** | `V_day = Σfee ÷ f_maker`（99.5% maker 时误差 < 0.5%）| 1 h | 与 k_v 目标偏差 > 50% → WARN | WARN |
| L2.10 | **FGR 手续费占毛利比** | `Σfee ÷ Σgross_capture` | 1 h | > 50% WARN；> 100% CRITICAL | WARN/CRIT |
| L2.11 | **净捕获率 e** | `(Σgross − Σadverse − Σfee) ÷ ΣV` | 滚动 100 笔 | ≤ 0 → 冻结加仓 | WARN |
| L2.12 | ASR 逆向选择损失率 | `Σadverse ÷ Σgross_capture` | 1 h | > 40% WARN；> 60% CRITICAL | WARN/CRIT |
| L2.13 | 强平距离 | `1 − margin_used/equity`（cross 近似）；精确口径用交易所 `liqOrdPx` | 30 s | < 30% → WARN；< 15% → CRITICAL | WARN/CRIT |
| L2.14 | 权益 vs 内部账本偏差 | `exchange_equity − (cash + Σposition_mtm + realized)` | 5 min | 偏差 > 0.5 USDT 或 > 1% → CRITICAL（记账不一致）| CRIT |
| L2.15 | 孤儿挂单 | `exchange_pending − local_pending` | 1 min | > 0 → WARN；持续 5 min → CRITICAL（撤掉孤儿单）| WARN/CRIT |

### 3.3 L3 策略健康层（统计推断）

| # | 监控项 | 计算公式 | 窗口 | 阈值 | 级别 |
|---|---|---|---|---|---|
| L3.1 | 滚动胜率 | `wins ÷ N`，按 FIFO 平仓轮次配对 | 滚动 100 轮 / 1 d | 与关卡基线差 > 10 pct → WARN | WARN |
| L3.2 | 滚动盈亏比 | `avg_win ÷ avg_loss` | 滚动 100 轮 | < 0.8 → WARN | WARN |
| L3.3 | 滚动夏普 | `mean(daily_pnl) ÷ std(daily_pnl) × √365` | 30 d | < 0.5 → WARN；< 0 → 冻结加仓 | WARN |
| L3.4 | 滚动 Profit Factor | `Σwin ÷ Σloss` | 滚动 100 轮 | < 1.0 → WARN | WARN |
| L3.5 | **ASR（滚动）** | 同 L2.12，但按 100 笔滚动 | 100 笔 | 见 L2.12 | WARN/CRIT |
| L3.6 | 特征分布漂移 PSI | 见下 | 1 d vs 基线 30 d | PSI < 0.10 稳定；0.10~0.25 WARN；> 0.25 冻结加仓 | WARN/CRIT |
| L3.7 | 模型预测分布漂移 | KS 检验（基线 vs 实时窗） | 1 d | `p_value < 0.01` → WARN；`KS > 0.2` → CRITICAL | WARN/CRIT |
| L3.8 | 预测均值漂移 | `E[p_tox_up] − E_base[p_tox_up]`、`E[p_tox_down] − ...` | 1 d | 偏移 > 0.15 → WARN | WARN |
| L3.9 | 与回测基线偏离 | 每笔净收益分布双样本 KS + 均值 t 检验 | 1 d vs 回测分布 | `KS p < 0.01` → WARN；`e_live < 0.5·e_bt` → 冻结加仓 | WARN |
| L3.10 | 换手倍数漂移 | `k_v = V_day ÷ E` | 1 d | 与关卡基线偏差 > 50% → WARN | WARN |
| L3.11 | 策略参数版本一致性 | 记录的 `config_hash` vs 运行中的 | 1 d | 不一致 → CRITICAL | CRIT |
| L3.12 | 特征/模型版本一致性 | 文件 mtime + sha256 前 8 位 | 1 d | 与注册表不符 → CRITICAL | CRIT |

**PSI 公式**：
```
PSI = Σ_{k=1..K} (A_k − B_k) · ln(A_k / B_k)
  A_k = 实时窗口（今日）落在第 k 分位的比例
  B_k = 基线窗口（上线前 30 天或最近 30 天）落在第 k 分位的比例
  K = 10（等频分位）
  约定：A_k = 0 时该项取 0.001 近似；PSI > 0.25 视为分布已显著改变
```
监控的特征：`annual_gk_vol`、`rolling_ofi_60s`、`ofi_norm`、`ma20_deviation`、`mu_pred`、`adx14`、`base_half_spread_bps`。
> 注意：`rolling_ofi_60s` 与 `adx14` 在实盘的分布**必然**与回测不同（回测 OFI 来自 1m bar 合成、实盘来自 60 s 逐笔 OFI）。因此基线必须用**实盘影子/模拟盘**数据重算，不能用回测分布。直接把回测分布当基线会天天报警。

**回测偏离的正确用法**：不是比绝对收益，而是比 **per-fill-leg 净 bps 分布**。
```
live_net_bps_i = (gross_i − adverse_i − fee_i) ÷ notional_i × 10000
bt_net_bps_j  = 同口径的回测分布
双样本 KS 检验 + 均值差 t 检验；并计算 ratio = mean(live)/mean(bt)
```

### 3.4 L3 依赖的增量代码（当前缺失，必须补）

| 需要的能力 | 当前状态 | 最小实现 |
|---|---|---|
| 成交时刻的 mid 快照 | 缺失 | 下单时把 `mid_px` 与 `ts` 存进订单上下文；成交事件携带回来 |
| mark-out（+1s/+5s/+30s） | 缺失 | 用 `okx_ws_manager` 的 `get_latest_book()["mid"]` 采样，写 `markout` 环形缓冲（deque(maxlen=1000)）|
| gross_capture 统计 | 缺失 | `gross_i = (sign_buy ? mid − fill_px : fill_px − mid) × notional` |
| adverse 统计 | 缺失 | `adverse_i = 方向 × (mid_{t+5s} − mid_at_fill) × qty`（用 5s 做主口径，同时保留 30s）|
| 逐笔 FIFO 轮次盈亏 | 缺失 | 维护 FIFO 队列（buy/sell 两侧），配对出「轮次」供 L3.1/L3.2 使用 |
| 特征基线快照 | 缺失 | 每日把特征向量写 `baseline/features_YYYYMMDD.parquet`，保留 30 天 |
| 预测值记录 | 部分（`mu_pred` 有）| 记录 3 个模型的完整输出概率 |

---

## 4. 告警与响应

### 4.1 分级定义

| 级别 | 含义 | 触发原则 | 自动动作 | 通知 |
|---|---|---|---|---|
| **INFO** | 记录性，不需人看 | 常规心跳、成交、每日汇总 | 无 | 写入日志；每日 08:00 汇总发一次 Telegram |
| **WARN** | 需要人知道，但系统还能自愈 | 单一指标越界，或多项指标同时接近阈值 | 可自动降级一档（降级类 WARN）；不可自动修复的仅记录 | Telegram，允许合并 |
| **CRITICAL** | 业务受损，需要尽快介入 | 记账不一致、库存越界、跨价失效、延迟飙升、模型缺失 | 自动降级 / 停机 + 撤单 | Telegram 立即（去抖后），带诊断快照 |
| **HALT** | 系统已停或即将造成不可逆损失 | 权益回撤触 L3/L4、Maker < 90%、WS 断线 > 5 min、强平距离 < 15% | 完全停机（撤单 + 平仓 + 退出）| Telegram + 短信/电话（需人工重启）|

**级联关系**：`WARN → CRITICAL` 的升级由「持续时间」与「影响面」共同决定：
- WARN 持续 > 3 个采样窗口未恢复 → 升级 CRITICAL；
- 任一 CRITICAL 未在 15 min 内被处理 → 升级 HALT（若该 CRITICAL 属可自动降级类，先降级再升级）。

### 4.2 告警去重与抑制（避免告警风暴）

1. **指纹（fingerprint）**：`sha1(level + rule_id + venue + symbol + direction)`。同一指纹在抑制窗口内只发一次。
2. **抑制窗口**：INFO 无窗口；WARN 15 min；CRITICAL 5 min；HALT 无窗口（每次都发）。
3. **状态机去重**：同一规则只在该规则**状态翻转**时发消息（OK→WARN→OK→WARN），恢复时发一条恢复通知，而不是每次采样都发。
4. **迟滞（hysteresis）**：升级阈值 > 降级阈值。例如 Maker 比例：升 CRITICAL < 95%，降回 WARN 需 > 97%，降回正常需 > 99%。防止在阈值附近抖动刷屏。
5. **风暴保护**：单通道 10 min 内最多 5 条；超出后聚合为一条「本窗口 N 条告警摘要」，并把同族规则的明细附在后面。
6. **优先级抢占**：HALT > CRITICAL > WARN，WARN 队列在 CRITICAL 到来时丢弃未发送项。
7. **断网缓冲**：Telegram 发送失败不阻塞主循环；失败消息写入本地 `alerts_pending.jsonl`，恢复后补发（补发时合并为一条摘要）。
8. **值班静默**：非 CRITICAL 在 02:00~07:00（用户时区）只写日志不发 Telegram（除非 HALT）。

**实现骨架**（`ops/alert_gateway.py`）：
```python
class AlertState:
    def __init__(self, path: str):
        self.path = path
        self.st = load_json(path, {})          # fingerprint -> {level, last_sent_ts, state}
    def evaluate(self, rule_id, venue, symbol, level, now_ts) -> Optional[str]:
        fp = sha1(f"{rule_id}|{venue}|{symbol}|{level}")
        prev = self.st.get(fp, {})
        window = SUPPRESS_SEC[level]             # INFO=inf, WARN=900, CRIT=300, HALT=0
        if prev.get("state") == level and now_ts - prev.get("last_sent_ts", 0) < window:
            return None                          # 抑制
        if prev.get("state") != level:
            self.st[fp] = {"state": level, "last_sent_ts": now_ts}
            save_json(self.path, self.st)
            return render(rule_id, venue, symbol, level)
        return None
```

### 4.3 Runbook（值班响应手册）

每个场景三段：**诊断 → 处置 → 恢复验证**。

#### R1 WebSocket 断线

**诊断**
1. `status.json` 看 `ws_reconnect_count_1h`、`last_book_age_ms`；
2. `docker logs` 找 `ConnectionClosed` / `websockets.exceptions`；
3. 本地 `ping`/REST 测连通性：`curl -s -o /dev/null -w '%{time_total}' https://www.okx.com/api/v5/public/time`（记录 RTT）；
4. 区分：本地网络问题 vs OKX 侧问题 vs 鉴权问题（后者日志里有 `code != 0`）。

**处置**
- 单次断线（< 5 s）：自动重连即可，记录 INFO；
- 持续断线 > 60 s：**撤掉所有挂单**（避免挂单在无监控状态下被毒性流打穿），进入 L2「只减不加」；
- 私有 WS 断（拿不到成交）而公开 WS 正常：**立即停止一切下单**（无法确认真实成交 → 会重复下单），只允许撤单；
- RTT 持续 > 300 ms：切到 REST 兜底撤单路径；若 REST 也超时 → HALT。

**恢复验证**
1. 私有 WS `login` 成功且 `orders`/`account` 频道有推送；
2. `last_book_age_ms < 1000` 持续 60 s；
3. **强制对账**：`GET /api/v5/trade/orders-pending` + `GET /api/v5/account/positions` 与本地账本一致，孤儿单 = 0；
4. 重新挂单前，先用 1 笔最小单验证成交回报链路正常。

#### R2 序列号缺口 / 事件时间戳异常

**诊断**
1. 检测源：`uTime` 回退 或 > 1 s 无盘口事件；
2. 拉 REST `books` 与本地缓存比较 mid，偏差 > 1 bp ⇒ 本地数据已错；
3. 检查私有 `orders` 事件是否也有缺口（决定是否只是公开流问题）。

**处置**
- 公开流缺口 → 停止报价（用 REST 快照做一次性校准后恢复），撤单重挂；
- 私有流缺口 → **进入 HALT 候选**：先撤单，再对账持仓/挂单/成交；确认无重复下单风险后才恢复；
- 任何缺口都触发一次**完整对账**（挂单 + 持仓 + 近 200 笔成交）。

**恢复验证**：本地 mid 与 REST mid 连续 60 s 偏差 < 0.5 bp；私有流恢复后 5 min 内无新缺口；对账差异 = 0。

#### R3 模型文件缺失 / 加载失败

**诊断**
1. `ls -l checkpoints/`；`sha256sum` 与注册表比对；
2. 加载错误信息（特征维度不匹配 vs 文件缺失）；
3. 当前 `checkpoints/lgb_*.txt` 训练于 2026-10-25、特征逻辑已不同步【实测：共享上下文】⇒ 加载成功也可能是**错配**。

**处置**
- 文件缺失 → **不允许回退到「无模型」继续下单**（模型缺失会让毒性判断失效，风险不可控）→ 撤单，进入 L2；
- 有备份版本（`checkpoints/<name>.txt.bak` + `registry.json`）→ 回滚到上一版本；
- 无备份 → 降级为「只减不加」，人工介入；
- **强制要求**：上线前把 `checkpoints/` 纳入版本控制（git-lfs 或 tar 快照），并保留至少 2 个历史版本。

**恢复验证**：模型加载成功 + 连续 10 次推理输出在合理区间（`mu_pred ∈ [-2, 2]`、`p_tox ∈ [0,1]`）+ 特征维度校验通过。

#### R4 特征计算溢出 / NaN

**诊断**
1. `annual_gk_vol` 是否 ∈ [0.05, 2.5]、`|ofi_norm| ≤ 3.5`、`|ma20_dev| ≤ 5`、`|mu_pred| ≤ 3`（这四条已在 `cron_accountbot3_ml_guard.py` 中【实测存在】）；
2. 检查 K 线拉取是否返回空/异常（`get_candles` 返回空列表 → `cached_gk_vol` 保持旧值，但 `cached_ma20_dev` 等也会保持旧值，**不会 NaN**，但会静默使用陈旧特征）；
3. 若真出现 NaN：`max()`/`np.clip` 边界未覆盖（如 `np.log` 负数）。

**处置**
- NaN/Inf → **本轮不产生新报价**（不是用默认值），撤掉旧单；
- 特征陈旧（超过 3 个刷新周期未更新）→ 停报价；
- 检查 `compute_gk_vol` 中 `log_hl`/`log_c` 的定义域，并加断言；
- 修 `bfill()` 的使用（回测侧已整改过【实测：kaggle_trainer 曾用 bfill 引入未来函数】，实盘侧也要确认没有用 bfill 填未来 bar）。

**恢复验证**：连续 20 次刷新全部特征在界内；`max_feature_age_ms < 45 s`。

#### R5 库存顶格 / 越界

**诊断**
1. `inventory`、`max_inventory`、本地账本 vs 交易所 `positions`；
2. 触发原因：毒性门控失效？冷却没生效？成交回报延迟导致超发？**最常见是「订单回报延迟 + 未按持仓检查」**；
3. 是否有孤儿单仍在交易所侧。

**处置**
- 越界即：撤掉**所有**该标的挂单（L2 只减不加），不要试图「补一单反向单」；
- 用 REST 拉真实持仓，以交易所为准重建本地 `inventory`；
- 若实际持仓 > 本地记录：说明私有流漏成交 → 按 R2 处理；
- 复核 `allow_bid = inventory < max_inventory` 的判定是否用了**最新**库存（当前实现中 `strategy.inventory` 只在收到成交事件时更新【实测：`on_real_fill`】——这是滞后的，必须改成「用交易所持仓兜底」）。

**恢复验证**：本地与交易所持仓一致；`|inventory| ≤ 0.8 × max_inventory` 持续 30 min；无孤儿单。

#### R6 手续费异常（占毛利比飙升）

**诊断**
1. `FGR = Σfee ÷ Σgross_capture`，看 1 h / 1 d 两个窗口；
2. 拆解：`fee` 上升是名义涨了还是费率变了 → 对照 `V_day = Σfee ÷ f_maker`；
3. 是否混入 taker：查 `maker_ratio` 与私有 `fill` 的 `execType`；
4. 是否费率档位变化（OKX 交易量等级返佣/加价）→ 查账户费率页面。

**处置**
- FGR > 50% → 冻结加仓，查原因；
- 出现 taker 成交 → 立即撤单，检查 `ordType` 是否仍为 `post_only`、价格是否跨过中间价；
- 费率档位变化（通常是**费率变贵**）→ 按新费率重算 `E_min` 与 `min_spread_bps`，必要时暂停；
- 连续 2 个窗口 FGR > 100% → 降级 L2。

**恢复验证**：连续 3 个 1 h 窗口 FGR < 50%；maker_ratio > 99%。

#### R7 延迟飙升

**诊断**
1. `loop_latency p99`、`event_loop_jitter p99`、`msg_latency p95` 三者分开看；
2. 若 `msg_latency` 高 ⇒ 网络问题；`loop_latency` 高 ⇒ 本机 CPU 争抢；
3. `docker stats` 看容器 CPU；`top` 看是不是多个容器在抢核；
4. RTT 实测：`curl` 打 OKX REST。

**处置**
- 本机 CPU 争抢 → 把非交易容器降优先级（`docker update --cpu-shares`），交易容器 `taskset` 绑核；
- 网络 RTT > 200 ms → 收紧报价（加宽）、降低 L_s 与下单速率、暂停加仓；
- 延迟 > 500 ms 持续 → 降级 L2（只减不加）；
- 事件循环长时间卡死（心跳断 > 120 s）→ HALT。

**恢复验证**：连续 1 h `loop p99 < 200 ms`、`jitter p99 < 50 ms`、`msg p95 < 300 ms`。

#### R8 权益快速下跌

**诊断**
1. 区分「浮亏」与「已实现亏损」：看 `unrealized_pnl` 与 `realized_pnl_today`；
2. 若是浮亏 → 检查库存方向与市场走势（ADX 门控是否触发）；
3. 若是已实现 → 逐笔回看最近 100 笔，算 e 与 ASR（多半是逆向选择突然放大，即被扫）；
4. 检查是否触发了「扫盘」：mark-out 的 30 s 分布。

**处置**
- 按 §2.6 熔断阶梯自动降级（不等人）；
- 浮亏为主且库存单边 → 优先撤掉**同向**的新开仓单，只留平仓方向；
- 已实现亏损且 ASR 突增 → 判定为毒性环境：加宽价差 ×2、延长成交后冷却（5 s → 30 s）、降低 L_s；
- 回撤触 L3 → HALT，等人工。

**恢复验证**：权益连续 2 h 不再下降；ASR 回到基线 ±20%；降级级别可逐级回升（每次回升间隔 ≥ 1 个观察窗口）。

---

## 5. 多交易所与多账户运维

### 5.1 凭证管理（先修当前的安全问题）

**当前发现的问题（必须在下一版修复）**：
- `live_cluster/cron_hot_monitor.py` 内**硬编码** OKX `api_key / api_secret / passphrase`【实测：源码第 96~99 行附近】；
- `live_cluster/cron_accountbot3_ml_guard.py` 与 `cron_hot_monitor.py` 内**硬编码 Telegram bot token 与 chat_id**【实测】；
- `run_live.py` 已有从 `config/accountbot3_credentials.env` 读取的雏形（文件权限未强制）。

**目标方案**：

| 项 | 方案 |
|---|---|
| 存储 | 每个账户一个 `config/accounts/<account>.env`，权限 `chmod 600`，属主 `root`；**不放 git**（`.gitignore` 加 `live_cluster/config/`）|
| 容器注入 | Docker `--env-file` 或 `secrets`（`/run/secrets/xxx`），不通过环境变量明文出现在 `docker inspect`（若用 env-file，至少不写进 compose 明文）|
| 权限分离 | 监控进程用**只读** API key（可查余额/持仓/成交，不可下单）；交易进程用**可交易但不可提现**的 key，并开启 **IP 白名单**（VPS 出口 IP）|
| 交易所侧 | 关闭提现权限；对每个账户使用独立 key（不共用），以便按账户吊销 |
| 轮换 | 每 **90 天**或每次怀疑泄露时轮换【建议起始】；轮换流程：新建 key → 灰度（监控用新 key 验证 1 天）→ 交易用新 key → 撤销旧 key；**永远先建后撤** |
| 轮换审计 | `config/accounts/registry.json` 记录 `{account, venue, key_id, created_at, rotated_at, revoked_at}`（只存 key_id，不存 secret）|
| 落地验证 | 启动时自检：若代码/日志中出现疑似 secret 字符串则拒绝启动；`git grep -n "api_secret\|passphrase\|TELEGRAM_TOKEN"` 必须为空（CI 卡口）|

**Telegram token 同样处理**：改为 `config/accounts/telegram.env`（600），并轮换一次（因为已出现在源码与历史提交中 ⇒ 视同泄露）。

### 5.2 多交易所参数隔离

**核心原则：参数按 venue × symbol 独立标定，不得跨所复用。** 每个交易所的费率、API 限频、最小下单单位、tick、盘口结构、延迟都不同；把 OKX 的 `gamma/κ/min_spread_bps` 直接搬到 Hyperliquid 一定错。

**参数文件结构**：
```
live_cluster/config/venues/
  okx.json
  hyperliquid.json
  lighter.json
  robinhood.json
  okx.btc-usdt-swap.json      # 可选：按 symbol 覆盖
```
**统一 schema（示例，OKX 为主；其余交易所的数值必须由标定流程填出，此处不臆造）**：
```json
{
  "venue": "okx",
  "display_name": "OKX",
  "product_type": "swap",
  "settlement": "USDT",
  "api": {
    "rest_base": "https://www.okx.com",
    "ws_public": "wss://ws.okx.com:443/ws/v5/public",
    "ws_private": "wss://ws.okx.com:443/ws/v5/private",
    "rate_limit_orders_per_2s": 10,
    "rate_limit_rest_per_2s": 20,
    "timeout_ms": 12000,
    "ipv4_only": true
  },
  "fees": { "maker_bps": 2.0, "taker_bps": 5.0, "tier": "base" },
  "instrument": {
    "symbol": "BTC-USDT-SWAP",
    "tick_size": 0.1,
    "lot_size_contracts": 0.01,
    "contract_value_btc": 0.01,
    "min_notional_usd": 8.08
  },
  "latency": { "rtt_p50_ms": 60, "rtt_p95_ms": 75 },
  "strategy": {
    "gamma": 0.35,
    "kappa": 2.1346,
    "min_spread_bps": 9.0,
    "max_inventory_contracts": 0.05,
    "levels_per_side": 1,
    "size_contracts_per_level": 0.01,
    "refresh_interval_s": 2.0,
    "post_fill_cooldown_s": 5.0,
    "adx_trend_block_threshold": 28.0
  },
  "risk": { "max_drawdown_pct": 0.03, "max_weight_per_symbol": 0.25, "max_weight_per_cluster": 0.40 },
  "calibration": { "date": "2026-11-14", "source": "live_accountbot3_10h", "status": "provisional" }
}
```
> `latency.rtt_p50/p95` 与 `fees` 来自实测【当前值来自 accountbot3 实测】；`calibration.status = provisional` 表示**尚未标定**，只允许用于关卡 0~1。

**标定流程（每个 venue × symbol 必须独立走一遍）**：
1. **盘口结构标定**：用 `cryptohftdata` 拉该交易所该标的的 `orderbook` 归档（注意 `exchange=okx` 返回 count=0，必须用 `okx_futures`/`okx_spot` 这类规范化 id【实测 API 行为】），统计：最优档价差分布、5 档深度、盘口更新频率、tick 分布。
2. **费率标定**：从账户费率页面/实测成交费用反推（`fee ÷ notional`），确认 Maker/Taker 与返佣层级。
3. **延迟标定**：连续 1000 次 REST 往返 + WS 推送时延，算 p50/p95/p99 与抖动。
4. **最小下单单位标定**：`min_size` / `min_notional`（影响 §2.2 约束 A）。
5. **队列与逆向选择标定**：影子模式 ≥ 7 天，按该所自己的盘口计算 e / ASR / φ。
6. 标定结果写回参数文件，`calibration.status = "calibrated"`，记录日期与数据来源；**未标定的 venue 不允许进入关卡 2**。

### 5.3 统一运行状态面板数据模型

一份 JSON schema 覆盖所有交易所实例（`live_cluster/ops/status.schema.json`）：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "VenueInstanceStatus",
  "type": "object",
  "required": ["instance_id", "venue", "account", "symbol", "ts_utc", "tier", "health", "equity"],
  "properties": {
    "instance_id":  { "type": "string" },
    "venue":        { "type": "string" },
    "account":      { "type": "string" },
    "symbol":       { "type": "string" },
    "ts_utc":       { "type": "string", "format": "date-time" },
    "tier":         { "type": "string", "enum": ["T0","T1","T2","T3","T4","T5","T6"] },
    "gate":         { "type": "string", "enum": ["shadow","demo","live"] },
    "process": {
      "type": "object",
      "properties": {
        "pid":              { "type": "integer" },
        "loop_count":       { "type": "integer" },
        "heartbeat_age_ms": { "type": "integer" },
        "loop_latency_ms":  { "type": "object", "properties": { "p50": {"type":"number"}, "p95": {"type":"number"}, "p99": {"type":"number"} } },
        "jitter_ms":        { "type": "object", "properties": { "p99": {"type":"number"} } },
        "feature_ms":       { "type": "number" },
        "inference_ms":     { "type": "number" },
        "ws_reconnect_1h":  { "type": "integer" },
        "last_book_age_ms": { "type": "integer" },
        "model_files_ok":   { "type": "boolean" }
      }
    },
    "orders": {
      "type": "object",
      "properties": {
        "places": { "type": "integer" }, "cancels": { "type": "integer" },
        "fills": { "type": "integer" }, "rejects": { "type": "integer" },
        "reject_reasons": { "type": "object", "additionalProperties": { "type": "integer" } },
        "reject_rate": { "type": "number" },
        "queue_hold_rate": { "type": "number" }
      }
    },
    "fills_detail": {
      "type": "object",
      "properties": {
        "maker_ratio": { "type": "number" },
        "notional_24h": { "type": "number" },
        "fee_24h": { "type": "number" }
      }
    },
    "unit_econ": {
      "type": "object",
      "properties": {
        "e_bps_net": { "type": "number" },
        "gross_capture_bps": { "type": "number" },
        "adverse_bps": { "type": "number" },
        "fee_bps": { "type": "number" },
        "asr": { "type": "number" },
        "fgr": { "type": "number" },
        "phi_capture_ratio": { "type": "number" }
      }
    },
    "position": {
      "type": "object",
      "properties": {
        "inventory_contracts": { "type": "number" },
        "inventory_notional": { "type": "number" },
        "max_inventory_contracts": { "type": "number" },
        "lambda": { "type": "number" },
        "turnover_per_day": { "type": "number" }
      }
    },
    "account": {
      "type": "object",
      "properties": {
        "equity": { "type": "number" }, "avail": { "type": "number" },
        "margin_used_ratio": { "type": "number" }, "upl": { "type": "number" },
        "realized_pnl_today": { "type": "number" }, "funding_today": { "type": "number" },
        "liq_distance": { "type": "number" },
        "drawdown_pct": { "type": "number" }, "dd_tier": { "type": "string" }
      }
    },
    "quotes": {
      "type": "object",
      "properties": {
        "bid": { "type": "number" }, "ask": { "type": "number" }, "mid": { "type": "number" },
        "half_spread_bps": { "type": "number" },
        "bid_offset_bp": { "type": "number" }, "ask_offset_bp": { "type": "number" },
        "mid_deviation_bp": { "type": "number" },
        "levels_per_side": { "type": "integer" }
      }
    },
    "health": {
      "type": "object",
      "properties": {
        "level": { "type": "string", "enum": ["INFO","WARN","CRITICAL","HALT"] },
        "alerts": { "type": "array", "items": { "type": "object", "properties": {
          "rule_id": {"type":"string"}, "level": {"type":"string"},
          "msg": {"type":"string"}, "ts_utc": {"type":"string"} } } },
        "blockers": { "type": "array", "items": { "type": "string" } }
      }
    },
    "cross_venue": {
      "type": "object",
      "properties": {
        "mid_spread_bps": { "type": "number" },
        "cluster_id": { "type": "string" },
        "cluster_weight": { "type": "number" }
      }
    }
  }
}
```
> 落地方式：每个实例写自己的 `status_<instance_id>.json`（原子写）；面板聚合器（同一个守护进程）读全部文件，输出一份 `fleet_status.json` 与一张 Telegram 汇总消息。

### 5.4 跨交易所数据一致性校验

| # | 校验 | 公式 | 频率 | 阈值 | 动作 |
|---|---|---|---|---|---|
| V1 | 同标的 mid 价差 | `\|mid_A/mid_B − 1\|` | 1 min | > 0.30% WARN；> 1.0% CRITICAL | WARN/CRIT |
| V2 | mid 价差持续性 | 连续 5 个采样点同向偏离 > 0.3% | 5 min | CRITICAL（疑似某一边行情源断了/标的错配）| CRIT |
| V3 | 隐含资金费率一致性 | 由两所 mid 差反推年化基差 vs 两所实际资金费率之和 | 1 h | 偏离 > 0.02% → INFO 记录（可能是真实的基差机会）| INFO |
| V4 | 标的一致性 | 两所同一 symbol 的标的映射表命中 | 启动 + 1 h | 未命中 → CRITICAL（防止把 ETH 当 BTC 算相关性）| CRIT |
| V5 | 库存方向一致性 | 同一标的在不同所的净库存方向相反且规模都 > 5% E | 1 h | WARN（合成暴露，跨所对冲失效）| WARN |
| V6 | 统一时钟 | 各实例 `ts_utc` 与 NTP 偏差 | 1 min | > 1 s → WARN（否则 L3 漂移比对失真）| WARN |

> V1 的阈值依据：跨所价差天然包含资金费率（BTC 永续年化 5~10% ⇒ 日化约 1.5~3 bp）与库存成本，因此**稳定态**的偏离应在几十 bp 内；> 0.3% 属于异常量级【建议起始】。

### 5.5 单一故障点隔离

**当前结构的风险**：`run_live.py` 是单进程多职责（WS 管理 + 定价 + 下单 + 记账 + 写盘），而 `cron_accountbot3_ml_guard.py` 用 `subprocess` 跑 `docker inspect`【实测】——监控与交易通过**共享主机资源**耦合：监控进程的 5 分钟扫描会与交易进程抢同一个核。

**隔离设计**：

| 故障 | 传播路径 | 隔离措施 |
|---|---|---|
| 某交易所 WS 断线 | 若多所共用一个进程 → 全部停摆 | **每 venue 一个独立进程/容器**，一个进程只连一个所；WS 断线只影响该容器 |
| 某交易所 API 限频 | 共享 HTTP 连接池 → 拖慢其他所 | 每 venue 独立 client 实例 + 独立限频器（`gateway_okx_client` 目前无退避队列，需补）|
| 监控守护进程卡死 | 抢 CPU → 交易进程抖动 | 监控进程 `taskset` 到独立核（若无独立核则 `nice +19`）+ cgroup 内存上限 128 MB |
| 磁盘写满 | 交易写日志失败 → 异常退出 | 独立日志卷 + logrotate + 磁盘水位监控（> 80% WARN）|
| 配置错误 | 影响全部 | 每 venue 独立 config 文件 + 启动时 schema 校验 |
| 凭证泄露 | 影响该账户 | 每账户独立 key，可单独吊销 |

**进程拓扑（1 核 1G 的现实版）**：
```
[交易容器 × N（每 venue 一个）]  taskset -c 0, cgroup memory=256M
[聚合守护进程 × 1]            nice +19, taskset -c 0（若无第二核则共享）, memory=128M
[容器健康检查（外部 cron）]    每 60 s 一次，只做 docker inspect + 文件读取
```
> 1 核机器上不建议超过 **2 个活跃交易实例**。多交易所扩展前必须先升配（§6）。

---

## 6. 基础设施演进路径

### 6.1 硬件升级路线表

| 档 | 规格 | 月成本【估算】 | 能支撑什么 | 前置条件 |
|---|---|---|---|---|
| **H0（当前）** | 1 vCPU / 1 GB RAM / 40 GB SSD，马来西亚 Evoxt | ~12 USDT【推断】| 1 个交易实例 + 1 个监控守护进程；事件循环抖动 10~50 ms【实测】| — |
| **H1** | 2 vCPU / 2 GB RAM，同机房 | ~24 USDT【推断】| 2 个交易实例 + 监控；`taskset` 把交易绑到独占核，抖动目标 < 10 ms | 关卡 2 达标（e>0）|
| **H2** | 4 vCPU / 4 GB RAM，同机房 | ~48 USDT【推断】| 4 个交易实例；可同时跑回测重放（关卡 0 的影子验证）而不干扰实盘 | 关卡 3 达标 |
| **H3** | 4 vCPU / 8 GB RAM + NVMe，**东京/香港** | ~60~90 USDT【推断】| 4~6 个实例；RTT 大幅下降（见 §6.2）；能做 L2 队列模型的在线校准 | 关卡 4 达标 + 单所 RTT < 40 ms |
| **H4** | 8 vCPU / 16 GB，2 机房冗余 | ~150~250 USDT【推断】| 主备双活 + 多所并行 | 关卡 5 达标 |

**升级判据（不是「有钱就升」）**：
- 抖动 p99 > 15 ms 持续 → 升 H1（绑核 + 独占核）；
- 需要跑 > 2 个交易实例 → 升 H2；
- 需要 RTT < 30 ms（为了把 T 压到 2 s 以内、减少 stale quote 的逆向选择）→ 迁 H3；
- 单机故障不可接受（本金 > 5,000 USDT）→ 上 H4（**且必须同时有跨机房备份与凭证独立**）。

### 6.2 地理迁移路线

| 位置 | 到 OKX 撮合 RTT【推断，须实测】| 对本策略的影响 |
|---|---|---|
| 马来西亚（当前）| 45~75 ms【实测】| 撤改单往返 ~150~250 ms，报价年龄天然偏高 |
| 新加坡 | ~20~40 ms | 明显改善，改单往返 < 100 ms |
| 香港 | ~15~35 ms | 改善，且靠近 OKX 港节点 |
| 东京 | ~5~15 ms | 最佳；但日本到 OKX 撮合的实际路径可能绕行，须实测 |

**迁移可行性判断（三条必须同时满足）**：
1. **收益**：RTT 从 60 ms 降到 15 ms 能把「报价年龄」砍到 1/4。按 §2.5 的公式 `T_max = 60·(0.5δ/σ_1min)²`，这允许把刷新周期 T 从 12 s 压到 3 s → **同样的 L_s 下订单速率翻 4 倍** ⇒ 在同样的下单速率预算下能挂 4 倍档位 ⇒ 单标的资金天花板提升 4 倍。这是迁移的核心经济理由。
2. **成本**：H3 相对 H0 增加 ~50 USDT/月。按 §2.2 的公式，运营成本上升会抬高 `E_op = C_op/(30·k_v·e)`；C_op 从 45 → 95 USDT 时，E_op 翻倍。**因此迁移只能等 e 已经稳定为正之后做**，否则只是把亏损放大。
3. **风险**：迁移 = 换 IP = 交易所 API key 的 IP 白名单要改 + 观察期重置（关卡退回 1）。迁移窗口应安排在低波动期。

**建议**：不在关卡 2/3 期间迁移。等关卡 3 达标、e 稳定为正，再在关卡 4 之前迁 H3，把多标的并行放在低延迟环境里做。

### 6.3 代码层面的降载手段（不花钱也能提的正确性与速度）

在 1 核上做以下 5 件事，可以把抖动压下来并腾出算力：

| # | 改造 | 现状 | 做法 | 收益 |
|---|---|---|---|---|
| O1 | **订单状态改用私有 WS 缓存** | `run_live.py` 每轮都 `GET /api/v5/trade/orders-pending`【实测：现状是 REST 轮询】| 私有 WS 已订阅 `orders` 频道【实测】⇒ 维护本地订单状态机，REST 只在启动与对账时调用 | 每 2 s 少 1 次 REST（当前最大的一块延迟与抖动源）；队列保持判定更准 |
| O2 | **K 线特征改用 WS 推送** | 每 15 s `GET /api/v5/market/candles`【实测】| 订阅 `candle1m` 频道或本地用 `trades` 累积 1m bar（保证因果） | 去掉周期性 REST；特征年龄从 ≤ 15 s 降到 ≤ 1 s |
| O3 | **特征计算下沉** | `compute_gk_vol` 纯 pandas/numpy，每 15 s 跑一次【实测】| 用 Numba `@njit` 重写 GK/MA20/ADX 的滚动部分（回测侧已用 Numba【实测：`run_2year_asgrid_backtest.py`】）| 单次耗时从数十 ms 降到 < 1 ms；CPU 占用降一个量级 |
| O4 | **把 `bfill()` 全部剔除** | 实盘侧 `compute_gk_vol` 中 `rolling(...).bfill()`【实测：源码存在】| 改成 `min_periods` 不足时返回 `None` ⇒ 特征不可用则不报价 | 消除「用未来值补齐历史」在实盘侧的残留（回测侧已整改过同类问题【实测】）|
| O5 | **轮询改事件驱动** | 主循环 `time.sleep(max(0.5, 2.0 - elapsed))` 固定 2 s【实测】| 由 WS 消息驱动重算报价；无消息时降频心跳（1 s） | 报价年龄从「平均 1 s / 最坏 2 s」降到「事件到达即更新」 |

> O1+O2+O5 是收益最大的三项：它们把 REST 调用从「每 2 s 1 次 + 每 15 s 1 次」降到「每 30 s 1 次（仅对账）」，直接消除大部分 45~75 ms RTT 暴露与 CPU 唤醒。
> O3/O4 是正确性项：O3 提速，O4 消除潜在未来函数。
> 落地顺序建议：O1 → O4 → O5 → O2 → O3（先做零风险、收益最大的）。

### 6.4 容器编排改进（1 核可落地）

| 项 | 现状 | 改进 |
|---|---|---|
| CPU 绑核 | 多容器共享单核，抖动 10~50 ms【实测】| 交易容器 `docker run --cpuset-cpus=0` 独占核；监控容器 `--cpuset-cpus=0,1`（若为 2 核）或 `--cpu-shares=128`；监控 `nice +19` |
| 内存上限 | 无限制，OOM 会拖垮邻居 | `--memory=256m --memory-swap=256m`（交易）、`--memory=128m`（监控）；`memory.high` 提前回收 |
| 日志卷 | 容器内写盘 | 独立 named volume，`json-file` driver 限制 `max-size=10m, max-file=3`；关键状态 JSON 写 `/state` 卷（**独立于容器生命周期，容器重建不丢**）|
| 健康检查 | `docker inspect` 由 cron 拉取【实测】| 容器内暴露 `/healthz`（读状态 JSON 的 `heartbeat_age_ms`），外部 cron 每 30 s 拉一次；连续 3 次失败 → `docker restart` |
| 自愈 | 依赖手工 | `restart: unless-stopped` + 崩溃时的**先撤单再退出**（当前 `SIGTERM` 处理器已撤单【实测】，需确保 `SIGKILL` 路径也有兜底：每隔 10 s 检查「进程活着但心跳停」→ 撤单）|
| 时钟 | 假设 NTP 正常 | 容器内 `chrony`/`ntpd`；L3 漂移比对要求时钟偏差 < 1 s（§5.4 V6）|
| 配置 | 部分硬编码 | 每 venue 独立 config + 启动 schema 校验；`config_hash` 写入状态文件供 L3.11 校验 |
| 镜像 | — | 固定 digest（不用 `latest`）；`python:3.11-slim` + 固定 `requirements.lock`；镜像构建不进交易容器 |

---

## 7. 落地清单（下一版要写的文件）

| 文件 | 作用 | 优先级 |
|---|---|---|
| `live_cluster/ops/status.schema.json` | §5.3 的 JSON Schema | P0 |
| `live_cluster/ops/collector.py` | 汇总各实例状态 → `fleet_status.json` | P0 |
| `live_cluster/ops/alert_gateway.py` | §4.2 去重/抑制 + Telegram | P0 |
| `live_cluster/ops/rules.py` | L1/L2/L3 的全部规则与阈值（单一真相源）| P0 |
| `live_cluster/ops/atomic_json.py` | 原子写工具 | P0 |
| `live_cluster/ops/markout.py` | 成交 mark-out 环形缓冲 → adverse/φ/e | P0 |
| `live_cluster/ops/unit_econ.py` | e / ASR / FGR / FIFO 轮次归集 | P0 |
| `live_cluster/ops/drift.py` | PSI + KS 基线比对 | P1 |
| `live_cluster/ops/capital.py` | §2.2 `E_min`、§2.4 风险平价、§2.6 熔断阶梯 | P1 |
| `live_cluster/config/venues/*.json` | 每所参数（先只有 okx.json）| P0 |
| `live_cluster/config/accounts/*.env`（600）+ `registry.json` | §5.1 凭证管理 | P0 |
| `live_cluster/ops/runbooks/` | §4.3 的 8 个场景，每个一个 md | P1 |
| `tests/test_ops_rules.py` | 规则的单元测试（阈值边界、迟滞、抑制）| P1 |

**必须同时修复的现有问题（不改这些，上面全是空转）**：
1. `cron_hot_monitor.py` 硬编码 OKX 密钥 → 移到 `config/accounts/*.env`【实测问题】；
2. `cron_accountbot3_ml_guard.py` / `cron_hot_monitor.py` 硬编码 Telegram token → 移出源码并**轮换**；
3. `run_live.py` 状态文件非原子写 → 改原子写（否则心跳误报）；
4. `run_live.py` 每轮 REST 拉 `orders-pending` → 改用私有 WS 订单缓存（§6.3 O1）；
5. `compute_gk_vol` 中的 `.bfill()` → 剔除（§6.3 O4）；
6. `run_live.py` 中 `client.cancel_batch_orders(cancel_list)` 写在 for 循环体内【实测：源码缩进如此】⇒ 每次迭代只撤第一张单，撤单效率与队列保持都被拖累 → 移出循环，批量撤。

---

## 8. 一页纸总结

1. **不要用回测决定上不上线**。回测的价值是给出**上界**；上线许可由关卡制给出，而关卡 2 的产出是**真实单位经济学**。
2. 当前实盘的真实单位经济学（反推）：**净捕获 −0.55 bp/名义、逆向选择 ≈ 3.05 bp/名义（吃掉 68% 的报价半价差）、手续费 2 bp**。**在 e 转正之前，任何加资金都是加速亏损。**
3. **最小可行资金有公式**：`E_min = max(N_min/ρ_grain, N_min·q_floor/λ_max, C_op/(30·k_v·e))`，其中 `λ_max = k_v·e/(SNR_min·σ_1d·ρ_inv)`。代入当前实测 e = −0.55 bp ⇒ **E_min 无解**；代入 e = 1 bp、k_v = 30 ⇒ E_min ≈ 1,500 USDT；e = 2 bp ⇒ 750 USDT。
4. **30U 在 BTC-USDT-SWAP 上不可能做精细做市**：最小名义 8.08 USDT = 27% 权益，粒度下限 E ≥ 162 USDT。30U 的正确用途是测量账户；若要小资金做市，换最小名义 ≈ 0.5~1 USDT 的标的。
5. **杠杆不改善期望**，只放大 λ 与破产速度；λ_max ≤ 1 的区间内应当拒绝杠杆。真正能放大收益的是 **e（降逆向选择、提捕获率）** 与 **k_v（工程量）**。
6. **多标的不是分散风险那么简单**：它是**单标的容量天花板**的必然结果（档位数 × 下单速率 × 报价陈旧度三条约束）。资金阶梯表与单标的资金上限由此推出。
7. **监控三层**（L1 进程 / L2 账户 / L3 统计）都落在一个 Python 守护进程 + JSON 状态文件 + Telegram 的形态上（现有 `cron_accountbot3_ml_guard.py` 模式），**不要**在 1 核机器上引入 Prometheus + Grafana。
8. **最重要的一条告警**：`e_rolling_100 ≤ 0` ⇒ 冻结加仓。其余指标都是辅助。
