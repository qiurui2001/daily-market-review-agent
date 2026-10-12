# -*- coding: utf-8 -*-
"""
crypto_tools.py —— 加密货币(BTC/ETH)复盘数据工具
=================================================

加密市场 7×24 小时交易、以永续合约为流动性中心，因此复盘维度与美股不同：

- 价格/量能：现货与永续日 K、均线结构、阶段涨跌、实现波动率；
- 衍生品（加密特有、最重要）：**资金费率(funding)**、**未平仓合约(OI)**、
  **多空比(long/short ratio)**、**强平/爆仓(liquidation)**、**基差(basis)**；
- 市场结构：总市值、**BTC/ETH 主导率(dominance)**、**ETH/BTC 汇率**（判断轮动）；
- 情绪：恐慌与贪婪指数(Fear & Greed)；
- 消息面：网页搜索。

数据源（均无需 API Key，且在本机网络中可达）：
- Gate.io 现货/永续（`api.gateio.ws`）—— 价格、量、资金费率、持仓、多空比、爆仓；
- Binance 公共数据镜像（`data-api.binance.vision`）—— 现货 K 线兜底；
- CoinLore（`api.coinlore.net`）—— 全球总市值/主导率；
- Alternative.me（`api.alternative.me/fng/`）—— 恐贪指数。

所有数据仅供研究参考，不构成投资建议。
"""

from __future__ import annotations

import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from crewai.tools import tool

from tools import REPORT_DIR, _http_get, _tencent_field, _tencent_quotes, _to_float

# ──────────────────────────────────────────────────────────────────────────────
# 常量与数据源
# ──────────────────────────────────────────────────────────────────────────────
GATE_API = "https://api.gateio.ws/api/v4"
BINANCE_DATA = "https://data-api.binance.vision/api/v3"
COINLORE_API = "https://api.coinlore.net/api"
FNG_API = "https://api.alternative.me/fng/"

COINS = {
    "BTC": {"name": "比特币", "gate": "BTC_USDT", "binance": "BTCUSDT", "lore_id": "90"},
    "ETH": {"name": "以太坊", "gate": "ETH_USDT", "binance": "ETHUSDT", "lore_id": "80"},
}

# 美国上市的现货 ETF（腾讯美股行情可覆盖，代码加 us 前缀）——资金关注度代理
CRYPTO_ETFS = {
    "BTC": [
        ("IBIT", "贝莱德 iShares Bitcoin"),
        ("FBTC", "富达 Fidelity Wise Origin"),
        ("GBTC", "灰度 Grayscale Bitcoin"),
        ("ARKB", "ARK 21Shares Bitcoin"),
        ("BITB", "Bitwise Bitcoin"),
        ("HODL", "VanEck Bitcoin"),
    ],
    "ETH": [
        ("ETHA", "贝莱德 iShares Ethereum"),
        ("FETH", "富达 Fidelity Ethereum"),
        ("ETHE", "灰度 Grayscale Ethereum"),
        ("ETHW", "Bitwise Ethereum"),
        ("CETH", "21Shares Core Ethereum"),
        ("EZET", "Franklin Ethereum"),
    ],
}
_ALIASES = {
    "btc": "BTC", "bitcoin": "BTC", "比特币": "BTC", "btcusdt": "BTC", "btc_usdt": "BTC",
    "xbt": "BTC",
    "eth": "ETH", "ethereum": "ETH", "以太坊": "ETH", "以太": "ETH",
    "ethusdt": "ETH", "eth_usdt": "ETH",
}

_KLINE_TTL = int(os.environ.get("CRYPTO_KLINE_TTL", "600") or "600")
_KLINE_CACHE: dict = {}
_JSON_TTL = int(os.environ.get("CRYPTO_JSON_TTL", "120") or "120")
_JSON_CACHE: dict = {}


def _coin(code: str) -> str:
    """把各种写法归一化为 "BTC" / "ETH"。"""
    key = (code or "BTC").strip().lower().replace(" ", "")
    return _ALIASES.get(key, "BTC")


def crypto_trade_date(fmt: str = "%Y-%m-%d") -> str:
    """返回加密货币「最近一个已收盘的 UTC 日」（日 K 以 UTC 00:00 收线）。"""
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).strftime(fmt)


def _utc_ts(fmt: str = "%Y-%m-%d %H:%M UTC") -> str:
    return datetime.now(timezone.utc).strftime(fmt)


# ──────────────────────────────────────────────────────────────────────────────
# HTTP 辅助
# ──────────────────────────────────────────────────────────────────────────────
def _gate_get(path: str, params: Optional[dict] = None):
    return _http_get(GATE_API + path, params=params, retries=3)


def _cached_json(url: str, params: Optional[dict] = None, ttl: Optional[int] = None):
    """带进程内缓存的 JSON GET（防限流）。"""
    key = url + "?" + repr(sorted((params or {}).items()))
    now = time.time()
    hit = _JSON_CACHE.get(key)
    if hit and now - hit[0] < (ttl or _JSON_TTL):
        return hit[1]
    resp = _http_get(url, params=params, retries=3)
    if resp is None:
        return None
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return None
    _JSON_CACHE[key] = (now, data)
    return data


# ──────────────────────────────────────────────────────────────────────────────
# K 线：Gate 现货为主，Binance 镜像兜底；返回 [[date, open, close, high, low, volume(USDT)], ...]
# ──────────────────────────────────────────────────────────────────────────────
def _gate_daily(pair: str, limit: int = 200) -> list[list]:
    resp = _gate_get("/spot/candlesticks",
                     {"currency_pair": pair, "interval": "1d", "limit": max(10, min(limit, 1000))})
    if resp is None:
        return []
    try:
        rows = resp.json()
    except Exception:  # noqa: BLE001
        return []
    bars = []
    for r in rows:
        # Gate 现货字段：[时间戳, 计价成交量, 收盘, 最高, 最低, 开盘, 基础成交量, 是否收线]
        ts, qvol, close, high, low, open_ = r[0], r[1], r[2], r[3], r[4], r[5]
        date = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
        bars.append([date, open_, close, high, low, qvol])
    return _drop_forming(bars)


def _binance_daily(symbol: str, limit: int = 200) -> list[list]:
    resp = _http_get(f"{BINANCE_DATA}/klines",
                     params={"symbol": symbol, "interval": "1d", "limit": max(10, min(limit, 1000))})
    if resp is None:
        return []
    try:
        rows = resp.json()
    except Exception:  # noqa: BLE001
        return []
    bars = []
    for r in rows:
        # Binance 字段：[开盘时间, 开, 高, 低, 收, 基础量, 收盘时间, 计价量, ...]
        date = datetime.fromtimestamp(int(r[0]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        bars.append([date, r[1], r[4], r[2], r[3], r[7]])
    return _drop_forming(bars)


def _drop_forming(bars: list[list]) -> list[list]:
    """丢弃仍在形成的「今日 UTC」K 线，保证日 K 以已收盘日为准。"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return [b for b in bars if b[0] < today]


def _crypto_bars(coin: str, limit: int = 200) -> list[list]:
    """获取某币种日 K（[date, open, close, high, low, volume]），带缓存与兜底。"""
    coin = _coin(coin)
    key = (coin, limit)
    now = time.time()
    hit = _KLINE_CACHE.get(key)
    if hit and now - hit[0] < _KLINE_TTL:
        return hit[1]
    bars = _gate_daily(COINS[coin]["gate"], limit)
    if len(bars) < 5:
        bars = _binance_daily(COINS[coin]["binance"], limit)
    if bars:
        _KLINE_CACHE[key] = (now, bars)
    return bars


def _spot_ticker(coin: str) -> Optional[dict]:
    data = _cached_json(f"{GATE_API}/spot/tickers",
                        {"currency_pair": COINS[_coin(coin)]["gate"]})
    if isinstance(data, list) and data:
        return data[0]
    return None


def _futures_ticker(coin: str) -> Optional[dict]:
    data = _cached_json(f"{GATE_API}/futures/usdt/tickers",
                        {"contract": COINS[_coin(coin)]["gate"]})
    if isinstance(data, list) and data:
        return data[0]
    return None


def _ma(closes: list[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _chg(closes: list[float], n: int) -> Optional[float]:
    if len(closes) > n and closes[-1 - n]:
        return (closes[-1] / closes[-1 - n] - 1) * 100
    return None


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:+.2f}%"


def _num(x, dp: int = 1) -> str:
    f = _to_float(x)
    return "—" if f is None else f"{f:,.{dp}f}"


def _usd(x: Optional[float]) -> str:
    if x is None:
        return "—"
    for unit, div in (("万亿", 1e12), ("亿", 1e8), ("万", 1e4)):
        if abs(x) >= div:
            return f"{x / div:,.2f}{unit}"
    return f"{x:,.0f}"


def _daily_vol_pct(closes: list[float], lookback: int = 30) -> Optional[float]:
    """日收益率标准差（%）。"""
    c = [x for x in closes if x]
    if len(c) < 4:
        return None
    rets = [(c[i] / c[i - 1] - 1) * 100 for i in range(1, len(c)) if c[i - 1]]
    rets = rets[-lookback:]
    if len(rets) < 3:
        return None
    mean = sum(rets) / len(rets)
    return math.sqrt(sum((r - mean) ** 2 for r in rets) / len(rets))


# ══════════════════════════════════════════════════════════════════════════════
# 工具 1：BTC/ETH 行情总览
# ══════════════════════════════════════════════════════════════════════════════
@tool
def get_crypto_overview() -> str:
    """获取 BTC、ETH 的现货行情快照（最新价、24h/7d/30d 涨跌、24h 高低、成交额），
    以及加密市场总市值、BTC/ETH 主导率与恐贪指数。做加密复盘的第一步。"""
    lines = [f"# 加密市场总览（{_utc_ts()}）", ""]
    for coin in ("BTC", "ETH"):
        name = COINS[coin]["name"]
        bars = _crypto_bars(coin, 60)
        closes = [_to_float(b[2]) for b in bars if _to_float(b[2]) is not None]
        if not bars:
            lines.append(f"- {name}({coin})：行情获取失败。")
            continue
        lb = bars[-1]
        close = _to_float(lb[2])
        prev_close = _to_float(bars[-2][2]) if len(bars) >= 2 else None
        chg1d = (close / prev_close - 1) * 100 if close and prev_close else None
        lines.append(
            f"- **{name}({coin})**：{_num(close)} USDT（{lb[0]} UTC 收盘，{_pct(chg1d)}）"
            f"｜高 {_num(lb[3])} / 低 {_num(lb[4])}"
            f"｜7d {_pct(_chg(closes, 7))}｜30d {_pct(_chg(closes, 30))}"
            f"｜当日成交额 {_usd(_to_float(lb[5]))} USDT"
        )

    g = _cached_json(f"{COINLORE_API}/global/")
    if isinstance(g, list) and g:
        g = g[0]
        lines += ["", "## 市场结构",
                  f"- 全球总市值：{_usd(_to_float(g.get('total_mcap')))} USD"
                  f"（24h {_pct(_to_float(g.get('mcap_change')))}）",
                  f"- 24h 总成交额：{_usd(_to_float(g.get('total_volume')))} USD",
                  f"- **BTC 主导率 {g.get('btc_d')}%** / ETH 主导率 {g.get('eth_d')}%"
                  f"（主导率上升＝资金偏防御/向 BTC 集中）"]

    fng = _cached_json(FNG_API, {"limit": 1})
    if isinstance(fng, dict) and fng.get("data"):
        d = fng["data"][0]
        lines += ["", f"- 恐贪指数：**{d.get('value')}（{d.get('value_classification')}）**"
                      "（0 极度恐慌 ~ 100 极度贪婪）"]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 工具 2：BTC/ETH 日 K 结构（均线 / 区间 / 阶段涨跌 / 波动率）
# ══════════════════════════════════════════════════════════════════════════════
@tool
def get_crypto_kline(coin: str = "BTC", count: int = 120) -> str:
    """获取 BTC 或 ETH 的日 K 线结构：均线（MA20/MA50/MA200）、近 20 日区间高低、
    阶段涨跌幅（7/30/90 日）、实现波动率，以及相对 200 日均线的多空位置。

    Args:
        coin: 币种，填 BTC / ETH 或中文（比特币/以太坊），默认 BTC。
        count: 取最近多少根日 K，默认 120（约四个月）。
    """
    coin = _coin(coin)
    count = max(30, min(int(count), 1000))
    bars = _crypto_bars(coin, count)
    if not bars:
        return f"【数据获取失败】未能获取 {coin} 的日 K 线。"

    closes = [_to_float(b[2]) for b in bars if _to_float(b[2]) is not None]
    vols = [_to_float(b[5]) for b in bars if len(b) > 5 and _to_float(b[5]) is not None]
    latest = bars[-1]
    ma20, ma50, ma200 = _ma(closes, 20), _ma(closes, 50), _ma(closes, 200)
    recent = bars[-20:]
    high20 = max((_to_float(b[3]) for b in recent if _to_float(b[3]) is not None), default=None)
    low20 = min((_to_float(b[4]) for b in recent if _to_float(b[4]) is not None), default=None)
    vol = _daily_vol_pct(closes)

    def ma_txt(label, val):
        return f"{label}={val:,.1f}" if val else f"{label}=—(数据不足)"

    pos200 = ""
    if ma200 and closes:
        gap = (closes[-1] / ma200 - 1) * 100
        pos200 = f"（{'高于' if gap >= 0 else '低于'} 200 日均线 {gap:+.1f}% → " \
                 f"{'多头格局' if gap >= 0 else '空头格局'}）"

    vol_note = "—"
    if len(vols) >= 6 and sum(vols[-6:-1]):
        avg5 = sum(vols[-5:]) / 5
        prev5 = sum(vols[-6:-1]) / 5
        vol_note = f"近5日均量较前5日 {(avg5 / prev5 - 1) * 100:+.1f}%"

    lines = [
        f"# {coin}（{COINS[coin]['name']}）日 K 结构（共 {len(bars)} 根，数据截至 {latest[0]} UTC）",
        "",
        f"- 最新收盘：{latest[2]}（开 {latest[1]} 高 {latest[3]} 低 {latest[4]}）",
        f"- 均线：{ma_txt('MA20', ma20)} / {ma_txt('MA50', ma50)} / {ma_txt('MA200', ma200)}",
        f"- 200 日均线位置：{pos200 or '数据不足（<200 根）'}",
        f"- 近 20 日区间：高点 {high20:,.1f} / 低点 {low20:,.1f}" if high20 and low20 else "- 近 20 日区间：—",
        f"- 阶段涨跌：近7日 {_pct(_chg(closes, 7))} / 近30日 {_pct(_chg(closes, 30))} / 近90日 {_pct(_chg(closes, 90))}",
        f"- 实现波动率：日波动 {vol:.2f}%（年化 {vol * math.sqrt(365):.0f}%）" if vol else "- 实现波动率：—",
        f"- 量能：{vol_note}",
        "",
        "最近 8 根日 K（日期 开 收 高 低 成交额USDT）：",
    ]
    for b in bars[-8:]:
        lines.append("  " + "  ".join(str(x) for x in b[:6]))
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 工具 3：BTC/ETH 衍生品指标（资金费率 / 持仓 / 多空比 / 爆仓 / 基差）
# ══════════════════════════════════════════════════════════════════════════════
@tool
def get_crypto_derivatives(coin: str = "BTC") -> str:
    """获取 BTC/ETH **永续合约衍生品指标**（加密复盘的核心）：
    资金费率（年化）、未平仓合约 OI 及变化、多空账户比/吃单比、近 24h 多空爆仓、期货基差。
    用于判断杠杆拥挤度与拥挤方向（极端资金费率/多空比＝潜在挤兑风险）。

    Args:
        coin: 币种，BTC / ETH，默认 BTC。
    """
    coin = _coin(coin)
    pair = COINS[coin]["gate"]
    name = COINS[coin]["name"]

    contract = _cached_json(f"{GATE_API}/futures/usdt/contracts/{pair}") or {}
    ftk = _futures_ticker(coin) or {}
    spot = _spot_ticker(coin) or {}
    stats = _cached_json(f"{GATE_API}/futures/usdt/contract_stats",
                         {"contract": pair, "interval": "1d", "limit": 8})
    stats = sorted(stats, key=lambda x: x.get("time", 0)) if isinstance(stats, list) else []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stats = [s for s in stats
             if datetime.fromtimestamp(s.get("time", 0), tz=timezone.utc).strftime("%Y-%m-%d") < today]

    if not contract and not ftk:
        return f"【数据获取失败】未能获取 {coin} 合约数据。"

    funding = _to_float(contract.get("funding_rate"))
    fund_ind = _to_float(contract.get("funding_rate_indicative"))
    interval = _to_float(contract.get("funding_interval")) or 28800.0
    periods = 365 * 24 * 3600 / interval
    ann = funding * periods * 100 if funding is not None else None

    mark = _to_float(contract.get("mark_price")) or _to_float(ftk.get("mark_price"))
    index = _to_float(contract.get("index_price")) or _to_float(ftk.get("index_price"))
    last = _to_float(spot.get("last")) or _to_float(ftk.get("last"))
    basis = ((mark / last - 1) * 100) if (mark and last) else None
    leverage_max = _to_float(contract.get("leverage_max"))

    oi_contracts = _to_float(ftk.get("total_size"))
    qmult = _to_float(ftk.get("quanto_multiplier")) or 1.0
    oi_usd = oi_contracts * qmult * mark if (oi_contracts and mark) else None

    oi_chg = None
    stats_note = ""
    if stats:
        cur = stats[-1]
        oi_usd = _to_float(cur.get("open_interest_usd")) or oi_usd
        if len(stats) >= 2:
            prev = _to_float(stats[-2].get("open_interest_usd"))
            if prev and oi_usd:
                oi_chg = (oi_usd / prev - 1) * 100
        lsr_acc = _to_float(cur.get("lsr_account"))
        lsr_taker = _to_float(cur.get("lsr_taker"))
        lliq = _to_float(cur.get("long_liq_usd"))
        sliq = _to_float(cur.get("short_liq_usd"))
        stats_note = (
            f"- 多空账户比（散户）：**{lsr_acc:.2f}**（>1 多头占优，>2 偏拥挤）\n"
            f"- 吃单多空比：{lsr_taker:.2f}（>1 主动买盘占优）\n"
            f"- 近一日爆仓：多头 {_usd(lliq)} / 空头 {_usd(sliq)} USD"
            f"（{'多头被挤' if (lliq or 0) > (sliq or 0) else '空头被挤'}）"
            if lsr_acc is not None else ""
        )

    fh = _cached_json(f"{GATE_API}/futures/usdt/funding_rate",
                      {"contract": pair, "limit": 8})
    fund_trend = "—"
    if isinstance(fh, list) and fh:
        rates = [_to_float(x.get("r")) for x in fh if _to_float(x.get("r")) is not None]
        if rates:
            avg = sum(rates) / len(rates)
            fund_trend = (f"- 近 {len(rates)} 期资金费率均值 {avg * periods * 100:+.1f}% 年化"
                          f"（最近 {rates[-1] * periods * 100:+.1f}% 年化）")

    interp = []
    if ann is not None:
        if ann > 30:
            interp.append("资金费率显著为正 → 多头拥挤、杠杆过热，警惕多头挤压回落")
        elif ann < -10:
            interp.append("资金费率为负 → 空头拥挤、现货强于合约，警惕空头回补反弹")
        else:
            interp.append("资金费率接近中性 → 杠杆情绪温和")
    if oi_chg is not None:
        interp.append(f"OI 较上一日 {oi_chg:+.2f}%")

    lines = [
        f"# {name}({coin}) 永续合约衍生品（{_utc_ts()}）",
        "",
        f"- 标记价 {mark:,.1f} / 指数价 {index:,.1f} / 现货 {last:,.1f}" if mark and index and last
        else f"- 标记价 {mark} / 指数价 {index} / 现货 {last}",
        f"- **资金费率：{('—' if funding is None else f'{funding * 100:+.4f}%')} / 期"
        f"（{interval / 3600:.0f}h）→ 年化 {_pct(ann)}**"
        + (f"，预示下期 {('—' if fund_ind is None else f'{fund_ind * 100:+.4f}%')}" if fund_ind is not None else ""),
        fund_trend,
        f"- **未平仓合约 OI：{_usd(oi_usd)} USD**" + (f"（较上一日 {oi_chg:+.2f}%）" if oi_chg is not None else ""),
        f"- 期货基差（标记价 vs 现货）：{_pct(basis)}" + ("，期货升水" if (basis or 0) > 0 else "，期货贴水"),
        f"- 最高杠杆：{leverage_max:,.0f}x" if leverage_max else "",
        stats_note,
        "",
        "**解读**：",
    ]
    lines += [f"- {x}" for x in (interp or ["数据不足，无法解读。"])]
    return "\n".join(l for l in lines if l != "")


# ══════════════════════════════════════════════════════════════════════════════
# 工具 4：市场结构（主导率 / ETH-BTC 汇率 / 轮动）
# ══════════════════════════════════════════════════════════════════════════════
@tool
def get_crypto_global() -> str:
    """获取加密市场结构：全球总市值与 24h 变化、BTC/ETH 主导率，以及 **ETH/BTC 汇率**
    （衡量资金在 BTC 与 ETH 之间的轮动，是判断山寨/主流币相对强弱的关键指标）。"""
    g = _cached_json(f"{COINLORE_API}/global/")
    lines = [f"# 加密市场结构（{_utc_ts()}）", ""]
    if isinstance(g, list) and g:
        g = g[0]
        lines += [
            f"- 全球总市值：{_usd(_to_float(g.get('total_mcap')))} USD"
            f"（24h {_pct(_to_float(g.get('mcap_change')))}）",
            f"- 24h 总成交额：{_usd(_to_float(g.get('total_volume')))} USD",
            f"- **BTC 主导率：{g.get('btc_d')}%**",
            f"- **ETH 主导率：{g.get('eth_d')}%**",
        ]

    btc_bars = _crypto_bars("BTC", 60)
    eth_bars = _crypto_bars("ETH", 60)
    if btc_bars and eth_bars:
        btc = _to_float(btc_bars[-1][2])
        eth = _to_float(eth_bars[-1][2])
        if btc and eth:
            ratio = eth / btc
            btc_c = [_to_float(b[2]) for b in btc_bars if _to_float(b[2])]
            eth_c = [_to_float(b[2]) for b in eth_bars if _to_float(b[2])]

            def rchg(n):
                if len(btc_c) > n and len(eth_c) > n and btc_c[-1 - n] and eth_c[-1 - n]:
                    r0 = eth_c[-1 - n] / btc_c[-1 - n]
                    return (ratio / r0 - 1) * 100
                return None

            lines += ["",
                      f"- **ETH/BTC 汇率：{ratio:.6f}**"
                      f"（7d {_pct(rchg(7))}｜30d {_pct(rchg(30))}）"]
            r7 = rchg(7)
            if r7 is not None:
                lines.append("- 解读：" + ("ETH 强于 BTC（资金向以太坊/山寨扩散，风险偏好偏高）"
                                          if r7 > 1 else
                                          ("ETH 弱于 BTC（资金回流比特币，偏防御）" if r7 < -1 else "ETH 与 BTC 同步")))
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 工具 5：美国现货 ETF 交易面（资金关注度代理）
# ══════════════════════════════════════════════════════════════════════════════
@tool
def get_crypto_etf_flows() -> str:
    """获取美国上市 比特币/以太坊 **现货 ETF**（IBIT/FBTC/ETHA/FETH 等）的交易面快照：
    价格、当日涨跌、成交额，并按标的汇总成交额作为『ETF 资金关注度』的代理指标。
    用于评估 ETF 渠道的资金参与度与情绪。

    说明：逐日**净申赎流量（net flow）**需付费/受限数据源（Farside/SoSoValue/CoinGlass
    在本网络不可达），故本工具只提供可复现的**交易面代理**；资金净流入/流出请结合
    get_crypto_news / web_search 检索「ETF 净流入 净流出」对外部报道交叉判断。"""
    all_etfs = [(coin, tk, name) for coin, lst in CRYPTO_ETFS.items() for tk, name in lst]
    quotes = _tencent_quotes(["us" + tk for _coin, tk, _name in all_etfs])

    lines = [f"# 美国现货 ETF 交易面（{_utc_ts()}）", "",
             "> 成交额为资金关注度的**代理**指标；净申赎流量请结合消息面判断。", ""]
    for coin in ("BTC", "ETH"):
        lines += [f"## {COINS[coin]['name']}({coin}) 现货 ETF", "",
                  "| 代码 | 名称 | 价格(USD) | 当日涨跌 | 成交额(USD) |", "|---|---|---|---|---|"]
        total_amt = 0.0
        for tk, name in CRYPTO_ETFS[coin]:
            f = quotes.get("us" + tk)
            if not f:
                lines.append(f"| {tk} | {name} | 数据缺失 | — | — |")
                continue
            price = _tencent_field(f, 3)
            pct = _tencent_field(f, 32)
            amt = _tencent_field(f, 37)  # 美元成交额
            if amt:
                total_amt += amt
            lines.append(f"| {tk} | {name} | {_num(price, 2)} | {_pct(pct)} | {_usd(amt)} |")
        lines.append("")
        if total_amt:
            lines.append(f"- **{coin} 现货 ETF 合计成交额：{_usd(total_amt)} USD**"
                         "（显著放大＝资金活跃、情绪升温；对比近期均值判断放量与否）")
        lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 工具 6：情绪（恐慌与贪婪指数）
# ══════════════════════════════════════════════════════════════════════════════
@tool
def get_crypto_sentiment() -> str:
    """获取加密市场「恐慌与贪婪指数」当前值与近期趋势（0 极度恐慌 ~ 100 极度贪婪），
    用于判断市场情绪极端程度。"""
    data = _cached_json(FNG_API, {"limit": 30})
    if not isinstance(data, dict) or not data.get("data"):
        return "【数据获取失败】未能获取恐贪指数。"
    rows = data["data"]
    cur = rows[0]
    vals = [_to_float(r.get("value")) for r in rows if _to_float(r.get("value")) is not None]
    avg7 = sum(vals[:7]) / len(vals[:7]) if len(vals) >= 7 else None
    avg30 = sum(vals[:30]) / len(vals[:30]) if vals else None
    lines = [
        f"# 加密恐慌与贪婪指数（{_utc_ts()}）",
        "",
        f"- 当前：**{cur.get('value')}（{cur.get('value_classification')}）**",
        f"- 近 7 日均值：{avg7:.0f}" if avg7 else "",
        f"- 近 30 日均值：{avg30:.0f}" if avg30 else "",
        "",
        "最近 10 日（日期 值 分类）：",
    ]
    for r in rows[:10]:
        ts = int(r.get("timestamp", 0))
        d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        lines.append(f"  {d}  {r.get('value')}  {r.get('value_classification')}")
    return "\n".join(l for l in lines if l != "")


# ══════════════════════════════════════════════════════════════════════════════
# 工具 7：加密新闻检索（必应）
# ══════════════════════════════════════════════════════════════════════════════
@tool
def get_crypto_news(query: str = "", count: int = 10) -> str:
    """检索加密货币最新新闻与事件（ETF 资金流、监管、宏观、交易所/项目事件、ETF、减半等）。

    Args:
        query: 搜索关键词，留空默认搜索「比特币 以太坊 加密货币 今日 行情 原因」。
        count: 返回条数，默认 10。
    """
    count = max(3, min(int(count), 15))
    q = query.strip() or f"比特币 BTC 以太坊 ETH 加密货币 今日行情 最新消息"
    resp = _http_get("https://cn.bing.com/search", params={"q": q, "count": count}, retries=3)
    if resp is None:
        return "【搜索失败】必应暂时不可用，请稍后重试。"
    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select("li.b_algo")
    if not items:
        return f"未搜索到「{q}」的相关结果。"
    lines = [f"# 加密新闻：{q}", ""]
    for it in items[:count]:
        a = it.select_one("h2 a")
        p = it.select_one("p")
        if not a:
            continue
        lines.append(f"- {a.get_text(strip=True)}")
        if a.get("href"):
            lines.append(f"  链接：{a.get('href')}")
        if p:
            lines.append(f"  摘要：{p.get_text(strip=True)}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 工具 8：生成 BTC/ETH K 线图
# ══════════════════════════════════════════════════════════════════════════════
def _make_crypto_chart(coin: str, name: str, days: int, out_dir: Path):
    bars = _crypto_bars(coin, days)
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
        return [sum(vals[i - n + 1:i + 1]) / n if i >= n - 1 else None for i in range(len(vals))]

    up_color, down_color = "#26a69a", "#ef5350"  # 加密常用绿涨红跌

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
    for n, col in ((20, "#ff9800"), (50, "#1e88e5"), (200, "#8e24aa")):
        series = ma(closes, n)
        if any(v is not None for v in series):
            ax.plot(x, series, color=col, linewidth=1.1, label=f"MA{n}", zorder=4)

    ax.set_title(f"{name}（{coin}）日 K 线（近 {len(bars)} 日, UTC）", fontsize=13, fontweight="bold")
    ax.set_ylabel("价格 USDT", fontsize=10)
    ax.grid(True, linestyle="--", alpha=0.25)
    ax.legend(loc="upper left", fontsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    vol_colors = [up_color if c >= o else down_color for o, c in zip(opens, closes)]
    axv.bar(x, vols, color=vol_colors, width=0.7, alpha=0.75)
    axv.set_ylabel("成交额", fontsize=9)
    axv.grid(True, linestyle="--", alpha=0.2)
    for spine in ("top", "right"):
        axv.spines[spine].set_visible(False)

    step = max(1, len(dates) // 8)
    ticks = x[::step]
    axv.set_xticks(ticks)
    axv.set_xticklabels([dates[i][5:] for i in ticks], fontsize=8)

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = re.sub(r"\D", "", dates[-1]) or datetime.now().strftime("%Y%m%d")
    path = out_dir / f"{coin}_{stamp}.png"
    fig.savefig(path, dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path, len(bars)


@tool
def generate_crypto_charts(coins: str = "", days: int = 120) -> str:
    """生成 BTC/ETH 日 K 线图（默认近 120 日），返回可插入报告的 Markdown 图片行。

    Args:
        coins: 逗号分隔的币种，如 "BTC,ETH"；留空默认两者都生成。
        days: 取最近多少根日 K，默认 120。
    """
    days = max(30, min(int(days), 500))
    coin_list = [_coin(c) for c in coins.split(",") if c.strip()] or ["BTC", "ETH"]
    chart_dir = REPORT_DIR / "crypto_charts"
    lines: list[str] = []
    for coin in coin_list:
        try:
            result = _make_crypto_chart(coin, COINS[coin]["name"], days, chart_dir)
        except Exception as exc:  # noqa: BLE001
            lines.append(f"（{coin} 图表生成失败：{exc}）")
            continue
        if result:
            path, n = result
            lines.append(f"![{COINS[coin]['name']}近{n}日K线]({path.resolve().as_posix()})")
        else:
            lines.append(f"（{coin} 数据不足，未生成图表）")
    if not lines:
        return "【生成失败】未能生成任何 K 线图。"
    return ("已生成加密 K 线图。请把下面每一行 **原样** 插入报告第一节之后：\n\n"
            + "\n\n".join(lines))


CRYPTO_TOOLS = [
    get_crypto_overview,
    get_crypto_kline,
    get_crypto_derivatives,
    get_crypto_global,
    get_crypto_etf_flows,
    get_crypto_sentiment,
    get_crypto_news,
    generate_crypto_charts,
]
