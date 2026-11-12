# Swim streams diagnostic (v5.1)

This is a full replacement for the existing v5 source code. No SQL migrations, new environment variables, or Strava reauthorization are required.

1. Replace the existing GitHub project files with the contents of this ZIP, preserving folder structure.
2. Commit and wait for Vercel deployment.
3. In Telegram, send `/swimstreams` and paste the response into ChatGPT.

The command queries Strava streams for the most recent swim and reports which streams exist, sample counts, and approximate time/distance sampling resolution. It does not expose credentials or raw heart-rate data. It does not modify or cache your activities.

Strava streams are not guaranteed to contain Garmin pool-length boundaries, stroke counts, SWOLF or 50-m length metrics.
