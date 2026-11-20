# Athlete OS v5.6 — 90-day Garmin pool-swim backfill

## Purpose
Import the 90 days preceding the first run of `/garminbackfill`, capturing pre-race, transition and post-knee-injury swim sessions. The 90-day cutoff is fixed in Supabase on first run, so repeated commands continue the same historical window.

## Deployment
1. Run `upgrade_v5_6.sql` in the Supabase SQL Editor.
2. Review and deploy the PR; existing `GARMIN_PERSONAL_API_KEY` and Supabase environment variables are reused.
3. In Telegram send `/garminbackfill`. Repeat until it reports COMPLETE.
4. Use `/garminbackfillstatus` to check persistent progress. `/garminbackfill reset` starts a fresh 90-day scan (existing FIT imports are not duplicated).
5. Run `/swimtrends` to review the most recent 12 imported pool swims.

## Mechanics
- Garmin activity list is paginated by `start` and `limit` and assumed newest-first, as in the existing integration.
- Each request scans up to ten activities and imports at most one new pool swim FIT to reduce Vercel timeout risk.
- Cursor is persisted after each successfully processed activity; failed FIT imports retain the offset for a later retry.
- Non-swim activities advance the cursor but are not imported by this historical backfill. Strava already holds historical multisport training data.
- Existing Garmin swims with positive `swim_length_count` are skipped. New swims use existing Garmin activity and length tables and unique keys; no writes to `activities` totals.
- The status records scanned activities, imported/existing swims, errors and next offset. `/garminbackfill` can be repeated safely.

## Caveats and checks
- **Not yet tested live.** Validate on the first few commands and inspect Vercel logs for timeout or Garmin API errors.
- May require many Telegram invocations for 90 days of training. No automatic rapid background job is added.
- The existing `/swimtrends` command currently analyses only the latest 12 imported pool swims; a later period-comparison feature is needed to compare all pre-race vs post-injury sessions.
- The historical backfill covers only Garmin pool swims. It does not label injury dates, diagnose injury or calculate full triathlon training load.
- The Garmin API may impose rate limits; retry later if errors occur.
- A data gap in Garmin's activity history cannot be filled from this API alone.
