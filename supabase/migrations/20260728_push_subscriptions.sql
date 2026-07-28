-- Notificaciones push (Web Push) — I1
--
-- El navegador entrega una "subscription" por dispositivo: un endpoint del servicio
-- de push (FCM, Mozilla, Apple) más dos claves con las que se cifra el mensaje. Solo
-- sirven para ese dispositivo y ese origen, y caducan cuando el usuario desinstala la
-- PWA o revoca el permiso — por eso el backend borra las que devuelven 404/410.
create table if not exists public.push_subscriptions (
  endpoint    text primary key,                 -- único por dispositivo
  p256dh      text not null,
  auth        text not null,
  user_agent  text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- Marcas de "esto ya se ha enviado". Es imprescindible que viva en la BD y no en
-- memoria: Home Assistant dispara el envío cada minuto y el backend escala a cero en
-- Fly, así que un dedupe en memoria se perdería en cada arranque en frío y el mismo
-- aviso saldría una y otra vez.
--
-- La clave la construye el backend (p. ej. "evento:<id>:<inicio>"); el insert actúa
-- como cerrojo: si choca con una existente, es que ya se envió.
create table if not exists public.push_enviados (
  clave       text primary key,
  created_at  timestamptz not null default now()
);

-- Para poder limpiar marcas viejas: delete from push_enviados where created_at < now() - interval '30 days';
create index if not exists push_enviados_created_at_idx on public.push_enviados (created_at desc);
