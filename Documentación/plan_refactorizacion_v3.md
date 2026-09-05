# contexto_zai/plan_refactorizacion_v3.md -- Plan v3: versionado de scripts con grafo de cambios reversible.
<!-- Destino en el proyecto: /home/z/my-project/contexto_zai/plan_refactorizacion_v3.md -->

# PLAN DE IMPLEMENTACIÓN v3 — Versionado de scripts con grafo de cambios reversible

**Versión:** 3.0
**Fecha:** 2026-09-04
**Autor:** Agente CZAI
**Estado:** Pendiente de validación por el Director.
**Spec objetivo:** v3.3 (entregada en paralelo).

---

## Principios de implementación

1. **OOP estricto:** Todos los componentes son clases con responsabilidad única, interfaces claras, type hints, docstrings. Sin funciones sueltas en módulos.
2. **Scripts atómicos standalone:** Cada módulo independiente se autocontiene, no depende de otros módulos del proyecto, e incluye su propia validación interna (bloque `if __name__ == "__main__"` con batería de pruebas sobre sus funcionalidades).
3. **Scripts de dependencia con tests:** Los módulos que orquestan varios atómicos se validan mediante tests independientes en la carpeta `tests/` del proyecto, que ejecutan la integración de cada módulo atómico en el flujo completo.
4. **Cambios quirúrgicos:** Sobre el código existente, se reescribe solo lo que cambia. Lo reutilizable se conserva.
5. **Compatibilidad Windows:** Todos los scripts son auto-ejecutables en Windows sin configuración previa (stub de `sys.path` + UTF-8 inline + cabeceras de documentación).

---

## Arquitectura de archivos

### Archivos atómicos nuevos

| Archivo | Responsabilidad |
|---|---|
| `processing/code_detector.py` | Detector de código: identifica scripts y artefactos versionables en el contenido de intercambios. Extrae bloques de código, identifica el nombre del script (por ruta de archivo, comentario `# Destino:`, o bloque de código con nombre). Asigna nombre propio (con apellido/DNI si hay duplicados). |
| `processing/version_graph.py` | Grafo de cambios: calcula diffs entre versiones consecutivas de un script (forward y reverse). Permite retroceder desde la versión actual aplicando cambios inversos. |

### Archivos atómicos a modificar

| Archivo | Cambio |
|---|---|
| `models.py` | Añadir modelos: `Script`, `ScriptVersion`, `ChangeGraph`, `ChangeNode`. |
| `processing/subdivider.py` | Integrar `code_detector`: cuando un intercambio contiene scripts, se subdividen por nombre de script (no por keywords léxicas). Cada subtema = nombre del script. |
| `generation/bloque_generator.py` | Incluir el grafo de cambios en el formato del bloque cuando contenga scripts versionados. |
| `generation/indice_generator.py` | Mostrar scripts versionados en el índice. |
| `generation/recovery_generator.py` | Orquestar la generación del archivo `_grafos_cambios.json`. |
| `process/recovery_cycle.py` | Invocar el detector de código durante la clasificación. |
| `config.py` | Patrones de detección de código (triple backtick, comentarios `# Destino:`, rutas de archivo). |

### Archivos de tests nuevos

| Archivo | Qué valida |
|---|---|
| `tests/test_code_detector.py` | Detección de scripts, extracción de bloques, identificación de duplicados. |
| `tests/test_version_graph.py` | Cálculo de diffs, retroceso a versiones anteriores, casos edge. |

### Archivos de tests a modificar

| Archivo | Cambio |
|---|---|
| `tests/test_classifier_packer_subdivider.py` | Añadir tests de subdivisión por nombre de script. |
| `tests/test_e2e_pipeline.py` | Añadir tests de detección de código y versionado en el flujo E2E. |

---

## Nuevos modelos

```python
class Script(BaseModel):
    """Un script o artefacto versionable identificado en el chat."""
    name: str           # Nombre propio (ej: "server", "router")
    full_path: str       # Ruta completa (DNI/apellido si hay duplicados)
    versions: list[ScriptVersion]

class ScriptVersion(BaseModel):
    """Una versión de un script en un punto del chat."""
    version_id: str     # Identificador único (ej: "v1", "v2")
    timestamp: float    # Cuándo apareció en el chat
    exchange_id: int     # En qué intercambio apareció
    content: str        # Contenido del script en esta versión
    parent_version: Optional[str]  # Versión padre en el grafo

class ChangeGraph(BaseModel):
    """Grafo de cambios reversible de un script."""
    script_name: str
    nodes: list[ChangeNode]  # Nodos del grafo (uno por versión)
    current_version: str

class ChangeNode(BaseModel):
    """Nodo del grafo de cambios."""
    version_id: str
    parent_version_id: Optional[str]
    forward_diff: str   # Diff para llegar a esta versión desde el padre
    reverse_diff: str   # Diff para volver al padre desde esta versión
```

---

## Fases de ejecución (milestones)

Cada milestone produce un entregable verificable de forma independiente.

### Milestone V1 — Code Detector
- Crear `processing/code_detector.py` (atómico standalone con auto-tests).
- **Responsabilidad:** identificar scripts y artefactos versionables en el contenido de intercambios.
- **Patrones de detección:**
  1. Bloques de código entre triple backtick con identificador de lenguaje.
  2. Comentarios `# Destino: ruta/al/archivo.py` en la primera línea.
  3. Rutas de archivo mencionadas en el texto.
  4. Bloques de código sin lenguaje explícito que contienen patrones de código (imports, def, class, function).
- **Nombres propios:** el nombre del script se extrae del nombre del archivo (sin extensión). Si hay duplicados, se distingue por ruta completa (apellido/DNI).
- **Tests auto:** detección de scripts, extracción de bloques, identificación de duplicados, casos edge (sin código, código sin nombre, código con ruta relativa).
- **Tests integración:** `tests/test_code_detector.py`.

### Milestone V2 — Version Graph
- Crear `processing/version_graph.py` (atómico standalone con auto-tests).
- **Responsabilidad:** calcular diffs entre versiones consecutivas de un script (forward y reverse), y permitir retroceder desde la versión actual aplicando cambios inversos.
- **Diff forward:** cambios necesarios para llegar de la versión anterior a la nueva.
- **Diff reverse:** cambios necesarios para volver de la nueva a la anterior.
- **Retroceso:** desde la versión actual, aplicar `reverse_diff` sucesivamente hasta llegar a la versión destino.
- **Casos edge:** sin versiones, una sola versión, ramificaciones (si el agente probó enfoques diferentes).
- **Tests auto:** cálculo de diffs, retroceso a versiones anteriores, casos edge.
- **Tests integración:** `tests/test_version_graph.py`.

### Milestone V3 — Modelos
- Actualizar `models.py` con `Script`, `ScriptVersion`, `ChangeGraph`, `ChangeNode`.
- Auto-tests de los nuevos modelos.

### Milestone V4 — Integración en Subdivider
- Modificar `processing/subdivider.py` para integrar `code_detector`.
- Cuando un intercambio contiene scripts, se subdividen por nombre de script (no por keywords léxicas).
- Cada subtema = nombre del script (con apellido/DNI si hay duplicados).
- El `_split_exchange_content` usa el detector de código para identificar scripts y crear subtemas con nombres propios.
- **Tests:** subdivisión por nombre de script, unicidad, integridad de versiones.

### Milestone V5 — Integración en Bloque Generator
- Modificar `generation/bloque_generator.py` para incluir el grafo de cambios en el formato del bloque.
- Cuando un bloque contiene scripts versionados, se incluye una sección con el resumen del grafo (versiones, cambios principales).
- **Tests:** formato con grafo de cambios.

### Milestone V6 — Integración en Índice y Recovery Generator
- Modificar `generation/indice_generator.py` para mostrar scripts versionados.
- Modificar `generation/recovery_generator.py` para orquestar la generación del archivo `_grafos_cambios.json`.
- **Tests:** índice con scripts, generación de `_grafos_cambios.json`.

### Milestone V7 — Integración en Recovery Cycle
- Modificar `process/recovery_cycle.py` para invocar el detector de código durante la clasificación.
- El flujo completo: extracción → clasificación → detección de código → subdivisión por script → empaquetado → generación con grafo de cambios.
- **Tests:** flujo completo con detección de código.

### Milestone V8 — Config y patrones
- Actualizar `config.py` con patrones de detección de código.
- **Tests:** patrones cargados correctamente.

### Milestone V9 — Validación E2E
- Ejecutar el proceso completo contra el chat real.
- Verificar que los scripts se identifican, versionan y guardan correctamente.
- Verificar que el grafo de cambios permite retroceder a versiones anteriores.
- **Tests:** `tests/test_e2e_pipeline.py` actualizado con tests de detección de código y versionado.

---

## Orden de ejecución

V1 → V2 → V3 → V4 → V5 → V6 → V7 → V8 → V9

---

## Cobertura de los cambios pendientes de la spec v3.3

| Cambio spec v3.3 | Milestone que lo cubre |
|---|---|
| 1. Crear `processing/code_detector.py` | V1 |
| 2. Crear `processing/version_graph.py` | V2 |
| 3. Actualizar `models.py` | V3 |
| 4. Actualizar `processing/subdivider.py` | V4 |
| 5. Actualizar `generation/bloque_generator.py` | V5 |
| 6. Actualizar `generation/indice_generator.py` | V6 |
| 7. Actualizar `generation/recovery_generator.py` | V6 |
| 8. Actualizar `process/recovery_cycle.py` | V7 |
| 9. Actualizar `config.py` | V8 |

**Cobertura total:** 9/9 cambios cubiertos.

---

## Cómo se valida este plan

Tras tu validación, el agente leerá:

1. `worklog.md` — estado actual y handoff de Sesión 5.
2. `download/spec_recuperacion_contexto_v3.3.md` — spec objetivo.
3. `download/plan_refactorizacion_v3.md` — este plan.

Y comenzará la ejecución por el Milestone V1, avanzando secuencialmente hasta donde la sesión permita, dejando handoff claro en el worklog al cierre.

---

## Pendiente de validación

Espero tu validación para pasar a la fase de EJECUCIÓN del plan v3. Si hay algo que ajustar del plan (orden de milestones, alcance, decisiones de arquitectura), indícamelo y lo corrijo antes de empezar.
