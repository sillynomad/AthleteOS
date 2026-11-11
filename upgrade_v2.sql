-- Run once in Supabase SQL Editor. Preserves all existing data.
alter table public.activities drop constraint if exists activities_kind_check;
alter table public.activities add constraint activities_kind_check check (kind in ('swim','gym','run','bike','other'));
alter table public.strava_imports add column if not exists swim_analysis jsonb;
