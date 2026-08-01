-- Registro del envío del resumen diario, para que los intentos de respaldo del cron
-- no manden dos correos el mismo día.
--
-- El cron de GitHub Actions se retrasa con frecuencia y a veces se salta la ejecución
-- sin avisar (el 1 de agosto de 2026 no llegó a dispararse ni una vez), así que el
-- workflow lo intenta varias veces por la mañana. La fecha es la clave primaria: el
-- primer intento del día la inserta y los siguientes chocan con el unique — ese
-- conflicto es justo lo que hace que salga UN solo correo.
--
-- No vale un flag en memoria: la máquina de Fly escala a cero y se duerme entre un
-- intento y el siguiente, así que el flag estaría borrado justo cuando hace falta.
create table if not exists public.brief_sends (
  brief_date date primary key,
  sent_at    timestamptz not null default now()
);

-- Solo entra el backend con la service key, que salta la RLS por diseño. Sin esto, la
-- anon key (pública) daría acceso a la tabla desde internet.
alter table public.brief_sends enable row level security;
