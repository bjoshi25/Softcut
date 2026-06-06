-- Softcut async job manifest table
-- Run in Supabase SQL editor.

create table if not exists public.jobs (
  job_id text primary key,
  pipeline_mode text not null,
  status text not null check (status in ('queued', 'running', 'completed', 'failed')),
  stage text not null check (stage in ('queued', 'ingest', 'analysis', 'planner', 'done', 'failed')),
  message text not null default '',
  created_at_utc timestamptz not null default now(),
  started_at_utc timestamptz null,
  updated_at_utc timestamptz not null default now(),
  completed_at_utc timestamptz null,
  artifacts jsonb not null default '{}'::jsonb,
  error text null
);

create index if not exists idx_jobs_updated_at on public.jobs (updated_at_utc desc);

alter table public.jobs enable row level security;

-- Service-role based backend writes bypass RLS.
-- Keep policy explicit for authenticated read access if needed in future.
