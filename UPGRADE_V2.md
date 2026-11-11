# Athlete OS v2 — swim intelligence + complete activity sync

1. Run `sql/upgrade_v2.sql` in Supabase SQL Editor BEFORE deployment. Do not rerun the original schema to reset data.
2. Replace your GitHub project files with the contents of this ZIP, preserving existing Vercel environment variables. Deploy.
3. Send `/sync` to Telegram. Existing swim descriptions are fetched and analyzed, and previously excluded types such as Soccer and Elliptical are imported.
4. Send `/swims` to see your five most recent swim analyses. `/progress` still counts only swim and gym toward those targets.

Parser semantics: `+` indicates simultaneous equipment/technique; commas are sequential components; N x (..) repeats the entire group. SKPS is swim-kick-pull-swim, with no assumed component splits. Unknown notation is preserved for review.

Strava API privacy: your OAuth tokens remain in Supabase; never share them. Strava's rate limits apply. This sync makes detailed API calls for new or previously unparsed swims only.
