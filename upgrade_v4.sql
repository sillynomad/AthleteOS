-- Athlete OS v4: additive migration; no existing tables or rows are removed.
create table if not exists public.waist_measurements (
 id bigint generated always as identity primary key,
 chat_id text not null, waist_cm numeric(5,1) not null check(waist_cm between 40 and 200),
 logged_on date not null, created_at timestamptz not null default now()
);
create index if not exists waist_chat_date_idx on public.waist_measurements(chat_id,logged_on desc);
create table if not exists public.wellness_checkins (
 id bigint generated always as identity primary key, chat_id text not null, logged_on date not null,
 fatigue integer check(fatigue between 1 and 5), sleep_hours numeric(4,1) check(sleep_hours between 0 and 24),
 knee_pain integer check(knee_pain between 0 and 10), achilles_pain integer check(achilles_pain between 0 and 10),
 injury_note text, created_at timestamptz not null default now()
);
create index if not exists wellness_chat_date_idx on public.wellness_checkins(chat_id,logged_on desc,created_at desc);
create table if not exists public.running_clearance (
 chat_id text primary key, clinician_cleared boolean not null default false,
 cleared_on date, updated_at timestamptz not null default now()
);
alter table public.waist_measurements enable row level security;
alter table public.wellness_checkins enable row level security;
alter table public.running_clearance enable row level security;
-- No public policies; service-role access only.
