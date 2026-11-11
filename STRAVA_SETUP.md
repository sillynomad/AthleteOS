# Athlete OS Strava v1 setup

1. Run `sql/strava.sql` in Supabase SQL Editor.
2. In Vercel, retain all existing environment variables and add `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, and `APP_DOMAIN=athlete-os-brown.vercel.app`. The first two were already added by you.
3. Deploy this code using the same GitHub repository and redeploy in Vercel.
4. Confirm Strava Authorization Callback Domain is `athlete-os-brown.vercel.app`.
5. In your private Telegram chat with the bot send `/connect`, follow the link, and authorize. Then send `/sync` and `/progress`.

## Behavior and limitations
- The `/sync` command imports up to the last 45 days of swim, gym, run and bike workouts. The existing 08:00 Singapore-time cron also syncs once a day before sending coaching. This is NOT instant webhook sync.
- The first sync may import historical activities. Repeated syncs skip Strava activity IDs already imported. Manually logged `/done` entries are not automatically deduplicated against Strava activities.
- Strava summaries include distance, date, moving time, elapsed time, and heart rate if provided; descriptions and swim intervals are not yet fetched.
- This single-user MVP uses the service-role key on the backend only; RLS is enabled on both new tables. The OAuth link is sent only to your private Telegram chat and expires in 15 minutes.
- Never share your Strava Client Secret, Supabase service-role key or Telegram bot token.
