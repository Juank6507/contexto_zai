# MANUAL COMPLETO DEL PROYECTO CONTEXTO Z.AI v3.5

**Sistema de recuperación de contexto para agentes de Z.ai mediante subagentes efímeros**

---

**Versión:** 3.5
**Fecha:** 2026-09-06
**Autor:** Agente CZAI
**Repositorio:** contexto_zai
**Licencia:** Propietaria del Director

---

## ÍNDICE

1. [Introducción](#1-introducción)
2. [Qué problema resuelve](#2-qué-problema-resuelve)
3. [Arquitectura del sistema](#3-arquitectura-del-sistema)
4. [Estructura de archivos](#4-estructura-de-archivos)
5. [Instalación](#5-instalación)
6. [Configuración](#6-configuración)
7. [Funcionalidades](#7-funcionalidades)
8. [Cómo funciona el proceso](#8-cómo-funciona-el-proceso)
9. [API pública](#9-api-pública)
10. [Pruebas realizadas](#10-pruebas-realizadas)
11. [Casos de uso](#11-casos-de-uso)
12. [Solución de problemas](#12-solución-de-problemas)
13. [Roadmap y versiones](#13-roadmap-y-versiones)

---

## 1. Introducción

### 1.1. Qué es Contexto Z.ai

**Contexto Z.ai (CZAI)** es un sistema de recuperación de contexto para agentes de la plataforma Z.ai. Cuando un agente pierde contexto (por ejemplo, al exceder el límite de tokens de la conversación), este proceso le permite recuperar la memoria completa del proyecto sin tener que releer todo el chat.

El sistema está construido en Python con OOP estricto, y funciona como un paquete importable que el agente puede invocar en cualquier momento para activar la recuperación de contexto.

### 1.2. Filosofía del proyecto

1. **OOP estricto:** Clases con responsabilidad única, interfaces claras, type hints, docstrings.
2. **Reutilización antes que duplicación:** Si una clase existente hace algo similar, se refactoriza para compartir interfaz.
3. **Scripts atómicos standalone:** Cada módulo es autocontenible y ejecutable directamente con `python archivo.py` (incluye auto-tests en `__main__`).
4. **Cambios quirúrgicos:** Solo se modifica lo que cambia; no se reescribe lo que funciona.
5. **Compatibilidad Windows/Linux:** Todos los paths usan `pathlib.Path`, los stubs de `sys.path` detectan automáticamente la estructura del proyecto.

### 1.3. Versión actual

**v3.5** (septiembre 2026) — Añade indexación de documentos adjuntos mediante subagentes efímeros.

---

## 2. Qué problema resuelve

### 2.1. El problema

Cuando trabajas con un agente de Z.ai en un proyecto largo, ocurren estos problemas:

1. **Pérdida de contexto:** Después de muchas interacciones, el agente supera su ventana de contexto (128K tokens) y "olvida" lo conversado al inicio.
2. **Documentos pesados:** Si le entregas al agente un PDF de 200 páginas, su contexto se llena inmediatamente y deja de poder trabajar.
3. **Temas mezclados:** Todo el chat se acumula en una sola conversación sin clasificar, lo que hace difícil encontrar información específica.
4. **Sin memoria entre sesiones:** Cuando el agente se reinicia, no tiene forma de recuperar lo que se hizo en sesiones anteriores.

### 2.2. La solución

CZAI resuelve estos problemas con:

1. **Recuperación de contexto estructurada:** Extrae todos los mensajes del chat, los clasifica por temas, y genera archivos de recuperación (estado, índice, decisiones, bloques temáticos) que el agente puede consultar bajo demanda.
2. **Subagentes efímeros para documentos pesados:** Cuando el Director adjunta un PDF, el proceso lanza un subagente que lo lee completo con SU PROPIO contexto (independiente del agente principal), lo clasifica, y devuelve al agente principal solo un resumen breve + referencia al índice.
3. **Clasificación temática por capas:**
   - **Capa 1:** Léxica (por palabras clave).
   - **Capa 2:** Intención (aprobación, rechazo, handoff, etc.).
   - **Capa 3:** Subagente discriminador que subdivide temas grandes en subtemas específicos.
4. **Exportación/importación de contexto:** Puedes empaquetar todo el contexto del proyecto en un `.zip` y cargarlo en otro agente CZAI sin perder memoria.

### 2.3. Métricas de mejora

- **Antes:** Un PDF de 200 páginas (165K tokens) llenaba completamente el contexto del agente.
- **Después:** El agente principal consume solo ~72 tokens (el resumen), preservando el 99.9% de su contexto.

---

## 3. Arquitectura del sistema

### 3.1. Diagrama de componentes

```
┌─────────────────────────────────────────────────────────────────┐
│                    PIPELINE (entry point)                       │
│  run()  |  status()  |  export_context()  |  import_context()   │
│  index_document()  |  find_context_packages()                  │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                  PROCESS (orquestadores)                         │
│  ┌─────────────────┐  ┌─────────────────────┐                   │
│  │   Orchestrator   │  │   RecoveryCycle      │                 │
│  │ (decide ciclo)   │  │ (pasos 5-9)         │                  │
│  └────────┬────────┘  └──────────┬──────────┘                   │
│           │                      │                              │
│           ▼                      ▼                              │
│  ┌─────────────────┐  ┌─────────────────────┐                   │
│  │ IncrementalCycle │  │  _index_attachments  │                 │
│  │ (updates)        │  │  _apply_capa3_disc.  │                 │
│  └─────────────────┘  └─────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│   CLIENT     │ │  PROCESSING   │ │   SUBAGENTS       │
│              │ │               │ │                    │
│ AuthClient   │ │ ExchangeBldr  │ │ SubagentLauncher  │
│ ChatClient   │ │ Classifier    │ │ EstadoSubagent   │
│ BrowserSess. │ │ IntentionClsf │ │ BarridoSubagent   │
│ WebReader    │ │ BlockPacker   │ │ DecisionesSubag.  │
│ AttachmentC. │ │ Subdivider    │ │ MantenimSubag.    │
│ (v3.5)       │ │ ContentDeleg. │ │ DiscriminatorSub. │
│              │ │ (v3.5)        │ │ DocumentoIndexer. │
│              │ │ AttachmentDet. │ │ (v3.5)            │
│              │ │ (v3.5)        │ │                    │
│              │ │ ContentCleaner│ │                    │
│              │ │ CodeDetector  │ │                    │
│              │ │ VersionGraph  │ │                    │
│              │ │ DecisionExtr. │ │                    │
└──────────────┘ └──────────────┘ └──────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│              GENERATION (archivos de recuperación)              │
│  EstadoGenerator  |  IndiceGenerator  |  DecisionesGenerator   │
│  BloqueGenerator  |  RecoveryGenerator                          │
└─────────────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│         VERIFICATION + METADATA + DETECTION                     │
│  Verifier  |  MetadataManager  |  LexicTrigger                │
│                                |  TokenCounter                  │
│                                |  SelfQuestions                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2. Patrones OOP utilizados

#### Patrón 1: ContentDelegator (clase base abstracta, v3.5)

Define la interfaz común para decidir si un contenido debe procesarse en el contexto del agente principal o delegarse a un subagente:

```
ContentDelegator (abstract)
├── DocumentDelegator  → decide sobre documentos adjuntos
└── Subdivider         → decide sobre temas grandes del chat
```

#### Patrón 2: Subagentes efímeros

Todos los subagentes siguen el mismo patrón:
- Reciben un contenido (archivo, tema, intercambio).
- Lo leen con su contexto independiente.
- Devuelven al agente principal un resumen o índice, no el contenido completo.

```
SubagentLauncher (genérico)
├── EstadoSubagent          → extrae contexto del tema activo
├── BarridoSubagent         → busca info puntual en un archivo
├── DecisionesSubagent      → extrae decisiones con LLM
├── MantenimientoSubagent   → actualización incremental
├── DiscriminatorSubagent   → subdivide temas grandes (Capa 3, v3.4)
└── DocumentoIndexerSubagent → lee+clasifica+resume docs (v3.5)
```

#### Patrón 3: Pipeline functional

El `pipeline.py` expone funciones puras (`run`, `status`, `export_context`, `import_context`, `index_document`) que instancian los objetos internos, los usan, y liberan los recursos. Esto facilita el uso desde el agente sin que este tenga que gestionar estado.

---

## 4. Estructura de archivos

### 4.1. Árbol del proyecto

```
contexto_zai/                          ← paquete Python (52 archivos .py, ~16K líneas)
├── __init__.py                        ← inicializador del paquete, exporta API pública
├── config.py                          ← constantes y configuración global
├── models.py                          ← modelos Pydantic (Message, Exchange, Attachment, etc.)
├── pipeline.py                        ← entry point: run(), status(), export_context(), etc.
│
├── Documentación/                     ← specs y planes de versiones anteriores
│   ├── spec_recuperacion_contexto_v3.0.md
│   ├── spec_recuperacion_contexto_v3.1.md
│   ├── spec_recuperacion_contexto_v3.2.md
│   ├── spec_recuperacion_contexto_v3.3.md
│   ├── plan_refactorizacion_v2.md
│   ├── plan_refactorizacion_v3.md
│   ├── metodologia_descubrimiento_jwt.md
│   ├── CZAI-01.pdf                    ← memoria del proyecto (208 páginas)
│   └── Token.txt
│
├── client/                            ← clientes de APIs externas
│   ├── __init__.py
│   ├── auth_client.py                 ← cliente de autenticación (JWT, create_share)
│   ├── browser_session.py             ← wrapper sobre agent-browser (inyección de cookie)
│   ├── chat_client.py                 ← extracción de mensajes (batch endpoint)
│   ├── web_reader.py                  ← lee URLs externas (v3.4)
│   └── attachment_client.py           ← descarga attachments (v3.5)
│
├── processing/                        ← procesamiento de mensajes
│   ├── __init__.py
│   ├── exchange_builder.py            ← agrupa mensajes en intercambios
│   ├── classifier.py                  ← clasificación léxica (Capa 1)
│   ├── intention_classifier.py        ← clasificación por intención (Capa 2, v3.4)
│   ├── content_cleaner.py             ← limpieza de HTML, reasoning, formato markdown
│   ├── block_packer.py                ← empaqueta temas en bloques por tamaño
│   ├── subdivider.py                  ← subdivide temas grandes (implementa ContentDelegator)
│   ├── content_delegator.py           ← clase base + DocumentDelegator (v3.5)
│   ├── attachment_detector.py         ← detecta attachments en batch (v3.5)
│   ├── code_detector.py               ← detecta scripts versionables en mensajes
│   ├── version_graph.py               ← grafo de cambios de scripts (v3.3)
│   └── decision_extractor.py          ← extractor de decisiones (regex)
│
├── generation/                        ← generación de archivos de recuperación
│   ├── __init__.py
│   ├── estado_generator.py            ← genera 00_estado_actual.md
│   ├── indice_generator.py            ← genera 01_indice_recuperacion.md
│   ├── decisiones_generator.py        ← genera 02_decisiones_clave.md
│   ├── bloque_generator.py            ← genera bloque_*.md
│   └── recovery_generator.py           ← orquesta todos los generadores
│
├── detection/                         ← detección de pérdida de contexto
│   ├── __init__.py
│   ├── lexic_trigger.py               ← detecta frases del Director ("ya te dije", etc.)
│   ├── token_counter.py               ← cuenta tokens consumidos
│   └── self_questions.py              ← auto-preguntas ("¿sé en qué archivo estoy?")
│
├── subagents/                         ← subagentes efímeros
│   ├── __init__.py
│   ├── launcher.py                    ← wrapper sobre Task de Z.ai
│   ├── _task_bridge.py                ← puente con la API de Task
│   ├── estado_subagent.py             ← extrae contexto del tema activo
│   ├── barrido_subagent.py            ← busca info puntual en un archivo
│   ├── decisiones_subagent.py         ← extrae decisiones con LLM
│   ├── mantenimiento_subagent.py     ← actualización incremental de archivos
│   ├── discriminator_subagent.py     ← subdivide temas grandes (v3.4)
│   └── documento_indexer_subagent.py ← indexa documentos adjuntos (v3.5)
│
├── process/                           ← orquestadores del ciclo
│   ├── __init__.py
│   ├── orchestrator.py                ← decide entre RecoveryCycle e IncrementalCycle
│   ├── recovery_cycle.py              ← ciclo completo (pasos 5-9)
│   └── incremental_cycle.py           ← actualización incremental
│
├── metadata/                          ← gestión de _metadata.json
│   ├── __init__.py
│   └── manager.py                     ← lee/escribe metadata con unicidad temática
│
├── verification/                      ← verificación de límites
│   ├── __init__.py
│   └── verifier.py                    ← verifica que archivos cumplen límites de tokens
│
└── context/                           ← exportación/importación de contexto
    ├── __init__.py
    ├── exporter.py                    ← empaqueta contexto en .zip (v3.4)
    └── importer.py                    ← descomprime .zip y carga contexto (v3.4)

tests/                                 ← tests del proyecto (9 archivos, ~3.6K líneas)
├── run_all_tests.py                   ← runner principal (41 tests)
├── test_v35_attachments.py            ← tests E2E v3.5 (15 tests)
├── test_e2e_pipeline.py              ← tests E2E generales (16 tests)
├── test_recovery_cycle.py             ← tests de integración del ciclo
├── test_classifier_packer_subdivider.py
├── test_estado_indice_generation.py
├── test_subagent_lifecycle.py
├── test_code_detector.py
└── test_version_graph.py
```

### 4.2. Estadísticas del código

- **52 archivos Python** en el paquete
- **~16.400 líneas de código** (incluyendo tests)
- **9 archivos de tests** con ~3.600 líneas
- **41 tests** en el runner principal
- **15 tests E2E** específicos de v3.5
- **Cero dependencias externas** más allá de `pydantic`, `httpx`, `beautifulsoup4`, `pdfplumber`

---

## 5. Instalación

### 5.1. Requisitos previos

- **Python 3.11 o superior** (probado en 3.11 y 3.12)
- **pip** o **uv** para instalar dependencias
- **Conexion a internet** para acceder a la API de Z.ai

### 5.2. Dependencias Python

```bash
pip install pydantic>=2.0 httpx beautifulsoup4 pdfplumber
```

Opcional (para lectura de más formatos):
```bash
pip install python-docx openpyxl  # DOCX, XLSX
```

### 5.3. Estructura del proyecto en tu ordenador

CZAI soporta dos estructuras de directorios:

#### Estructura A (recomendada para Linux/macOS)

```
/home/usuario/workspace/           ← workspace (PYTHONPATH apunta aquí)
└── contexto_zai/                  ← paquete Python
    ├── __init__.py
    ├── config.py
    └── ...
```

#### Estructura B (recomendada para Windows)

```
C:\Python\Proyectos\               ← workspace Y paquete a la vez
└── contexto_zai\                  ← este directorio es el workspace y el paquete
    ├── __init__.py
    ├── config.py
    └── ...
```

Ambas estructuras funcionan automáticamente. El stub de `sys.path` al inicio de cada módulo detecta la raíz del paquete y configura `PYTHONPATH` sin intervención manual.

### 5.4. Instalación paso a paso (Windows)

1. **Descomprime el ZIP** `contexto_zai_completo.zip` en `C:\Python\Proyectos\`:

   ```
   C:\Python\Proyectos\
   ├── contexto_zai\          ← paquete Python
   ├── tests\                  ← tests
   └── download\               ← documentación
   ```

2. **Instala las dependencias:**

   ```powershell
   pip install pydantic httpx beautifulsoup4 pdfplumber
   ```

3. **Verifica la instalación** ejecutando un módulo atómico:

   ```powershell
   cd C:\Python\Proyectos
   python contexto_zai\config.py
   ```

   Debes ver `[PASS] config.py: todos los tests pasaron`.

4. **Ejecuta el test runner completo:**

   ```powershell
   python tests\run_all_tests.py
   ```

   Debes ver:
   ```
   RESULTADO FINAL
     Total tests ejecutados: 41
     Pasaron: 41
     Fallaron: 0
   ```

### 5.5. Instalación paso a paso (Linux/macOS)

1. **Descomprime el ZIP** en tu directorio de trabajo:

   ```bash
   unzip contexto_zai_completo.zip -d ~/workspace/
   ```

2. **Instala las dependencias:**

   ```bash
   pip install pydantic httpx beautifulsoup4 pdfplumber
   # o con uv:
   uv pip install pydantic httpx beautifulsoup4 pdfplumber
   ```

3. **Verifica:**

   ```bash
   cd ~/workspace
   python tests/run_all_tests.py
   ```

### 5.6. Verificación de la instalación

Para confirmar que todo está correctamente instalado, ejecuta los 4 módulos nuevos de v3.5:

```powershell
python contexto_zai\client\attachment_client.py
python contexto_zai\processing\attachment_detector.py
python contexto_zai\processing\content_delegator.py
python contexto_zai\subagents\documento_indexer_subagent.py
```

Cada uno debe mostrar `[PASS] xxx.py: todos los tests pasaron`.

Para validar el flujo completo de attachments:

```powershell
python tests\test_v35_attachments.py
```

Debes ver: `RESULTADO E2E v3.5: 15 pasaron, 0 fallaron de 15 tests`.

---

## 6. Configuración

### 6.1. Constantes globales (config.py)

Todas las constantes del sistema están centralizadas en `contexto_zai/config.py`:

#### Límites de tokens (spec v3.2)

| Constante | Valor | Descripción |
|---|---|---|
| `TOKEN_LIMITS.ventana_agente` | 128.000 | Ventana total del agente Z.ai |
| `TOKEN_LIMITS.margen_seguridad_pct` | 20% | Margen reservado (25.600 tokens) |
| `TOKEN_LIMITS.capacidad_util` | 102.400 | Ventana - margen |
| `TOKEN_LIMITS.max_tokens_bloque` | 70.000 | Máximo por bloque temático |
| `TOKEN_LIMITS.max_tokens_estado` | 20.000 | Máximo para `00_estado_actual.md` |
| `TOKEN_LIMITS.max_tokens_indice` | 8.000 | Máximo para `01_indice_recuperacion.md` |
| `TOKEN_LIMITS.max_tokens_decisiones` | 12.000 | Máximo para `02_decisiones_clave.md` |
| `TOKEN_LIMITS.carga_principal_max` | 40.000 | Suma de los 3 archivos principales |
| `TOKEN_LIMITS.conversion_rate` | 3.5 | Chars por token (promedio es-código) |
| `TOKEN_LIMITS.umbral_disparo_tokens` | 92.160 | 90% de capacidad_util (activa recuperación) |

#### API de Z.ai

| Constante | Valor |
|---|---|
| `API_CONFIG.base_url` | `https://chat.z.ai` |
| `API_CONFIG.cookie_name` | `token` |
| `API_CONFIG.messages_batch_by_chat_url` | `https://chat.z.ai/api/v1/chats/{chat_id}/messages/batch` |
| `API_CONFIG.timeout_seconds` | 30.0 |

#### Reglas temáticas (Capa 1)

8 reglas léxicas con keywords:
- `validaciones` (pytest, test, valida)
- `configuracion_proyecto` (worklog, repo, estrategia)
- `metodologia` (DCPA, diagnóstico)
- `general` (fallback, sin keywords)
- Y 4 más...

#### Disparadores de pérdida de contexto

- **10 frases léxicas:** "ya te dije", "lo hablamos", "no repitas", "estás olvidando", etc.
- **3 auto-preguntas:** "¿Sé en qué archivo estoy?", "¿Sé qué decidimos?", "¿Sé qué sigue?"

#### v3.4: Patrones para links e intenciones

- `URL_PATTERN`: regex para detectar URLs `http(s)://`
- `INTENTION_THEMES`: 8 temas de intención (aprobación, rechazo, corrección, handoff, etc.)

#### v3.5: Delegación de documentos adjuntos

| Constante | Valor | Descripción |
|---|---|---|
| `DELEGATION_THRESHOLD_TOKENS` | 5.000 | Documentos >5K tokens se delegan al subagente |
| `DELEGATION_CONTEXT_LIMIT_PCT` | 80 | Si agente >80% ocupado, delega aunque el doc sea mediano |
| `TRIVIAL_SIZE_TOKENS` | 1.000 | Documentos <1K tokens se incorporan directo |
| `DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS` | 500 | Tamaño máximo del resumen que devuelve el subagente |
| `DISCRIMINATOR_MAX_SUBTEMAS` | 5 | Máximo de subtemas que propone el discriminador |
| `DISCRIMINATOR_MIN_EXCHANGES_PER_SUBTEMA` | 2 | Mínimo de intercambios por subtema |

#### Directorios del sistema

| Constante | Valor por defecto |
|---|---|
| `WORKSPACE_ROOT` | Directorio padre del paquete `contexto_zai/` |
| `WORKSPACE_OUTPUT_DIR` | `WORKSPACE_ROOT/contexto_recuperacion` |
| `DOWNLOAD_OUTPUT_DIR` | `WORKSPACE_ROOT/download/contexto_recuperacion` |
| `ATTACHMENTS_TEMP_DIR` | `WORKSPACE_ROOT/download/uploads/temp` |
| `ATTACHMENTS_INDEXED_DIR` | `WORKSPACE_ROOT/download/uploads/indexed` |

### 6.2. Variable de entorno opcional

Puedes sobrescribir el workspace del proyecto con la variable de entorno:

```bash
export CZAI_WORKSPACE_DIR=/ruta/personalizada
```

Si no se establece, se usa el directorio padre del paquete `contexto_zai/` automáticamente.

### 6.3. Autenticación con Z.ai

El proceso necesita el JWT del Director para acceder a la API de Z.ai. Hay dos formas de obtenerlo:

#### Método 1: Token directo (recomendado para pruebas)

```python
from contexto_zai.pipeline import run
result = run(chat_id="...", jwt="eyJhbG...")
```

#### Método 2: Sesión del navegador (automático en sandbox)

```python
from contexto_zai.client.browser_session import BrowserSession
from contexto_zai.client.chat_client import ChatClient

session = BrowserSession()
session.authenticate()  # inyecta cookie JWT del Director
client = ChatClient(browser_session=session)
```

El protocolo de inyección de cookie está documentado en `Documentación/metodologia_descubrimiento_jwt.md`.

---

## 7. Funcionalidades

### 7.1. Recuperación de contexto (función principal)

**Qué hace:** Extrae todos los mensajes del chat, los clasifica por temas, y genera 4 tipos de archivos de recuperación que el agente puede consultar bajo demanda.

**Archivos generados:**

| Archivo | Descripción | Límite |
|---|---|---|
| `00_estado_actual.md` | Estado actual del proyecto (8 secciones D1-D4 + A1-A4) | 20K tokens |
| `01_indice_recuperacion.md` | Índice de materias con mapeo tema → archivo | 8K tokens |
| `02_decisiones_clave.md` | Decisiones operativas extraídas del chat | 12K tokens |
| `bloque_*.md` | Bloques temáticos con intercambios completos | 70K tokens/bloque |

**Cómo invocarla:**

```python
from contexto_zai.pipeline import run
from contexto_zai.models import DetectionTrigger

result = run(
    chat_id="13b43432-36d8-4ed0-8fde-2c17e2f90484",
    jwt="eyJhbG...",
    trigger=DetectionTrigger.EXPLICITO,
    reason="Director indicó pérdida de contexto",
    chat_label="Proyecto CZAI",
)
```

### 7.2. Clasificación temática por capas

**Capa 1 — Léxica (`MessageClassifier`):**
Clasifica intercambios por palabras clave del mensaje del Director. El tema con más coincidencias gana. En caso de empate, prioriza el tema del intercambio anterior (continuidad temática).

**Capa 2 — Intención (`IntentionClassifier`, v3.4):**
Si un intercambio se clasifica como "general" en la Capa 1, se analiza la intención del mensaje:
- `solicitud_documentacion` ("describe", "explica", "paso a paso")
- `solicitud_implementacion` ("implementa", "ejecuta", "a ejecutar")
- `aprobacion` ("correcto", "ok", "aprobado")
- `rechazo` ("no estoy de acuerdo", "incorrecto")
- `correccion` ("no lo que te pedí", "mejor hacer")
- `consulta_estado` ("cómo vamos", "qué falta")
- `handoff` ("relee el worklog", "perdiste contexto")
- `priorizacion` ("entrega primero", "urgente")

**Capa 3 — Subagente discriminador (`DiscriminatorSubagent`, v3.4):**
Si un tema (especialmente "general") sigue siendo demasiado grande después de las Capas 1 y 2, se lanza un subagente que:
1. Lee todos los intercambios del tema.
2. Identifica qué se está discutiendo realmente.
3. Propone temas específicos para subdividir.
4. El proceso reasigna los intercambios a los nuevos temas.

### 7.3. Estado con truncamiento lógico (v3.4)

Cuando el estado actual supera el límite de 20K tokens, en vez de cortar con "(truncado por límite de espacio)", aplica truncamiento lógico:

1. Identifica la parte más antigua que no cabe.
2. Resume esa parte sin perder información clave.
3. Añade el resumen al final en una sección "Resumen del contexto excluido".
4. Mantiene el orden cronológico.

### 7.4. Links externos como contexto (v3.4)

Si el Director escribe un link en el chat (ej: "Lee esto: https://ejemplo.com/doc"), el proceso:
1. Detecta la URL con `URL_PATTERN`.
2. Descarga el contenido con `WebReader`.
3. Convierte HTML a texto plano (elimina scripts, estilos, etiquetas).
4. Crea un intercambio virtual con el contenido como respuesta del agente.
5. Lo clasifica con tema `link_externo` y lo empaqueta como cualquier otro.

### 7.5. Documentos adjuntos mediante subagentes efímeros (v3.5)

**Esta es la funcionalidad principal de v3.5.**

Cuando el Director adjunta un documento (PDF, DOCX, TXT) con el botón "+" del chat de Z.ai, el proceso:

1. **`AttachmentDetector`** detecta el attachment en el campo `files` del batch endpoint.
2. **`DocumentDelegator`** decide si delegar al subagente:
   - Si el documento >5K tokens → delega (default).
   - Si el documento <1K tokens → lee directamente.
   - Si el agente principal >80% ocupado → delega.
   - Override del Director: "lee completo" → lee directo; "no leas" → delega.
3. **`DocumentoIndexerSubagent`** (si se delega):
   - Descarga el archivo con `AttachmentClient`.
   - Lo guarda temporalmente en `download/uploads/temp/`.
   - Lanza un subagente efímero que lee el archivo completo con SU contexto independiente.
   - El subagente clasifica el contenido por temas y genera un resumen breve (≤500 chars).
   - El subagente devuelve el resumen + temas al agente principal.
   - El archivo se mueve de `temp/` a `download/uploads/indexed/`.
4. **`IndiceGenerator`** actualiza `01_indice_recuperacion.md` con una sección "Documentos indexados (v3.5)" que lista el documento, sus temas, el resumen y la ruta.

**Resultado:** El agente principal recibe solo el resumen (≤500 chars), no el contenido completo. Esto preserva hasta el 99.9% de su contexto.

**Cómo invocarla manualmente:**

```python
from contexto_zai.pipeline import index_document

# Indexar un documento adjunto
result = index_document(
    file_id="096b178e-a6be-4239-a571-7c15d9229c5f",
    jwt="eyJhbG...",
    filename="CZAI-01.pdf",
)
if result and result.success:
    print(f"Indexado: {result.filename}")
    print(f"Resumen: {result.resumen_breve}")
    print(f"Temas: {result.temas_nombres}")
    print(f"Archivo: {result.archivo_indexado_path}")

# Forzar lectura directa (override "lee completo")
result = index_document(
    file_id="...", jwt="...", filename="doc.pdf",
    force_direct=True,
)
```

### 7.6. Exportación de contexto (v3.4)

Empaqueta todos los archivos del contexto en un `.zip` descargable para transferir a otro agente:

```python
from contexto_zai.pipeline import export_context

zip_path = export_context(chat_id="abc-123")
# zip_path = /home/z/my-project/download/contexto_exportado_abc-123_20260906_023456.zip
```

El ZIP incluye:
- `00_estado_actual.md`
- `01_indice_recuperacion.md`
- `02_decisiones_clave.md`
- `bloque_*.md`
- `_metadata.json`
- `_paquete.json` (metadata del paquete: chat_id, fecha, totales)
- `_instrucciones_recuperacion.md` (protocolo paso a paso)

### 7.7. Importación de contexto (v3.4)

Descomprime un paquete de contexto exportado y lo carga en el workspace:

```python
from contexto_zai.pipeline import import_context, find_context_packages

# Buscar paquetes disponibles
packages = find_context_packages()
# [Path('/home/.../contexto_exportado_abc-123_20260906_023456.zip'), ...]

# Cargar el más reciente
if packages:
    instrucciones = import_context(zip_path=packages[0])
    print("Contexto cargado. Instrucciones:")
    print(instrucciones)
```

### 7.8. Detección de pérdida de contexto

El proceso detecta automáticamente cuándo el agente ha perdido contexto mediante 3 mecanismos:

1. **Disparador léxico:** Detecta frases del Director como "ya te dije", "no repitas", "estás olvidando".
2. **Contador de tokens:** Cuando el agente supera el 90% de su capacidad útil (92.160 tokens).
3. **Auto-preguntas:** El agente se pregunta "¿Sé en qué archivo estoy?" y responde negativamente.

### 7.9. Subagentes efímeros (6 tipos)

El proceso puede lanzar 6 tipos de subagentes especializados:

| Subagente | Función |
|---|---|
| `EstadoSubagent` | Lee el archivo del tema activo y extrae contexto para el estado actual |
| `BarridoSubagent` | Busca información puntual sobre un tema en un archivo específico |
| `DecisionesSubagent` | Extrae decisiones operativas usando LLM (no regex) |
| `MantenimientoSubagent` | Actualización incremental de archivos existentes |
| `DiscriminatorSubagent` | Subdivide un tema grande en subtemas específicos (Capa 3) |
| `DocumentoIndexerSubagent` | Lee, clasifica y resume documentos adjuntos (v3.5) |

### 7.10. Verificación de límites

Después de generar los archivos, `Verifier` verifica que todos cumplen los límites de tokens:

- **OK:** archivo dentro del límite.
- **WARNING:** archivo entre 90% y 110% del límite.
- **ERROR:** archivo supera el 110% del límite.

También verifica que la carga principal (estado + índice + decisiones) no supere los 40K tokens.

### 7.11. Metadata con unicidad temática

El archivo `_metadata.json` registra:
- `chat_id` y `share_id` del chat.
- `ultimo_timestamp` (para incremental).
- `tema_a_archivo`: mapeo tema → archivo (unicidad garantizada).
- `subtemas_derivados`: registro de subtemas creados al subdividir.
- `ultima_activacion`: timestamp ISO de la última activación.

La unicidad temática se valida: si intentas registrar un tema en dos archivos diferentes, lanza `ValueError`.

### 7.12. Scripts versionados (v3.3)

`CodeDetector` identifica scripts en los mensajes del agente y `VersionGraphBuilder` construye un grafo de cambios con diffs forward y reverse. Los grafos se guardan en `_grafos_cambios.json`.

---

## 8. Cómo funciona el proceso

### 8.1. Flujo completo del ciclo de recuperación

```
┌─────────────────────────────────────────────────────────────────────┐
│  PASO -1: Autenticación                                             │
│  - Inyectar cookie JWT del Director en agent-browser               │
│  - Verificar autenticación con /api/v1/auths/                      │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PASO 0: Activación                                                  │
│  - El Director dice "relee el worklog" o "ya te dije"              │
│  - O el contador de tokens supera 92K                              │
│  - O el Director activa explícitamente                              │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PASO 1-2: Estrategia y contexto                                    │
│  - Leer worklog_template.md                                          │
│  - Clonar repo de estrategia                                         │
│  - Leer archivos de contexto (identidad, contrato, entorno, etc.)  │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PASO 3-4: Decisión de ciclo                                         │
│  - Si no hay metadata previa → RecoveryCycle (completo)             │
│  - Si hay metadata previa → IncrementalCycle (solo nuevos msgs)    │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PASO 5: Extracción de mensajes                                     │
│  - POST /api/v1/chats/{chat_id}/share → obtener share_id            │
│  - GET /api/v1/chats/share/{share_id} → árbol de mensajes           │
│  - POST /api/v1/chats/{chat_id}/messages/batch → contenido completo │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PASO 5b (v3.5): Indexación de attachments                           │
│  - AttachmentDetector detecta attachments en el batch                │
│  - DocumentDelegator decide delegación para cada uno                │
│  - DocumentoIndexerSubagent lee+clasifica+resume los delegados      │
│  - Resultados en RecoveryCycleResult.attachments_indexados           │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PASO 6: Clasificación por capas                                    │
│  - Capa 1: léxica (MessageClassifier con keywords)                  │
│  - Capa 2: intención (IntentionClassifier)                          │
│  - Capa 3: DiscriminatorSubagent para temas grandes                 │
│  - Subdivider: subdivide temas que superan 70K tokens               │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PASO 6b (v3.3): Scripts versionados                                 │
│  - CodeDetector detecta scripts en mensajes del agente               │
│  - VersionGraphBuilder construye grafo de cambios                   │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PASO 7: Generación de archivos                                     │
│  - 02_decisiones_clave.md (DecisionesGenerator)                     │
│  - 00_estado_actual.md (EstadoGenerator con truncamiento lógico)    │
│  - 01_indice_recuperacion.md (IndiceGenerator con documentos v3.5)  │
│  - bloque_*.md (BloqueGenerator)                                     │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PASO 8-9: Subagentes de estado y barrido                            │
│  - EstadoSubagent extrae contexto del tema activo                   │
│  - BarridoSubagent busca info puntual bajo demanda                   │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PASO 10-11: Verificación y escritura                                │
│  - Verifier comprueba límites de tokens                              │
│  - Escribir archivos en workspace/ y download/                       │
│  - MetadataManager persiste _metadata.json                           │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PASO 12-13: Confirmación                                            │
│  - Reportar al Director: archivos generados, temas, bloques        │
│  - Si hay errores, listar para corrección                            │
└─────────────────────────────────────────────────────────────────────┘
```

### 8.2. Flujo de indexación de documentos (v3.5)

```
Director adjunta PDF con botón "+"
                │
                ▼
┌─────────────────────────────────────────┐
│  AttachmentDetector                     │
│  detect_in_raw_messages(raw_batch)      │
│  → [Attachment(file_id, filename, ...)]│
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  DocumentDelegator                     │
│  should_delegate(size, context, override)│
│                                          │
│  Criterio:                              │
│  - Override "lee completo" → False     │
│  - Override "no leas" → True            │
│  - size < 1000 → False (trivial)       │
│  - size > 5000 → True (delegar)        │
│  - context > 80% → True                │
│  - Otro caso → False                    │
└─────────────────┬───────────────────────┘
                  │
        ┌─────────┴─────────┐
        │                   │
   delega=True         delega=False
        │                   │
        ▼                   ▼
┌─────────────────┐  ┌─────────────────┐
│ DocumentoIndexer│  │ Lectura directa │
│ Subagent        │  │ (AttachmentClient│
│                 │  │  + WebReader)   │
│ 1. Descarga     │  │                 │
│ 2. Guarda temp/ │  │ Crea intercambio│
│ 3. Lanza Task   │  │ virtual con     │
│ 4. Subagente lee│  │ contenido       │
│    completo     │  │ completo        │
│ 5. Clasifica    │  └─────────────────┘
│ 6. Resume ≤500  │
│ 7. Mueve a      │
│    indexed/     │
└─────────┬───────┘
          │
          ▼
┌─────────────────────────────────────────┐
│ DocumentoIndexResult                   │
│  - attachment_id                       │
│  - filename                            │
│  - resumen_breve (≤500 chars)          │
│  - temas_detectados: [ThemeSection]    │
│  - archivo_indexado_path               │
│  - success: bool                       │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│ IndiceGenerator                        │
│  - Sección "Documentos indexados" en   │
│    01_indice_recuperacion.md           │
│  - Tabla: documento, temas, resumen, │
│    ruta                                │
└─────────────────────────────────────────┘
```

---

## 9. API pública

### 9.1. pipeline.py — Funciones principales

#### `run(chat_id, jwt, ...)`

Activa el proceso de recuperación de contexto completo.

```python
from contexto_zai.pipeline import run
from contexto_zai.models import DetectionTrigger

result = run(
    chat_id="13b43432-36d8-4ed0-8fde-2c17e2f90484",
    jwt="eyJhbG...",
    trigger=DetectionTrigger.EXPLICITO,  # default
    reason="Director indicó pérdida de contexto",
    chat_label="Proyecto CZAI",
    workspace_dir=WORKSPACE_OUTPUT_DIR,  # default
    download_dir=DOWNLOAD_OUTPUT_DIR,    # default
)
# result: OrchestratorResult
#   .success: bool
#   .cycle_used: "recovery" | "incremental"
#   .files_generated: list[str]
#   .error: str (si falló)
```

#### `status(chat_id, workspace_dir)`

Devuelve el estado actual del proceso.

```python
from contexto_zai.pipeline import status

st = status(chat_id="abc-123")
# st = {
#   "metadata_exists": True,
#   "chat_id": "abc-123",
#   "total_exchanges": 45,
#   "ultimo_timestamp": 1788445359,
#   "ultima_activacion": "2026-09-06T...",
#   "temas_registrados": ["validaciones", "configuracion_proyecto", ...],
# }
```

#### `export_context(chat_id, workspace_dir, output_dir)`

Empaqueta el contexto en un `.zip` descargable.

```python
from contexto_zai.pipeline import export_context

zip_path = export_context(chat_id="abc-123")
# zip_path = Path('/home/.../contexto_exportado_abc-123_20260906_023456.zip')
```

#### `import_context(zip_path, workspace_dir)`

Descomprime un paquete de contexto y lo carga.

```python
from contexto_zai.pipeline import import_context

instrucciones = import_context(zip_path="/path/to/contexto.zip")
# instrucciones = str (contenido de _instrucciones_recuperacion.md)
```

#### `find_context_packages(search_dir)`

Busca paquetes de contexto exportados.

```python
from contexto_zai.pipeline import find_context_packages

packages = find_context_packages()
# [Path('/home/.../contexto_exportado_abc-123_20260906.zip'), ...]
# Ordenado por fecha (más reciente primero)
```

#### `index_document(file_id, jwt, filename, content_type, size, force_direct)` (v3.5)

Indexa un documento adjunto en tiempo real.

```python
from contexto_zai.pipeline import index_document

result = index_document(
    file_id="096b178e-a6be-4239-a571-7c15d9229c5f",
    jwt="eyJhbG...",
    filename="CZAI-01.pdf",
    content_type="application/pdf",  # opcional, se detecta por magic number
    size=1652025,                    # opcional
    force_direct=False,              # True = lee directo sin subagente
)
# result: DocumentoIndexResult | None
#   .success: bool
#   .filename: str
#   .resumen_breve: str (≤500 chars)
#   .temas_detectados: list[ThemeSection]
#   .archivo_indexado_path: Path
```

### 9.2. Clientes (client/)

#### `AuthClient`

```python
from contexto_zai.client.auth_client import AuthClient

with AuthClient(token="eyJhbG...") as auth:
    share_id = auth.create_share(chat_id="13b43432-...")
    # share_id = "1d1196b7-18e1-43c7-8869-e59d2dba45f7"
```

#### `ChatClient`

```python
from contexto_zai.client.chat_client import ChatClient

with ChatClient(token="eyJhbG...") as client:
    messages = client.extract_all(share_id="...", chat_id="...")
    # messages: list[Message]

    # v3.5: también devuelve el JSON crudo del batch (con attachments)
    messages, raw = client.extract_all_with_raw(share_id="...", chat_id="...")
```

#### `AttachmentClient` (v3.5)

```python
from contexto_zai.client.attachment_client import AttachmentClient

with AttachmentClient(token="eyJhbG...") as client:
    content = client.download("file_id_abc")
    # content: bytes (contenido binario del archivo)

    client.download_to_file("file_id_abc", "/tmp/doc.pdf")
    # Guarda el archivo en disco

    # Detección de tipo por magic number
    mime = AttachmentClient.detect_type_by_magic(b"%PDF-1.4...")
    # mime = "application/pdf"
```

#### `WebReader` (v3.4)

```python
from contexto_zai.client.web_reader import WebReader

reader = WebReader()
content = reader.read("https://ejemplo.com/articulo")
# content: ExternalContent(url, title, content, source)

urls = WebReader.find_urls("Lee esto: https://a.com y https://b.com")
# urls = ["https://a.com", "https://b.com"]
```

### 9.3. Procesamiento (processing/)

#### `AttachmentDetector` (v3.5)

```python
from contexto_zai.processing.attachment_detector import AttachmentDetector

detector = AttachmentDetector()
attachments = detector.detect_in_raw_messages(raw_batch_json)
# attachments: list[Attachment]

# Filtrar por tipo
pdfs = detector.filter_by_content_type(attachments, "application/pdf")
docs = detector.filter_by_media(attachments, "doc")
```

#### `DocumentDelegator` (v3.5)

```python
from contexto_zai.processing.content_delegator import DocumentDelegator

delegator = DocumentDelegator()
should = delegator.should_delegate(
    content_size_tokens=165000,
    agent_context_available_pct=20,
    director_override=None,  # o "lee completo" / "no leas"
)
# should = True (delega al subagente)
```

### 9.4. Subagentes (subagents/)

#### `DocumentoIndexerSubagent` (v3.5)

```python
from contexto_zai.subagents.documento_indexer_subagent import DocumentoIndexerSubagent
from contexto_zai.subagents.launcher import SubagentLauncher
from contexto_zai.client.attachment_client import AttachmentClient

launcher = SubagentLauncher()
client = AttachmentClient(token="eyJhbG...")
indexer = DocumentoIndexerSubagent(
    launcher=launcher,
    attachment_client=client,
    max_resumen_chars=500,
)

result = indexer.run(attachment)
# result: DocumentoIndexResult
#   .success: bool
#   .resumen_breve: str
#   .temas_detectados: list[ThemeSection]
#   .archivo_indexado_path: Path
```

#### `DiscriminatorSubagent` (v3.4)

```python
from contexto_zai.subagents.discriminator_subagent import DiscriminatorSubagent

sub = DiscriminatorSubagent(launcher=launcher)
proposal = sub.run(tema="general", exchanges=large_exchanges)
# proposal: SubdivisionProposal
#   .is_valid: bool
#   .subtemas: list[SubtemaProposal]
#   .tema_padre: str

if proposal.is_valid:
    sub.apply(proposal, exchanges)  # reclasifica intercambios
```

---

## 10. Pruebas realizadas

### 10.1. Resumen de tests

El proyecto tiene **3 niveles de tests**:

| Nivel | Archivos | Tests | Descripción |
|---|---|---|---|
| **Atómicos standalone** | 37 módulos | 37 | Auto-tests en `__main__` de cada módulo |
| **Integración** | 3 archivos | 3 | Tests de integración entre módulos |
| **E2E** | 2 archivos | 31 | Tests end-to-end del flujo completo |
| **TOTAL** | **9 archivos** | **71 tests** | |

### 10.2. Test runner principal (`tests/run_all_tests.py`)

```bash
python tests/run_all_tests.py
```

**Resultado esperado:**
```
============================================================
FASE 1: Auto-tests de modulos atomicos
============================================================
  [PASS]  config.py
  [PASS]  models.py
  [PASS]  client/browser_session.py
  ... (37 módulos en total)
  [PASS]  pipeline.py

============================================================
FASE 2: Tests de integracion
============================================================
  [PASS]  tests/test_classifier_packer_subdivider.py
  [PASS]  tests/test_estado_indice_generation.py
  [PASS]  tests/test_recovery_cycle.py

============================================================
FASE 3: Test E2E
============================================================
  [PASS]  tests/test_e2e_pipeline.py

============================================================
RESULTADO FINAL
  Total tests ejecutados: 41
  Pasaron: 41
  Fallaron: 0
============================================================
```

### 10.3. Tests E2E específicos v3.5 (`tests/test_v35_attachments.py`)

```bash
python tests/test_v35_attachments.py
```

**15 tests** que validan:

| # | Test | Qué valida |
|---|---|---|
| 1 | `attachment_client_magic_numbers` | Detección de PDF, ZIP, PNG, JPEG, texto, binario |
| 2 | `attachment_client_download_with_mock` | Descarga con mock httpx + errores HTTP 401/403/404 + tamaño excedido |
| 3 | `attachment_client_download_to_file` | Guarda archivo en disco correctamente |
| 4 | `attachment_detector_real_json` | Detector con JSON crudo real del batch endpoint |
| 5 | `document_delegator_all_cases` | 12 casos: override, trivial, umbral, contexto |
| 6 | `documento_indexer_subagent_full_flow` | Flujo completo del subagente con mock invoker |
| 7 | `documento_indexer_error_handling` | Manejo de errores: descarga fallida, subagente falla, mal formado |
| 8 | `indice_generator_with_attachments` | Sección "Documentos indexados (v3.5)" en índice |
| 9 | `pipeline_index_document` | `index_document()` con mock |
| 10 | `full_e2e_attachment_flow` | **Flujo E2E completo** con PDF simulado (6 pasos, ahorro 100%) |
| 11 | `attachment_model_properties` | Modelo Attachment: PDF, TXT, DOCX, imagen |
| 12 | `content_delegator_abstract_interface` | ContentDelegator abstracta + Subdivider refactorizado |
| 13 | `exchange_builder_with_attachments` | ExchangeBuilder: PDF delegado + TXT directo + sin truncado |
| 14 | `recovery_cycle_result_with_attachments` | RecoveryCycleResult con `attachments_indexados` |
| 15 | `chat_client_extract_all_with_raw` | `extract_all_with_raw()` devuelve tupla (messages, raw) |

### 10.4. Tests E2E generales (`tests/test_e2e_pipeline.py`)

```bash
python tests/test_e2e_pipeline.py
```

**16 tests** que validan:

| # | Test | Qué valida |
|---|---|---|
| 1 | `pipeline_run_success` | Pipeline completo arranca y completa sin errores |
| 2 | `all_4_file_types_generated` | Genera los 4 tipos de archivo (estado, índice, decisiones, bloques) |
| 3 | `estado_with_8_sections` | Estado actual tiene las 8 secciones D1-D4 + A1-A4 |
| 4 | `indice_with_mapping_table` | Índice tiene tabla de mapeo tema → archivo |
| 5 | `metadata_correct` | `_metadata.json` se escribe correctamente |
| 6 | `no_block_exceeds_70k_tokens` | Ningún bloque supera 70K tokens |
| 7 | `unicity_tematica` | Unicidad temática (no se repite tema en varios archivos) |
| 8 | `status_function` | `status()` devuelve metadata correcta |
| 9 | `orchestrator_chooses_recovery_when_no_metadata` | Orchestrator elige RecoveryCycle si no hay metadata |
| 10 | `files_in_workspace_and_download` | Archivos escritos tanto en workspace como en download |
| 11 | `windows_path_compatibility` | Paths multiplataforma (funciona en Windows) |
| 12 | `fix1_links_externos` (v3.4) | Links externos se procesan como intercambios |
| 13 | `fix2_capa3_discriminator` (v3.4) | Capa 3 discriminador integrado |
| 14 | `fix3_truncamiento_logico` (v3.4) | Estado con truncamiento lógico |
| 15 | `v34_export_import_context` (v3.4) | Exportación/importación de contexto |
| 16 | `v35_attachment_pipeline` (v3.5) | Pipeline completo con attachments |

### 10.5. Tests de integración

- **`test_classifier_packer_subdivider.py`:** Valida clasificador + block packer + subdivider.
- **`test_estado_indice_generation.py`:** Valida generación de estado, índice y decisiones.
- **`test_recovery_cycle.py`:** Valida el ciclo completo de recuperación con API simulada.
- **`test_subagent_lifecycle.py`:** Valida el ciclo de vida de los subagentes efímeros.
- **`test_code_detector.py`:** Valida detección de scripts versionables.
- **`test_version_graph.py`:** Valida construcción del grafo de versiones.

### 10.6. Cómo ejecutar todos los tests

```bash
# Tests atómicos + integración + E2E
python tests/run_all_tests.py

# Tests E2E específicos de v3.5 (attachments)
python tests/test_v35_attachments.py

# Ejecutar un módulo atómico standalone
python contexto_zai/config.py
python contexto_zai/client/attachment_client.py
python contexto_zai/subagents/documento_indexer_subagent.py
```

### 10.7. Cobertura de tests

| Componente | Tests | Cobertura |
|---|---|---|
| config.py | 12 | Constantes, límites, patrones |
| models.py | 10 | Modelos Pydantic, Attachment |
| client/ | 8 por módulo | Auth, Chat, Browser, WebReader, AttachmentClient |
| processing/ | 6-12 por módulo | Classifier, IntentionClassifier, ContentDelegator, AttachmentDetector, etc. |
| generation/ | 5-7 por módulo | Estado, Índice, Decisiones, Bloque, Recovery |
| subagents/ | 7-12 por módulo | Launcher, 6 subagentes especializados |
| process/ | 10 por módulo | Orchestrator, RecoveryCycle, IncrementalCycle |
| pipeline.py | 10 | run, status, export, import, index_document |
| E2E | 16 + 15 = 31 | Flujo completo, attachments, export/import |

---

## 11. Casos de uso

### 11.1. Caso 1: Recuperación de contexto estándar

**Escenario:** El agente pierde contexto después de una conversación larga.

```python
from contexto_zai.pipeline import run

result = run(
    chat_id="13b43432-...",
    jwt="eyJhbG...",
    reason="Agente superó 90% de contexto",
)
```

**Archivos generados:**
```
contexto_recuperacion/
├── 00_estado_actual.md          ← estado del proyecto
├── 01_indice_recuperacion.md    ← índice de materias
├── 02_decisiones_clave.md       ← decisiones operativas
├── bloque_validaciones.md       ← intercambios sobre validaciones
├── bloque_configuracion.md      ← intercambios sobre configuración
├── bloque_general.md            ← intercambios varios
├── _metadata.json               ← metadata de recuperación
└── _grafos_cambios.json         ← grafo de scripts versionados
```

### 11.2. Caso 2: Documento PDF adjunto

**Escenario:** El Director adjunta un PDF de 200 páginas con la memoria del proyecto.

```python
from contexto_zai.pipeline import index_document

result = index_document(
    file_id="096b178e-...",
    jwt="eyJhbG...",
    filename="CZAI-01.pdf",
)
print(result.resumen_breve)
# "Documento de 208 páginas con la memoria completa del proyecto CZAI..."
print(result.temas_nombres)
# ['worklog_sesiones_anteriores', 'especificacion_recuperacion_contexto', ...]
```

**El agente principal consume solo ~72 tokens** (el resumen), no los 165K tokens del PDF completo.

### 11.3. Caso 3: Transferencia de contexto entre agentes

**Escenario:** El agente A termina su sesión y quiere pasar el contexto al agente B.

```python
# Agente A: exportar contexto
from contexto_zai.pipeline import export_context
zip_path = export_context(chat_id="abc-123")

# Agente B: importar contexto al iniciar sesión
from contexto_zai.pipeline import find_context_packages, import_context
packages = find_context_packages()
if packages:
    instrucciones = import_context(zip_path=packages[0])
    print(instrucciones)  # protocolo de recuperación paso a paso
```

### 11.4. Caso 4: Override del Director

**Escenario:** El Director quiere que el agente lea un documento completo sin subagente.

```python
from contexto_zai.pipeline import index_document

# Forzar lectura directa
result = index_document(
    file_id="...",
    jwt="...",
    filename="doc.pdf",
    force_direct=True,  # override "lee completo"
)
# El agente principal consume el contenido completo del documento
```

### 11.5. Caso 5: Detección automática de pérdida de contexto

**Escenario:** El agente detecta automáticamente que perdió contexto.

```python
from contexto_zai.detection.lexic_trigger import LexicTrigger
from contexto_zai.detection.token_counter import TokenCounter

# Disparador léxico
trigger = LexicTrigger()
if trigger.detect("ya te dije que no repitas eso"):
    # Activa recuperación
    run(chat_id="...", jwt="...")

# Contador de tokens
counter = TokenCounter()
if counter.exceeds_threshold(92160):
    # Activa recuperación
    run(chat_id="...", jwt="...")
```

---

## 12. Solución de problemas

### 12.1. `ModuleNotFoundError: No module named 'contexto_zai'`

**Causa:** El stub de `sys.path` no detecta la estructura del proyecto.

**Solución:** Verifica que estás en el directorio correcto:

```bash
# Estructura A (Linux)
cd /home/usuario/workspace
python tests/run_all_tests.py

# Estructura B (Windows)
cd C:\Python\Proyectos
python tests\run_all_tests.py
```

El stub nuevo (v3.5) detecta automáticamente la raíz del paquete (directorio con `__init__.py` cuyo padre no tiene `__init__.py`).

### 12.2. `ImportError: cannot import name 'DELEGATION_CONTEXT_LIMIT_PCT'`

**Causa:** Tienes una versión antigua de `config.py` (v3.4 o anterior).

**Solución:** Descarga el ZIP más reciente de `contexto_zai_completo.zip` y reemplaza todos los archivos.

### 12.3. `ShareCreationError: Sin permisos para crear share (HTTP 401)`

**Causa:** El JWT no es válido o ha expirado.

**Solución:**
1. Obtén el JWT actualizado de Z.ai (DevTools → Application → Cookies → `token`).
2. Pásalo al proceso: `run(chat_id="...", jwt="eyJhbG...")`.
3. Si usas `BrowserSession`, ejecuta `session.authenticate()` para inyectar la cookie.

### 12.4. `AttachmentDownloadError: Token inválido o expirado (HTTP 401)`

**Causa:** El JWT no tiene permisos para descargar el attachment.

**Solución:** Verifica que el JWT sea del Director (no de invitado) y que el chat_id corresponda al chat donde se adjuntó el archivo.

### 12.5. Los archivos generados están vacíos

**Causa:** Probablemente el chat no tiene mensajes o la extracción falló silenciosamente.

**Solución:**
1. Verifica que el chat_id sea correcto.
2. Ejecuta con logging habilitado:
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```
3. Revisa los logs para identificar dónde falla la extracción.

### 12.6. El subagente no devuelve respuesta

**Causa:** El `SubagentLauncher` no puede ejecutar el Task de Z.ai (probablemente en entorno local sin acceso a la API de Task).

**Solución:** En tests, inyecta un `task_invoker` mock:

```python
from contexto_zai.subagents.launcher import SubagentLauncher

def mock_invoker(prompt: str) -> str:
    return "RESUMEN: Test\n\nTEMA: tema1\nDESCRIPCION: desc\nSECCIONES: s1"

launcher = SubagentLauncher(task_invoker=mock_invoker)
```

### 12.7. Windows: acentos y caracteres especiales

**Causa:** La consola de Windows no usa UTF-8 por defecto.

**Solución:** Todos los módulos reconfiguran stdout/stderr a UTF-8 automáticamente. Si aún tienes problemas, ejecuta:

```powershell
chcp 65001
python tests\run_all_tests.py
```

---

## 13. Roadmap y versiones

### 13.1. Historial de versiones

| Versión | Fecha | Cambios principales |
|---|---|---|
| v1.0 | 2025-09-02 | CLI con Click, 22 archivos Python, pipeline básico |
| v2.0 | 2025-09-04 | Refactor OOP, eliminación de CLI, 32 tests |
| v3.0 | 2025-09-04 | Spec v3.0, autenticación automática vía cookie |
| v3.1 | 2025-09-04 | Spec v3.1, 8 secciones en estado actual |
| v3.2 | 2025-09-05 | Límites actualizados (40K carga principal), metadata con unicidad |
| v3.3 | 2025-09-05 | Scripts versionados, grafo de cambios |
| v3.4 | 2026-09-05 | Links externos, clasificación por capas (3 niveles), truncamiento lógico, export/import de contexto |
| **v3.5** | **2026-09-06** | **Indexación de documentos adjuntos mediante subagentes efímeros** |

### 13.2. Funcionalidades por versión

#### v3.5 (actual)
- `AttachmentClient`: descarga archivos desde `/api/v1/files/{id}/content`.
- `AttachmentDetector`: detecta attachments en JSON crudo del batch endpoint.
- `ContentDelegator` + `DocumentDelegator`: decide delegación con override del Director.
- `DocumentoIndexerSubagent`: subagente que lee, clasifica y resume documentos.
- `ExchangeBuilder` refactorizado: links + attachments unificados, sin truncado 10K.
- `IndiceGenerator` con sección "Documentos indexados (v3.5)".
- `pipeline.index_document()`: indexa documentos en tiempo real.
- `Subdivider` refactorizado para implementar `ContentDelegator`.

#### v3.4
- `WebReader`: lee URLs externas.
- `IntentionClassifier`: Capa 2 de clasificación por intención.
- `DiscriminatorSubagent`: Capa 3 con subagentes.
- `EstadoGenerator` con truncamiento lógico.
- `ContextExporter` + `ContextImporter`: export/import de contexto.

#### v3.3
- `CodeDetector`: detecta scripts versionables.
- `VersionGraphBuilder`: grafo de cambios con diffs.

#### v3.2
- `BrowserSession`: autenticación automática vía cookie.
- `MetadataManager` con unicidad temática.
- Límites actualizados (40K carga principal).

#### v3.0-v3.1
- `Orchestrator`: decide entre RecoveryCycle e IncrementalCycle.
- 8 secciones en estado actual (D1-D4 + A1-A4).

### 13.3. Funcionalidades futuras (pendientes de consenso)

- **OCR para imágenes:** Integrar `pytesseract` para leer imágenes adjuntas.
- **Audio transcripción:** Integrar Whisper para transcribir audios adjuntos.
- **Búsqueda semántica:** En vez de clasificación léxica, usar embeddings para encontrar temas similares.
- **Cache de attachments:** Evitar re-descargar attachments ya indexados.
- **Multi-agente:** Soportar múltiples agentes CZAI compartiendo el mismo contexto.

---

## Apéndice A: Glosario

- **Agente principal:** El agente Z.ai con el que el Director interactúa directamente.
- **Subagente efímero:** Un agente lanzado por el proceso para realizar una tarea específica (leer un archivo, clasificar un tema) con su propio contexto independiente.
- **Attachment:** Archivo adjunto que el Director entrega al agente mediante el botón "+" del chat de Z.ai.
- **Delegación:** Decisión de si el agente principal procesa un contenido directamente o lo cede a un subagente.
- **Intercambio (Exchange):** Unidad de conversación compuesta por un mensaje del Director + las respuestas del agente.
- **Bloque temático (ThematicBlock):** Agrupación de intercambios por tema, empaquetados en un archivo `bloque_*.md`.
- **Capa 1/2/3:** Niveles de clasificación temática (léxica, intención, discriminador).
- **RecoveryCycle:** Ciclo completo de recuperación (extracción → clasificación → generación).
- **IncrementalCycle:** Actualización incremental de archivos existentes con nuevos mensajes.
- **Truncamiento lógico:** Resumir la parte excluida en vez de cortar a secas.

## Apéndice B: Referencias

- **Spec v3.5:** `download/spec_recuperacion_contexto_v3.5.md`
- **Plan v3.5:** `download/plan_refactorizacion_v3.5.md`
- **Metodología JWT:** `contexto_zai/Documentación/metodologia_descubrimiento_jwt.md`
- **Worklog del proyecto:** `worklog.md` (en la raíz del workspace)
- **Estrategia de agentes:** `estrategia/` (repo separado)

## Apéndice C: Contacto

- **Director del proyecto:** Juan Carlos González (`juanca6507@gmail.com`)
- **Agente CZAI:** Implementado por sesiones consecutivas de Z.ai
- **Repositorio de estrategia:** `github.com/Juank6507/estrategia-agentes-zai`

---

**Fin del manual.**

Para cualquier duda o problema, consulta la sección 12 (Solución de problemas) o revisa los tests E2E para ejemplos de uso completos.
