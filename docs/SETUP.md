# Setup & Operation

## 1. Install

```bash
python 3.12 (recommended)
pip install -r requirements.txt
```

Dependencies: `crewai`, `requests`, `beautifulsoup4`, `lxml`, `python-dotenv`, `matplotlib`, `tzdata`.

> On Linux CI/machines, install a CJK font for the charts: `sudo apt-get install -y fonts-noto-cjk`.

## 2. Configure

```bash
cp .env.example .env
```

| Variable | Required | Default | Notes |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | ✅ | — | DeepSeek API key |
| `DEEPSEEK_BASE_URL` | | `https://api.deepseek.com/v1` | OpenAI-compatible endpoint |
| `DEEPSEEK_MODEL` | | `deepseek-v4-flash` | |
| `LLM_TEMPERATURE` | | `0.8` | creative agents |
| `LLM_MAX_TOKENS` | | `16384` | |
| `LLM_EMPTY_RETRY` / `LLM_RETRY_DELAY` | | `3` / `2` | empty-response retry |
| `SMTP_HOST` / `SMTP_PORT` | | `smtp.qq.com` / `587` | mail delivery (optional) |
| `SMTP_USER` / `SMTP_PASS` | | — | account / app password |
| `FROM_EMAIL` | | =`SMTP_USER` | |
| `REPORT_TO_EMAIL` | | — | leave empty to only archive |
| `AGENT_VERBOSE` | | `true` | |
| `HTTP_TIMEOUT` | | `20` | |
| `SECTOR_CACHE_TTL` / `SINA_KLINE_TTL` | | `600` / `1800` | caches (seconds) |
| `PRED_VOL_MULT` | | `1.0` | direction noise band = `mult × daily vol × √N` |
| `PRED_SHOCK_MULT` | | `2.5` | shock day = `|move| > mult × daily vol` |
| `PRED_VOL_LOOKBACK` | | `20` | vol estimate window |
| `PRED_MIN_LEVEL` / `PRED_MAX_LEVEL` | | `100` / `100000` | level range considered |
| `REGIME_TREND_GAP` | | `0.8` | MA10/MA30 gap (%) → trend vs chop |
| `REGIME_VOL_LOW` / `REGIME_VOL_HIGH` | | `0.8` / `1.5` | vol buckets (%) |
| `LEDGER_FILE` | | `prediction_ledger.jsonl` | append-only ledger (commit to git) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | | — | optional push (see SETUP-TELEGRAM) |
| `REPORT_DIR` / `OUTPUT_DIR` | | `reports` / `outputs` | |

> Changing any `PRED_*` / `REGIME_*` threshold is a **version change to the scoring spec**: it only
> applies to the future. Never re-score history.

## 3. Run

```bash
python main.py                          # review latest US trading day
python main.py --date 2026-10-09        # specific date
python main.py --to client@example.com  # override recipient
python main.py --quiet                  # no verbose logs
python main.py --self-review            # monthly self-review (default 30 days)
python main.py --self-review --days 90
python scripts/build_track_record.py    # refresh Live Track Record
```

After each run, `main.py` automatically commits the day's predictions to `prediction_ledger.jsonl`.

## 4. Verify & audit

```bash
python integrity.py                # summary + verify chain + reconcile
python integrity.py commit 2026-10-09
```

`verify_chain()` recomputes the hash chain (detects edits/cuts); `reconcile()` compares the ledger
with the current report files (detects edits after commit).

## 5. Data sources & known limits

- **Quotes** — Tencent (`qt.gtimg.cn`, `us` prefix): indices, ETFs, stocks. Stable.
- **Daily K-line** — Sina (`US_MinKService`): `.INX/.IXIC/.DJI/.NDX` + `AAPL`/`XLK`/… (Tencent's US
  K-line returns only 2 bars and is unusable).
- **Global / macro** — Sina: DXY (`DINIW`), Brent (`hf_OIL`), Gold (`hf_GC`), Nikkei, FTSE.
- **News** — Eastmoney 7×24. **Search** — Bing.
- **No free direct 10Y yield / DXY K-line / VIX K-line** → bonds proxied by TLT/IEF price direction;
  VIX snapshot only.

## 6. Scheduling

A GitHub Actions workflow (`.github/workflows/daily.yml`) runs after the US close, generates the
report, updates the ledger, and refreshes the Live Track Record. Configure repository secrets
(`DEEPSEEK_API_KEY`, `SMTP_*`) — see the workflow file.
