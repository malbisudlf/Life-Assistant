-- WhatsApp, en modo lectura: lo mínimo para saber a quién le debes respuesta.
--
-- Una fila por chat individual con la hora del último mensaje SUYO y la del último
-- TUYO. El texto de los mensajes no está aquí ni en ninguna otra tabla: no sale del
-- puente de `caja`. Ver `docs/WHATSAPP.md`.
create table if not exists public.whatsapp_chats (
  -- El id del chat tal cual lo da WhatsApp: `<número>@s.whatsapp.net` o `<id>@lid`.
  -- Nunca un grupo (`@g.us`): los descartan el puente y el backend.
  chat        text primary key,
  nombre      text,
  ultimo_suyo timestamptz,
  ultimo_mio  timestamptz,
  actualizado timestamptz not null default now()
);

-- El aviso pregunta siempre lo mismo: los chats con mensaje suyo reciente.
create index if not exists whatsapp_chats_suyo_idx on public.whatsapp_chats (ultimo_suyo);

-- Sin policies: solo entra el backend con la service key. Son nombres de contactos y
-- números de teléfono, y la anon key es pública por diseño.
alter table public.whatsapp_chats enable row level security;

-- Apuntar un lote quedándose con la hora MÁS RECIENTE de cada lado. Tiene que ser en la
-- base de datos: el puente manda en vivo y además el historial al vincularse, y los dos
-- pueden llegar en cualquier orden. Un upsert normal dejaría la hora de un mensaje viejo
-- del historial encima de la de uno nuevo, y el chat saldría como pendiente sin estarlo.
-- `greatest` ignora los nulos, que es justo lo que hace falta cuando un lado no viene.
create or replace function public.whatsapp_apuntar(filas jsonb)
returns integer
language sql
as $$
  with apuntadas as (
    insert into public.whatsapp_chats as c (chat, nombre, ultimo_suyo, ultimo_mio, actualizado)
    select f->>'chat',
           nullif(f->>'nombre', ''),
           (f->>'suyo')::timestamptz,
           (f->>'mio')::timestamptz,
           now()
    from jsonb_array_elements(filas) as f
    on conflict (chat) do update set
      nombre      = coalesce(excluded.nombre, c.nombre),
      ultimo_suyo = greatest(c.ultimo_suyo, excluded.ultimo_suyo),
      ultimo_mio  = greatest(c.ultimo_mio, excluded.ultimo_mio),
      actualizado = now()
    returning 1
  )
  select count(*)::integer from apuntadas;
$$;

revoke all on function public.whatsapp_apuntar(jsonb) from public, anon, authenticated;
grant execute on function public.whatsapp_apuntar(jsonb) to service_role;

insert into public.migraciones_aplicadas (nombre) values ('20260928_whatsapp')
  on conflict (nombre) do nothing;
