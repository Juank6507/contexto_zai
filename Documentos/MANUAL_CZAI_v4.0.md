# contexto_zai/Documentación/EXPLICACION_PROYECTO.md
# Documento 1 — Explicación explícita del proyecto CZAI (Contexto Z.ai)

**Versión:** 4.0
**Fecha:** 2026-09-09
**Autor:** Agente CZAI (Sesión 11)
**Estado:** Pendiente de validación por el Director.

---

## 1. Para qué existe este proyecto

Z.ai comprime la ventana de contexto del agente cuando se llena. Cuando eso pasa, el agente pierde el hilo de todo lo conversado: qué le pidió el Director, qué decisiones se tomaron, en qué archivo quedó cada cosa, qué estaba haciendo cuando lo cortaron. Sin algo que lo rescate, el agente vuelve a empezar como si fuera la primera conversación.

**contexto_zai existe para que el agente nunca pierda el hilo.**

Es un bibliotecario siempre disponible que el agente consulta cuando necesita contexto. El agente le pregunta, el bibliotecario busca en sus archivos y le responde con lo justo — nunca lo manda a leer documentos enormes. Si el bibliotecario necesita revisar algo grande para responder, lanza subagentes que hacen el trabajo pesado y le devuelven al agente solo la respuesta.

## 2. Cómo se ve desde el Director

El Director trabaja con el agente como siempre. Lo que cambia es que el agente, en vez de perder contexto cada vez que la ventana se comprime, retoma el hilo solo: lee tres archivos (`00_estado_actual.md`, `01_indice_recuperacion.md` y `02_decisiones_clave.md`) y sigue trabajando.

Esto significa que **un proyecto puede empezar y terminar en una sola sesión**, sin necesidad de generar múltiples sesiones para continuar el trabajo. Hoy en día, con el modelo de Z.ai, un proyecto mediano genera 5-10 sesiones porque cada compresión de contexto reinicia al agente. Con contexto_zai, el agente siempre sabe dónde quedó y qué decisión tomó el Director justo antes de la compresión.

## 3. Cómo se ve desde el agente

Cuando el agente arranca una sesión (o cuando lo comprimen), hace lo siguiente:

1. Lee `00_estado_actual.md` — le dice dónde quedó, qué estaba haciendo, qué sigue.
2. Lee `01_indice_recuperacion.md` — le dice qué temas existen y en qué archivo está cada uno.
3. Lee `02_decisiones_clave.md` — le dice cuál fue la última decisión que tomó el Director sobre la tarea pendiente, para retomarla exactamente donde se acordó.

Estos tres archivos son **los puntos de entrada obligatorios** tras una compresión de contexto. Sin los tres, el agente no puede retomar el hilo: el primero le dice qué hacía, el segundo le dice dónde está lo demás, el tercero le dice qué decisión debe respetar al continuar.

Si después de leer los tres necesita detalle de un tema específico, **consulta al proceso** con una pregunta concreta. El proceso identifica qué bloques pueden tener la respuesta, lanza un subagente por cada bloque candidato en paralelo, y le devuelve al agente una respuesta completa y abarcadora de lo que se preguntó.

El agente **nunca** lee los bloques completos en su ventana. Los bloques pueden ser enormes (hasta 70K tokens cada uno). Siempre consulta al proceso, y el proceso le responde con lo justo.

## 4. Qué contiene cada archivo de recuperación

### 4.1. `00_estado_actual.md` (5 secciones, no 8)

El archivo que el agente lee primero tras una compresión de contexto. Estructura:

- **D1 — Última instrucción del Director:** textual, sin tocar. El último mensaje del Director tal cual lo escribió.
- **D4 — Restricciones activas del último tema:** las restricciones y preferencias del Director enfocadas al tema activo (no a los últimos 10 intercambios genéricos). Interpreta un subagente.
- **A1 — Qué estaba haciendo el agente (con truncado inteligente):** toma el tema activo en orden cronológico. Si es muy largo, trunca a ~16K de contexto textual y le suma ~4K de resumen del contenido truncado hecho por un subagente. Esto es el "truncado inteligente": combina texto literal con resumen para no perder el hilo.
- **A2 — Entregables producidos:** los archivos que el agente mencionó en intercambios recientes. Patrones ampliados para capturar más tipos de rutas.
- **A3 — Errores abiertos:** los errores detectados en intercambios recientes. Patrones ampliados para detectar más tipos de errores.
- **A4 — Siguiente paso lógico:** analiza los últimos intercambios para detectar qué quedó pendiente, en vez de repetir "continuar con la instrucción del Director".

Las secciones D2 (contexto del tema activo) y D3 (decisiones pendientes) que existían en v3.6 **se eliminan** en v4.0. D2 se reemplaza por A1 con truncado inteligente, que ya captura el contexto del tema activo. D3 se elimina porque las decisiones ya viven en `02_decisiones_clave.md` — solo se necesita consultar cuál fue la última relevante, no duplicarla en `00_estado_actual.md`.

### 4.2. `01_indice_recuperacion.md`

Lista todos los temas del chat y en qué archivo está cada uno (tabla `tema → archivo`). Incluye el protocolo de recuperación: cómo debe el agente usar el proceso para consultar sin gastar su contexto.

### 4.3. `02_decisiones_clave.md`

Lista las decisiones reales tomadas por el Director, con su alcance: a qué tarea se refiere, qué incluye, qué no incluye. Un subagente distingue entre aprobaciones genéricas (que se descartan) y decisiones reales (que se documentan).

### 4.4. Bloques temáticos (`bloque_01.md` a `bloque_NN.md`)

Contienen los intercambios completos agrupados por tema. Varios temas por bloque, hasta llenar el límite de tokens. El agente nunca los lee directamente en su ventana — siempre consulta al proceso, que lanza subagentes para responder.

## 5. Cuándo se construye el contexto

### 5.1. Construcción inicial (desde un chat de Z.ai)

Una vez por proyecto. El agente invoca el proceso con el `chat_id` del chat donde se está desarrollando el trabajo con el Director. El proceso:

- Extrae todos los mensajes del chat (viaja a la API de Z.ai con el JWT del Director).
- Los agrupa en intercambios (pregunta-respuesta).
- Clasifica cada intercambio por tema.
- Empaqueta los intercambios en bloques temáticos (varios temas por bloque, hasta el límite de tokens).
- Genera los tres archivos principales.
- Genera los bloques temáticos.

### 5.2. Ampliación de contexto (desde fuentes externas)

Cuando el Director le pasa al agente material nuevo que no estaba en el chat original —un PDF, un link a una página web, un .docx— el agente lo procesa:

- **Si es chico:** el agente lo lee directo y lo incorpora al contexto.
- **Si es grande:** el agente le pide al proceso que lo indexe. El proceso usa subagentes para clasificarlo (con el flujo de 3 niveles si es muy grande: divide, clasifica en paralelo, concilia) y agrega el resultado como nuevos bloques al directorio de recuperación. El índice y la metadata se actualizan.

### 5.3. Actualización incremental (cuando el chat avanza)

Cada vez que el chat original acumula mensajes nuevos, el proceso puede actualizar los archivos de recuperación sin tener que re-procesar todo desde cero. Detecta qué intercambios son nuevos desde la última actualización, los clasifica, los agrega a los bloques correspondientes (o crea bloques nuevos), y regenera los tres archivos principales.

## 6. Cómo se transfiere entre agentes

Si el proyecto cambia de agente (porque el Director quiere que otro agente continúe, o porque arranca una sesión nueva en un sandbox limpio), el contexto se puede transferir:

1. El agente actual exporta el contexto como un archivo `.zip` que contiene todos los archivos de recuperación (estado, índice, decisiones, bloques, metadata) y un archivo de instrucciones.
2. El agente nuevo importa el `.zip` en su workspace. Tiene inmediatamente disponible todo el contexto del proyecto sin tener que re-extraer el chat original.
3. El agente nuevo lee primero los tres puntos de entrada (`00_estado_actual.md`, `01_indice_recuperacion.md` y `02_decisiones_clave.md`) y puede retomar el trabajo.

El archivo de instrucciones dentro del `.zip` le dice al agente nuevo los pasos en el orden correcto: primero leer los tres puntos de entrada, después lanzar subagentes para detalle si hace falta.

## 7. Los subagentes y cómo se organizan

El proceso usa subagentes para varias tareas: detectar decisiones, interpretar restricciones, hacer truncado inteligente, responder consultas sobre bloques, clasificar documentos externos. Todos estos subagentes hacen lo mismo con distinto input (reciben un contexto, hacen una tarea semántica, devuelven un texto).

Hay una clase base común que implementa la lógica compartida (construir prompt, invocar subagente, parsear respuesta estructurada), y dos subclases que se diferencian por el input: una recibe archivos o links, otra recibe intercambios del chat. Esto evita duplicar código y hace que los subagentes sean consistentes.

**Regla crítica sobre subagentes:** si un subagente falla, el error no puede ser silencioso. La clase que lanza subagentes tiene que decir por qué no pudo hacerlo, y después de la corrección, si vuelve a fallar, el error tiene que llegar al Director — el agente lo comunica en su respuesta, no se lo traga.

## 8. Los dos mini-servicios del sandbox

El proceso usa dos mini-servicios cuando corre en el sandbox de Z.ai. Ambos viven en `mini-services/` del workspace.

### 8.1. JwtBridgeServer (puerto 8086) — Herramienta temporal

No es infraestructura permanente. Es una herramienta que se levanta solo cuando se necesita obtener el JWT del Director. Hace su trabajo (recibir el JWT y guardarlo en `~/.czai/credentials.json`) y se cierra solo. La próxima vez que se necesite, se vuelve a levantar.

El JWT se obtiene mediante un bookmarklet que el Director instala en su navegador (con un `.bat` de doble clic). Cuando el Director está en un chat de Z.ai y hace clic en "Conectar CZAI", el bookmarklet extrae el JWT de la sesión del navegador y lo envía al sandbox. La URL del sandbox se construye dinámicamente a partir del `chatId` de la URL donde está el Director (por ejemplo, `https://chat.z.ai/c/{chatId}` se convierte en `https://preview-chat-{chatId}.space-z.ai/api/czai/recibir-jwt`), lo cual hace que cada sesión del agente tenga su propia URL pública accesible para el bookmarklet.

### 8.2. TaskBridgeServer (puerto 8087) — Puente para subagentes

Puede estar activo o no. El proceso siempre responde cuando se le demanda, con o sin TaskBridgeServer. Si está activo, el proceso lo usa para lanzar subagentes en paralelo (más eficiente). Si no, el proceso encuentra el camino alternativo para usar subagentes igual — nunca cae a un modo "light" sin subagentes.

## 9. Lo que el agente nunca hace

- **Nunca lee bloques completos en su ventana.** Siempre consulta al proceso.
- **Nunca consume su contexto con documentos grandes.** Siempre delega a subagentes.
- **Nunca reextrae el chat desde cero si ya hay contexto recuperado.** Usa actualización incremental.
- **Nunca pide al Director que edite código, ejecute scripts o revise archivos técnicos.** El Director habla de funcionalidades y resultados; los tecnicismos son cosa del agente.
- **Nunca se calla un error de subagente.** Si el subagente falla, el agente lo comunica al Director.

## 10. Lo que el Director siempre puede hacer

- **Pasarle al agente cualquier link o documento** para que lo incorpore al contexto.
- **Pedirle al agente que continúe en otra sesión** exportando el contexto actual.
- **Preguntarle al agente cualquier cosa sobre lo conversado antes** — el agente consulta al proceso y responde.
- **Trabajar en proyectos largos sin preocuparse por las compresiones de contexto** — el proceso está para resolver ese momento crítico.

## 11. Estado actual del proyecto

**Versión instalada:** v3.6 (implementada en la Sesión 10).

**Lo que ya funciona:**
- Extracción de mensajes del chat (407 mensajes en la prueba real de la Sesión 11).
- Clasificación temática (247 intercambios → 36 bloques).
- Subagentes paralelos de 3 niveles para documentos grandes (probado con PDF de 208 páginas).
- Exportación/importación de contexto como `.zip` con instrucciones de recuperación.
- JwtBridgeServer y TaskBridgeServer operativos.
- Bookmarklet del JWT funcional (construye la URL pública del sandbox dinámicamente a partir del `chatId`).

**Lo que falta (conciliado en Sesión 11):**
- El `00_estado_actual.md` pasa de 8 secciones a 5 (se eliminan D2 y D3, A1 queda con truncado inteligente).
- El `02_decisiones_clave.md` se llena de falsos positivos porque usa regex. Necesita un subagente que distinga decisiones reales de aprobaciones genéricas y capture el alcance de cada decisión.
- No existe la consulta bajo demanda: el agente todavía tiene que leer los archivos directamente en su ventana. Falta que el proceso reciba la pregunta del agente, identifique bloques candidatos, lance un subagente por cada uno en paralelo, y devuelva la respuesta completa y abarcadora.
- La ampliación desde fuentes externas solo funciona para attachments del chat, no para cualquier link o documento que el Director pase.
- El pipeline muere silenciosamente cuando corre en background con subagentes en paralelo. Falta diagnosticar qué lo mata antes de intervenir.
- Los temas generados por subdivisión temporal tienen nombres ilegibles (`general_general_2026sep09_2026sep09_2_...`). Falta que el `Subdivider` use un subagente para asignar nombres legibles.
- Falta probar el bookmarklet en sandboxes nuevos y verificar que el JWT persiste correctamente entre sesiones.
- Falta unificar los subagentes en una clase base común OOP (clase base abstracta + 2 subclases) para evitar duplicar código.

Estas mejoras se especifican en el **documento 2 (spec v4.0)** y se planifican en el **documento 3 (plan v4.0)**.

---

## 12. Sobre los documentos existentes en `contexto_zai/Documentación/`

El Director pidió que evalúe si los documentos existentes siguen teniendo sentido. Aquí va la evaluación:

| Documento existente | Mantener / Eliminar | Razón |
|---|---|---|
| `1-LEER-PRIMERO.txt` | **ELIMINAR** | Es una guía de instalación manual que mezcla instrucciones de git con instrucciones del agente. Hoy el setup lo hace `setup-czai.sh` automáticamente. Confunde más de lo que ayuda. |
| `MANUAL_CZAI_v3.5.md` | **REEMPLAZAR** por `MANUAL_CZAI_v4.0.md` | Es un manual desactualizado. Debería reescribirse con la visión del bibliotecario siempre disponible y los tres modos (construcción, ampliación, consulta). |
| `LEEME_INSTALACION.md` | **MANTENER** | Sigue siendo útil como guía rápida de instalación. |
| `spec_recuperacion_contexto_v3.6.md` | **MANTENER** | Es el historial de la spec anterior. No se borra, se agrega la nueva `spec_recuperacion_contexto_v4.0.md`. |
| `plan_refactorizacion_v3.6.md` | **MANTENER** | Mismo criterio: historial del plan anterior. |
| `historial_versiones_spec_plan.md` | **MANTENER** | Es el archivo de versiones. Se actualiza con la nueva entrada v4.0. |
| `historial_spec.md` | **MANTENER** | Historial. |
| `historial_plan.md` | **MANTENER** | Historial. |
| `metodologia_descubrimiento_jwt.md` | **MANTENER** | Documenta cómo se descubrió el mecanismo del JWT. Útil para nuevos agentes que necesiten entender el "por qué". |
| `metodologia_obtencion_jwt.md` | **MANTENER** | Guía para nuevos Directores. |
| `worklog_contexto_zai.md` | **EVALUAR** | Si es un worklog paralelo al del sandbox (`/home/z/my-project/worklog.md`), debería unificarse en uno solo para evitar duplicación. Si es distinto (ej: cambios del repo), mantener. |
| `CZAI-01.pdf` | **MANTENER** | Es el PDF de prueba usado para validar el flujo de 3 niveles. |
| `Token.txt` | **EVALUAR** | Si contiene solo el JWT en texto plano, eliminar (no debería haber JWTs en el repo — el JWT vive en `~/.czai/credentials.json`). Si contiene otra cosa, mantener. |

**Resumen:** 1 eliminar, 1 reemplazar, 2 evaluar, el resto mantener.

---

**Fin del documento 1.**
