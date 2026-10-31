# RSR-USDT-SWAP 高频网格做市服务 (dayuan)

> **当前状态**：⏸️ 已暂停 (挂单撤销，持仓市价平仓，等待参数与模型优化)
> **部署服务器**：Server A (155.254.60.38)
> **合约规格**：ctVal = 100 RSR

## 一、策略模型与架构
- **模型体系**：`Negative Funding Rate Carry Harvesting + Micro OFI Drift`
- **单边冷却**：`5.0 秒单边成交冷却`
- **特征工程清单**：
  - 针对极端负费率 (-0.15%/8h) 的多头保留价格下移模型 (r* 动态偏置)
  - Top-5 OFI 订单流不平衡量短期方向修正
  - 单边成交 5 秒断路器与非对称撤单 (Asymmetric Fade)

## 二、现行生产参数配置清单
```ini
INST_ID=RSR-USDT-SWAP
INITIAL_CAPITAL=27.45 USDT
LOT_SZ=10
MAX_INVENTORY=150
MIN_SPREAD_BPS=7.0
PRICE_TOLERANCE=0.000002
GAMMA_CALM=0.35
GAMMA_VOL=1.20
FILL_COOLDOWN_SEC=5.0
```

## 三、ML 训练与优化标记
**【标记：待改进 ML 参数】**

待改进 ML 参数：成功实现 +0.0511u 的资金费正向收取，但胜率仅 27.05%，主要因逆势累积多头时遭遇微观下行滑点。待优化多头持仓衰减因子（Decay Factor），并将利差门槛提升至 8.0~8.5 bps。
