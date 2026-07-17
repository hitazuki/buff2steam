"""
HTML 报告生成模板
提供交互式可视化网页，以图表和卡片形式展现挂刀统计数据
"""
import json
from pathlib import Path
from datetime import datetime

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Steam 挂刀收益分析看板</title>
    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Chart.js CDN -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <!-- Google Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Noto+Sans+SC:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Noto Sans SC', sans-serif;
            background: radial-gradient(circle at top right, #1e1b4b, #0f172a, #020617);
        }
        .font-display {
            font-family: 'Outfit', sans-serif;
        }
        .glass {
            background: rgba(30, 41, 59, 0.45);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
        .glow-emerald {
            box-shadow: 0 0 25px -5px rgba(16, 185, 129, 0.15);
        }
        .glow-red {
            box-shadow: 0 0 25px -5px rgba(239, 68, 68, 0.15);
        }
        .glow-blue {
            box-shadow: 0 0 25px -5px rgba(59, 130, 246, 0.15);
        }
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }
        ::-webkit-scrollbar-track {
            background: rgba(15, 23, 42, 0.6);
        }
        ::-webkit-scrollbar-thumb {
            background: rgba(71, 85, 105, 0.5);
            border-radius: 9999px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(100, 116, 139, 0.8);
        }
    </style>
</head>
<body class="min-h-screen text-slate-100 pb-16 font-sans">

    <!-- 顶部导航栏 -->
    <header class="border-b border-slate-800/60 sticky top-0 z-50 bg-slate-950/80 backdrop-blur-md">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div class="flex items-center gap-3">
                <div class="h-10 w-10 rounded-xl bg-gradient-to-tr from-indigo-500 to-emerald-400 flex items-center justify-center text-white text-xl font-bold shadow-lg">
                    🗡️
                </div>
                <div>
                    <h1 class="text-xl sm:text-2xl font-bold tracking-tight bg-gradient-to-r from-white via-slate-100 to-slate-400 bg-clip-text text-transparent">
                        Steam 挂刀收益分析看板
                    </h1>
                    <p class="text-xs text-slate-400">BUFF/C5 买单 × Steam 卖单 (FIFO 先进先出自动对账系统)</p>
                </div>
            </div>
            <div class="flex items-center gap-3">
                <span class="text-xs px-2.5 py-1 rounded-full bg-slate-800 border border-slate-700/60 text-slate-400">
                    生成时间: <span class="font-display" id="generated-time">2026-05-22 18:00:00</span>
                </span>
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-8 space-y-8">

        <!-- 汇总卡片网格 -->
        <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            <!-- 累计净利润 -->
            <div class="glass rounded-2xl p-6 glow-emerald hover:border-emerald-500/30 transition-all duration-300">
                <div class="flex items-center justify-between">
                    <span class="text-sm font-medium text-slate-400">累计净利润</span>
                    <span class="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">CNY</span>
                </div>
                <div class="mt-4 flex items-baseline gap-2">
                    <span class="text-3xl font-bold tracking-tight text-emerald-400 font-display" id="stat-total-profit">¥0.00</span>
                </div>
                <div class="mt-2 text-xs text-slate-400 flex items-center gap-1.5">
                    <span>总完成</span>
                    <span class="font-display font-semibold text-slate-200" id="stat-total-trades">0</span>
                    <span>笔交易</span>
                </div>
            </div>

            <!-- 平均投资回报率 -->
            <div class="glass rounded-2xl p-6 glow-blue hover:border-blue-500/30 transition-all duration-300">
                <div class="flex items-center justify-between">
                    <span class="text-sm font-medium text-slate-400">平均投资回报率 (ROI)</span>
                    <span class="text-xs px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 font-medium">ROI</span>
                </div>
                <div class="mt-4 flex items-baseline gap-2">
                    <span class="text-3xl font-bold tracking-tight text-blue-400 font-display" id="stat-avg-roi">0.00%</span>
                </div>
                <div class="mt-2 text-xs text-slate-400 flex items-center gap-1.5">
                    <span>平均持仓天数:</span>
                    <span class="font-display font-semibold text-slate-200" id="stat-avg-hold">0.0</span>
                    <span>天</span>
                </div>
            </div>

            <!-- 资金往来 -->
            <div class="glass rounded-2xl p-6 hover:border-slate-500/30 transition-all duration-300">
                <div class="flex items-center justify-between">
                    <span class="text-sm font-medium text-slate-400">总投入成本 / 到手金额</span>
                    <span class="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-medium">流水</span>
                </div>
                <div class="mt-4 space-y-1">
                    <div class="flex justify-between items-center">
                        <span class="text-xs text-slate-400">买入总额:</span>
                        <span class="font-semibold font-display text-slate-300" id="stat-total-invested">¥0.00</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-xs text-slate-400">Steam到手:</span>
                        <span class="font-semibold font-display text-slate-200" id="stat-total-received">¥0.00</span>
                    </div>
                </div>
                <div class="mt-3 h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                    <div class="h-full bg-gradient-to-r from-indigo-500 to-emerald-400 rounded-full" id="stat-cashflow-progress" style="width: 50%"></div>
                </div>
            </div>

            <!-- 当前持仓 -->
            <div class="glass rounded-2xl p-6 glow-red hover:border-red-500/30 transition-all duration-300">
                <div class="flex items-center justify-between">
                    <span class="text-sm font-medium text-slate-400">当前持仓</span>
                    <span class="text-xs px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-medium">库存</span>
                </div>
                <div class="mt-4 flex items-baseline gap-2">
                    <span class="text-3xl font-bold tracking-tight text-cyan-400 font-display" id="stat-holding-count">0</span>
                    <span class="text-sm text-slate-400">件</span>
                </div>
                <div class="mt-2 text-xs text-slate-400 flex items-center gap-1.5">
                    <span>持仓总成本:</span>
                    <span class="font-display font-semibold text-yellow-400/90" id="stat-holding-invested">¥0.00</span>
                </div>
            </div>
        </section>

        <!-- 图表网格 -->
        <div id="empty-trades-notice" class="hidden rounded-xl border border-amber-500/20 bg-amber-500/5 px-5 py-3 text-sm text-amber-200">
            当前没有可与本 Steam 账号买单匹配的卖出记录，因此收益图表为空；买入记录仍完整保留在下方各分类标签中。
        </div>

        <section class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <!-- 累计收益趋势线图 -->
            <div class="glass rounded-2xl p-6 lg:col-span-2 space-y-4">
                <h3 class="font-bold text-slate-200 flex items-center gap-2">
                    📈 累计收益趋势图
                </h3>
                <div class="h-80 w-full relative">
                    <canvas id="trend-chart"></canvas>
                </div>
            </div>

            <!-- 游戏类目收益占比饼图 -->
            <div class="glass rounded-2xl p-6 space-y-4 flex flex-col justify-between">
                <h3 class="font-bold text-slate-200 flex items-center gap-2">
                    🎮 游戏分类统计占比
                </h3>
                <div class="h-64 w-full relative flex items-center justify-center">
                    <canvas id="game-chart"></canvas>
                </div>
                <div class="flex justify-around text-xs text-slate-400 border-t border-slate-800/80 pt-4 mt-2">
                    <div class="text-center">
                        <span class="inline-block w-2.5 h-2.5 rounded-full bg-blue-500 mr-1.5"></span>CS2:
                        <span class="font-semibold text-slate-200 font-display" id="game-cs2-profit">¥0.00</span>
                    </div>
                    <div class="text-center">
                        <span class="inline-block w-2.5 h-2.5 rounded-full bg-emerald-400 mr-1.5"></span>DOTA2:
                        <span class="font-semibold text-slate-200 font-display" id="game-dota2-profit">¥0.00</span>
                    </div>
                </div>
            </div>
        </section>

        <!-- 数据表格与分类选项卡 -->
        <section class="glass rounded-2xl overflow-hidden shadow-2xl">
            <div id="data-coverage-note" class="px-6 py-3 border-b border-slate-800/60 bg-indigo-500/5 text-xs text-slate-300"></div>
            <!-- 标签页选择器与搜索过滤 -->
            <div class="p-6 border-b border-slate-800/60 space-y-4">
                <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                    <!-- Tab Buttons -->
                    <div class="flex flex-wrap rounded-xl bg-slate-950 p-1 border border-slate-800">
                        <button id="tab-btn-trades" onclick="switchTab('trades')" class="px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 bg-slate-800 text-white shadow">
                            ✅ 已完成交易明细 <span id="tab-count-trades" class="font-display text-xs">(0)</span>
                        </button>
                        <button id="tab-btn-holdings" onclick="switchTab('holdings')" class="px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 text-slate-400 hover:text-slate-200">
                            📦 当前持有持仓 <span id="tab-count-holdings" class="font-display text-xs">(0)</span>
                        </button>
                        <button id="tab-btn-other-holdings" onclick="switchTab('other-holdings')" class="px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 text-slate-400 hover:text-slate-200">
                            🔌 其他账号买单 <span id="tab-count-other" class="font-display text-xs">(0)</span>
                        </button>
                        <button id="tab-btn-no-steamid" onclick="switchTab('no-steamid')" class="px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 text-slate-400 hover:text-slate-200">
                            ❔ 缺失SteamID交易 <span id="tab-count-missing" class="font-display text-xs">(0)</span>
                        </button>
                    </div>

                    <!-- 搜索框 -->
                    <div class="relative w-full sm:w-72">
                        <span class="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-500">🔍</span>
                        <input type="text" id="search-input" oninput="handleFilter()" placeholder="搜索饰品名称、订单号..." 
                               class="w-full pl-9 pr-4 py-2 rounded-xl bg-slate-900 border border-slate-800 text-sm placeholder-slate-500 focus:outline-none focus:border-indigo-500/50 focus:ring-2 focus:ring-indigo-500/10 text-slate-200 transition-all duration-200">
                    </div>
                </div>

                <!-- 细微过滤器 -->
                <div class="flex flex-wrap items-center gap-3 text-xs">
                    <span class="text-slate-500 font-medium">筛选:</span>
                    <!-- 游戏筛选 -->
                    <select id="filter-game" onchange="handleFilter()" class="bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg text-slate-300 focus:outline-none focus:border-indigo-500/50">
                        <option value="all">所有游戏</option>
                        <option value="csgo">CS2</option>
                        <option value="dota2">DOTA2</option>
                    </select>

                    <!-- 仅在交易明细 Tab 显示：利润状态筛选 -->
                    <select id="filter-profit" onchange="handleFilter()" class="bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg text-slate-300 focus:outline-none focus:border-indigo-500/50">
                        <option value="all">所有利润状态</option>
                        <option value="gain">仅盈利</option>
                        <option value="loss">仅亏损</option>
                    </select>

                    <button onclick="resetFilters()" class="text-slate-400 hover:text-indigo-400 font-semibold px-2 py-1 transition-colors">
                        重置筛选
                    </button>
                </div>
            </div>

            <!-- 数据表格体 -->
            <div class="overflow-x-auto min-h-[300px]">
                <table class="w-full text-left border-collapse">
                    <thead class="bg-slate-950/60 text-slate-400 text-xs font-semibold uppercase tracking-wider border-b border-slate-800/80">
                        <tr id="table-headers">
                            <!-- JS 渲染表头 -->
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-800/40 text-sm text-slate-300" id="table-body">
                        <!-- JS 渲染数据行 -->
                    </tbody>
                </table>
            </div>

            <!-- 分页控件 -->
            <div class="p-4 border-t border-slate-800/60 bg-slate-950/20 flex items-center justify-between gap-4">
                <div class="text-xs text-slate-400">
                    共 <span class="font-semibold text-slate-300" id="total-count-display">0</span> 条记录，
                    当前显示第 <span class="font-semibold text-slate-300 font-display" id="page-range-display">1 - 15</span> 条
                </div>
                <div class="flex items-center gap-2">
                    <button id="prev-page-btn" onclick="changePage(-1)" class="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 hover:border-slate-700 disabled:opacity-40 text-xs text-slate-300 disabled:hover:border-slate-800 transition-all">
                        上一页
                    </button>
                    <span class="text-xs text-slate-400 font-display" id="current-page-display">1 / 1</span>
                    <button id="next-page-btn" onclick="changePage(1)" class="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 hover:border-slate-700 disabled:opacity-40 text-xs text-slate-300 disabled:hover:border-slate-800 transition-all">
                        下一页
                    </button>
                </div>
            </div>
        </section>
    </main>

    <!-- 注入的静态数据 -->
    <script id="dashboard-raw-data" type="application/json">
    DATA_PLACEHOLDER
    </script>

    <!-- 逻辑脚本 -->
    <script>
        const RAW_DATA = JSON.parse(document.getElementById('dashboard-raw-data').textContent);
        
        let currentTab = RAW_DATA.trades.length > 0
            ? 'trades'
            : (RAW_DATA.holdings.length > 0
                ? 'holdings'
                : ((RAW_DATA.other_holdings || []).length > 0
                    ? 'other-holdings'
                    : 'no-steamid'));
        let filteredTrades = [...RAW_DATA.trades];
        let filteredHoldings = [...RAW_DATA.holdings];
        let filteredOtherHoldings = [...(RAW_DATA.other_holdings || [])];
        let filteredNoSteamid = [...(RAW_DATA.no_steamid_holdings || [])];

        let displayTradesList = [];
        let displayHoldingsList = [];
        let displayOtherHoldingsList = [];
        let displayNoSteamidList = [];
        
        let tradesPage = 1;
        let holdingsPage = 1;
        let otherHoldingsPage = 1;
        let noSteamidPage = 1;
        const pageSize = 15;

        // 默认排序字段
        let sortField = 'sold_at';
        let sortDirection = -1; // -1: 降序, 1: 升序
        let holdingSortField = 'bought_at';
        let holdingSortDirection = -1;
        let otherHoldingsSortField = 'bought_at';
        let otherHoldingsSortDirection = -1;
        let noSteamidSortField = 'bought_at';
        let noSteamidSortDirection = -1;

        document.getElementById('generated-time').textContent = RAW_DATA.generated_at;

        // 分组辅助函数
        function groupTrades(tradesList) {
            const groups = {};
            tradesList.forEach(t => {
                const key = `${t.buy_source}|${t.game}|${t.name}|${t.buy_price.toFixed(2)}|${t.sell_price_cny.toFixed(2)}`;
                if (!groups[key]) {
                    groups[key] = {
                        buy_source: t.buy_source,
                        game: t.game,
                        name: t.name,
                        name_zh: t.name_zh,
                        buy_price: t.buy_price,
                        sell_price_cny: t.sell_price_cny,
                        sell_price_received_unit: t.sell_price_received,
                        sell_currency: t.sell_currency,
                        profit: 0,
                        hold_days_list: [],
                        bought_at_list: [],
                        sold_at_list: [],
                        count: 0
                    };
                }
                const g = groups[key];
                g.profit += t.profit;
                g.hold_days_list.push(t.hold_days);
                if (t.bought_at) g.bought_at_list.push(t.bought_at);
                if (t.sold_at) g.sold_at_list.push(t.sold_at);
                g.count++;
            });

            return Object.values(groups).map(g => {
                const avg_hold_days = g.hold_days_list.length > 0 ? Math.round(g.hold_days_list.reduce((a, b) => a + b, 0) / g.hold_days_list.length) : 0;
                
                let bought_range = '-';
                if (g.bought_at_list.length > 0) {
                    const bDates = g.bought_at_list.map(d => d.slice(0, 10)).sort();
                    bought_range = bDates[0] === bDates[bDates.length - 1] ? bDates[0] : `${bDates[0].slice(5)}~${bDates[bDates.length - 1].slice(5)}`;
                }

                let sold_range = '-';
                let latest_sold_at = '';
                if (g.sold_at_list.length > 0) {
                    const sDates = g.sold_at_list.map(d => d.slice(0, 10)).sort();
                    sold_range = sDates[0] === sDates[sDates.length - 1] ? sDates[0] : `${sDates[0].slice(5)}~${sDates[sDates.length - 1].slice(5)}`;
                    latest_sold_at = sDates[sDates.length - 1];
                }

                const total_buy = g.count * g.buy_price;
                const roi = total_buy > 0 ? (g.profit / total_buy) * 100 : 0;

                return {
                    buy_source: g.buy_source,
                    game: g.game,
                    name: g.name,
                    name_zh: g.name_zh,
                    buy_price: g.buy_price,
                    sell_price_cny: g.sell_price_cny,
                    sell_price_received: g.sell_price_received_unit,
                    sell_currency: g.sell_currency,
                    profit: g.profit,
                    roi: roi,
                    hold_days: avg_hold_days,
                    bought_range: bought_range,
                    sold_range: sold_range,
                    count: g.count,
                    sold_at: latest_sold_at,
                    bought_at: g.bought_at_list.length > 0 ? g.bought_at_list.sort()[0] : ''
                };
            });
        }

        function groupHoldings(holdingsList) {
            const groups = {};
            holdingsList.forEach(h => {
                const key = `${h.buy_source}|${h.game}|${h.name}|${h.buy_price.toFixed(2)}`;
                if (!groups[key]) {
                    groups[key] = {
                        buy_source: h.buy_source,
                        game: h.game,
                        name: h.name,
                        name_zh: h.name_zh,
                        buy_price: h.buy_price,
                        bought_at_list: [],
                        count: 0
                    };
                }
                const g = groups[key];
                if (h.bought_at) g.bought_at_list.push(h.bought_at);
                g.count++;
            });

            const now = new Date();
            return Object.values(groups).map(g => {
                let bought_range = '-';
                let hold_days_list = [];
                if (g.bought_at_list.length > 0) {
                    const bDates = g.bought_at_list.map(d => d.slice(0, 10)).sort();
                    bought_range = bDates[0] === bDates[bDates.length - 1] ? bDates[0] : `${bDates[0].slice(5)}~${bDates[bDates.length - 1].slice(5)}`;
                    
                    g.bought_at_list.forEach(bat => {
                        const buyDate = new Date(bat);
                        const holdDays = Math.max(0, Math.floor((now - buyDate) / (1000 * 60 * 60 * 24)));
                        hold_days_list.push(holdDays);
                    });
                }
                
                const avg_hold_days = hold_days_list.length > 0 ? Math.round(hold_days_list.reduce((a, b) => a + b, 0) / hold_days_list.length) : '-';
                const earliest_bought_at = g.bought_at_list.length > 0 ? g.bought_at_list.sort()[0] : '';

                return {
                    buy_source: g.buy_source,
                    game: g.game,
                    name: g.name,
                    name_zh: g.name_zh,
                    buy_price: g.buy_price,
                    bought_range: bought_range,
                    hold_days: avg_hold_days,
                    count: g.count,
                    bought_at: earliest_bought_at
                };
            });
        }

        function groupOtherHoldings(otherList) {
            const groups = {};
            otherList.forEach(o => {
                const key = `${o.buy_source}|${o.game}|${o.name}|${o.buy_price.toFixed(2)}|${o.buyer_steamid || ''}`;
                if (!groups[key]) {
                    groups[key] = {
                        buy_source: o.buy_source,
                        game: o.game,
                        name: o.name,
                        name_zh: o.name_zh,
                        buy_price: o.buy_price,
                        buyer_steamid: o.buyer_steamid,
                        bought_at_list: [],
                        count: 0
                    };
                }
                const g = groups[key];
                if (o.bought_at) g.bought_at_list.push(o.bought_at);
                g.count++;
            });

            return Object.values(groups).map(g => {
                let bought_range = '-';
                if (g.bought_at_list.length > 0) {
                    const bDates = g.bought_at_list.map(d => d.slice(0, 10)).sort();
                    bought_range = bDates[0] === bDates[bDates.length - 1] ? bDates[0] : `${bDates[0].slice(5)}~${bDates[bDates.length - 1].slice(5)}`;
                }
                const earliest_bought_at = g.bought_at_list.length > 0 ? g.bought_at_list.sort()[0] : '';

                return {
                    buy_source: g.buy_source,
                    game: g.game,
                    name: g.name,
                    name_zh: g.name_zh,
                    buy_price: g.buy_price,
                    buyer_steamid: g.buyer_steamid,
                    bought_range: bought_range,
                    count: g.count,
                    bought_at: earliest_bought_at
                };
            });
        }

        function groupNoSteamid(noSteamidList) {
            const groups = {};
            noSteamidList.forEach(o => {
                const key = `${o.buy_source}|${o.game}|${o.name}|${o.buy_price.toFixed(2)}`;
                if (!groups[key]) {
                    groups[key] = {
                        buy_source: o.buy_source,
                        game: o.game,
                        name: o.name,
                        name_zh: o.name_zh,
                        buy_price: o.buy_price,
                        bought_at_list: [],
                        count: 0
                    };
                }
                const g = groups[key];
                if (o.bought_at) g.bought_at_list.push(o.bought_at);
                g.count++;
            });

            return Object.values(groups).map(g => {
                let bought_range = '-';
                if (g.bought_at_list.length > 0) {
                    const bDates = g.bought_at_list.map(d => d.slice(0, 10)).sort();
                    bought_range = bDates[0] === bDates[bDates.length - 1] ? bDates[0] : `${bDates[0].slice(5)}~${bDates[bDates.length - 1].slice(5)}`;
                }
                const earliest_bought_at = g.bought_at_list.length > 0 ? g.bought_at_list.sort()[0] : '';

                return {
                    buy_source: g.buy_source,
                    game: g.game,
                    name: g.name,
                    name_zh: g.name_zh,
                    buy_price: g.buy_price,
                    bought_range: bought_range,
                    count: g.count,
                    bought_at: earliest_bought_at
                };
            });
        }

        // 载入页面数据
        function initDashboard() {
            renderSummaryCards();
            renderCharts();
            renderDataCoverage();
            switchTab(currentTab);
        }

        function renderDataCoverage() {
            const counts = {
                trades: RAW_DATA.trades.length,
                holdings: RAW_DATA.holdings.length,
                other: (RAW_DATA.other_holdings || []).length,
                missing: (RAW_DATA.no_steamid_holdings || []).length,
            };
            const totalBuys = counts.trades + counts.holdings + counts.other + counts.missing;
            document.getElementById('tab-count-trades').textContent = `(${counts.trades})`;
            document.getElementById('tab-count-holdings').textContent = `(${counts.holdings})`;
            document.getElementById('tab-count-other').textContent = `(${counts.other})`;
            document.getElementById('tab-count-missing').textContent = `(${counts.missing})`;
            document.getElementById('data-coverage-note').textContent =
                `已载入 ${totalBuys} 条买入明细：当前账号 ${counts.holdings + counts.trades} 条，` +
                `其他账号 ${counts.other} 条，缺失 SteamID ${counts.missing} 条。` +
                `表格按饰品、平台和价格合并，每页显示 ${pageSize} 组，可使用下方分页查看全部。`;
            if (counts.trades === 0) {
                document.getElementById('empty-trades-notice').classList.remove('hidden');
            }
        }

        // 渲染统计卡片
        function renderSummaryCards() {
            const sum = RAW_DATA.summary;
            document.getElementById('stat-total-profit').textContent = `¥${sum.total_profit.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
            document.getElementById('stat-total-trades').textContent = sum.total_trades;
            document.getElementById('stat-avg-roi').textContent = `${sum.avg_roi.toFixed(2)}%`;
            document.getElementById('stat-avg-hold').textContent = sum.avg_hold_days.toFixed(1);
            document.getElementById('stat-total-invested').textContent = `¥${sum.total_invested.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
            document.getElementById('stat-total-received').textContent = `¥${sum.total_received.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
            document.getElementById('stat-holding-count').textContent = sum.holding_count;
            document.getElementById('stat-holding-invested').textContent = `¥${sum.holding_invested.toLocaleString(undefined, {minimumFractionDigits: 2})}`;

            // 资金条进度比
            const totalOut = sum.total_invested + sum.total_profit;
            const progress = totalOut > 0 ? (sum.total_invested / totalOut) * 100 : 50;
            document.getElementById('stat-cashflow-progress').style.width = `${progress}%`;
        }

        // 切换 Tab 页
        function switchTab(tab) {
            currentTab = tab;
            const btnTrades = document.getElementById('tab-btn-trades');
            const btnHoldings = document.getElementById('tab-btn-holdings');
            const btnOtherHoldings = document.getElementById('tab-btn-other-holdings');
            const btnNoSteamid = document.getElementById('tab-btn-no-steamid');
            const filterProfit = document.getElementById('filter-profit');

            // Reset classNames to unselected styling
            btnTrades.className = 'px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 text-slate-400 hover:text-slate-200';
            btnHoldings.className = 'px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 text-slate-400 hover:text-slate-200';
            btnOtherHoldings.className = 'px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 text-slate-400 hover:text-slate-200';
            btnNoSteamid.className = 'px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 text-slate-400 hover:text-slate-200';

            if (tab === 'trades') {
                btnTrades.className = 'px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 bg-slate-800 text-white shadow';
                filterProfit.style.display = 'inline-block';
            } else if (tab === 'holdings') {
                btnHoldings.className = 'px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 bg-slate-800 text-white shadow';
                filterProfit.style.display = 'none';
            } else if (tab === 'other-holdings') {
                btnOtherHoldings.className = 'px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 bg-slate-800 text-white shadow';
                filterProfit.style.display = 'none';
            } else {
                btnNoSteamid.className = 'px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 bg-slate-800 text-white shadow';
                filterProfit.style.display = 'none';
            }
            handleFilter();
        }

        // 检索与筛选数据
        function handleFilter() {
            const query = document.getElementById('search-input').value.toLowerCase().trim();
            const game = document.getElementById('filter-game').value;
            const profitState = document.getElementById('filter-profit').value;

            if (currentTab === 'trades') {
                filteredTrades = RAW_DATA.trades.filter(t => {
                    const matchQuery = t.name.toLowerCase().includes(query) || 
                                       (t.name_zh && t.name_zh.toLowerCase().includes(query)) || 
                                       t.buff_no.includes(query) || 
                                       t.steam_id.includes(query);
                    const matchGame = game === 'all' || t.game === game;
                    const matchProfit = profitState === 'all' || 
                                       (profitState === 'gain' && t.profit > 0) || 
                                       (profitState === 'loss' && t.profit <= 0);
                    return matchQuery && matchGame && matchProfit;
                });
                tradesPage = 1;
                sortAndRenderTable();
            } else if (currentTab === 'holdings') {
                filteredHoldings = RAW_DATA.holdings.filter(h => {
                    const matchQuery = h.name.toLowerCase().includes(query) || 
                                       (h.name_zh && h.name_zh.toLowerCase().includes(query)) || 
                                       h.buff_no.includes(query);
                    const matchGame = game === 'all' || h.game === game;
                    return matchQuery && matchGame;
                });
                holdingsPage = 1;
                sortAndRenderTable();
            } else if (currentTab === 'other-holdings') {
                filteredOtherHoldings = (RAW_DATA.other_holdings || []).filter(o => {
                    const matchQuery = o.name.toLowerCase().includes(query) || 
                                       (o.name_zh && o.name_zh.toLowerCase().includes(query)) || 
                                       o.buff_no.includes(query) ||
                                       (o.buyer_steamid && o.buyer_steamid.toLowerCase().includes(query));
                    const matchGame = game === 'all' || o.game === game;
                    return matchQuery && matchGame;
                });
                otherHoldingsPage = 1;
                sortAndRenderTable();
            } else {
                filteredNoSteamid = (RAW_DATA.no_steamid_holdings || []).filter(o => {
                    const matchQuery = o.name.toLowerCase().includes(query) || 
                                       (o.name_zh && o.name_zh.toLowerCase().includes(query)) || 
                                       o.buff_no.includes(query);
                    const matchGame = game === 'all' || o.game === game;
                    return matchQuery && matchGame;
                });
                noSteamidPage = 1;
                sortAndRenderTable();
            }
        }

        // 重置过滤器
        function resetFilters() {
            document.getElementById('search-input').value = '';
            document.getElementById('filter-game').value = 'all';
            document.getElementById('filter-profit').value = 'all';
            handleFilter();
        }

        // 排序与渲染数据表格
        function sortAndRenderTable() {
            if (currentTab === 'trades') {
                displayTradesList = groupTrades(filteredTrades);
                displayTradesList.sort((a, b) => {
                    let va = a[sortField];
                    let vb = b[sortField];
                    if (va === null || va === undefined) return 1;
                    if (vb === null || vb === undefined) return -1;
                    if (typeof va === 'string') {
                        return va.localeCompare(vb) * sortDirection;
                    }
                    return (va - vb) * sortDirection;
                });
                renderTradesTable();
            } else if (currentTab === 'holdings') {
                displayHoldingsList = groupHoldings(filteredHoldings);
                displayHoldingsList.sort((a, b) => {
                    let va = a[holdingSortField];
                    let vb = b[holdingSortField];
                    if (va === null || va === undefined) return 1;
                    if (vb === null || vb === undefined) return -1;
                    if (typeof va === 'string') {
                        return va.localeCompare(vb) * holdingSortDirection;
                    }
                    return (va - vb) * holdingSortDirection;
                });
                renderHoldingsTable();
            } else if (currentTab === 'other-holdings') {
                displayOtherHoldingsList = groupOtherHoldings(filteredOtherHoldings);
                displayOtherHoldingsList.sort((a, b) => {
                    let va = a[otherHoldingsSortField];
                    let vb = b[otherHoldingsSortField];
                    if (va === null || va === undefined) return 1;
                    if (vb === null || vb === undefined) return -1;
                    if (typeof va === 'string') {
                        return va.localeCompare(vb) * otherHoldingsSortDirection;
                    }
                    return (va - vb) * otherHoldingsSortDirection;
                });
                renderOtherHoldingsTable();
            } else {
                displayNoSteamidList = groupNoSteamid(filteredNoSteamid);
                displayNoSteamidList.sort((a, b) => {
                    let va = a[noSteamidSortField];
                    let vb = b[noSteamidSortField];
                    if (va === null || va === undefined) return 1;
                    if (vb === null || vb === undefined) return -1;
                    if (typeof va === 'string') {
                        return va.localeCompare(vb) * noSteamidSortDirection;
                    }
                    return (va - vb) * noSteamidSortDirection;
                });
                renderNoSteamidTable();
            }
        }

        // 触发排序
        function triggerSort(field) {
            if (currentTab === 'trades') {
                if (sortField === field) {
                    sortDirection *= -1; // 倒序
                } else {
                    sortField = field;
                    sortDirection = -1; // 默认大值/近时间在先
                }
            } else if (currentTab === 'holdings') {
                if (holdingSortField === field) {
                    holdingSortDirection *= -1;
                } else {
                    holdingSortField = field;
                    holdingSortDirection = -1;
                }
            } else if (currentTab === 'other-holdings') {
                if (otherHoldingsSortField === field) {
                    otherHoldingsSortDirection *= -1;
                } else {
                    otherHoldingsSortField = field;
                    otherHoldingsSortDirection = -1;
                }
            } else {
                if (noSteamidSortField === field) {
                    noSteamidSortDirection *= -1;
                } else {
                    noSteamidSortField = field;
                    noSteamidSortDirection = -1;
                }
            }
            sortAndRenderTable();
        }

        // 辅助获取排序小图标
        function getSortArrow(field) {
            let activeField, dir;
            if (currentTab === 'trades') {
                activeField = sortField;
                dir = sortDirection;
            } else if (currentTab === 'holdings') {
                activeField = holdingSortField;
                dir = holdingSortDirection;
            } else if (currentTab === 'other-holdings') {
                activeField = otherHoldingsSortField;
                dir = otherHoldingsSortDirection;
            } else {
                activeField = noSteamidSortField;
                dir = noSteamidSortDirection;
            }
            if (activeField !== field) return '<span class="text-slate-600 ml-1">⇅</span>';
            return dir === 1 ? '<span class="text-indigo-400 ml-1">▲</span>' : '<span class="text-indigo-400 ml-1">▼</span>';
        }

        // 渲染已完成交易表
        function renderTradesTable() {
            const tableHeaders = document.getElementById('table-headers');
            tableHeaders.innerHTML = `
                <th class="py-3.5 px-4 cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('game')">游戏 ${getSortArrow('game')}</th>
                <th class="py-3.5 px-4">买入平台</th>
                <th class="py-3.5 px-4 cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('name')">饰品名称 ${getSortArrow('name')}</th>
                <th class="py-3.5 px-4 text-right cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('buy_price')">买入单价 ${getSortArrow('buy_price')}</th>
                <th class="py-3.5 px-4 text-right cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('sell_price_cny')">到手单价 ${getSortArrow('sell_price_cny')}</th>
                <th class="py-3.5 px-4 text-right cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('profit')">总净利润 ${getSortArrow('profit')}</th>
                <th class="py-3.5 px-4 text-right cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('roi')">ROI ${getSortArrow('roi')}</th>
                <th class="py-3.5 px-4 text-center cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('hold_days')">平均持仓 ${getSortArrow('hold_days')}</th>
                <th class="py-3.5 px-4 text-center cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('sold_at')">交易日期范围 ${getSortArrow('sold_at')}</th>
            `;

            const tbody = document.getElementById('table-body');
            tbody.innerHTML = '';

            const rawTotal = filteredTrades.length;
            const total = displayTradesList.length;
            document.getElementById('total-count-display').textContent = `${rawTotal} 条明细 (${total} 组)`;

            if (total === 0) {
                tbody.innerHTML = `<tr><td colspan="9" class="text-center py-12 text-slate-500">无已完成交易数据</td></tr>`;
                updatePagination(0, 0);
                return;
            }

            const totalPages = Math.ceil(total / pageSize);
            if (tradesPage > totalPages) tradesPage = totalPages || 1;

            const startIdx = (tradesPage - 1) * pageSize;
            const endIdx = Math.min(startIdx + pageSize, total);

            const displayData = displayTradesList.slice(startIdx, endIdx);
            
            displayData.forEach(t => {
                const profitClass = t.profit > 0 ? 'text-emerald-400 font-semibold' : (t.profit < 0 ? 'text-red-400 font-semibold' : 'text-slate-400');
                const profitSign = t.profit > 0 ? '+' : '';
                const gameBadge = t.game === 'csgo' ? 'bg-orange-500/10 text-orange-400 border border-orange-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20';
                const gameName = t.game === 'csgo' ? 'CS2' : 'DOTA2';
                
                const countBadge = t.count > 1 ? `<span class="ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">x${t.count}</span>` : '';
                const singleProfit = t.profit / t.count;
                const singleProfitStr = t.count > 1 ? `<div class="text-[10px] text-slate-500">单件: ¥${singleProfit.toFixed(2)}</div>` : '';

                const tr = document.createElement('tr');
                tr.className = 'hover:bg-slate-900/35 border-b border-slate-800/40 transition-colors';
                tr.innerHTML = `
                    <td class="py-3 px-4">
                        <span class="text-xs px-2 py-0.5 rounded-full font-medium ${gameBadge}">${gameName}</span>
                    </td>
                    <td class="py-3 px-4 text-xs font-semibold text-indigo-300">${(t.buy_source || 'buff').toUpperCase()}</td>
                    <td class="py-3 px-4 max-w-[280px] truncate">
                        <div class="flex items-center font-medium text-slate-200">
                            <span class="truncate">${t.name_zh || t.name}</span>
                            ${countBadge}
                        </div>
                        <div class="text-[11px] text-slate-500 font-display truncate">${t.name}</div>
                    </td>
                    <td class="py-3 px-4 text-right font-display font-medium text-slate-300">¥${t.buy_price.toFixed(2)}</td>
                    <td class="py-3 px-4 text-right font-display font-medium text-slate-300">
                        <div>¥${t.sell_price_cny.toFixed(2)}</div>
                        <div class="text-[10px] text-slate-500">${t.sell_price_received.toFixed(2)} ${t.sell_currency}</div>
                    </td>
                    <td class="py-3 px-4 text-right font-display ${profitClass}">
                        <div>${profitSign}¥${t.profit.toFixed(2)}</div>
                        ${singleProfitStr}
                    </td>
                    <td class="py-3 px-4 text-right font-display ${profitClass}">${profitSign}${t.roi.toFixed(1)}%</td>
                    <td class="py-3 px-4 text-center font-display">${t.hold_days}天</td>
                    <td class="py-3 px-4 text-center text-xs">
                        <div class="text-slate-300 font-display">${t.sold_range}</div>
                        <div class="text-slate-500 text-[10px] font-display">买: ${t.bought_range}</div>
                    </td>
                `;
                tbody.appendChild(tr);
            });

            updatePagination(total, totalPages, tradesPage, startIdx + 1, endIdx);
        }

        // 渲染当前持仓表
        function renderHoldingsTable() {
            const tableHeaders = document.getElementById('table-headers');
            tableHeaders.innerHTML = `
                <th class="py-3.5 px-4 cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('game')">游戏 ${getSortArrow('game')}</th>
                <th class="py-3.5 px-4">买入平台</th>
                <th class="py-3.5 px-4 cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('name')">饰品名称 ${getSortArrow('name')}</th>
                <th class="py-3.5 px-4 text-right cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('buy_price')">买入单价 ${getSortArrow('buy_price')}</th>
                <th class="py-3.5 px-4 text-center cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('bought_at')">买入日期范围 ${getSortArrow('bought_at')}</th>
                <th class="py-3.5 px-4 text-center">平均持有天数</th>
            `;

            const tbody = document.getElementById('table-body');
            tbody.innerHTML = '';

            const rawTotal = filteredHoldings.length;
            const total = displayHoldingsList.length;
            document.getElementById('total-count-display').textContent = `${rawTotal} 条明细 (${total} 组)`;

            if (total === 0) {
                tbody.innerHTML = `<tr><td colspan="6" class="text-center py-12 text-slate-500">当前没有持仓物品</td></tr>`;
                updatePagination(0, 0);
                return;
            }

            const totalPages = Math.ceil(total / pageSize);
            if (holdingsPage > totalPages) holdingsPage = totalPages || 1;

            const startIdx = (holdingsPage - 1) * pageSize;
            const endIdx = Math.min(startIdx + pageSize, total);

            const displayData = displayHoldingsList.slice(startIdx, endIdx);

            displayData.forEach(h => {
                const gameBadge = h.game === 'csgo' ? 'bg-orange-500/10 text-orange-400 border border-orange-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20';
                const gameName = h.game === 'csgo' ? 'CS2' : 'DOTA2';
                
                const countBadge = h.count > 1 ? `<span class="ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-semibold bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">x${h.count}</span>` : '';
                const totalCost = h.count * h.buy_price;
                const totalCostStr = h.count > 1 ? `<div class="text-[10px] text-slate-500">总成本: ¥${totalCost.toFixed(2)}</div>` : '';

                const tr = document.createElement('tr');
                tr.className = 'hover:bg-slate-900/35 border-b border-slate-800/40 transition-colors';
                tr.innerHTML = `
                    <td class="py-3.5 px-4">
                        <span class="text-xs px-2 py-0.5 rounded-full font-medium ${gameBadge}">${gameName}</span>
                    </td>
                    <td class="py-3.5 px-4 text-xs font-semibold text-indigo-300">${(h.buy_source || 'buff').toUpperCase()}</td>
                    <td class="py-3.5 px-4">
                        <div class="flex items-center font-medium text-slate-200">
                            <span class="truncate">${h.name_zh || h.name}</span>
                            ${countBadge}
                        </div>
                        <div class="text-[11px] text-slate-500 font-display truncate">${h.name}</div>
                    </td>
                    <td class="py-3.5 px-4 text-right font-display font-medium text-slate-300">
                        <div>¥${h.buy_price.toFixed(2)}</div>
                        ${totalCostStr}
                    </td>
                    <td class="py-3.5 px-4 text-center text-xs font-display text-slate-400">${h.bought_range}</td>
                    <td class="py-3.5 px-4 text-center font-display text-yellow-400/90 font-medium">${h.hold_days}天</td>
                `;
                tbody.appendChild(tr);
            });

            updatePagination(total, totalPages, holdingsPage, startIdx + 1, endIdx);
        }

        // 渲染其他账号买单表
        function renderOtherHoldingsTable() {
            const tableHeaders = document.getElementById('table-headers');
            tableHeaders.innerHTML = `
                <th class="py-3.5 px-4 cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('game')">游戏 ${getSortArrow('game')}</th>
                <th class="py-3.5 px-4">买入平台</th>
                <th class="py-3.5 px-4 cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('name')">饰品名称 ${getSortArrow('name')}</th>
                <th class="py-3.5 px-4 text-right cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('buy_price')">买入单价 ${getSortArrow('buy_price')}</th>
                <th class="py-3.5 px-4 text-center cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('bought_at')">买入日期范围 ${getSortArrow('bought_at')}</th>
                <th class="py-3.5 px-4 text-center">买入SteamID</th>
            `;

            const tbody = document.getElementById('table-body');
            tbody.innerHTML = '';

            const rawTotal = filteredOtherHoldings.length;
            const total = displayOtherHoldingsList.length;
            document.getElementById('total-count-display').textContent = `${rawTotal} 条明细 (${total} 组)`;

            if (total === 0) {
                tbody.innerHTML = `<tr><td colspan="6" class="text-center py-12 text-slate-500">没有其他账号的买单数据</td></tr>`;
                updatePagination(0, 0);
                return;
            }

            const totalPages = Math.ceil(total / pageSize);
            if (otherHoldingsPage > totalPages) otherHoldingsPage = totalPages || 1;

            const startIdx = (otherHoldingsPage - 1) * pageSize;
            const endIdx = Math.min(startIdx + pageSize, total);

            const displayData = displayOtherHoldingsList.slice(startIdx, endIdx);

            displayData.forEach(h => {
                const gameBadge = h.game === 'csgo' ? 'bg-orange-500/10 text-orange-400 border border-orange-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20';
                const gameName = h.game === 'csgo' ? 'CS2' : 'DOTA2';

                const countBadge = h.count > 1 ? `<span class="ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-semibold bg-purple-500/20 text-purple-300 border border-purple-500/30">x${h.count}</span>` : '';
                const totalCost = h.count * h.buy_price;
                const totalCostStr = h.count > 1 ? `<div class="text-[10px] text-slate-500">总成本: ¥${totalCost.toFixed(2)}</div>` : '';

                const tr = document.createElement('tr');
                tr.className = 'hover:bg-slate-900/35 border-b border-slate-800/40 transition-colors';
                tr.innerHTML = `
                    <td class="py-3.5 px-4">
                        <span class="text-xs px-2 py-0.5 rounded-full font-medium ${gameBadge}">${gameName}</span>
                    </td>
                    <td class="py-3.5 px-4 text-xs font-semibold text-indigo-300">${(h.buy_source || 'buff').toUpperCase()}</td>
                    <td class="py-3.5 px-4">
                        <div class="flex items-center font-medium text-slate-200">
                            <span class="truncate">${h.name_zh || h.name}</span>
                            ${countBadge}
                        </div>
                        <div class="text-[11px] text-slate-500 font-display truncate">${h.name}</div>
                    </td>
                    <td class="py-3.5 px-4 text-right font-display font-medium text-slate-300">
                        <div>¥${h.buy_price.toFixed(2)}</div>
                        ${totalCostStr}
                    </td>
                    <td class="py-3.5 px-4 text-center text-xs font-display text-slate-400">${h.bought_range}</td>
                    <td class="py-3.5 px-4 text-center text-xs font-display text-slate-400">${h.buyer_steamid || '-'}</td>
                `;
                tbody.appendChild(tr);
            });

            updatePagination(total, totalPages, otherHoldingsPage, startIdx + 1, endIdx);
        }

        // 渲染缺失SteamID交易表
        function renderNoSteamidTable() {
            const tableHeaders = document.getElementById('table-headers');
            tableHeaders.innerHTML = `
                <th class="py-3.5 px-4 cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('game')">游戏 ${getSortArrow('game')}</th>
                <th class="py-3.5 px-4">买入平台</th>
                <th class="py-3.5 px-4 cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('name')">饰品名称 ${getSortArrow('name')}</th>
                <th class="py-3.5 px-4 text-right cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('buy_price')">买入单价 ${getSortArrow('buy_price')}</th>
                <th class="py-3.5 px-4 text-center cursor-pointer hover:bg-slate-900 transition-colors" onclick="triggerSort('bought_at')">买入日期范围 ${getSortArrow('bought_at')}</th>
            `;

            const tbody = document.getElementById('table-body');
            tbody.innerHTML = '';

            const rawTotal = filteredNoSteamid.length;
            const total = displayNoSteamidList.length;
            document.getElementById('total-count-display').textContent = `${rawTotal} 条明细 (${total} 组)`;

            if (total === 0) {
                tbody.innerHTML = `<tr><td colspan="5" class="text-center py-12 text-slate-500">没有缺失SteamID的买单数据</td></tr>`;
                updatePagination(0, 0);
                return;
            }

            const totalPages = Math.ceil(total / pageSize);
            if (noSteamidPage > totalPages) noSteamidPage = totalPages || 1;

            const startIdx = (noSteamidPage - 1) * pageSize;
            const endIdx = Math.min(startIdx + pageSize, total);

            const displayData = displayNoSteamidList.slice(startIdx, endIdx);

            displayData.forEach(h => {
                const gameBadge = h.game === 'csgo' ? 'bg-orange-500/10 text-orange-400 border border-orange-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20';
                const gameName = h.game === 'csgo' ? 'CS2' : 'DOTA2';

                const countBadge = h.count > 1 ? `<span class="ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-semibold bg-gray-500/20 text-gray-300 border border-gray-500/30">x${h.count}</span>` : '';
                const totalCost = h.count * h.buy_price;
                const totalCostStr = h.count > 1 ? `<div class="text-[10px] text-slate-500">总成本: ¥${totalCost.toFixed(2)}</div>` : '';

                const tr = document.createElement('tr');
                tr.className = 'hover:bg-slate-900/35 border-b border-slate-800/40 transition-colors';
                tr.innerHTML = `
                    <td class="py-3.5 px-4">
                        <span class="text-xs px-2 py-0.5 rounded-full font-medium ${gameBadge}">${gameName}</span>
                    </td>
                    <td class="py-3.5 px-4 text-xs font-semibold text-indigo-300">${(h.buy_source || 'buff').toUpperCase()}</td>
                    <td class="py-3.5 px-4">
                        <div class="flex items-center font-medium text-slate-200">
                            <span class="truncate">${h.name_zh || h.name}</span>
                            ${countBadge}
                        </div>
                        <div class="text-[11px] text-slate-500 font-display truncate">${h.name}</div>
                    </td>
                    <td class="py-3.5 px-4 text-right font-display font-medium text-slate-300">
                        <div>¥${h.buy_price.toFixed(2)}</div>
                        ${totalCostStr}
                    </td>
                    <td class="py-3.5 px-4 text-center text-xs font-display text-slate-400">${h.bought_range}</td>
                `;
                tbody.appendChild(tr);
            });

            updatePagination(total, totalPages, noSteamidPage, startIdx + 1, endIdx);
        }

        // 分页更新
        function updatePagination(total, totalPages, currentPage, startRange, endRange) {
            if (total === 0) {
                document.getElementById('page-range-display').textContent = '0 - 0';
                document.getElementById('current-page-display').textContent = '1 / 1';
                document.getElementById('prev-page-btn').disabled = true;
                document.getElementById('next-page-btn').disabled = true;
                return;
            }

            document.getElementById('page-range-display').textContent = `${startRange} - ${endRange}`;
            document.getElementById('current-page-display').textContent = `${currentPage} / ${totalPages}`;
            document.getElementById('prev-page-btn').disabled = currentPage === 1;
            document.getElementById('next-page-btn').disabled = currentPage === totalPages;
        }

        // 点击翻页
        function changePage(direction) {
            if (currentTab === 'trades') {
                tradesPage += direction;
                renderTradesTable();
            } else if (currentTab === 'holdings') {
                holdingsPage += direction;
                renderHoldingsTable();
            } else if (currentTab === 'other-holdings') {
                otherHoldingsPage += direction;
                renderOtherHoldingsTable();
            } else {
                noSteamidPage += direction;
                renderNoSteamidTable();
            }
        }

        // 渲染图表
        function renderCharts() {
            // ---------------------------------
            // 1. 累计收益趋势线图
            // ---------------------------------
            const sortedTrades = [...RAW_DATA.trades].sort((a, b) => a.sold_at.localeCompare(b.sold_at));
            
            // 按日期累加收益
            const profitByDate = {};
            sortedTrades.forEach(t => {
                const date = t.sold_at.slice(0, 10);
                profitByDate[date] = (profitByDate[date] || 0) + t.profit;
            });

            const dates = Object.keys(profitByDate).sort();
            let rollingSum = 0;
            const trendData = dates.map(d => {
                rollingSum += profitByDate[d];
                return rollingSum;
            });

            const ctxTrend = document.getElementById('trend-chart').getContext('2d');
            new Chart(ctxTrend, {
                type: 'line',
                data: {
                    labels: dates,
                    datasets: [{
                        label: '累计净利润 (CNY)',
                        data: trendData,
                        borderColor: '#10b981',
                        borderWidth: 2.5,
                        backgroundColor: 'rgba(16, 185, 129, 0.08)',
                        fill: true,
                        tension: 0.35,
                        pointRadius: Math.min(6, Math.max(1.5, 120 / dates.length)),
                        pointHoverRadius: 6,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15, 23, 42, 0.9)',
                            titleColor: '#94a3b8',
                            bodyColor: '#34d399',
                            borderColor: 'rgba(255, 255, 255, 0.08)',
                            borderWidth: 1,
                            padding: 10,
                            displayColors: false,
                            callbacks: {
                                label: function(context) {
                                    return `累计净利润: ¥${context.raw.toFixed(2)}`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(255, 255, 255, 0.03)' },
                            ticks: { color: '#64748b', maxTicksLimit: 8, font: { family: 'Outfit' } }
                        },
                        y: {
                            grid: { color: 'rgba(255, 255, 255, 0.04)' },
                            ticks: { color: '#64748b', font: { family: 'Outfit' } }
                        }
                    }
                }
            });

            // ---------------------------------
            // 2. 游戏品类占比饼图
            // ---------------------------------
            const gameBreakdowns = RAW_DATA.summary.by_game;
            const games = Object.keys(gameBreakdowns);
            const profits = games.map(g => gameBreakdowns[g].profit_cny);
            
            // 界面中更新具体数值
            if (gameBreakdowns.csgo) {
                document.getElementById('game-cs2-profit').textContent = `¥${gameBreakdowns.csgo.profit_cny.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
            }
            if (gameBreakdowns.dota2) {
                document.getElementById('game-dota2-profit').textContent = `¥${gameBreakdowns.dota2.profit_cny.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
            }

            const ctxGame = document.getElementById('game-chart').getContext('2d');
            new Chart(ctxGame, {
                type: 'doughnut',
                data: {
                    labels: games.map(g => g === 'csgo' ? 'CS2' : 'DOTA2'),
                    datasets: [{
                        data: profits,
                        backgroundColor: ['#3b82f6', '#34d399'],
                        borderColor: '#0f172a',
                        borderWidth: 3,
                        hoverOffset: 12
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '72%',
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            backgroundColor: 'rgba(15, 23, 42, 0.9)',
                            padding: 10,
                            borderColor: 'rgba(255, 255, 255, 0.08)',
                            borderWidth: 1,
                            callbacks: {
                                label: function(context) {
                                    const val = context.raw;
                                    const sum = profits.reduce((a, b) => a + b, 0);
                                    const pct = sum > 0 ? ((val / sum) * 100).toFixed(1) : 0;
                                    return `利润: ¥${val.toFixed(2)} (${pct}%)`;
                                }
                            }
                        }
                    }
                }
            });
        }

        // 页面入口初始化
        window.addEventListener('load', initDashboard);
    </script>
</body>
</html>
"""

def generate_html_report(trades: list, unmatched_buys: list, summary, output_path: Path, unmatched_other_buys: list = None, unmatched_no_steamid_buys: list = None) -> Path:
    """
    序列化统计数据，将其嵌入 HTML 模板，并保存文件。
    """
    trades_list = []
    for t in trades:
        trades_list.append({
            "buy_source": t.buy_source,
            "game": t.game,
            "name": t.name,
            "name_zh": t.name_zh,
            "buy_price": t.buy_price_cny,
            "bought_at": t.bought_at,
            "sell_price_received": t.sell_price_received,
            "sell_currency": t.sell_currency,
            "sell_price_cny": t.sell_price_cny,
            "sold_at": t.sold_at,
            "hold_days": t.hold_days,
            "profit": t.profit_cny,
            "roi": t.roi_pct,
            "buy_no": t.buy_order_no,
            "buff_no": t.buy_order_no,
            "steam_id": t.steam_row_id,
        })

    holdings_list = []
    for b in unmatched_buys:
        holdings_list.append({
            "buy_source": b.buy_source,
            "game": b.game,
            "name": b.name,
            "name_zh": b.name_zh,
            "buy_price": b.buy_price_cny,
            "bought_at": b.bought_at,
            "buy_no": b.buy_order_no,
            "buff_no": b.buy_order_no,
        })

    other_holdings_list = []
    if unmatched_other_buys:
        for b in unmatched_other_buys:
            other_holdings_list.append({
                "buy_source": b.buy_source,
                "game": b.game,
                "name": b.name,
                "name_zh": b.name_zh,
                "buy_price": b.buy_price_cny,
                "bought_at": b.bought_at,
                "buy_no": b.buy_order_no,
                "buff_no": b.buy_order_no,
                "buyer_steamid": b.buyer_steamid,
            })

    no_steamid_holdings_list = []
    if unmatched_no_steamid_buys:
        for b in unmatched_no_steamid_buys:
            no_steamid_holdings_list.append({
                "buy_source": b.buy_source,
                "game": b.game,
                "name": b.name,
                "name_zh": b.name_zh,
                "buy_price": b.buy_price_cny,
                "bought_at": b.bought_at,
                "buy_no": b.buy_order_no,
                "buff_no": b.buy_order_no,
            })

    best_trade = None
    if summary.best_trade:
        best_trade = {
            "name": summary.best_trade.name_zh or summary.best_trade.name,
            "profit": summary.best_trade.profit_cny,
            "roi": summary.best_trade.roi_pct
        }

    worst_trade = None
    if summary.worst_trade:
        worst_trade = {
            "name": summary.worst_trade.name_zh or summary.worst_trade.name,
            "profit": summary.worst_trade.profit_cny,
            "roi": summary.worst_trade.roi_pct
        }

    summary_dict = {
        "total_trades": summary.total_trades,
        "total_invested": summary.total_invested_cny,
        "total_received": summary.total_received_cny,
        "total_profit": summary.total_profit_cny,
        "avg_roi": summary.avg_roi_pct,
        "avg_hold_days": summary.avg_hold_days,
        "holding_count": summary.holding_count,
        "holding_invested": summary.holding_invested_cny,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "by_game": summary.by_game,
    }

    raw_data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trades": trades_list,
        "holdings": holdings_list,
        "other_holdings": other_holdings_list,
        "no_steamid_holdings": no_steamid_holdings_list,
        "summary": summary_dict,
    }

    serialized_data = json.dumps(raw_data, ensure_ascii=False, indent=2)
    html_content = HTML_TEMPLATE.replace("DATA_PLACEHOLDER", serialized_data)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return output_path
