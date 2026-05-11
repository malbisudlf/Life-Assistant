-- Resultados de entregas resueltas por el agente PC
-- El usuario revisa esta tabla desde el dashboard y entrega manualmente

create table if not exists public.job_results (
  id          uuid primary key default gen_random_uuid(),
  job_id      uuid references public.jobs(id) on delete cascade,
  titulo      text not null,
  enunciado   text not null,
  solucion    text not null,
  created_at  timestamptz not null default now()
);

create index if not exists job_results_job_id_idx on public.job_results (job_id);
create index if not exists job_results_created_at_idx on public.job_results (created_at desc);
