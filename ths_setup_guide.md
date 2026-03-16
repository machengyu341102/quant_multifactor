# 同花顺 Web 交易网关对接指南

## 架构

```
Mac (量化策略系统) ──HTTP──→ 同花顺交易网关 ──→ 国盛证券账户
                              (本机 / VM / 远程)
```

策略系统通过 HTTP API 连接同花顺交易网关, macOS 原生可用, 无需 Windows GUI 客户端.

## 1. 交易网关部署

### 方案 A: Windows VM (推荐)

1. 安装 VMware Fusion / Parallels Desktop
2. 安装 Windows 10/11 虚拟机
3. VM 中安装同花顺客户端 + 登录国盛证券账户
4. 部署同花顺 HTTP 交易网关 (开放端口 9099)
5. VM 网络设置为桥接模式, 确保 Mac 能访问 VM IP

### 方案 B: 远程服务器

1. 在 Windows 服务器上安装同花顺客户端
2. 部署 HTTP 交易网关
3. 配置防火墙允许 9099 端口
4. `config.py` 中 `ths_base_url` 设为服务器地址

### 方案 C: 同花顺 Web 版

1. 浏览器登录同花顺 Web 交易
2. 提取登录后的 Cookie
3. `config.py` 中 `ths_auth_mode` 设为 `"cookie"`, 填入 `ths_cookie`

## 2. 配置参数 (config.py)

```python
STOCK_EXECUTOR_PARAMS = {
    "mode": "demo",                     # demo 先验证, 确认无误再切 live
    "broker": "ths_web",                # 使用同花顺 Web 接口
    "ths_base_url": "http://127.0.0.1:9099",   # 网关地址
    "ths_username": "你的账号",
    "ths_password": "你的密码",
    "ths_auth_mode": "token",           # token 或 cookie
    "ths_cookie": "",                   # cookie 模式时填入
    "ths_timeout_sec": 10,
    "ths_retry_count": 2,
    "ths_token_refresh_min": 30,
}
```

## 3. 模式说明

| 模式 | 说明 | 是否下单 |
|------|------|----------|
| `demo` | 模拟模式, 记录操作日志但不实际下单 | 否 |
| `live` | 实盘模式, 通过网关真实下单 | 是 |
| `paper` | 纸盘模式 (系统内置, 不走同花顺) | 否 |

建议流程: `demo` → 验证一周 → `live`

## 4. 验证步骤

### 步骤 1: 连接测试

```bash
cd quant_multifactor
python3 ths_broker.py test
```

预期输出:
```
同花顺交易网关连接测试
==================================================
  mode: demo
  base_url: http://127.0.0.1:9099
  auth_mode: token
  status: ok
  message: Demo 模式, 无需连接网关
  Demo买入测试: [THS-Demo] 买入 000001 x100 @ 10.01

连接测试通过!
```

### 步骤 2: Demo 买卖测试

```bash
python3 ths_broker.py demo_buy 600519   # 模拟买入
python3 ths_broker.py demo_sell 600519  # 模拟卖出
python3 ths_broker.py demo_log          # 查看操作日志
```

### 步骤 3: 系统集成验证

```bash
python3 broker_executor.py status       # 查看组合状态
python3 broker_executor.py kill_switch  # 检查安全开关
```

### 步骤 4: 测试套件

```bash
python3 -m pytest tests/ -x -q          # 全量测试不回归
```

## 5. API 接口规范

交易网关需实现以下 HTTP API:

| 接口 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 心跳 | GET | `/api/ping` | 返回 200 表示网关在线 |
| 登录 | POST | `/api/login` | 返回 `{success, token}` |
| 下单 | POST | `/api/order` | 买入/卖出委托 |
| 余额 | GET | `/api/balance` | 返回资产信息 |
| 持仓 | GET | `/api/positions` | 返回持仓列表 |

### 下单请求格式

```json
{
  "action": "buy",
  "code": "600519",
  "quantity": 100,
  "price": 1800.0,
  "order_type": "limit"
}
```

### 统一响应格式

```json
{
  "success": true,
  "code": 0,
  "data": { ... },
  "message": "ok"
}
```

## 6. 安全说明

- **Demo 模式不会实际下单**, 只记录操作日志到 `ths_demo_log.json`
- 切换 live 前务必确认:
  1. Kill Switch 正常 (`broker_executor.py kill_switch`)
  2. 仓位限制合理 (单笔 15%, 最多 9 笔)
  3. 日亏损限制 (-5%) 已启用
- Token 自动刷新, 无需手动维护
- 所有交易操作写入审计日志 (`broker_audit.json`)

## 7. 常见问题

**Q: 连接网关失败?**
- 检查 VM 是否运行、同花顺是否登录
- 检查网络: `curl http://127.0.0.1:9099/api/ping`
- 检查防火墙是否放行 9099 端口

**Q: Token 过期?**
- 系统自动刷新 (默认 30 分钟), 无需手动操作
- 如果持续失败, 检查用户名密码是否正确

**Q: 如何切换到 live 模式?**
- `config.py` 中 `"mode": "live"`, 填入正确的用户名密码
- 重启策略系统即生效
