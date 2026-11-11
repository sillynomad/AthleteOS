-- Run once in Supabase SQL Editor. Does not modify or delete existing workouts.
create table if not exists public.coaching_recommendations (
 id bigint generated always as identity primary key,
 chat_id text not null,
 recommendation_date date not null,
 planned_kind text not null,
 planned_name text not null,
 planned_details text not null,
 recommendation text not null,
 reasoning jsonb not null default '[]'::jsonb,
 message text not null,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique(chat_id,recommendation_date)
);
-- The backend uses the Supabase service role key; no public table access needed.
alter table public.coaching_recommendations enable row level security;
