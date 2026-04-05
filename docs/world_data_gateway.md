# World Data Gateway

`world-data-gateway` 是世界模型的统一硬源入口层。主系统不直接对接第三方站点，而是只访问标准化 JSON 接口。

## 目标

- 统一外部硬源格式
- 隔离上游供应商凭据
- 给主系统提供稳定 URL
- 允许在未接通真实供应商时回退到本地派生源

## 运行方式

```bash
WORLD_DATA_GATEWAY_TOKEN=your-token python3 world_data_gateway.py
```

默认监听：

- `127.0.0.1:18080`

可通过环境变量覆盖：

- `WORLD_DATA_GATEWAY_HOST`
- `WORLD_DATA_GATEWAY_PORT`

## 认证

若设置了 `WORLD_DATA_GATEWAY_TOKEN`，请求必须带其中之一：

- `Authorization: Bearer <token>`
- `X-World-Gateway-Token: <token>`

## 主系统环境变量

主系统应把以下 URL 指向网关：

- `WORLD_DATA_GATEWAY_BASE_URL`
- `WORLD_OFFICIAL_FULLTEXT_URL`
- `WORLD_SHIPPING_AIS_URL`
- `WORLD_FREIGHT_RATES_URL`
- `WORLD_COMMODITY_TERMINAL_URL`
- `WORLD_MACRO_RATES_FX_URL`

如果设置了 `WORLD_DATA_GATEWAY_BASE_URL`，主系统会自动派生 5 条完整硬源 URL；只有你想单独覆写某条源时，才需要再配单独的 `WORLD_*_URL`。

如需带统一认证头：

- `WORLD_HARD_SOURCE_AUTH_TOKEN`
- `WORLD_HARD_SOURCE_AUTH_HEADER`

若主系统直连的是你自己的 gateway，最简单配置是：

```bash
WORLD_DATA_GATEWAY_BASE_URL=http://127.0.0.1:18080
WORLD_DATA_GATEWAY_TOKEN=your-token
```

主系统会自动把 `WORLD_DATA_GATEWAY_TOKEN` 复用成硬源请求 token；如果你想和 gateway token 分开，再单独设置 `WORLD_HARD_SOURCE_AUTH_TOKEN`。

## 接口

### `GET /health/live`

健康状态。

### `GET /api/world-gateway/source-status`

返回 5 条硬源当前状态。

### `GET /api/world-gateway/official-fulltext`

返回：

- `documents`
  - `title`
  - `source`
  - `published_at`
  - `excerpt`
  - `reference_url`
  - `keywords`
  - `affected_directions`
  - `affected_regions`

### `GET /api/world-gateway/shipping-ais`

返回：

- `routes`
  - `route`
  - `restriction_scope`
  - `estimated_flow_impact_pct`
  - `allowed_vessels`
  - `blocked_vessels`
  - `affected_countries`
  - `notes`

### `GET /api/world-gateway/freight-rates`

返回：

- `lanes`
  - `route`
  - `pressure_level`
  - `rate_change_pct_1d`
  - `insurance_premium_bp`
  - `tanker_bias`
  - `notes`

### `GET /api/world-gateway/commodity-terminal`

返回：

- `commodities`
  - `name`
  - `price`
  - `change_pct_1d`
  - `change_pct_5d`
  - `pressure_level`
  - `downstream_industries`

### `GET /api/world-gateway/macro-rates-fx`

返回：

- `instruments`
  - `key`
  - `label`
  - `category`
  - `value`
  - `score`
  - `bias`
  - `change_pct_1d`
  - `summary`

## 当前实现

- 优先返回本地已缓存的标准化 payload
- 缓存不存在时自动回退到本地 fallback builder
- 这样即使真实供应商入口还没接通，主系统也能先走完整链路
