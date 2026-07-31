-- RLS en las tablas de la cola de jobs y de los agentes PC.
--
-- El resto del esquema (ideas, training_*, health_metrics, clothing, oauth_tokens) ya
-- activa RLS sin policies: se accede SOLO desde el backend con la service key, que la
-- salta por diseño. Estas cuatro se quedaron fuera de ese criterio.
--
-- Importa especialmente en `jobs`: la anon key de Supabase es pública por diseño y su
-- endpoint REST está expuesto a internet, así que sin RLS cualquiera que la tenga puede
-- INSERTAR filas — y `jobs.payload` es exactamente lo que el agente ejecuta en el PC.
-- `job_results` guarda además enunciados y soluciones de entregas.

alter table public.jobs        enable row level security;
alter table public.job_events  enable row level security;
alter table public.job_results enable row level security;
alter table public.pc_agents   enable row level security;
