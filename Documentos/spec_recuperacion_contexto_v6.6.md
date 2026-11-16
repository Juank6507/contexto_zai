# contexto_zai/Documentos/spec_recuperacion_contexto_v6.6.md
# Spec v6.6 — Unificación OOP de los caminos de generación de contexto

**Versión:** 6.6
**Fecha:** 2026-10-01
**Estado:** Pendiente de implementación.
**Especifica continuación de:** spec v6.5.

## 1. Propósito

La v6.5 preservó bloques externos y normalizó nombres, pero dejó sin resolver
el problema de fondo: los dos caminos de generación de contexto (recuperar
del chat y ampliar desde fuente externa) van por rutas paralelas que duplican
lógica, divergen en estructura, y producen 9 bugs visibles. Esta spec los
unifica bajo OOP respetando 4 principios del Director.

## 2. Los 4 principios del Director

1. **OOP para lo común.** Los procesos que recorren el mismo camino (recuperar
   del chat, recuperar de otra sesión, ampliar desde fuente externa) deben
   construirse con clases que compartan estructura común. Lo común se hereda,
   lo divergente se especializa.

2. **Estructura uniforme del contexto.** Sea cual sea el origen (chat actual,
   otra sesión, fuente externa), el contexto resultante tiene la misma forma:
   mismos archivos, mismos nombres, mismos headers, misma organización. Un
   bloque se llama `bloque_NN.md` y empieza con `# Bloque tematico:` venga
   de donde venga.

3. **El estado siempre se genera desde el último intercambio — pero solo
   cuando hay pérdida de contexto.** Cuando el agente pierde contexto
   (recuperación del chat o de otra sesión), los 4 archivos de recuperación
   se generan y el estado refleja el último intercambio. Cuando el agente
   está trabajando bien y solo amplía contexto (fuente externa), **no se
   generan los archivos de recuperación** — solo se añaden bloques + índice
   (spec v4.4, línea 36). Esto es así porque la ampliación no es pérdida de
   contexto, sino incorporación de información nueva.

4. **Bloques secuenciales, índices abarcadores.** Los bloques se llenan en
   orden cronológico en el momento en que se procesan (no se agrupan por
   tema). Cuando entra un intercambio de un tema que ya existe en otro
   bloque, **no se regeneran todos los bloques** — se hace reempaquetado
   selectivo (solo temas afectados). El índice debe ser abarcador: cubrir
   cada intercambio procesado sin huecos.

## 3. Los 9 bugs heredados de v6.5

Estos son los bugs conciliados con el Director en la conversación previa:

| # | Bug | Detectado por APA | Confirmado |
|---|---|---|---|
| 1 | Resumen de bloques vacío para externos (`temas=[]` y `estimated_tokens=0`) | Sí | Correcto |
| 2 | Tokens `~?` en tabla de mapeo para bloques externos | Sí | Correcto (glob busca en directorio equivocado) |
| 3 | `00_estado_actual.md` no se genera tras `ampliar_contexto()` | Sí | **No es bug** — la spec v4.4 dice que ampliar NO genera archivos de recuperación |
| 4 | `02_decisiones_clave.md` no se genera tras `ampliar_contexto()` | Sí | **No es bug** — mismo motivo que #3 |
| 5 | `_grafos_cambios.json` referenciado en índice pero no existe | Sí | Correcto (enlace muerto) |
| 6 | Sub-detección de scripts versionados | Sí | Parcial (solo busca sufijos) |
| 7 | Bloques externos sin `RESUMEN:` al inicio | No detectado por APA | Confirmado |
| 8 | Nombres de bloques externos no normalizados a `bloque_NN.md` | No detectado por APA | Confirmado (`_normalizar_bloques_externos()` solo se llama desde `pipeline.run()`) |
| 9 | Header de bloques externos no canónico (`# Bloque externo:` vs `# Bloque tematico:`) | No detectado por APA | Confirmado |
| 10 | Doble prefijo `ampliar_ampliar_` en archivos temporales | Nota menor | Correcto (cosmético) |
| 11 | `IncrementalCycle` no invoca `EstadoGenerator` — el estado queda congelado tras la última recuperación completa | No detectado por APA | Confirmado (este SÍ es bug — el incremental es recuperación por pérdida de contexto) |

**Nota sobre los bugs 3 y 4**: el agente APA los diagnosticó como bugs, pero
la spec v4.4 línea 36 establece explícitamente que `ampliar_contexto()` NO
genera los 4 archivos de recuperación. El agente APA no conocía esa spec.
Por lo tanto, los bugs 3 y 4 se **descartan** del plan v6.6.

## 4. Divergencias contra los principios (corregidas)

Tras contrastar el código con el historial de versiones:

### Principio 1 — OOP para lo común

| # | Divergencia |
|---|---|
| 1.1 | No existe clase base común. `RecoveryCycle` e `IncrementalCycle` son clases separadas sin herencia ni interfaz común. |
| 1.2 | `ampliar_contexto()` es una función suelta de ~270 líneas, no una clase. No comparte interfaz con los ciclos. |
| 1.3 | Los post-procesamientos (`_enriquecer_bloques_post_run`, `_ejecutar_pending_tasks_obligatorias`, `_consolidar_decisiones_llm`, `_normalizar_bloques_externos`) son funciones privadas en `pipeline.py` que solo llama `pipeline.run()`. |
| 1.4 | Hay dos integradores de índice duplicados: `IncrementalCycle._regenerar_indice()` e `IntegradorRespuestas._regenerar_indice_recuperacion()` hacen casi lo mismo. |
| 1.5 | `ProcesadorDocumento` y `RecoveryCycle` son conceptualmente simétricos (toman fuente y producen bloques+archivos) pero no comparten interfaz. |

### Principio 2 — Estructura uniforme del contexto

| # | Divergencia |
|---|---|
| 2.1 | Los bloques externos usan nombres distintos (`bloque_externo_grande_ampliar_*.txt_lote_*.md`) vs `bloque_NN.md`. |
| 2.2 | Los bloques externos usan header distinto (`# Bloque externo:` vs `# Bloque tematico:`). |
| 2.3 | Los bloques externos se guardan en subcarpeta `bloques_externos/` vs raíz del workspace. |
| 2.4 | Los bloques externos no pasan por `BloqueGenerator` (escritos a mano en `IntegradorRespuestas._integrar_documento()`). |
| 2.5 | Los bloques externos no se enriquecen (sin `RESUMEN:` al inicio) porque `ampliar_contexto()` no invoca `_enriquecer_bloques_con_fallback()`. |
| 2.6 | Dos caminos para generar contenido de bloque: `BloqueGenerator` (chat) vs escritura manual (externos). |

### Principio 3 — Estado desde último intercambio (solo en pérdida de contexto)

| # | Divergencia |
|---|---|
| 3.1 | `IncrementalCycle` no invoca `EstadoGenerator` — el estado queda congelado en el último `RecoveryCycle`. **Este SÍ es bug** porque el incremental es recuperación por pérdida de contexto. |
| 3.2 | `ampliar_contexto()` no genera estado — **NO es bug**, está bien según spec v4.4. |

### Principio 4 — Bloques secuenciales, índices abarcadores

| # | Divergencia |
|---|---|
| 4.1 | ~~`BlockPacker` empaqueta por tema, no secuencialmente~~ **Descartado**: el `BlockPacker` SÍ es secuencial (con reempaquetado selectivo en incremental). Confirmado por spec v4.4 línea 242. |
| 4.2 | `_find_tokens_for_tema()` roto: devuelve `~?` o `~0.0K` porque los `ThematicBlock` del índice llegan sin `estimated_tokens` y el fallback busca `bloque_externo_*` en la raíz cuando están en subcarpeta o normalizados a `bloque_NN.md`. |
| 4.3 | El índice tiene secciones que no aplican a fuentes externas ("Scripts versionados" referencia `_grafos_cambios.json` inexistente; "Documentos indexados" es para adjuntos del chat). |
| 4.4 | El índice prioriza metadata sobre bloques físicos, pero los bloques físicos pueden estar desactualizados (modo incremental no los escribe). |

## 5. Soluciones

### F1 — Clase base `ContextoGenerator` (Principio 1)

**Archivos:** `generation/contexto_generator.py` (nuevo), `process/recovery_cycle.py`, `process/incremental_cycle.py`, `pipeline.py`.

**Qué se hace:**

1. Crear `generation/contexto_generator.py` con la clase base abstracta
   `ContextoGenerator` que define el flujo común:

   ```
   class ContextoGenerator(ABC):
       def generar(self) -> Resultado:
           intercambios = self._extraer_intercambios()    # abstracto
           bloques = self._empaquetar(intercambios)        # común
           self._escribir_bloques(bloques)                # común
           self._actualizar_metadata(bloques)              # común
           self._actualizar_indice(bloques)                # común
           self._post_procesar(bloques)                    # común (enriquecer, etc.)
           if self._debe_generar_recuperacion():           # hook
               self._generar_estado(bloques)               # solo recovery
               self._generar_decisiones(bloques)           # solo recovery

       @abstractmethod
       def _extraer_intercambios(self) -> list[Exchange]: ...

       def _debe_generar_recuperacion(self) -> bool:
           return True  # default: sí genera (recovery)
   ```

2. `RecoveryCycle` y `IncrementalCycle` se refactorizan para usar
   `ContextoGenerator` como base. Ambos sobrescriben `_extraer_intercambios()`
   (el recovery extrae todo, el incremental solo los nuevos).

3. `ampliar_contexto()` se refactoriza a una clase `AmpliarGenerator` que
   hereda de `ContextoGenerator` y sobrescribe `_debe_generar_recuperacion()`
   para devolver `False` (no genera estado ni decisiones).

4. Los post-procesamientos (`_enriquecer_bloques_post_run`, etc.) se mueven
   a métodos de `ContextoGenerator` para que ambos caminos los ejecuten.

### F2 — Estructura uniforme de bloques (Principio 2)

**Archivos:** `coordinador/integrador_respuestas.py`, `generation/bloque_generator.py`, `pipeline.py`.

**Qué se hace:**

1. `IntegradorRespuestas._integrar_documento()` deja de escribir bloques a
   mano. Pasa por `BloqueGenerator.generate()` como los del chat.

2. Los bloques externos se nombran `bloque_NN.md` desde el principio (no
   `bloque_externo_grande_ampliar_*.txt_lote_*.md`). El número se asigna
   al momento de escribir, no en un post-procesamiento.

3. Los bloques externos se guardan en la raíz del workspace, no en
   subcarpeta `bloques_externos/`.

4. El header de los bloques externos pasa a ser `# Bloque tematico: <temas>`
   (canónico), generado por `BloqueGenerator`.

5. Los bloques externos pasan por `_enriquecer_bloques_con_fallback()` para
   tener `RESUMEN:` al inicio.

### F3 — Estado correcto en modo incremental (Principio 3, divergencia 3.1)

**Archivos:** `process/incremental_cycle.py`.

**Qué se hace:**

1. `IncrementalCycle.run()` invoca `EstadoGenerator.generate(all_exchanges)`
   tras el reempaquetado, y escribe `00_estado_actual.md` al disco.

2. `IncrementalCycle.run()` invoca `DecisionesGenerator.generate(all_exchanges)`
   y escribe `02_decisiones_clave.md`.

3. `IncrementalCycle.run()` escribe los bloques físicos al disco (hoy los
   genera en memoria y no los persiste).

### F4 — Índice abarcador y correcto (Principio 4)

**Archivos:** `generation/indice_generator.py`, `coordinador/integrador_respuestas.py`, `process/incremental_cycle.py`.

**Qué se hace:**

1. `_find_tokens_for_tema()` se arregla: el fallback busca `bloque_*.md` en
   la raíz del workspace (no `bloque_externo_*` en subcarpeta), y estima
   tokens del tamaño del archivo físico.

2. Los `ThematicBlock` que se pasan al `IndiceGenerator` se construyen con
   `temas` y `external_size_chars` (o equivalente) poblados, no con el hack
   `block._temas = ...` que no funciona.

3. Se elimina la sección "Scripts versionados (v3.3)" que referencia
   `_grafos_cambios.json` (archivo que nunca se crea) — Bug 5.

4. El detector de scripts versionados se amplía para detectar temas cuyos
   bloques contienen código con extensión de archivo, no solo por sufijo
   del nombre — Bug 6.

5. Se elimina la sección "Documentos indexados (v3.5)" para fuentes externas
   (no aplica).

### F5 — Bugs residuales

**Archivos:** `pipeline.py`, `coordinador/integrador_respuestas.py`.

**Qué se hace:**

1. **Bug 1**: Los `ThematicBlock` externos se construyen con `temas` y
   `external_size_chars` poblados (o equivalente) para que `estimated_tokens`
   no sea 0.

2. **Bug 2**: Resuelto por F4.1.

3. **Bug 7**: Resuelto por F2.5 (enriquecimiento de bloques externos).

4. **Bug 8**: Resuelto por F2.2 (nombres canónicos desde el principio).

5. **Bug 9**: Resuelto por F2.4 (header canónico vía `BloqueGenerator`).

6. **Bug 10** (doble prefijo `ampliar_ampliar_`): se elimina el prefijo
   duplicado en `ampliar_contexto()`.

### F6 — Bug 11 (estado congelado en incremental)

**Archivos:** `process/incremental_cycle.py`.

**Qué se hace:**

1. Tras el reempaquetado selectivo, `IncrementalCycle.run()` invoca
   `EstadoGenerator` con los intercambios completos (no solo los nuevos)
   para regenerar `00_estado_actual.md`.

2. Esto es consistente con el Principio 3: cuando hay pérdida de contexto
   (que es lo que dispara el incremental), el estado se genera desde el
   último intercambio.

## 6. Archivos intervenidos

| Archivo | Cambios |
|---|---|
| `generation/contexto_generator.py` | NUEVO: clase base `ContextoGenerator`. |
| `process/recovery_cycle.py` | Refactor: hereda de `ContextoGenerator`. |
| `process/incremental_cycle.py` | Refactor: hereda de `ContextoGenerator` + invoca `EstadoGenerator` + escribe bloques físicos (F3, F6). |
| `pipeline.py` | `ampliar_contexto()` refactoriza a `AmpliarGenerator` (clase, no función suelta) + elimina doble prefijo (F5.6). |
| `coordinador/integrador_respuestas.py` | `_integrar_documento()` usa `BloqueGenerator` + nombra `bloque_NN.md` + guarda en raíz (F2). |
| `generation/bloque_generator.py` | Sin cambios (ya genera formato canónico). |
| `generation/indice_generator.py` | `_find_tokens_for_tema()` arreglado + elimina `_grafos_cambios.json` + detector de scripts ampliado + elimina "Documentos indexados" para externos (F4). |
| `generation/estado_generator.py` | Sin cambios (ya existe y funciona). |
| `generation/decisiones_generator.py` | Sin cambios. |
| `models.py` | Posible: `ThematicBlock.external_size_chars` para bloques sin exchanges (Bug 1 fix). |

## 7. Flujo unificado (diagrama)

```
ContextoGenerator.generar()
│
├─ _extraer_intercambios()        ← abstracto (cada subclase lo implementa)
├─ _empaquetar(intercambios)      ← común (BlockPacker, secuencial + selectivo)
├─ _escribir_bloques(bloques)     ← común (BloqueGenerator + disco)
├─ _actualizar_metadata(bloques)  ← común
├─ _actualizar_indice(bloques)   ← común (IndiceGenerator)
├─ _post_procesar(bloques)       ← común (enriquecer, consolidar decisiones, normalizar)
│
└─ if _debe_generar_recuperacion():
     ├─ _generar_estado(bloques)     ← solo RecoveryCycle / IncrementalCycle
     └─ _generar_decisiones(bloques) ← solo RecoveryCycle / IncrementalCycle

Subclases:
- RecoveryCycleGenerator: _extraer = chat completo, _debe_generar = True
- IncrementalCycleGenerator: _extraer = solo nuevos, _debe_generar = True
- AmpliarGenerator: _extraer = fuente externa, _debe_generar = False
```

**Diferencia clave entre subclases:**
- `RecoveryCycle` e `IncrementalCycle` generan los 4 archivos (pérdida de contexto).
- `AmpliarGenerator` no genera estado ni decisiones (ampliación sin pérdida).

---

**Fin de la spec v6.6.**
