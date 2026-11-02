"""Minimal Telegram Bot API sender."""
from __future__ import annotations

import requests


class TelegramClient:
    def __init__(self, token: str, chat_id: str):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id

    def send(self, text: str) -> None:
        resp = requests.post(self.url, json={
            "chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"Telegram returned {resp.status_code}: {resp.text[:200]}")
