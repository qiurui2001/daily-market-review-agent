🌐 [English](README.md) · **中文**

![Python](https://img.shields.io/badge/python-3.12-blue)
![CrewAI](https://img.shields.io/badge/powered%20by-CrewAI-6f42c1)
![License](https://img.shields.io/badge/license-pending-lightgrey)
![Track Record](https://img.shields.io/badge/track%20record-live-orange)

# Daily Market Review Agent · 美股复盘 Agent

**一个自主的 AI 市场研究 Agent：研究 → 交叉核验 → 预测 → 验证。**

**每一条预测都被记录**——写入只追加、哈希链台账，并用真实行情**客观判分**。

[🔴 在线 Demo](docs/SETUP-DEMO.md) · [🤖 Telegram 机器人](docs/SETUP-TELEGRAM.md) · [📈 今日报告](LATEST_REPORT.md) · [📊 战绩页](TRACK_RECORD.md)

> ⚠️ 本项目仅供研究参考，不构成任何投资建议。

---

## 📊 Live Track Record（实时战绩）

<!-- TRACK_RECORD:START -->
_📉 数据积累中——系统运行几天后即出现实时战绩。_

_每条预测都写入 `prediction_ledger.jsonl`（只追加、哈希链），并自动用真实行情判分。_
<!-- TRACK_RECORD:END -->

---

## 为什么它不一样

市面上大多数「AI 股票 agent」生成一段像模像样的话，然后就忘了。这个更像一个**有简历的分析师**：

- **先预测，再被打分**：每天的观点白纸黑字写下、锁进台账，次日用真实价格判分——**不是模型自己给自己打分**。
- **判分是确定性的**：支撑/压力位对照真实高低点；方向用**波动率噪音带**衡量——只是随机晃动的走势记为「未定」，不算命中。
- **历史不可回改**：预测存在**只追加、哈希链**台账里，改一个字符 `verify_ledger_integrity` 就会失败。
- **它知道自己哪里弱**：战绩按**能力维度 × 市场体制 × 视野 × 置信度**分桶；月度**自省**用算出来的错误结构追问「我为什么老错」。

> 代码可以被复制，**这份复利、防篡改的历史战绩不能。**

完整方法论见 **[预测核验方法论.md](预测核验方法论.md)**（或 [English](METHODOLOGY.md)）。

---

## 工作流

```
研究员 → 核查员 → 复盘校验员 → 分析师 → 撰稿人 → 交付
 收集情报   独立复核/防幻觉  检索往期+确定性核验  量价/轮动/结构  撰写+配图  存档+发信
      │
      └── 每条预测 ──► prediction_ledger.jsonl（哈希链）──► 次日自动判分
                                                      └──► Live Track Record
```

| 阶段 | Agent | 职责 |
|---|---|---|
| 1 | **研究员** | 采集指数、11 大 SPDR 行业 ETF、市场内部结构（七巨头/风格/VIX）、宏观外围、消息面 |
| 2 | **事实核查员** | 重新取数逐项交叉验证，标记幻觉 |
| 3 | **复盘校验员** | 检索往期预测、**确定性判分**、补充归因 |
| 4 | **盘面分析师** | 量价、轮动、内部结构、支撑压力、情景与概率 |
| 5 | **专业投资顾问** | 渲染报告（含 K 线图）、归档、发邮件 |

板块表、K 线图、判分都由代码确定性产出，LLM 只做组织与解读。

---

## 覆盖范围（美股）

`标普500 · 纳斯达克 · 道琼斯 · 纳指100 · 罗素2000 · VIX` · 11 大 SPDR 行业 ETF ·
科技七巨头 · 美债(TLT/IEF) · 美元指数 · 原油 · 黄金 · 亚太欧股 · 7×24 快讯 · 财报与美联储。

数据源全部免费、无需 API Key：腾讯行情、新浪美股 K 线、新浪全球、东方财富快讯、必应搜索。

---

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env          # 填 DEEPSEEK_API_KEY（可选：SMTP）
python main.py                # 复盘最近一个美股交易日
python main.py --self-review  # 月度自省（“我为什么错了？”）
python scripts/build_track_record.py   # 刷新 Live Track Record
```

> 美股 16:00（美东）收盘 ≈ 北京时间次日 04:00/05:00。建议收盘后运行；默认复盘日期为**美东最近交易日**。

完整配置见 **[docs/SETUP.md](docs/SETUP.md)**；在线 Demo 与 Telegram 见
**[docs/SETUP-DEMO.md](docs/SETUP-DEMO.md) / [docs/SETUP-TELEGRAM.md](docs/SETUP-TELEGRAM.md)**。

---

## 文档

| 文档 | 说明 |
|---|---|
| [预测核验方法论.md](预测核验方法论.md) · [English](METHODOLOGY.md) | 判分确定性、抗噪、统计纪律、红线清单（**核心**） |
| [TRACK_RECORD.md](TRACK_RECORD.md) | 实时、自动更新的战绩页 |
| [docs/SETUP.md](docs/SETUP.md) | 配置与运行 |
| [docs/SETUP-DEMO.md](docs/SETUP-DEMO.md) | 搭建在线 Demo |
| [docs/SETUP-TELEGRAM.md](docs/SETUP-TELEGRAM.md) | 搭建 Telegram 机器人 |
| [BUGFIX-LLM空响应重试.md](BUGFIX-LLM空响应重试.md) | 线上问题复盘 |

---

## Roadmap

- [x] 确定性预测判分 + 防篡改台账
- [x] Live Track Record（GitHub Actions 自动更新）
- [x] 月度自省
- [ ] 公开在线 Demo + Telegram 机器人
- [ ] 基准对比（动量 / 随机 / 常多）
- [ ] 宏观事件日历（用于冲击日标记）
- [ ] **选择并添加 `LICENSE`**（如 MIT）——待定

---

## 免责声明

仅供研究与学习参考，**不构成任何投资建议**。市场有风险，请自行判断。
