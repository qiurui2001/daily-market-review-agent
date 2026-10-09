# Stand up the Telegram Bot

The funnel is **Star → Telegram → user**. A Telegram bot pushes the daily report (and the latest
track-record line) to a channel or chat, so followers see each prediction and its result the next day.

## 1. Create the bot

1. Open Telegram, chat with [@BotFather](https://t.me/BotFather), send `/newbot`, follow prompts.
2. BotFather returns a token like `123456:ABC-DEF...`. Put it in `.env`:

```ini
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
```

## 2. Get the chat id

- **Channel:** add the bot as an admin of your channel, then post any message; fetch
  `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `result[].channel_post.chat.id`
  (usually `-100…`).
- **Private chat:** send the bot a `/start`, then read `result[].message.chat.id`.
- Put it in `.env`:

```ini
TELEGRAM_CHAT_ID=-1001234567890
```

## 3. How it sends

`notify.py` exposes `send_telegram(text)`. `main.py` calls it (best-effort) after delivery, posting a
short digest: date, top calls, and yesterday's verdict. If the token/chat is unset, it silently
no-ops.

You can also wire a **two-way bot** later (commands like `/today`, `/track`) — have it read
`TRACK_RECORD.md` and the latest report from the repo. That's the funnel's retention loop.

## 4. Etiquette

- Don't spam: one digest per trading day.
- Always include the disclaimer + a link back to the repo's track record.
- Publish the *verifiable* result, not a promise — that's the whole brand.
