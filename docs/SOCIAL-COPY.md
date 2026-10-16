# 社媒文案模板（X / Twitter + Telegram）

> 一句模板随时可用；带 `{{...}}` 的数字建议用 `python scripts/build_social_profile.py` 自动填充（读 `TRACK_RECORD.md` / `CRYPTO_TRACK_RECORD.md`）。

---

## 一、X / Twitter

**显示名（Name）**
- 中文：`每日复盘 Agent｜美股·加密`
- English：`Daily Market Review Agent`

**用户名（handle，建议）**：`@daily_review_agent` / `@mkt_review_agent` / `@review_agent_ai`（若被占用加下划线或数字）

**简介（Bio，≤160 字）**
- 中文：`每天收盘自动复盘美股&加密。每条预测写进哈希链台账、用真实行情客观判分——战绩公开可查。研究参考，非投资建议。`
- English：`Daily auto-review of US stocks & crypto. Every call is committed to a hash-chained ledger and scored against real prices — open track record. Research only, not advice.`

**主页链接**：填你的 Telegram 频道（`https://t.me/yourchannel`）或公开战绩页（GitHub `TRACK_RECORD.md`）。

**置顶推文（Pinned）模板**
```
📊 用 AI 每天复盘美股 & 加密，并把每条预测写进不可回改的哈希链台账、用真实行情客观判分。

公开战绩（自动更新）：
· 美股 {{US_N}} 条已判分，命中 {{US_HIT}}（宽松 {{US_LOOSE}}）
· 加密 {{CR_N}} 条已判分，命中 {{CR_HIT}}（宽松 {{CR_LOOSE}}）

点位与操作策略 → {{CHANNEL_URL}}
研究参考，非投资建议。
```

**发帖节奏**：每个交易日收盘后 1 条 `build_teaser` 预告（结论 + 点位 + 命中率 + 频道链接），周中可再发 1 条"战绩更新"。

---

## 二、Telegram 频道

**频道名**：`📊 每日复盘｜美股 · 加密`
**频道简介**：`每交易日发布美股&加密的「大盘 + 板块」公开复盘；点位与操作策略在付费/私域。研究参考，非投资建议。`

**置顶消息（Pin）**——由 `python scripts/build_social_profile.py` 自动生成（数字实时）：
```
📌 频道导航

▶️ 免费（每日）：
   · 美股复盘：大盘 + 板块/结构
   · 加密复盘：BTC/ETH 行情 + 杠杆与结构
🔒 私域（筹备中）：多空点位、操作策略、个性化持仓复盘、周报/月报
📊 公开战绩（确定性判分 · 哈希链防篡改 · 不可回改）：
   · 美股 {{US_N}} 条已判分，命中 {{US_HIT}}（宽松 {{US_LOOSE}}）
   · 加密 {{CR_N}} 条已判分，命中 {{CR_HIT}}（宽松 {{CR_LOOSE}}）
🔗 台账原始数据：{{REPO_URL}}/blob/main/TRACK_RECORD.md
⚠️ 仅供研究参考，不构成任何投资建议。
```

**群规 / 首次加入欢迎语**
```
欢迎 👋 本频道只做「公开复盘 + 透明战绩」，不喊单、不承诺收益。
所有内容仅供研究参考，据此操作风险自负。
点位/策略类内容在私域，敬请留意后续开放。
```

---

## 三、通用免责声明
> 本账号/频道及所载内容仅供研究与学习参考，**不构成任何投资建议**。市场有风险，投资须谨慎；据此操作，风险自负。
