# Implementación de componentes del sandbox

Este directorio contiene los archivos que viven en el sandbox de Z.ai pero que
forman parte del proyecto contexto_zai. Se incluyen aquí para que el repositorio
del proyecto sea completo y autocontenido.

## Estructura

```
contexto_zai/
├── mini-services/
│   └── worker-cascade/           # Worker Bun persistente (puerto 8090)
│       ├── index.ts               # Coordinador de la cascada Worker 1 → Workers 2-4
│       └── package.json           # Dependencias (Bun)
│
└── sandbox-src/
    └── api/
        └── zai-proxy/             # Proxy APA (rutas del Next.js del sandbox)
            ├── _lib.ts            # Corazón del proxy: lee /etc/.z-ai-config, reenvía a internal-api.z.ai
            └── v1/
                ├── chat/completions/route.ts   # Endpoint principal del LLM
                ├── vision/route.ts             # Análisis de imágenes
                ├── tts/route.ts                # Texto a voz
                ├── asr/route.ts                 # Voz a texto
                ├── images/generations/route.ts # Generación de imágenes
                ├── async-result/route.ts        # Polling de operaciones async
                └── functions/invoke/route.ts    # Tool calling
```

## Cómo se implementan en el sandbox

### 1. Proxy APA (`sandbox-src/api/zai-proxy/`)

El proxy APA vive dentro del Next.js del sandbox como rutas API. Para instalarlo:

1. Copiar `sandbox-src/api/zai-proxy/` a `src/app/api/zai-proxy/` en el sandbox.
2. El proxy lee automáticamente `/etc/.z-ai-config` para obtener las credenciales.
3. Reenvía las peticiones a `internal-api.z.ai/v1/chat/completions` con los headers del sandbox.
4. No necesita un proceso separado — vive dentro del Next.js que ya está corriendo en el puerto 3000.

### 2. Worker Bun persistente (`mini-services/worker-cascade/`)

El Worker Bun es un servicio independiente que coordina la cascada de procesamiento de bloques:

1. Copiar `mini-services/worker-cascade/` al sandbox.
2. Ejecutar: `cd mini-services/worker-cascade && bun run dev`
3. El worker escucha en el puerto 8090 y lee `_pending_blocks.json` del workspace.
4. Para cada bloque ejecuta la cascada: Worker 1 (resumen) → Workers 2-4 (nombre, decisiones, temas) en paralelo.
5. Las respuestas se escriben en `_responses/` del workspace.
6. El agente llama `pipeline.collect_responses()` para integrar las respuestas.

### 3. Relación entre componentes

```
pipeline.run()  →  genera bloques + _pending_blocks.json
                        ↓
Worker Bun      →  lee _pending_blocks.json
                   Worker 1: lee bloque → genera resumen → escribe al inicio del bloque
                   Workers 2-4: leen resumen → extraen nombre, decisiones, temas
                        ↓
collect_responses()  →  lee _responses/ → Integrador aplica a metadata y archivos
```
