-- Una avería que se detecta sola, se arregla sola y solo te pide el último permiso.
--
-- `revision_hallazgos` nació para UNA cosa: el issue que deja la revisión nocturna, con
-- su pregunta por la mañana («¿lo arreglo?»). Esto añade el camino inverso, que es el
-- que de verdad quita trabajo: el CI se pone rojo, nadie pregunta nada, se lanza el
-- arreglo en el momento y la pregunta llega DESPUÉS, cuando ya hay un PR con el CI en
-- verde esperando. Preguntar antes de arreglar te hace decidir con lo que menos sabes;
-- preguntar después te deja decidir viendo el arreglo hecho.
--
-- Se queda en la misma tabla y no en una nueva porque es la misma pregunta con el mismo
-- botón, el mismo id determinista y la misma transición atómica. Lo único que cambia es
-- de dónde vino y hasta dónde llega.
alter table public.revision_hallazgos
  -- De dónde salió: 'issue' (la revisión nocturna, el camino de siempre) o 'ci' (el CI
  -- rojo en main). Con default, las filas que ya existen quedan bien sin tocarlas.
  add column if not exists origen text not null default 'issue',
  -- El PR que abrió la sesión de arreglo. Es lo que se despliega cuando das el permiso,
  -- y se guarda porque entre que el PR queda verde y tú contestas pasan minutos u horas:
  -- releer "el PR más reciente" al contestar podría desplegar otro.
  add column if not exists pr_numero integer,
  -- Qué se rompió, en una línea, para poder decírtelo por teléfono sin abrir GitHub.
  add column if not exists detalle text;

-- Los estados posibles pasan a ser:
--   pendiente   → hay algo que decidir (el camino del issue nocturno)
--   arreglando  → hay una sesión trabajando en ello
--   listo       → hay un PR con el CI en verde esperando tu permiso
--   desplegado  → dijiste que sí y se desplegó
--   descartado  → dijiste que no
-- No hay constraint que los liste a propósito: un estado nuevo no debe necesitar una
-- migración, y quien los valida es el PATCH condicional de `_revision_decidir`.

-- El vigilante pregunta "¿tengo algo esperando permiso?" en cada tick, y "lo último de
-- este origen" al cerrar el arreglo. Las dos consultas caen en este índice.
create index if not exists revision_hallazgos_origen
  on public.revision_hallazgos (origen, estado, creado desc);
