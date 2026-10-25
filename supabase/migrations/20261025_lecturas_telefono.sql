-- Por dónde iba lo que te lee el teléfono (el briefing, la agenda, el parte, las tareas).
--
-- Colgar a media lectura perdía el sitio: la posición vivía en la voice-app, en la
-- memoria de esa llamada. Desde el parche 24 la voice-app avisa al backend de cada trozo
-- que empieza a sonar (`POST /telefono/lectura/posicion`), y «sigue leyendo» en otra
-- llamada retoma ese trozo. El backend la tiene en memoria; esta tabla es para que un
-- despliegue entre colgar y retomar no se la lleve. Sin ella, todo funciona igual salvo
-- eso, y el backend lo dice una vez en el registro.
--
-- Una fila por `que`: solo importa la última lectura de cada cosa. No crece, no se purga.
create table if not exists public.lecturas_telefono (
  que         text primary key,            -- briefing, semana, correo o tareas
  fecha       text not null default '',    -- la del briefing (YYYY-MM-DD); vacía en lo demás
  nombre      text,                        -- «el briefing», como lo dice la llamada
  n           integer not null default 1,  -- la sección que estaba sonando
  titulo      text,                        -- su título, para encontrarla si el texto cambia
  trozo       integer not null default 0,  -- el trozo dentro de esa sección, desde 0
  total       integer,                     -- cuántas secciones tiene
  indice      jsonb,                       -- todas, con sus bloques: «ve a la de economía»
  terminada   boolean not null default false,
  actualizado timestamptz not null default now()
);

-- Como toda tabla del proyecto: RLS sin policies. Solo entra el backend, con la service
-- key, que la salta por diseño; la anon key (pública) no ve nada.
alter table public.lecturas_telefono enable row level security;

insert into public.migraciones_aplicadas (nombre) values ('20261025_lecturas_telefono')
  on conflict (nombre) do nothing;
