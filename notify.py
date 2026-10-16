# -*- coding: utf-8 -*-
"""
notify.py —— 社交分发（X/Twitter + Telegram 频道）
==================================================

分层漏斗（公域 → 私域）：

- **X/Twitter（公开）**：每天 1 条 **预告(teaser)** —— 一句话结论 + 1–2 个关键点位 + 滚动命中率 + 频道链接；
- **Telegram 免费频道**：**大盘 + 板块**（把报告压缩成公开可发的部分）+ 1 张 K 线图；
- （预留）**付费 Bot/私群**：多空点位、个性化持仓复盘、周报月报 —— 后续再加。

重要：本机（中国大陆）**无法访问** api.x.com / api.telegram.org，因此推送应在
**GitHub Actions（美国 runner）** 上执行；本地未配置凭据时静默跳过（no-op）。

环境变量见 .env.example；凭据配置见 docs/SETUP-SOCIAL.md。
所有内容仅供研究参考，不构成投资建议。
"""

from __future__ import annotations

import base64
import os
import re

import requests

try:
    from requests_oauthlib import OAuth1
except Exception:  # noqa: BLE001
    OAuth1 = None

TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "20") or "20")
CHANNEL_URL = os.environ.get("TELEGRAM_CHANNEL_URL", "").strip()  # 如 https://t.me/yourchannel


# ──────────────────────────────────────────────────────────────────────────────
# 配置读取
# ──────────────────────────────────────────────────────────────────────────────
def _tg_creds(chat_id: str | None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = (chat_id or os.environ.get("TELEGRAM_CHANNEL_ID", "")
            or os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
    return token, chat


def _x_creds():
    return {
        "api_key": os.environ.get("X_API_KEY", "").strip(),
        "api_secret": os.environ.get("X_API_SECRET", "").strip(),
        "access_token": os.environ.get("X_ACCESS_TOKEN", "").strip(),
        "access_secret": os.environ.get("X_ACCESS_SECRET", "").strip(),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 报告解析（用于生成分层内容）
# ──────────────────────────────────────────────────────────────────────────────
_HEAD_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _strip_md(s: str) -> str:
    """去掉 Markdown 强调/代码标记（保留换行），让纯文本推送更好读。"""
    return s.replace("**", "").replace("`", "").replace("*", "")


def _plain(s: str) -> str:
    """压成一行纯文本：去强调、去引用/列表符号、折叠空白。"""
    s = _strip_md(s)
    s = re.sub(r"^[>\-\s]+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _sections(md: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    head, buf = "（开篇）", []
    for line in md.splitlines():
        m = _HEAD_RE.match(line)
        if m:
            if buf:
                out.append((head, "\n".join(buf).strip()))
                buf = []
            head = m.group(2).strip()
        else:
            buf.append(line)
    if buf:
        out.append((head, "\n".join(buf).strip()))
    return out


def _section(md: str, *keywords: str) -> str:
    """取标题命中任一关键词的章节正文（拼接）。"""
    parts = [body for head, body in _sections(md) if any(k in head for k in keywords)]
    return "\n\n".join(p for p in parts if p)


def _conclusion(md: str) -> str:
    m = re.search(r"一句话结论[^\n]*?[:：]\s*(.+)", md)
    if m:
        return _plain(m.group(1))
    # 兜底：取第一个引用行
    for line in md.splitlines():
        s = line.strip()
        if s.startswith(">"):
            return _plain(s)
    return ""


def _first_image(md: str) -> str:
    m = re.search(r"!\[[^\]]*\]\(([^)]+)\)", md)
    if not m:
        return ""
    path = m.group(1).strip()
    return path if os.path.exists(path) else ""


def _key_levels(md: str) -> str:
    """从「后市预判/操作策略」章节里挑一句含支撑/压力的口径句。"""
    body = _section(md, "后市预判", "操作策略", "预判")
    for line in body.splitlines():
        if ("压力" in line or "支撑" in line) and re.search(r"\d", line):
            return _plain(line)
    return ""


def _hit_rate(md: str) -> str:
    body = _section(md, "往期验证", "验证")
    for line in body.splitlines():
        if "命中率" in line:
            return _plain(line)
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# 内容构造
# ──────────────────────────────────────────────────────────────────────────────
def build_free_digest(report_md: str, title: str = "") -> str:
    """免费频道内容：一句话结论 + 大盘 + 板块/结构（不含付费的点位与预判）。"""
    parts = []
    if title:
        parts.append(title)
    overview = _strip_md(_section(report_md, "大盘", "行情"))
    flows = _strip_md(_section(report_md, "资金", "结构", "板块"))
    concl = _conclusion(report_md)
    if concl and concl[:16] not in overview:  # 避免与正文重复
        parts.append(f"🧭 {concl}")
    for block in (overview, flows):
        if block:
            parts.append(block)
    if CHANNEL_URL:
        parts.append(f"🔒 点位与操作策略见付费/私域（预留）：{CHANNEL_URL}")
    text = "\n\n".join(parts).strip()
    return text[:3900]


def build_teaser(report_md: str, title: str = "") -> str:
    """X 预告：结论 + 关键点位 + 命中率 + 频道链接，控制在 280 字内。"""
    concl = _conclusion(report_md)
    levels = _key_levels(report_md)
    hit = _hit_rate(report_md)
    lines = [title or "📊 每日复盘"]
    if concl:
        lines.append(concl[:140])
    if levels:
        lines.append("📍 " + levels[:90])
    if hit:
        lines.append("📈 " + hit[:80])
    if CHANNEL_URL:
        lines.append("🔗 " + CHANNEL_URL)
    text = "\n".join(l for l in lines if l).strip()
    return text[:275]


# ──────────────────────────────────────────────────────────────────────────────
# Telegram 推送
# ──────────────────────────────────────────────────────────────────────────────
def send_telegram(text: str, chat_id: str | None = None) -> str:
    """推送文本。未配置则跳过，不抛异常。"""
    token, chat = _tg_creds(chat_id)
    if not token or not chat:
        return "【跳过】未配置 TELEGRAM_BOT_TOKEN / (CHANNEL_ID|CHAT_ID)。"
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text[:4000],
                                "disable_web_page_preview": True}, timeout=TIMEOUT)
        ok = r.status_code == 200 and (r.json() or {}).get("ok")
        return "Telegram 文本已推送。" if ok else f"【失败】Telegram {r.status_code}: {r.text[:120]}"
    except Exception as exc:  # noqa: BLE001
        return f"【失败】{exc}"


def send_telegram_photo(image_path: str, caption: str = "",
                        chat_id: str | None = None) -> str:
    """推送图片（附说明）。未配置或文件不存在则跳过。"""
    token, chat = _tg_creds(chat_id)
    if not token or not chat:
        return "【跳过】未配置 Telegram。"
    if not image_path or not os.path.exists(image_path):
        return "【跳过】无图片。"
    try:
        with open(image_path, "rb") as fh:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                              data={"chat_id": chat, "caption": caption[:1000]},
                              files={"photo": fh}, timeout=TIMEOUT)
        ok = r.status_code == 200 and (r.json() or {}).get("ok")
        return "Telegram 图片已推送。" if ok else f"【失败】Telegram {r.status_code}: {r.text[:120]}"
    except Exception as exc:  # noqa: BLE001
        return f"【失败】{exc}"


# ──────────────────────────────────────────────────────────────────────────────
# X/Twitter 推送（OAuth 1.0a 用户上下文）
# ──────────────────────────────────────────────────────────────────────────────
def post_tweet(text: str, image_path: str = "") -> str:
    """发一条推文（可带 1 张图）。未配置凭据则跳过。"""
    c = _x_creds()
    if not all(c.values()):
        return "【跳过】未配置 X_* 凭据。"
    if OAuth1 is None:
        return "【失败】缺少 requests-oauthlib（pip install requests-oauthlib）。"
    auth = OAuth1(c["api_key"], c["api_secret"], c["access_token"], c["access_secret"])
    media_ids: list[str] = []
    try:
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as fh:
                up = requests.post(
                    "https://upload.twitter.com/1.1/media/upload.json",
                    data={"media_data": base64.b64encode(fh.read()).decode()},
                    auth=auth, timeout=TIMEOUT)
            if up.status_code == 200:
                media_ids.append(up.json().get("media_id_string", ""))
        payload: dict = {"text": text[:280]}
        if media_ids and media_ids[0]:
            payload["media"] = {"media_ids": media_ids}
        r = requests.post("https://api.twitter.com/2/tweets", json=payload,
                          auth=auth, timeout=TIMEOUT)
        ok = r.status_code in (200, 201)
        return "X 推文已发布。" if ok else f"【失败】X {r.status_code}: {r.text[:160]}"
    except Exception as exc:  # noqa: BLE001
        return f"【失败】{exc}"


# ──────────────────────────────────────────────────────────────────────────────
# 编排：复盘结束后一键分发
# ──────────────────────────────────────────────────────────────────────────────
def push_social(report_path: str, title: str = "") -> str:
    """读报告 → 免费频道(大盘+板块+图) + X 预告，返回各渠道结果。"""
    if not os.path.exists(report_path):
        return f"【跳过】找不到报告：{report_path}"
    md = open(report_path, encoding="utf-8").read()
    img = _first_image(md)
    digest = build_free_digest(md, title)
    teaser = build_teaser(md, title)

    results = []
    # 免费频道：图文
    if img:
        results.append(send_telegram_photo(img, caption=digest[:1000]))
    results.append(send_telegram(digest))
    # X：预告 + 图
    results.append(post_tweet(teaser, image_path=img))
    return " | ".join(results)


def daily_digest(today: str, report_md: str = "") -> str:
    """（兼容旧接口）构造一条简短摘要。"""
    concl = _conclusion(report_md) if report_md else ""
    tail = f"\n\n🔗 {CHANNEL_URL}" if CHANNEL_URL else ""
    return f"📈 每日复盘 | {today}" + (f"\n\n{concl}" if concl else "") + tail


if __name__ == "__main__":
    print(send_telegram("测试消息：Daily Market Review Agent 已接通 Telegram。"))
