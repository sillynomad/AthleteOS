# Athlete OS — Daily Coach MVP

Telegram-first daily training coach for the 12-week lean swimmer physique programme. Starting weight 75 kg; fat-loss goal; three swims and two gym sessions/week. Knee-protective weeks 1–3. **Garmin is not connected yet.**

## What works
- Telegram commands `/start`, `/help`, `/today`, `/plan`, `/progress`, `/weight 75`, `/knee 0`, `/done swim 2800`, `/done gym`, `/sync`.
- Private single-user access by Telegram chat ID and webhook secret.
- Supabase storage for logged activities, weight, knee symptoms, deduplicated Telegram updates and daily notifications.
- Daily scheduled Telegram message at **08:00 Singapore time** via Vercel cron (00:00 UTC). The cron runs once daily, not at an exact guaranteed second.
- 12-week workout plan based on Monday start date (configurable); no automatic medical clearance after week 3.

## Deploy (Vercel + Supabase + Telegram)
1. Create a **new Supabase project** (or use a separate schema/project from Garden Habitat). In Supabase SQL Editor run `sql/schema.sql`.
2. In Telegram, open **@BotFather**, send `/newbot`, and securely copy the bot token. Send your bot `/start` once. Obtain your numerical Telegram chat ID using Telegram's `getUpdates` API *before setting the webhook*: `https://api.telegram.org/bot<TOKEN>/getUpdates` (keep token private; never paste it into chats or public issues). Find `message.chat.id`. You can instead use a trusted Telegram chat-ID bot.
3. Push this folder to a **private GitHub repository**. In Vercel, import that repository as a new project. Choose Other framework and Python runtime auto-detection. Deploy.
4. Add Vercel environment variables listed in `.env.example`. Obtain Supabase URL and service-role secret from Supabase project settings; **server-side only**, never `NEXT_PUBLIC_`. Generate long random `TELEGRAM_WEBHOOK_SECRET` (letters, numbers, underscore, hyphen) and `CRON_SECRET` (e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`). Set `PROGRAM_START_DATE` to the Monday you begin, e.g. `2026-11-16`.
5. Redeploy after adding env variables. Visit `https://YOUR_DOMAIN/api/health` to confirm `ok:true`.
6. Register Telegram webhook (replace placeholders locally, never share token):
   ```bash
   curl -sS -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
     --data-urlencode "url=https://YOUR_DOMAIN/api/telegram" \
     --data-urlencode "secret_token=$TELEGRAM_WEBHOOK_SECRET" \
     -d 'allowed_updates=["message"]'
   ```
7. Message your bot `/today`, `/plan`, `/weight 75`, `/knee 0`, `/done swim 2500`, then `/progress`.
8. Test daily job manually (optional):
   ```bash
   curl -H "Authorization: Bearer $CRON_SECRET" "https://YOUR_DOMAIN/api/daily"
   ```
   This sends today's message once; later same-day calls return `already sent`.
9. Check Vercel function logs for webhook errors and confirm Supabase rows. On Vercel plans where daily cron scheduling is unavailable, use an external scheduler to GET `/api/daily` with `Authorization: Bearer <CRON_SECRET>`; avoid exposing the secret in a URL.

## Known MVP limitations
- `/sync` reports that Garmin integration is **not connected**. Garmin data is not fetched, and there is no Garmin credential handling. Official Garmin access requires an approved integration; an unofficial library should not be treated as a reliable production dependency.
- No Strava import, swim-set parsing, nutrition logging, strength sets, automatic coaching AI or body-composition dashboard yet.
- Workout plan is fixed by weekday; it doesn't automatically adapt to missed workouts.
- Weight and pain logs are append-only. `/progress` reflects only manually logged activities.
- The webhook's idempotency check is best-effort under concurrent delivery. A rare retry between DB write and notification can leave a missing reply; review logs if this occurs.
- This is coaching support, not a medical decision engine. Stop/modify painful exercise and follow your treating clinician's guidance.
- Calorie trial of 2,200–2,400 kcal/day is a starting estimate, not an individually measured maintenance calculation.

## Security
- Keep GitHub repository private; don't commit `.env`.
- Restrict bot to `TELEGRAM_CHAT_ID`, validate Telegram webhook secret, and protect scheduled endpoint with `CRON_SECRET`.
- Supabase tables have RLS enabled with no public access policies; service-role secret stays in Vercel server environment.
- Rotate secrets if accidentally exposed.


## Routing fix (11 Nov 2026)
This version uses explicit Vercel rewrites to `api/index.py?route=...` and dispatches by the route query parameter. Redeploy with the repository root containing `api/` and `vercel.json`. Test `/api/health` after deployment.


## v5
See `UPGRADE_V5.md` for combined v4 + lap analytics deployment. `/swimdetail` fetches and caches latest Strava swim lap pace and heart rate.
