"""
报告生成模块
使用 rich 库输出彩色终端表格，并导出 CSV
"""
from __future__ import annotations

import csv
import logging
import sys
from datetime import datetime
from pathlib import Path

# Ensure Windows terminal doesn't crash on Unicode emoji characters
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.columns import Columns
from rich.padding import Padding
from rich.style import Style

from ..calculator import TradeSummary
from ..matching import MatchedTrade, UnmatchedBuy, UnmatchedSell

logger = logging.getLogger(__name__)

console = Console()

GAME_LABEL = {
    "csgo": "CS2",
    "dota2": "DOTA2",
    "unknown": "?",
}


def _group_trades(trades: list[MatchedTrade]) -> list[dict]:
    groups = {}
    for t in trades:
        key = (t.buy_source, t.game, t.name, round(t.buy_price_cny, 2), round(t.sell_price_cny, 2))
        if key not in groups:
            groups[key] = {
                "game": t.game,
                "buy_source": t.buy_source,
                "name": t.name,
                "name_zh": t.name_zh,
                "buy_price_cny": t.buy_price_cny,
                "sell_price_cny": t.sell_price_cny,
                "total_profit_cny": 0.0,
                "hold_days_list": [],
                "bought_at_list": [],
                "sold_at_list": [],
                "count": 0,
            }
        g = groups[key]
        g["total_profit_cny"] += t.profit_cny
        g["hold_days_list"].append(t.hold_days)
        if t.bought_at:
            g["bought_at_list"].append(t.bought_at)
        if t.sold_at:
            g["sold_at_list"].append(t.sold_at)
        g["count"] += 1

    result = []
    for g in groups.values():
        avg_hold_days = round(sum(g["hold_days_list"]) / len(g["hold_days_list"])) if g["hold_days_list"] else 0
        if g["bought_at_list"]:
            bought_dates = [d[:10] for d in g["bought_at_list"] if d]
            bought_dates.sort()
            bought_range = bought_dates[0] if bought_dates[0] == bought_dates[-1] else f"{bought_dates[0][5:]}~{bought_dates[-1][5:]}"
        else:
            bought_range = "-"

        if g["sold_at_list"]:
            sold_dates = [d[:10] for d in g["sold_at_list"] if d]
            sold_dates.sort()
            sold_range = sold_dates[0] if sold_dates[0] == sold_dates[-1] else f"{sold_dates[0][5:]}~{sold_dates[-1][5:]}"
        else:
            sold_range = "-"

        total_buy = g["count"] * g["buy_price_cny"]
        total_received = g["count"] * g["sell_price_cny"]
        balance_ratio_pct = (
            total_buy / total_received * 100 if total_received > 0 else 0.0
        )
        latest_sold_at = max(g["sold_at_list"]) if g["sold_at_list"] else ""

        result.append({
            "game": g["game"],
            "buy_source": g["buy_source"],
            "name": g["name"],
            "name_zh": g["name_zh"],
            "buy_price_cny": g["buy_price_cny"],
            "sell_price_cny": g["sell_price_cny"],
            "total_profit_cny": g["total_profit_cny"],
            "balance_ratio_pct": balance_ratio_pct,
            "avg_hold_days": avg_hold_days,
            "bought_range": bought_range,
            "sold_range": sold_range,
            "count": g["count"],
            "latest_sold_at": latest_sold_at,
        })
    result.sort(key=lambda x: x["latest_sold_at"], reverse=True)
    return result


def _group_holdings(holdings: list[UnmatchedBuy]) -> list[dict]:
    groups = {}
    now = datetime.now()
    for b in holdings:
        key = (b.buy_source, b.game, b.name, round(b.buy_price_cny, 2))
        if key not in groups:
            groups[key] = {
                "game": b.game,
                "buy_source": b.buy_source,
                "name": b.name,
                "name_zh": b.name_zh,
                "buy_price_cny": b.buy_price_cny,
                "bought_at_list": [],
                "hold_days_list": [],
                "count": 0,
            }
        g = groups[key]
        if b.bought_at:
            g["bought_at_list"].append(b.bought_at)
            try:
                buy_dt = datetime.fromisoformat(b.bought_at)
                g["hold_days_list"].append((now - buy_dt).days)
            except (ValueError, TypeError):
                pass
        g["count"] += 1

    result = []
    for g in groups.values():
        if g["bought_at_list"]:
            bought_dates = [d[:10] for d in g["bought_at_list"] if d]
            bought_dates.sort()
            bought_range = bought_dates[0] if bought_dates[0] == bought_dates[-1] else f"{bought_dates[0][5:]}~{bought_dates[-1][5:]}"
            earliest_bought_at = min(g["bought_at_list"])
        else:
            bought_range = "-"
            earliest_bought_at = ""

        avg_hold_days = round(sum(g["hold_days_list"]) / len(g["hold_days_list"])) if g["hold_days_list"] else "-"

        result.append({
            "game": g["game"],
            "buy_source": g["buy_source"],
            "name": g["name"],
            "name_zh": g["name_zh"],
            "buy_price_cny": g["buy_price_cny"],
            "bought_range": bought_range,
            "avg_hold_days": avg_hold_days,
            "count": g["count"],
            "earliest_bought_at": earliest_bought_at,
        })
    result.sort(key=lambda x: x["earliest_bought_at"])
    return result


def _group_other_buys(holdings: list[UnmatchedBuy]) -> list[dict]:
    groups = {}
    for b in holdings:
        key = (b.buy_source, b.game, b.name, round(b.buy_price_cny, 2), b.buyer_steamid)
        if key not in groups:
            groups[key] = {
                "game": b.game,
                "buy_source": b.buy_source,
                "name": b.name,
                "name_zh": b.name_zh,
                "buy_price_cny": b.buy_price_cny,
                "buyer_steamid": b.buyer_steamid,
                "bought_at_list": [],
                "count": 0,
            }
        g = groups[key]
        if b.bought_at:
            g["bought_at_list"].append(b.bought_at)
        g["count"] += 1

    result = []
    for g in groups.values():
        if g["bought_at_list"]:
            bought_dates = [d[:10] for d in g["bought_at_list"] if d]
            bought_dates.sort()
            bought_range = bought_dates[0] if bought_dates[0] == bought_dates[-1] else f"{bought_dates[0][5:]}~{bought_dates[-1][5:]}"
            earliest_bought_at = min(g["bought_at_list"])
        else:
            bought_range = "-"
            earliest_bought_at = ""

        result.append({
            "game": g["game"],
            "buy_source": g["buy_source"],
            "name": g["name"],
            "name_zh": g["name_zh"],
            "buy_price_cny": g["buy_price_cny"],
            "buyer_steamid": g["buyer_steamid"],
            "bought_range": bought_range,
            "count": g["count"],
            "earliest_bought_at": earliest_bought_at,
        })
    result.sort(key=lambda x: x["earliest_bought_at"])
    return result


def _group_no_steamid_buys(holdings: list[UnmatchedBuy]) -> list[dict]:
    groups = {}
    for b in holdings:
        key = (b.buy_source, b.game, b.name, round(b.buy_price_cny, 2))
        if key not in groups:
            groups[key] = {
                "game": b.game,
                "buy_source": b.buy_source,
                "name": b.name,
                "name_zh": b.name_zh,
                "buy_price_cny": b.buy_price_cny,
                "bought_at_list": [],
                "count": 0,
            }
        g = groups[key]
        if b.bought_at:
            g["bought_at_list"].append(b.bought_at)
        g["count"] += 1

    result = []
    for g in groups.values():
        if g["bought_at_list"]:
            bought_dates = [d[:10] for d in g["bought_at_list"] if d]
            bought_dates.sort()
            bought_range = bought_dates[0] if bought_dates[0] == bought_dates[-1] else f"{bought_dates[0][5:]}~{bought_dates[-1][5:]}"
            earliest_bought_at = min(g["bought_at_list"])
        else:
            bought_range = "-"
            earliest_bought_at = ""

        result.append({
            "game": g["game"],
            "buy_source": g["buy_source"],
            "name": g["name"],
            "name_zh": g["name_zh"],
            "buy_price_cny": g["buy_price_cny"],
            "bought_range": bought_range,
            "count": g["count"],
            "earliest_bought_at": earliest_bought_at,
        })
    result.sort(key=lambda x: x["earliest_bought_at"])
    return result


class ReportGenerator:
    """报告生成器：终端彩色输出 + CSV 导出"""

    def __init__(self, output_dir: str = "./output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def print_full_report(
        self,
        trades: list[MatchedTrade],
        summary: TradeSummary,
        unmatched_buys: list[UnmatchedBuy],
        unmatched_sells: list[UnmatchedSell],
        unmatched_other_buys: list[UnmatchedBuy] = None,
        unmatched_no_steamid_buys: list[UnmatchedBuy] = None,
    ) -> None:
        """打印完整报告到终端"""
        console.print()
        self._print_banner()
        self._print_summary_panel(summary)
        self._print_trades_table(trades)

        if unmatched_buys:
            self._print_holdings_table(unmatched_buys)

        if unmatched_other_buys:
            self._print_other_buys_table(unmatched_other_buys)

        if unmatched_no_steamid_buys:
            self._print_no_steamid_buys_table(unmatched_no_steamid_buys)

        if unmatched_sells:
            self._print_unmatched_sells(unmatched_sells)

        self._print_game_breakdown(summary)

    def export_csv(
        self,
        trades: list[MatchedTrade],
        unmatched_buys: list[UnmatchedBuy],
        summary: TradeSummary,
        unmatched_other_buys: list[UnmatchedBuy] = None,
        unmatched_no_steamid_buys: list[UnmatchedBuy] = None,
    ) -> Path:
        """导出详细记录到 CSV 文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = self.output_dir / f"profit_report_{timestamp}.csv"

        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)

            # 表头
            writer.writerow([
                "状态", "游戏", "物品名称(英文)", "物品名称(中文)",
                "买入价(CNY)", "买入时间",
                "Steam到手价(原币)", "原始货币", "Steam到手价(CNY)",
                "卖出时间", "持仓天数",
                "净利润(CNY)", "倒余额比例(%)",
                "买入订单号", "Steam记录ID", "买入SteamID", "买入平台",
            ])

            # 已完成交易
            for t in sorted(trades, key=lambda x: x.sold_at, reverse=True):
                writer.writerow([
                    "已完成",
                    GAME_LABEL.get(t.game, t.game),
                    t.name,
                    t.name_zh,
                    f"{t.buy_price_cny:.2f}",
                    t.bought_at[:10] if t.bought_at else "",
                    f"{t.sell_price_received:.2f}",
                    t.sell_currency,
                    f"{t.sell_price_cny:.2f}",
                    t.sold_at[:10] if t.sold_at else "",
                    t.hold_days,
                    f"{t.profit_cny:.2f}",
                    f"{t.balance_ratio_pct:.2f}",
                    t.buy_order_no,
                    t.steam_row_id,
                    "",
                    t.buy_source.upper(),
                ])

            # 持仓未售出
            for b in unmatched_buys:
                writer.writerow([
                    "持仓中",
                    GAME_LABEL.get(b.game, b.game),
                    b.name,
                    b.name_zh,
                    f"{b.buy_price_cny:.2f}",
                    b.bought_at[:10] if b.bought_at else "",
                    "-", "-", "-", "-", "-", "-", "-",
                    b.buy_order_no, "-", b.buyer_steamid, b.buy_source.upper(),
                ])

            # 其他账号交易
            if unmatched_other_buys:
                for b in unmatched_other_buys:
                    writer.writerow([
                        "其他账号交易",
                        GAME_LABEL.get(b.game, b.game),
                        b.name,
                        b.name_zh,
                        f"{b.buy_price_cny:.2f}",
                        b.bought_at[:10] if b.bought_at else "",
                        "-", "-", "-", "-", "-", "-", "-",
                        b.buy_order_no, "-", b.buyer_steamid, b.buy_source.upper(),
                    ])

            # 缺失SteamID交易
            if unmatched_no_steamid_buys:
                for b in unmatched_no_steamid_buys:
                    writer.writerow([
                        "缺失SteamID交易",
                        GAME_LABEL.get(b.game, b.game),
                        b.name,
                        b.name_zh,
                        f"{b.buy_price_cny:.2f}",
                        b.bought_at[:10] if b.bought_at else "",
                        "-", "-", "-", "-", "-", "-", "-",
                        b.buy_order_no, "-", b.buyer_steamid, b.buy_source.upper(),
                    ])

            # 汇总行
            writer.writerow([])
            writer.writerow([
                "汇总", "", "", "",
                f"{summary.total_invested_cny:.2f}", "",
                "", "", f"{summary.total_received_cny:.2f}",
                "", f"{summary.avg_hold_days:.1f}",
                f"{summary.total_profit_cny:.2f}",
                f"{summary.balance_ratio_pct:.2f}",
                "", "", "", "",
            ])

        logger.info("[Report] CSV 已导出：%s", csv_path)
        console.print(f"\n📄 CSV 报告已导出：[cyan]{csv_path}[/cyan]")
        return csv_path

    def export_html(
        self,
        trades: list[MatchedTrade],
        unmatched_buys: list[UnmatchedBuy],
        summary: TradeSummary,
        unmatched_other_buys: list[UnmatchedBuy] = None,
        unmatched_no_steamid_buys: list[UnmatchedBuy] = None,
    ) -> Path:
        """导出交互式 HTML 看板报告"""
        from .html import generate_html_report

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_path = self.output_dir / f"profit_report_{timestamp}.html"

        generate_html_report(
            trades, 
            unmatched_buys, 
            summary, 
            html_path, 
            unmatched_other_buys=unmatched_other_buys,
            unmatched_no_steamid_buys=unmatched_no_steamid_buys
        )

        logger.info("[Report] HTML 看板已导出：%s", html_path)
        console.print(f"📊 网页看板已导出：[cyan]{html_path}[/cyan]")
        return html_path

    # ------------------------------------------------------------------
    # 终端输出方法
    # ------------------------------------------------------------------

    def _print_banner(self) -> None:
        title = Text("🗡  Steam 挂刀收益统计报告  🗡", style="bold bright_cyan")
        sub = Text(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                   style="dim")
        console.print(Panel(
            Padding(f"{title}\n{sub}", (1, 4)),
            box=box.DOUBLE_EDGE,
            style="bright_cyan",
            expand=False,
        ))

    def _print_summary_panel(self, summary: TradeSummary) -> None:
        profit_color = "bright_green" if summary.total_profit_cny >= 0 else "bright_red"

        lines = [
            f"[bold]完成交易[/bold]：[white]{summary.total_trades}[/white] 笔",
            f"[bold]总买入成本[/bold]：[yellow]¥{summary.total_invested_cny:,.2f}[/yellow]",
            f"[bold]总到手金额[/bold]：[yellow]¥{summary.total_received_cny:,.2f}[/yellow]",
            f"[bold]总净利润[/bold]：[{profit_color}]¥{summary.total_profit_cny:,.2f}[/{profit_color}]",
            f"[bold]倒余额比例[/bold]：[bright_blue]{summary.balance_ratio_pct:.2f}%[/bright_blue]",
            f"[bold]平均持仓[/bold]：[white]{summary.avg_hold_days:.1f}[/white] 天",
            f"[bold]当前持仓[/bold]：[cyan]{summary.holding_count}[/cyan] 件"
            f"（成本 [yellow]¥{summary.holding_invested_cny:,.2f}[/yellow]）",
        ]

        if summary.best_trade:
            t = summary.best_trade
            lines.append(
                f"[bold]最佳单笔[/bold]：[green]{t.name_zh or t.name}[/green]"
                f" +¥{t.profit_cny:.2f}（倒余额 {t.balance_ratio_pct:.1f}%）"
            )
        if summary.worst_trade and summary.worst_trade.profit_cny < 0:
            t = summary.worst_trade
            lines.append(
                f"[bold]最差单笔[/bold]：[red]{t.name_zh or t.name}[/red]"
                f" ¥{t.profit_cny:.2f}（倒余额 {t.balance_ratio_pct:.1f}%）"
            )

        console.print(Panel(
            "\n".join(lines),
            title="[bold bright_yellow]📊 总览[/bold bright_yellow]",
            border_style="yellow",
            padding=(1, 3),
        ))

    def _print_trades_table(self, trades: list[MatchedTrade]) -> None:
        if not trades:
            console.print("[dim]暂无已完成交易记录[/dim]")
            return

        grouped_trades = _group_trades(trades)

        table = Table(
            title=f"[bold]✅ 已完成交易明细（共 {len(trades)} 笔，合并为 {len(grouped_trades)} 组）[/bold]",
            box=box.ROUNDED,
            header_style="bold bright_white on #1a1a2e",
            border_style="bright_blue",
            show_lines=True,
            expand=True,
        )

        table.add_column("游戏", style="dim", width=6, justify="center")
        table.add_column("平台", style="cyan", width=6, justify="center")
        table.add_column("物品名称", min_width=20)
        table.add_column("数量", justify="center", width=6)
        table.add_column("买入单价\n(CNY)", justify="right", width=10)
        table.add_column("到手单价\n(CNY)", justify="right", width=10)
        table.add_column("总利润\n(CNY)", justify="right", width=10)
        table.add_column("倒余额\n比例", justify="right", width=8)
        table.add_column("平均持仓\n天数", justify="center", width=8)
        table.add_column("买入日期范围", justify="center", width=15)
        table.add_column("卖出日期范围", justify="center", width=15)

        for t in grouped_trades:
            profit_str = f"¥{t['total_profit_cny']:.2f}"
            balance_ratio_str = f"{t['balance_ratio_pct']:.1f}%"

            if t['total_profit_cny'] > 0:
                profit_style = "bright_green"
            elif t['total_profit_cny'] < 0:
                profit_style = "bright_red"
            else:
                profit_style = "white"

            name_display = t['name_zh'] if t['name_zh'] else t['name']
            if len(name_display) > 35:
                name_display = name_display[:33] + "…"

            table.add_row(
                GAME_LABEL.get(t['game'], t['game']),
                t['buy_source'].upper(),
                name_display,
                str(t['count']),
                f"¥{t['buy_price_cny']:.2f}",
                f"¥{t['sell_price_cny']:.2f}",
                Text(profit_str, style=profit_style),
                Text(balance_ratio_str, style="bright_blue"),
                str(t['avg_hold_days']),
                t['bought_range'],
                t['sold_range'],
            )

        console.print(table)

    def _print_holdings_table(self, holdings: list[UnmatchedBuy]) -> None:
        if not holdings:
            return

        grouped_holdings = _group_holdings(holdings)

        table = Table(
            title=f"[bold]📦 当前持仓（共 {len(holdings)} 件，合并为 {len(grouped_holdings)} 组）[/bold]",
            box=box.ROUNDED,
            header_style="bold bright_white on #1a2e1a",
            border_style="cyan",
            show_lines=True,
            expand=True,
        )

        table.add_column("游戏", style="dim", width=6, justify="center")
        table.add_column("平台", style="cyan", width=6, justify="center")
        table.add_column("物品名称", min_width=25)
        table.add_column("数量", justify="center", width=6)
        table.add_column("买入单价 (CNY)", justify="right", width=14)
        table.add_column("买入日期范围", justify="center", width=15)
        table.add_column("平均持有天数", justify="center", width=12)

        for b in grouped_holdings:
            name_display = b["name_zh"] if b["name_zh"] else b["name"]
            if len(name_display) > 40:
                name_display = name_display[:38] + "…"

            color = "yellow" if isinstance(b["avg_hold_days"], int) and b["avg_hold_days"] > 30 else "white"
            table.add_row(
                GAME_LABEL.get(b["game"], b["game"]),
                b["buy_source"].upper(),
                name_display,
                str(b["count"]),
                f"¥{b['buy_price_cny']:.2f}",
                b["bought_range"],
                Text(str(b["avg_hold_days"]), style=color),
            )

        console.print(table)

    def _print_other_buys_table(self, holdings: list[UnmatchedBuy]) -> None:
        if not holdings:
            return

        grouped_other = _group_other_buys(holdings)

        table = Table(
            title=f"[bold]🔌 其他账号买单（共 {len(holdings)} 件，合并为 {len(grouped_other)} 组）[/bold]",
            box=box.ROUNDED,
            header_style="bold bright_white on #2e1a2e",
            border_style="magenta",
            show_lines=True,
            expand=True,
        )

        table.add_column("游戏", style="dim", width=6, justify="center")
        table.add_column("平台", style="cyan", width=6, justify="center")
        table.add_column("物品名称", min_width=25)
        table.add_column("数量", justify="center", width=6)
        table.add_column("买入单价 (CNY)", justify="right", width=14)
        table.add_column("买入日期范围", justify="center", width=15)
        table.add_column("买入SteamID", justify="center", width=18)

        for b in grouped_other:
            name_display = b["name_zh"] if b["name_zh"] else b["name"]
            if len(name_display) > 40:
                name_display = name_display[:38] + "…"

            table.add_row(
                GAME_LABEL.get(b["game"], b["game"]),
                b["buy_source"].upper(),
                name_display,
                str(b["count"]),
                f"¥{b['buy_price_cny']:.2f}",
                b["bought_range"],
                b["buyer_steamid"] or "-",
            )

        console.print(table)

    def _print_no_steamid_buys_table(self, holdings: list[UnmatchedBuy]) -> None:
        if not holdings:
            return

        grouped_no_steamid = _group_no_steamid_buys(holdings)

        table = Table(
            title=f"[bold]❔ 缺失SteamID交易（共 {len(holdings)} 件，合并为 {len(grouped_no_steamid)} 组）[/bold]",
            box=box.ROUNDED,
            header_style="bold bright_white on #2e2e2e",
            border_style="bright_black",
            show_lines=True,
            expand=True,
        )

        table.add_column("游戏", style="dim", width=6, justify="center")
        table.add_column("平台", style="cyan", width=6, justify="center")
        table.add_column("物品名称", min_width=25)
        table.add_column("数量", justify="center", width=6)
        table.add_column("买入单价 (CNY)", justify="right", width=14)
        table.add_column("买入日期范围", justify="center", width=15)

        for b in grouped_no_steamid:
            name_display = b["name_zh"] if b["name_zh"] else b["name"]
            if len(name_display) > 40:
                name_display = name_display[:38] + "…"

            table.add_row(
                GAME_LABEL.get(b["game"], b["game"]),
                b["buy_source"].upper(),
                name_display,
                str(b["count"]),
                f"¥{b['buy_price_cny']:.2f}",
                b["bought_range"],
            )

        console.print(table)

    def _print_unmatched_sells(self, sells: list[UnmatchedSell]) -> None:
        console.print(Panel(
            f"[yellow]⚠ 发现 {len(sells)} 条 Steam 卖出记录无法匹配买单\n"
            "[dim]可能为礼物收到的物品、其他渠道购入或数据缺失[/dim]",
            border_style="yellow",
            padding=(0, 2),
        ))

    def _print_game_breakdown(self, summary: TradeSummary) -> None:
        if not summary.by_game:
            return

        panels = []
        for game, stats in summary.by_game.items():
            color = "bright_green" if stats["profit_cny"] >= 0 else "bright_red"
            content = (
                f"交易笔数：{stats['count']}\n"
                f"总买入：¥{stats['invested_cny']:,.2f}\n"
                f"净利润：[{color}]¥{stats['profit_cny']:,.2f}[/{color}]\n"
                f"倒余额比例：[bright_blue]{stats['balance_ratio_pct']:.2f}%[/bright_blue]"
            )
            panels.append(Panel(
                content,
                title=f"[bold]{GAME_LABEL.get(game, game)}[/bold]",
                border_style="magenta",
                width=28,
            ))

        if panels:
            console.print("\n[bold]🎮 按游戏分类[/bold]")
            console.print(Columns(panels))

    def view_csv(self, csv_path: Path) -> None:
        """从已导出的 CSV 报告中读取数据，并在终端进行友好的可视化展示（支持相同物品合并）"""
        if not csv_path.exists():
            console.print(f"[red]❌ 错误：CSV 报告文件不存在：{csv_path}[/red]")
            return

        console.print()
        console.print(Panel(
            Padding(Text(f"📖 正在读取并展示 CSV 报告：{csv_path.name}", style="bold bright_cyan"), (1, 4)),
            box=box.DOUBLE_EDGE,
            style="bright_cyan",
            expand=False,
        ))

        trades = []
        holdings = []
        other_buys = []
        no_steamid_buys = []
        summary_row = None

        try:
            with open(csv_path, encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                headers = next(reader)  # 跳过表头
                for row in reader:
                    if not row or not row[0].strip():
                        continue
                    status = row[0].strip()
                    if status == "已完成":
                        trades.append(row)
                    elif status == "持仓中":
                        holdings.append(row)
                    elif status == "其他账号交易":
                        other_buys.append(row)
                    elif status == "缺失SteamID交易":
                        no_steamid_buys.append(row)
                    elif status == "汇总":
                        summary_row = row
        except Exception as e:
            console.print(f"[red]❌ 读取 CSV 文件失败：{e}[/red]")
            return

        # 1. 展示汇总面板
        if summary_row:
            try:
                total_invested = float(summary_row[4]) if summary_row[4] else 0.0
                total_received = float(summary_row[8]) if summary_row[8] else 0.0
                avg_hold = float(summary_row[10]) if summary_row[10] else 0.0
                total_profit = float(summary_row[11]) if summary_row[11] else 0.0
                balance_ratio = (
                    total_invested / total_received * 100
                    if total_received > 0 else 0.0
                )
            except (ValueError, IndexError):
                total_invested = total_received = avg_hold = total_profit = balance_ratio = 0.0

            profit_color = "bright_green" if total_profit >= 0 else "bright_red"

            lines = [
                f"[bold]完成交易[/bold]：[white]{len(trades)}[/white] 笔",
                f"[bold]总买入成本[/bold]：[yellow]¥{total_invested:,.2f}[/yellow]",
                f"[bold]总到手金额[/bold]：[yellow]¥{total_received:,.2f}[/yellow]",
                f"[bold]总净利润[/bold]：[{profit_color}]¥{total_profit:,.2f}[/{profit_color}]",
                f"[bold]倒余额比例[/bold]：[bright_blue]{balance_ratio:.2f}%[/bright_blue]",
                f"[bold]平均持仓[/bold]：[white]{avg_hold:.1f}[/white] 天",
                f"[bold]当前持仓[/bold]：[cyan]{len(holdings)}[/cyan] 件",
            ]

            console.print(Panel(
                "\n".join(lines),
                title="[bold bright_yellow]📊 报告数据总览 (来自 CSV)[/bold bright_yellow]",
                border_style="yellow",
                padding=(1, 3),
            ))

        # 2. 已完成交易明细
        if trades:
            # Group trades
            g_trades = {}
            for t in trades:
                try:
                    game = t[1]
                    name_en = t[2]
                    name_zh = t[3]
                    buy_p = float(t[4]) if t[4] else 0.0
                    buy_t = t[5]
                    sell_p = float(t[8]) if t[8] else 0.0
                    sell_t = t[9]
                    hold = int(t[10]) if t[10] and t[10] != "-" else 0
                    prof = float(t[11]) if t[11] else 0.0
                    buy_source = t[16].upper() if len(t) > 16 and t[16] else "BUFF"
                except (ValueError, IndexError):
                    continue

                key = (buy_source, game, name_en, round(buy_p, 2), round(sell_p, 2))
                if key not in g_trades:
                    g_trades[key] = {
                        "buy_source": buy_source,
                        "game": game,
                        "name_en": name_en,
                        "name_zh": name_zh,
                        "buy_price": buy_p,
                        "sell_price": sell_p,
                        "total_profit": 0.0,
                        "hold_days_list": [],
                        "bought_at_list": [],
                        "sold_at_list": [],
                        "count": 0,
                    }
                gt = g_trades[key]
                gt["total_profit"] += prof
                gt["hold_days_list"].append(hold)
                if buy_t:
                    gt["bought_at_list"].append(buy_t)
                if sell_t:
                    gt["sold_at_list"].append(sell_t)
                gt["count"] += 1

            grouped_trades_list = []
            for gt in g_trades.values():
                avg_hold = round(sum(gt["hold_days_list"]) / len(gt["hold_days_list"])) if gt["hold_days_list"] else 0
                if gt["bought_at_list"]:
                    b_dates = [d[:10] for d in gt["bought_at_list"] if d]
                    b_dates.sort()
                    b_range = b_dates[0] if b_dates[0] == b_dates[-1] else f"{b_dates[0][5:]}~{b_dates[-1][5:]}"
                else:
                    b_range = "-"

                if gt["sold_at_list"]:
                    s_dates = [d[:10] for d in gt["sold_at_list"] if d]
                    s_dates.sort()
                    s_range = s_dates[0] if s_dates[0] == s_dates[-1] else f"{s_dates[0][5:]}~{s_dates[-1][5:]}"
                    latest_sold = max(gt["sold_at_list"])
                else:
                    s_range = "-"
                    latest_sold = ""

                total_buy = gt["count"] * gt["buy_price"]
                total_received = gt["count"] * gt["sell_price"]
                balance_ratio_pct = (
                    total_buy / total_received * 100 if total_received > 0 else 0.0
                )

                grouped_trades_list.append({
                    "buy_source": gt["buy_source"],
                    "game": gt["game"],
                    "name_en": gt["name_en"],
                    "name_zh": gt["name_zh"],
                    "buy_price": gt["buy_price"],
                    "sell_price": gt["sell_price"],
                    "total_profit": gt["total_profit"],
                    "balance_ratio": balance_ratio_pct,
                    "avg_hold_days": avg_hold,
                    "bought_range": b_range,
                    "sold_range": s_range,
                    "count": gt["count"],
                    "latest_sold_at": latest_sold,
                })
            grouped_trades_list.sort(key=lambda x: x["latest_sold_at"], reverse=True)

            max_display = 30
            display_trades = grouped_trades_list[:max_display]

            table = Table(
                title=f"[bold]✅ 已完成交易明细（共 {len(trades)} 笔，合并展示前 {len(display_trades)}/{len(grouped_trades_list)} 组）[/bold]",
                box=box.ROUNDED,
                header_style="bold bright_white on #1a1a2e",
                border_style="bright_blue",
                show_lines=True,
                expand=True,
            )
            table.add_column("游戏", style="dim", width=6, justify="center")
            table.add_column("平台", width=5, justify="center")
            table.add_column("物品名称", min_width=14, overflow="fold")
            table.add_column("数量", justify="center", width=6)
            table.add_column("买入单价\n(CNY)", justify="right", width=10)
            table.add_column("到手单价\n(CNY)", justify="right", width=10)
            table.add_column("总利润\n(CNY)", justify="right", width=10)
            table.add_column("倒余额\n比例", justify="right", width=8)
            table.add_column("平均持仓\n天数", justify="center", width=8)
            table.add_column("买入日期范围", justify="center", width=11)
            table.add_column("卖出日期范围", justify="center", width=11)

            for t in display_trades:
                profit_str = f"¥{t['total_profit']:.2f}"
                balance_ratio_str = f"{t['balance_ratio']:.1f}%"

                if t['total_profit'] > 0:
                    profit_style = "bright_green"
                elif t['total_profit'] < 0:
                    profit_style = "bright_red"
                else:
                    profit_style = "white"

                name_display = t['name_zh'] if t['name_zh'] else t['name_en']
                if len(name_display) > 35:
                    name_display = name_display[:33] + "…"

                table.add_row(
                    t['game'],
                    t['buy_source'],
                    name_display,
                    str(t['count']),
                    f"¥{t['buy_price']:.2f}",
                    f"¥{t['sell_price']:.2f}",
                    Text(profit_str, style=profit_style),
                    Text(balance_ratio_str, style="bright_blue"),
                    str(t['avg_hold_days']),
                    t['bought_range'],
                    t['sold_range'],
                )
            console.print(table)
            if len(grouped_trades_list) > max_display:
                console.print(f"[dim]💡 已省略较早的 {len(grouped_trades_list) - max_display} 组已完成交易，完整明细请在原 CSV 文件或 HTML 看板中查看。[/dim]\n")
        else:
            console.print("[dim]报告中无已完成交易记录[/dim]")

        # 3. 持仓中明细
        if holdings:
            # Group holdings
            g_holdings = {}
            now = datetime.now()
            for b in holdings:
                try:
                    game = b[1]
                    name_en = b[2]
                    name_zh = b[3]
                    buy_p = float(b[4]) if b[4] else 0.0
                    buy_t = b[5]
                    buy_source = b[16].upper() if len(b) > 16 and b[16] else "BUFF"
                except (ValueError, IndexError):
                    continue

                key = (buy_source, game, name_en, round(buy_p, 2))
                if key not in g_holdings:
                    g_holdings[key] = {
                        "buy_source": buy_source,
                        "game": game,
                        "name_en": name_en,
                        "name_zh": name_zh,
                        "buy_price": buy_p,
                        "bought_at_list": [],
                        "hold_days_list": [],
                        "count": 0,
                    }
                gh = g_holdings[key]
                if buy_t:
                    gh["bought_at_list"].append(buy_t)
                    try:
                        buy_dt = datetime.fromisoformat(buy_t)
                        gh["hold_days_list"].append((now - buy_dt).days)
                    except (ValueError, TypeError):
                        pass
                gh["count"] += 1

            grouped_holdings_list = []
            for gh in g_holdings.values():
                if gh["bought_at_list"]:
                    b_dates = [d[:10] for d in gh["bought_at_list"] if d]
                    b_dates.sort()
                    b_range = b_dates[0] if b_dates[0] == b_dates[-1] else f"{b_dates[0][5:]}~{b_dates[-1][5:]}"
                    earliest_b = min(gh["bought_at_list"])
                else:
                    b_range = "-"
                    earliest_b = ""

                avg_hold = round(sum(gh["hold_days_list"]) / len(gh["hold_days_list"])) if gh["hold_days_list"] else "-"

                grouped_holdings_list.append({
                    "buy_source": gh["buy_source"],
                    "game": gh["game"],
                    "name_en": gh["name_en"],
                    "name_zh": gh["name_zh"],
                    "buy_price": gh["buy_price"],
                    "bought_range": b_range,
                    "avg_hold_days": avg_hold,
                    "count": gh["count"],
                    "earliest_bought_at": earliest_b,
                })
            grouped_holdings_list.sort(key=lambda x: x["earliest_bought_at"])

            max_display = 30
            display_holdings = grouped_holdings_list[:max_display]

            table_h = Table(
                title=f"[bold]📦 当前持仓明细（共 {len(holdings)} 件，合并展示前 {len(display_holdings)}/{len(grouped_holdings_list)} 组）[/bold]",
                box=box.ROUNDED,
                header_style="bold bright_white on #1a2e1a",
                border_style="cyan",
                show_lines=True,
                expand=True,
            )
            table_h.add_column("游戏", style="dim", width=6, justify="center")
            table_h.add_column("平台", width=6, justify="center")
            table_h.add_column("物品名称", min_width=25)
            table_h.add_column("数量", justify="center", width=6)
            table_h.add_column("买入单价 (CNY)", justify="right", width=14)
            table_h.add_column("买入日期范围", justify="center", width=15)
            table_h.add_column("平均持有天数", justify="center", width=12)

            for b in display_holdings:
                name_display = b["name_zh"] if b["name_zh"] else b["name_en"]
                if len(name_display) > 40:
                    name_display = name_display[:38] + "…"

                color = "yellow" if isinstance(b["avg_hold_days"], int) and b["avg_hold_days"] > 30 else "white"
                table_h.add_row(
                    b['game'],
                    b['buy_source'],
                    name_display,
                    str(b['count']),
                    f"¥{b['buy_price']:.2f}",
                    b['bought_range'],
                    Text(str(b['avg_hold_days']), style=color),
                )
            console.print(table_h)
            if len(grouped_holdings_list) > max_display:
                console.print(f"[dim]💡 已省略较早的 {len(grouped_holdings_list) - max_display} 组持仓记录，完整明细请在原 CSV 文件或 HTML 看板中查看。[/dim]\n")

        # 4. 其他账号买单明细
        if other_buys:
            # Group other buys
            g_other = {}
            for b in other_buys:
                try:
                    game = b[1]
                    name_en = b[2]
                    name_zh = b[3]
                    buy_p = float(b[4]) if b[4] else 0.0
                    buy_t = b[5]
                    buyer_steamid = b[15] if len(b) > 15 else ""
                    buy_source = b[16].upper() if len(b) > 16 and b[16] else "BUFF"
                except (ValueError, IndexError):
                    continue

                key = (buy_source, game, name_en, round(buy_p, 2), buyer_steamid)
                if key not in g_other:
                    g_other[key] = {
                        "buy_source": buy_source,
                        "game": game,
                        "name_en": name_en,
                        "name_zh": name_zh,
                        "buy_price": buy_p,
                        "buyer_steamid": buyer_steamid,
                        "bought_at_list": [],
                        "count": 0,
                    }
                go = g_other[key]
                if buy_t:
                    go["bought_at_list"].append(buy_t)
                go["count"] += 1

            grouped_other_list = []
            for go in g_other.values():
                if go["bought_at_list"]:
                    b_dates = [d[:10] for d in go["bought_at_list"] if d]
                    b_dates.sort()
                    b_range = b_dates[0] if b_dates[0] == b_dates[-1] else f"{b_dates[0][5:]}~{b_dates[-1][5:]}"
                    earliest_b = min(go["bought_at_list"])
                else:
                    b_range = "-"
                    earliest_b = ""

                grouped_other_list.append({
                    "buy_source": go["buy_source"],
                    "game": go["game"],
                    "name_en": go["name_en"],
                    "name_zh": go["name_zh"],
                    "buy_price": go["buy_price"],
                    "buyer_steamid": go["buyer_steamid"],
                    "bought_range": b_range,
                    "count": go["count"],
                    "earliest_bought_at": earliest_b,
                })
            grouped_other_list.sort(key=lambda x: x["earliest_bought_at"])

            max_display = 30
            display_other = grouped_other_list[:max_display]

            table_o = Table(
                title=f"[bold]🔌 其他账号买单明细（共 {len(other_buys)} 件，合并展示前 {len(display_other)}/{len(grouped_other_list)} 组）[/bold]",
                box=box.ROUNDED,
                header_style="bold bright_white on #2e1a2e",
                border_style="magenta",
                show_lines=True,
                expand=True,
            )
            table_o.add_column("游戏", style="dim", width=6, justify="center")
            table_o.add_column("平台", width=6, justify="center")
            table_o.add_column("物品名称", min_width=25)
            table_o.add_column("数量", justify="center", width=6)
            table_o.add_column("买入单价 (CNY)", justify="right", width=14)
            table_o.add_column("买入日期范围", justify="center", width=15)
            table_o.add_column("买入SteamID", justify="center", width=18)

            for b in display_other:
                name_display = b["name_zh"] if b["name_zh"] else b["name_en"]
                if len(name_display) > 40:
                    name_display = name_display[:38] + "…"

                table_o.add_row(
                    b['game'],
                    b['buy_source'],
                    name_display,
                    str(b['count']),
                    f"¥{b['buy_price']:.2f}",
                    b['bought_range'],
                    b['buyer_steamid'] or "-",
                )
            console.print(table_o)
            if len(grouped_other_list) > max_display:
                console.print(f"[dim]💡 已省略较早的 {len(grouped_other_list) - max_display} 组其他账号交易记录，完整明细请在原 CSV 文件或 HTML 看板中查看。[/dim]\n")

        # 5. 缺失SteamID交易明细
        if no_steamid_buys:
            # Group no steamid buys
            g_no_steamid = {}
            for b in no_steamid_buys:
                try:
                    game = b[1]
                    name_en = b[2]
                    name_zh = b[3]
                    buy_p = float(b[4]) if b[4] else 0.0
                    buy_t = b[5]
                    buy_source = b[16].upper() if len(b) > 16 and b[16] else "BUFF"
                except (ValueError, IndexError):
                    continue

                key = (buy_source, game, name_en, round(buy_p, 2))
                if key not in g_no_steamid:
                    g_no_steamid[key] = {
                        "buy_source": buy_source,
                        "game": game,
                        "name_en": name_en,
                        "name_zh": name_zh,
                        "buy_price": buy_p,
                        "bought_at_list": [],
                        "count": 0,
                    }
                gns = g_no_steamid[key]
                if buy_t:
                    gns["bought_at_list"].append(buy_t)
                gns["count"] += 1

            grouped_no_steamid_list = []
            for gns in g_no_steamid.values():
                if gns["bought_at_list"]:
                    b_dates = [d[:10] for d in gns["bought_at_list"] if d]
                    b_dates.sort()
                    b_range = b_dates[0] if b_dates[0] == b_dates[-1] else f"{b_dates[0][5:]}~{b_dates[-1][5:]}"
                    earliest_b = min(gns["bought_at_list"])
                else:
                    b_range = "-"
                    earliest_b = ""

                grouped_no_steamid_list.append({
                    "buy_source": gns["buy_source"],
                    "game": gns["game"],
                    "name_en": gns["name_en"],
                    "name_zh": gns["name_zh"],
                    "buy_price": gns["buy_price"],
                    "bought_range": b_range,
                    "count": gns["count"],
                    "earliest_bought_at": earliest_b,
                })
            grouped_no_steamid_list.sort(key=lambda x: x["earliest_bought_at"])

            max_display = 30
            display_no_steamid = grouped_no_steamid_list[:max_display]

            table_ns = Table(
                title=f"[bold]❔ 缺失SteamID交易明细（共 {len(no_steamid_buys)} 件，合并展示前 {len(display_no_steamid)}/{len(grouped_no_steamid_list)} 组）[/bold]",
                box=box.ROUNDED,
                header_style="bold bright_white on #2e2e2e",
                border_style="bright_black",
                show_lines=True,
                expand=True,
            )
            table_ns.add_column("游戏", style="dim", width=6, justify="center")
            table_ns.add_column("平台", width=6, justify="center")
            table_ns.add_column("物品名称", min_width=25)
            table_ns.add_column("数量", justify="center", width=6)
            table_ns.add_column("买入单价 (CNY)", justify="right", width=14)
            table_ns.add_column("买入日期范围", justify="center", width=15)

            for b in display_no_steamid:
                name_display = b["name_zh"] if b["name_zh"] else b["name_en"]
                if len(name_display) > 40:
                    name_display = name_display[:38] + "…"

                table_ns.add_row(
                    b['game'],
                    b['buy_source'],
                    name_display,
                    str(b['count']),
                    f"¥{b['buy_price']:.2f}",
                    b['bought_range'],
                )
            console.print(table_ns)
            if len(grouped_no_steamid_list) > max_display:
                console.print(f"[dim]💡 已省略较早的 {len(grouped_no_steamid_list) - max_display} 组缺失SteamID交易记录，完整明细请在原 CSV 文件或 HTML 看板中查看。[/dim]\n")


