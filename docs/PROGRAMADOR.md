<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

# El programador

Jarvis le encarga a Claude Code un proyecto entero y lo sigue: «encárgale al programador
una web para la lista de la compra», «¿cómo va?», «dile que el fondo azul». El trabajo lo
hace un servicio de `caja` —el **puente**— que pone los encargos en cola, de uno en uno, y
trabaja cada uno en un contenedor aislado que solo ve la carpeta de su proyecto.

| Dónde | Qué |
|---|---|
| Este repositorio, `backend/main.py` (sección «El programador») | Las tres herramientas, la firma y `POST /programador/terminado` |
| HomeLab, `caja/programador/` | El puente (`puente.py` y su lógica pura `logica.py`, con tests), el `Dockerfile` del contenedor, el servicio de systemd y **`INSTALAR.md`, que es «Lo hace Mikel»** paso a paso, con el primer encargo de prueba |

No es `encargar_a_una_sesion`. Aquel es para el código de **este** repositorio y lanza una
sesión en la nube con su flujo de PR y CI; el programador es para **cualquier otro**
proyecto: uno nuevo, uno que ya le encargaste, o un repositorio tuyo de GitHub. Las dos
descripciones lo dicen, y hay un caso de eval que lo mide.

## Lo hace Mikel

Todo está en `caja/programador/INSTALAR.md` del repositorio HomeLab, en orden: el token
de Claude Code (`claude setup-token`), el token **fine-grained** de GitHub, construir la
imagen, el `.env` del puente, las cuatro variables del backend, el servicio, la red
aislada (recomendada) y los dos primeros encargos de prueba (sin repositorio, y con uno
de usar y tirar). Desde este repositorio solo hace falta **desplegar el backend** con
estas cuatro en `~/stack/backend.env`:

```
PROGRAMADOR_URL=http://172.17.0.1:3341
PROGRAMADOR_TOKEN=<el mismo que en ~/programador/programador.env>
PROGRAMADOR_AVISO_TOKEN=<el mismo que en ~/programador/programador.env>
PROGRAMADOR_DUENOS=<tu usuario de GitHub>
```

## Las tres herramientas

| Herramienta | Confirma | Qué hace |
|---|---|---|
| `encargar_proyecto` | **Sí** | `POST /encargos` al puente con el encargo **firmado**. `titulo` («área: qué», será el commit y el PR), `encargo` (detallado y autocontenido), y `repo` (dueño/nombre) **o** `proyecto` (el slug de uno suyo, para modificarlo) |
| `ver_proyectos` | No | `GET /encargos`: los diez últimos con estado, progreso (el plan con ✓ y el % de pasos hechos), qué hace ahora, su última respuesta, el resumen y el PR |
| `hablar_con_el_programador` | No | `POST /encargos/{id|slug|activo}/mensaje`, **firmado** con el destinatario dentro. Trabajando: lo lee tras el paso que esté dando. En cola: se añade al encargo. Terminado: lo reabre y sigue, recordando lo que hizo |

**Por qué hablarle no se confirma** (y encargar sí): un mensaje solo dirige un trabajo que
ya se aprobó, y todo lo que hace el programador acaba en una rama y un PR que Mikel revisa
antes de mergear; el daño posible está acotado por eso, no por el botón. Lo que sí queda
abierto, y se dice: un mensaje a un encargo **terminado** lo reabre sin botón. Si eso
llegara a molestar, la palanca es que `hablar_con_el_programador` confirme solo en ese caso.

## Lo que no se puede relajar

- **Tokens en los dos sentidos, y fail-closed.** Backend → puente con `PROGRAMADOR_TOKEN`;
  puente → backend con `PROGRAMADOR_AVISO_TOKEN`, otro distinto, por `_token_ok()` y solo
  de cabecera. Quien tenga uno no puede hacerse pasar por el otro lado. Sin token, esa
  dirección no funciona (401).
- **El encargo va firmado, como el del agente PC (invariante 9).** Lo que va a ejecutar
  Claude Code con terminal es texto libre que no se puede validar contra una lista, así
  que se valida QUIÉN lo escribió: HMAC-SHA256 del JSON canónico con `PROGRAMADOR_TOKEN`,
  calculado **de cero aquí tras el «sí»**, y comprobado en el puente al recibirlo (con diez
  minutos de vigencia y sin repeticiones) y otra vez al sacarlo de la cola, que es un
  fichero. El canónico tiene que ser idéntico en los dos lados: hay un **vector de prueba
  igual** en `tests/backend/test_programador.py` y en `caja/programador/pruebas/`.
- **Solo repositorios de `PROGRAMADOR_DUENOS`**, comprobado aquí al proponer
  (`_validar_encargo`, que `_propuesta_invalida` aplica: con un repo ajeno no sale ni el
  botón) y otra vez en el puente. Lista vacía = ningún repositorio.
- **Trabaja en una rama y abre un PR. Nunca mergea ni empuja a `main`**: el puente solo
  publica ramas con el prefijo `arreglo/` (la convención de este repositorio para el
  trabajo automático) y nunca la rama por defecto.
- **En los repositorios de Mikel no queda escrito qué herramienta hizo el trabajo** (ver
  «Ramas» y «Autoría» en `CLAUDE.md`). No se fía de que Claude Code no ponga su
  `Co-Authored-By`: **el commit y el PR los escribe el puente**, un commit por vuelta con
  la identidad de Mikel y el título del encargo, la rama sale del título sin nada que
  delate la herramienta, y el cuerpo del PR pasa por un filtro. Los ajustes gestionados
  de la imagen apagan además la atribución en origen.
- **El token de GitHub es fine-grained** (Contents y Pull requests, solo en los
  repositorios elegidos) y **nunca entra en el contenedor**: clona y empuja el puente, en
  el host, con un directorio git propio que el contenedor no ve. Así tampoco puede el
  contenedor plantar un hook o un `.git/config` que el puente ejecute fuera.
- **El aviso, por `_apuntar_aviso`** (regla `programador`): con su silenciado y su
  memoria, sin botones que votar, y fuera del presupuesto del día porque lo pediste tú
  (`_es_tuyo`), como un `recordarme`. El enlace al PR solo viaja si es de GitHub y de un
  dueño de la lista. Los mensajes que el programador contesta a mitad del trabajo **no**
  avisan al móvil: se leen en `ver_proyectos`.
- **Lo que devuelve es un dato.** Resúmenes y respuestas los escribe un modelo que ha leído
  repositorios ajenos: `ver_proyectos` los marca con `_AVISO_WEB`. Por eso, y porque
  encargar y hablar lanzan trabajo con terminal, **ninguna de las tres está en el
  teléfono** (`_MCP_SERVIDOR_SOLO_LECTURA`).
- **Los errores del puente se traducen**, no se copian: cada código a su arreglo («el token
  no es el mismo en los dos lados», «está en marcha: háblale»).

## Lo que queda abierto

- **La red del contenedor**: con la de por defecto (`bridge`) sale a internet y ve la LAN.
  `caja/programador/red.sh` la aísla y está escrito sin probar (paso 7 de `INSTALAR.md`).
- **El token de Claude Code entra en el contenedor**: lo necesita para trabajar. Un
  repositorio con texto preparado podría intentar sacarlo. Por eso solo se aceptan
  repositorios de la lista blanca, que son los de Mikel.
- **Nada ha corrido aún contra Claude Code, Docker ni GitHub de verdad**: el formato de los
  eventos `stream-json` y el hook de los mensajes se escribieron con la documentación
  delante. Si el plan con ✓ no se rellena en `ver_proyectos`, mirar `logica.aplicar_evento`.
