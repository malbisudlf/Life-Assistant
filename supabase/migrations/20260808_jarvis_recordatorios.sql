-- Recordatorios que Jarvis se apunta para avisarte más tarde.
--
-- Es lo único del sistema que hace que Jarvis hable sin que le hablen. Va a una tabla y
-- no a memoria por lo de siempre: Fly escala a cero, y un recordatorio que se evapora en
-- el próximo cold start no es un recordatorio.
--
-- Quien mira la hora es el sondeo de Home Assistant (`/ha/brief-tick`, cada 5 min), por
-- el mismo motivo que el reloj del resumen diario: sin nadie que llame, aquí no hay
-- proceso vivo que pueda mirar el reloj.
create table if not exists public.jarvis_recordatorios (
  id      uuid        primary key default gen_random_uuid(),
  cuando  timestamptz not null,
  texto   text        not null,
  enviado boolean     not null default false,
  creado  timestamptz not null default now()
);

-- El despacho pregunta siempre lo mismo: qué queda por mandar que ya haya vencido.
create index if not exists jarvis_recordatorios_pendientes
  on public.jarvis_recordatorios (enviado, cuando);

alter table public.jarvis_recordatorios enable row level security;
