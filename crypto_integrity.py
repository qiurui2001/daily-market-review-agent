# -*- coding: utf-8 -*-
"""
crypto_integrity.py —— 加密预测的只追加、哈希链台账（防篡改）
=============================================================

与美股 `integrity.py` 共用同一套哈希链内核（`integrity.commit/verify_chain/reconcile`），
仅将台账文件与「预测条目构造器」换成加密版本：

- 台账文件：`crypto_ledger.jsonl`（放项目根目录，**应纳入版本控制**）；
- 条目来源：`crypto_ledger.build_items_for_date`（解析 `加密复盘_{date}.md`）。

用途：加密预测一旦落库不可回改，判分由行情独立重算，从而形成可信的 Crypto Track Record。

所有数据仅供研究参考，不构成投资建议。
"""

from __future__ import annotations

import os
from pathlib import Path

from crewai.tools import tool

import crypto_ledger
import integrity

CRYPTO_LEDGER_FILE = Path(os.environ.get("CRYPTO_LEDGER_FILE", "crypto_ledger.jsonl"))


def commit_crypto_day(date: str) -> str:
    """把某日《加密复盘》里的预测提交进加密哈希链台账。同一天已提交则跳过（只追加，不覆盖）。"""
    return integrity.commit(CRYPTO_LEDGER_FILE, date,
                            crypto_ledger.build_items_for_date(date), "加密预测")


def verify_crypto_chain() -> str:
    return integrity.verify_chain(CRYPTO_LEDGER_FILE)


def reconcile_crypto() -> str:
    return integrity.reconcile(CRYPTO_LEDGER_FILE, builder=crypto_ledger.build_items_for_date)


def crypto_chain_summary() -> str:
    return integrity.chain_summary(CRYPTO_LEDGER_FILE)


@tool
def verify_crypto_ledger_integrity() -> str:
    """校验加密预测台账（只追加哈希链）的完整性：检测文件是否被篡改、记录是否断裂，
    并对比台账与当前《加密复盘》报告是否一致。用于证明加密历史战绩未被回改。"""
    return verify_crypto_chain() + "\n" + reconcile_crypto()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "commit":
        from crypto_tools import crypto_trade_date
        d = sys.argv[2] if len(sys.argv) > 2 else crypto_trade_date()
        print(commit_crypto_day(d))
    else:
        print(crypto_chain_summary())
        print(verify_crypto_chain())
        print(reconcile_crypto())
