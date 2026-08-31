-- Qué apagar cuando el aviso trae el botón de apagarlo.
--
-- El aviso de "te has ido y quedan encendidas: Salón, Cocina" ya decía QUÉ estaba
-- encendido, pero solo por su nombre bonito y dentro de una frase. Para que el botón de
-- la notificación pueda apagarlo hace falta el `entity_id`, y hace falta el de ESE
-- momento: el catálogo que empuja Home Assistant va con hasta una hora de retraso, así
-- que releerlo al pulsar apagaría lo que estaba encendido hace un rato, no lo que decía
-- el aviso que pulsaste. Se apaga exactamente lo que se te dijo — ni más ni menos.
--
-- En columna y no en memoria por lo de siempre: entre que el aviso se apunta (al cambiar
-- la presencia), se manda (el tick de HA) y lo pulsas pueden pasar minutos y un cold
-- start de Fly, que se lleva por delante cualquier cosa que solo viva en el proceso.
alter table public.jarvis_recordatorios
  add column if not exists entidades jsonb;
