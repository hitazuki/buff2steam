# -*- coding: utf-8 -*-
"""
补充提取 Steam sessionid 并更新 config.yaml
"""
import io, json, os, shutil, socket, struct, subprocess, sys, time
from pathlib import Path
import requests
import yaml

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

CDP_PORT = 9222
CDP_BASE = f'http://localhost:{CDP_PORT}'
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

def launch_chrome():
    user_data_dir = Path(os.environ["TEMP"]) / "chrome_cookie_debug"
    user_data_dir.mkdir(exist_ok=True)
    return subprocess.Popen([
        CHROME_PATH,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "https://steamcommunity.com/login/home/",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def wait_for_chrome(timeout=20):
    for _ in range(timeout):
        try:
            if requests.get(f"{CDP_BASE}/json/version", timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False

def ws_connect():
    tabs = requests.get(f'{CDP_BASE}/json', timeout=5).json()
    page = next((t for t in tabs if t.get('type') == 'page'), tabs[0])
    ws_url = page['webSocketDebuggerUrl']
    from urllib.parse import urlparse
    p = urlparse(ws_url)
    host, port, path = p.hostname, p.port or 80, p.path
    key = __import__('base64').b64encode(os.urandom(16)).decode()
    sock = socket.create_connection((host, port), timeout=10)
    sock.send((
        f'GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n'
        f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'
    ).encode())
    buf = b''
    while b'\r\n\r\n' not in buf:
        buf += sock.recv(4096)
    return sock

def ws_send(sock, payload):
    data = payload.encode()
    mask = os.urandom(4)
    length = len(data)
    header = struct.pack('!BB', 0x81, 0x80 | length) if length < 126 else struct.pack('!BBH', 0x81, 0x80 | 126, length)
    sock.send(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

def ws_recv(sock):
    h = sock.recv(2)
    if len(h) < 2: return ''
    b1, b2 = h
    length = b2 & 0x7F
    if length == 126: length = struct.unpack('!H', sock.recv(2))[0]
    elif length == 127: length = struct.unpack('!Q', sock.recv(8))[0]
    payload = b''
    while len(payload) < length:
        payload += sock.recv(length - len(payload))
    return payload.decode('utf-8', errors='replace')

def get_all_cookies():
    sock = ws_connect()
    ws_send(sock, json.dumps({'id': 1, 'method': 'Network.getAllCookies'}))
    deadline = time.time() + 10
    while time.time() < deadline:
        raw = ws_recv(sock)
        if not raw: break
        try:
            data = json.loads(raw)
            if data.get('id') == 1:
                sock.close()
                return data.get('result', {}).get('cookies', [])
        except Exception:
            continue
    sock.close()
    return []

# ---- 主流程 ----
print("=" * 55)
print("  补充提取 Steam sessionid")
print("=" * 55)
print()

# 检查是否已有调试端口
running = False
try:
    if requests.get(f"{CDP_BASE}/json/version", timeout=2).status_code == 200:
        running = True
        print("[OK] Chrome 调试端口已开启")
except Exception:
    pass

proc = None
if not running:
    print("[1] 启动 Chrome（调试模式）...")
    proc = launch_chrome()
    if not wait_for_chrome(20):
        print("[错误] Chrome 启动超时")
        sys.exit(1)
    print("    [OK] Chrome 已就绪")
    print()
    print("[!] 请在打开的 Chrome 窗口中登录 steamcommunity.com")
    print()

try:
    input("登录完成后按 Enter...")
except (EOFError, OSError):
    time.sleep(3)
print()

print("正在获取所有 Cookie...")
all_cookies = get_all_cookies()

# 显示所有 steam 相关 Cookie 方便调试
steam_cookies = [c for c in all_cookies if 'steam' in c.get('domain', '').lower()]
print(f"找到 Steam 相关 Cookie {len(steam_cookies)} 个：")
for c in steam_cookies:
    mark = " <-- sessionid" if c['name'] == 'sessionid' else ""
    print(f"  [{c['domain']:35s}] {c['name']:25s} httpOnly={c.get('httpOnly', False)}{mark}")

print()

# 提取 sessionid
sessionid = ""
for c in steam_cookies:
    if c['name'] == 'sessionid':
        sessionid = c['value']
        print(f"[OK] sessionid = {sessionid[:8]}... (domain={c['domain']})")
        break

if not sessionid:
    print("[!] 所有 steam Cookie 中均无 sessionid，可能尚未登录或登录状态未同步")

if proc:
    proc.terminate()

# 写入 config.yaml
if sessionid:
    config_path = Path(__file__).parent / "config.yaml"
    if config_path.exists():
        with open(config_path, encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        config.setdefault('steam', {})['session_id'] = sessionid
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        print(f"[OK] sessionid 已写入 {config_path.resolve()}")
    else:
        print("[错误] config.yaml 不存在")
else:
    print("[!] 未能提取 sessionid，请手动填入 config.yaml")

print()
print("完成！运行 python src/main.py 开始统计")
