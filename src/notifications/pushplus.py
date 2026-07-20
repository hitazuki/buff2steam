from __future__ import annotations

import time

import requests

from .base import Notifier, NotifyResult


class PushPlusNotifier(Notifier):
    URL = "https://www.pushplus.plus/send"

    def __init__(
        self,
        token: str,
        timeout: float = 10,
        max_retries: int = 2,
        session: requests.Session | None = None,
    ) -> None:
        if not token:
            raise ValueError("PushPlus token 不能为空")
        self.token = token
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.session = session or requests.Session()

    def send(self, title: str, content: str) -> NotifyResult:
        last_error = "未知错误"
        payload = {
            "token": self.token,
            "title": title,
            "content": content,
            "template": "html",
            "channel": "wechat",
            "timestamp": int(time.time() * 1000),
        }
        for attempt in range(self.max_retries):
            try:
                response = self.session.post(self.URL, json=payload, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
                if data.get("code") == 200:
                    return NotifyResult(True, str(data.get("msg") or "PushPlus 推送成功"))
                last_error = f"PushPlus code={data.get('code')}: {data.get('msg')}"
            except (requests.RequestException, ValueError) as exc:
                last_error = f"PushPlus 请求失败: {exc}"
            if attempt + 1 < self.max_retries:
                time.sleep(2 ** attempt)
        return NotifyResult(False, last_error)
