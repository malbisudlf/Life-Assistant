# REVISAO_BACKEND

Issues encontrados en la carpeta `backend/` (sin contar `main.py`).

## `Dockerfile`

### `COPY . .` copia todo el directorio (media)

```dockerfile
COPY . .
```

Copia todo lo que llega al build context al contenedor. Si `.dockerignore` falla o
alguien añade un fichero nuevo no ignorado, puede terminar dentro: `.env`, archivos
temporales, logs.

**Arreglo:**

```dockerfile
COPY main.py check_config.py .
```

Copia explícito de los ficheros que se necesitan. Si en el futuro se añaden módulos
separados (`backend/models.py`, etc.), añadirlos a este `COPY`.

### Versión de Python no fija (baja)

```dockerfile
FROM python:3.11-slim
```

`3.11-slim` puede actualizarse automáticamente con parches nuevos. Un cambio en la
imagen base podría romper algo sin que nadie lo note hasta el siguiente deploy.

**Arreglo:**

```dockerfile
FROM python:3.11.11-slim
```

Pon la versión exacta que funciona. Actualizar manualmente cuando se actualice la
imagen base.

### Sin usuario no-root (baja)

Uvicorn corre como root dentro del contenedor. En Fly el aislamiento es por
containerd, así que no es un riesgo inmediato, pero es buena práctica.

**Arreglo:**

```dockerfile
RUN adduser --disabled-password --gecos "" appuser
USER appuser
```

Antes del `CMD`.

---

## `fly.toml`

### Sin health check explícito (baja)

Fly usa `internal_port` para health checks por defecto, pero cualquier request
aleatorio cuenta como health check. Si un scraper o bot golpea el puerto, un 404
podría hacer que Fly piense que la máquina está caída y la reinicie.

**Arreglo:**

```toml
[http_service.health_check]
  interval = 15000
  timeout = 5000
  grace_period = "10s"
```

O añadir un endpoint `/health` en `main.py` que responda 200 sin hacer nada, y
apuntar ahí.

---

## `.env`

### `DASHBOARD_PASSWORD=1234` (baja)

Valor de desarrollo local extremadamente débil. No es un riesgo de seguridad (el
fichero está en `.gitignore`), pero si alguien lo comparte accidentalmente, es
trivial de explotar.

**Arreglo:** Generar una contraseña más fuerte para desarrollo local, o al menos
documentar que no se use la misma que producción.

---

## `.env.example`

### 312 líneas puede abrumar (baja)

El fichero es exhaustivo pero puede intimidar a alguien que solo quiera configurar
lo mínimo.

**Opción A — dejar como está:** ya está bien documentado y los valores por defecto
en `main.py` hacen que funcione sin tocar nada.

**Opción B — versión mínima + fichero aparte:** crear un `.env.example` de 10 líneas
con solo las variables obligatorias y mover las opcionales a comentarios en
`main.py` o a un `docs/CONFIGURACION_COMPLETA.md`.

No es urgente: el proyecto ya tiene `.env.example` y `check_config.py` funciona
como guía.

---

## `requirements.txt`

### `pydantic` no explícito (info)

FastAPI lo incluye como dependencia transitiva, así que funciona. Pero si en el
futuro alguien quita FastAPI o cambia de versión, `pydantic` podría desaparecer
sin que `requirements.txt` lo refleje.

No es un problema actual — es mejor así de simple. Solo mencionarlo por si en el
futuro se usa `pydantic` directamente fuera de FastAPI.

---

## `.dockerignore`

### Ficheros de build faltantes (baja)

```
.env
.token
venv/
__pycache__/
*.pyc
.git/
```

Faltaría:

```
*.pyo
*.egg-info/
dist/
build/
```

No debería haber ningún problema en la práctica (no se generan en este proyecto),
pero es buena práctica de seguridad.

---

## `check_config.py`

### No verifica variables de Jarvis (info)

El script no comprueba `JARVIS_MODEL`, `JARVIS_MODEL_ACCION`, `JARVIS_MCP_SERVERS`,
etc. Es intencionado: son opcionales y complejos. No es un bug.

---

## Resumen

| Archivo | Severidad | Cuánto arreglar |
|---|---|---|
| `Dockerfile` COPY . . | Media | 1 línea |
| `Dockerfile` versión Python | Baja | 1 línea |
| `Dockerfile` usuario no-root | Baja | 2 líneas |
| `fly.toml` health check | Baja | 4 líneas o añadir endpoint |
| `.env` contraseña débil | Baja | 1 línea |
| `.env.example` extenso | Baja | Decisión de diseño |
| `.dockerignore` ficheros | Baja | 4 líneas |
| `requirements.txt` pydantic | Info | Ninguna |

Total: ~15 líneas de cambio, todo trivial.
