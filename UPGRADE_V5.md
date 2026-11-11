# Athlete OS v5: combined v4 + swim performance

You are currently running v3. You do NOT need to deploy v4 separately.

1. In Supabase SQL Editor run `sql/upgrade_v4.sql` and then `sql/upgrade_v5.sql` in that order. Both are additive. Do not rerun the original schema or replace your database.
2. Replace your GitHub project files with the contents of this v5 ZIP. Keep the folder layout, especially `api/index.py` and `vercel.json`. Commit and let Vercel deploy.
3. No new Vercel environment variables or Strava authorization are required. Keep all current secrets and configuration.
4. Test in Telegram: `/coach`, `/dashboard`, `/swims`, `/swimdetail`. `/laps` is an alias for `/swimdetail`.
5. `/swimdetail` fetches Strava lap data for the latest swim when first requested, caches it in `strava_imports.lap_analysis`, and shows up to 15 laps with pace and average HR where available. If Strava returns no laps, the bot reports that instead of fabricating data.

Limitations: Strava laps may not be Garmin pool lengths or match your description's intervals; wrist HR can be unreliable in water. The overall moving pace uses moving time, which may not equal swim-only time. The first version does not fetch raw HR streams, infer pace drift or coach automatically from lap data; those require validation against actual lap output. Cached lap analysis is not refreshed unless cleared in Supabase.

Your v4 features (weight/waist, wellness, natural language, clinician clearance, compare, dashboard) are included. No need to install v4 separately.
