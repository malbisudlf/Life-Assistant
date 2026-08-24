-- Fecha en la que se cambió de dispositivo de salud.
--
-- Una SOLA fila que se sobreescribe, igual que `brief_ajustes` y `presence`.
--
-- Existe por un problema que no se ve venir: al cambiar de reloj, las métricas siguen
-- llegando con el mismo nombre y el mismo aspecto, pero las MIDE otro sensor con otro
-- algoritmo. Las puntuaciones de bienestar no comparan valores absolutos sino cada día
-- contra la propia historia del usuario —la HRV contra la ventana D-14..D-8, la
-- respiración contra 30 días, la FC en reposo contra los percentiles de 90—, así que
-- durante toda la longitud de esas ventanas se estaría comparando el aparato nuevo con
-- el viejo y leyendo la diferencia entre fabricantes como si fuera fisiología del
-- usuario. Un mes largo de conclusiones falsas, sin nada que lo delate.
--
-- Guardar la fecha permite que las líneas base no crucen el corte. No se borra ni se
-- toca el histórico: los datos viejos siguen enteros para las gráficas, simplemente
-- dejan de servir como referencia contra la que puntuar.
--
-- `cambio_dispositivo` nullable = nunca se ha cambiado de aparato, que es el estado
-- normal y con el que todo se comporta igual que antes de existir esta tabla.
create table if not exists public.salud_ajustes (
  id                  text primary key default 'actual' check (id = 'actual'),
  cambio_dispositivo  date,
  dispositivo         text,
  updated_at          timestamptz not null default now()
);

alter table public.salud_ajustes enable row level security;
