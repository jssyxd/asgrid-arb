# AKE-USDT-SWAP 高频网格做市服务 (accountbot3)

> **当前状态**：⏸️ 已暂停 (挂单撤销，持仓市价平仓，等待参数与模型优化)
> **部署服务器**：Server A (155.254.60.38)
> **合约规格**：ctVal = 100 AKE

## 一、策略模型与架构
- **模型体系**：`High-Turnover Liquidity Absorption + Post-Only Engine`
- **单边冷却**：`5.0 秒单边成交冷却`
- **特征工程清单**：
  - 超高换手率流动性微观价格捕捉
  - 严格 100% Post-Only 被动挂单保障
  - 突发成交单边切断冷静期

## 二、现行生产参数配置清单
```ini
INST_ID=AKE-USDT-SWAP
INITIAL_CAPITAL=28.73 USDT
LOT_SZ=10
MAX_INVENTORY=100
MIN_SPREAD_BPS=9.0
PRICE_TOLERANCE=0.00002
GAMMA_CALM=0.35
GAMMA_VOL=1.20
FILL_COOLDOWN_SEC=5.0
```

## 三、ML 训练与优化标记
**【标记：待改进 ML 参数】**

待改进 ML 参数：【重点待优化】新币换手极高但庄家单边下砸剧烈，9 bps 仍不足以抵抗大单穿透。待改进：最小利差由 9.0 bps 提升至 14.0~16.0 bps，单笔挂单减半至 5 张，最大库存收敛至 40 张，并引入 VPIN 毒性暴击硬性熔断。
