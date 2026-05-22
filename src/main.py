"""
主入口
读取配置 → 拉取 BUFF/Steam 数据 → 匹配 → 计算 → 输出报告
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Steam 挂刀收益统计工具（BUFF → Steam）"
    )
    parser.add_argument(
        "--config", default="config.yaml",
        help="配置文件路径（默认：config.yaml）"
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="忽略本地缓存，强制重新拉取数据"
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
        "--view-csv", nargs="?", const="latest", default=None,
        help="在终端友好地展示指定的 CSV 报告。如果未指定路径，则展示最新生成的报告。"
    )
    parser.add_argument(
        "--open-html", action="store_true",
        help="导出 HTML 看板后，自动在浏览器中打开"
    )
    args = parser.parse_args()

    # 1. 加载配置
    cfg = load_config(args.config)
    buff_cfg = cfg.get("buff", {})
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
    )

    buff_client = BuffClient(
        cookie=buff_cfg.get("cookie", ""),
        page_size=buff_cfg.get("page_size", 20),
        max_pages=buff_cfg.get("max_pages", 100),
    )

    steam_client = SteamClient(
        session_id=steam_cfg.get("session_id", ""),
        steam_login_secure=steam_cfg.get("steam_login_secure", ""),
        default_currency=steam_cfg.get("default_currency", 23),
    )

    matcher = TransactionMatcher(converter=converter)
    calculator = ProfitCalculator()
    reporter = ReportGenerator(output_dir=output_dir)

    # 2.5 检查是否是查看 CSV 报告模式
    if args.view_csv is not None:
        csv_path = None
        if args.view_csv == "latest":
            p_output_dir = Path(output_dir)
            csv_files = list(p_output_dir.glob("profit_report_*.csv"))
            if not csv_files:
                logger.error("在输出目录 %s 中未找到任何 CSV 报告！", output_dir)
                sys.exit(1)
            csv_files.sort()
            csv_path = csv_files[-1]
        else:
            csv_path = Path(args.view_csv)
            if not csv_path.exists():
                logger.error("指定的 CSV 报告文件不存在：%s", csv_path)
                sys.exit(1)
        
        reporter.view_csv(csv_path)
        sys.exit(0)

    # 3. Cookie 验证
    if not args.skip_login_check:
        logger.info("正在验证 Cookie...")
        buff_ok = buff_client.check_login()
        steam_ok = steam_client.check_login()
        if not buff_ok or not steam_ok:
            logger.error("Cookie 验证失败，请更新配置后重试。使用 --skip-login-check 跳过此步骤。")
            sys.exit(1)

    # 提取当前登录的 Steam ID
    current_steam_id = steam_cfg.get("steam_id", "")
    if not current_steam_id:
        current_steam_id = extract_steam_id(steam_cfg.get("steam_login_secure", ""))
    if current_steam_id:
        logger.info("当前登录的 Steam ID: %s", current_steam_id)
    else:
        logger.warning("未检测到当前 Steam ID，将跳过按 Steam 账号分区匹配的逻辑")

    # 4. 拉取 BUFF 买单历史（CS2 + DOTA2）
    games: list[str] = buff_cfg.get("games", ["csgo"])
    all_buff_orders: list[dict] = []

    for game in games:
        cache_file = data_dir / f"buff_{game}_orders.json" if not args.no_cache else None
        orders = buff_client.fetch_buy_orders(game=game, cache_path=cache_file)
        all_buff_orders.extend(orders)

    logger.info("BUFF 总计买单：%d 条（CS2+DOTA2）", len(all_buff_orders))

    # 5. 拉取 Steam 卖单历史
    steam_cache = data_dir / "steam_sales.json" if not args.no_cache else None
    steam_sales = steam_client.fetch_sell_history(
        cache_path=steam_cache,
        fetch_count=steam_cfg.get("fetch_count", 500),
    )
    logger.info("Steam 总计卖单：%d 条", len(steam_sales))

    # 6. 日期范围过滤（可选）
    date_from = settings.get("date_from") or ""
    date_to = settings.get("date_to") or ""
    if date_from or date_to:
        all_buff_orders, steam_sales = _apply_date_filter(
            all_buff_orders, steam_sales, date_from, date_to
        )

    # 7. FIFO 匹配
    match_result = matcher.match(all_buff_orders, steam_sales, current_steam_id=current_steam_id)

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


def _apply_date_filter(
    buff_orders: list[dict],
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

    filtered_buff = [o for o in buff_orders if in_range(o.get("created_at", ""))]
    filtered_steam = [s for s in steam_sales if in_range(s.get("sold_at", ""))]

    logger.info("日期过滤 [%s ~ %s]：BUFF %d→%d 条，Steam %d→%d 条",
                date_from or "始", date_to or "今",
                len(buff_orders), len(filtered_buff),
                len(steam_sales), len(filtered_steam))

    return filtered_buff, filtered_steam


if __name__ == "__main__":
    main()
