"""
主入口
读取配置 → 拉取 BUFF/C5/Steam 数据 → 匹配 → 计算 → 输出报告
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

# 确保 src 包可被找到
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.buff_client import BuffClient
from src.c5_client import C5Client, C5ClientError
from src.steam_client import SteamClient
from src.currency_converter import CurrencyConverter
from src.transaction_matcher import TransactionMatcher
from src.profit_calculator import ProfitCalculator
from src.report import ReportGenerator

# ------------------------------------------------------------------
# 日志配置
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def extract_steam_id(steam_login_secure: str) -> str:
    """从 steam_login_secure cookie 中提取 17 位 SteamID64"""
    if not steam_login_secure:
        return ""
    from urllib.parse import unquote
    unquoted = unquote(steam_login_secure)
    if "||" in unquoted:
        return unquoted.split("||", 1)[0].strip()
    return ""


def load_config(config_path: str = "config.yaml") -> dict:
    """加载配置文件"""
    p = Path(config_path)
    if not p.exists():
        logger.error("配置文件 %s 不存在！请先复制 config.example.yaml → config.yaml 并填入 Cookie", p)
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Steam 挂刀收益统计工具（BUFF/C5 → Steam）"
    )
    parser.add_argument(
        "command",
        choices=("sync", "refresh", "build", "check-login", "view", "monitor"),
        help=(
            "执行动作：sync 增量抓取后聚合；refresh 全量抓取后聚合；"
            "build 使用本地数据聚合并导出；check-login 仅校验 Cookie；"
            "view 查看已导出的 CSV；monitor 运行行情监控"
        ),
    )
    parser.add_argument(
        "view_path",
        nargs="?",
        help="view 命令要查看的 CSV 路径；省略时查看最新报告",
    )
    parser.add_argument(
        "--platform",
        dest="platforms",
        action="append",
        choices=("buff", "c5", "steam"),
        help="仅操作指定平台；可重复传入，例如 --platform buff --platform steam",
    )
    parser.add_argument(
        "--config", default="config.yaml",
        help="配置文件路径（默认：config.yaml）"
    )
    parser.add_argument(
        "--no-export", action="store_true",
        help="不导出 CSV 文件，仅在终端打印"
    )
    parser.add_argument(
        "--skip-login-check", action="store_true",
        help="跳过 Cookie 有效性检查（加快启动）"
    )
    parser.add_argument(
        "--open-html", action="store_true",
        help="导出 HTML 看板后，自动在浏览器中打开"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="monitor 命令仅执行一轮后退出"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="monitor 命令保存行情并评估策略，但不发送通知或改变告警状态"
    )
    parser.add_argument(
        "--test-notify", action="store_true",
        help="monitor 命令发送一条 PushPlus 测试通知后退出"
    )
    parser.add_argument(
        "--status", action="store_true",
        help="monitor 命令显示最近行情和监控状态后退出"
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "view" and args.view_path is not None:
        parser.error("只有 view 命令可以指定 CSV 路径")
    if args.skip_login_check and args.command not in {"sync", "refresh"}:
        parser.error("--skip-login-check 仅用于 sync 或 refresh")
    if (args.no_export or args.open_html) and args.command not in {"sync", "refresh", "build"}:
        parser.error("--no-export 和 --open-html 仅用于 sync、refresh 或 build")
    if args.no_export and args.open_html:
        parser.error("--no-export 与 --open-html 不能同时使用")
    if args.platforms and args.command in {"build", "view"}:
        parser.error(f"{args.command} 不访问平台，不接受 --platform")
    monitor_flags = (args.once, args.dry_run, args.test_notify, args.status)
    if args.command != "monitor" and any(monitor_flags):
        parser.error("--once/--dry-run/--test-notify/--status 仅用于 monitor")
    if args.command == "monitor":
        if args.view_path is not None:
            parser.error("monitor 不接受额外位置参数")
        if args.platforms or args.no_export or args.open_html or args.skip_login_check:
            parser.error("monitor 不接受交易统计命令的选项")
        if sum(bool(value) for value in (args.test_notify, args.status)) > 1:
            parser.error("--test-notify 与 --status 不能同时使用")
        if (args.test_notify or args.status) and (args.once or args.dry_run):
            parser.error("--test-notify/--status 不能与 --once/--dry-run 组合")
        if args.dry_run and not args.once:
            parser.error("--dry-run 必须与 --once 一起使用")

    # 1. 加载配置
    cfg = load_config(args.config)

    if args.command == "monitor":
        _run_monitor_command(cfg, args)
        return

    buff_cfg = cfg.get("buff", {})
    c5_cfg = cfg.get("c5", {})
    steam_cfg = cfg.get("steam", {})
    currency_cfg = cfg.get("currency", {})
    settings = cfg.get("settings", {})

    data_dir = Path(settings.get("data_dir", "./data"))
    output_dir = settings.get("output_dir", "./output")
    cache_ttl = settings.get("cache_ttl_hours", 6)

    # 2. 初始化各模块
    converter = CurrencyConverter(
        fallback_rates=currency_cfg.get("fallback_rates", {}),
        cache_path=data_dir / "exchange_rates.json",
        cache_ttl_hours=cache_ttl,
        allow_online=args.command in {"sync", "refresh"},
    )

    buff_client = BuffClient(
        cookie=buff_cfg.get("cookie", ""),
        page_size=buff_cfg.get("page_size", 20),
        max_pages=buff_cfg.get("max_pages", 100),
    )

    c5_enabled = bool(c5_cfg.get("enabled", False))
    if args.platforms and "c5" in args.platforms and not c5_enabled:
        parser.error("C5 未启用；请先在配置中设置 c5.enabled: true")
    c5_client = C5Client(
        cookie=c5_cfg.get("cookie", ""),
        page_size=c5_cfg.get("page_size", 60),
        max_pages=c5_cfg.get("max_pages", 100),
    ) if c5_enabled else None

    steam_client = SteamClient(
        session_id=steam_cfg.get("session_id", ""),
        steam_login_secure=steam_cfg.get("steam_login_secure", ""),
        default_currency=steam_cfg.get("default_currency", 23),
    )

    matcher = TransactionMatcher(converter=converter)
    calculator = ProfitCalculator()
    reporter = ReportGenerator(output_dir=output_dir)

    # 2.5 查看已导出的 CSV 报告，不校验 Cookie、不抓取数据。
    if args.command == "view":
        csv_path = None
        if args.view_path is None:
            p_output_dir = Path(output_dir)
            csv_files = list(p_output_dir.glob("profit_report_*.csv"))
            if not csv_files:
                logger.error("在输出目录 %s 中未找到任何 CSV 报告！", output_dir)
                sys.exit(1)
            csv_files.sort()
            csv_path = csv_files[-1]
        else:
            csv_path = Path(args.view_path)
            if not csv_path.exists():
                logger.error("指定的 CSV 报告文件不存在：%s", csv_path)
                sys.exit(1)
        
        reporter.view_csv(csv_path)
        sys.exit(0)

    # 3. 按平台校验与抓取。单个平台失败不会阻止其他平台继续执行。
    configured_platforms = {"buff", "steam"}
    if c5_enabled:
        configured_platforms.add("c5")
    selected_platforms = set(args.platforms or configured_platforms)
    network_action = args.command in {"sync", "refresh", "check-login"}
    failed_platforms: set[str] = set()

    clients = {
        "buff": buff_client,
        "steam": steam_client,
        "c5": c5_client,
    }
    if network_action and not args.skip_login_check:
        for platform in ("buff", "c5", "steam"):
            if platform not in selected_platforms:
                continue
            logger.info("正在验证 %s Cookie...", platform.upper())
            client = clients[platform]
            if client is None or not client.check_login():
                failed_platforms.add(platform)

    if args.command == "check-login":
        if failed_platforms:
            logger.error("Cookie 校验失败的平台：%s", ", ".join(sorted(failed_platforms)))
            raise SystemExit(1)
        logger.info("所选平台 Cookie 均有效：%s", ", ".join(sorted(selected_platforms)))
        return

    games: list[str] = buff_cfg.get("games", ["csgo"])
    fetch_platforms = selected_platforms - failed_platforms if network_action else set()
    force_refresh = args.command == "refresh"
    incremental = args.command == "sync"

    if "buff" in fetch_platforms:
        for game in games:
            buff_client.fetch_buy_orders(
                game=game,
                cache_path=data_dir / f"buff_{game}_orders.json",
                force_refresh=force_refresh,
                incremental=incremental,
            )

    if "c5" in fetch_platforms and c5_client:
        try:
            c5_client.fetch_buy_orders(
                games=games,
                cache_path=data_dir / "c5_buy_orders.json",
                force_refresh=force_refresh,
                incremental=incremental,
            )
        except C5ClientError as exc:
            logger.error("C5 抓取失败：%s", exc)
            failed_platforms.add("c5")

    if "steam" in fetch_platforms:
        steam_client.fetch_sell_history(
            cache_path=data_dir / "steam_sales.json",
            fetch_count=steam_cfg.get("fetch_count", 500),
            force_refresh=force_refresh,
            incremental=incremental,
        )

    # 提取当前登录的 Steam ID
    current_steam_id = steam_cfg.get("steam_id", "")
    if not current_steam_id:
        current_steam_id = extract_steam_id(steam_cfg.get("steam_login_secure", ""))
    if current_steam_id:
        logger.info("当前登录的 Steam ID: %s", current_steam_id)
    else:
        if c5_enabled:
            logger.error(
                "启用 C5 时必须能确定当前 SteamID。请配置 steam.steam_id，"
                "或提供有效的 steam_login_secure，避免跨账号混算。"
            )
            sys.exit(1)
        else:
            logger.warning("未检测到当前 Steam ID，将跳过按 Steam 账号分区匹配的逻辑")

    # 4. 从本地数据聚合买单历史（联网动作已在上方更新缓存）
    all_buy_orders: list[dict] = []

    for game in games:
        cache_file = data_dir / f"buff_{game}_orders.json"
        _require_local_cache(cache_file)
        orders = buff_client.fetch_buy_orders(
            game=game,
            cache_path=cache_file,
        )
        all_buy_orders.extend(orders)

    logger.info("BUFF 总计买单：%d 条", len(all_buy_orders))

    if c5_client:
        c5_cache = data_dir / "c5_buy_orders.json"
        _require_local_cache(c5_cache)
        try:
            c5_orders = c5_client.fetch_buy_orders(
                games=games,
                cache_path=c5_cache,
            )
        except C5ClientError as exc:
            logger.error("C5 买单拉取失败，为避免使用不完整数据，本次统计已终止：%s", exc)
            sys.exit(1)
        all_buy_orders.extend(c5_orders)
        logger.info("C5 总计买单：%d 件", len(c5_orders))

    logger.info("全部平台总计买单：%d 件", len(all_buy_orders))

    # 5. 从本地数据读取 Steam 卖单历史
    steam_cache = data_dir / "steam_sales.json"
    _require_local_cache(steam_cache)
    steam_sales = steam_client.fetch_sell_history(
        cache_path=steam_cache,
        fetch_count=steam_cfg.get("fetch_count", 500),
    )
    logger.info("Steam 总计卖单：%d 条", len(steam_sales))

    # 6. 日期范围过滤（可选）
    date_from = settings.get("date_from") or ""
    date_to = settings.get("date_to") or ""
    if date_from or date_to:
        all_buy_orders, steam_sales = _apply_date_filter(
            all_buy_orders, steam_sales, date_from, date_to
        )

    # 7. FIFO 匹配
    match_result = matcher.match(all_buy_orders, steam_sales, current_steam_id=current_steam_id)

    # 8. 收益计算
    trades, summary = calculator.calculate(match_result)

    # 9. 输出报告
    reporter.print_full_report(
        trades=trades,
        summary=summary,
        unmatched_buys=match_result.unmatched_buys,
        unmatched_sells=match_result.unmatched_sells,
        unmatched_other_buys=match_result.unmatched_other_buys,
        unmatched_no_steamid_buys=match_result.unmatched_no_steamid_buys,
    )

    # 10. 导出 CSV 和 HTML 看板
    if not args.no_export:
        reporter.export_csv(
            trades, 
            match_result.unmatched_buys, 
            summary, 
            unmatched_other_buys=match_result.unmatched_other_buys,
            unmatched_no_steamid_buys=match_result.unmatched_no_steamid_buys
        )
        html_path = reporter.export_html(
            trades, 
            match_result.unmatched_buys, 
            summary, 
            unmatched_other_buys=match_result.unmatched_other_buys,
            unmatched_no_steamid_buys=match_result.unmatched_no_steamid_buys
        )
        if args.open_html:
            import webbrowser
            logger.info("正在浏览器中打开 HTML 报告看板...")
            webbrowser.open(html_path.absolute().as_uri())

    if failed_platforms:
        logger.error(
            "报告已使用本地缓存生成，但以下平台本次未更新：%s",
            ", ".join(sorted(failed_platforms)),
        )
        raise SystemExit(1)


def _require_local_cache(cache_path: Path) -> None:
    """聚合前确认抓取阶段已生成所需的本地数据。"""
    if not cache_path.exists():
        logger.error("本地数据不存在：%s；请确认对应平台已成功抓取", cache_path)
        raise SystemExit(1)


def _run_monitor_command(cfg: dict, args: argparse.Namespace) -> None:
    """构建并运行独立行情监控，不初始化个人交易客户端。"""
    import os
    from datetime import datetime

    from dotenv import load_dotenv

    from src.monitoring.runner import MonitorRunner
    from src.monitoring.service import MonitorService
    from src.monitoring.smis_client import SmisClient
    from src.monitoring.storage import MonitorStorage
    from src.monitoring.strategy import ThresholdStrategy
    from src.notifications import CompositeNotifier, ConsoleNotifier, PushPlusNotifier

    load_dotenv()
    monitor_cfg = cfg.get("monitoring", {})
    settings = cfg.get("settings", {})
    item_cfg = monitor_cfg.get("item", {})
    item = {
        "item_key": item_cfg.get("item_key", "csgo:fracture_case"),
        "appid": int(item_cfg.get("appid", 730)),
        "smis_id": int(item_cfg.get("smis_id", 1579)),
        "name": item_cfg.get("name", "Fracture Case"),
        "name_zh": item_cfg.get("name_zh", "裂空武器箱"),
        "platform": item_cfg.get("platform", "buff"),
    }
    if item["platform"] != "buff":
        raise SystemExit("第一版监控仅支持 platform: buff")

    data_dir = Path(settings.get("data_dir", "./data"))
    database = Path(monitor_cfg.get("database", data_dir / "monitor.db"))
    storage = MonitorStorage(database)

    if args.status:
        state = storage.get_state(item["item_key"])
        snapshot = storage.latest_snapshot(item["item_key"])
        logger.info("监控状态：%s", state)
        if snapshot:
            logger.info("最近行情：%s", snapshot)
        else:
            logger.info("尚无实时行情快照")
        return

    notification_cfg = cfg.get("notifications", {}).get("pushplus", {})
    token_env = notification_cfg.get("token_env", "PUSHPLUS_TOKEN")
    token = os.getenv(token_env, "").strip()
    console_notifier = ConsoleNotifier()
    if args.dry_run:
        notifier = console_notifier
    else:
        if notification_cfg.get("enabled", True) and not token:
            raise SystemExit(
                f"PushPlus 已启用但环境变量 {token_env} 未设置；"
                "请配置 token，或使用 monitor --once --dry-run"
            )
        channels = [console_notifier]
        if notification_cfg.get("enabled", True):
            channels.append(PushPlusNotifier(
                token=token,
                timeout=float(notification_cfg.get("timeout_seconds", 10)),
                max_retries=int(notification_cfg.get("max_retries", 2)),
            ))
        notifier = CompositeNotifier(channels)

    if args.test_notify:
        result = notifier.send(
            "【buff2steam】行情监控测试",
            f"PushPlus 通知连接成功。<br>测试时间：{datetime.now().isoformat(timespec='seconds')}",
        )
        if not result.success:
            logger.error("测试通知失败：%s", result.message)
            raise SystemExit(1)
        logger.info("测试通知成功：%s", result.message)
        return

    source_cfg = monitor_cfg.get("source", {})
    source = SmisClient(
        timeout=float(source_cfg.get("timeout_seconds", 15)),
        max_retries=int(source_cfg.get("max_retries", 3)),
        auth_key=source_cfg.get("auth_key", SmisClient.DEFAULT_AUTH_KEY),
        auth2=source_cfg.get("auth2", SmisClient.DEFAULT_AUTH2),
    )
    strategy_cfg = monitor_cfg.get("strategy", {})
    strategy = ThresholdStrategy(
        max_ratio=float(strategy_cfg.get("max_ratio", 0.72)),
        max_age_minutes=int(strategy_cfg.get("max_age_minutes", 15)),
        min_buff_sell_num=int(strategy_cfg.get("min_buff_sell_num", 100)),
        min_steam_volume=int(strategy_cfg.get("min_steam_volume", 1000)),
    )
    service = MonitorService(
        item=item,
        source=source,
        storage=storage,
        strategy=strategy,
        notifier=notifier,
        history_days=int(monitor_cfg.get("history_days", 30)),
        confirmations=int(strategy_cfg.get("confirmations", 2)),
        clear_confirmations=int(strategy_cfg.get("clear_confirmations", 2)),
        health_failure_threshold=int(monitor_cfg.get("health_failure_threshold", 3)),
    )
    if args.once:
        result = service.run_once(dry_run=args.dry_run)
        if not result.success:
            raise SystemExit(1)
        return
    MonitorRunner(service, int(monitor_cfg.get("interval_seconds", 300))).run()


def _apply_date_filter(
    buy_orders: list[dict],
    steam_sales: list[dict],
    date_from: str,
    date_to: str,
) -> tuple[list[dict], list[dict]]:
    """按日期范围过滤记录"""
    from datetime import datetime

    def in_range(dt_str: str) -> bool:
        if not dt_str:
            return True
        try:
            dt = datetime.fromisoformat(dt_str[:10])
        except ValueError:
            return True
        if date_from and dt < datetime.fromisoformat(date_from):
            return False
        if date_to and dt > datetime.fromisoformat(date_to):
            return False
        return True

    filtered_buys = [o for o in buy_orders if in_range(o.get("created_at", ""))]
    filtered_steam = [s for s in steam_sales if in_range(s.get("sold_at", ""))]

    logger.info("日期过滤 [%s ~ %s]：买单 %d→%d 条，Steam %d→%d 条",
                date_from or "始", date_to or "今",
                len(buy_orders), len(filtered_buys),
                len(steam_sales), len(filtered_steam))

    return filtered_buys, filtered_steam


if __name__ == "__main__":
    main()
