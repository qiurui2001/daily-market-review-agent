# -*- coding: utf-8 -*-
"""
build_social_profile.py —— 用真实战绩生成社媒文案（X 置顶推文 + Telegram 置顶消息）

读取 `TRACK_RECORD.md` / `CRYPTO_TRACK_RECORD.md`，提取「已判分条数 / 命中率 / 宽松命中率」，
填充 `docs/SOCIAL-COPY.md` 里的模板，输出可直接粘贴的文案。

用法：
    python scripts/build_social_profile.py
环境变量（可选）：
    REPO_URL=https://github.com/you/daily-market-review-agent
    CHANNEL_URL=https://t.me/yourchannel
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = os.environ.get("REPO_URL", "https://github.com/qiurui2001/daily-market-review-agent")
CHANNEL_URL = os.environ.get("CHANNEL_URL", os.environ.get("TELEGRAM_CHANNEL_URL", "https://t.me/yourchannel"))


def _read(name: str) -> str:
    p = ROOT / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _us_stats() -> dict:
    txt = _read("TRACK_RECORD.md")
    hit = re.search(r"\*\*([\d.]+)%\*\*.*?loose \(hit\+partial\) ([\d.]+)%", txt)
    n = re.search(r"(\d+)\s*scored predictions", txt)
    return {
        "n": n.group(1) if n else "—",
        "hit": f"{hit.group(1)}%" if hit else "—",
        "loose": f"{hit.group(2)}%" if hit else "—",
    }


def _cr_stats() -> dict:
    txt = _read("CRYPTO_TRACK_RECORD.md")
    hit = re.search(r"总体命中率：([\d.]+)%.*?宽松（命中\+部分）([\d.]+)%", txt)
    n = re.search(r"可核验预测：\*\*(\d+)\*\*", txt)
    return {
        "n": n.group(1) if n else "—",
        "hit": f"{hit.group(1)}%" if hit else "—",
        "loose": f"{hit.group(2)}%" if hit else "—",
    }


def render() -> str:
    us, cr = _us_stats(), _cr_stats()
    return f"""==================== Telegram 置顶消息 ====================
📌 频道导航

▶️ 免费（每日）：
   · 美股复盘：大盘 + 板块/结构
   · 加密复盘：BTC/ETH 行情 + 杠杆与结构
🔒 私域（筹备中）：多空点位、操作策略、个性化持仓复盘、周报/月报
📊 公开战绩（确定性判分 · 哈希链防篡改 · 不可回改）：
   · 美股 {us['n']} 条已判分，命中 {us['hit']}（宽松 {us['loose']}）
   · 加密 {cr['n']} 条已判分，命中 {cr['hit']}（宽松 {cr['loose']}）
🔗 台账原始数据：{REPO_URL}/blob/main/TRACK_RECORD.md
⚠️ 仅供研究参考，不构成任何投资建议。

==================== X 置顶推文 ====================
📊 用 AI 每天复盘美股 & 加密，并把每条预测写进不可回改的哈希链台账、用真实行情客观判分。

公开战绩（自动更新）：
· 美股 {us['n']} 条已判分，命中 {us['hit']}（宽松 {us['loose']}）
· 加密 {cr['n']} 条已判分，命中 {cr['hit']}（宽松 {cr['loose']}）

点位与操作策略 → {CHANNEL_URL}
研究参考，非投资建议。

==================== X 简介（Bio） ====================
每天收盘自动复盘美股&加密。每条预测写进哈希链台账、用真实行情客观判分——战绩公开可查。研究参考，非投资建议。
"""


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(render())
