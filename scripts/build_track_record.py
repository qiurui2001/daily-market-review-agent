# -*- coding: utf-8 -*-
"""
build_track_record.py —— 从预测台账生成「Live Track Record」
=============================================================

把 `prediction_ledger.jsonl`（只追加哈希链台账）里的预测，用确定性判分汇总，
渲染成：
1. `README.md` / `README.zh-CN.md` 中 `<!-- TRACK_RECORD:START/END -->` 之间的**内嵌战绩块**；
2. `TRACK_RECORD.md` 的**完整战绩页**。

供 GitHub Actions 每日自动运行（无需人工）。网络不可用时优雅降级。

用法：
    python scripts/build_track_record.py            # 中英双语 + 完整页
    python scripts/build_track_record.py --lang en  # 只更新英文
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ledger  # noqa: E402

START = "<!-- TRACK_RECORD:START -->"
END = "<!-- TRACK_RECORD:END -->"

_CAP_EN = {"方向": "Direction", "行业": "Sector", "事件": "Event", "风险": "Risk"}
_CAP_ZH = {"方向": "方向", "行业": "行业", "事件": "事件", "风险": "风险"}
_INST_EN = {
    "标普500": "S&P 500", "纳斯达克综指": "Nasdaq", "道琼斯": "Dow Jones",
    "纳斯达克100": "Nasdaq 100", "罗素2000": "Russell 2000", "VIX": "VIX",
    "半导体(SMH)": "Semis (SMH)", "科技(XLK)": "Tech (XLK)", "金融(XLF)": "Financials (XLF)",
    "能源(XLE)": "Energy (XLE)", "医疗(XLV)": "Health Care (XLV)", "可选消费(XLY)": "Cons. Disc. (XLY)",
    "必需消费(XLP)": "Cons. Staples (XLP)", "工业(XLI)": "Industrials (XLI)", "原材料(XLB)": "Materials (XLB)",
    "公用事业(XLU)": "Utilities (XLU)", "房地产(XLRE)": "Real Estate (XLRE)", "通信(XLC)": "Comm. (XLC)",
}
_VERDICT_EN = {"hit": "✅ Hit", "partial": "⚠️ Partial", "miss": "❌ Miss", "unverifiable": "⏳ Pending"}
_VERDICT_ZH = {"hit": "✅命中", "partial": "⚠️部分命中", "miss": "❌偏离", "unverifiable": "⏳待验证"}


def _collect():
    """返回 (全部条目, 可核验条目)。网络失败时返回 ([], [])。"""
    try:
        items = ledger.score_all(days_back=3650)
    except Exception:  # noqa: BLE001
        return [], []
    scored = [s for s in items if s["verdict"] in ledger._VERDICTS]
    return items, scored


def _esc(s: str, n: int = 42) -> str:
    s = s.replace("|", "/").replace("\n", " ").strip()
    return s[:n] + ("…" if len(s) > n else "")


def render_block(lang: str, items: list[dict], scored: list[dict]) -> str:
    cap_map = _CAP_EN if lang == "en" else _CAP_ZH
    vd_map = _VERDICT_EN if lang == "en" else _VERDICT_ZH

    if not scored:
        if lang == "en":
            return ("_📉 Collecting data — the live track record begins once the agent has run for a few days._\n\n"
                    "_Every prediction is committed to `prediction_ledger.jsonl` (append-only, hash-chained) "
                    "and scored automatically against what the market actually did._")
        return ("_📉 数据积累中——系统运行几天后即出现实时战绩。_\n\n"
                "_每条预测都写入 `prediction_ledger.jsonl`（只追加、哈希链），并自动用真实行情判分。_")

    overall = ledger._rates([s["verdict"] for s in scored])
    dates = sorted({s["report_date"] for s in scored})

    if lang == "en":
        head = (f"_Last updated: **{datetime.now():%Y-%m-%d}** · auto-generated from `prediction_ledger.jsonl`_")
        kpi = (f"**Overall hit rate: {overall['hit_rate']:.1f}%** "
               f"(95% CI {overall['ci'][0]:.0f}–{overall['ci'][1]:.0f}) · "
               f"**{overall['verified']} scored predictions · {len(dates)} trading "
               f"{'day' if len(dates) == 1 else 'days'}**")
        cols = ["Capability", "Hit rate", "n"]
        latest_title = "**Latest calls**"
        no_latest = "_No calls yet._"
        inst = lambda x: _INST_EN.get(x, x)
    else:
        head = f"_最后更新：**{datetime.now():%Y-%m-%d}** · 由 `prediction_ledger.jsonl` 自动生成_"
        kpi = (f"**总体命中率 {overall['hit_rate']:.1f}%**"
               f"（95% 置信区间 {overall['ci'][0]:.0f}–{overall['ci'][1]:.0f}）· "
               f"**已核验 {overall['verified']} 条 · 覆盖 {len(dates)} 个交易日**")
        cols = ["能力维度", "命中率", "样本"]
        latest_title = "**最新预测**"
        no_latest = "_暂无预测。_"
        inst = lambda x: x

    groups: dict = {}
    for s in scored:
        groups.setdefault(s["capability"], []).append(s["verdict"])

    lines = [head, "", kpi, "", f"| {cols[0]} | {cols[1]} | {cols[2]} |", "|---|---|---|"]
    for key in ("方向", "行业", "事件", "风险"):
        if key in groups:
            r = ledger._rates(groups[key])
            lines.append(f"| {cap_map.get(key, key)} | {r['hit_rate']:.0f}% | {r['verified']} |")

    lines += ["", latest_title, "", f"| {'Date' if lang=='en' else '日期'} | "
              f"{'Instrument' if lang=='en' else '标的'} | "
              f"{'Call' if lang=='en' else '预测'} | "
              f"{'Result' if lang=='en' else '结果'} |", "|---|---|---|---|"]
    latest = sorted(sorted(items, key=lambda s: s["report_date"], reverse=True)[:6],
                    key=lambda s: s["report_date"], reverse=True)
    if latest:
        for s in latest:
            lines.append(f"| {s['report_date']} | {inst(s['instrument'])} | {_esc(s['text'])} "
                         f"| {vd_map.get(s['verdict'], s['verdict'])} |")
    else:
        lines.append(f"| — | — | {no_latest} | — |")
    return "\n".join(lines)


def update_markers(path: Path, block: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if START not in text or END not in text:
        return False
    pre = text.split(START)[0]
    post = text.split(END)[-1]
    new = f"{pre}{START}\n{block}\n{END}{post}"
    if new != text:
        path.write_text(new, encoding="utf-8")
        return True
    return False


def render_full(items: list[dict], scored: list[dict]) -> str:
    if not scored:
        return ("# Live Track Record\n\n"
                "_📉 Collecting data — no scored predictions yet._\n\n"
                "Run `python main.py` daily; predictions are committed to `prediction_ledger.jsonl` "
                "and scored automatically.\n")
    overall = ledger._rates([s["verdict"] for s in scored])
    dates = sorted({s["report_date"] for s in scored})
    lines = [
        "# Live Track Record",
        "",
        f"_Last updated: {datetime.now():%Y-%m-%d} · {len(scored)} scored predictions · "
        f"{len(dates)} trading days ({dates[0]} ~ {dates[-1]})_",
        "",
        f"## Overall\n\n**{overall['hit_rate']:.1f}%** "
        f"(95% CI {overall['ci'][0]:.0f}–{overall['ci'][1]:.0f}) · "
        f"loose (hit+partial) {overall['loose_rate']:.1f}%",
    ]
    for dim, keyf in (("By capability", lambda s: _CAP_EN.get(s["capability"], s["capability"])),
                      ("By market regime", lambda s: s["regime"]),
                      ("By horizon", lambda s: s["horizon"])):
        groups: dict = {}
        for s in scored:
            groups.setdefault(keyf(s), []).append(s["verdict"])
        lines += ["", f"## {dim}", "", "| Group | Hit rate | n | 95% CI |", "|---|---|---|---|"]
        for k, v in sorted(groups.items(), key=lambda x: -len(x[1])):
            r = ledger._rates(v)
            lines.append(f"| {k} | {r['hit_rate']:.1f}% | {r['verified']} "
                         f"| [{r['ci'][0]:.0f}, {r['ci'][1]:.0f}] |")
    lines += ["", "> Deterministic scoring: levels = touched by high/low; direction = move beyond the "
                  "volatility noise band. Scoring rules are frozen and versioned — history is never re-scored.",
              "", "> Research only. Not investment advice."]
    return "\n".join(lines)


def write_latest_report() -> bool:
    """把最新一份复盘报告复制到根目录 LATEST_REPORT.md（reports/ 被 git 忽略，需单独发布）。"""
    rep_dir = ROOT / "reports"
    files = sorted(rep_dir.glob("美股复盘_*.md")) if rep_dir.exists() else []
    if not files:
        return False
    latest = files[-1]
    body = latest.read_text(encoding="utf-8", errors="replace")
    banner = (f"> Auto-published from `reports/{latest.name}` on {datetime.now():%Y-%m-%d}. "
              f"[Track Record](TRACK_RECORD.md) · Research only, not investment advice.\n\n---\n\n")
    (ROOT / "LATEST_REPORT.md").write_text(banner + body, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=["both", "en", "zh"], default="both")
    args = parser.parse_args()

    items, scored = _collect()
    changed = []

    if args.lang in ("both", "en"):
        en = render_block("en", items, scored)
        if update_markers(ROOT / "README.md", en):
            changed.append("README.md")
    if args.lang in ("both", "zh"):
        zh = render_block("zh", items, scored)
        if update_markers(ROOT / "README.zh-CN.md", zh):
            changed.append("README.zh-CN.md")

    (ROOT / "TRACK_RECORD.md").write_text(render_full(items, scored), encoding="utf-8")
    changed.append("TRACK_RECORD.md")

    if write_latest_report():
        changed.append("LATEST_REPORT.md")

    print(f"Track record updated ({len(scored)} scored predictions). Changed: {', '.join(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
