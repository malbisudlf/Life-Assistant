-- Preguntas al móvil que llevan una acción: el «Sí, hazlo» ejecuta lo guardado aquí. Ver
-- «Lo que se confirma en el móvil» en `backend/main.py` y en `docs/JARVIS.md`.
--
-- `accion` es {herramienta, argumentos, caduca?}: lo que propuso Jarvis (crear o mover un
-- evento) o la regla «vas tarde», tal cual se ejecutará. La frase de la notificación la
-- escribe el backend a partir de esto mismo, no el modelo. Solo `crear_evento` y
-- `editar_evento`; el backend lo vuelve a comprobar al ejecutar.
--
-- `resultado` es lo que devolvió al pulsar el botón, para que Jarvis sepa si se hizo.
--
-- Mientras esta migración no esté aplicada, lo único que falla es proponer una acción al
-- móvil: la herramienta dice que no ha podido guardarla. Las preguntas sin acción siguen
-- igual (el backend lee la tabla con `select=*`).
alter table public.jarvis_preguntas
  add column if not exists accion    jsonb,
  add column if not exists resultado jsonb;

insert into public.migraciones_aplicadas (nombre) values ('20261013_preguntas_con_accion')
  on conflict (nombre) do nothing;
