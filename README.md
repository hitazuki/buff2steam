# buff2steam — Steam 挂刀收益统计工具

> 自动拉取 **网易 BUFF** 买单历史和 **Steam** 社区市场卖单历史，按 FIFO 策略配对，统计每笔挂刀交易的净利润与 ROI。

## 功能特性

- ✅ 支持 **CS2（CSGO）** 和 **DOTA2** 双游戏
- ✅ 自动拉取 BUFF 买单历史（分页）
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

### 3. 运行

```bash
python src/main.py
```

### 常用参数

```bash
# 强制刷新数据（忽略缓存）
python src/main.py --no-cache

# 仅打印报告，不导出 CSV
python src/main.py --no-export

# 指定配置文件
python src/main.py --config my_config.yaml

# 跳过 Cookie 验证（加快启动）
python src/main.py --skip-login-check

# 友好展示最新生成的 CSV 报告（不请求网络数据）
python src/main.py --view-csv

# 友好展示指定的 CSV 报告文件
python src/main.py --view-csv output/profit_report_xxxx.csv

# 导出 HTML 看板后，自动在浏览器中打开
python src/main.py --open-html
```

## 项目结构

```
buff2steam/
├── src/
│   ├── main.py                # 主入口
│   ├── buff_client.py         # BUFF API 客户端
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

## 收益计算说明

```
净利润 = Steam到手价(CNY) - BUFF买入价(CNY)
ROI    = 净利润 / BUFF买入价 × 100%
```

- **Steam到手价**：已经是扣除平台手续费（Steam 5% + 游戏开发商 10% = 共15%）后的到账金额
- **BUFF买入价**：买家直接支付的价格，无额外手续费
- **多货币处理**：若 Steam 账号为非 CNY 区，自动按实时汇率换算

## 注意事项

- Cookie 有效期通常为数天至数周，过期后需重新获取
- Steam 市场历史接口有频率限制，脚本已内置延迟
- 本地缓存默认 6 小时有效期，可在配置中调整
- 数据仅用于个人统计，请勿滥用接口
