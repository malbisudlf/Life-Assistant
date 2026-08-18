<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Módulo Entrenamiento

El usuario entrena a personas y cobra 16 €/hora, generalmente cada 4 sesiones.

### Tablas de Supabase

- `training_clients` — `price_per_hour=16`, `sessions_per_payment=4`. **No hardcodees
  estos valores**: salen de la tabla.
- `training_sessions` — sesiones (42 históricas importadas, sep 2025 – may 2026).
- `training_payments` — cobros (6 importados, ene–may 2026).

### Notas técnicas

- **El filtro de sesiones pendientes va por `created_at`, no por `date`**: antes la query
  usaba `date=gt.{last_payment_date}` (comparando solo la fecha) — si se cobraba hoy y
  luego se entrenaba hoy, la sesión nueva tenía la misma `date` que el cobro y el `gt` la
  excluía (no aparecía en el widget, aunque sí en "sesiones recientes" de Ajustes, que no
  filtra). Ahora `/training/summary` y `POST /training/payments` comparan el `created_at`
  del último pago contra el `created_at` de las sesiones.
- **Codifica `created_at` con `urllib.parse.quote` al meterlo en la query de Supabase**:
  el timestamp lleva `+00:00` y el `+` sin codificar se lee como un espacio en una query
  string, rompiendo el filtro `gt.` contra PostgREST (devolvía 0 filas, sin error visible)
  — no aparecía **ninguna** sesión pendiente. Es el mismo fallo que tumbó
  `/jobs/pending`; ver `docs/BUGS_HISTORICOS.md`.
- El último pago se obtiene con `order=created_at.desc` (no `order=date.desc`), para que
  sea el cobro más reciente en el tiempo y no solo por fecha.
- El importe se calcula al marcar el cobro (horas desde el último cobro × precio).
