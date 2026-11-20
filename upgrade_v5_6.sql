-- Athlete OS v5.6: resumable 90-day Garmin swim backfill.
-- Run BEFORE deploying the v5.6 code. Private server-only cursor state.
create table if not exists public.garmin_backfill_state (
  chat_id text primary key,
  cutoff_date date not null,
  next_offset integer not null default 0 check (next_offset >= 0),
  scanned integer not null default 0 check (scanned >= 0),
  swims_imported integer not null default 0 check (swims_imported >= 0),
  swims_existing integer not null default 0 check (swims_existing >= 0),
  failed_count integer not null default 0 check (failed_count >= 0),
  status text not null default 'running' check (status in ('running','complete','error')),
  last_error text,
  updated_at timestamptz not null default now()
);
alter table public.garmin_backfill_state enable row level security;
-- No public RLS policies; only Supabase service role may read/write.
