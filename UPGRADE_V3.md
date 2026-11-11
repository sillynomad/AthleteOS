# Athlete OS v3: adaptive Telegram coaching

1. Run `sql/upgrade_v3.sql` in your existing Supabase SQL Editor.
2. Replace the project files in GitHub with the files in this archive (keep existing Vercel environment variables).
3. Wait for Vercel to deploy.
4. Send `/coach` to Telegram to preview the new daily recommendation with Unicode progress bars.
5. Check `coaching_recommendations` in Supabase: one saved prescription per date. Repeating `/coach` updates that day's record; the morning cron sends once a day.

The existing `/today` command continues to show the fixed baseline programme; `/coach` shows an adaptive recommendation. Morning `/api/daily` now sends `/coach`-style content. The next Strava sync will still import actual sessions as before. Detailed prescribed-vs-actual set comparisons and graphical PNG dashboards are **not yet implemented**.

Rules: rest days remain rest; existing workouts today prevent double-session recommendations; recent knee pain >=3 triggers a caution; hitting weekly swim/gym goals suggests recovery or lower volume. These are conservative rules, not medical clearance. `/knee` scores should be updated regularly.

Telegram supports Unicode progress bars, but alignment may vary by font/device. No additional API keys required.
