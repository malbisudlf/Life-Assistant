-- Ubicación actual del usuario, tal como la reporta la app companion de Home
-- Assistant. Una SOLA fila que se sobreescribe: aquí no hay histórico a propósito.
-- Un registro de por dónde has pasado es el dato más sensible de todo el proyecto y
-- no hace falta para nada de lo que se construye encima — el clima y la hora de
-- salida solo necesitan dónde estás AHORA, y la serie diaria (health_metrics,
-- métrica `time_at_home`) solo guarda cuántas horas, nunca dónde.
--
-- No puede vivir en memoria como los flags de WOL/apagado: Fly escala a cero y cada
-- vez que la máquina se duerme se perdería la ubicación, así que el dashboard se
-- quedaría sin saber dónde estás hasta el siguiente cambio de zona en HA — que
-- puede tardar horas si no te mueves.
create table if not exists public.presence (
  id          text primary key default 'actual' check (id = 'actual'),
  zona        text not null,              -- nombre de la zona de HA: casa, trabajo, gimnasio, "fuera"…
  en_casa     boolean not null,
  lat         double precision,           -- puede faltar: hay device_trackers sin GPS
  lon         double precision,
  precision_m double precision,           -- radio de precisión que reporta el GPS
  fuente      text,                       -- quién lo mandó (ha_companion), para diagnóstico
  updated_at  timestamptz not null default now()
);

alter table public.presence enable row level security;
