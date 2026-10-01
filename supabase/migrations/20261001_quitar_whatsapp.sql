-- WhatsApp se quitó el 2026-10-01, tres días después de montarlo: no convenció.
--
-- Se borran la tabla y su función. La tabla guardaba nombres de contactos y números de
-- teléfono de terceros (nunca mensajes), y quedarse con eso sin nada que lo use es
-- justo lo que no tiene sentido guardar. `20260928_whatsapp` se queda en el directorio
-- como historia: es lo que se aplicó.
drop function if exists public.whatsapp_apuntar(jsonb);
drop table if exists public.whatsapp_chats;

insert into public.migraciones_aplicadas (nombre) values ('20261001_quitar_whatsapp')
  on conflict (nombre) do nothing;
