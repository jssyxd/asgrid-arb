# CORE-USDT-SWAP 高频网格做市服务 (accountbot5)

> **当前状态**：⏸️ 已暂停 (挂单撤销，持仓市价平仓，等待参数与模型优化)
> **部署服务器**：Server B (23.27.186.126)
> **合约规格**：ctVal = 1 CORE

## 一、策略模型与架构
- **模型体系**：`High-Beta Spread Buffer + Funding Rate Carry Drift`
- **单边冷却**：`5.0 秒单边成交冷却`
- **特征工程清单**：
  - 实时 8h 资金费率 Carry 偏置注入保留价格
  - 高 Beta 弹性自适应利差控制 (7.0 bps)
  - 无量纲存货比例 I_ratio 动态惩罚与平滑出清

## 二、现行生产参数配置清单
```ini
INST_ID=CORE-USDT-SWAP
INITIAL_CAPITAL=24.79 USDT
LOT_SZ=50
MAX_INVENTORY=400
MIN_SPREAD_BPS=7.0
PRICE_TOLERANCE=0.00002
GAMMA_CALM=0.35
GAMMA_VOL=1.20
FILL_COOLDOWN_SEC=5.0
```

## 三、ML 训练与优化标记
**【标记：待改进 ML 参数】**

待改进 ML 参数：当前 7.0 bps 利差在高 Beta 标的下回撤率已降至 0.57%，但胜率仍处于 45.4%。需引入 1 分钟 K 线布林带通道挤压（BB Squeeze）与 CVD 动量过滤，在价格突破上轨时抑制多头承接。
