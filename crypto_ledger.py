# -*- coding: utf-8 -*-
"""
crypto_ledger.py —— 加密预测的「确定性」自动核验与命中率统计
=============================================================

与美股 `ledger.py` 同源同口径的护城河：把「判对判错」交给**价格数据确定性计算**，
模型只负责归因。差异仅在于：

- 报告文件：`加密复盘_{date}.md`；
- 标的：BTC / ETH（默认 BTC）；
- 行情：Gate.io 现货日 K（UTC 收线），窗口按 UTC 日切分；
- 能力维度：方向 / 资金·衍生品 / 事件 / 风险。

判分规则完全复用 `ledger.py`（压力/支撑/突破/跌破/关键位是否触及；方向按波动率归一化，
噪音带内记为「未定」不计分），口径固定、可复现。评分规则变更**只对未来生效**，不回改历史。

所有数据仅供研究参考，不构成投资建议。
"""

from __future__ import annotations

import os
from datetime import datetime

from crewai.tools import tool

# 复用美股台账的抽取与统计内核（口径统一）
from ledger import (
    SHOCK_MULT,
    VOL_MULT,
    _FULL_DATE,
    _KIND_LABEL,
    _NUM_RE,
    _VERDICT_ICON,
    _VERDICTS,
    _aggregate,
    _base_close,
    _classify_level,
    _conf_bucket,
    _daily_vol,
    _direction,
    _fmt_line,
    _group_table,
    _horizon,
    _horizon_label,
    _noise_band,
    _prediction_sections,
    _rates,
    _regime,
    _score_rules,
    _shock_dates,
    _split_chunks,
    _strip_noise,
    extract_confidence,
    extract_scenarios,
)

from crypto_tools import _crypto_bars
from tools import REPORT_DIR, _to_float

CRYPTO_GLOB = "加密复盘_*.md"
# 加密点位数范围远宽于美股（BTC 可达 6 位数、部分币 0.xxx），单独设阈
_MIN_LEVEL = float(os.environ.get("CRYPTO_PRED_MIN_LEVEL", "0.1") or "0.1")
_MAX_LEVEL = float(os.environ.get("CRYPTO_PRED_MAX_LEVEL", "10000000") or "10000000")


# ──────────────────────────────────────────────────────────────────────────────
# 一、标的与能力维度
# ──────────────────────────────────────────────────────────────────────────────
_CRYPTO_INSTRUMENT_RULES = [
    (("btc", "比特币", "bitcoin", "xbt"), "BTC"),
    (("eth", "以太坊", "以太", "ethereum"), "ETH"),
]


def _instrument(text: str) -> str:
    """按「最先被提及」判断标的，避免把『ETH/BTC』这类文本误判为 BTC。"""
    low = text.lower()
    best_symbol, best_pos = None, len(low) + 1
    for keywords, symbol in _CRYPTO_INSTRUMENT_RULES:
        for kw in keywords:
            pos = low.find(kw)
            if pos != -1 and pos < best_pos:
                best_pos, best_symbol = pos, symbol
    return best_symbol or "BTC"  # 加密复盘默认围绕 BTC


_CAP_RISK = ("风险", "回撤", "止损", "爆仓", "挤兑", "警惕", "谨防", "见顶", "破位", "清算", "去杠杆", "闪崩")
_CAP_EVENT = ("etf", "减半", "美联储", "cpi", "pce", "降息", "加息", "监管", "sec", "升级", "分叉",
              "解锁", "空投", "上市", "会议", "讲话", "大会", "听证", "法案", "合规")
_CAP_FLOW = ("资金费率", "funding", "持仓", "未平仓", "oi", "多空比", "爆仓", "清算", "流入", "流出",
             "净流入", "净流出", "主导率", "轮动", "eth/btc", "汇率", "灰度", "etf 资金", "现货 etf",
             "链上", "巨鲸", "稳定币")


def _capability(text: str) -> str:
    low = text.lower()
    if any(k in low for k in _CAP_RISK):
        return "风险"
    if any(k in low for k in _CAP_EVENT):
        return "事件"
    if any(k in low for k in _CAP_FLOW):
        return "资金/衍生品"
    return "方向"


# ──────────────────────────────────────────────────────────────────────────────
# 二、预测要素抽取（加密点位阈值）
# ──────────────────────────────────────────────────────────────────────────────
def _extract_rules(text: str) -> list[dict]:
    rules: list[dict] = []
    direction, kw = _direction(text)
    if direction:
        label = {"bull": "看多", "bear": "看空", "range": "震荡"}[direction]
        rules.append({"kind": "direction", "dir": direction, "desc": f"{label}（{kw}）"})

    clean = _strip_noise(text)
    seen: set = set()
    for m in _NUM_RE.finditer(clean):
        try:
            num = float(m.group().replace(",", ""))
        except ValueError:
            continue
        if not (_MIN_LEVEL <= num <= _MAX_LEVEL):
            continue
        before = clean[max(0, m.start() - 18):m.start()]
        kind = _classify_level(before)
        if not kind or (kind, num) in seen:
            continue
        seen.add((kind, num))
        rules.append({"kind": kind, "level": num, "desc": f"{_KIND_LABEL[kind]} {num:g}"})
    return rules


# ──────────────────────────────────────────────────────────────────────────────
# 三、报告解析
# ──────────────────────────────────────────────────────────────────────────────
def _iter_reports():
    if not REPORT_DIR.exists():
        return
    for path in sorted(REPORT_DIR.glob(CRYPTO_GLOB)):
        m = _FULL_DATE.search(path.name)
        if m:
            yield f"{m.group(1)}-{m.group(2)}-{m.group(3)}", path


def _items_from_text(text: str, report_date: str) -> list[dict]:
    items: list[dict] = []
    for _head, body in _prediction_sections(text):
        for chunk in _split_chunks(body):
            if len(chunk) < 6 or len(chunk) > 300:
                continue
            rules = _extract_rules(chunk)
            if not rules:
                continue
            symbol = _instrument(chunk)
            items.append({"report_date": report_date, "text": chunk,
                          "instrument": symbol, "symbol": symbol, "rules": rules,
                          "capability": _capability(chunk),
                          "confidence": extract_confidence(chunk)})
    return items


def build_items(days_back: int = 30, exclude_date: str = "") -> list[dict]:
    ref = datetime.now()
    items: list[dict] = []
    for report_date, path in _iter_reports():
        if exclude_date and report_date == exclude_date:
            continue
        try:
            age = (ref - datetime.strptime(report_date, "%Y-%m-%d")).days
        except ValueError:
            age = 0
        if age < 0 or age > days_back:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        items.extend(_items_from_text(text, report_date))
    return items


def build_items_for_date(date: str) -> list[dict]:
    """只读取 `加密复盘_{date}.md` 抽取预测（供台账提交/校验用）。"""
    path = REPORT_DIR / f"加密复盘_{date}.md"
    if not path.exists():
        return []
    return _items_from_text(path.read_text(encoding="utf-8", errors="replace"), date)


# ──────────────────────────────────────────────────────────────────────────────
# 四、确定性判分（窗口按 UTC 日切分，行情用 Gate 现货日 K）
# ──────────────────────────────────────────────────────────────────────────────
def score_item(item: dict, cache: dict) -> dict:
    symbol = item["symbol"]
    bars = cache.get(symbol)
    if bars is None:
        bars = _crypto_bars(symbol, 400)
        cache[symbol] = bars
    regime = _regime(bars, item["report_date"]) if bars else "数据不足"
    if not bars:
        return {**item, "verdict": "unverifiable", "verdict_ex_shock": "unverifiable",
                "rules_detail": [], "ret": None, "range_text": "无行情",
                "horizon": _horizon_label(_horizon(item["text"])), "shock_days": [], "regime": regime}

    vol = _daily_vol(bars)
    shock = _shock_dates(bars, vol)
    h = _horizon(item["text"])
    latest = bars[-1][0]
    window = [b for b in bars if item["report_date"] < b[0] <= latest][:h]

    if not window:
        return {**item, "verdict": "unverifiable", "verdict_ex_shock": "unverifiable",
                "rules_detail": [], "ret": None, "range_text": "无后续行情",
                "horizon": _horizon_label(h), "shock_days": [], "regime": regime}

    scored = _score_rules(item["rules"], window, vol, _base_close(bars, window))
    verdict, hit_n, total = _aggregate(scored[0]) if scored else ("unverifiable", 0, 0)
    hi, lo, ret = (scored[1], scored[2], scored[3]) if scored else (None, None, None)

    ex_bars = [b for b in window if b[0] not in shock]
    verdict_ex = "unverifiable"
    if ex_bars:
        scored_ex = _score_rules(item["rules"], ex_bars, vol, _base_close(bars, window))
        verdict_ex, _, _ = _aggregate(scored_ex[0]) if scored_ex else ("unverifiable", 0, 0)

    window_shock = sorted(b[0] for b in window if b[0] in shock)
    return {
        **item,
        "verdict": verdict, "verdict_ex_shock": verdict_ex,
        "rules_detail": scored[0] if scored else [],
        "hit_n": hit_n, "total": total, "ret": round(ret, 2) if ret is not None else None,
        "range_text": f"{window[0][0]}~{window[-1][0]}（{lo:,.0f}~{hi:,.0f}）" if lo is not None else "—",
        "horizon": _horizon_label(h), "shock_days": window_shock, "regime": regime,
    }


def score_all(days_back: int = 90, exclude_date: str = "") -> list[dict]:
    items = build_items(days_back=days_back, exclude_date=exclude_date)
    cache: dict = {}
    return [score_item(it, cache) for it in items]


def _collect_brier(days_back: int, cache: dict) -> list[float]:
    ref = datetime.now()
    scores: list[float] = []
    for report_date, path in _iter_reports():
        try:
            age = (ref - datetime.strptime(report_date, "%Y-%m-%d")).days
        except ValueError:
            age = 0
        if age < 0 or age > days_back:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for _head, body in _prediction_sections(text):
            scen = [s for s in extract_scenarios(body) if s["prob"] is not None]
            if len(scen) < 2:
                continue
            symbol = _instrument(body)
            bars = cache.get(symbol) or _crypto_bars(symbol, 400)
            cache[symbol] = bars
            if not bars:
                continue
            vol = _daily_vol(bars)
            h = _horizon(body)
            window = [b for b in bars if report_date < b[0] <= bars[-1][0]][:h]
            if not window:
                continue
            closes = [_to_float(b[2]) for b in window if _to_float(b[2]) is not None]
            start = _base_close(bars, window) or (closes[0] if closes else None)
            if not closes or not start:
                continue
            ret = (closes[-1] / start - 1) * 100
            band = _noise_band(vol, len(window))
            th = band if band is not None else 0.5
            realized = "bull" if ret >= th else ("bear" if ret <= -th else "range")
            brier = sum((s["prob"] - (1.0 if s["direction"] == realized else 0.0)) ** 2 for s in scen)
            scores.append(brier)
    return scores


# ──────────────────────────────────────────────────────────────────────────────
# 五、工具：确定性核验 / 概率校准 / 战绩
# ──────────────────────────────────────────────────────────────────────────────
@tool
def auto_verify_crypto_predictions(days_back: int = 30, max_items: int = 12,
                                   exclude_date: str = "") -> str:
    """从往期《加密复盘》报告抽取「对未来的预测」，用真实日 K（Gate 现货，UTC）**确定性自动判分**
    （压力/支撑/突破/跌破位是否触及；方向按波动率归一化，落在噪音带内记为「未定」），输出逐条核验表。
    复盘校验员应**以本工具结果为准**，只负责补充「归因」。

    Args:
        days_back: 只核验最近多少天内的报告，默认 30。
        max_items: 最多返回多少条预测，默认 12。
        exclude_date: 需排除的报告日期（如今天正在生成的报告）。
    """
    items = build_items(days_back=days_back, exclude_date=exclude_date)
    if not items:
        return (f"【无往期预测】{REPORT_DIR.resolve()} 下最近 {days_back} 天内没有可核验的"
                f"《加密复盘》预测；首次运行属正常。")

    cache: dict = {}
    scored = [score_item(it, cache) for it in items]
    scored.sort(key=lambda x: x["report_date"], reverse=True)
    scored = scored[:max(1, int(max_items))]

    def esc(s: str) -> str:
        return s.replace("|", "/").replace("\n", " ")

    def icon(hit) -> str:
        return "—" if hit is None else ("✅" if hit else "❌")

    lines = [
        f"# 加密往期预测自动核验（确定性，共 {len(scored)} 条）",
        "",
        "> 判分口径：压力/目标位=期间最高价是否触及；支撑位=期间最低价是否触及；"
        "突破/跌破位=期间收盘价是否突破/跌破；关键位=区间是否穿过；"
        f"方向=区间涨跌是否超过噪音带（{VOL_MULT:g}×日波动×√N，带内记为「未定」不计分）。",
        "",
        "| 报告日期 | 视野 | 币种 | 预测内容 | 实际走势（核验区间） | 结论 | 规则命中明细 |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in scored:
        detail = "；".join(
            f"{d['desc']}:{icon(d['hit'])}{d['actual']}" for d in s["rules_detail"]
        ) or "（无可判分规则）"
        note = f"（冲击日 {'、'.join(s['shock_days'])}）" if s["shock_days"] else ""
        lines.append(
            f"| {s['report_date']} | {s['horizon']} | {s['instrument']} | {esc(s['text'])[:80]} "
            f"| {s['range_text']} | {_VERDICT_ICON.get(s['verdict'], s['verdict'])} | {esc(detail)}{note} |"
        )

    r = _rates([s["verdict"] for s in scored])
    lines += ["", _fmt_line("本次自动核验", r)]
    return "\n".join(lines)


@tool
def get_crypto_prediction_stats(window: int = 5, days_back: int = 90) -> str:
    """统计加密往期预测的命中率（**以确定性自动核验为准**）：全时段 / 按视野分桶，
    各带 Wilson 95% 置信区间，并给出「剔除冲击日」对照与情景概率 Brier 校准分。

    Args:
        window: 滚动窗口（最近多少份含预测的报告），默认 5。
        days_back: 统计覆盖最近多少天内的报告，默认 90。
    """
    scored = score_all(days_back=days_back)
    valid = [s for s in scored if s["verdict"] in _VERDICTS]
    if not valid:
        return "【无数据】未在加密历史复盘中找到可核验的预测，或尚无历史《加密复盘》报告。"

    dates = sorted({s["report_date"] for s in valid})
    recent = set(dates[-window:]) if dates else set()

    lines = [
        "# 加密预测命中率统计（确定性自动核验）",
        "",
        f"- 覆盖含预测报告的份数：**{len(dates)}** 份",
        f"- 累计可核验预测：**{len(valid)}** 条",
        "",
        "## 全时段",
        _fmt_line("原始", _rates([s["verdict"] for s in scored])),
        _fmt_line("剔除冲击日", _rates([s["verdict_ex_shock"] for s in scored])),
    ]
    shock_n = sum(len(s["shock_days"]) for s in scored)
    lines.append(f"- 冲击日合计 {shock_n} 个（单日 |涨跌| > {SHOCK_MULT:g}×日波动）")

    lines += ["", "## 按视野分桶"]
    for label in ("次日", "约1周", "1-2周"):
        bucket = [s for s in valid if s["horizon"] == label]
        lines.append(_fmt_line(label, _rates([s["verdict"] for s in bucket])))

    if recent:
        lines += ["", f"## 近 {window} 份（{('、'.join(sorted(recent))) or '—'}）",
                  _fmt_line("滚动", _rates([s["verdict"] for s in scored if s["report_date"] in recent]))]

    cache: dict = {}
    brier = _collect_brier(days_back, cache)
    if brier:
        avg = sum(brier) / len(brier)
        baseline = 2 / 3
        lines += ["", "## 情景概率校准（Brier，越低越好）",
                  f"- 平均 Brier **{avg:.3f}**（均匀基准 {baseline:.3f}，共 {len(brier)} 组）："
                  f"{'优于' if avg < baseline else '劣于'}均匀先验。"]
    lines += ["", "> 判分口径变更只对**未来**生效，不回改历史（保证台账可审计）。"]
    return "\n".join(lines)


@tool
def get_crypto_track_record(days_back: int = 180, min_sample: int = 1) -> str:
    """输出加密「AI Research Track Record」：按**能力维度**（方向/资金·衍生品/事件/风险）、
    **市场体制**、**视野**、**置信度分档**分别统计命中率与 Wilson 区间，用于校准加密研究系统的强弱项。

    Args:
        days_back: 覆盖最近多少天内的报告，默认 180。
        min_sample: 每个分类至少多少条样本才展示，默认 1。
    """
    scored = [s for s in score_all(days_back=days_back) if s["verdict"] in _VERDICTS]
    if not scored:
        return "【无数据】暂无可核验的加密预测记录；先积累几天《加密复盘》即可形成 Track Record。"

    overall = _rates([s["verdict"] for s in scored])
    dates = sorted({s["report_date"] for s in scored})
    lines = [
        "# Crypto AI Research Track Record",
        "",
        f"- 观测窗口：{dates[0]} ~ {dates[-1]}（{len(dates)} 个 UTC 日）",
        f"- 可核验预测：**{overall['verified']}** 条",
        f"- **总体命中率：{overall['hit_rate']:.1f}%**"
        f"（Wilson 95% [{overall['ci'][0]:.0f}, {overall['ci'][1]:.0f}]），"
        f"宽松（命中+部分）{overall['loose_rate']:.1f}%",
        "",
    ]
    lines += _group_table(scored, lambda s: s["capability"], "按能力维度", min_sample)
    lines += [""]
    lines += _group_table(scored, lambda s: s["regime"], "按市场体制（做出预测时）", min_sample)
    lines += [""]
    lines += _group_table(scored, lambda s: s["horizon"], "按视野", min_sample)
    lines += [""]

    calib = [s for s in scored if s.get("confidence") is not None]
    if calib:
        lines += _group_table(calib, lambda s: _conf_bucket(s["confidence"]), "按表态置信度（校准）", min_sample)
        high = _rates([s["verdict"] for s in calib if s["confidence"] >= 0.8])
        if high["verified"] >= 3 and high["hit_rate"] < overall["hit_rate"]:
            lines += ["", f"> ⚠️ 高信心（≥80%）命中率 {high['hit_rate']:.1f}% 低于总体 "
                          f"{overall['hit_rate']:.1f}%，存在**过度自信**。"]
    else:
        lines += ["## 按表态置信度（校准）", "",
                  "（预测未标注概率，暂无法校准；建议在预判中写明情景概率，如「概率60%」。）"]
    lines += ["", "> 判分确定性、按维度/体制/视野/置信度分桶、带 Wilson 区间；样本少时勿下结论。"]
    return "\n".join(lines)


@tool
def get_crypto_error_analysis(days_back: int = 30, top_n: int = 8) -> str:
    """对最近一段时间的加密预测做**确定性错误结构分析**：找低命中率弱项、列典型偏离案例、
    检查过度自信与冲击日敏感性，并与「永远看多」基准对比。供《研究月报/自省》归因。

    Args:
        days_back: 分析覆盖最近多少天内的报告，默认 30。
        top_n: 最多列出多少条典型偏离案例，默认 8。
    """
    scored = [s for s in score_all(days_back=days_back) if s["verdict"] in _VERDICTS]
    if not scored:
        return "【无数据】暂无可分析的加密预测记录；先积累几天《加密复盘》。"

    overall = _rates([s["verdict"] for s in scored])
    lines = [
        f"# 加密错误结构分析（近 {days_back} 天）",
        "",
        f"- 可核验预测 {overall['verified']} 条，命中率 {overall['hit_rate']:.1f}%"
        f"（Wilson [{overall['ci'][0]:.0f}, {overall['ci'][1]:.0f}]），宽松 {overall['loose_rate']:.1f}%",
    ]
    rets = [s["ret"] for s in scored if s.get("ret") is not None]
    if rets:
        up = sum(1 for r in rets if r > 0) / len(rets) * 100
        lines.append(f"- 基准：窗口内上涨占比 {up:.1f}%（≈『永远看多』命中率）；"
                     f"系统{'跑赢' if overall['hit_rate'] >= up else '跑输'}该基准。")

    weak = []
    for label, keyf in (
        ("能力维度", lambda s: s["capability"]),
        ("市场体制", lambda s: s["regime"]),
        ("视野", lambda s: s["horizon"]),
        ("置信度", lambda s: _conf_bucket(s.get("confidence"))),
    ):
        groups: dict = {}
        for s in scored:
            groups.setdefault(keyf(s), []).append(s["verdict"])
        for k, v in groups.items():
            r = _rates(v)
            if r["verified"] >= 3 and r["hit_rate"] < overall["hit_rate"] - 10:
                weak.append((label, k, r["verified"], r["hit_rate"]))
    lines += ["", "## 弱项（样本≥3 且命中率明显低于总体）"]
    if weak:
        for label, k, n, hr in sorted(weak, key=lambda x: x[3]):
            lines.append(f"- 【{label}】{k}：{n} 条，命中率 {hr:.1f}%（总体 {overall['hit_rate']:.1f}%）")
    else:
        lines.append("- 暂无样本充足（≥3）且明显偏低的弱项。")

    misses = [s for s in scored if s["verdict"] == "miss"][:max(1, int(top_n))]
    lines += ["", "## 典型偏离案例"]
    if misses:
        for s in misses:
            fails = "；".join(f"{d['desc']}（{d['actual']}）" for d in s["rules_detail"] if d["hit"] is False)
            lines.append(f"- [{s['report_date']}·{s['capability']}·{s['horizon']}·{s['regime']}] "
                         f"{s['text'][:60]} → {fails or '—'}")
    else:
        lines.append("- 无完全偏离案例。")
    lines += ["", "> 以上为**确定性统计**；请据此撰写归因，不得编造数据。"]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        print(auto_verify_crypto_predictions.run(days_back=60))
    else:
        print(get_crypto_prediction_stats.run())
        print()
        print(get_crypto_track_record.run())
