# Athlete OS v5.4 — Garmin FIT enrichment

## Deployment order
1. Run `upgrade_v5_4.sql` in Supabase SQL Editor. The migration is additive, RLS-enabled and contains no public policies.
2. Confirm Vercel Production has `GARMIN_PERSONAL_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `TELEGRAM_CHAT_ID`, and the existing Telegram/Strava settings.
3. Check CI/preview tests; merge only after review. Vercel must install `fitparse` from requirements.
4. In Telegram run `/garmin`, then `/garminsync`, then `/swimanalysis`.
5. Check Supabase `garmin_activities` and `garmin_swim_lengths`. For Nov 18 Garmin ID 25113613520, expect 60 x 25 m pool-length records if the downloaded ZIP matches the supplied original FIT file.

## Behavior
- Garmin's documented `GET /download-service/files/activity/{activityId}` returns a ZIP containing the FIT recording.
- `/garminsync` scans the latest 5 activities; scheduled daily sync scans the latest 2 to limit execution time.
- Activities are upserted by Garmin activity ID; swim lengths by (Garmin activity ID, length index). Repeated runs do not duplicate these records.
- Garmin activity records enrich Strava data and **never** insert into the existing `activities` totals table.
- Matching is conservative: same date, compatible sport, close distance, and a unique Strava candidate. Ambiguous matches remain unlinked. This is not a reliable identity join if multiple same-day similar workouts exist.
- `/swimanalysis` prefers the latest imported Garmin pool swim; falls back to Strava if none has FIT lengths. This is a change in default source; report labels make it explicit.
- Stores summary and length-level fields only, not raw FIT binaries, GPS or raw HR time series.
- No Garmin key, access token or ZIP bytes are persisted in Supabase.

## Known limitations / acceptance checks
- **Draft and untested live:** token endpoint and activity listing were already verified by `/garmin`, but FIT download and Vercel `fitparse` have not yet been tested.
- Cron can time out if Garmin is slow; the bounded 2-activity scan may miss workouts on days with many activities. Run `/garminsync` manually for backfill. A future paginated cursor and dedicated sync cron are preferable.
- A failure after partial length upserts is retried; counts are updated only after all length batches succeed.
- Original Garmin FIT files may not include valid pool-length metadata for open-water swims. Those remain metadata-only.
- Garmin swim length times reflect active length timers; resting intervals are not part of length times. SWOLF is calculated from recorded strokes plus seconds per pool length.
- Confirm `/coach`, `/sync`, `/garmin`, `/swimanalysis`, `/garminsync` all work after deployment.
- Compare Nov 18 with previously supplied FIT file and confirm exactly 1,500 m, 60 lengths, ~25:36.5 swimming timer.
- No automatic retroactive full history import or Strava-to-Garmin workout merging in the main `activities` table; matching is metadata linkage only.

## Official reference
Garmin Personal API Swagger: https://developer.garmin.com/gc-developer-program/personal/swagger-docs/
Garmin Python client: https://github.com/garmin/connect-personal-api-python
