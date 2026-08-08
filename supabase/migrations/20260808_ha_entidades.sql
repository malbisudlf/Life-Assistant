-- Catálogo de dispositivos de la casa, tal y como lo empuja Home Assistant.
--
-- El backend no puede preguntárselo a HA (vive en la LAN y no está expuesto: el mismo
-- mixed content que obligó a que el WOL pasara por aquí), así que aquí se repite el
-- patrón de la presencia — el que SABE es HA y empuja, el que NECESITA saber es el
-- backend. Sin esta lista, Jarvis solo podría encender cosas cuyo nombre se inventara.
--
-- Una sola fila que se sobreescribe, como `presence`: es un catálogo, no un histórico.
-- Y va a Supabase en vez de a un flag en memoria porque es ESTADO: perderlo en un cold
-- start de Fly dejaría a Jarvis sin saber qué hay en casa hasta el siguiente empuje de
-- HA, que puede tardar una hora. Las ÓRDENES, en cambio, siguen viviendo en memoria
-- (ver `_ha_ordenes`): perder una solo cuesta volver a pedirla.
create table if not exists public.ha_entidades (
  id          text primary key,
  entidades   jsonb       not null default '[]'::jsonb,
  actualizado timestamptz not null default now()
);

alter table public.ha_entidades enable row level security;
