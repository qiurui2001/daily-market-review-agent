# Stand up the Live Demo

The README links to a **Live Demo** so visitors can see "what did it predict, and how did it do?"
without cloning anything. Pick one of the options below and put its URL in `README.md` /
`README.zh-CN.md` (the `[🔴 Try the Live Demo](...)` link).

## Option A — GitHub Pages (simplest, static)

Publish the generated reports and the track record as a static site.

1. Create `docs/index.md` that renders `TRACK_RECORD.md` (or symlink/copy it on build).
2. Repo **Settings → Pages → Deploy from branch → `main` / `/docs`**.
3. The workflow already commits `TRACK_RECORD.md`; add a step to copy it into `docs/` and let Pages
   serve it. Your demo URL becomes `https://<user>.github.io/<repo>/`.
4. Update the README link.

## Option B — Streamlit / Gradio app

Host a tiny app that shows the ledger + latest report.

```python
# app.py (Streamlit)
import streamlit as st, json, pathlib
st.title("Daily Market Review — Live Track Record")
st.markdown(pathlib.Path("TRACK_RECORD.md").read_text(encoding="utf-8"))
ledger = pathlib.Path("prediction_ledger.jsonl")
if ledger.exists():
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    st.metric("Committed days", len(rows))
    st.dataframe([r["items"] for r in rows[-1:]])
```

Deploy on Streamlit Community Cloud / Render / Fly.io, then link the URL.

## Option C — Just the track record

If you don't want to host anything, point the "Live Demo" link at the **raw, auto-updated**
`TRACK_RECORD.md` on GitHub:

```
https://github.com/<user>/<repo>/blob/main/TRACK_RECORD.md
```

## Keep it honest

Whatever you host, it must come **directly from the ledger / deterministic scorer** — no manual
editing of numbers. The whole point is that the record is verifiable.
