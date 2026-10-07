-- Moodle: qué entregas se han llevado ya al calendario. Ver `docs/MOODLE.md` y la sección
-- «MOODLE (entregas)» de `backend/main.py`.
--
-- Hace falta memoria porque la sincronización tiene que distinguir tres cosas que desde
-- Moodle se ven igual: una entrega NUEVA (se crea el evento y se avisa), una que ya estaba
-- (se deja, o se mueve si cambió la fecha) y una que ha DESAPARECIDO de los pendientes
-- (se ha entregado: el 📚 del evento pasa a ✅). Sin esta tabla, cada pasada crearía otra
-- vez todos los eventos.
create table if not exists public.moodle_entregas (
  -- El id del evento de calendario de Moodle, no el de la tarea: es lo que devuelve la
  -- lista de pendientes y lo único estable entre una pasada y otra.
  moodle_id   bigint primary key,
  nombre      text not null,
  curso       text,
  url         text,
  vence       timestamptz not null,
  -- El evento de Outlook. null = aún no se pudo crear (se reintenta); '-' = lo borraste
  -- tú, y no se vuelve a crear.
  outlook_id  text,
  estado      text not null default 'pendiente'
              check (estado in ('pendiente', 'entregada', 'fuera')),
  creado      timestamptz not null default now(),
  actualizado timestamptz not null default now()
);

-- Cada pasada lee las de los últimos dos meses.
create index if not exists moodle_entregas_vence on public.moodle_entregas (vence);

-- Sin policies: solo entra el backend con la service key, que salta RLS por diseño.
alter table public.moodle_entregas enable row level security;

insert into public.migraciones_aplicadas (nombre) values ('20261007_moodle')
  on conflict (nombre) do nothing;
