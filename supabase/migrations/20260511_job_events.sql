-- Trazabilidad de etapas de ejecución de un job
create table if not exists public.job_events (
  id         uuid primary key default gen_random_uuid(),
  job_id     uuid not null references public.jobs(id) on delete cascade,
  stage      text not null,
  message    text,
  created_at timestamptz not null default now()
);

create index if not exists job_events_job_id_idx on public.job_events (job_id, created_at asc);
