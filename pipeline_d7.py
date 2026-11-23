"""contexto_zai/pipeline_d7.py -- Bucle D7 de completitud (v7.0 modularizado).

Contiene la clase ``CicloD7`` con los métodos estáticos migrados desde
``EnriquecimientoOrquestador`` que implementan el bucle D7 (P17):

- ``_bucle_d7_completitud`` (v6.14 F3 → v6.17 F3 criterio 2) — bucle D7
  SEPARADO de la cascada. Lee ``pending_tasks``, reintenta con feedback
  hasta ``MAX_ITER_D7=5``. Si no completa tras 5 intentos, la tarea se
  MANTIENE en ``pending_task`` (no se elimina, no se descarta — queda
  para auditoría y para que el agente CZAI la procese manualmente).
- ``_construir_pending_task_d7_corregido`` (v6.14 F3) — construye una
  SubagentTask con feedback explícito sobre qué falló.
- ``_ejecutar_pending_tasks_obligatorias`` (v6.3 F1 → v6.14 F3) —
  DEPRECATED wrapper que delega a ``_bucle_d7_completitud``.
- ``_bucle_d7`` (v6.17 F12 criterio 12) — bucle D7 encapsulado que
  recibe ``pending_tasks`` y devuelve las que siguen incompletas.

No cambia el grafo de flujo interno: solo mueve código.
"""

from __future__ import annotations

import logging
import json
import time
from pathlib import Path
from typing import Optional

from pipeline_auditoria import AuditorWorkspace

logger = logging.getLogger(__name__)


class CicloD7:
    """v6.17 F12: Bucle D7 de completitud (refactor OOP v6.11 F5).

    Agrupa como ``@staticmethod`` los métodos relacionados con el bucle
    D7 (reintento con feedback). Antes vivían en
    ``EnriquecimientoOrquestador`` (v6.x). v7.0 los mueve aquí para
    separar responsabilidades.

    La clase es stateless — todos sus métodos son ``@staticmethod``.
    """

    @staticmethod
    def _bucle_d7_completitud(
        result: "OrchestratorResult",
        workspace_dir: Path | str,
    ) -> "OrchestratorResult":
        """v6.14 F3 → v6.17 F3 (criterio 2): Bucle D7 SEPARADO de la cascada.

        El bucle D7 opera sobre ``pending_tasks``, NO sobre niveles de la
        cascada. Cuando la cascada (los 3 niveles: Worker Bun → proxy Z.ai
        → subagentes/Nivel 3) no completa un bloque, el bloque va a
        ``pending_task`` (publicada por ``CascadaAccesoLLM`` en
        ``_pending_tasks.json``).

        El bucle D7 lee las ``pending_tasks`` y reintenta con feedback
        hasta ``MAX_ITER_D7=5``. Si el D7 no completa tras 5 intentos,
        la tarea se MANTIENE en ``pending_task`` (no se elimina, no se
        descarta — queda para auditoría P17 y para que el agente CZAI la
        procese manualmente si decide intervenir).

        v6.17 F3 (criterio 2): el bucle D7 NO baja niveles. No
        interactúa con la cascada. La cascada decide el nivel (1/2/3),
        el D7 decide el reintento. Son mecanismos distintos.

        El proceso no puede invocar el Task tool directamente — solo
        publica las pending_tasks corregidas en ``_pending_tasks.json``
        para que el agente CZAI las ejecute. El agente CZAI, tras
        ejecutar los subagentes y llamar ``collect_responses()``, puede
        volver a invocar el pipeline; P17 detecta si quedan incompletos
        y vuelve a iterar. Las iteraciones se cuentan en
        ``_d7_iter_count.json``.

        Si ``MAX_ITER_D7`` (5) se agota → genera informe de escalado al
        Director con las 4 preguntas por iteración (qué falló → qué se
        diagnosticó → cómo se corrigió → qué se implementó) en
        ``/home/z/my-project/download/informe_escalado_d7_<timestamp>.md``.
        Las tareas SIGUEN en ``pending_tasks`` tras el informe (F3:
        no se eliminan, no se descartan).

        Args:
            result: OrchestratorResult devuelto por P14 (con pending_tasks).
            workspace_dir: Directorio del workspace.

        Returns:
            El mismo OrchestratorResult con pending_tasks actualizadas:
            - Si no hay incompletos: pending_tasks = [] (verde).
            - Si hay incompletos: pending_tasks = lista de SubagentTask
              con prompts corregidos para que el agente CZAI las ejecute.
        """
        import json as _json
        import time as _time
        from config import MAX_ITER_D7 as _MAX_ITER_D7
        from models import ThematicBlock as _TB
        # Lazy imports para evitar dependencia circular.
        from pipeline_cascada import _persistir_pending_task_en_disco
        from pipeline_w3 import CicloW3
        # ``_construir_pending_task_para_bloque`` sigue en pipeline.py
        # como utility (no es parte de ningún subproceso). Lazy import.
        from pipeline import _construir_pending_task_para_bloque

        ws_path = Path(workspace_dir)
        if not ws_path.exists():
            return result

        # 1. Detectar bloques incompletos físicamente (post P14-P16).
        audit = AuditorWorkspace.auditar_bloques(workspace_dir)
        incompletos = audit.get("incompletos", [])

        # 2. Leer contador de iteraciones previas (archivo _d7_iter_count.json).
        iter_path = ws_path / "_d7_iter_count.json"
        iter_count = 0
        iter_history: list = []
        if iter_path.exists():
            try:
                iter_data = _json.loads(iter_path.read_text(encoding="utf-8"))
                iter_count = int(iter_data.get("count", 0))
                iter_history = iter_data.get("history", [])
            except Exception:
                iter_count = 0
                iter_history = []

        if not incompletos:
            # Verde: no hay nada que iterar. Resetear el contador.
            if iter_path.exists():
                try:
                    iter_path.unlink()
                except Exception:
                    pass
            logger.info(
                "v6.14 P17 D7: 0 bloques incompletos. Saco vacío (verde)."
            )
            result.pending_tasks = []
            try:
                AuditorWorkspace.sincronizar_registro(workspace_dir)
            except Exception as e:
                logger.warning("v6.14 P17 D7: sincronizar_registro falló: %s", e)
            return result

        # 3. Incrementar contador (esta invocación es la iteración N+1).
        iter_count += 1
        logger.info(
            "v6.14 P17 D7: iteración %d/%d. %d bloque(s) incompleto(s).",
            iter_count, _MAX_ITER_D7, len(incompletos),
        )

        # 4. Para cada bloque incompleto, construir prompt corregido.
        new_pending_tasks: list = []
        iter_entry = {
            "iter": iter_count,
            "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
            "bloques_incompletos": [
                b.get("block_id", "") if isinstance(b, dict) else str(b)
                for b in incompletos
            ],
            "diagnosticos": [],
        }

        for b in incompletos:
            if isinstance(b, dict):
                block_id = b.get("block_id", "")
                faltantes = b.get("faltantes", [])
            else:
                block_id = str(b)
                faltantes = []
            filename = f"{block_id}.md"
            bloque_path = ws_path / filename

            if not bloque_path.exists():
                logger.warning("v6.14 P17 D7: bloque %s no existe (saltando).", filename)
                continue

            bloque_content = bloque_path.read_text(encoding="utf-8", errors="ignore")
            diagnostico = {
                "block_id": block_id,
                "fallo": "",
                "diagnostico": "",
                "correccion": "",
                "implementacion": "",
            }

            # Caso A: bloque tiene RESUMEN. Validar W3.
            if bloque_content.startswith("RESUMEN:"):
                parts = bloque_content.split("\n\n---\n\n", 1)
                if parts[0].startswith("RESUMEN:"):
                    resumen_actual = parts[0][len("RESUMEN:"):].strip()
                else:
                    resumen_actual = parts[0].strip()
                w3_ok, w3_motivo = CicloW3._validar_resumen_w3(
                    resumen_actual, len(bloque_content)
                )
                if not w3_ok:
                    # RESUMEN existe pero falla W3 → feedback al subagente.
                    diagnostico["fallo"] = f"RESUMEN no cumple W3: {w3_motivo}"
                    diagnostico["diagnostico"] = f"Validación W3 falló: {w3_motivo}"
                    diagnostico["correccion"] = (
                        "Generar nuevo RESUMEN que cumpla 600-900 chars, "
                        "4 oraciones, sin etiquetas prohibidas."
                    )
                    diagnostico["implementacion"] = (
                        "Prompt con feedback explícito publicado en _pending_tasks.json"
                    )
                    task = CicloD7._construir_pending_task_d7_corregido(
                        filename=filename,
                        feedback=(
                            f"El RESUMEN actual NO cumple el formato rígido W3: {w3_motivo}. "
                            "Genera de nuevo el resumen cumpliendo: 600-900 caracteres, "
                            "exactamente 4 oraciones (separadas por punto y seguido), "
                            "SIN etiquetas como 'Tema central:', 'Decisiones:', etc., "
                            "SIN listas con guiones, SIN negritas, texto natural "
                            "en un solo párrafo."
                        ),
                    )
                    if task:
                        new_pending_tasks.append(task)
                    iter_entry["diagnosticos"].append(diagnostico)
                    continue
                else:
                    # RESUMEN OK pero faltan archivos auxiliares.
                    diagnostico["fallo"] = (
                        f"Faltan archivos en _responses/: {faltantes}"
                    )
                    diagnostico["diagnostico"] = (
                        "Bloque tiene RESUMEN válido pero faltan uno o más "
                        "de los 3 archivos auxiliares (_nombre.txt, "
                        "_decisiones.txt, _temas.txt)."
                    )
                    diagnostico["correccion"] = (
                        "Generar los archivos faltantes sin tocar el RESUMEN existente."
                    )
                    diagnostico["implementacion"] = (
                        "Prompt específico para archivos faltantes publicado en _pending_tasks.json"
                    )
                    faltantes_str = (
                        ", ".join(faltantes) if faltantes
                        else "nombre.txt, decisiones.txt, temas.txt"
                    )
                    task = CicloD7._construir_pending_task_d7_corregido(
                        filename=filename,
                        feedback=(
                            f"El bloque ya tiene RESUMEN válido, pero faltan estos "
                            f"archivos en _responses/: {faltantes_str}. Genera SOLO "
                            f"los archivos faltantes usando el contenido del bloque. "
                            f"NO modifiques el RESUMEN existente."
                        ),
                    )
                    if task:
                        new_pending_tasks.append(task)
                    iter_entry["diagnosticos"].append(diagnostico)
                    continue

            # Caso B: bloque NO tiene RESUMEN → usar prompt estándar.
            diagnostico["fallo"] = "Bloque sin RESUMEN (no enriquecido)"
            diagnostico["diagnostico"] = (
                "El bloque no ha sido enriquecido todavía (no tiene RESUMEN al inicio)."
            )
            diagnostico["correccion"] = (
                "Generar RESUMEN + 3 archivos auxiliares desde cero."
            )
            diagnostico["implementacion"] = (
                "Prompt estándar de enriquecimiento publicado en _pending_tasks.json"
            )
            block_obj = _TB(filename=filename)
            task = _construir_pending_task_para_bloque(block_obj, chat_label="v6.14_d7")
            if task:
                new_pending_tasks.append(task)
            iter_entry["diagnosticos"].append(diagnostico)

        iter_history.append(iter_entry)

        # 5. Si MAX_ITER_D7 agotado → generar informe de escalado al Director.
        if iter_count >= _MAX_ITER_D7:
            try:
                ts = _time.strftime("%Y%m%d_%H%M%S", _time.gmtime())
                informe_path = Path("/home/z/my-project/download") / f"informe_escalado_d7_{ts}.md"
                informe_path.parent.mkdir(parents=True, exist_ok=True)
                lines = [
                    "# Informe de Escalado al Director — Bucle D7 agotado",
                    "",
                    f"**Timestamp:** {_time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime())}",
                    f"**Workspace:** `{workspace_dir}`",
                    f"**Iteraciones D7 ejecutadas:** {iter_count} (máximo {_MAX_ITER_D7})",
                    f"**Bloques aún incompletos:** {len(incompletos)}",
                    "",
                    "## Acción requerida",
                    "",
                    "El W3 no pudo completar estos bloques tras agotar sus iteraciones.",
                    "El agente CZAI debe intentar completarlos como última opción.",
                    "Si no puede, debe explicar el porqué de la incompletitud al Director.",
                    "",
                    "## Las 4 preguntas por iteración",
                    "",
                ]
                for h in iter_history:
                    lines.append(
                        f"### Iteración {h.get('iter', '?')} — {h.get('timestamp', '')}"
                    )
                    lines.append("")
                    bloques_inc = h.get("bloques_incompletos", [])
                    lines.append(
                        f"- **Bloques incompletos detectados:** "
                        f"{', '.join(bloques_inc) if bloques_inc else '(ninguno)'}"
                    )
                    lines.append("")
                    for d in h.get("diagnosticos", []):
                        lines.append(f"#### Bloque `{d.get('block_id', '?')}`")
                        lines.append("")
                        lines.append(f"1. **Qué falló:** {d.get('fallo', '?')}")
                        lines.append(f"2. **Qué se diagnosticó:** {d.get('diagnostico', '?')}")
                        lines.append(f"3. **Cómo se corrigió:** {d.get('correccion', '?')}")
                        lines.append(f"4. **Qué se implementó:** {d.get('implementacion', '?')}")
                        lines.append("")
                informe_path.write_text("\n".join(lines), encoding="utf-8")
                logger.warning(
                    "v6.14 P17 D7: MAX_ITER_D7=%d agotado. Informe de escalado "
                    "generado en %s",
                    _MAX_ITER_D7, informe_path,
                )
            except Exception as e:
                logger.error(
                    "v6.14 P17 D7: no se pudo generar informe de escalado: %s", e
                )

        # 6. Persistir contador de iteraciones + historial.
        try:
            iter_path.write_text(
                _json.dumps(
                    {"count": iter_count, "history": iter_history},
                    indent=2, ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(
                "v6.14 P17 D7: no se pudo persistir _d7_iter_count.json: %s", e
            )

        # 7. Publicar pending_tasks corregidas en _pending_tasks.json
        #    (reemplaza el saco viejo por el corregido).
        # v6.17 F11 (criterio 11): usar _persistir_pending_task_en_disco
        # (la misma función que usa _post_bloque y _nivel3_subagentes)
        # para que la persistencia sea consistente. Las pending_tasks
        # pueden caer desde cualquier nivel de la cascada (N1, N2 o N3).
        try:
            ws_path_d7 = Path(workspace_dir)
            pending_path_d7 = ws_path_d7 / "_pending_tasks.json"
            # Limpiar el saco viejo (reemplazar, no append).
            if pending_path_d7.exists():
                pending_path_d7.unlink()
            # Persistir cada nueva pending_task con la función única.
            for task in new_pending_tasks:
                _persistir_pending_task_en_disco(
                    workspace_dir=workspace_dir, task=task
                )
        except Exception as e:
            logger.warning(
                "v6.17 F11: no se pudo persistir pending_tasks del D7: %s", e
            )

        # 8. Actualizar result.pending_tasks.
        result.pending_tasks = new_pending_tasks

        # 9. Sincronizar _processed_blocks.json.
        try:
            AuditorWorkspace.sincronizar_registro(workspace_dir)
        except Exception as e:
            logger.warning(
                "v6.14 P17 D7: sincronizar_registro falló: %s", e
            )

        return result

    @staticmethod
    def _construir_pending_task_d7_corregido(
        filename: str,
        feedback: str,
    ) -> "SubagentTask":
        """v6.14 F3: Construye una SubagentTask con feedback explícito para el bucle D7.

        A diferencia de ``_construir_pending_task_para_bloque``, este prompt
        incluye feedback explícito sobre qué falló en la iteración anterior
        y qué debe corregir el subagente en esta iteración.

        Args:
            filename: Nombre del archivo de bloque (``bloque_NN.md``).
            feedback: Texto explicando qué falló y qué corregir.

        Returns:
            SubagentTask con prompt corregido lista para que el agente
            CZAI la ejecute con el Task tool.
        """
        from models import SubagentTask
        block_id = filename.replace(".md", "")
        prompt = f"""Eres un subagente Actuador del proceso contexto_zai. Estás en el bucle D7 (P17)
de garantía de completitud: revisar la falla respecto al spec, corregirla,
re-entregarla al Actuador y re-valorar contra el baremo W3.

## Bloque a procesar

- Lee el archivo `{filename}` en el workspace.

## Feedback de la iteración anterior

{feedback}

## Tu tarea

1. Lee el bloque completo.
2. Si el bloque NO tiene RESUMEN al inicio: genera un RESUMEN de 600-900
   caracteres, exactamente 4 oraciones (separadas por punto y seguido),
   SIN etiquetas como 'Tema central:', 'Decisiones:', etc., SIN listas
   con guiones, SIN negritas, texto natural en un solo párrafo.
3. Si el bloque YA tiene RESUMEN válido: NO lo modifiques. Solo genera
   los archivos que falten en ``_responses/``.
4. Extrae: nombre legible en snake_case (máximo 5 palabras), decisiones
   con formato 'DECISION: ... | ALCANCE: ...', temas principales en
   snake_case (máximo 5).
5. Escribe los 4 artefactos:
   - RESUMEN al inicio del archivo `{filename}` con el prefijo 'RESUMEN: '
     (separado del contenido existente por \\n\\n---\\n\\n).
   - _responses/{block_id}_nombre.txt
   - _responses/{block_id}_decisiones.txt
   - _responses/{block_id}_temas.txt

Respuesta:"""
        return SubagentTask(
            task_id=f"d7_{block_id}",
            purpose=f"v6.14.d7.completitud.{filename}",
            prompt=prompt,
            context={"filename": filename, "feedback": feedback[:500]},
        )

    @staticmethod
    def _ejecutar_pending_tasks_obligatorias(
        result: "OrchestratorResult",
        workspace_dir: Path | str,
    ) -> "OrchestratorResult":
        """v6.3 F1 → v6.14 F3 (criterio 19): DEPRECATED wrapper.

        Antes: intentaba resolver pending_tasks llamando
        ``collect_responses()`` como "arregla todo" (uso incorrecto del
        integrador). Ahora: delega en ``_bucle_d7_completitud()`` que
        implementa el bucle D7 real de P17 con feedback y MAX_ITER_D7=5.

        Se mantiene como wrapper de compatibilidad para código externo
        que aún lo invoque. No hace nada por su cuenta.
        """
        return CicloD7._bucle_d7_completitud(
            result=result, workspace_dir=workspace_dir,
        )

    @staticmethod
    def _bucle_d7(
        pending_tasks: list,
        workspace_dir: Path | str,
    ) -> list:
        """v6.17 F12 (criterio 12): bucle D7 encapsulado.

        Encapsula el bucle D7 (reintento con feedback) en una función
        que recibe ``pending_tasks`` y devuelve las que siguen
        incompletas tras ``MAX_ITER_D7=5`` intentos.

        Procedimiento (criterio 12):
        1. Recibe ``pending_tasks``.
        2. Para cada una: revisar qué falló (auditando el bloque físico
           con ``_descubrir_bloques_incompletos()`` de F1), construir
           prompt corregido (con feedback explícito), reintentar y
           verificar (4 artefactos).
        3. Si cumple → fuera del saco (no se devuelve).
        4. Si no cumple → próxima iteración (sigue en el saco).
        5. Si ``MAX_ITER_D7=5`` intentos agotados → se mantiene en
           ``pending_task`` (se devuelve al llamador).

        v6.17 F3 (criterio 2): el bucle D7 NO baja niveles. No
        interactúa con la cascada. Recibe pending_tasks (que ya cayeron
        desde la cascada en cualquier nivel) y reintenta con feedback.

        v6.17 F11 (criterio 11): las pending_tasks se persisten en
        ``_pending_tasks.json`` vía ``_persistir_pending_task_en_disco``
        (la misma función que usa ``_post_bloque``).

        Args:
            pending_tasks: Lista de SubagentTask pendientes.
            workspace_dir: Directorio del workspace.

        Returns:
            Lista de SubagentTask que siguen incompletas tras
            ``MAX_ITER_D7=5`` intentos. Si todas se completaron,
            devuelve lista vacía.
        """
        if not pending_tasks:
            return []

        from config import MAX_ITER_D7 as _MAX_ITER_D7
        from models import OrchestratorResult

        ws_path = Path(workspace_dir)
        if not ws_path.exists():
            return list(pending_tasks)

        # Construir un OrchestratorResult dummy con las pending_tasks
        # y delegar al bucle D7 existente (_bucle_d7_completitud). El
        # bucle interno hace la auditoría, construcción de prompts
        # corregidos, y persistencia.
        dummy_result = OrchestratorResult(success=True)
        dummy_result.pending_tasks = list(pending_tasks)
        try:
            resultado = CicloD7._bucle_d7_completitud(
                result=dummy_result,
                workspace_dir=workspace_dir,
            )
            # _bucle_d7_completitud devuelve el OrchestratorResult con
            # pending_tasks actualizadas (las que siguen incompletas).
            return list(getattr(resultado, "pending_tasks", []) or [])
        except Exception as e:
            logger.warning(
                "v6.17 F12: _bucle_d7 falló (%s) — devolviendo pending_tasks originales.",
                e,
            )
            return list(pending_tasks)
