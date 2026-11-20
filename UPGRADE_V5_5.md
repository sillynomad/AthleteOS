# Athlete OS v5.5 — Garmin swim efficiency

No SQL migration needed: reads existing `garmin_activities` and `garmin_swim_lengths` from v5.4.

## New Telegram command
`/swimtrends`: latest 12 imported pool swims, current pace, strokes per length, calculated SWOLF, first-vs-second-half active-length pace, recent-session history, and a cautious technique/pacing recommendation.

## Comparison guardrails
- At least 3 imported pool swims before interpreting trends.
- Historical stroke benchmark only against older sessions with **same pool length**, pace within 5%, distance within 25%; otherwise no improvement claim.
- SWOLF is descriptive and sensitive to stroke type, drills, pool length and watch recording.
- Second-half pacing is based on active-length time and does not include rest. A >5% pace change is a prompt to review, not proof of fatigue.
- Never recommends intensity increases solely from swim data; continue following recovery and knee-aware guidance in `/coach`.
- Read-only analysis; no new workout totals or writes. Garmin FIT sync remains v5.4.

## Validation
1. Deploy preview and verify Python import succeeds.
2. Run `/swimtrends` after `/garminsync`. With only two imported swims, expect 'Baseline building'.
3. Run `/swimanalysis` and `/coach` to verify no regressions.
4. As more swims accumulate, verify the older-session benchmark requires comparable pool size, pace and distance.

## Future
A fuller fatigue model requires drill/rest segmentation, recovery logs and multiple comparable sessions. This release intentionally does not diagnose fatigue or alter the scheduled workout automatically.
