# contexto_zai/Documentación/spec_recuperacion_contexto_v5.0.md
# Spec v5.0 — Proxy de subagentes + Separación de plataforma

**Versión:** 5.0
**Fecha:** 2026-09-20
**Autor:** Agente CZAI (Sesión 19, con consenso del Director)
**Estado:** Pendiente de validación por el Director.
**Especifica continuación de:** spec v4.5 (índice multi-bloque + 03 ampliado + eliminación de 04_resumenes).
**Spec asociada:** esta.
**Plan asociado:** plan_refactorizacion_v5.0.md.

---

## 1. Propósito

La v5.0 introduce dos cambios arquitectónicos que hacen al proceso más independiente del agente y más portable a otras plataformas:

1. **Proxy de subagentes**: un servicio que sustituye al agente en la coordinación de subagentes. El proceso le dice al proxy "necesito un subagente que haga X", y el proxy lo lanza directamente en el LLM, sin pasar por el agente. El agente gasta muchos menos tokens de su ventana.

2. **Separación de plataforma por OOP**: lo que depende exclusivamente de Z.ai (autenticación, extracción de mensajes, formato de links) se separa del resto del proceso mediante interfaces. Z.ai es una implementación de esas interfaces. El proceso queda portable a cualquier plataforma que ofrezca capacidades similares.

## 2. El proxy de subagentes

### 2.1. El problema actual

Hoy el flujo de coordinación de subagentes es:

1. El proceso publica tareas en `_pending_tasks.json`.
2. El agente lee las tareas (gasta tokens de su ventana).
3. El agente lanza los subagentes con el Task tool (gasta más tokens).
4. Los subagentes escriben respuestas en `_responses/`.
5. El agente llama a `collect_responses()` (gasta más tokens).

El agente gasta una parte importante de su ventana de contexto en **coordinación**, no en trabajar el proyecto. Para un chat con 100 tareas pendientes, el agente puede gastar 20K-40K tokens solo en lanzar y coordinar subagentes.

### 2.2. La solución

Un **proxy** que vive en el sandbox de Z.ai (junto al proceso) y que:

1. Lee las tareas pendientes de `_pending_tasks.json` automáticamente.
2. Lanza cada tarea directamente al LLM (vía `internal-api.z.ai/v1/chat/completions`).
3. Escribe las respuestas en `_responses/`.
4. Avisa al proceso que las respuestas están listas.

El agente solo llama a `pipeline.run()` y después a `collect_responses()`. No tiene que leer tareas, ni lanzar subagentes, ni esperar respuestas. Todo lo hace el proxy en segundo plano.

### 2.3. Latencia y eficiencia

El proxy introduce consideraciones de latencia y eficiencia que hay que valorar:

| Aspecto | Hoy (agente coordina) | Con proxy |
|---|---|---|
| **Tokens del agente** | 20K-40K por sesión (lanzar + coordinar) | ~0 (no coordina nada) |
| **Latencia por subagente** | ~30-60s (Task tool) | ~5-15s (LLM directo, sin overhead del Task tool) |
| **Paralelismo** | Limitado por la ventana del agente | Limitado por la conexión del proxy |
| **Dependencia del agente** | Alta (sin agente, no hay subagentes) | Baja (el proxy funciona solo) |
| **Disponibilidad** | Solo cuando el agente está activo | Siempre que el sandbox esté activo |

**Latencia**: el proxy llama al LLM directamente (HTTP POST a `internal-api.z.ai`), sin pasar por el Task tool. El Task tool añade overhead (creación de instancia efímera, inicialización, carga de contexto). El LLM directo responde en 5-15 segundos; el Task tool tarda 30-60 segundos. El proxy es más rápido.

**Paralelismo**: el proxy puede lanzar varios subagentes en paralelo (múltiples peticiones HTTP simultáneas). El agente también puede (lanza varios Task tools en un solo mensaje), pero cada uno consume tokens de su ventana. El proxy no tiene ese límite.

**Eficiencia**: el proxy elimina el gasto de tokens del agente en coordinación. Esos tokens quedan disponibles para que el agente trabaje el proyecto. El agente puede dedicar toda su ventana a leer los 4 archivos de recuperación y trabajar, en vez de gastarla en lanzar subagentes.

### 2.4. Arquitectura del proxy

```
┌─────────────────────────────────────────────────────────┐
│  SANDBOX DE Z.AI                                         │
│                                                          │
│  ┌──────────────┐     ┌──────────────────────────┐      │
│  │  Proceso CZAI │     │  Proxy de subagentes     │      │
│  │  (Python)     │     │  (Next.js / TypeScript)  │      │
│  │               │     │                          │      │
│  │  pipeline.run │     │  1. Lee _pending_tasks   │      │
│  │  → publica    │────→│     .json               │      │
│  │    tareas     │     │                          │      │
│  │               │     │  2. Para cada tarea:     │      │
│  │  collect_     │     │     POST LLM con prompt   │      │
│  │  responses ←──│─────│     → escribe _responses/│      │
│  │               │     │                          │      │
│  └──────────────┘     │  3. Avisa al proceso     │      │
│                       │     (señal/file)          │      │
│                       └───────────┬──────────────┘      │
│                                   │                     │
│                                   │ HTTP POST            │
│                                   ▼                     │
│                       internal-api.z.ai/v1/             │
│                       chat/completions                  │
│                                   │                     │
│                                   ▼                     │
│                       glm-4-plus (LLM real)              │
│                                                          │
└─────────────────────────────────────────────────────────┘
         ▲
         │ El agente NO interviene en la coordinación
         │ Solo llama pipeline.run() y collect_responses()
         ▲
┌────────┴────────┐
│  AGENTE          │
│  (Z.ai)          │
│                  │
│  pipeline.run()  │──→ proceso genera archivos + publica tareas
│  collect_        │──→ proceso integra respuestas del proxy
│  responses()    │
│                  │
│  Lee los 4       │
│  archivos de     │
│  recuperación    │
└──────────────────┘
```

### 2.5. Cómo sabe el proceso que las respuestas están listas

El proxy escribe las respuestas en `_responses/` (igual que hoy lo hacen los subagentes). El proceso, cuando el agente llama a `collect_responses()`, lee las respuestas de ahí. No necesita saber quién las escribió — si están en `_responses/`, las integra.

**No hay polling**: el proxy escribe las respuestas cuando terminan. El agente llama a `collect_responses()` cuando está listo para integrar. Si algunas respuestas todavía no llegaron, `collect_responses()` integra las que están y deja las demás para la próxima.

### 2.6. El proxy reutiliza la infraestructura existente

El proxy de CZAI reutiliza el mismo patrón que el proxy de APA:

- `_lib.ts` lee las credenciales de `/etc/.z-ai-config`.
- Los endpoints reenvían a `internal-api.z.ai/v1/chat/completions`.
- El proxy descarta los headers del llamante y usa credenciales reales.

La diferencia es que el proxy de CZAI:
- No recibe peticiones desde fuera (no es un endpoint HTTP público).
- Lee tareas de un archivo (`_pending_tasks.json`).
- Escribe respuestas a archivos (`_responses/`).
- Funciona en segundo plano (daemon o servicio Bun).

### 2.7. Compatibilidad con el flujo actual

El proxy es **opt-in**: si no está corriendo, el proceso funciona como hoy (el agente lanza los subagentes). Si está corriendo, el proceso no publica tareas en `_pending_tasks.json` — le dice al proxy directamente.

Esto permite una transición gradual: primero se monta el proxy, se prueba, y cuando funciona, se cambia el proceso para que lo use por defecto.

## 3. Separación de plataforma por OOP

### 3.1. El problema actual

El proceso está casado con Z.ai en varios sitios:

| Componente | Dependencia de Z.ai | Archivo |
|---|---|---|
| Autenticación (JWT) | Cookie `token` de Z.ai | `client/auth_client.py` |
| Extracción de mensajes | API `chat.z.ai/api/v1/chats/` | `client/chat_client.py` |
| Links `/s/` y `/c/` | Formato de URL de Z.ai | `pipeline.py` |
| Lanzamiento de subagentes | Task tool de Z.ai | `subagents/launcher.py` |
| Credenciales del sandbox | `/etc/.z-ai-config` | `src/app/api/zai-proxy/_lib.ts` |

El resto del proceso — clasificar, empaquetar en bloques, indexar, generar archivos de recuperación, consultar temas — **no depende de Z.ai**. Es lógica del proceso que serviría en cualquier plataforma.

### 3.2. La solución

Separar mediante **interfaces** (clases abstractas) lo que el proceso necesita de lo que cada plataforma proporciona:

```
contexto_zai/
├── platform/
│   ├── __init__.py
│   ├── interfaces.py          ← Interfaces abstractas (lo que el proceso necesita)
│   │   ├── PlatformAuth       ← Autenticarse (obtener token)
│   │   ├── PlatformChat       ← Extraer mensajes de un chat
│   │   ├── PlatformLinks      ← Parsear links de la plataforma
│   │   └── PlatformLLM        ← Llamar al LLM (para el proxy)
│   │
│   ├── zai/
│   │   ├── __init__.py
│   │   ├── zai_auth.py        ← Implementación de PlatformAuth para Z.ai (JWT)
│   │   ├── zai_chat.py        ← Implementación de PlatformChat para Z.ai (API)
│   │   ├── zai_links.py       ← Implementación de PlatformLinks para Z.ai (/s/, /c/)
│   │   └── zai_llm.py         ← Implementación de PlatformLLM para Z.ai (internal-api)
│   │
│   └── (futuro: otras plataformas)
│       ├── openai/
│       ├── anthropic/
│       └── ...
```

### 3.3. Las 4 interfaces

#### `PlatformAuth`

```python
class PlatformAuth(ABC):
    @abstractmethod
    def get_token(self) -> str:
        """Obtiene el token de autenticación de la plataforma."""
        pass

    @abstractmethod
    def create_share(self, chat_id: str) -> str:
        """Crea un share de un chat (si la plataforma lo soporta)."""
        pass
```

#### `PlatformChat`

```python
class PlatformChat(ABC):
    @abstractmethod
    def extract_messages(self, chat_id: str, share_id: str = "") -> list[Message]:
        """Extrae todos los mensajes de un chat."""
        pass

    @abstractmethod
    def get_chat_tree(self, share_id: str) -> dict:
        """Obtiene el árbol de mensajes de un share (si aplica)."""
        pass
```

#### `PlatformLinks`

```python
class PlatformLinks(ABC):
    @abstractmethod
    def parse_link(self, url: str) -> dict:
        """Parsea un link de la plataforma y devuelve {type, id}."""
        pass

    @abstractmethod
    def is_platform_link(self, url: str) -> bool:
        """Verifica si un URL es un link de la plataforma."""
        pass
```

#### `PlatformLLM`

```python
class PlatformLLM(ABC):
    @abstractmethod
    def complete(self, prompt: str, system_prompt: str = "") -> str:
        """Envía un prompt al LLM y devuelve la respuesta."""
        pass
```

### 3.4. Cómo se usa

El proceso recibe una instancia de `PlatformAuth`, `PlatformChat`, `PlatformLinks` y `PlatformLLM` al inicializarse. No sabe ni le importa qué plataforma es. Solo usa las interfaces.

```python
# En el Orchestrator:
orch = Orchestrator(
    chat_id=chat_id,
    auth=ZaiAuth(jwt=jwt),        # o OpenAIAuth(api_key=...)
    chat=ZaiChat(token=jwt),     # o OpenAIChat(api_key=...)
    links=ZaiLinks(),             # o OpenAILinks()
    llm=ZaiLLM(),                 # o OpenAILLM(api_key=...)
)
```

### 3.5. Lo que no cambia

- La lógica del proceso (clasificar, empaquetar, indexar, generar archivos).
- Los 4 archivos de recuperación.
- El índice multi-bloque.
- Los 3 sistemas de indexado.
- Los subagentes (sus prompts y parsers).
- La coordinación por archivos (`_pending_tasks.json` + `_responses/`).

### 3.6. Migración gradual

La separación se hace en fases:

1. **Crear las interfaces** (`platform/interfaces.py`) — sin tocar el código existente.
2. **Crear las implementaciones de Z.ai** (`platform/zai/`) — envolviendo el código existente.
3. **Cambiar el proceso para que use las interfaces** — en vez de importar directamente `AuthClient`, usar `PlatformAuth`.
4. **Verificar que todo sigue funcionando** — tests + E2E.

El código existente (`client/auth_client.py`, `client/chat_client.py`, etc.) se conserva. Las implementaciones de Z.ai los envuelven (patrón Adapter).

## 4. Lo que se conserva de versiones anteriores

Todo lo de v4.2 a v4.5: bibliotecario, 2 clases principales, coordinación por archivos, 4 archivos de recuperación, índice multi-bloque, 03 ampliado, 3 sistemas de indexado, lógica de 4 casos, multi-chat, subagentes cableados.

## 5. Lo que se añade en v5.0

- **Proxy de subagentes**: servicio que lanza subagentes directamente al LLM sin pasar por el agente.
- **Separación de plataforma**: 4 interfaces abstractas + implementación de Z.ai.
- **Carpeta `platform/`**: nueva estructura para las interfaces y implementaciones.

## 6. Lo que se desmonta

- Nada. El proxy es opt-in. La separación es por adapter (el código existente se envuelve, no se elimina).

## 7. Reglas de implementación

- **Cambios quirúrgicos.**
- **Scripts atómicos y standalone con auto-tests.**
- **OOP:** interfaces abstractas + implementaciones concretas.
- **No hardcoding.**
- **Tests individuales + E2E.**
- **Lo que funciona se conserva.**

## 8. Compatibilidad con v4.5

- Todos los archivos existentes se conservan.
- Las funciones públicas mantienen su signature.
- Si el proxy no está corriendo, el proceso funciona como hoy.
- Si las interfaces no se pasan, el proceso usa las implementaciones de Z.ai por defecto.

## 9. Validación

- **Proxy**: auto-test que publica una tarea, el proxy la lee, llama al LLM, escribe la respuesta, y `collect_responses()` la integra.
- **Interfaces**: auto-test que verifica que las implementaciones de Z.ai cumplen las interfaces.
- **Latencia**: medir tiempo de respuesta del proxy vs. Task tool.
- **Test E2E**: flujo completo con proxy (pipeline.run → proxy lanza subagentes → collect_responses → archivos actualizados).

---

**Fin de la spec v5.0.**
