# -*- coding: utf-8 -*-
"""
build_crypto_track_record.py —— 从加密预测台账生成加密战绩页
============================================================

把 `crypto_ledger.jsonl`（只追加哈希链台账）里的预测用确定性判分汇总，渲染成：
1. `CRYPTO_TRACK_RECORD.md` —— 加密完整战绩页；
2. `LATEST_CRYPTO_REPORT.md` —— 最新一份《加密复盘》报告副本（reports/ 被 git 忽略，需单独发布）。

供 GitHub Actions 每日自动运行（无需人工）。网络不可用时优雅降级。

用法：
    python scripts/build_crypto_track_record.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crypto_ledger as cl  # noqa: E402

CRYPTO_TRACK_FILE = ROOT / "CRYPTO_TRACK_RECORD.md"
LATEST_REPORT_FILE = ROOT / "LATEST_CRYPTO_REPORT.md"


def build() -> list[str]:
    changed: list[str] = []

    body = cl.get_crypto_track_record.run(days_back=100000)
    header = (
        f"> Auto-generated from `crypto_ledger.jsonl` on {datetime.now():%Y-%m-%d}. "
        "Research only, not investment advice.\n\n---\n\n"
    )
    CRYPTO_TRACK_FILE.write_text(header + body + "\n", encoding="utf-8")
    changed.append("CRYPTO_TRACK_RECORD.md")

    rep_dir = ROOT / "reports"
    files = sorted(rep_dir.glob("加密复盘_*.md")) if rep_dir.exists() else []
    if files:
        latest = files[-1]
        banner = (
            f"> Auto-published from `reports/{latest.name}` on {datetime.now():%Y-%m-%d}. "
            "[Crypto Track Record](CRYPTO_TRACK_RECORD.md) · Research only, not investment advice.\n\n---\n\n"
        )
        LATEST_REPORT_FILE.write_text(banner + latest.read_text(encoding="utf-8"), encoding="utf-8")
        changed.append("LATEST_CRYPTO_REPORT.md")

    return changed


if __name__ == "__main__":
    print("更新：" + "、".join(build()))
