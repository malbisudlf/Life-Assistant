# 💩 CacaMap

Mini-app independiente del dashboard, vibecodeada en un prompt: un mapa social
para registrar los sitios en los que has cagado y competir con tus amigos.

## Cómo usarla

Es un único fichero autocontenido, sin build ni servidor:

```bash
# opción 1: abrir directamente
open cacamap/index.html        # macOS
xdg-open cacamap/index.html    # Linux

# opción 2: servirla (recomendado para geolocalización)
npx serve cacamap
```

## Qué incluye

- **Registro e inicio de sesión** por usuario (contraseña con hash SHA-256 + sal
  en `localStorage`; varios usuarios pueden compartir navegador).
- **Mapa interactivo** (Leaflet + teselas oscuras de CARTO): clic en cualquier
  punto para registrar una cagada con lugar, fecha, calidad (1–5 💩) y nota.
- **Comparación entre amigos sin servidor**: cada usuario exporta su
  *caca-código* (JSON en base64) y lo comparte por donde quiera; al importarlo,
  las cagadas del amigo aparecen en el mapa con su propio color.
- **Ranking de tronos** con medallas, estadísticas personales (total, mes en
  curso, calidad media) e historial con borrado.

## Limitaciones asumidas

- Los datos viven en el `localStorage` del navegador: no hay backend ni
  sincronización real. La "autenticación" es local y no protege nada frente a
  alguien con acceso al dispositivo — es una app de risas, no de banca.
- Leaflet y las teselas se cargan por CDN: hace falta conexión a internet.
