# contexto_zai/Documentos/spec_recuperacion_contexto_v6.7.md
# Spec v6.7 — Bloques con contenido literal + clasificación y enriquecimiento correctos

**Versión:** 6.7
**Fecha:** 2026-10-04
**Estado:** Pendiente de implementación.
**Especifica continuación de:** spec v6.6.

## 1. Propósito

La v6.6 unificó los caminos de generación de contexto y resolvió 8 de 9 bugs,
pero dejó sin resolver un defecto de diseño más profundo que viene desde v3.5:
los bloques generados desde fuentes externas contienen solo un índice temático
(1-2 KB) en vez del contenido literal formateado hasta 70K tokens como prevé
el diseño original. Esta spec corrige ese defecto y formaliza 4 principios
conciliados con el Director.

## 2. Los 4 principios del Director (conciliados en sesión 21)

### Principio 1 — OOP para lo común
Crear contexto, ampliar contexto y actualizar contexto usan el mismo código vía
OOP. La clase base `ContextoGenerator` (creada en v6.6 F1) define el flujo
común: extraer intercambios → empaquetar en bloques → escribir bloques →
actualizar metadata → actualizar índice → enriquecer (RESUMEN + Workers 2-4).
Las subclases solo especializan la extracción.

### Principio 2 — Estructura uniforme del contexto
Un bloque es un bloque, sin importar el origen (chat, otra sesión, fuente
externa). Mismo nombre (`bloque_NN.md`), mismo header (`# Bloque tematico:`),
misma estructura interna (intercambios con fecha y contenido literal), mismo
enriquecimiento (RESUMEN al inicio + Workers 2-4 en `_responses/`).

### Principio 3 — Los 4 archivos dependen de la cronología, no del origen
Los archivos `00_estado_actual.md`, `01_indice_recuperacion.md`,
`02_decisiones_clave.md` y `03_objetivo_proyecto.md` se generan cuando la
información nueva permite identificar un "último intercambio" cronológico que
sea el más reciente del contexto. No depende del origen (chat o externo),
depende de si la información es cronológica y posterior al último timestamp
conocido.

| Caso | Origen | Cronológico | Más reciente | ¿Genera 4 archivos? |
|---|---|---|---|---|
| 1 | Chat (incremental) | Sí | Sí | SÍ |
| 2 | Chat (recuperación completa) | Sí | Sí | SÍ |
| 3 | Externo con timestamps, posterior | Sí | Sí | SÍ |
| 4 | Externo con timestamps, anterior | Sí | No | NO |
| 5 | Externo sin timestamps | No | No determinable | NO |

### Principio 4 — Bloques secuenciales hasta 70K, índices abarcadores
Los bloques se llenan hasta 70K tokens en orden cronológico. El `BlockPacker`
ya hace reempaquetado selectivo correctamente (no se toca). El índice debe
cubre cada intercambio procesado sin huecos.

## 3. El defecto de diseño que viene desde v3.5

### Lo que dice el diseño original (v3.2 + v6.0 cascada)

El bloque se llena hasta 70K tokens con contenido **LITERAL** formateado en
estructura legible. Después Worker 1 lee el bloque completo y genera un
RESUMEN de 600-900 caracteres que se escribe al inicio del bloque como
prefijo `RESUMEN:`. Workers 2-4 leen solo el RESUMEN y extraen nombre
legible, decisiones y temas.

### Lo que hace el código actual

El `DocumentoIndexerSubagent` (desde v3.5) y el `ProcesadorDocumento` (desde
v4.2) le piden al subagente que genere un **índice temático** (TEMA /
DESCRIPCION / SECCIONES / RESUMEN breve), no que extraiga el contenido
literal. El integrador escribe ese índice como si fuera el bloque.

**Consecuencia visible:** los bloques del APA miden 1-2 KB (índice) en vez
de 70K (contenido literal). El contenido completo del documento externo se
pierde — solo queda el índice.

### Causa raíz en el prompt del subagente

El prompt actual (`ProcesadorDocumento._build_documento_prompt` y
`_build_lote_prompt`) le pide al subagente:
> "Identifica los temas principales... Para cada tema, indica nombre,
> descripción, secciones... Genera un resumen breve (máximo 500 caracteres)."

El prompt correcto debería pedirle:
> "Lee las líneas X a Y del documento. Extrae el contenido literal y
> formatealo en estructura markdown legible. No resumas. No generes índice."

## 4. Estructura canónica del bloque (Principio 2)

Todos los bloques, sin importar el origen, tienen esta estructura:

```markdown
RESUMEN: <resumen de 600-900 chars generado por Worker 1, 4 oraciones: tema
central, decisiones, temas específicos, tipo de actividad>

# Bloque tematico: <tema1>, <tema2>, <tema3>

**Periodo:** YYYY-MM-DD → YYYY-MM-DD
**Intercambios:** N (M del Director, K del agente)
**Temas en este archivo:** 3 (<tema1>, <tema2>, <tema3>)
**Tamano estimado:** ~XK tokens

---

## Exchange 1 — [YYYY-MM-DD HH:MM]

### Director:
{contenido del mensaje del Director, literal, sin editar}

### Agente:
{respuesta visible del agente, sin reasoning, código conservado íntegro}

---

## Exchange 2 — [YYYY-MM-DD HH:MM]

### Director:
...
```

Para fuentes externas sin timestamps, los "intercambios" son secciones del
documento formateadas con el mismo patrón:

```markdown
## Sección 1 — <título de la sección del documento>

{contenido literal de esa sección, formateado en markdown legible}

---

## Sección 2 — <título>

...
```

## 5. El flujo correcto (Principio 1 — OOP)

```
ContextoGenerator.ejecutar()  [clase base]
│
├─ 1. _extraer_intercambios()       [abstracto — cada subclase lo implementa]
│    ├─ RecoveryCycleGenerator: extrae todo el chat de Z.ai
│    ├─ IncrementalCycleGenerator: extrae solo los nuevos desde ultimo_timestamp
│    └─ AmpliarGenerator: extrae de fuente externa (URL o archivo)
│
├─ 2. _empaquetar(intercambios)     [común]
│    └─ BlockPacker.pack_from_exchanges() — bloques secuenciales hasta 70K
│
├─ 3. _escribir_bloques(bloques)   [común]
│    └─ BloqueGenerator.generate() — formato canónico # Bloque tematico:
│
├─ 4. _actualizar_metadata(bloques)  [común]
│    └─ MetadataManager — tema_a_archivo, ultimo_timestamp, total_exchanges
│
├─ 5. _actualizar_indice(bloques)   [común]
│    └─ IndiceGenerator.generate() — tabla tema → archivo con tokens reales
│
├─ 6. _post_procesar(bloques)       [común — cascada de workers]
│    ├─ Worker 1 (RESUMEN): lee bloque completo (70K) → genera RESUMEN (600-900 chars)
│    │   → escribe al inicio del bloque con prefijo "RESUMEN: "
│    ├─ Worker 2 (nombre legible): lee RESUMEN → nombre legible → _responses/
│    ├─ Worker 3 (decisiones): lee RESUMEN → decisiones con alcance → _responses/
│    └─ Worker 4 (temas): lee RESUMEN → temas principales → _responses/
│
└─ 7. if _debe_generar_recuperacion():    [hook — Principio 3]
     ├─ _generar_estado(bloques)         — solo si la info es cronológica y posterior
     ├─ _generar_decisiones(bloques)     — solo si la info es cronológica y posterior
     └─ _actualizar_indice_recuperacion()
```

### Hook `_debe_generar_recuperacion()` (Principio 3)

```python
def _debe_generar_recuperacion(self) -> bool:
    """Los 4 archivos se generan si la info nueva es cronológica y la más reciente."""
    if not self._intercambios_tienen_marca_cronologica():
        return False  # caso 5 (fuente externa sin timestamps)
    if not self._intercambios_son_posteriores_a_ultimo_timestamp():
        return False  # caso 4 (info anterior al último conocido)
    return True       # casos 1, 2, 3
```

## 6. Soluciones

### F1 — Subagente extractor de contenido literal (reemplaza al indexador)

**Archivos:** `subagents/documento_indexer_subagent.py` (refactor),
`procesadores/procesador_documento.py` (refactor prompts).

**Qué se hace:**
1. Cambiar el rol del subagente: de "indexador que genera TEMA/DESCRIPCION/
   RESUMEN" a "extractor que devuelve contenido literal formateado".
2. El prompt del subagente (`_build_documento_prompt` y `_build_lote_prompt`)
   pasa a pedir: "Lee las líneas X a Y del documento. Extrae el contenido
   literal y formatealo en estructura markdown legible (secciones con título,
   contenido íntegro). No resumas. No generes índice."
3. El subagente devuelve el contenido formateado, no un índice temático.
4. El `ProcesadorDocumento` cambia el tamaño de lote: de ~5K tokens (para
   generar índice) a ~70K tokens (para llenar el bloque completo).

### F2 — Integrador escribe bloque con contenido literal hasta 70K

**Archivos:** `coordinador/integrador_respuestas.py`.

**Qué se hace:**
1. `_integrar_documento()` deja de escribir el índice como bloque. Pasa el
   contenido literal extraído por el subagente al `BloqueGenerator` para que
   lo formatee con el header canónico `# Bloque tematico:`.
2. El bloque se llena hasta 70K tokens con el contenido literal, no con 1-2
   KB de índice.
3. La clasificación por temas se hace después (Worker 4), no durante la
   extracción.

### F3 — Hook `_debe_generar_recuperacion()` basado en cronología

**Archivos:** `generation/contexto_generator.py`, `pipeline.py`.

**Qué se hace:**
1. Implementar el hook `_debe_generar_recuperacion()` en `ContextoGenerator`
   con la lógica de los 5 casos del Principio 3.
2. `_intercambios_tienen_marca_cronologica()`: verifica si los intercambios
   nuevos tienen timestamps > 0.
3. `_intercambios_son_posteriores_a_ultimo_timestamp()`: compara el timestamp
   máximo de los nuevos contra `metadata.ultimo_timestamp`.
4. `ampliar_contexto()` pasa a usar `AmpliarGenerator` que hereda de
   `ContextoGenerator` y respeta este hook.
5. Cuando el hook devuelve False, no se generan `00_estado_actual.md` ni
   `02_decisiones_clave.md` — el estado y las decisiones siguen reflejando
   el último intercambio cronológico verificado.

### F4 — Worker 1 (RESUMEN) sobre el contenido literal

**Archivos:** `pipeline.py`, `mini-services/worker-cascade/index.ts`.

**Qué se hace:**
1. Confirmar que Worker 1 (Worker Bun o fallback) lee el bloque físico
   completo (70K con contenido literal) y genera el RESUMEN de 600-900 chars.
2. El RESUMEN se escribe al inicio del bloque con prefijo `RESUMEN: `.
3. El `PROMPT_RESUMEN_RIGIDO` ya existe en `config.py` y funciona — no se
   cambia el prompt, solo se asegura que el bloque tenga contenido literal
   para que el RESUMEN sea significativo.

### F5 — Workers 2-4 sobre el RESUMEN

**Archivos:** `mini-services/worker-cascade/index.ts`, `pipeline.py`.

**Qué se hace:**
1. Workers 2-4 (nombre legible, decisiones, temas) leen solo el RESUMEN
   al inicio del bloque, no el bloque completo.
2. El Integrador aplica sus respuestas en `_responses/` y actualiza
   `02_decisiones_clave.md` e índice.
3. La cascada ya está diseñada así en v6.0 — solo necesita que el bloque
   tenga contenido literal para que el RESUMEN sea rico.

### F6 — EstadoGenerator respeta cronología

**Archivos:** `generation/estado_generator.py`.

**Qué se hace:**
1. Cuando se invoca desde `ContextoGenerator._generar_archivos_recuperacion()`,
   el `EstadoGenerator` usa el último intercambio de la info nueva (no del
   contexto existente).
2. Si la info nueva no es cronológica (caso 5), no se invoca al
   `EstadoGenerator` — el estado existente se preserva.

## 7. Archivos intervenidos

| Archivo | Cambio |
|---|---|
| `subagents/documento_indexer_subagent.py` | F1: rol cambia de indexador a extractor. |
| `procesadores/procesador_documento.py` | F1: prompts piden contenido literal, no índice. Lote de 70K, no 5K. |
| `coordinador/integrador_respuestas.py` | F2: escribe bloque con contenido literal vía BloqueGenerator. |
| `generation/contexto_generator.py` | F3: hook `_debe_generar_recuperacion()` basado en cronología. |
| `pipeline.py` | F3: `ampliar_contexto()` pasa a usar `AmpliarGenerator`. |
| `generation/estado_generator.py` | F6: usa último intercambio de la info nueva si es cronológica. |
| `mini-services/worker-cascade/index.ts` | F4+F5: confirmar que W1 lee bloque completo y W2-4 leen RESUMEN. |

## 8. Validación esperada

- Bloques externos miden ~70K (no 1-2 KB).
- Bloques externos empiezan con `RESUMEN: <resumen>` (no con `# Bloque externo:`).
- Bloques externos tienen contenido literal del documento, no índice.
- Worker 1 genera RESUMEN significativo (no "resumen de un índice").
- Workers 2-4 extraen nombre, decisiones, temas del RESUMEN.
- `00_estado_actual.md` se genera solo cuando la info es cronológica y
  posterior al último timestamp conocido.

---

**Fin de la spec v6.7.**
