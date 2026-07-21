from __future__ import annotations

import requests

from .base import NotifyResult


class AstrBotNotifier:
    """Send proactive plain-text messages through AstrBot OpenAPI."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        message_path: str = "/api/v1/im/message",
        timeout: float = 10,
        session: requests.Session | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("AstrBot base_url 不能为空")
        self.url = f"{base_url.rstrip('/')}/{message_path.lstrip('/')}"
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()

    def send_to(self, umo: str, title: str, content: str) -> NotifyResult:
        if not self.api_key:
            return NotifyResult(False, "AstrBot API Key 未配置")
        text = f"{title}\n{content}" if content else title
        try:
            response = self.session.post(
                self.url,
                headers={"X-API-Key": self.api_key},
                json={"umo": umo, "message": text},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") == "ok" or payload.get("ok") is True:
                return NotifyResult(True, "AstrBot 推送成功")
            return NotifyResult(False, f"AstrBot 返回异常: {payload}")
        except (requests.RequestException, ValueError) as exc:
            return NotifyResult(False, f"AstrBot 请求失败: {exc}")
