# Athlete OS v4 — upgrade from v3

1. Back up Supabase data, then run `sql/upgrade_v4.sql` in Supabase SQL Editor. Do not rerun schema.sql or remove old tables.
2. Replace project files in GitHub with this ZIP, preserving your existing Vercel environment variables and the webhook.
3. Deploy in Vercel. Verify `/api/health` still returns `ok: true`.
4. In Telegram try `/checkin fatigue 3 sleep 7 knee 1 achilles 0`, `/waist 82`, `/trend`, `/coach`, `/compare`, `/dashboard`, `/runstatus`.
5. The daily cron remains at 08:00 Singapore time. On Mondays it also sends a PNG weekly dashboard. Manual `/dashboard` works any day.

## Notes
- The original `/weight`, `/knee`, `/sync`, `/swims`, `/progress`, `/today`, `/coach`, `/connect` and daily cron remain.
- Natural-language recovery messages are keyword based, **not an LLM conversation**. Text is stored in a private table. Do not send intimate photos or confidential medical documents to the bot.
- `/clearance yes` records your report of **explicit clinician clearance**; it does not automatically prescribe running. `/runstatus` requires current knee and Achilles scores and offers cautious guidance only.
- `/compare [YYYY-MM-DD]` compares recorded recommendations to activities logged on that date, not exact interval matching. Swim notes are shown if available.
- Body weight trend compares the latest seven days to the previous seven days. Waist is optional and should be measured consistently every two weeks.
- Telegram images are generated on the server with Pillow. If `/dashboard` fails, check Vercel logs and package deployment.
- No photo storage or calorie logging in v4.
