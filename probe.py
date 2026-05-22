# -*- coding: utf-8 -*-
"""
探查 BUFF 账单接口和 Steam 原始数据格式
"""
import io, json, os, sys
from pathlib import Path
import requests
import yaml

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with open("config.yaml", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

buff_sess = requests.Session()
buff_sess.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Cookie": cfg["buff"]["cookie"]
})

print("=== 探查 BUFF 账单 API ===")
# 尝试更多 BUFF 账单接口
endpoints = [
    "/api/market/buy_order/history",
    "/api/market/buy_order/history?game=csgo&page_num=1",
    "/api/market/history/buy",
    "/api/market/bill_order/buy",
    "/api/market/buy_order",
    "/api/market/bill_order",
]

for ep in endpoints:
    url = f"https://buff.163.com{ep}"
    try:
        r = buff_sess.get(url, timeout=5)
        print(f"URL: {url} -> Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"  Response key: {list(data.keys())}")
            if data.get("code") == "OK":
                print(f"  [OK] 成功匹配到接口！")
                print(f"  示例数据: {json.dumps(data, ensure_ascii=False)[:300]}")
    except Exception as e:
        print(f"URL: {url} -> 异常: {e}")

# --- 探查 Steam 历史格式 ---
print("\n=== 探查 Steam 历史数据 ===")
steam_sess = requests.Session()
steam_sess.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Cookie": f"sessionid={cfg['steam']['session_id']}; steamLoginSecure={cfg['steam']['steam_login_secure']}"
})

# 不带 norender=1 的请求
url_render = "https://steamcommunity.com/market/myhistory/render/?query=&start=0&count=10"
try:
    r = steam_sess.get(url_render, timeout=10)
    print(f"Render API status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"Render Keys: {list(data.keys())}")
        print(f"Total count: {data.get('total_count')}")
        results_html = data.get("results_html", "")
        print(f"results_html length: {len(results_html)}")
        if results_html:
            print(f"HTML 样例 (前 500 字): {results_html[:500]}")
except Exception as e:
    print(f"Steam Render 错误: {e}")

# 带 norender=1 的请求，看看返回什么
url_norender = "https://steamcommunity.com/market/myhistory/render/?query=&start=0&count=10&norender=1"
try:
    r = steam_sess.get(url_norender, timeout=10)
    print(f"\nNorender API status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"Norender Keys: {list(data.keys())}")
        print(f"Total count: {data.get('total_count')}")
        # 看看有没有 events / listings 等
        for key in ['events', 'listings', 'purchases', 'assets']:
            if key in data:
                val = data[key]
                print(f"  键 {key} 的类型: {type(val)}，长度/大小: {len(val) if hasattr(val, '__len__') else 'N/A'}")
                if val:
                    print(f"  {key} 样例: {str(val)[:200]}")
except Exception as e:
    print(f"Steam Norender 错误: {e}")
