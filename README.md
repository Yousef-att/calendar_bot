# Calendar Bot

Tag this bot on a reply to a Telegram message about a meeting, and it will
preview the event it extracted (date, time, topic, who, where) with a **✅
Set** button. Tapping it creates the event on your boss's Google Calendar.

## 1. Create the Telegram bot

1. Message [@BotFather](https://t.me/BotFather) -> `/newbot`, follow the
   prompts, save the token it gives you.
2. `/setprivacy` -> select your bot -> **Disable**. This makes sure the bot
   reliably sees full message context in the group (mentions already bypass
   privacy mode, but disabling it removes any edge case).
3. Add the bot to your group with your boss.

## 2. Set up Google Calendar access

1. In the [Google Cloud Console](https://console.cloud.google.com/), create
   a project (or reuse one) and enable the **Google Calendar API**.
2. Configure the OAuth consent screen (External, Testing mode is fine --
   add your own Google account as a test user).
3. Create an OAuth client of type **Desktop app**. Download it as
   `credentials.json` and place it in this folder.
4. Ask your boss to share his Google Calendar with your Google account,
   permission **"Make changes to events"**. Note his calendar's address
   (usually just his email) -- this is `BOSS_CALENDAR_ID`.

## 3. Local setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`: `TELEGRAM_BOT_TOKEN`, `OPENROUTER_API_KEY`, `BOSS_CALENDAR_ID`.

Then authorize your Google account once, interactively:

```bash
python google_auth_setup.py
```

This opens a browser to log in and approve access, then saves `token.json`
(a refresh token -- treat it like a password, never commit it).

**Test locally first** against your own calendar as a safe sandbox: point
`BOSS_CALENDAR_ID` in `.env` at your own email temporarily, run `python
bot.py`, and in the group reply-tag the bot on a message with a clear
date/time/topic. Confirm the preview looks right, tap Set, confirm the
event lands correctly (check the time). Then switch `BOSS_CALENDAR_ID` back
to your boss's calendar.

## 4. Deploy to Fly.io

```bash
fly launch --no-deploy   # picks up fly.toml; choose a unique app name if asked
fly secrets set \
  TELEGRAM_BOT_TOKEN=... \
  OPENROUTER_API_KEY=... \
  BOSS_CALENDAR_ID=... \
  GOOGLE_TOKEN_JSON="$(cat token.json)"
fly deploy
```

`GOOGLE_TOKEN_JSON` carries the exact contents of your local `token.json` as
a secret env var (there's no volume to upload the file itself onto) --
`config.py` writes it back out to `token.json` on every startup.

Check it came up: `fly logs` should show `Logged in as @yourbotname`. Send a
fresh tag in the real group to confirm long polling resumed after deploy.

## Notes / limitations

- No inline editing of a wrong extraction -- only Set. If the preview is
  wrong, just reply-tag the bot again (or fix the event manually).
- Either you or your boss can tap Set.
- Pending previews are kept in memory. If the bot restarts between showing a
  preview and someone tapping Set, that one preview goes stale (tapping it
  will say so) -- tag the bot again to regenerate it.
