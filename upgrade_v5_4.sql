-- Athlete OS v5.4: Garmin activity metadata + Garmin pool-length details.
-- Run in Supabase SQL Editor BEFORE merging the PR.
-- Garmin is an enrichment source, not a second copy of Strava workout totals.
create table if not exists public.garmin_activities (
  activity_id bigint primary key,
  chat_id text not null,
  activity_date date not null,
  start_time_local text,
  activity_type text not null,
  name text not null default '',
  distance_m numeric(10,2),
  duration_s numeric(12,2),
  strava_activity_id text,
  match_status text not null default 'unmatched' check (match_status in ('matched','unmatched','ambiguous')),
  swim_length_count integer not null default 0,
  imported_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists garmin_activities_chat_date_idx on public.garmin_activities(chat_id,activity_date desc);
create index if not exists garmin_activities_strava_idx on public.garmin_activities(strava_activity_id);
create table if not exists public.garmin_swim_lengths (
  activity_id bigint not null references public.garmin_activities(activity_id) on delete cascade,
  length_index integer not null check (length_index > 0),
  start_time text,
  distance_m numeric(8,2) not null check (distance_m > 0),
  timer_s numeric(10,3) not null check (timer_s > 0),
  strokes integer check (strokes >= 0),
  stroke_type text,
  avg_hr integer,
  primary key(activity_id,length_index)
);
create index if not exists garmin_swim_lengths_activity_idx on public.garmin_swim_lengths(activity_id);
alter table public.garmin_activities enable row level security;
alter table public.garmin_swim_lengths enable row level security;
-- No public RLS policies: service-role-only access.
