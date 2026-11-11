
-- Strava credentials: server-only access, never expose service role to clients.
create table if not exists public.strava_connections (id integer primary key check (id=1), access_token text not null, refresh_token text not null, expires_at bigint not null, athlete_id text, created_at timestamptz not null default now());
create table if not exists public.strava_imports (activity_id text primary key, name text, description text, sport_type text, moving_time_s integer, elapsed_time_s integer, average_heartrate numeric, distance_m integer, activity_date date, created_at timestamptz not null default now());
alter table public.strava_connections enable row level security;
alter table public.strava_imports enable row level security;
