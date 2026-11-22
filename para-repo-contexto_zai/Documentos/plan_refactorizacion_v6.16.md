# contexto_zai/Documentos/plan_refactorizacion_v6.16.md
# Plan v6.16 — Fixes de bugs v6.15 + checkpointing + paralelismo Nivel 2

**Versión:** 6.16
**Fecha:** 2026-11-09
**Estado:** Pendiente de implementación.
**Spec asociada:** spec_recuperacion_contexto_v6.16.md
**Sesión origen:** CZAI 6a00fcb8, elementos E+P del método DCEPI.

---

## Principio: cambios quirúrgicos (NH18), validar antes de entregar (NH19), solo lo pedido (NH23)

Modo de ejecución v1.6 (D6): UN solo Actuador + el agente como Crítico.

---

## Fases (quirúrgicas)

### F1 — Bug 1: test 2 de pipeline.py usa workspace vacío (criterio 34)

- **Archivo:** `pipeline.py` (función `__main__`, test 2, líneas 3487-3504)
- **Cambio quirúrgico:**
  - El test 2 actualmente hace:
    ```python
    result = run(chat_id="invalid-chat", jwt="invalid-jwt", workspace_dir=tmpdir, download_dir=tmpdir+"/download")
    assert not result.success
    ```
  - Cambiar a: el workspace `tmpdir` se pasa vacío (sin bloques físicos). La cascada detecta 0 bloques sin RESUMEN y termina inmediatamente. El test verifica que `run()` devuelve `success=False` en menos de 5 segundos.
  - El JWT inválido hace que la extracción de mensajes falle antes de generar bloques → la cascada no tiene nada que procesar → no se cuelga.
- **Estado:** ❌ Pendiente
- **Dependencias:** ninguna

### F2 — Bug 2+7: checkpointing tras cada bloque (criterios 35, 36)

- **Archivos:** `pipeline.py` (clase `CascadaAccesoLLM`)
- **Cambio quirúrgico:**
  - Añadir método `_escribir_checkpoint(self)` a `CascadaAccesoLLM` que escribe `_cascada_checkpoint.json`:
    ```python
    def _escribir_checkpoint(self):
        checkpoint = {
            "completados": [b.filename for b in self._todos_los_bloques if _bloque_esta_completo(b, self._workspace_dir)],
            "pendientes": [b.filename for b in self._todos_los_bloques if not _bloque_esta_completo(b, self._workspace_dir)],
            "timestamp": time.time(),
        }
        Path(self._workspace_dir, "_cascada_checkpoint.json").write_text(json.dumps(checkpoint, indent=2))
    ```
  - Llamar `self._escribir_checkpoint()` al final de `procesar_tarea()` (tras procesar cada bloque).
  - Al inicio de `_enriquecer_bloques_con_fallback()`, leer el checkpoint y filtrar los bloques ya completos:
    ```python
    checkpoint_path = Path(workspace_dir, "_cascada_checkpoint.json")
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text())
        completados = set(checkpoint.get("completados", []))
        bloques_sin_resumen = [b for b in bloques_sin_resumen if b.filename not in completados]
    ```
- **Estado:** ❌ Pendiente
- **Dependencias:** ninguna

### F3 — Bug 3: pending_tasks persistente tras cada Nivel 3 (criterio 37)

- **Archivos:** `pipeline.py` (clase `CascadaAccesoLLM`)
- **Cambio quirúrgico:**
  - En `_nivel3_subagentes()`, tras publicar una pending_task en `self._pending_tasks`, escribirla inmediatamente en `_pending_tasks.json` (append):
    ```python
    def _persistir_pending_task(self, task):
        path = Path(self._workspace_dir, "_pending_tasks.json")
        data = {"tasks": []}
        if path.exists():
            data = json.loads(path.read_text())
        data["tasks"].append(task)
        data["total"] = len(data["tasks"])
        path.write_text(json.dumps(data, indent=2, default=str))
    ```
  - Llamar `self._persistir_pending_task(task)` tras cada bloque que cae a Nivel 3.
- **Estado:** ❌ Pendiente
- **Dependencias:** F2

### F4 — Bug 4a: generar _pending_blocks.json en _integrar_documento (criterio 38)

- **Archivos:** `coordinador/integrador_respuestas.py` (función `_integrar_documento`)
- **Cambio quirúrgico:**
  - Tras escribir cada bloque externo a disco, generar o actualizar `_pending_blocks.json`:
    ```python
    def _actualizar_pending_blocks(self, ws, bloque_filename):
        path = ws / "_pending_blocks.json"
        data = {"blocks": []}
        if path.exists():
            data = json.loads(path.read_text())
        # Añadir el bloque si no existe ya
        block_id = bloque_filename.replace(".md", "")
        if not any(b.get("block_id") == block_id for b in data["blocks"]):
            data["blocks"].append({
                "block_id": block_id,
                "filename": bloque_filename,
                "path": str(ws / bloque_filename),
            })
        path.write_text(json.dumps(data, indent=2))
    ```
  - Llamar `self._actualizar_pending_blocks(ws, bloque_filename)` tras escribir el bloque.
- **Estado:** ❌ Pendiente
- **Dependencias:** ninguna

### F5 — Bug 4b: _nivel1_worker_bun usa constantes nuevas (criterio 39)

- **Archivos:** `pipeline.py` (clase `CascadaAccesoLLM`, método `_nivel1_worker_bun`)
- **Cambio quirúrgico:**
  - En `_nivel1_worker_bun()`, reemplazar la llamada a `EnriquecimientoOrquestador._arrancar_worker_y_esperar()` (que usa `ProgressMonitor.esperar_y_verificar()` con 20s+40s) por:
    1. Arrancar el Worker Bun (igual que antes).
    2. Usar `self._esperar_y_verificar_progreso()` (5s×3=15s) para monitorear.
    3. Si hay progreso → seguir esperando.
    4. Si 3 intervalos sin progreso → return False (caída).
- **Estado:** ❌ Pendiente
- **Dependencias:** ninguna

### F6 — Bug 5: paralelismo en Nivel 2 con ThreadPoolExecutor (criterio 40)

- **Archivos:** `pipeline.py` (clase `CascadaAccesoLLM`, método `_nivel2_proxy_zai`)
- **Cambio quirúrgico:**
  - Modificar `_nivel2_proxy_zai()` para aceptar un lote de bloques (no uno solo).
  - Usar `ThreadPoolExecutor(max_workers=5)` para procesar 5 bloques en paralelo:
    ```python
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def _nivel2_proxy_zai(self, tareas) -> bool:
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(self._procesar_bloque_nivel2, b): b for b in tareas}
            for future in as_completed(futures):
                bloque = futures[future]
                ok = future.result()
                if ok:
                    # bloque completado
                    self._escribir_checkpoint()
                else:
                    # bloque falló → Nivel 3
                    self._nivel3_subagentes([bloque])
    ```
  - `self._procesar_bloque_nivel2(bloque)` hace: llamar `_enriquecer_con_proxy_zai()` (1 intento). Si 429 → `_esperar_y_verificar_progreso()`. Si hay progreso → reintenta. Si no → return False.
- **Estado:** ❌ Pendiente
- **Dependencias:** F2, F3, F5

### F7 — Bug 6: hash de caché incluye versión del pipeline (criterio 40)

- **Archivos:** `pipeline.py` (función `_enriquecer_con_proxy_zai`)
- **Cambio quirúrgico:**
  - En el cálculo del hash de caché, añadir la versión del pipeline:
    ```python
    from contexto_zai.config import PIPELINE_VERSION  # nueva constante
    prompt_hash = _hashlib.sha256((prompt + PIPELINE_VERSION).encode("utf-8")).hexdigest()
    ```
  - Añadir `PIPELINE_VERSION = "6.16"` en `config.py`.
- **Estado:** ❌ Pendiente
- **Dependencias:** ninguna

### F8 — Encapsular tareas post-bloque en función (propuesta del Director)

- **Archivos:** `pipeline.py`
- **Cambio quirúrgico:**
  - Crear función `_post_bloque(workspace_dir, bloque, resultado, cascada)` que ejecuta la secuencia de pasos que siempre son los mismos tras procesar un bloque:
    1. Escribir checkpoint (`_cascada_checkpoint.json`).
    2. Si el bloque cayó a Nivel 3 → persistir pending_task en `_pending_tasks.json`.
    3. Actualizar `_processed_blocks.json` (marcar completed o pending).
    4. Actualizar `_pending_blocks.json` (quitar el bloque de pendientes si se completó).
  - Llamar `_post_bloque()` al final de `procesar_tarea()`.
  - **Criterio del Actuador: función, no clase.** Es stateless — toma el estado actual y lo persiste. No necesita preservar nada entre llamadas. Vive como método estático de `EnriquecimientoOrquestador` o como función del módulo.
- **Estado:** ❌ Pendiente
- **Dependencias:** F2, F3, F4

### F9 — Reconstruir contexto desde exchanges_czai_consolidados.md

- **Qué se hace:**
  1. Borrar workspace `contexto_recuperacion/` actual.
  2. Invocar al daemon con `ampliar_contexto("file", "exchanges_czai_consolidados.md")`.
  3. El daemon ejecuta el pipeline con las correcciones F1-F8.
  4. F4 hace que `_pending_blocks.json` se genere para bloques externos.
  5. F5 hace que Nivel 1 use 15s (no 60s).
  6. F6 hace que Nivel 2 procese en paralelo (5 bloques a la vez).
  7. F2 hace checkpointing tras cada bloque.
  8. F3 hace pending_tasks persistentes.
  9. F7 invalida la caché vieja.
- **Estado:** ❌ Pendiente
- **Dependencias:** F1-F8

### F10 — Gauntlet de terminación (7 pasos + 40 criterios)

- **Qué se hace:**
  1. Tras F9, ejecutar los 7 pasos del Gauntlet sobre el workspace reconstruido.
  2. Verificar los 40 criterios de aceptación (33 heredados + 7 nuevos).
  3. Si no pasa → bucle D7 (P17) con MAX_ITER=5.
  4. Si pasa → empaquetado (I.3.a) desbloqueado.
- **Estado:** ❌ Pendiente
- **Dependencias:** F9

---

## Orden de ejecución

| Fase | Descripción | Estado | Dependencias |
|---|---|---|---|
| F1 | Bug 1: test 2 workspace vacío | ❌ | ninguna |
| F2 | Bug 2+7: checkpointing | ❌ | ninguna |
| F3 | Bug 3: pending_tasks persistente | ❌ | F2 |
| F4 | Bug 4a: _pending_blocks.json en _integrar_documento | ❌ | ninguna |
| F5 | Bug 4b: constantes nuevas en Nivel 1 | ❌ | ninguna |
| F6 | Bug 5: paralelismo Nivel 2 | ❌ | F2, F3, F5 |
| F7 | Bug 6: hash caché con versión | ❌ | ninguna |
| F8 | Encapsular tareas post-bloque | ❌ | F2, F3, F4 |
| F9 | Reconstruir contexto | ❌ | F1-F8 |
| F10 | Gauntlet de terminación | ❌ | F9 |

**Total:** 10 fases quirúrgicas.

---

## Valoración: clase vs función para tareas post-bloque (propuesta del Director)

**Criterio del Actuador: función.**

| Aspecto | Clase | Función |
|---|---|---|
| ¿Tiene estado que preservar? | No — toma el estado actual y lo persiste | No |
| ¿Se reutiliza con estado? | No | No |
| Complejidad | Mayor (init, atributos, métodos) | Menor (una función, parámetros claros) |
| L018 (encapsulamiento) | "Clase cuando hay estado" | "Función cuando es stateless" |

Las tareas post-bloque son **stateless**: reciben `(workspace_dir, bloque, resultado, cascada)` y persisten el estado en disco. No necesitan recordar nada entre llamadas. Por lo tanto, **función**.

**Implementación:** función `_post_bloque(workspace_dir, bloque, resultado, cascada)` en `pipeline.py`, invocada al final de `CascadaAccesoLLM.procesar_tarea()`.

---

**Fin del plan v6.16.**
