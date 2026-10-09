<!-- Badges -->
🌐 **English** · [中文](README.zh-CN.md)

![Python](https://img.shields.io/badge/python-3.12-blue)
![CrewAI](https://img.shields.io/badge/powered%20by-CrewAI-6f42c1)
![License](https://img.shields.io/badge/license-pending-lightgrey)
![Track Record](https://img.shields.io/badge/track%20record-live-orange)

# Daily Market Review Agent

**An autonomous AI market research agent that researches → debates → predicts → verifies.**

**Every prediction is recorded** — committed to an append-only, hash-chained ledger, and scored
objectively against what the market actually did.

[🔴 Try the Live Demo](docs/SETUP-DEMO.md) · [🤖 Telegram Bot](docs/SETUP-TELEGRAM.md) · [📈 Today's Report](LATEST_REPORT.md) · [📊 Track Record](TRACK_RECORD.md)

> ⚠️ Research tooling only. Not investment advice.

---

## 📊 Live Track Record

<!-- TRACK_RECORD:START -->
_📉 Collecting data — the live track record begins once the agent has run for a few days._

_Every prediction is committed to `prediction_ledger.jsonl` (append-only, hash-chained) and scored automatically against what the market actually did._
<!-- TRACK_RECORD:END -->

<details>
<summary>What the live record looks like once it's running (example)</summary>

```
Overall hit rate: 63.2% (95% CI 56–70) · 214 scored predictions · 48 trading days

| Capability | Hit rate | n  |
|------------|----------|----|
| Direction  | 61%      | 96 |
| Sector     | 71%      | 52 |
| Event      | 68%      | 28 |
| Risk       | 76%      | 38 |

Latest calls
| Date       | Instrument | Call                                | Result      |
|------------|------------|-------------------------------------|-------------|
| 2026-10-09 | 标普500    | resistance 7,850 · support 7,700    | ⏳ Pending  |
| 2026-10-08 | 纳斯达克   | break above 27,500 → bullish        | ✅ Hit      |
| 2026-10-08 | 能源(XLE)  | sector liderança rotation           | ⚠️ Partial  |
```

</details>

---

## Why this is different

Most "AI stock agents" generate a plausible paragraph and forget it. This one behaves like an
**analyst with a résumé**:

- **It predicts, then it's judged.** Each day's forecast is written down, committed, and next day
  scored against real prices — not by the model rating itself.
- **Judging is deterministic.** Support/resistance levels are tested against actual highs/lows;
  direction is measured against a **volatility noise band** (a move that's just noise is recorded
  as *undecided*, not as a "hit").
- **The history can't be rewritten.** Predictions live in an append-only **hash-chained ledger**.
  Change one character and `verify_ledger_integrity` fails.
- **It knows where it's weak.** The track record is sliced by **capability × market regime ×
  horizon × confidence**, and a monthly **self-review** asks *"why have I been wrong?"* using
  computed error structure — not vibes.

> The code can be copied. **The compounding, tamper-evident track record cannot.**

Read the full reasoning in **[METHODOLOGY.md](METHODOLOGY.md)** (or [中文](预测核验方法论.md)).

---

## How it works

```
Researcher → Fact-checker → Review-validator → Analyst → Writer → Deliver
   gather       独立复核/防幻觉    检索往期+确定性核验   量价/轮动/结构   撰写+配图   存档+发信
      │
      └── every prediction ──► prediction_ledger.jsonl (hash-chained) ──► auto-scored next day
                                                                    └──► Live Track Record
```

| Stage | Agent | What it does |
|---|---|---|
| 1 | **Researcher** | Collects indices, 11 SPDR sector ETFs, market internals (Mag-7 / style / VIX), macro & global, news |
| 2 | **Fact-checker** | Re-fetches data and cross-verifies every number; flags hallucinations |
| 3 | **Review-validator** | Pulls past predictions, **scores them deterministically**, adds attribution |
| 4 | **Analyst** | Price/volume, rotation, internals, support/resistance, scenarios & probabilities |
| 5 | **Writer** | Renders the report with K-line charts, files it, emails it |

Deterministic, code-produced data (sector tables, charts, scoring) — the LLM only organizes and interprets.

---

## What it covers (US market)

`S&P 500 · Nasdaq · Dow · Nasdaq-100 · Russell 2000 · VIX` ·
11 SPDR sector ETFs · Magnificent 7 · bonds (TLT/IEF) · DXY · oil · gold · Asia/Europe ·
7×24 news · earnings & Fed.

Data sources (free, no API keys): Tencent quotes, Sina US K-line, Sina global, Eastmoney news, Bing search.

---

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env          # then fill DEEPSEEK_API_KEY (+ optional SMTP)
python main.py                # review the latest US trading day
python main.py --self-review  # monthly self-review ("why was I wrong?")
python scripts/build_track_record.py   # refresh the Live Track Record
```

> US close 16:00 ET ≈ 04:00/05:00 Beijing. Run after the close; the default review date is the
> latest US trading day (Eastern time).

See **[docs/SETUP.md](docs/SETUP.md)** for the full configuration reference, and
**[docs/SETUP-DEMO.md](docs/SETUP-DEMO.md) / [docs/SETUP-TELEGRAM.md](docs/SETUP-TELEGRAM.md)**
to wire up the Live Demo and Telegram bot.

---

## Documentation

| Doc | 说明 |
|---|---|
| [METHODOLOGY.md](METHODOLOGY.md) · [中文](预测核验方法论.md) | 判分确定性、抗噪、统计纪律、红线清单（**核心**） |
| [TRACK_RECORD.md](TRACK_RECORD.md) | Live, auto-updated performance record |
| [docs/SETUP.md](docs/SETUP.md) | Configuration & operation |
| [docs/SETUP-DEMO.md](docs/SETUP-DEMO.md) | Stand up the Live Demo link |
| [docs/SETUP-TELEGRAM.md](docs/SETUP-TELEGRAM.md) | Stand up the Telegram bot |
| [BUGFIX-LLM空响应重试.md](BUGFIX-LLM空响应重试.md) | Incident post-mortem |

---

## Roadmap

- [x] Deterministic prediction scoring & tamper-evident ledger
- [x] Live Track Record (auto-updated via GitHub Actions)
- [x] Monthly self-review
- [ ] Public Live Demo + Telegram bot
- [ ] Benchmark comparison (momentum / random / always-long)
- [ ] Macro event calendar for shock-day tagging
- [ ] **Choose & add a `LICENSE`** (e.g. MIT) — pending owner decision

---

## Disclaimer

Research and educational use only. **Not investment advice.** Markets are risky; do your own work.
