# -*- coding: utf-8 -*-
"""
tools.py —— 美股盘后复盘 Agent 的工具集
===========================================

设计原则
--------
1. 只做「数据获取 + 交付」这类确定性动作，把「分析、判断、写作」留给 LLM。
2. 每个工具都做了重试与降级，返回**纯文本**，方便直接塞进 Agent 上下文。
3. 盘后复盘用不到毫秒级实时行情，优先使用稳定、免费、国内可直连的数据源：
   - 腾讯行情 (qt.gtimg.cn)     → 美股指数 / 个股 / ETF 快照（us 前缀）
   - 新浪美股 (US_MinKService)  → 美股日 K 线（指数 .INX/.IXIC/.DJI/.NDX、个股/ETF）
   - 新浪全球 (hq.sinajs.cn)    → 美元指数 / 布伦特原油 / 纽约黄金 / 日经·富时
   - 东方财富资讯 (np-listapi)  → 7x24 全球财经快讯
   - 必应搜索 (cn.bing.com)     → 补充新闻/事件检索
   - SMTP                       → 邮件交付

美股与 A 股的关键差异（本文件已据此取舍）：
- 美股**无涨跌停、无连板/炸板**，故不再采集「涨停池/连板梯队/炸板率」；
- 复盘核心转为：**指数、行业板块轮动（SPDR 行业 ETF）、市场内部结构（龙头/风格）、
  利率与美元、波动率 VIX、消息面与财报**。

所有数据仅供研究参考，不构成投资建议。
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import smtplib
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from crewai.tools import tool

# ──────────────────────────────────────────────────────────────────────────────
# 环境配置
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()

REPORT_DIR = Path(os.environ.get("REPORT_DIR", "reports"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "outputs"))

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or "587")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "") or SMTP_USER
REPORT_TO_EMAIL = os.environ.get("REPORT_TO_EMAIL", "")

HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "20") or "20")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

EM_NEWS_URL = "https://np-listapi.eastmoney.com/comm/web/getFastNewsList"

try:
    US_EASTERN = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001  Windows 缺少 tzdata 时降级为本地时间
    US_EASTERN = None


# ──────────────────────────────────────────────────────────────────────────────
# 标的注册表：名称 → (腾讯代码 usXXX, 新浪美股代码)
# 腾讯代码用于快照；新浪代码用于日 K 线（指数用 .INX/.IXIC/.DJI/.NDX）
# ──────────────────────────────────────────────────────────────────────────────
US_INDICES = {
    "标普500": ("usINX", ".INX"),
    "纳斯达克综指": ("usIXIC", ".IXIC"),
    "道琼斯": ("usDJI", ".DJI"),
    "纳斯达克100": ("usNDX", ".NDX"),
    "罗素2000": ("usIWM", "IWM"),   # 以 iShares 罗素2000 ETF 作小盘代理
    "VIX": ("usVIX", None),
}

US_SECTORS = {
    "科技": ("usXLK", "XLK"),
    "金融": ("usXLF", "XLF"),
    "能源": ("usXLE", "XLE"),
    "医疗保健": ("usXLV", "XLV"),
    "可选消费": ("usXLY", "XLY"),
    "必需消费": ("usXLP", "XLP"),
    "工业": ("usXLI", "XLI"),
    "原材料": ("usXLB", "XLB"),
    "公用事业": ("usXLU", "XLU"),
    "房地产": ("usXLRE", "XLRE"),
    "通信服务": ("usXLC", "XLC"),
}

US_MEGA = {
    "苹果": ("usAAPL", "AAPL"),
    "微软": ("usMSFT", "MSFT"),
    "英伟达": ("usNVDA", "NVDA"),
    "谷歌": ("usGOOGL", "GOOGL"),
    "亚马逊": ("usAMZN", "AMZN"),
    "Meta": ("usMETA", "META"),
    "特斯拉": ("usTSLA", "TSLA"),
}

US_STYLE = {
    "标普500(大盘)": ("usSPY", "SPY"),
    "罗素2000(小盘)": ("usIWM", "IWM"),
    "标普500等权": ("usRSP", "RSP"),
    "纳斯达克100(成长)": ("usQQQ", "QQQ"),
    "半导体": ("usSMH", "SMH"),
    "科技七巨头": ("usMAGS", "MAGS"),
}

US_BONDS = {
    "20年期以上美债ETF(TLT)": ("usTLT", "TLT"),
    "7-10年期美债ETF(IEF)": ("usIEF", "IEF"),
}

# 腾讯全球指数
GLOBAL_EQ_TENCENT = {
    "恒生指数": "hkHSI",
    "恒生科技": "hkHSTECH",
}
# 新浪全球指数（int_ 前缀）
GLOBAL_EQ_SINA = [
    ("日经225", "int_nikkei"),
    ("英国富时100", "int_ftse"),
]
# 新浪全球商品/汇率
SINA_GLOBAL = [
    ("美元指数", "DINIW", "fx"),
    ("布伦特原油", "hf_OIL", "hf"),
    ("纽约黄金", "hf_GC", "hf"),
]


def _all_instruments() -> dict:
    merged: dict = {}
    for group in (US_INDICES, US_SECTORS, US_MEGA, US_STYLE, US_BONDS):
        merged.update(group)
    return merged


# 英文/简写别名 → 注册表中的中文名（方便 LLM 用 sp500 / nasdaq / dow / ndx 等）
_ALIASES = {
    "sp500": "标普500", "s&p500": "标普500", "spx": "标普500", "inx": "标普500",
    "nasdaq": "纳斯达克综指", "ixic": "纳斯达克综指", "comp": "纳斯达克综指",
    "dow": "道琼斯", "dji": "道琼斯", "djia": "道琼斯",
    "ndx": "纳斯达克100", "nasdaq100": "纳斯达克100",
    "rut": "罗素2000", "russell": "罗素2000",
    "vix": "VIX",
}


def _resolve(code: str) -> tuple[str, Optional[str]]:
    """把用户输入解析为 (显示名, 新浪K线代码)。

    支持：中文名（如「标普500」）、英文别名（sp500/nasdaq/dow/ndx）、
    腾讯代码（usAAPL）、新浪代码（.INX）、以及裸代码（AAPL / XLK）。
    """
    c = (code or "").strip()
    low = c.lower()
    instruments = _all_instruments()
    if low in _ALIASES:
        disp = _ALIASES[low]
        return disp, instruments[disp][1]
    for disp, (tc, sina) in instruments.items():
        if low == disp.lower() or low == tc.lower() or (sina and low == sina.lower()):
            return disp, sina
    if low.startswith("us"):
        return c[2:].upper(), c[2:].upper()
    return c.lstrip(".").upper(), c.upper()


# ──────────────────────────────────────────────────────────────────────────────
# 时间：美东交易日
# ──────────────────────────────────────────────────────────────────────────────
def _et_now() -> datetime:
    return datetime.now(US_EASTERN) if US_EASTERN else datetime.now()


def _prev_weekday(d):
    while d.weekday() >= 5:  # 周六日回退
        d -= timedelta(days=1)
    return d


def us_trade_date(fmt: str = "%Y-%m-%d") -> str:
    """返回最近一个美股交易日。优先取腾讯 usINX 的行情时间戳（ET），否则按美东工作日推算。"""
    q = _tencent_quotes(["usINX"])
    f = q.get("usINX")
    if f and len(f) > 30 and f[30]:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", f[30])
        if m:
            return datetime.strptime(m.group(0), "%Y-%m-%d").strftime(fmt)

    now = _et_now()
    d = now.date()
    if now.hour < 16:  # 收盘前，最近一个「完成」的交易日是昨天
        d -= timedelta(days=1)
    d = _prev_weekday(d)
    return d.strftime(fmt)


# ──────────────────────────────────────────────────────────────────────────────
# 通用 HTTP / 格式化工具
# ──────────────────────────────────────────────────────────────────────────────
def _http_get(url: str, params: Optional[dict] = None, retries: int = 3,
              timeout: int = HTTP_TIMEOUT, encoding: Optional[str] = None,
              headers: Optional[dict] = None):
    """带重试的 GET，失败返回 None。"""
    last_err = "unknown"
    for attempt in range(retries):
        try:
            resp = SESSION.get(url, params=params, timeout=timeout, headers=headers)
            if resp.status_code == 200:
                if encoding:
                    resp.encoding = encoding
                return resp
            last_err = f"HTTP {resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)[:120]
        time.sleep(1.2 * (attempt + 1))
    return None


def _to_float(value, default=None):
    try:
        f = float(value)
        if math.isnan(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _pct(value) -> str:
    f = _to_float(value)
    return "—" if f is None else f"{f:+.2f}%"


# ──────────────────────────────────────────────────────────────────────────────
# 腾讯行情解析（美股 us 前缀）
# ──────────────────────────────────────────────────────────────────────────────
def _tencent_quotes(codes: list[str]) -> dict[str, list[str]]:
    """批量获取腾讯行情快照，返回 {code: fields[]}。"""
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    resp = _http_get(url, encoding="gbk", retries=3)
    if resp is None:
        return {}
    result: dict[str, list[str]] = {}
    for chunk in resp.text.split(";"):
        chunk = chunk.strip()
        if not chunk.startswith("v_"):
            continue
        key, _, payload = chunk.partition("=")
        code = key[2:]
        fields = payload.strip().strip('"').split("~")
        if len(fields) > 35:
            result[code] = fields
    return result


def _tencent_field(fields: list[str], idx: int):
    return _to_float(fields[idx]) if len(fields) > idx else None


def _quote_line(name: str, fields: list[str], show_amount: bool = False) -> str:
    """把腾讯字段格式化为一行摘要。"""
    price = _tencent_field(fields, 3)
    change = _tencent_field(fields, 31)
    pct = _tencent_field(fields, 32)
    high = _tencent_field(fields, 33)
    low = _tencent_field(fields, 34)
    amount = _tencent_field(fields, 37)  # 美元
    high_low = ""
    if high is not None and low is not None and price:
        high_low = f"，振幅{(high - low) / price * 100:.2f}%"
    amount_text = f"，成交额{amount / 1e8:,.1f}亿美元" if (show_amount and amount) else ""
    pct_text = f"{pct:+.2f}%" if pct is not None else "—"
    chg_text = f"{change:+.2f}" if change is not None else "—"
    return (
        f"{name}: {price if price is not None else '—'}"
        f"（{chg_text}，{pct_text}）"
        f"{amount_text}{high_low}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 新浪美股日 K 线（腾讯美股K线仅返回 2 根，故改用新浪）
# ──────────────────────────────────────────────────────────────────────────────
_SINA_KLINE_CACHE: dict = {}
SINA_KLINE_TTL = int(os.environ.get("SINA_KLINE_TTL", "1800") or "1800")


def _sina_us_kline(symbol: str, count: int = 60) -> list[list]:
    """获取新浪美股日 K，返回 [[date, open, close, high, low, volume], ...]。"""
    key = (symbol, count)
    now = time.time()
    hit = _SINA_KLINE_CACHE.get(key)
    if hit and now - hit[0] < SINA_KLINE_TTL:
        return hit[1]

    url = ("https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/"
           f"var/US_MinKService.getDailyK?symbol={symbol}&___qn=3")
    resp = _http_get(url, retries=3, headers={"Referer": "https://finance.sina.com.cn/"})
    if resp is None:
        return []
    m = re.search(r"var\((\[.*\])\)", resp.text, re.DOTALL)
    if not m:
        return []
    try:
        raw = json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return []
    bars = [[x.get("d"), x.get("o"), x.get("c"), x.get("h"), x.get("l"), x.get("v")]
            for x in raw if x.get("d")]
    bars = bars[-count:]
    if bars:
        _SINA_KLINE_CACHE[key] = (now, bars)
    return bars


def _ma(closes: list[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


# ══════════════════════════════════════════════════════════════════════════════
# 工具 1：美股大盘指数总览
# ══════════════════════════════════════════════════════════════════════════════
@tool
def get_market_overview() -> str:
    """获取美股主要指数收盘快照（标普500、纳斯达克综指、道琼斯、纳斯达克100、罗素2000、VIX恐慌指数）。
    适合每天美股盘后复盘的第一步，用来判断大盘温度与风险偏好。"""
    quotes = _tencent_quotes([tc for tc, _ in US_INDICES.values()])
    if not quotes:
        return "【数据获取失败】腾讯行情接口暂时不可用，请稍后重试或改用其他数据源。"

    lines = [f"# 美股收盘总览（{us_trade_date()}）", ""]
    for name, (code, _) in US_INDICES.items():
        fields = quotes.get(code)
        if not fields:
            continue
        if name == "VIX":
            vix = _tencent_field(fields, 3)
            lines.append(f"- VIX恐慌指数: {vix if vix is not None else '—'}"
                         f"（15-20 为常态区间，>20 偏谨慎，>30 恐慌）")
        else:
            lines.append("- " + _quote_line(name, fields, show_amount=False))
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 工具 2：指数 / 个股 K 线 + 均线结构
# ══════════════════════════════════════════════════════════════════════════════
@tool
def get_index_kline(code: str = "sp500", period: str = "day", count: int = 60) -> str:
    """获取美股指数或个股/ETF 的日 K 线，并计算均线、区间高低点、近 5 日量能变化等结构指标。

    Args:
        code: 标的代码。可填中文名或代码，如「标普500」/sp500/ush000、.INX、AAPL、NVDA、XLK。
              常用指数：标普500(.INX) / 纳斯达克综指(.IXIC) / 道琼斯(.DJI) / 纳斯达克100(.NDX)。
        period: K 线周期，目前美股仅支持 day，默认 day。
        count: 取最近多少根 K 线，默认 60。
    """
    _disp, sina = _resolve(code)
    if not sina:
        return f"【数据获取失败】{code} 无日 K 数据源（如 VIX 仅提供快照，无 K 线）。"
    count = max(10, min(int(count), 500))
    bars = _sina_us_kline(sina, count)
    if not bars:
        return f"【数据获取失败】未能获取 {code}（新浪代码 {sina}）的 K 线，请检查代码是否正确。"

    closes = [_to_float(b[2]) for b in bars if _to_float(b[2]) is not None]
    volumes = [_to_float(b[5]) for b in bars if len(b) > 5 and _to_float(b[5]) is not None]
    latest = bars[-1]

    ma5, ma10, ma20, ma60 = (_ma(closes, 5), _ma(closes, 10), _ma(closes, 20), _ma(closes, 60))
    recent = bars[-20:]
    high20 = max((_to_float(b[3]) for b in recent if _to_float(b[3]) is not None), default=None)
    low20 = min((_to_float(b[4]) for b in recent if _to_float(b[4]) is not None), default=None)

    vol_note = "—"
    if len(volumes) >= 6:
        avg5 = sum(volumes[-5:]) / 5
        prev5 = sum(volumes[-6:-1]) / 5
        if prev5:
            vol_note = f"近5日均量较前5日 {(avg5 / prev5 - 1) * 100:+.1f}%"

    def _chg(n):
        if len(closes) > n and closes[-1 - n]:
            return f"{(closes[-1] / closes[-1 - n] - 1) * 100:+.2f}%"
        return "—"

    ma_text = " / ".join(
        f"{label}={val:.2f}" if val else f"{label}=—"
        for label, val in (("MA5", ma5), ("MA10", ma10), ("MA20", ma20), ("MA60", ma60))
    )

    lines = [
        f"# {code} K线结构（{period}，共{len(bars)}根，数据截至 {latest[0]}）",
        "",
        f"- 最新收盘：{latest[2]}（开{latest[1]} 高{latest[3]} 低{latest[4]}）",
        f"- 均线：{ma_text}",
        f"- 近20日区间：高点 {high20} / 低点 {low20}",
        f"- 阶段涨跌：近5日 {_chg(5)} / 近20日 {_chg(20)}",
        f"- 量能：{vol_note}",
        "",
        "最近 10 根 K 线（日期 开 收 高 低 量）：",
    ]
    for b in bars[-10:]:
        lines.append("  " + "  ".join(str(x) for x in b[:6]))
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 工具 3：生成 K 线图（近三个月），用于报告/邮件直观展示
# ══════════════════════════════════════════════════════════════════════════════
def _make_kline_chart(symbol: str, name: str, days: int, out_dir: Path):
    """用 matplotlib 画一张蜡烛图（价格 + 成交量 + MA5/MA20），返回 (PNG 路径, K线根数)。"""
    bars = _sina_us_kline(symbol, days)
    if len(bars) < 5:
        return None

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    dates = [b[0] for b in bars]
    opens = [_to_float(b[1], 0) or 0 for b in bars]
    closes = [_to_float(b[2], 0) or 0 for b in bars]
    highs = [_to_float(b[3], 0) or 0 for b in bars]
    lows = [_to_float(b[4], 0) or 0 for b in bars]
    vols = [_to_float(b[5], 0) or 0 for b in bars]
    x = list(range(len(bars)))

    def ma(vals, n):
        out = []
        for i in range(len(vals)):
            out.append(sum(vals[i - n + 1:i + 1]) / n if i >= n - 1 else None)
        return out

    up_color, down_color = "#2e7d32", "#d32f2f"  # 美股绿涨红跌

    fig, (ax, axv) = plt.subplots(
        2, 1, figsize=(9, 5.2), sharex=True,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.06},
    )

    for i, (o, c, h, l) in enumerate(zip(opens, closes, highs, lows)):
        color = up_color if c >= o else down_color
        ax.vlines(i, l, h, color=color, linewidth=0.9, zorder=2)
        body_low = min(o, c)
        body_h = abs(c - o) or (max(h - l, 0.01) * 0.01)
        ax.add_patch(Rectangle((i - 0.32, body_low), 0.64, body_h,
                               facecolor=color, edgecolor=color, zorder=3))

    for n, col in ((5, "#ff9800"), (20, "#1e88e5")):
        series = ma(closes, n)
        ax.plot(x, series, color=col, linewidth=1.1, label=f"MA{n}", zorder=4)

    ax.set_title(f"{name} 日K线（近 {len(bars)} 个交易日）", fontsize=13, fontweight="bold")
    ax.set_ylabel("点位", fontsize=10)
    ax.grid(True, linestyle="--", alpha=0.25)
    ax.legend(loc="upper left", fontsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    vol_colors = [up_color if c >= o else down_color for o, c in zip(opens, closes)]
    axv.bar(x, vols, color=vol_colors, width=0.7, alpha=0.75)
    axv.set_ylabel("成交量", fontsize=9)
    axv.grid(True, linestyle="--", alpha=0.2)
    for spine in ("top", "right"):
        axv.spines[spine].set_visible(False)

    step = max(1, len(dates) // 8)
    ticks = x[::step]
    axv.set_xticks(ticks)
    axv.set_xticklabels([dates[i][5:] for i in ticks], fontsize=8, rotation=0)

    out_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^0-9A-Za-z_-]", "_", symbol.lstrip("."))
    stamp = re.sub(r"\D", "", dates[-1]) or datetime.now().strftime("%Y%m%d")
    path = out_dir / f"{safe}_{stamp}.png"
    fig.savefig(path, dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path, len(bars)


@tool
def generate_index_charts(codes: str = "", days: int = 60) -> str:
    """生成美股主要指数的日 K 线图（默认近 60 个交易日≈三个月），并把可直接插入报告的 Markdown 图片行返回。
    用于在复盘报告第一节后面直观展示大盘走势。

    Args:
        codes: 逗号分隔的指数代码/名称，例如 "sp500,nasdaq" 或 ".INX,.DJI"；留空默认生成
               标普500、纳斯达克综指、道琼斯、纳斯达克100。
        days: 取最近多少个交易日，默认 60（约三个月），范围 20-120。
    """
    days = max(20, min(int(days), 120))
    default = ["sp500", "nasdaq", "dow", "ndx"]
    code_list = [c.strip() for c in codes.split(",") if c.strip()] or default

    chart_dir = REPORT_DIR / "charts"
    lines: list[str] = []
    for code in code_list:
        disp, sina = _resolve(code)
        if not sina:
            lines.append(f"（{disp} 无 K 线数据源，未生成图表）")
            continue
        try:
            result = _make_kline_chart(sina, disp, days, chart_dir)
        except Exception as exc:  # noqa: BLE001
            lines.append(f"（{disp} 图表生成失败：{exc}）")
            continue
        if result:
            path, n = result
            lines.append(f"![{disp}近{n}日K线]({path.resolve().as_posix()})")
        else:
            lines.append(f"（{disp} 数据不足，未生成图表）")

    if not lines:
        return "【生成失败】未能生成任何指数 K 线图。"
    return (
        f"已生成 {len(lines)} 张指数 K 线图（近 {days} 个交易日）。"
        "请把下面每一行 **原样** 插入报告第一节（大盘表格）之后：\n\n"
        + "\n\n".join(lines)
    )


# ══════════════════════════════════════════════════════════════════════════════
# 工具 4：行业板块轮动（11 大 SPDR 行业 ETF）
# ══════════════════════════════════════════════════════════════════════════════
_SECTOR_CACHE: dict = {}
SECTOR_CACHE_TTL = int(os.environ.get("SECTOR_CACHE_TTL", "600") or "600")


@tool
def get_sector_performance() -> str:
    """获取美股 11 大 SPDR 行业 ETF 当日表现（科技/金融/能源/医疗/可选消费/必需消费/工业/
    原材料/公用事业/房地产/通信服务），按涨跌幅排序，用于判断当日行业轮动与主线（进攻/防御）。
    这是美股复盘识别风格切换的核心工具。"""
    now = time.time()
    hit = _SECTOR_CACHE.get("sectors")
    if hit and now - hit[0] < SECTOR_CACHE_TTL:
        rows = hit[1]
    else:
        codes = [tc for tc, _ in US_SECTORS.values()]
        quotes = _tencent_quotes(codes)
        if not quotes:
            return "【数据获取失败】未能获取行业 ETF 行情，接口可能临时限流，请重试。"
        rows = []
        for name, (code, _) in US_SECTORS.items():
            f = quotes.get(code)
            if not f:
                continue
            rows.append({
                "name": name, "code": code,
                "price": _tencent_field(f, 3),
                "pct": _tencent_field(f, 32),
            })
        if not rows:
            return "【数据获取失败】未能获取行业 ETF 行情，接口可能临时限流，请重试。"
        rows.sort(key=lambda r: (r["pct"] if r["pct"] is not None else -1e9), reverse=True)
        _SECTOR_CACHE["sectors"] = (now, rows)

    ups = sum(1 for r in rows if (r["pct"] or 0) > 0)
    downs = sum(1 for r in rows if (r["pct"] or 0) < 0)
    lines = [
        f"# 行业板块轮动（11 大 SPDR 行业 ETF，{us_trade_date()}）",
        "",
        f"> 上涨 {ups} / 下跌 {downs}（共 {len(rows)} 个行业）",
        "",
        "| 行业 | ETF | 现价 | 涨跌幅 |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['name']} | {r['code']} | {r['price'] if r['price'] is not None else '—'} | {_pct(r['pct'])} |")
    if rows:
        def _fmt_group(group):
            return "、".join("{}（{}）".format(r["name"], _pct(r["pct"])) for r in group)

        lines += [
            "",
            "**领涨行业**：" + _fmt_group(rows[:3]),
            "**领跌行业**：" + _fmt_group(rows[-3:][::-1]),
        ]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 工具 5：市场内部结构（龙头 / 风格轮动 / 风险偏好）
# ══════════════════════════════════════════════════════════════════════════════
@tool
def get_market_internals() -> str:
    """获取美股市场内部结构：科技七巨头等龙头股表现、大小盘/成长/等权风格强弱、
    以及 VIX 隐含的风险偏好。用于判断「上涨是普涨还是少数权重股拉动」以及风格切换。"""
    mega_codes = [tc for tc, _ in US_MEGA.values()]
    style_codes = [tc for tc, _ in US_STYLE.values()]
    quotes = _tencent_quotes(mega_codes + style_codes + ["usVIX"])
    if not quotes:
        return "【数据获取失败】未能获取行情，接口可能临时限流，请重试。"

    def pct_of(code) -> Optional[float]:
        f = quotes.get(code)
        return _tencent_field(f, 32) if f else None

    lines = ["# 市场内部结构", ""]

    # 龙头股
    lines += ["## 科技七巨头（Magnificent 7）", "",
              "| 股票 | 代码 | 现价 | 涨跌幅 |", "|---|---|---|---|"]
    mega_pcts = []
    for name, (code, _) in US_MEGA.items():
        f = quotes.get(code)
        if not f:
            continue
        pct = _tencent_field(f, 32)
        if pct is not None:
            mega_pcts.append(pct)
        lines.append(f"| {name} | {code} | {_tencent_field(f, 3)} | {_pct(pct)} |")
    if mega_pcts:
        avg = sum(mega_pcts) / len(mega_pcts)
        up = sum(1 for p in mega_pcts if p > 0)
        lines.append(f"\n七巨头平均 {avg:+.2f}%，{up}/{len(mega_pcts)} 上涨。")

    # 风格
    lines += ["", "## 风格与大盘代理", "",
              "| 指标 | 现价 | 涨跌幅 |", "|---|---|---|"]
    style_pct: dict[str, float] = {}
    for name, (code, _) in US_STYLE.items():
        f = quotes.get(code)
        if not f:
            continue
        pct = _tencent_field(f, 32)
        style_pct[name] = pct if pct is not None else 0.0
        lines.append(f"| {name} | {_tencent_field(f, 3)} | {_pct(pct)} |")

    # 风险偏好判读
    def diff(a_key, b_key):
        if a_key in style_pct and b_key in style_pct:
            return style_pct[a_key] - style_pct[b_key]
        return None

    notes = []
    small_big = diff("罗素2000(小盘)", "标普500(大盘)")
    if small_big is not None:
        notes.append(f"小盘 vs 大盘：小盘{small_big:+.2f}pct → " +
                     ("小盘相对占优（风险偏好回升）" if small_big > 0 else "大盘相对占优（资金抱团权重）"))
    eq_cap = diff("标普500等权", "标普500(大盘)")
    if eq_cap is not None:
        notes.append(f"等权 vs 市值加权：等权{eq_cap:+.2f}pct → " +
                     ("普涨、宽度好" if eq_cap > 0 else "少数权重股拉动、宽度偏弱"))
    vix_f = quotes.get("usVIX")
    vix = _tencent_field(vix_f, 3) if vix_f else None
    if vix is not None:
        mood = ("低波动、风险偏好高" if vix < 15 else
                "常态波动" if vix < 20 else
                "波动偏大、偏谨慎" if vix < 30 else "恐慌区间")
        notes.append(f"VIX {vix:.2f} → {mood}")

    if notes:
        lines += ["", "## 风险偏好判读", ""]
        lines += [f"- {n}" for n in notes]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 工具 6：外围市场与宏观（欧亚股市 / 美元 / 商品 / 美债）
# ══════════════════════════════════════════════════════════════════════════════
def _sina_quote_map(codes: list[str]) -> dict[str, list[str]]:
    url = "https://hq.sinajs.cn/list=" + ",".join(codes)
    resp = _http_get(url, retries=2, encoding="gbk",
                     headers={"Referer": "https://finance.sina.com.cn/"})
    if resp is None:
        return {}
    data: dict[str, list[str]] = {}
    for line in resp.text.splitlines():
        m = re.match(r'var hq_str_(\w+)="(.*)";', line.strip())
        if m:
            data[m.group(1)] = m.group(2).split(",")
    return data


@tool
def get_global_markets() -> str:
    """获取美股外围环境：亚太/欧洲主要股指（恒生、恒生科技、日经、英国富时）、
    美元指数、布伦特原油、纽约黄金，以及美债 ETF（10 年期与 20 年期，作为利率方向代理）。
    用于研判影响美股的宏观与跨市场因素。"""
    lines = ["# 外围市场与宏观", ""]

    # 亚太 / 欧洲股指
    tq = _tencent_quotes(list(GLOBAL_EQ_TENCENT.values()))
    lines.append("## 亚太 / 欧洲股市")
    lines.append("")
    got = False
    for name, code in GLOBAL_EQ_TENCENT.items():
        f = tq.get(code)
        if f:
            lines.append("- " + _quote_line(name, f))
            got = True
    sg = _sina_quote_map([c for _, c in GLOBAL_EQ_SINA])
    for name, code in GLOBAL_EQ_SINA:
        f = sg.get(code)
        if f and len(f) >= 4:
            price, chg, pct = _to_float(f[1]), _to_float(f[2]), _to_float(f[3])
            lines.append(f"- {name}: {price}（{chg:+.2f}，{pct:+.2f}%）" if price is not None else f"- {name}: —")
            got = True
    if not got:
        lines.append("- （暂无数据）")

    # 美元 / 商品
    lines += ["", "## 美元与商品", ""]
    sdata = _sina_quote_map([c for _, c, _ in SINA_GLOBAL])
    for name, code, kind in SINA_GLOBAL:
        f = sdata.get(code)
        if not f or len(f) < 8:
            continue
        if kind == "fx":       # time,price,...,prev,... → price=f[1], prev=f[3]
            price, prev = _to_float(f[1]), _to_float(f[3])
        else:                  # hf: price=f[0], ..., prev=f[7]
            price, prev = _to_float(f[0]), _to_float(f[7])
        if price is None:
            continue
        pct = (price / prev - 1) * 100 if (prev and price) else None
        lines.append(f"- {name}: {price}（{pct:+.2f}%）" if pct is not None else f"- {name}: {price}")

    # 美债（利率代理）
    lines += ["", "## 美债（利率方向代理）", ""]
    bond_q = _tencent_quotes([tc for tc, _ in US_BONDS.values()])
    for name, (code, _) in US_BONDS.items():
        f = bond_q.get(code)
        if f:
            lines.append("- " + _quote_line(name, f))
    lines.append("")
    lines.append("> 说明：无免费 10 年期美债收益率直连数据，以 TLT/IEF 价格方向代理利率——"
                 "债价跌=收益率升（对成长股偏空），债价涨=收益率降。")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 工具 7：7x24 财经资讯
# ══════════════════════════════════════════════════════════════════════════════
@tool
def get_market_news(count: int = 20) -> str:
    """获取最新 7x24 全球财经快讯（宏观、政策、产业、公司要闻，含美股与美联储动态），
    用于收集当日消息面。

    Args:
        count: 返回条数，默认 20，最多 50。
    """
    count = max(5, min(int(count), 50))
    params = {
        "client": "web", "biz": "web_724", "fastColumn": "102",
        "sortEnd": "", "pageSize": str(count), "req_trace": str(int(time.time() * 1000)),
    }
    resp = _http_get(EM_NEWS_URL, params=params, retries=3)
    if resp is None:
        return "【数据获取失败】未能获取财经快讯，接口可能临时限流，请重试。"
    try:
        news = (resp.json().get("data") or {}).get("fastNewsList") or []
    except Exception:  # noqa: BLE001
        return "【数据解析失败】快讯返回格式异常。"
    if not news:
        return "暂无最新快讯。"

    lines = ["# 最新财经快讯", ""]
    for item in news:
        title = item.get("title") or item.get("summary", "")[:40]
        summary = item.get("summary", "")
        show_time = item.get("showTime", "")
        lines.append(f"- [{show_time}] {title}")
        if summary and summary != title:
            lines.append(f"    {summary}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 工具 8：必应网页搜索
# ══════════════════════════════════════════════════════════════════════════════
@tool
def web_search(query: str, count: int = 8) -> str:
    """使用必应搜索互联网，返回标题、摘要与链接，用于补充新闻、财报、美联储动态等事件。

    Args:
        query: 搜索关键词，例如「美股 今日 复盘 纳指 科技股 下跌原因」。
        count: 返回结果条数，默认 8。
    """
    count = max(3, min(int(count), 15))
    resp = _http_get("https://cn.bing.com/search", params={"q": query, "count": count}, retries=3)
    if resp is None:
        return "【搜索失败】必应暂时不可用，请稍后重试或换用财经快讯工具。"
    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select("li.b_algo")
    if not items:
        return f"未搜索到「{query}」的相关结果。"

    lines = [f"# 搜索：{query}", ""]
    for it in items[:count]:
        a = it.select_one("h2 a")
        p = it.select_one("p")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href", "")
        snippet = p.get_text(strip=True) if p else ""
        lines.append(f"- {title}")
        lines.append(f"  链接：{href}")
        if snippet:
            lines.append(f"  摘要：{snippet}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 工具 9：网页正文抓取
# ══════════════════════════════════════════════════════════════════════════════
@tool
def fetch_webpage(url: str, max_chars: int = 4000) -> str:
    """抓取指定网页的标题与正文文本，用于读取新闻、研报、公告等具体内容。

    Args:
        url: 完整网址。
        max_chars: 正文最大字符数，默认 4000。
    """
    max_chars = max(500, min(int(max_chars), 12000))
    resp = _http_get(url, retries=2, encoding=None)
    if resp is None:
        return f"【抓取失败】无法访问 {url}。"
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else url
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
        tag.decompose()

    selectors = ["article", ".article-content", ".newsContent", "#ContentBody",
                 ".detail-text", ".report-content", "div[class*='content']", "main"]
    content = ""
    for sel in selectors:
        elems = soup.select(sel)
        if elems:
            content = "\n".join(e.get_text(strip=True, separator="\n") for e in elems)
            if len(content) >= 100:
                break
    if len(content) < 50:
        content = soup.get_text(separator="\n", strip=True)
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    if len(content) > max_chars:
        content = content[:max_chars] + "\n…（已截断）"
    return f"# {title}\n\n{content}"


# ══════════════════════════════════════════════════════════════════════════════
# 工具 10：保存复盘文件
# ══════════════════════════════════════════════════════════════════════════════
@tool
def save_report_file(filename: str, content: str = "", source_file: str = "") -> str:
    """将复盘内容保存为 Markdown 文件到 reports/ 目录，便于归档与二次编辑。

    Args:
        filename: 文件名（不含路径），例如「美股复盘_20261009.md」。
        content: Markdown 正文内容。若留空则从 source_file 读取。
        source_file: 已有的 Markdown 文件路径，当 content 为空时从此文件读取并归档。
    """
    if not content.strip() and source_file.strip():
        src = Path(source_file.strip())
        if not src.is_absolute():
            src = (Path.cwd() / src).resolve()
        if not src.exists():
            return f"【保存失败】找不到 source_file：{src}"
        content = src.read_text(encoding="utf-8")
    if not content.strip():
        return "【保存失败】内容为空（content 与 source_file 至少提供一个）。"

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[\\/:*?\"<>|]", "_", filename).strip() or "report.md"
    if not safe.endswith(".md"):
        safe += ".md"
    path = REPORT_DIR / safe
    path.write_text(content, encoding="utf-8")
    return f"已保存：{path.resolve()}"


# ══════════════════════════════════════════════════════════════════════════════
# 工具 11：发送复盘邮件
# ══════════════════════════════════════════════════════════════════════════════
def _markdown_to_html(md: str) -> str:
    """Markdown → HTML（邮件渲染用），支持标题、表格、图片、列表、引用、粗体、链接。"""
    lines = md.split("\n")
    html: list[str] = []
    in_list = False
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].rstrip()
        if line.lstrip().startswith("|") and i + 1 < n and \
                re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]) and "-" in lines[i + 1]:
            _close_list(html, in_list); in_list = False
            table_html, i = _render_table(lines, i)
            html.append(table_html)
            continue
        if line.startswith("### "):
            _close_list(html, in_list); in_list = False
            html.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            _close_list(html, in_list); in_list = False
            html.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            _close_list(html, in_list); in_list = False
            html.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.strip() in ("---", "***"):
            _close_list(html, in_list); in_list = False
            html.append("<hr/>")
        elif re.match(r"^\s*[-*] ", line):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_inline(re.sub(r'^\s*[-*] ', '', line))}</li>")
        elif re.match(r"^\s*\d+\. ", line):
            if not in_list:
                html.append("<ol>")
                in_list = True
            html.append(f"<li>{_inline(re.sub(r'^\s*\d+\. ', '', line))}</li>")
        elif line.startswith(">"):
            _close_list(html, in_list); in_list = False
            html.append(f"<blockquote>{_inline(line.lstrip('> '))}</blockquote>")
        elif line.strip() == "":
            _close_list(html, in_list); in_list = False
        else:
            _close_list(html, in_list); in_list = False
            html.append(f"<p>{_inline(line)}</p>")
        i += 1
    _close_list(html, in_list)
    return "\n".join(html)


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _render_table(lines: list[str], start: int) -> tuple[str, int]:
    """把连续的 Markdown 表格行渲染为带样式的 <table>，返回 (html, 下一行索引)。"""
    header = _split_row(lines[start])
    i = start + 2
    body: list[list[str]] = []
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        body.append(_split_row(lines[i]))
        i += 1

    th_style = ("padding:7px 9px;background:#eef2ff;color:#3f51b5;font-weight:600;"
                "border:1px solid #dfe3ee;text-align:left;white-space:nowrap")
    td_style = "padding:7px 9px;border:1px solid #e6e9f0;vertical-align:top"
    head = "".join(f'<th style="{th_style}">{_inline(c)}</th>' for c in header)
    rows = []
    for row in body:
        cells = "".join(f'<td style="{td_style}">{_inline(c)}</td>' for c in row)
        rows.append(f"<tr>{cells}</tr>")
    table = (
        '<table style="width:100%;border-collapse:collapse;font-size:13px;'
        'margin:10px 0;color:#333">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )
    return table, i


def _close_list(html: list[str], in_list: bool):
    if in_list:
        html.append("</ul>")


def _img_tag(alt: str, src: str) -> str:
    """图片：本地文件转 base64 内联（邮件里必然显示），远程链接直接引用。"""
    src = src.strip()
    style = "max-width:100%;height:auto;border:1px solid #e6e9f0;border-radius:6px;margin:8px 0"
    if src.lower().startswith(("http://", "https://")):
        return f'<img src="{src}" alt="{alt}" style="{style}">'
    path = Path(src)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        return f'<span style="color:#c0392b">[图片缺失: {alt or src}]</span>'
    ext = path.suffix.lower().lstrip(".")
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext or 'png'}"
    try:
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    except Exception:  # noqa: BLE001
        return f'<span style="color:#c0392b">[图片读取失败: {alt or src}]</span>'
    return f'<img src="data:{mime};base64,{b64}" alt="{alt}" style="{style}">'


def _inline(text: str) -> str:
    text = re.sub(r"!\[(.*?)\]\((.+?)\)", lambda m: _img_tag(m.group(1), m.group(2)), text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
    return text


def _render_email_html(title: str, body_html: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""\
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:12px;background:#f2f4f7;font-family:-apple-system,
 BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif">
<div style="max-width:680px;margin:0 auto;background:#fff;border-radius:10px;
 overflow:hidden;box-shadow:0 1px 6px rgba(0,0,0,0.08)">
 <div style="background:linear-gradient(135deg,#1f6feb,#6f42c1);padding:22px 20px;color:#fff">
  <h1 style="margin:0;font-size:20px">{title}</h1>
  <p style="margin:6px 0 0;font-size:13px;opacity:.85">生成时间：{now}</p>
 </div>
 <div style="padding:20px;color:#333;font-size:14px;line-height:1.75">
  {body_html}
 </div>
 <div style="text-align:center;padding:14px;color:#aaa;font-size:11px;border-top:1px solid #eee">
  本报告由 AI Agent 自动生成，仅供研究参考，不构成投资建议
 </div>
</div>
</body></html>"""


@tool
def send_email_report(subject: str, content: str = "", to_email: str = "",
                      source_file: str = "") -> str:
    """将复盘报告（Markdown 格式）渲染为 HTML 邮件并发送给客户；若未配置 SMTP 则保存为 HTML 文件。

    Args:
        subject: 邮件主题，例如「美股复盘 | 2026-10-09 大盘回顾与策略」。
        content: 复盘报告正文（Markdown）。若留空则从 source_file 读取。
        to_email: 收件邮箱，留空则使用环境变量 REPORT_TO_EMAIL。
        source_file: 报告文件路径（Markdown），当 content 为空时从此文件读取，
                     推荐先 save_report_file 再用它发送，避免超长文本通过参数传递。
    """
    if not content.strip() and source_file.strip():
        path = Path(source_file.strip())
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        if not path.exists():
            return f"【发送失败】找不到 source_file：{path}"
        content = path.read_text(encoding="utf-8")
    if not content.strip():
        return "【发送失败】邮件正文为空（content 与 source_file 至少提供一个）。"

    recipient = (to_email or os.environ.get("REPORT_TO_EMAIL", "") or REPORT_TO_EMAIL).strip()
    body_html = _markdown_to_html(content)
    html = _render_email_html(subject, body_html)

    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS]):
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d")
        path = REPORT_DIR / f"美股复盘邮件_{stamp}.html"
        path.write_text(html, encoding="utf-8")
        return (f"未配置 SMTP，已改为保存 HTML 文件：{path.resolve()}。"
                f"如需自动发送，请在 .env 配置 SMTP_HOST/USER/PASS。")

    if not recipient or "@" not in recipient:
        return "【发送失败】收件邮箱为空或格式不正确，请检查 to_email 或 REPORT_TO_EMAIL。"

    msg = MIMEMultipart("alternative")
    msg["From"] = FROM_EMAIL
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(content, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    server = None
    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=HTTP_TIMEOUT)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=HTTP_TIMEOUT)
            server.ehlo()
            server.starttls()
            server.ehlo()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(FROM_EMAIL, [recipient], msg.as_string())
        return f"邮件已发送至 {recipient}。"
    except Exception as exc:  # noqa: BLE001
        return f"【邮件发送失败】{exc}"
    finally:
        if server:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                pass


# 供 agents.py 统一引用
ALL_TOOLS = [
    get_market_overview,
    get_index_kline,
    generate_index_charts,
    get_sector_performance,
    get_market_internals,
    get_global_markets,
    get_market_news,
    web_search,
    fetch_webpage,
    save_report_file,
    send_email_report,
]


if __name__ == "__main__":
    # 手动冒烟测试：python tools.py
    print(get_market_overview.run())
    print()
    print(get_index_kline.run(code="sp500", count=30))
    print()
    print(get_sector_performance.run())
    print()
    print(get_market_internals.run())
    print()
    print(get_global_markets.run())
