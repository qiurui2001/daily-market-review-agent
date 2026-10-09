# -*- coding: utf-8 -*-
"""
notify.py —— 可选推送（Telegram）
=================================

把当日复盘摘要推送到 Telegram 频道/群，形成「Star → Telegram → 用户」的留存闭环。
未配置 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 时静默跳过（no-op）。

配置见 docs/SETUP-TELEGRAM.md。
"""

from __future__ import annotations

import os

import requests

TELEGRAM_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "20") or "20")


def send_telegram(text: str) -> str:
    """推送一条文本消息。未配置则返回跳过提示，不抛异常。"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return "【跳过】未配置 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID。"

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True},
            timeout=TELEGRAM_TIMEOUT,
        )
        ok = resp.status_code == 200 and (resp.json() or {}).get("ok")
        return "Telegram 已推送。" if ok else f"【失败】Telegram 返回 {resp.status_code}: {resp.text[:120]}"
    except Exception as exc:  # noqa: BLE001
        return f"【失败】{exc}"


def daily_digest(today: str, report_md: str = "") -> str:
    """构造当日推送摘要（首屏即结论，附战绩页链接）。"""
    head = f"📈 美股复盘 | {today}"
    body = report_md.strip()[:1200] if report_md else ""
    tail = "\n\n📊 Live Track Record: https://github.com/your-org/your-repo/blob/main/TRACK_RECORD.md"
    return head + ("\n\n" + body if body else "") + tail


if __name__ == "__main__":
    print(send_telegram("测试消息：Daily Market Review Agent 已接通 Telegram。"))
