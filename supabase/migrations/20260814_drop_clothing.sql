-- El conteo de ropa era temporal desde el principio: llevaba la cuenta de la ropa
-- comprada hasta saldar el gasto, y ese gasto ya está saldado. Se retira el widget
-- entero (frontend, endpoints y tabla), tal y como estaba previsto.
--
-- La tabla guardaba las fotos como data URL, así que es la más pesada del esquema
-- para lo poco que aportaba ya. Si quieres conservar el histórico antes de borrarlo,
-- pásate por GET /export (o exporta la tabla desde Supabase) ANTES de ejecutar esto:
-- el drop no tiene vuelta atrás.
drop table if exists public.clothing;
