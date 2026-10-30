# NautilusTrader 多币种微观做市集群 (Multi-Asset Live Cluster)

本项目在生产 VPS（Debian 12 + 2GB 持久化 Swap + Python 3.11 + NautilusTrader 1.221.0）上实现了三大独立资产的物理隔离高频做市：

```
live_cluster/
├── shared/                              # 共享高性能网关与通用状态机
│   ├── gateway_okx_client.py           # 强制 IPv4、Keep-Alive、Chrome UA、OKX HMAC 签名
│   └── okx_ws_manager.py               # 原生全双工 WebSocket (books5 深度 + orders 真实成交)
│
├── sol_trader_bot2/                    # 实例 1: SOL-USDT (accountbot2, 40U 3x)
│   ├── run_sol.py                      # Stoikov 微观价 + Top-5 OFI + 动态 Gamma 状态机 (0.35/1.20)
│   ├── config/accountbot2_credentials.env.example
│   ├── nautilus-sol-bot2.service       # Systemd 守护单元 (MemoryMax=350M)
│   └── README.md
│
├── doge_trader_bot4/                   # 实例 2: DOGE-USDT (accountbot4, 30U 3x)
│   ├── run_doge.py                     # 量能加速度门控 (Vol/MA20 > 2.5) + 12 bps 肥尾吸收
│   ├── config/accountbot4_credentials.env.example
│   ├── nautilus-doge-bot4.service      # Systemd 守护单元 (MemoryMax=350M)
│   └── README.md
│
└── sui_trader_bot5/                    # 实例 3: SUI-USDT (accountbot5, 30U 3x)
    ├── run_sui.py                      # 8h 资金费率 Carry 偏置 + 10 bps 价差 + 无冷却即时流转
    ├── config/accountbot5_credentials.env.example
    ├── nautilus-sui-bot5.service       # Systemd 守护单元 (MemoryMax=350M)
    └── README.md
```

## 核心生产纪律与特性
1. **进程与配置绝对隔离**：每个子交易程序独占独立的运行目录、独立日志、独立状态快照，完全杜绝竞态条件。
2. **严格 Post-Only 守卫**：全量报单绑定 `ord_type = "post_only"`，杜绝任何 Taker 吃单滑点与惩罚性费率。
3. **真实成交记账 (True Fill Accounting)**：仅以私有 WebSocket orders 频道的 `state in ['filled', 'partially_filled']` 为唯一成交凭证。
4. **队列优先权感知 (Queue Priority Preservation)**：最新公允价格微动在容差内保持原单排队，维护 FIFO 时间优先权。
5. **动态资本风控**：初始保证金占用率严格锁死在 $\le 15\%$，净持仓锁死在 $\le 45\%$，给小微账户永久保留 $\ge 55\%$ 流动性缓冲垫。
