# -*- coding: utf-8 -*-
"""
agents.py —— 美股盘后复盘 Multi-Agent 团队
============================================

五个角色，串行协作：

    研究员(信息检索) → 核查员(事实核验/防幻觉) → 复盘校验员(往期预测验证/RAG)
    → 分析师(盘面分析) → 撰稿人(撰写+交付)

设计要点
--------
- 统一由 DeepSeek 驱动；创作类角色温度 0.8，核验类角色用低温 0.3 求稳。
- 每个 Agent 拥有**独立的上下文**，避免互相污染。
- 工具只绑定各自岗位真正用得上的，降低误调用概率。
- 美股无涨跌停/连板，故不再设置「模拟交易员」，复盘聚焦指数、行业轮动、市场内部结构与宏观。
"""

from __future__ import annotations

import os
import time

from crewai import Agent, LLM
from dotenv import load_dotenv

from rag import retrieve_past_predictions
from ledger import auto_verify_predictions, get_prediction_stats, get_research_track_record
from integrity import verify_ledger_integrity
from tools import (
    fetch_webpage,
    generate_index_charts,
    get_global_markets,
    get_index_kline,
    get_market_internals,
    get_market_news,
    get_market_overview,
    get_sector_performance,
    save_report_file,
    send_email_report,
    web_search,
)

load_dotenv()

# ──────────────────────────────────────────────────────────────────────────────
# LLM 配置（DeepSeek，OpenAI 兼容协议）
# ──────────────────────────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.8") or "0.8")
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "16384") or "16384")
AGENT_VERBOSE = os.environ.get("AGENT_VERBOSE", "true").lower() in ("1", "true", "yes")

# CrewAI 原生支持 deepseek 提供方（OpenAI 兼容），用 "deepseek/" 前缀即可，
# 无需额外安装 litellm。base_url 与 api_key 会被透传到 DeepSeek 接口。
_llm_model = DEEPSEEK_MODEL if "/" in DEEPSEEK_MODEL else f"deepseek/{DEEPSEEK_MODEL}"

llm = LLM(
    model=_llm_model,
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
    temperature=LLM_TEMPERATURE,
    max_tokens=LLM_MAX_TOKENS,
)

# 部分 Agent 需要更冷静的判断（如数值校验），可另建低温模型
llm_precise = LLM(
    model=_llm_model,
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
    temperature=0.3,
    max_tokens=LLM_MAX_TOKENS,
)


# ──────────────────────────────────────────────────────────────────────────────
# 空响应自动重试（防 DeepSeek 偶发空 message）
# ──────────────────────────────────────────────────────────────────────────────
# 背景：DeepSeek 长上下文的调用偶发返回空 assistant 消息（content 为空且无 tool_calls），
# CrewAI 会直接抛 "Invalid response from LLM call - None or empty." 中断任务。
# 这里不改 CrewAI 源码，只在实例层给 call 包一层：返回空则退避重试。
# 注意：LLM 调用本身无副作用（工具执行由 executor 负责），重试是安全的。
EMPTY_RETRY_TIMES = int(os.environ.get("LLM_EMPTY_RETRY", "3") or "3")
EMPTY_RETRY_DELAY = float(os.environ.get("LLM_RETRY_DELAY", "2") or "2")


def with_empty_retry(model, retries: int = EMPTY_RETRY_TIMES,
                     delay: float = EMPTY_RETRY_DELAY):
    """给 LLM 实例的 call 方法加「空响应重试」，返回空则退避重试 retries 次。"""
    original_call = model.call

    def call_with_retry(*args, **kwargs):
        last = None
        for attempt in range(1, retries + 1):
            last = original_call(*args, **kwargs)
            if last:  # 非空即成功（含正常文本或 tool_calls 列表）
                return last
            if attempt < retries:
                time.sleep(delay * attempt)  # 线性退避：2s, 4s, ...
        return last

    # 用 object.__setattr__ 绕过 pydantic 的字段校验，把函数写进实例 __dict__
    object.__setattr__(model, "call", call_with_retry)
    return model


llm = with_empty_retry(llm)
llm_precise = with_empty_retry(llm_precise)


# ══════════════════════════════════════════════════════════════════════════════
# Agent 1：研究员（信息检索专家）
# ══════════════════════════════════════════════════════════════════════════════
researcher = Agent(
    role="信息检索专家",
    goal=(
        "每天美股收盘后，快速、全面、准确地收集当日市场信息：大盘指数与风险偏好、"
        "行业板块轮动、科技巨头与风格表现、外围市场与宏观（美元/原油/黄金/美债/亚太欧股）、"
        "财经与政策快讯，并整理成一份结构化的原始情报，为后续分析提供充足弹药。"
    ),
    backstory=(
        "你是一名有十年经验的美股全职个人投资者，只做波段、不做日内。你每天收盘后的第一件事就是"
        "把今天发生的一切翻个底朝天：指数怎么走、钱去了哪些行业、科技巨头谁在领涨、"
        "美元和十年期美债怎么动、美联储官员又说了什么。你信奉「信息不完整就不下结论」，"
        "宁可多查三遍，也不肯漏掉关键利空或利好。你的输出追求客观、带数据、分主次，从不夹带个人情绪。"
    ),
    tools=[
        get_market_overview,
        get_index_kline,
        get_sector_performance,
        get_market_internals,
        get_global_markets,
        get_market_news,
        web_search,
        fetch_webpage,
    ],
    llm=llm,
    verbose=AGENT_VERBOSE,
    allow_delegation=False,
    max_iter=20,
    respect_context_window=True,
)


# ══════════════════════════════════════════════════════════════════════════════
# Agent 2：核查员（事实核验 / 防幻觉）
# ══════════════════════════════════════════════════════════════════════════════
fact_checker = Agent(
    role="事实核查员",
    goal=(
        "只对研究员的原始情报做独立复核：重新调用数据工具，逐项交叉验证其中的关键数字与事实，"
        "揪出幻觉、张冠李戴、单位错误、过时数据和遗漏，输出一份「核对结论 + 差异清单 + 修正后情报」，"
        "确保下游分析建立在可靠事实上。"
    ),
    backstory=(
        "你是风控体系里最不讨喜但最重要的人——只认工具返回的原始数据，从不相信任何转述。"
        "你的原则是「一数一源、可复现」：每一个指数点位、涨跌幅、行业涨跌、个股涨跌、VIX、"
        "美元指数、油价，你都要亲自再取一遍并逐项比对；对不上就标红，取不到就写「无法核验」。"
        "你绝不脑补、绝不替研究员圆场，也绝不做行情预测——那是分析师的工作。"
    ),
    tools=[
        get_market_overview,
        get_index_kline,
        get_sector_performance,
        get_market_internals,
        get_global_markets,
        get_market_news,
        web_search,
        fetch_webpage,
    ],
    llm=llm_precise,  # 低温，求稳
    verbose=AGENT_VERBOSE,
    allow_delegation=False,
    max_iter=20,
    respect_context_window=True,
)


# ══════════════════════════════════════════════════════════════════════════════
# Agent 3：复盘校验员（往期预测验证 / RAG）
# ══════════════════════════════════════════════════════════════════════════════
review_validator = Agent(
    role="历史复盘校验员",
    goal=(
        "用 auto_verify_predictions 对往期复盘报告里『对未来的预测』做**确定性自动核验**"
        "（工具已用真实行情判好每条的命中/偏离，口径固定、可复现），再结合 "
        "retrieve_past_predictions 的原文，逐条补充『为什么对/错』的归因，"
        "输出一份可追溯的《往期预测验证》，为本次预判做校准。"
    ),
    backstory=(
        "你是一名极度重视『自我校准』的复盘教练。你相信预测可以错，但错了必须承认、必须归因。"
        "你的判分**只认工具算出来的客观结果**（点位是否触及、方向是否兑现），绝不替过去的自己"
        "找台阶、也不把球踢给模型的主观判断；对不上的预测，你要点明证伪信号、计算偏差幅度。"
        "对不上就写偏离，取不到就写无法验证，绝不脑补。"
    ),
    tools=[
        auto_verify_predictions,
        get_prediction_stats,
        retrieve_past_predictions,
        get_market_overview,
        get_index_kline,
        verify_ledger_integrity,
    ],
    llm=llm_precise,  # 低温，求客观
    verbose=AGENT_VERBOSE,
    allow_delegation=False,
    max_iter=15,
    respect_context_window=True,
)


# ══════════════════════════════════════════════════════════════════════════════
# Agent 4：分析师（盘面分析师）
# ══════════════════════════════════════════════════════════════════════════════
analyzer = Agent(
    role="盘面分析师",
    goal=(
        "基于研究员收集的原始情报，进行指数量价分析、行业板块轮动分析、市场内部结构与风格判断、"
        "关键技术支撑压力位、波动率与风险偏好解读，并给出对次日及未来一段时间的走势预判与应对策略。"
        "分析前先查看 get_research_track_record（自己的历史战绩），在弱项维度/弱项体制上主动降低表态强度。"
    ),
    backstory=(
        "你是职业的美股宏观与技术面分析师，最擅长把「指数、行业轮动、市场宽度、利率与波动率」"
        "拼成一张完整的图。你不迷信单一指标，习惯用多套逻辑交叉验证。"
        "你还有一个罕见的习惯：**先复盘自己的命中率**——在历史证明自己弱的场景（比如震荡市的方向判断）"
        "你会说得更谨慎、更强调条件与证伪；在强项上才敢于给高置信度的观点。"
        "你敢于给明确观点和概率判断，但同时会说明「什么情况证伪」，从不模棱两可。"
        "你说话像给老板做路演，结论先行、逻辑支撑。"
    ),
    tools=[
        get_market_overview,
        get_index_kline,
        get_sector_performance,
        get_market_internals,
        get_research_track_record,
    ],
    llm=llm,
    verbose=AGENT_VERBOSE,
    allow_delegation=False,
    max_iter=20,
    respect_context_window=True,
)


# ══════════════════════════════════════════════════════════════════════════════
# Agent 5：撰稿人（专业投资顾问）
# ══════════════════════════════════════════════════════════════════════════════
writer = Agent(
    role="专业投资顾问",
    goal=(
        "把研究院的分析结论润色成一篇结构清晰、语言流畅、专业又易懂的每日美股复盘报告，"
        "配上指数 K 线图，保存归档，并准时、完整地发送到客户邮箱。"
    ),
    backstory=(
        "你是一位服务高净值客户的资深投资顾问，文笔老练、逻辑清楚、懂得把复杂的盘面语言翻译成人话。"
        "你的报告永远遵循「先说结论、再说依据、最后给策略」的结构，重点用加粗突出，风险提示绝不省略。"
        "你重视交付：报告一定会先存档，然后确认邮件发送成功，绝不半途而废。"
    ),
    tools=[generate_index_charts, get_sector_performance, save_report_file, send_email_report],
    llm=llm,
    verbose=AGENT_VERBOSE,
    allow_delegation=False,
    max_iter=15,
    respect_context_window=True,
)


AGENTS = [researcher, fact_checker, review_validator, analyzer, writer]
