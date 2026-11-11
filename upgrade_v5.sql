-- Run AFTER sql/upgrade_v4.sql if upgrading from v3.
-- Safe additive migration; keeps all existing activities and swim descriptions.
alter table public.strava_imports add column if not exists lap_analysis jsonb;
