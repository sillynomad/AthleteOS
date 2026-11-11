-- Private single-user bot tables. Only server-side service-role access; no client access.
create table if not exists public.activities (id bigint generated always as identity primary key, chat_id text not null, kind text not null check(kind in ('swim','gym','run','bike')), distance_m integer, activity_date date not null, source text not null default 'telegram', created_at timestamptz not null default now());
create table if not exists public.body_metrics (id bigint generated always as identity primary key, chat_id text not null, weight_kg numeric(5,2) not null, logged_on date not null, created_at timestamptz not null default now());
create table if not exists public.recovery_logs (id bigint generated always as identity primary key, chat_id text not null, pain_score integer not null check(pain_score between 0 and 10), logged_on date not null, created_at timestamptz not null default now());
create table if not exists public.notifications (id bigint generated always as identity primary key, notification_key text not null unique, created_at timestamptz not null default now());
create table if not exists public.processed_updates (update_id bigint primary key, created_at timestamptz not null default now());
create index if not exists activities_chat_date_idx on public.activities(chat_id,activity_date);
alter table public.activities enable row level security;
alter table public.body_metrics enable row level security;
alter table public.recovery_logs enable row level security;
alter table public.notifications enable row level security;
alter table public.processed_updates enable row level security;
-- No anon/authenticated policies. The trusted server uses the service-role key.
