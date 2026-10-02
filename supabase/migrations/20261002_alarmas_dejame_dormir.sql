-- «Déjame dormir»: saltarse UNA mañana sin tocar la alarma.
--
-- `saltar` es el día (local) en que la alarma no tiene que sonar. Cuando le llega la
-- hora y su fecha coincide, el tick no avisa: si se repite, se rearma para la siguiente
-- vez como si hubiera sonado; si era de una sola vez, pasa a `saltada`.
--
-- Una fecha y no un booleano, a propósito: lo que se pide es «mañana no», no «la
-- próxima vez no». Si después editas la alarma a otro día, la marca deja de coincidir
-- y suena, que es lo que querías al moverla. Y una fecha que ya pasó no puede volver a
-- coincidir nunca: no hace falta limpiarla para que deje de valer.
--
-- Columna y no tabla aparte por lo mismo que `repetir`: el backend lee las alarmas
-- vivas y decide en Python, nunca filtra por esto en SQL.
alter table public.alarmas add column if not exists saltar date;

insert into public.migraciones_aplicadas (nombre) values ('20261002_alarmas_dejame_dormir')
  on conflict (nombre) do nothing;
