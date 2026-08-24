-- Hora de cada aportación (opcional). Con ella se puede pedir a Yahoo Finance el
-- precio horario más cercano al momento exacto de la compra, en vez de caer directo
-- al cierre del día — con solo la fecha, el precio calculado podía diferir del real
-- (visto en producción: hasta ~0,15-0,2 puntos porcentuales de ganancia de más).
alter table public.etf_aportaciones
  add column if not exists hora time;
