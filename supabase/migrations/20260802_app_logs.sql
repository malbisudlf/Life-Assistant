-- Registro persistente del backend.
--
-- El backend ya llamaba a logger.error() en todos los sitios que importan, pero eso
-- escribe en el stdout de una máquina de Fly que ESCALA A CERO: los mensajes se van con
-- ella y solo se ven si alguien está mirando `fly logs` justo en ese momento. Por eso el
-- 409 que dejó al Watch sin sincronizar estuvo días registrándose sin que nadie lo viera.
--
-- Solo se persiste WARNING y por encima (LOG_PERSIST_LEVEL), así que el volumen es
-- pequeño: esta tabla no es para trazas de depuración, es para lo que hay que mirar
-- cuando algo va mal. La escritura la hace un hilo de fondo en lotes, nunca la petición.
create table if not exists public.app_logs (
  id         uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  level      text not null,
  source     text,
  message    text not null,
  -- Fichero:línea de origen y, si el mensaje salió atendiendo una petición, su
  -- "MÉTODO /ruta" (sin query string: ahí viajan los tokens de servicio).
  context    jsonb
);
create index if not exists app_logs_created_at_idx on public.app_logs (created_at desc);
-- El filtro por nivel del panel del dashboard siempre va acompañado del orden por fecha.
create index if not exists app_logs_level_created_at_idx on public.app_logs (level, created_at desc);
alter table public.app_logs enable row level security;
