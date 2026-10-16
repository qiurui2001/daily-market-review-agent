# -*- coding: utf-8 -*-
"""
crypto_main.py —— 加密货币(BTC/ETH)复盘 Agent 入口
=================================================

编排 研究员 → 核查员 → 复盘校验员 → 分析师 → 撰稿人 串行协作，
一键产出《加密复盘》报告并邮件交付，同时把当日预测提交进加密哈希链台账。

用法：
    python crypto_main.py                      # 复盘最近一个已收盘的 UTC 日
    python crypto_main.py --date 2026-10-09    # 指定 UTC 日期
    python crypto_main.py --to client@qq.com    # 指定收件邮箱
    python crypto_main.py --quiet               # 关闭过程日志

环境变量：见 .env.example

所有数据仅供研究参考，不构成投资建议。
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="加密货币(BTC/ETH)复盘 Multi-Agent")
    parser.add_argument("--date", default="", help="复盘 UTC 日期，格式 YYYY-MM-DD，默认最近一个已收盘 UTC 日")
    parser.add_argument("--to", default="", help="收件邮箱，覆盖 REPORT_TO_EMAIL")
    parser.add_argument("--quiet", action="store_true", help="关闭详细过程日志")
    return parser.parse_args()


def _build_crew():
    from crewai import Crew, Process

    from crypto_agents import CRYPTO_AGENTS
    from crypto_tasks import CRYPTO_TASKS

    return Crew(
        agents=CRYPTO_AGENTS,
        tasks=CRYPTO_TASKS,
        process=Process.sequential,
        verbose=not os.environ.get("AGENT_VERBOSE", "true").lower() in ("0", "false", "no"),
        memory=False,
        max_rpm=30,
    )


def main() -> int:
    args = _parse_args()

    if args.to:
        os.environ["REPORT_TO_EMAIL"] = args.to
    if args.quiet:
        os.environ["AGENT_VERBOSE"] = "false"

    today = args.date.strip()
    if not today:
        from crypto_tools import crypto_trade_date
        today = crypto_trade_date()

    from agents import DEEPSEEK_API_KEY  # noqa: F401  （复用美股团队的 LLM 配置）

    if not DEEPSEEK_API_KEY:
        print("=" * 60)
        print("  [ERROR] 未检测到 DEEPSEEK_API_KEY")
        print("  请复制 .env.example 为 .env 并填写，或设置系统环境变量")
        print("=" * 60)
        return 1

    crew = _build_crew()

    print("=" * 60)
    print("  加密货币(BTC/ETH)复盘 Agent 启动")
    print(f"  复盘日期（UTC）：{today}")
    print("  团队：研究员 → 核查员 → 复盘校验员 → 分析师 → 撰稿人")
    print(f"  收件邮箱：{os.environ.get('REPORT_TO_EMAIL', '（未配置，将只存档）')}")
    print("=" * 60)

    try:
        result = crew.kickoff(inputs={"today": today})
    except KeyboardInterrupt:
        print("\n[已中断] 用户取消运行。")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"\n[运行失败] {exc}")
        return 1

    print("\n" + "=" * 60)
    print("  加密复盘完成")
    print("=" * 60)
    print(result)

    # 提交当日预测到加密哈希链台账（防篡改；同一日不重复提交）
    try:
        from crypto_integrity import commit_crypto_day
        print("\n[加密预测台账] " + commit_crypto_day(today))
    except Exception as exc:  # noqa: BLE001
        print(f"\n[加密预测台账] 提交失败（不影响复盘）：{exc}")

    # 可选：社交分发（X 预告 + Telegram 免费频道；未配置凭据则静默跳过 / 本地网络不可达）
    try:
        from notify import push_social
        report_path = os.path.join(os.environ.get("REPORT_DIR", "reports"), f"加密复盘_{today}.md")
        print("[分发] " + push_social(report_path, title=f"🪙 加密复盘 | {today}"))
    except Exception as exc:  # noqa: BLE001
        print(f"[分发] 推送失败（不影响复盘）：{exc}")

    usage = getattr(crew, "usage_metrics", None)
    if usage:
        print("\n[Token 用量] " + str(usage))
    return 0


if __name__ == "__main__":
    sys.exit(main())
