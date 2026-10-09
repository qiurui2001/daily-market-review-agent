# -*- coding: utf-8 -*-
"""
main.py —— 美股盘后复盘 Agent 入口
====================================

编排 研究员 → 核查员 → 复盘校验员 → 分析师 → 撰稿人 串行协作，
一键产出美股复盘报告并邮件交付。

用法：
    python main.py                         # 复盘最近一个美股交易日
    python main.py --date 2026-10-09       # 指定日期
    python main.py --to client@qq.com      # 指定收件邮箱
    python main.py --quiet                 # 关闭过程日志

环境变量：见 .env.example
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

# 先加载 .env，且不覆盖已有的系统环境变量（命令行参数优先级更高）
load_dotenv()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="美股盘后复盘 Multi-Agent")
    parser.add_argument("--date", default="", help="复盘日期，格式 YYYY-MM-DD，默认最近一个美股交易日")
    parser.add_argument("--to", default="", help="收件邮箱，覆盖 REPORT_TO_EMAIL")
    parser.add_argument("--quiet", action="store_true", help="关闭详细过程日志")
    parser.add_argument("--self-review", action="store_true", help="改为运行《研究月报》(自省)，而非每日复盘")
    parser.add_argument("--days", type=int, default=30, help="研究月报覆盖天数，默认 30")
    return parser.parse_args()


def _build_crew():
    # 延迟导入：确保命令行注入的环境变量在 Agent / LLM 初始化前生效
    from crewai import Crew, Process

    from agents import AGENTS
    from tasks import TASKS

    return Crew(
        agents=AGENTS,
        tasks=TASKS,
        process=Process.sequential,
        verbose=not os.environ.get("AGENT_VERBOSE", "true").lower() in ("0", "false", "no"),
        memory=False,          # 复盘任务上下文清晰，无需向量记忆，避免额外依赖
        max_rpm=30,            # 控制请求频率，规避接口限流
    )


def main() -> int:
    args = _parse_args()

    if args.to:
        os.environ["REPORT_TO_EMAIL"] = args.to
    if args.quiet:
        os.environ["AGENT_VERBOSE"] = "false"

    today = args.date.strip()
    if not today:
        # 默认取「最近一个美股交易日」（美东口径），避免北京日期比美股慢/快一天
        from tools import us_trade_date
        today = us_trade_date()

    # 延迟导入以读取最终环境变量
    from agents import AGENTS, DEEPSEEK_API_KEY  # noqa: F401
    from tasks import TASKS  # noqa: F401

    if not DEEPSEEK_API_KEY:
        print("=" * 60)
        print("  [ERROR] 未检测到 DEEPSEEK_API_KEY")
        print("  请复制 .env.example 为 .env 并填写，或设置系统环境变量")
        print("=" * 60)
        return 1

    # ── 研究月报（自省）模式 ──
    if args.self_review:
        from selfreview import run_self_review
        print("=" * 60)
        print(f"  研究月报（自省）启动")
        print(f"  基准日：{today}｜覆盖近 {args.days} 天")
        print("=" * 60)
        try:
            result = run_self_review(days_back=args.days, today=today)
        except KeyboardInterrupt:
            print("\n[已中断] 用户取消运行。")
            return 130
        except Exception as exc:  # noqa: BLE001
            print(f"\n[运行失败] {exc}")
            return 1
        print("\n" + "=" * 60)
        print("  研究月报完成")
        print("=" * 60)
        print(result)
        return 0

    crew = _build_crew()

    print("=" * 60)
    print(f"  美股盘后复盘 Agent 启动")
    print(f"  复盘日期（美东）：{today}")
    print(f"  团队：研究员 → 核查员 → 复盘校验员 → 分析师 → 撰稿人")
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
    print("  复盘完成")
    print("=" * 60)
    print(result)

    # 提交当日预测到只追加、哈希链台账（防篡改；同一日不重复提交）
    try:
        from integrity import commit_day
        print("\n[预测台账] " + commit_day(today))
    except Exception as exc:  # noqa: BLE001
        print(f"\n[预测台账] 提交失败（不影响复盘）：{exc}")

    # 可选：推送到 Telegram（未配置则静默跳过）
    try:
        from notify import daily_digest, send_telegram
        report_path = os.path.join(os.environ.get("REPORT_DIR", "reports"), f"美股复盘_{today}.md")
        body = ""
        if os.path.exists(report_path):
            with open(report_path, encoding="utf-8") as fh:
                body = fh.read()
        print("[通知] " + send_telegram(daily_digest(today, body)))
    except Exception as exc:  # noqa: BLE001
        print(f"[通知] 推送失败（不影响复盘）：{exc}")

    usage = getattr(crew, "usage_metrics", None)
    if usage:
        print("\n[Token 用量] " + str(usage))
    return 0


if __name__ == "__main__":
    sys.exit(main())
