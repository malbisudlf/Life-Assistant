-- Cuánto ocupa la base de datos, para avisar ANTES de que se llene.
--
-- El plan gratuito de Supabase da 500 MB, y hay tablas que crecen solas sin que nadie
-- las mire: `app_logs`, `health_metrics`, `backend_latidos`, `jarvis_gasto`. El día que
-- se llene, las escrituras empiezan a fallar en TODAS partes a la vez —la ingesta, los
-- avisos, el registro— y el registro, que es lo que diría qué pasa, es lo primero que se
-- queda sin sitio.
--
-- PostgREST no deja preguntar `pg_database_size()` directamente, así que se expone como
-- función RPC. `security definer` para poder leer el catálogo; y ejecutable SOLO por
-- `service_role` (el backend): la anon key es pública por diseño y no tiene por qué
-- saber ni el tamaño ni el nombre de las tablas.
create or replace function public.espacio_bd()
returns json
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
  select json_build_object(
    'total', pg_database_size(current_database()),
    'tablas', coalesce((
      select json_agg(t)
      from (
        select c.relname as tabla, pg_total_relation_size(c.oid) as bytes
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind = 'r'
        order by pg_total_relation_size(c.oid) desc
        limit 8
      ) t
    ), '[]'::json)
  );
$$;

revoke all on function public.espacio_bd() from public, anon, authenticated;
grant execute on function public.espacio_bd() to service_role;

insert into public.migraciones_aplicadas (nombre) values ('20260924_espacio_bd')
  on conflict (nombre) do nothing;
