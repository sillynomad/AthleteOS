# Swim insights + Garmin FIT validation (proposed)

## What changed
- `/swimanalysis` now displays all estimated 50 m segments (subject to Telegram's existing 3,900-character message limit), 500 m blocks, pace variability and a cautious HR trend.
- The HR trend excludes the first six 50 m segments and implausible values. This is **not** a validated cardiac-drift measure.
- New local utility: `tools/inspect_garmin_fit.py`. It reads pool-length messages from a Garmin FIT export, including length time, strokes and estimated SWOLF where recorded.

## Garmin validation workflow
1. Open the swim activity in Garmin Connect on the web.
2. Use the activity's export menu to download the **original FIT file** (not GPX or TCX).
3. On your own computer: `python -m pip install fitparse`.
4. Run `python tools/inspect_garmin_fit.py activity.fit --csv lengths.csv`.
5. Compare length times against the corresponding Strava estimated splits.

No Garmin credentials are requested or stored. The script is offline. A Garmin Connect API integration is **not** included: reliable automatic access would require an approved Garmin integration and its authorization flow. The FIT utility does **not** yet import lengths into Supabase or Telegram.

## Validation before merge
- Run `python -m py_compile index.py tools/inspect_garmin_fit.py`.
- Test `/swimanalysis` on a continuous 1,500 m swim and on an interval session with rests.
- Check Telegram truncation for longer swims. A future update should paginate or send an image.
- Validate SWOLF and strokes against Garmin Connect's display: the script's SWOLF estimate is length duration in seconds + stroke count, where FIT fields are present.
