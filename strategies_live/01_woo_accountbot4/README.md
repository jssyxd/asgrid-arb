# WOO-USDT-SWAP 高频网格做市服务 (accountbot4)

> **当前状态**：🟢 保持实盘运行中 (Active)
> **部署服务器**：Server B (23.27.186.126)
> **合约规格**：ctVal = 10 WOO

## 一、策略模型与架构
- **模型体系**：`Stoikov Micro-Price + Top-5 OFI + Volatility Expansion Gating`
- **单边冷却**：`5.0 秒单边成交冷却`
- **特征工程清单**：
  - L2 Top-5 Order Flow Imbalance (OFI) 滚动归一化
  - Garman-Klass 极值波动率突破 (突破中位数1.5倍自适应拓宽利差)
  - 20 周期收盘价均线乖离率 (MA_dev)
  - Strict Post-Only 队列保持与最小价差硬门槛

## 二、现行生产参数配置清单
```ini
INST_ID=WOO-USDT-SWAP
INITIAL_CAPITAL=28.51 USDT
LOT_SZ=10
MAX_INVENTORY=100
MIN_SPREAD_BPS=8.5
PRICE_TOLERANCE=0.00002
LEVERAGE=9
GAMMA_CALM=0.35
GAMMA_VOL=1.20
FILL_COOLDOWN_SEC=5.0
```

## 三、ML 训练与优化标记
**【标记：待改进 ML 参数】**

待改进 ML 参数：当前实测胜率 52.8%，实现纯价差正收益。待升级 Severity-Weighted Adverse Move 毒性分类器，进一步在短周期大单涌入时提前切断单边。
