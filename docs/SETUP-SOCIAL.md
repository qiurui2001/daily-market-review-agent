# 📣 社交分发：X(Twitter) + Telegram 频道

本项目支持把每日复盘自动分发成**分层漏斗**：

| 层 | 平台 | 内容 | 代码 |
|---|---|---|---|
| 公域 | **X/Twitter** | 一句话结论 + 关键点位 + 命中率 + 频道链接 | `notify.build_teaser` |
| 私域(免费) | **Telegram 频道** | **大盘 + 板块** + 1 张 K 线图 | `notify.build_free_digest` |
| 私域(付费·预留) | Telegram Bot/群 | 多空点位、个性化持仓复盘、周/月报 | 后续跟进 |

> ⚠️ 本机（中国大陆）**无法访问** api.x.com / api.telegram.org。推送应在 **GitHub Actions（美国 runner）** 上跑；本地未配置凭据时**静默跳过**，不影响复盘。

---

## 一、Telegram 免费频道

1. 找 **@BotFather** → `/newbot` 建一个 bot，得到 **`TELEGRAM_BOT_TOKEN`**（形如 `123456:ABC...`）。
2. 新建一个**频道**（公开频道会得到 `t.me/xxx` 链接 → 填 `TELEGRAM_CHANNEL_URL`）。
3. 把 bot **加为频道管理员**（发帖权限）。
4. 取频道 ID（形如 `-1001234567890`）：
   - 在频道里随便发一条消息，浏览器打开
     `https://api.telegram.org/bot<TOKEN>/getUpdates`，找 `"chat":{"id":-100...,"title":"...","type":"channel"}`；
   - 或用 **@userinfobot** 转发一条频道消息获取。
5. 填环境变量：
   ```
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHANNEL_ID=-100...
   TELEGRAM_CHANNEL_URL=https://t.me/yourchannel
   ```

> 想同时私发给自己，可另设 `TELEGRAM_CHAT_ID`（个人 chat id）。

---

## 二、X / Twitter

1. 进 [X Developer Portal](https://developer.x.com/) 建 **Project + App**（免费档够每天 1 条）。
2. App 的 **User authentication settings**：权限选 **Read and Write**（OAuth 1.0a）。
3. **Keys and tokens** 生成：
   - `X_API_KEY`（API Key）
   - `X_API_SECRET`（API Key Secret）
   - `X_ACCESS_TOKEN`（Access Token）
   - `X_ACCESS_SECRET`（Access Token Secret）
4. 填环境变量（见 `.env.example`）。

> 依赖：`requests-oauthlib`（已在 `requirements.txt`）。图片走 v1.1 `media/upload`（base64），文本走 v2 `POST /2/tweets`。

---

## 三、接到 GitHub Actions（推荐）

在仓库 **Settings → Secrets and variables → Actions** 添加：
`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHANNEL_ID`、`TELEGRAM_CHANNEL_URL`、
`X_API_KEY`、`X_API_SECRET`、`X_ACCESS_TOKEN`、`X_ACCESS_SECRET`。

`daily.yml` 已把这些透传给 `main.py` / `crypto_main.py`；每日复盘结束后会自动：
1. 发**免费频道**（大盘+板块+图）；
2. 发**X 预告**（结论+点位+命中率+频道链接）。

---

## 四、本地手动测试（可选）

本机网络不可达时只能测**内容构造**（不发网络）：

```bash
python - <<'PY'
import notify
md = open("reports/美股复盘_2026-10-14.md", encoding="utf-8").read()
print(notify.build_teaser(md, "📈 美股复盘 | 2026-10-14"))
print("\n---\n")
print(notify.build_free_digest(md, "📈 美股复盘 | 2026-10-14")[:800])
PY
```

---

## 五、合规

全程仅研究参考、**不构成投资建议**；避免「稳赚/喊单/收益承诺」措辞（加密尤甚）。
付费层级如涉及收款，请确保符合平台与当地法规。
