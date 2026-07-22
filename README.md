# steam-skin-ops

Steam 饰品收益统计与行情规则监控。项目包含两个互相独立的运行边界：

- `steam_skin_ops.profit`：在本地使用个人 BUFF、C5、Steam Cookie 统计历史收益。
- `steam_skin_ops.monitor`：使用 SMIS 公共行情提供查询、T+7/到价规则和告警事件 API。

AstrBot 只是可选客户端与告警投递适配器；行情和规则服务可以单独部署。

## 本地收益统计

安装：

```bash
python -m pip install -e ".[profit]"
copy config\profit.example.yaml config\profit.yaml
```

常用命令：

```bash
python -m steam_skin_ops.profit cookies
python -m steam_skin_ops.profit sync
python -m steam_skin_ops.profit refresh
python -m steam_skin_ops.profit build
python -m steam_skin_ops.profit check-login
python -m steam_skin_ops.profit view
```

默认缓存位于 `data/profit/`，报告位于 `output/profit/`。第一次使用默认目录时，
程序会从旧版 `data/` 安全复制已知订单和汇率缓存；不会覆盖新文件或删除旧文件。

收益配置只包含个人交易客户端、汇率和报告设置，不包含监控配置。Cookie 文件
`config/profit.yaml` 已被 Git 忽略，禁止提交。

## 独立行情与监控服务

复制环境文件并启动：

```bash
copy .env.steam-skin-ops.example .env.steam-skin-ops
docker compose up -d
```

默认使用 `store` 告警驱动，服务只绑定 `127.0.0.1:8080`，不要求 AstrBot 或
`astrbot-internal` 网络。所有接口除 `/healthz` 外使用 Bearer Token：

```bash
curl -H "Authorization: Bearer <token>" \
  "http://127.0.0.1:8080/v2/market/quote?q=1579"
```

主要接口：

```text
GET  /v2/market/search?q=
GET  /v2/market/quote?q=
GET  /v2/market/history?q=&days=7
GET/POST/PATCH/DELETE /v2/rules
GET  /v2/events?recipient_key=&acknowledged=false
POST /v2/events/{id}/ack
POST /v2/events/test
GET  /v2/monitor/items
GET  /v2/monitor/status
GET  /healthz
```

规则类型：

- `ratio`：当前最低第三方平台价 ÷ 当前 Steam 到手价。
- `t7`：当前最低平台价 ÷ 过去 7 天 Steam 到手价 P25。
- `platform`：最低第三方平台价达到买入目标。
- `steam`：Steam 展示售价达到库存清理目标。

规则连续两轮满足才产生一次事件；解除条件连续两轮越过 3% 回差后重新布防。
默认每 30 分钟轮询，真实请求连续失败三轮才生成异常事件。

## AstrBot 集成

先创建外部网络并让 AstrBot 加入：

```bash
docker network create astrbot-internal
docker compose -f compose.yml -f compose.astrbot.yml up -d
```

将 `plugins/astrbot_plugin_steam_skin_ops` 复制到 AstrBot 数据目录的
`plugins/astrbot_plugin_steam_skin_ops`，配置：

```text
service_base_url=http://steam-skin-ops:8080
service_token=<与 STEAM_SKIN_OPS_SERVICE_TOKEN 相同>
```

插件提供 `/skin search`、`quote`、`rule`、`items`、`test`、`status`、`help`。
添加规则时会把 AstrBot UMO 当作不透明 `recipient_key`；核心服务不依赖其格式。

完整 VPS 部署与 v2 迁移见 [DEPLOY_ASTRBOT.md](DEPLOY_ASTRBOT.md)。

## 开发

```bash
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
```

目录边界测试会阻止 `profit` 与 `monitor` 相互导入，并确认监控镜像不包含 Cookie
收益模块。提交与 PR 标题必须遵循根目录 [AGENTS.md](AGENTS.md) 中带 scope 的
Conventional Commits。

## v3 破坏性变更

- 项目由 `buff2steam` 更名为 `steam-skin-ops`。
- Python 包改为 `steam_skin_ops`，不保留 `python src/main.py`。
- 监控环境变量改为 `STEAM_SKIN_OPS_*`。
- HTTP API 直接升级为 `/v2`，接收者字段由 `umo` 改为 `recipient_key`。
- AstrBot 插件 ID 改为 `astrbot_plugin_steam_skin_ops`。
- SQLite 启动时自动迁移规则接收者和告警事件，部署前仍必须备份数据库。
