<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Copia de seguridad de Supabase

Ideas 5.4 y 6.6 de `docs/IDEAS.md`. Piezas:

| Fichero | Qué es |
|---|---|
| `scripts/copia_supabase.py` | El volcado: lee Supabase por REST, cifra y verifica |
| `.github/workflows/copia-supabase.yml` | Lo dispara los lunes y a mano, y guarda el resultado |
| `tests/backend/test_copia_supabase.py` | Paginación, copia vacía, cifrado y salida sin datos |

### Por qué existe

Es el único dato del proyecto que no se puede regenerar. El calendario está en Outlook,
la configuración en el `.env`, el código en GitHub; el histórico del Apple Watch existe
en un solo sitio. Y la ingesta de salud resuelve por upsert `(metric_date, metric_name)`,
así que **un cliente que escriba mal pisa la serie sin dejar rastro** — no hay papelera,
no hay versión anterior, y el fallo se descubre semanas después mirando una gráfica rara.

El coste de no hacerlo es el único de la lista de ideas que es irreversible.

### Qué se copia

Lo que hay en `TABLAS` (`scripts/copia_supabase.py`), que es la lista canónica:

- **`health_metrics`** — el histórico del Watch. Es la única marcada **obligatoria**.
- `training_clients`, `training_sessions`, `training_payments` — entrenamiento personal.
- `ideas`, `clothing` — notas de voz y ropa.
- `jarvis_memoria`, `jarvis_recordatorios`, `jarvis_mcp_servidores` — lo que Jarvis sabe.
- `reglas_usuario`, `vigilancias`, `avisos_reglas`, `ha_entidades` — lo proactivo.
- `salud_ajustes`, `brief_ajustes` — ajustes que se escribieron a mano una vez.
- `etf_holdings`, `etf_aportaciones` — la cartera introducida a mano.

**Lo que NO se copia, y por qué:**

- **`oauth_tokens`** — son credenciales vivas de Microsoft Graph. Copiarlas solo
  multiplica los sitios donde vive un refresh token, y la tabla se regenera entera
  pasando otra vez por `/auth/login`. Un backup no es sitio para un secreto que no hace
  falta.
- **La columna `token` de `jarvis_mcp_servidores`** — mismo motivo, y además caduca
  sola (sale de `gh auth token`).
- **`jobs`, `job_events`, `job_results`, `pc_agents`, `app_logs`, `login_attempts`,
  `presence`, `brief_envios`, `informe_envios`, `vigilante_estado`,
  `revision_hallazgos`, `averias`** — estado operativo y registro. Se regeneran solos y
  perderlos no cuesta nada. `presence` además es una sola fila sin histórico, a
  propósito (ver `docs/BACKEND_PATRONES.md`).

Si añades una tabla nueva que guarde algo que el usuario escribió a mano, **añádela a
`TABLAS`**: lo que no está en esa tupla no se copia.

### Dónde acaba, y por qué está cifrado

El repositorio es **público**. Eso descarta de entrada:

- versionar el volcado (obvio),
- y **también** subirlo en claro como artefacto de Actions: los artefactos de un
  repositorio público los puede descargar cualquiera que pase por la pestaña Actions.
  Ese es el error que parece seguro y no lo es.

Tampoco vale con dejar el fichero en claro un momento y cifrarlo después: un paso que
falle a medias deja el JSON en el disco del runner y en cualquier `actions/upload-artifact`
posterior. Por eso **el cifrado lo hace el propio script**, no un paso del workflow: el
JSON viaja de memoria a la entrada estándar de `gpg` y **el volcado en claro no existe
nunca como fichero**.

Se eligió `gpg --symmetric` con AES256 frente a las alternativas:

- **`age`** haría lo mismo y con menos superficie, pero hay que instalarlo en el runner
  y no está en ninguna máquina de las que ya se usan. `gpg` viene en `ubuntu-latest` y
  en la máquina de desarrollo.
- **Cifrar en Python** (`cryptography`, que ya entra de rebote por `python-jose`)
  obligaría a inventarse el formato del contenedor —derivación de clave, nonce,
  autenticación— y a mantenerlo. Un formato de cifrado casero en el camino de una copia
  de seguridad es exactamente donde no conviene tener código propio.
- **Una clave asimétrica** (cifrar con la pública, descifrar con la privada) sería mejor
  en un equipo, porque el runner no necesitaría poder leer lo que escribe. Aquí el
  usuario es uno y la clave privada acabaría en el mismo gestor de contraseñas que la
  frase, así que solo añade ceremonia.

Destinos, en este orden:

1. **Artefacto de la ejecución** (`copia-supabase`), 90 días de retención. La copia es
   semanal, así que hay unas doce generaciones vivas — margen suficiente para volver
   atrás de un fallo que tarde semanas en notarse.
2. **Repositorio privado, opcional.** Si existen la variable `BACKUP_REPO`
   (`usuario/repo`, y **tiene que ser privado**) y el secret `BACKUP_REPO_TOKEN`, el
   `.gpg` se empuja también ahí, a `supabase/`. Los artefactos caducan; esto no. Sin
   esas dos cosas el paso se salta.

En local, el script deja los ficheros en `copias/`, que está en `.gitignore` junto al
patrón `*.json.gpg` — cifrado o no, ese fichero no entra en el repositorio.

### Secrets y variables que hay que dar de alta

En **Settings → Secrets and variables → Actions** del repositorio:

| Nombre | Tipo | Qué es |
|---|---|---|
| `SUPABASE_URL` | secret | La misma que tiene el backend en Fly |
| `SUPABASE_KEY` | secret | La **service key**: es la única que salta la RLS y ve las tablas |
| `COPIA_PASSPHRASE` | secret | La frase de cifrado. **Guárdala fuera de GitHub** (gestor de contraseñas): sin ella las copias no se abren y no hay forma de recuperarlas |
| `BACKUP_REPO` | variable | *Opcional.* `usuario/repo` del repositorio **privado** del segundo destino |
| `BACKUP_REPO_TOKEN` | secret | *Opcional.* Token con permiso de escritura sobre ese repositorio |

`backend/.env.example` no cambia: el backend no participa en esto. `SUPABASE_URL` y
`SUPABASE_KEY` ya están documentadas ahí porque el backend las usa; `COPIA_PASSPHRASE`
es solo del workflow y del script, y por eso vive aquí y no allí.

### Cómo se restaura

**Esto es lo importante del documento.** Una copia que no se sabe restaurar no es una
copia.

**1. Conseguir el fichero.** Desde la ejecución del workflow (Actions → *Copia de
seguridad de Supabase* → la ejecución que toque → artefacto `copia-supabase`), o del
repositorio privado si está configurado. Descomprime el zip del artefacto: dentro está
el `copia-supabase-AAAA-MM-DD.json.gpg`.

**2. Comprobar que se abre, antes de tocar nada.**

```bash
export COPIA_PASSPHRASE='…'
python scripts/copia_supabase.py --verificar copia-supabase-2026-09-03.json.gpg
```

Descifra en memoria, cuenta las filas de cada tabla y falla si `health_metrics` viene
vacía. Si esto no pasa, el problema es la copia, no la base de datos.

**3. Sacar el JSON.**

```bash
gpg --batch --pinentry-mode loopback --passphrase "$COPIA_PASSPHRASE" \
    --decrypt copia-supabase-2026-09-03.json.gpg > copia.json
```

La forma del fichero es:

```json
{
  "version": 1,
  "generado_en": "2026-09-03T04:17:11+00:00",
  "recuentos": { "health_metrics": 4213, "...": 0 },
  "tablas":    { "health_metrics": [ {…}, {…} ], "...": [] }
}
```

Cada lista son las filas tal y como las devuelve PostgREST, con sus nombres de columna.
Borra `copia.json` en cuanto termines: son datos de salud en claro.

**4. Devolverlas a Supabase.** No hay un botón: se hace tabla a tabla contra el REST,
con la service key y `Prefer: resolution=merge-duplicates`. Para `health_metrics` hay que
nombrar la restricción de unicidad real, que **no** es la clave primaria — la misma
trampa del 409 que documenta `docs/BACKEND_PATRONES.md`:

```bash
python - <<'PY'
import json, os, requests
copia = json.load(open("copia.json", encoding="utf-8"))
filas = copia["tablas"]["health_metrics"]
cab = {"apikey": os.environ["SUPABASE_KEY"],
       "Authorization": f"Bearer {os.environ['SUPABASE_KEY']}",
       "Content-Type": "application/json",
       "Prefer": "resolution=merge-duplicates"}
url = (os.environ["SUPABASE_URL"] +
       "/rest/v1/health_metrics?on_conflict=metric_date,metric_name")
for i in range(0, len(filas), 500):
    r = requests.post(url, headers=cab, json=filas[i:i + 500], timeout=60)
    print(i, r.status_code)
    r.raise_for_status()
PY
```

Notas de la restauración, aprendidas del esquema:

- **`on_conflict` cambia por tabla**: es la columna o columnas con `unique`/`primary key`
  de verdad. `health_metrics` → `metric_date,metric_name`; `jarvis_memoria` → `clave`;
  `vigilancias` → `clave`; `salud_ajustes`/`brief_ajustes` → `id`; las que van por `id`
  uuid, `id`.
- **`training_sessions` y `training_payments` referencian `training_clients`** por clave
  ajena: restaura primero los clientes. Igual `etf_aportaciones` después de
  `etf_holdings`.
- **Restaurar es un upsert, no un borrado**: lo que hay hoy en la tabla y no está en la
  copia se queda. Si lo que hay que deshacer es una escritura que *pisó* filas buenas,
  el upsert las devuelve a su sitio. Si hay que dejar la tabla exactamente como estaba,
  hay que vaciarla antes, y eso conviene pensarlo dos veces.
- Los `created_at` van dentro del JSON, así que las filas vuelven con su fecha original.

### Verificación: por qué el script se niega a hacer copias vacías

El fallo clásico de estos scripts no es que fallen: es que **triunfen escribiendo nada**.
Un fichero de 40 bytes sustituye a la copia buena, el workflow sale en verde durante
meses y el problema aparece el único día que la copia hacía falta.

Contra eso, el script:

1. Cuenta las filas de cada tabla y las imprime (solo nombres y números).
2. Compara lo descargado con el total que declara PostgREST en `Content-Range`, y falla
   si no cuadran — una descarga truncada a mitad de paginación no pasa por buena.
3. Falla si `health_metrics` viene con **0 filas**, y en ese caso **no escribe el
   fichero**: la copia de la semana pasada sigue donde estaba.
4. Después de cifrar, **vuelve a abrir lo que acaba de escribir** y comprueba que los
   recuentos coinciden. Es la única prueba que vale de que el fichero sirve.
5. Sale con código 1 y por `stderr` ante cualquiera de esas cosas, así que el workflow
   se pone rojo.

Y `--verificar` repite el paso 4 sobre cualquier fichero, para comprobar una copia vieja
sin restaurar nada.

### Lo que no se registra nunca

La salida del script acaba en el log de un workflow de un repositorio **público**. Por
eso solo escribe nombres de tabla y recuentos: ni valores, ni la clave, ni el cuerpo de
un error de Supabase (que puede traer filas dentro), ni la frase de cifrado. Hay tests
que lo comprueban (`TestSalidaSinDatos`), incluido uno que verifica que la frase no
viaja en la línea de órdenes de `gpg` — ahí sería visible en la lista de procesos de la
máquina. La frase va a un fichero temporal que se borra en un `finally`; los **datos**
nunca tocan el disco en claro.
