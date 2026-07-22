# buff2steam — Steam 挂刀收益统计工具

> 自动拉取 **网易 BUFF / C5GAME** 买单历史和 **Steam** 社区市场卖单历史，按账号隔离后使用 FIFO 策略配对，统计每笔挂刀交易的净利润与倒余额比例。

## 功能特性

- ✅ 支持 **CS2（CSGO）** 和 **DOTA2** 双游戏
- ✅ 自动拉取 BUFF 买单历史（分页）
- ✅ 可选拉取 C5 成功买单（手动 Cookie、只读请求）
- ✅ BUFF/C5 跨平台统一 FIFO，并按接收 SteamID 隔离账号
- ✅ 自动拉取 Steam 市场卖单历史
- ✅ **多货币支持**：自动获取实时汇率，将所有收入换算为 CNY
- ✅ FIFO 自动配对（先买先出）
- ✅ 彩色终端表格报告（`rich`）
- ✅ **CSV 报表查看器**：直接在控制台查看已导出的 CSV，防刷屏设计
- ✅ **HTML 交互看板**：自动生成可视化网页，支持实时排序、过滤和分页
- ✅ 本地数据缓存，避免重复请求

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 Cookie

项目内置了自动化和手动两种获取 Cookie 的方式。

#### 选项 A：使用脚本自动获取并写入（推荐 🚀）

脚本会自动以调试模式拉起 Chrome，提取 Cookie 并直接写入 `config.yaml`。

1. **复制配置模板**：
   ```bash
   copy config.example.yaml config.yaml
   ```
2. **关闭所有 Chrome 窗口**（非常重要，避免调试端口冲突）。
3. **运行提取脚本**：
   ```bash
   python get_cookies.py
   ```
4. **登录网页**：在脚本自动打开的 Chrome 调试窗口中，分别登录 **BUFF** 和 **Steam** 账号。
5. **完成提取**：登录完成后，回到终端按 `Enter` 键，脚本即可自动完成抓取并自动保存至 `config.yaml`。

> [!NOTE]
> 该脚本完全在本地运行，直接调用本地 Chrome 调试接口（CDP），不经过任何第三方服务器，安全可靠。

#### 选项 B：手动获取并填入（备用 📝）

如果自动脚本不可用，可以手动提取并修改 `config.yaml`：

* **获取 BUFF Cookie**：
  1. 浏览器打开 [BUFF](https://buff.163.com) 并登录。
  2. 按 `F12` 打开开发者工具 → 切换到 **Application (应用)** 选项卡 → 左侧展开 **Cookies** → 选择 `https://buff.163.com`。
  3. 复制 `session` 字段的值，填入 `config.yaml` 中 `buff` 部分的 `cookie` 字段（如：`cookie: "session=xxxx"`）。

* **获取 Steam Cookie**：
  1. 浏览器打开 [Steam 社区](https://steamcommunity.com) 并登录。
  2. 按 `F12` 打开开发者工具 → 切换到 **Application (应用)** 选项卡 → 左侧展开 **Cookies** → 选择 `https://steamcommunity.com`。
  3. 复制 `sessionid` 和 `steamLoginSecure` 的值，分别填入 `config.yaml` 中 `steam` 部分的 `session_id` 和 `steam_login_secure` 字段。

* **启用 C5 买单（可选）**：
  1. 浏览器登录 [C5GAME](https://www.c5game.com)。
  2. 从浏览器站点 Cookie 中复制完整 Cookie 请求串，填入 `c5.cookie`。
  3. 将 `c5.enabled` 改为 `true`。C5 第一版不会被 `get_cookies.py` 自动提取，也不会使用 `app-key`。

```yaml
c5:
  enabled: true
  cookie: "你的完整 C5 Cookie"
  page_size: 60
  max_pages: 100
```

> C5 客户端只调用账号信息、成功买单列表和买单详情三个 GET 接口。Cookie 与账单缓存位于被 `.gitignore` 排除的本地配置和 `data/` 目录，不需要外部服务器。
> 启用 C5 时必须能从 `steam_login_secure` 识别当前 SteamID；若无法识别，请显式填写 `steam.steam_id`，程序不会在账号未知时混算。

### 3. 运行

```bash
# 增量抓取，随后自动聚合并导出报告
python src/main.py sync

# 跳过抓取，使用本地数据聚合并导出报告
python src/main.py build
```

### 命令与常用参数

```bash
# 全量重新抓取，随后自动聚合并导出报告
python src/main.py refresh

# 仅校验各平台 Cookie，不拉取交易记录
python src/main.py check-login

# 只校验 Steam Cookie
python src/main.py check-login --platform steam

# 增量抓取 BUFF 和 Steam，然后使用全部本地数据聚合报告
python src/main.py sync --platform buff --platform steam

# 使用本地数据聚合并在终端展示，不导出 CSV/HTML
python src/main.py build --no-export

# 指定配置文件
python src/main.py sync --config my_config.yaml

# 同步时跳过 Cookie 预检（实际拉取仍可能因 Cookie 过期而失败）
python src/main.py sync --skip-login-check

# 友好展示最新生成的 CSV 报告（不请求网络数据）
python src/main.py view

# 友好展示指定的 CSV 报告文件
python src/main.py view output/profit_report_xxxx.csv

# 导出 HTML 看板后，自动在浏览器中打开
python src/main.py build --open-html
```

## 裂空武器箱行情监控

监控子系统使用 SMIS 行情，以 BUFF 买入并挂到 Steam 的预计余额比例作为信号。首次运行会尝试回填 30 天历史；实时行情与告警状态保存在 `data/monitor.db`。

先在 [PushPlus](https://www.pushplus.plus/) 获取个人 token，并设置环境变量：

```powershell
$env:PUSHPLUS_TOKEN="你的 PushPlus token"
```

常用命令：

```bash
# 验证 PushPlus 通知
python src/main.py monitor --test-notify

# 获取行情、回填历史并评估，但不发通知、不改变告警状态
python src/main.py monitor --once --dry-run

# 正式执行一轮
python src/main.py monitor --once

# 每 5 分钟长期运行，Ctrl+C 安全退出
python src/main.py monitor

# 查看最近行情和状态
python src/main.py monitor --status
```

默认策略要求挂刀比例不高于 72%、数据不超过 15 分钟、BUFF 在售数不少于 100、Steam 日成交量不少于 1000，并连续命中两次。阈值可在 `config.yaml` 的 `monitoring.strategy` 中调整。

`--platform` 可选 `buff`、`c5`、`steam`，需要选择多个平台时重复传入。未指定时操作全部已启用平台。若某个平台 Cookie 校验失败，其他通过校验的平台仍会继续抓取；命令最终以非零状态退出并列出失败平台。`sync` 或 `refresh` 随后生成报告时，失败或未选择的平台会继续使用已有本地缓存。

命令必须显式指定，不提供无参数默认动作。`sync` 和 `refresh` 抓取完成后都会自动执行与 `build` 相同的聚合、终端展示和导出流程。项目不再提供旧版参数兼容入口。

## 项目结构

```
buff2steam/
├── src/
│   ├── main.py                # 主入口
│   ├── buff_client.py         # BUFF API 客户端
│   ├── c5_client.py           # C5 Cookie 只读客户端
│   ├── steam_client.py        # Steam API 客户端
│   ├── currency_converter.py  # 多货币汇率转换
│   ├── transaction_matcher.py # FIFO 买卖配对
│   ├── profit_calculator.py   # 收益计算
│   └── report.py              # 报告生成（终端+CSV）
├── data/                      # 本地缓存（自动生成）
├── output/                    # CSV 报告输出（自动生成）
├── config.example.yaml        # 配置模板
├── config.yaml                # 实际配置（需自行创建，已 gitignore）
└── requirements.txt
```

## AstrBot 查询与监控服务

项目可作为独立 Docker 服务与 AstrBot 部署在同一 VPS，通过内部网络提供行情查询、
按 QQ 会话订阅和主动告警。服务不需要部署个人 BUFF/Steam Cookie。

仓库提供两份 Compose 配置：

- [`compose.yml`](compose.yml)：buff2steam 行情与监控服务。
- [`compose.astrbot.example.yml`](compose.astrbot.example.yml)：参考实际 VPS
  AstrBot 配置整理的独立部署样例。

两个容器通过外部网络 `astrbot-internal` 互访。网络只需创建一次：

```bash
docker network create astrbot-internal
```

新部署 AstrBot 时，将样例复制到独立的 AstrBot 目录并命名为 `compose.yml`：

```bash
mkdir -p ~/astrbot && cd ~/astrbot
cp /path/to/buff2steam/compose.astrbot.example.yml compose.yml
docker compose up -d
```

已有 AstrBot Compose 时无需覆盖原配置，只需为 `astrbot` 服务和顶层网络增加
`astrbot-internal`，并保留 `external: true`。AstrBot WebUI 示例端口为 `6185`；
公网部署时应通过防火墙、反向代理或其他访问控制保护管理界面。

插件配置中的 `service_token` 必须与 buff2steam 的
`BUFF2STEAM_SERVICE_TOKEN` 相同；`ASTRBOT_API_KEY` 则是 buff2steam
主动调用 AstrBot OpenAPI 使用的、仅含 `im` 权限的 Key，两者不要混用。

AstrBot 插件统一使用英文命令：

```text
/skin quote <SMIS_ID|名称>
/skin items
/skin watch list
/skin watch add <SMIS_ID> [MAX_RATIO_PERCENT]
/skin watch remove <SMIS_ID>
/skin watch threshold <SMIS_ID> <MAX_RATIO_PERCENT>
/skin watch test
/skin watch status
/skin help
```

完整部署步骤见 [DEPLOY_ASTRBOT.md](DEPLOY_ASTRBOT.md)。

Docker 镜像会在推送 `v*` Git 标签时由 GitHub Actions 自动构建并发布到
`docker.io/hitazuki/buff2steam`，支持 `linux/amd64` 和 `linux/arm64`。

## 收益计算说明

```
净利润 = Steam到手价(CNY) - 买入价(CNY)
倒余额比例 = 买入价 / Steam到手价 × 100%
```

- **Steam到手价**：已经是扣除平台手续费（Steam 5% + 游戏开发商 10% = 共15%）后的到账金额
- **倒余额比例**：以百分数显示，例如花费 ¥80 获得 ¥100 Steam 余额，比例为 80%；数值越低越划算
- **买入价**：BUFF 使用订单价格；C5 优先使用实际支付金额，多饰品订单按原价比例精确分摊到分
- **多货币处理**：若 Steam 账号为非 CNY 区，自动按实时汇率换算

## 注意事项

- Cookie 有效期通常为数天至数周，过期后需重新获取
- Steam 市场历史接口有频率限制，脚本已内置延迟
- 本地缓存默认 6 小时有效期，可在配置中调整
- 数据仅用于个人统计，请勿滥用接口
