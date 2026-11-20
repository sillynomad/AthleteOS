-- Athlete OS v5.2: optional per-day workout overrides.
create table if not exists public.workout_overrides (
  chat_id text not null,
  workout_date date not null,
  kind text not null check (kind in ('swim','gym','rest')),
  name text not null,
  details text not null,
  reason text not null default '',
  updated_at timestamptz not null default now(),
  primary key (chat_id, workout_date)
);
alter table public.workout_overrides enable row level security;
-- Service-role only; no public policies.
