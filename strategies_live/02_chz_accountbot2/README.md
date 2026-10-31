# CHZ-USDT-SWAP 高频网格做市服务 (accountbot2)

> **当前状态**：⏸️ 已暂停 (挂单撤销，持仓市价平仓，等待参数与模型优化)
> **部署服务器**：Server B (23.27.186.126)
> **合约规格**：ctVal = 10 CHZ

## 一、策略模型与架构
- **模型体系**：`Stoikov Micro-Price + Top-5 OFI + Regime-Switching Gamma`
- **单边冷却**：`5.0 秒单边成交冷却`
- **特征工程清单**：
  - 前5档订单簿失衡度 OBI 与微观价格加权
  - Garman-Klass 波动率机制切换 Gamma (平稳 0.35 / 高波 1.20)
  - 盘口深度挂单排队优先级保护 (Queue Priority Hold)

## 二、现行生产参数配置清单
```ini
INST_ID=CHZ-USDT-SWAP
INITIAL_CAPITAL=33.00 USDT
LOT_SZ=10
MAX_INVENTORY=100
MIN_SPREAD_BPS=8.0
PRICE_TOLERANCE=0.00002
GAMMA_CALM=0.35
GAMMA_VOL=1.20
FILL_COOLDOWN_SEC=5.0
```

## 三、ML 训练与优化标记
**【标记：待改进 ML 参数】**

待改进 ML 参数：CHZ 盘口极厚（前5档近 $30,000），被动成交频率偏低。需结合 L2 挂单撤单速度（Cancel Rate）与微观成交加速度，动态收敛价差至 6.5~7.5 bps 以提升成交量与资金周转率。
