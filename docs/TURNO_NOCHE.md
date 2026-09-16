# El turno de noche

Lo que se resuelve mientras duermes, para que por la mañana solo haya que aprobarlo.

El objetivo, dicho como se pidió: *«un agente que no duerma, que resuelva las cosas por
mí mientras duermo»*. El parte de la mañana se parece a esto:

> Entraron 14 correos. Los 4 que pedían respuesta están redactados y esperándote en
> Borradores. Los hallazgos de la revisión de anoche están arreglados y el PR espera tu
> permiso.

**Lo que no hace, y no por descuido**: no te llama a las seis de la mañana.

## Las dos reglas que lo sostienen

Todo lo demás es consecuencia de estas dos. Antes de tocar nada aquí, léelas.

1. **Todo queda en borrador.** El turno no envía correo, no mergea, no borra y no toca la
   casa. Prepara y anota; la decisión es tuya por la mañana. Esto es lo que permite
   dejarlo corriendo de madrugada sin nadie mirando, y la primera línea que lo cruce
   convierte esto en otra cosa que ya no se puede dejar sola.
2. **Nace apagado.** `NOCHE_TURNO`, `NOCHE_CORREO` y `NOCHE_ARREGLA` valen `0` por
   defecto, al revés que casi todos los interruptores del proyecto. Lee el buzón, llama a
   modelos de pago y lanza sesiones de Claude Code: ninguna de las tres cosas debe empezar
   a pasar sola porque alguien actualice el backend.

## Cómo corre

**No hay reloj propio.** El turno se cuelga del tick que Home Assistant ya llama cada
cinco minutos (`POST /ha/brief-tick`), como todo lo que tiene hora en este backend. Un
scheduler dentro del proceso sería un hilo más que mantener y un sitio más donde mirar
cuando algo no pasa.

```
cada 5 min   POST /ha/brief-tick
               └─ _turno_noche_seguro()
                    └─ _turno_de_noche_si_toca()      guarda de hora: NOCHE_HORA ≤ ahora < 06:00
                         └─ correr_turno_de_noche()
                              ├─ _reservar_parte(fecha)     INSERT en noche_partes → el 409 ES la respuesta
                              ├─ _noche_correos()           el buzón
                              ├─ _anotar_en_el_parte(...)   filas en noche_items
                              └─ _apuntar_aviso(REGLA_NOCHE, …, cuando=08:30)
```

El **tope de las 06:00** no es decorativo: sin él, un backend que arranca a mediodía (una
reconstrucción del add-on, por ejemplo) se pondría a redactar borradores a las doce,
llamaría a eso «el turno de noche» y gastaría el día entero del parte en una noche que ya
no existe.

La **idempotencia** es la misma del resumen diario: `noche_partes.fecha` es la clave
primaria, se hace `INSERT` y el `409` contra la clave *es* la respuesta a «¿ya se hizo?».
Preguntar primero y escribir después dejaría abierta justo la ventana que el tick recorre
cada cinco minutos, y una noche redactaría los mismos borradores doce veces.

Para probarlo sin esperar a las tres de la mañana:

```bash
curl -X POST "$BACKEND_URL/noche/correr?forzar=1" -H "X-Auth-Token: $BRIEF_TOKEN"
```

`?forzar=1` salta la hora **y** la idempotencia, para poder lanzarlo dos veces seguidas.

## El buzón

Aquí se relaja, a propósito y solo aquí, la regla que la sección del correo entrante lleva
escrita en el propio código: *«el CUERPO no se lee ni se manda a ningún modelo»*. No hay
forma de redactar la respuesta a un correo sin haberlo leído. Lo que se conserva es el
espíritu de la regla, acotándola:

| Paso | Qué ve | Qué hace |
|---|---|---|
| `_cabeceras_recientes()` | asunto, remitente, `internetMessageId` | los no leídos de las últimas `CORREO_HORAS`, con `$select` |
| `_noche_clasificar()` | **solo asunto y remitente** | `responder` / `informativo` / `ruido` |
| `_cuerpos_de()` | el cuerpo, **solo de los `responder`** | `uniqueBody` en texto, acotado a `CORREO_MAX_CUERPO` |
| `_redactar_respuesta()` | ese cuerpo | el borrador, con el modelo grande |
| `_guardar_borrador()` | — | `POST /me/messages/{id}/createReply` |

Y lo que **no** pasa:

- De una newsletter o de un aviso del banco no se abre nada: la clasificación sigue viendo
  solo cabeceras, y si esa clasificación **falla**, el defecto es `ruido` — el que no toca
  nada. Un fallo del modelo no puede acabar abriendo treinta correos.
- El cuerpo no se guarda en ningún sitio. Se lee, se usa y se olvida: en Supabase quedan el
  asunto, el remitente y el borrador, que es lo que tú vas a ver.
- Los correos siguen sin leer por la mañana, exactamente donde estaban: leer un mensaje
  por Graph no cambia `isRead` —eso solo lo hace un `PATCH` que aquí no existe—, igual que
  el `BODY.PEEK` del IMAP de antes. Hay un test que comprueba que no sale ni un PATCH.
- **No hay camino de envío.** En todo el turno no se llama a `enviar_correo()` ni a
  `smtplib` ni una vez, y hay un test que lo comprueba. Mandar el borrador es un acto tuyo,
  en tu cliente de correo.

### Por qué Graph y no IMAP

El buzón es el de Outlook, y el IMAP de Outlook está cerrado: su servidor anuncia
`LOGINDISABLED` y `AUTH=XOAUTH2`, o sea que desde que Microsoft retiró la autenticación
básica **la contraseña no vale**, tampoco una de aplicación. Se puede comprobar en diez
segundos y sin credenciales:

```python
import imaplib; print(imaplib.IMAP4_SSL("outlook.office365.com", 993).capabilities)
```

Quedaban dos caminos: reaprovechar el token de Graph para autenticarse por IMAP con
XOAUTH2, o hablar Graph a secas. Se eligió Graph porque el backend **ya** lo habla para el
calendario, con la renovación de tokens resuelta y probada, y porque el resultado es menos
código y no más: `createReply` deja el borrador colgando del hilo sin construir un MIME a
mano, y desaparece el problema de la carpeta de borradores, cuyo nombre no es estándar en
ningún sitio (`Drafts`, `[Gmail]/Borradores`, el nombre en el idioma de la cuenta) y cuyo
fallo dejaba el borrador en una carpeta nueva donde no iba a mirar nadie.

Tampoco hace falta el rodeo del UID: el `id` de Graph identifica al mensaje y no a su
posición, así que el turno puede volver a por el cuerpo de unos pocos minutos después sin
riesgo de bajarse otro correo.

**El permiso hay que volver a darlo una vez.** El consentimiento de Outlook que ya está
guardado es anterior al buzón y no incluye `Mail.ReadWrite`: al encender el correo hay que
pulsar «Conectar Outlook» en el dashboard otra vez. Y pedir un permiso no consentido en
una *renovación* no devuelve un token capado, devuelve un error — que sin red de seguridad
dejaría sin calendario, sin avisos y sin resumen diario, con «Sesión de Outlook caducada»
como único síntoma. Por eso `get_valid_token()` reintenta con los permisos de siempre si
la renovación ampliada falla: lo que se queda sin funcionar es el buzón, que además lo
dice en el registro con lo que hay que hacer.

## El código: un atajo, no un camino nuevo

Esto ya estaba casi entero montado (`docs/REVISION_NOCTURNA.md`), y conviene saberlo antes
de «añadirlo»:

```
01:37 UTC  revision-nocturna.yml → routine (solo lectura) → issue en GitHub
           → revision-aviso.yml → POST /revision/hallazgos
           → fila en revision_hallazgos + aviso DIFERIDO a las 08:30 con botones
08:30      «Arreglarlo» → _revision_decidir → _disparar_arreglo → PR → merge
```

Lo único que le faltaba para ser un turno de noche era **no esperar a las 08:30 para
preguntar**. Con `NOCHE_ARREGLA=1`, `revision_hallazgos()` llama a `_arreglar_de_noche()`,
que reusa entero el camino que ya existía —la misma tabla, el mismo estado `arreglando`, la
misma rutina de arreglo— y solo cambia quién aprieta el botón. Por la mañana te encuentras
el aviso de despliegue que también existía ya, con el CI en verde.

La condición **no es «es de madrugada»** sino «este aviso se iba a quedar esperando a
mañana de todas formas» (`_cuando_avisar(ahora) > ahora`). Si hay horas hasta que lo veas,
no tiene sentido gastarlas preguntando; si el aviso salía ya, no hay nada que adelantar.

Lo único propio es la instrucción, y dice explícitamente **que no se mergee**: la regla de
que ninguna sesión despliega no se toca porque nadie esté mirando, se toca menos. Es el
mismo trato que las averías: actuar y preguntar después, en vez de preguntar y actuar.

Si el disparo falla, `_arreglar_de_noche` devuelve la fila a `pendiente` y se cae al camino
de siempre. Mejor preguntarte a las 8:30 que quedarse callado con el hallazgo dentro.

## El parte de la mañana

Llega por dos sitios, y por ninguno más: **no** manda un correo (ya tienes el resumen
diario) ni añade una notificación nueva a las que hay.

- **El widget «Anoche»** del dashboard, con lo que hay agrupado por área y un par de
  botones por cosa: *Visto* y *Descartar*. «Visto» **no envía nada** — quiere decir «lo he
  mirado y me vale». Las dos decisiones van por `POST /noche/items/{id}/decidir` con un
  PATCH condicionado a `estado=eq.pendiente`, para que dos pestañas abiertas o el botón
  pulsado dos veces no cuenten como dos decisiones.
- **Hablando**, por el mismo modo llamada de siempre. El aviso de las 08:30 trae un botón
  «Que me lo cuente» que abre `?llamada=1&noche=1`; el parte **solo sale si se pide** y no
  entra en el orden de prioridades de `GET /llamada/pendiente`, porque es un informe y no
  una decisión esperando respuesta — descolgar por un permiso de despliegue no debe empezar
  contándote el buzón de anoche. Jarvis tiene además la herramienta `turno_de_noche` para
  cuando lo preguntes a cualquier hora.

La frase de una línea la escribe el backend (`_frase_parte`) porque la **dice** Jarvis al
descolgar y la **lee** el widget: dos copias acaban siendo dos frases distintas.

## Tablas

`supabase/migrations/20260914_turno_noche.sql`. **Aplicarla el mismo día que se mergea**
(las migraciones se aplican a mano y por eso se olvidan).

| Tabla | Para qué |
|---|---|
| `noche_partes` | una fila por noche; `fecha` es la PK y eso es lo que da la idempotencia. `resumen` guarda las cuentas |
| `noche_items` | lo que se hizo. `area` ∈ correo / codigo / agenda / recado; `estado` pendiente → aprobado \| descartado |

`_anotar_en_el_parte()` abre el parte si no existe: el atajo del código se dispara cuando
la revisión abre su issue, que es más tarde que el turno y puede caer un día en que el turno
no corrió. Sin eso, ese item se estrellaría contra la clave foránea y se perdería sin ruido.

## Lo que falta

Se hizo la primera fase: el carril, el buzón y el atajo del código. Quedan dos áreas de las
cuatro que se decidieron, y **ninguna se empieza hasta que esto lleve unas noches en
producción**:

- **Agenda del día siguiente.** Conflictos, desplazamientos imposibles (ya hay Google Maps),
  huecos de entreno y sesiones dadas sin cobrar. Todo sale de `get_events(credentials=None)`
  y `get_class_events(...)`, que ya usa `construir_brief()`. Los items serían propuestas que
  al aprobarlas llaman a `crear_evento` / `editar_evento`, herramientas de Jarvis que ya
  existen y ya piden confirmación.
- **Recados.** Una herramienta `dejar_para_la_noche(texto)` y una rutina nueva «Turno de
  noche» que los ejecute con su skill, siguiendo el patrón de `_lanzar_rutina_de_sesion`.

Y un requisito de configuración: `CORREO_LEER=1` y, **una sola vez**, volver a conectar
Outlook desde el dashboard para consentir `Mail.ReadWrite`. Sin eso, `NOCHE_CORREO=1` no
hace nada y el registro lo dice en cada intento. El correo entrante (`_revisar_correo`, la
regla proactiva que existía desde antes) lleva apagado desde que se escribió por lo mismo:
nunca hubo buzón configurado.
