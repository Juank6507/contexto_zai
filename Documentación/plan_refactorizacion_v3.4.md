# contexto_zai/plan_refactorizacion_v3.4.md -- Plan v3.4: links externos, clasificacion por capas, estado sin truncado, exportacion/importacion de contexto.
<!-- Destino en el proyecto: /home/z/my-project/plan_refactorizacion_v3.4.md -->

# PLAN DE IMPLEMENTACIÓN v3.4 — Links externos, clasificación por capas, estado sin truncado, exportación/importación

**Versión:** 3.4
**Fecha:** 2026-09-05
**Autor:** Agente CZAI
**Estado:** Pendiente de validación por el Director.
**Spec objetivo:** v3.4 (entregada en paralelo).

---

## Principios de implementación

1. **OOP estricto:** Clases con responsabilidad única, interfaces claras, type hints, docstrings.
2. **Scripts atómicos standalone:** Autocontenidos con bloque `if __name__ == "__main__"` con auto-tests.
3. **Scripts de dependencia con tests:** Tests de integración en `tests/`.
4. **Cambios quirúrgicos:** Sobre el código existente del repo, solo se modifica lo que cambia.
5. **Compatibilidad Windows:** Auto-ejecutables sin configuración previa.

---

## Archivos nuevos

| Archivo | Responsabilidad |
|---|---|
| `client/web_reader.py` | Lee contenido de una URL y lo convierte en texto plano. Detecta URLs en mensajes del Director. |
| `subagents/discriminator_subagent.py` | Subagente que lee un tema grande y propone subdivisión en temas específicos basándose en el contenido real. |
| `processing/intention_classifier.py` | Capa 2 de clasificación: analiza la intención del usuario para descomponer el tema "general" en temas reales. |
| `context/exporter.py` | Empaqueta todos los archivos del contexto en un `.zip` con instrucciones de recuperación y metadata del paquete. |
| `context/importer.py` | Descomprime un paquete de contexto exportado y lo carga en el workspace del agente. |
| `context/__init__.py` | Paquete de exportación/importación de contexto. |

## Archivos a modificar

| Archivo | Cambio |
|---|---|
| `processing/exchange_builder.py` | Cuando detecta un link en un mensaje del Director, usa `web_reader` para leerlo y crea un intercambio virtual con el contenido. |
| `processing/classifier.py` | Después de la clasificación léxica (Capa 1), si un intercambio va a "general", pasa por `intention_classifier` (Capa 2) para asignarle un tema real. |
| `generation/estado_generator.py` | Reemplazar el truncado actual por truncamiento lógico: resumir la parte excluida y añadirla al final, manteniendo orden cronológico. |
| `config.py` | Añadir patrones de detección de URLs y temas de intención (solicitud_documentacion, aprobacion, rechazo, etc.). |
| `process/recovery_cycle.py` | Invocar el subagente discriminador cuando un tema sigue siendo demasiado grande después de la Capa 2. |
| `pipeline.py` | Añadir funciones `export_context()` y `import_context()`. |
| `worklog_template.md` (repo estrategia) | Documentar exportación/importación de contexto en el Paso 2b. |

---

## Fases de ejecución (milestones)

### Milestone F1 — Web Reader (links externos)
- Crear `client/web_reader.py` (atómico standalone con auto-tests).
- Detecta URLs (`http://`, `https://`) en texto.
- Descarga el contenido de la URL con httpx.
- Convierte HTML a texto plano (elimina scripts, estilos, etiquetas).
- Extrae el título de la página.
- Devuelve `ExternalContent` con url, title, content, source.
- **Tests auto:** detección de URLs, lectura de HTML, limpieza de scripts/estilos, extracción de título, casos edge (URL vacía, URL inválida, sin conexión).

### Milestone F2 — Integración de links en exchange_builder
- Modificar `processing/exchange_builder.py`.
- Cuando construye intercambios, escanea los mensajes del Director buscando URLs.
- Si encuentra un link, usa `web_reader` para leerlo.
- Crea un intercambio virtual con el contenido del link como respuesta del agente.
- El intercambio se clasifica y se mete en un bloque temático como cualquier otro.
- **Tests:** detección de links en mensajes, creación de intercambios virtuales, integración con el pipeline.

### Milestone F3 — Clasificación por intención (Capa 2)
- Crear `processing/intention_classifier.py` (atómico standalone con auto-tests).
- Recibe un intercambio clasificado como "general".
- Analiza la intención del usuario basándose en patrones:
  - `solicitud_documentacion`: "describe", "explica", "paso a paso".
  - `solicitud_implementacion`: "implementa", "ejecuta", "a ejecutar".
  - `aprobacion`: "correcto", "aprobado", "ok".
  - `rechazo`: "no estoy de acuerdo", "incorrecto".
  - `correccion`: "no lo que te pedí", "mejor hacer".
  - `consulta_estado`: "cómo vamos", "estado", "qué falta".
  - `handoff`: "relee el worklog", "perdiste contexto".
  - `priorizacion`: "entrega primero", "necesito que".
- Devuelve el tema real (no "general").
- **Tests auto:** detección de cada intención, casos edge (mensaje neutro, mensaje ambiguo).

### Milestone F4 — Integración de Capa 2 en classifier
- Modificar `processing/classifier.py`.
- Después de la clasificación léxica (Capa 1), si un intercambio se asigna a "general", pasa por `intention_classifier` (Capa 2).
- Si la Capa 2 asigna un tema real, se usa ese.
- Si la Capa 2 no encuentra intención, se mantiene "general".
- **Tests:** clasificación de dos capas en secuencia, temas reales asignados correctamente.

### Milestone F5 — Subagente discriminador (Capa 3)
- Crear `subagents/discriminator_subagent.py` (atómico standalone con auto-tests).
- Se lanza cuando un tema (después de Capa 1 y Capa 2) sigue siendo demasiado grande.
- Lee todos los intercambios del tema.
- Identifica qué se está discutiendo realmente.
- Propone temas específicos para subdividir.
- Devuelve una propuesta de subdivisión (tema → intercambios).
- **Tests auto:** discriminación de temas, propuesta de subdivisión.

### Milestone F6 — Integración de Capa 3 en recovery_cycle
- Modificar `process/recovery_cycle.py`.
- Después de la clasificación (Capa 1 + Capa 2), si un tema sigue superando el límite, lanza el subagente discriminador (Capa 3).
- Aplica la subdivisión propuesta por el subagente.
- Reclasifica los intercambios a los nuevos temas.
- **Tests:** integración de tres capas, reducción del tema "general".

### Milestone F7 — Estado actual con truncamiento lógico
- Modificar `generation/estado_generator.py`.
- Reemplazar el `_truncate` actual (que corta con "(truncado por límite de espacio)") por truncamiento lógico:
  1. Identifica la parte del contenido que no cabe (la más antigua del tema).
  2. Resume esa parte sin perder información clave.
  3. Añade el resumen al final en una sección "Resumen del contexto excluido".
  4. Mantiene el orden cronológico.
- **Tests:** truncamiento lógico, preservación de información, orden cronológico.

### Milestone F8 — Config y patrones
- Modificar `config.py`.
- Añadir patrones de detección de URLs (`URL_PATTERN`).
- Añadir temas de intención (`INTENTION_THEMES` con keywords por intención).
- **Tests:** patrones cargados correctamente.

### Milestone F9 — Validación E2E (fixes 1-3)
- Ejecutar el proceso completo contra el chat real.
- Verificar que los links externos se procesan como intercambios.
- Verificar que el tema "general" se descompone en temas reales.
- Verificar que el estado actual no se trunca a secas (o usa truncamiento lógico).
- **Tests:** `tests/test_e2e_pipeline.py` actualizado.

### Milestone F10 — Exportador de contexto
- Crear `context/exporter.py` (atómico standalone con auto-tests).
- Empaqueta todos los archivos del contexto (`00_estado_actual.md`, `01_indice_recuperacion.md`, `02_decisiones_clave.md`, `bloque_*.md`, `_metadata.json`, `_grafos_cambios.json`) en un `.zip`.
- Genera `_instrucciones_recuperacion.md` con el protocolo de recuperación paso a paso.
- Genera `_paquete.json` con metadata del paquete (chat_id, fecha, totales).
- Guarda el `.zip` en `download/` o en la carpeta indicada.
- **Tests auto:** empaquetado, generación de instrucciones, generación de metadata, casos edge (sin archivos, sin metadata).

### Milestone F11 — Importador de contexto
- Crear `context/importer.py` (atómico standalone con auto-tests).
- Busca archivos `contexto_exportado_*.zip` en `download/` o carpeta indicada.
- Descomprime el paquete en `/home/z/my-project/contexto_recuperacion/`.
- Lee `_instrucciones_recuperacion.md` y devuelve el protocolo de recuperación.
- Verifica que los archivos están completos.
- **Tests auto:** descompresión, verificación de integridad, casos edge (paquete corrupto, sin paquete).

### Milestone F12 — Integración en pipeline y worklog
- Modificar `pipeline.py`: añadir `export_context()` y `import_context()`.
- Modificar `worklog_template.md` (repo estrategia): documentar exportación/importación en el Paso 2b.
- **Tests:** integración de exportación/importación en el flujo E2E.

---

## Orden de ejecución

F1 → F2 → F3 → F4 → F5 → F6 → F7 → F8 → F9 → F10 → F11 → F12

---

## Cobertura de los cambios de la spec v3.4

| Cambio spec v3.4 | Milestone |
|---|---|
| 1. Crear `client/web_reader.py` | F1 |
| 2. Modificar `processing/exchange_builder.py` | F2 |
| 3. Crear `processing/intention_classifier.py` | F3 |
| 4. Modificar `processing/classifier.py` (Capa 2) | F4 |
| 5. Crear `subagents/discriminator_subagent.py` | F5 |
| 6. Modificar `process/recovery_cycle.py` (Capa 3) | F6 |
| 7. Modificar `generation/estado_generator.py` | F7 |
| 8. Modificar `config.py` | F8 |
| 9. Crear `context/exporter.py` | F10 |
| 10. Crear `context/importer.py` | F11 |
| 11. Modificar `pipeline.py` | F12 |
| 12. Modificar `worklog_template.md` | F12 |

**Cobertura total:** 12/12 cambios cubiertos.

---

## Pendiente de validación

Espero tu validación para pasar a la fase de EJECUCIÓN del plan v3.4.
