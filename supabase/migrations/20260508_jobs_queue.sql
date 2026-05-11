-- Cola de trabajos para agente PC
create extension if not exists pgcrypto;

create table if not exists public.jobs (
  id uuid primary key default gen_random_uuid(),
  status text not null default 'pending' check (status in ('pending','claimed','running','done','failed')),
  claimed_by text,
  claimed_at timestamptz,
  attempt integer not null default 0 check (attempt >= 0),
  dedupe_key text not null,
  payload jsonb,
  created_at timestamptz not null default now()
);

create unique index if not exists jobs_dedupe_key_uidx on public.jobs (dedupe_key);
create index if not exists jobs_status_created_at_idx on public.jobs (status, created_at);

-- Estado/presencia de agentes PC
create table if not exists public.pc_agents (
  agent_id text primary key,
  status text not null check (status in ('starting','online','busy','offline')),
  last_seen_at timestamptz not null default now(),
  hostname text,
  version text,
  updated_at timestamptz not null default now()
);

create index if not exists pc_agents_status_last_seen_idx on public.pc_agents (status, last_seen_at desc);
