"""contexto_zai/pipeline_archivos.py -- Subproceso de archivos (v7.0 modularizado).

Contiene la clase ``SubprocesoArchivos`` con los métodos estáticos migrados
desde ``EnriquecimientoOrquestador`` que generan y consolidan los
artefactos del workspace:

- ``_generar_archivos_recuperacion`` (v6.20 F5) — subproceso que hace
  una sola llamada al LLM vía cascada y genera 00, 01, 02, 03. El 03
  solo se genera la primera vez.
- ``_collect_responses_and_finalize`` (v6.19 F6) — endpoint handler:
  integra respuestas de subagentes y finaliza el pipeline (P16-P19).
- ``_consolidar_decisiones_llm`` (v6.4 F1) — consolida las decisiones
  del LLM en ``02_decisiones_clave.md``.
- ``_regenerar_indice_tras_enriquecimiento`` (v6.8.4 re-aplicado v6.10 F4)
  — vuelca los temas significativos del ``_responses/<bloque>_temas.txt``
  al ``tema_a_archivo`` del metadata y regenera ``01_indice_recuperacion.md``.
- ``_normalizar_bloques_externos`` (v6.8.4 re-aplicado v6.10 F4) —
  normaliza los bloques externos del workspace tras el enriquecimiento.

No cambia el grafo de flujo interno: solo mueve código.
"""

from __future__ import annotations

import logging
import json
import re as _re_module
from pathlib import Path
from typing import Optional

# v7.0 F2: import tipado de la ABC (no se instancia directamente).
from contexto_zai.platforms.interfaces import PlatformLLM  # noqa: F401

from contexto_zai.pipeline_auditoria import AuditorWorkspace

logger = logging.getLogger(__name__)


class SubprocesoArchivos:
    """v6.20 F5 + v6.19 F6 + v6.4 F1 + v6.10 F4: Subproceso de archivos.

    Agrupa como ``@staticmethod`` los métodos que generan y consolidan
    los artefactos del workspace (00-03 + bloques enriquecidos). Antes
    vivían en ``EnriquecimientoOrquestador`` (v6.x). v7.0 los mueve
    aquí para separar responsabilidades.

    La clase es stateless — todos sus métodos son ``@staticmethod``.
    """

    @staticmethod
    def _generar_archivos_recuperacion(
        workspace_dir: Path | str,
        chat_id: str = "",
        llm: Optional[PlatformLLM] = None,
    ) -> dict:
        """v7.0 F5 (D1 + A5): Subproceso de archivos de recuperación por pasos.

        v6.20 F5 hacía una sola llamada LLM monolítica que pedía los 4
        archivos en un JSON. La conciliación v7.0 acordó separar por pasos
        usando los generadores existentes (EstadoGenerator, DecisionesGenerator,
        IndiceGenerator) y un reemplazador de placeholders para el 03. Esto
        porque la implementación v6.20 no completaba los archivos de forma
        correcta.

        v7.0 F5 (A5): el subproceso NO bypassa la cascada. Cuando algún
        generador necesita LLM (por ejemplo, DecisionesGenerator en modo
        launcher), delega al W3 que a su vez usa la cascada. El LLM se
        inyecta por parámetro; si es None, se construye ZaiLLM() (default
        Zai).

        Pasos:
        1. ``EstadoGenerator.generate()`` → ``00_estado_actual.md``.
        2. ``DecisionesGenerator.generate()`` → ``02_decisiones_clave.md``.
        3. ``IndiceGenerator.generate()`` → ``01_indice_recuperacion.md``.
        4. ``PlaceholderReplacer.reemplazar()`` → ``03_objetivo_proyecto.md``
           (solo si no existe; si existe, solo reemplaza placeholders).

        Cada paso es independiente y se puede verificar por separado.

        Args:
            workspace_dir: Directorio del workspace.
            chat_id: Identificador del chat (para cabecera del 00).
            llm: Implementación PlatformLLM opcional. Si es None, ZaiLLM().

        Returns:
            Dict con ``success``, ``archivos_generados`` (lista), ``genero_03``.
        """
        ws = Path(workspace_dir)
        if not ws.exists():
            return {"error": f"workspace no existe: {workspace_dir}"}

        # v7.0 F2: resolver el LLM a usar. Default ZaiLLM() si no se inyecta.
        if llm is None:
            try:
                from contexto_zai.platforms.zai.zai_llm import ZaiLLM
                llm = ZaiLLM()
            except Exception as e:
                return {
                    "success": False,
                    "error": f"no se pudo construir ZaiLLM default: {e}",
                    "archivos_generados": [],
                }

        archivos_generados: list[str] = []

        # ============ PASO 1: 00_estado_actual.md ============
        # Genera el archivo usando EstadoGenerator con los intercambios
        # reconstruidos desde los bloques (vía el worklog y el metadata).
        try:
            from contexto_zai.generation.estado_generator import EstadoGenerator
            from contexto_zai.generation.recovery_generator import RecoveryGenerator
            from contexto_zai.models import RecoveryMetadata
            import json as _json

            # Leer metadata del workspace.
            meta_path = ws / "_metadata.json"
            exchanges = []
            tema_actual = ""
            if meta_path.exists():
                try:
                    meta = _json.loads(meta_path.read_text(encoding="utf-8"))
                    tema_a_archivo = meta.get("tema_a_archivo", {})
                    if tema_a_archivo:
                        # El tema activo es el primero del mapping.
                        tema_actual = list(tema_a_archivo.keys())[0]
                except Exception:
                    pass

            # Construir intercambios a partir de los bloques físicos.
            # El EstadoGenerator necesita intercambios reales; los reconstruimos
            # leyendo los bloques (cada bloque contiene intercambios formateados).
            # Si no hay bloques, generamos una lista vacía y el EstadoGenerator
            # producirá el archivo con secciones vacías.
            try:
                from contexto_zai.processing.exchange_builder import ExchangeBuilder
                exchanges = ExchangeBuilder.build_from_workspace(ws)
            except Exception:
                # Si ExchangeBuilder no tiene método build_from_workspace,
                # pasamos lista vacía y el EstadoGenerator usará los bloques
                # directamente vía el workspace_dir.
                exchanges = []

            estado_gen = EstadoGenerator(workspace_dir=ws, chat_id=chat_id)
            estado_content = estado_gen.generate(exchanges, chat_label=chat_id or "contexto_zai")
            estado_path = ws / "00_estado_actual.md"
            estado_path.write_text(estado_content, encoding="utf-8")
            archivos_generados.append("00_estado_actual.md")
            logger.info("v7.0 F5 (D1-A5) paso 1: 00_estado_actual.md generado por EstadoGenerator")
        except Exception as e:
            logger.warning("v7.0 F5 (D1-A5) paso 1 falló: %s", e)

        # ============ PASO 2: 02_decisiones_clave.md ============
        # Consolidar decisiones leyendo los _decisiones.txt y fallback a caches.
        # Esta función ya está refactorizada en SubprocesoArchivos y usa
        # el consolidador con fallback. No necesita LLM directo: las decisiones
        # ya están en los _decisiones.txt o en los caches (escritos por la cascada).
        try:
            n_decisiones = SubprocesoArchivos._consolidar_decisiones_llm(workspace_dir=ws)
            if n_decisiones > 0 or (ws / "02_decisiones_clave.md").exists():
                archivos_generados.append("02_decisiones_clave.md")
                logger.info(
                    "v7.0 F5 (D1-A5) paso 2: 02_decisiones_clave.md generado por "
                    "_consolidar_decisiones_llm (%d decisiones)", n_decisiones,
                )
        except Exception as e:
            logger.warning("v7.0 F5 (D1-A5) paso 2 falló: %s", e)

        # ============ PASO 3: 01_indice_recuperacion.md ============
        # Regenerar el índice con los temas significativos actualizados.
        # Esta función ya está en SubprocesoArchivos y delega al IndiceGenerator.
        try:
            SubprocesoArchivos._regenerar_indice_tras_enriquecimiento(workspace_dir=ws)
            if (ws / "01_indice_recuperacion.md").exists():
                archivos_generados.append("01_indice_recuperacion.md")
                logger.info("v7.0 F5 (D1-A5) paso 3: 01_indice_recuperacion.md regenerado")
        except Exception as e:
            logger.warning("v7.0 F5 (D1-A5) paso 3 falló: %s", e)

        # ============ PASO 4: 03_objetivo_proyecto.md ============
        # Si no existe, crear con plantilla base. Si existe, solo reemplazar
        # placeholders. NO se sobrescribe si ya existe (criterio spec v6.20).
        try:
            objetivo_path = ws / "03_objetivo_proyecto.md"
            genero_03 = not objetivo_path.exists()
            if genero_03:
                # Crear con plantilla base con placeholders.
                plantilla = (
                    "# Objetivo del Proyecto — Contexto Zai\n\n"
                    "## G0.A — Quién eres\n\n"
                    "Sos un agente Z.ai (modelo __MODELO_AGENTE__) que el Director "
                    "**__DIRECTOR__** (``__EMAIL__``) está construyendo como parte de una "
                    "estrategia mayor de trabajo con proyectos informáticos. Tu nombre "
                    "interno en esta fase es **CZAI** (Contexto Zai). Trabajás en un "
                    "sandbox de Z.ai en la ruta ``/home/z/my-project/`` "
                    "(Next.js + Bun + Python venv).\n\n"
                    "## G0.B — Norte del proyecto\n\n"
                    "(A definir por el Director en la primera sesión.)\n\n"
                    "## G0.C — Acta de nacimiento\n\n"
                    "__ACTA_NACIMIENTO__\n"
                )
                objetivo_path.write_text(plantilla, encoding="utf-8")
                archivos_generados.append("03_objetivo_proyecto.md")
                logger.info("v7.0 F5 (D1-A5) paso 4: 03_objetivo_proyecto.md creado con plantilla")
            # Reemplazar placeholders (siempre, tanto si se creó como si ya existía).
            SubprocesoArchivos._reemplazar_placeholders_objetivo(workspace_dir=ws)
        except Exception as e:
            logger.warning("v7.0 F5 (D1-A5) paso 4 falló: %s", e)

        return {
            "success": len(archivos_generados) > 0,
            "archivos_generados": archivos_generados,
            "genero_03": genero_03 if 'genero_03' in dir() else False,
        }

    @staticmethod
    def _collect_responses_and_finalize(
        workspace_dir: Path | str,
    ) -> dict:
        """v6.19 F6 (autonomía del agente CZAI): integra respuestas de subagentes
        y finaliza el pipeline (P16-P19).

        Este método lo invoca el endpoint ``POST /collect-responses`` del daemon
        después de que el agente CZAI haya ejecutado las pending_tasks de Nivel 3
        (vía Task tool) y escrito las respuestas en ``_responses/``.

        Flujo:
        1. ``collect_responses()`` — integra las respuestas de los subagentes
           en los bloques físicos (escribe RESUMEN + nombre + decisiones + temas).
        2. Re-verificar bloques incompletos.
        3. Si aún hay incompletos → publicar nuevas pending_tasks y retornar
           ``needs_agent_action=True`` (el agente debe ejecutar más subagentes).
        4. Si todos completos → P16 (auditoría) + P18 (consolidar decisiones)
           + P19 (regenerar índice) + status=done.

        Args:
            workspace_dir: Directorio del workspace.

        Returns:
            Dict con ``success``, ``needs_agent_action``, ``pending_tasks_count``,
            ``completados``, ``pendientes``, ``error``.
        """
        # Lazy imports para evitar dependencia circular.
        from contexto_zai.pipeline_w3 import (
            CicloW3,
            _descubrir_bloques_incompletos,
            _enriquecer_bloques_con_fallback,
        )
        from contexto_zai.pipeline_cascada import _actualizar_estado_daemon
        # ``ContextoPipeline.collect_responses`` sigue en pipeline.py
        # (API pública). Lazy import para evitar dependencia circular.
        from contexto_zai.pipeline import ContextoPipeline

        ws = Path(workspace_dir)
        if not ws.exists():
            return {"error": f"workspace no existe: {workspace_dir}"}

        # (1) collect_responses: integra respuestas de _responses/ en bloques.
        try:
            ContextoPipeline.collect_responses(
                workspace_dir=ws,
                is_chat_chronological=False,
            )
            logger.info("v6.19 F6: collect_responses() completado tras /collect-responses")
        except Exception as e:
            logger.warning("v6.19 F6: collect_responses falló: %s", e)

        # (2) Re-verificar bloques incompletos.
        try:
            incompletos = _descubrir_bloques_incompletos(ws)
        except Exception as e:
            logger.warning("v6.19 F6: _descubrir_bloques_incompletos falló: %s", e)
            incompletos = []

        total = len(list(ws.glob("bloque_*.md")))
        pendientes = len(incompletos)
        completados = max(0, total - pendientes)

        # (3) Si aún hay incompletos, publicar nuevas pending_tasks y retornar.
        if incompletos:
            # Re-disparar cascada para los que siguen incompletos.
            bloques_para_cascada = [inc["bloque"] for inc in incompletos]
            nuevas_pending = []
            try:
                nuevas_pending = _enriquecer_bloques_con_fallback(
                    blocks=bloques_para_cascada,
                    workspace_dir=ws,
                )
            except Exception as e:
                logger.warning("v6.19 F6: re-cascada falló: %s", e)

            if nuevas_pending:
                # Aún hay pending_tasks de Nivel 3 → seguir esperando al agente.
                import json as _json_f6b
                pending_path = ws / "_pending_tasks.json"
                try:
                    pending_data = {
                        "tasks": [
                            t.model_dump() if hasattr(t, 'model_dump') else t
                            for t in nuevas_pending
                        ]
                    }
                    pending_path.write_text(
                        _json_f6b.dumps(pending_data, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8",
                    )
                except Exception as e:
                    logger.warning("v6.19 F6: escribir _pending_tasks.json falló: %s", e)

                _actualizar_estado_daemon(
                    workspace_dir=ws,
                    status="waiting_for_agent",
                    tarea_actual="Nivel 3 — agente CZAI debe ejecutar pending_tasks (iteración 2)",
                )
                # v7.0 F4: serializar las pending_tasks completas en la respuesta HTTP
                # para que el agente CZAI reciba todo en una sola respuesta y sepa
                # exactamente qué hacer sin tener que leer _pending_tasks.json.
                # Cada tarea incluye task_id, purpose, prompt y context.
                pending_tasks_serializadas = []
                for t in nuevas_pending:
                    if hasattr(t, "model_dump"):
                        pending_tasks_serializadas.append(t.model_dump())
                    elif hasattr(t, "__dict__"):
                        pending_tasks_serializadas.append({
                            "task_id": getattr(t, "task_id", ""),
                            "purpose": getattr(t, "purpose", ""),
                            "prompt": getattr(t, "prompt", ""),
                            "context": getattr(t, "context", None),
                        })
                    else:
                        pending_tasks_serializadas.append(t)
                return {
                    "success": True,
                    "needs_agent_action": True,
                    "pending_tasks_count": len(nuevas_pending),
                    "pending_tasks": pending_tasks_serializadas,
                    "completados": completados,
                    "pendientes": pendientes,
                    "instruction": (
                        "Aún hay bloques incompletos tras collect_responses. "
                        "Ejecutar las nuevas pending_tasks automáticamente (campo "
                        "'pending_tasks' de esta respuesta) y llamar /collect-responses "
                        "nuevamente. NO es necesario leer _pending_tasks.json: todas "
                        "las tareas están en esta respuesta."
                    ),
                }

        # (4) Todos completos → P16 + P18 + P19 + status=done.
        try:
            audit_final = AuditorWorkspace.auditar_completitud(ws)
            logger.info(
                "v6.19 F6 P16: Auditoría final: %d completos, %d incompletos",
                len(audit_final["completos"]),
                len(audit_final["incompletos"]),
            )
        except Exception as e:
            logger.warning("v6.19 F6 P16: auditar_completitud falló: %s", e)

        try:
            SubprocesoArchivos._consolidar_decisiones_llm(workspace_dir=ws)
            logger.info("v6.19 F6 P18: decisiones consolidadas")
        except Exception as e:
            logger.warning("v6.19 F6 P18: _consolidar_decisiones_llm falló: %s", e)

        try:
            SubprocesoArchivos._regenerar_indice_tras_enriquecimiento(workspace_dir=ws)
            logger.info("v6.19 F6 P19: índice regenerado")
        except Exception as e:
            logger.warning("v6.19 F6 P19: _regenerar_indice falló: %s", e)

        # v7.0 F5 (D11): regenerar la sección G0.B "Síntesis del contexto
        # disponible" del 00_estado_actual.md. Antes de v7.0, esta sección
        # se escribía una sola vez en P9 (antes del enriquecimiento) cuando
        # los bloques todavía no tenían RESUMEN, y nunca se revalidaba.
        # Por eso el workspace actual dice "Síntesis no disponible (los
        # bloques del tema 'contexto_compresion' no tienen RESUMEN)" aunque
        # los 22 bloques sí tienen RESUMEN. Esta llamada regenera G0.B
        # leyendo los RESUMENES actuales.
        try:
            SubprocesoArchivos._regenerar_sintesis_contexto(workspace_dir=ws)
            logger.info("v7.0 F5 (D11): síntesis G0.B regenerada")
        except Exception as e:
            logger.warning("v7.0 F5 (D11): _regenerar_sintesis_contexto falló: %s", e)

        # v7.0 F5 (D4): reemplazar placeholders del 03_objetivo_proyecto.md
        # (MODELO_AGENTE, DIRECTOR, EMAIL, ACTA_NACIMIENTO). Antes de v7.0,
        # estos placeholders quedaban literales porque nadie implementó la
        # lógica de reemplazo (aunque el comentario del código decía que el
        # agente que responde debía rellenarlos).
        try:
            SubprocesoArchivos._reemplazar_placeholders_objetivo(workspace_dir=ws)
            logger.info("v7.0 F5 (D4): placeholders del objetivo reemplazados")
        except Exception as e:
            logger.warning("v7.0 F5 (D4): _reemplazar_placeholders_objetivo falló: %s", e)

        # Status final: done.
        _actualizar_estado_daemon(
            workspace_dir=ws,
            status="done",
            tarea_actual="",
        )

        # Limpiar _pending_tasks.json (ya no hay pendientes).
        pending_path = ws / "_pending_tasks.json"
        try:
            pending_path.write_text(
                '{"tasks": []}', encoding="utf-8"
            )
        except Exception:
            pass

        logger.info(
            "v6.19 F6: pipeline finalizado. %d/%d bloques completos. status=done.",
            completados, total,
        )

        return {
            "success": True,
            "needs_agent_action": False,
            "pending_tasks_count": 0,
            "completados": completados,
            "pendientes": 0,
            "status": "done",
        }

    @staticmethod
    def _consolidar_decisiones_llm(workspace_dir: Path | str) -> int:
        """v6.4 F1 → v7.0 F5: Consolida las decisiones del LLM en 02_decisiones_clave.md.

        QUÉ SOLUCIONA: el DecisionExtractor regex se eliminó (v6.4). Las decisiones
        reales las extrae el LLM (Worker Bun o subagentes fallback) y las escribe en
        _responses/bloque_NN_decisiones.txt con formato "DECISION: ... | ALCANCE: ...".
        Esta función lee todos esos archivos y los consolida en 02_decisiones_clave.md.

        v7.0 F5: FALLBACK A CACHES. Si los archivos ``_decisiones.txt`` no existen
        (porque fueron borrados por el limpiador del RecogedorRespuestas en v6.20,
        bug 5 detectado por el Director), esta función lee los caches en
        ``_responses/cache/*.json`` que también tienen el campo ``decisiones``.
        Esto permite recuperar las 65 decisiones que vimos en el workspace actual.

        Args:
            workspace_dir: Directorio del workspace.

        Returns:
            Número de decisiones consolidadas.
        """
        from pathlib import Path as _Path
        import json as _json
        ws = _Path(workspace_dir)
        responses_dir = ws / "_responses"
        if not responses_dir.exists():
            return 0

        # Paso 1: leer todas las decisiones de _responses/bloque_*_decisiones.txt
        all_decisions: list[str] = []
        for p in sorted(responses_dir.glob("bloque_*_decisiones.txt")):
            try:
                content = p.read_text(encoding="utf-8").strip()
                if not content:
                    continue
                for line in content.split("\n"):
                    line = line.strip()
                    if line and (line.startswith("DECISION:") or line.startswith("DECISION :")):
                        all_decisions.append(line)
            except Exception as e:
                logger.warning("v6.4 F1: no se pudo leer %s: %s", p.name, e)

        # v7.0 F5: Paso 2 (fallback) — si no hay decisiones en _decisiones.txt,
        # leer los caches _responses/cache/*.json que tienen campo ``decisiones``.
        if not all_decisions:
            cache_dir = responses_dir / "cache"
            if cache_dir.exists():
                logger.info(
                    "v7.0 F5: no hay _decisiones.txt (probablemente borrados por "
                    "RecogedorRespuestas.limpiar en v6.20). Fallback a caches en %s",
                    cache_dir,
                )
                for cache_file in sorted(cache_dir.glob("*.json")):
                    try:
                        cache_data = _json.loads(cache_file.read_text(encoding="utf-8"))
                        cache_decisiones = cache_data.get("decisiones") or []
                        for dec in cache_decisiones:
                            if isinstance(dec, str) and dec.strip():
                                # Asegurar formato "DECISION: ... | ALCANCE: ..."
                                if not dec.startswith("DECISION:"):
                                    dec = f"DECISION: {dec}"
                                all_decisions.append(dec)
                    except Exception as e:
                        logger.warning(
                            "v7.0 F5: no se pudo leer cache %s: %s",
                            cache_file.name, e,
                        )
                if all_decisions:
                    logger.info(
                        "v7.0 F5: fallback a caches recuperó %d decisiones",
                        len(all_decisions),
                    )

        if not all_decisions:
            logger.info("v6.4 F1: no hay decisiones del LLM para consolidar (ni en _decisiones.txt ni en caches).")
            return 0

        # Generar el contenido de 02_decisiones_clave.md
        lines: list[str] = [
            "# Decisiones Clave",
            "",
            f"**Total de decisiones:** {len(all_decisions)}",
            f"**Fuente:** Extracción LLM (Worker Bun + subagentes fallback + caches v7.0 F5)",
            "",
            "---",
            "",
        ]

        for i, dec in enumerate(all_decisions, start=1):
            # Parsear "DECISION: ... | ALCANCE: ..."
            decision_text = dec
            alcance_text = "A determinar"
            if "|" in dec:
                parts = dec.split("|", 1)
                decision_text = parts[0].strip()
                alcance_part = parts[1].strip()
                if alcance_part.startswith("ALCANCE:"):
                    alcance_text = alcance_part[len("ALCANCE:"):].strip()
                else:
                    alcance_text = alcance_part

            # Limpiar prefijo "DECISION:" si existe
            if decision_text.startswith("DECISION:"):
                decision_text = decision_text[len("DECISION:"):].strip()
            elif decision_text.startswith("DECISION :"):
                decision_text = decision_text[len("DECISION :"):].strip()

            lines.append(f"## D{i:02d} -- {decision_text[:80]}")
            lines.append(f"- **Decisión:** {decision_text}")
            lines.append(f"- **Alcance:** {alcance_text}")
            lines.append("")

        content = "\n".join(lines)

        # Escribir el archivo
        decisiones_path = ws / "02_decisiones_clave.md"
        decisiones_path.write_text(content, encoding="utf-8")
        logger.info("v6.4 F1: %d decisiones del LLM consolidadas en 02_decisiones_clave.md", len(all_decisions))
        return len(all_decisions)

    @staticmethod
    def _regenerar_indice_tras_enriquecimiento(
        workspace_dir: Path | str,
    ) -> int:
        """v6.8.4 re-aplicado (v6.10 F4): Vuelca los temas significativos del
        ``_responses/<bloque>_temas.txt`` al ``tema_a_archivo`` del metadata,
        elimina los temas provisionales ``documento_externo_NN`` y regenera
        ``01_indice_recuperacion.md``.

        Es idempotente: si los ``_responses/<bloque>_temas.txt`` no existen
        todavía, no hace nada y devuelve 0.
        """
        ws = Path(workspace_dir)
        responses_dir = ws / "_responses"
        metadata_path = ws / "_metadata.json"

        if not responses_dir.exists() or not metadata_path.exists():
            return 0

        import json as _json
        try:
            metadata = _json.loads(metadata_path.read_text(encoding="utf-8"))
        except (ValueError, _json.JSONDecodeError):
            metadata = {}

        tema_a_archivo = metadata.setdefault("tema_a_archivo", {})

        # 1. Eliminar temas provisionales "documento_externo_NN" residuales.
        provisionales_eliminados = 0
        for clave in list(tema_a_archivo.keys()):
            if clave.startswith("documento_externo_"):
                del tema_a_archivo[clave]
                provisionales_eliminados += 1
        if provisionales_eliminados:
            logger.info(
                "v6.10 F4: %d tema(s) provisionales eliminados de tema_a_archivo.",
                provisionales_eliminados,
            )

        # 2. Volver a leer los _responses/<bloque>_temas.txt y registrar los temas.
        bloques_con_temas = 0
        for p in sorted(responses_dir.glob("bloque_*_temas.txt")):
            block_id = p.stem
            if block_id.endswith("_temas"):
                block_id = block_id[: -len("_temas")]
            bloque_filename = f"{block_id}.md"

            try:
                content = p.read_text(encoding="utf-8").strip()
            except Exception as e:
                logger.warning("v6.10 F4: no se pudo leer %s: %s", p.name, e)
                continue

            if not content:
                continue

            temas_significativos = [
                t.strip() for t in content.split("\n") if t.strip()
            ]
            if not temas_significativos:
                continue

            for tema in temas_significativos:
                existente = tema_a_archivo.get(tema)
                if isinstance(existente, list):
                    if bloque_filename in existente:
                        continue
                    existente.append(bloque_filename)
                    tema_a_archivo[tema] = existente
                elif isinstance(existente, str):
                    if existente == bloque_filename:
                        tema_a_archivo[tema] = [bloque_filename]
                    else:
                        tema_a_archivo[tema] = [existente, bloque_filename]
                else:
                    tema_a_archivo[tema] = [bloque_filename]

            bloques_con_temas += 1

        # 3. Persistir el metadata actualizado.
        metadata_path.write_text(
            _json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # 4. Regenerar 01_indice_recuperacion.md.
        if bloques_con_temas > 0 or provisionales_eliminados > 0:
            try:
                from contexto_zai.coordinador.integrador_respuestas import IntegradorRespuestas
                IntegradorRespuestas._regenerar_indice_recuperacion(ws, metadata)
                logger.info(
                    "v6.10 F4: índice regenerado (%d bloque(s) con temas, %d provisional(es) eliminado(s)).",
                    bloques_con_temas, provisionales_eliminados,
                )
            except Exception as e:
                logger.warning("v6.10 F4: no se pudo regenerar el índice: %s", e)

        return bloques_con_temas

    @staticmethod
    def _normalizar_bloques_externos(workspace_dir: Path | str) -> int:
        """v6.8.4 re-aplicado (v6.10 F4): Normaliza los bloques externos del
        workspace tras el enriquecimiento. Punto de consistencia defensivo que
        re-intenta el vuelco de temas por si algún ``_temas.txt`` llegó tarde.
        """
        ws = Path(workspace_dir)
        metadata_path = ws / "_metadata.json"
        if not metadata_path.exists():
            return 0

        import json as _json
        try:
            metadata = _json.loads(metadata_path.read_text(encoding="utf-8"))
        except (ValueError, _json.JSONDecodeError):
            return 0

        archivo_a_source = metadata.get("archivo_a_source", {})
        tema_a_archivo = metadata.setdefault("tema_a_archivo", {})

        bloques_externos = []
        for bloque_filename, source_info in archivo_a_source.items():
            if not isinstance(source_info, dict):
                continue
            if source_info.get("source_type") in ("file", "url"):
                bloques_externos.append(bloque_filename)

        if not bloques_externos:
            return 0

        responses_dir = ws / "_responses"
        normalizados = 0
        for bloque_filename in bloques_externos:
            block_id = bloque_filename.replace(".md", "")
            temas_path = responses_dir / f"{block_id}_temas.txt"
            if not temas_path.exists():
                continue

            try:
                content = temas_path.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            temas = [t.strip() for t in content.split("\n") if t.strip()]
            if not temas:
                continue

            ya_cubierto = False
            for tema in temas:
                existente = tema_a_archivo.get(tema)
                if isinstance(existente, list) and bloque_filename in existente:
                    ya_cubierto = True
                    break
                if isinstance(existente, str) and existente == bloque_filename:
                    ya_cubierto = True
                    break
            if ya_cubierto:
                continue

            normalizados += 1

        if normalizados > 0:
            SubprocesoArchivos._regenerar_indice_tras_enriquecimiento(workspace_dir)
            logger.info("v6.10 F4: %d bloque(s) externo(s) normalizado(s).", normalizados)

        return normalizados

    @staticmethod
    def _regenerar_sintesis_contexto(workspace_dir: Path | str) -> bool:
        """v7.0 F5 (D11): regenera la sección G0.B "Síntesis del contexto
        disponible" del ``00_estado_actual.md`` leyendo los RESUMENES actuales
        de los bloques.

        Antes de v7.0, la sección G0.B se escribía una sola vez en P9 (antes
        del enriquecimiento) cuando los bloques todavía no tenían RESUMEN, y
        nunca se revalidaba tras el enriquecimiento (P14). Por eso el workspace
        actual dice "Síntesis no disponible (los bloques del tema
        'contexto_compresion' no tienen RESUMEN)" aunque los 22 bloques sí
        tienen RESUMEN.

        Esta función lee los RESUMENES de los bloques del tema activo (sacado
        del ``_metadata.json``) y los concatena en la sección G0.B, igual que
        hace ``EstadoGenerator._build_g0_b`` pero invocable después del
        enriquecimiento.

        Args:
            workspace_dir: Directorio del workspace.

        Returns:
            True si se actualizó la sección G0.B, False si no.
        """
        import json as _json
        import re as _re
        ws = Path(workspace_dir)
        estado_path = ws / "00_estado_actual.md"
        if not estado_path.exists():
            logger.warning("v7.0 F5 (D11): 00_estado_actual.md no existe en %s", ws)
            return False

        # Leer el tema activo del metadata.
        meta_path = ws / "_metadata.json"
        if not meta_path.exists():
            return False
        try:
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        tema_a_archivo = meta.get("tema_a_archivo", {})
        if not tema_a_archivo:
            return False

        # El tema activo es el primero del tema_a_archivo (igual que en
        # EstadoGenerator._build_g0_b cuando no se pasa tema_actual).
        # Pero para ser más robusto, leemos el tema activo de la cabecera
        # del 00_estado_actual.md (línea "**Tema activo:** **xxx**").
        content = estado_path.read_text(encoding="utf-8")
        tema_actual = ""
        match_tema = _re_module.search(r"\*\*Tema activo:\*\*\s*\*\*([^*]+)\*\*", content)
        if match_tema:
            tema_actual = match_tema.group(1).strip()
        if not tema_actual:
            # Fallback al primer tema del metadata.
            tema_actual = list(tema_a_archivo.keys())[0] if tema_a_archivo else ""

        if not tema_actual:
            logger.warning("v7.0 F5 (D11): no se pudo determinar el tema activo")
            return False

        # Buscar los bloques del tema activo.
        archivos = tema_a_archivo.get(tema_actual, [])
        if isinstance(archivos, str):
            archivos = [archivos]
        if not archivos:
            return False

        # Leer el RESUMEN de cada bloque.
        resumenes: list[str] = []
        for bloque_name in archivos:
            bloque_path = ws / bloque_name
            if not bloque_path.exists():
                continue
            try:
                bloque_content = bloque_path.read_text(encoding="utf-8")
                first_line = bloque_content.split("\n", 1)[0].strip()
                if first_line.startswith("RESUMEN:"):
                    resumen_text = first_line[len("RESUMEN:"):].strip()
                    resumenes.append(f"**{bloque_name}:** {resumen_text}")
                else:
                    resumenes.append(f"**{bloque_name}:** (sin RESUMEN generado aún)")
            except Exception as e:
                logger.warning("v7.0 F5 (D11): no se pudo leer %s: %s", bloque_name, e)

        if not resumenes:
            logger.info("v7.0 F5 (D11): no hay bloques con RESUMEN para el tema '%s'", tema_actual)
            return False

        sintesis_text = "\n\n---\n\n".join(resumenes)

        # Reemplazar la sección G0.B en el 00_estado_actual.md.
        marker = "## G0.B — Síntesis del contexto disponible"
        if marker not in content:
            logger.info("v7.0 F5 (D11): marker G0.B no encontrado, no se actualiza")
            return False

        # Patron: desde el marker hasta el próximo "## " header o fin de archivo.
        pattern = _re_module.compile(
            rf"({ _re_module.escape(marker) }[^\n]*\n\n)(.*?)(?=\n## |\Z)",
            _re_module.DOTALL,
        )
        new_content = pattern.sub(rf"\g<1>{ _re_module.escape(sintesis_text) }\n", content)

        if new_content != content:
            estado_path.write_text(new_content, encoding="utf-8")
            logger.info(
                "v7.0 F5 (D11): sección G0.B regenerada con %d resumen(es) del tema '%s'",
                len(resumenes), tema_actual,
            )
            return True
        return False

    @staticmethod
    def _reemplazar_placeholders_objetivo(workspace_dir: Path | str) -> bool:
        """v7.0 F5 (D4): reemplaza los placeholders del ``03_objetivo_proyecto.md``
        por sus valores reales.

        Placeholders a reemplazar:
        - ``__MODELO_AGENTE__``: modelo del agente CZAI (ej: "glm-4-plus").
          Se lee del ``ZaiLLM`` default.
        - ``__DIRECTOR__``: nombre del Director. Se asume "Juan Carlos" por
          el JWT del CredentialManager (no es perfectamente derivable sin
          decodificar el JWT, que requiere el payload). Para no romper el
          archivo si el JWT no está, se deja como "Director".
        - ``__EMAIL__``: email del Director del CredentialManager.
        - ``__ACTA_NACIMIENTO__``: primer intercambio del chat cronológico
          (primer mensaje del Director que dio origen al proyecto). Se lee
          del primer bloque (bloque_01.md o el más antiguo) si tiene RESUMEN.

        Antes de v7.0, estos placeholders quedaban literales porque el
        comentario del código decía "el agente que responde debe rellenarlos"
        pero nadie implementó la lógica.

        Args:
            workspace_dir: Directorio del workspace.

        Returns:
            True si se reemplazó algún placeholder, False si no.
        """
        import json as _json
        ws = Path(workspace_dir)
        objetivo_path = ws / "03_objetivo_proyecto.md"
        if not objetivo_path.exists():
            return False

        content = objetivo_path.read_text(encoding="utf-8")
        original_content = content

        # __MODELO_AGENTE__: leer del ZaiLLM. Sin fallback hardcoded: si
        # ZaiLLM no se puede construir, devolvemos error (no placeholder).
        try:
            from contexto_zai.platforms.zai.zai_llm import ZaiLLM
            llm = ZaiLLM()
            modelo_agente = llm.get_default_model_heavy()
        except Exception as e:
            logger.warning(
                "v7.0 F5 (D4): no se pudo leer modelo del ZaiLLM: %s. "
                "Placeholder __MODELO_AGENTE__ no se reemplazará.", e,
            )
            modelo_agente = None  # No reemplazar si no hay fuente real.
        if modelo_agente:
            content = content.replace("__MODELO_AGENTE__", modelo_agente)

        # __EMAIL__ y __DIRECTOR__: leer via PlatformAuth (abstracción v7.0 F2).
        # Antes de v7.0, importaba directo ``CredentialManager``. Ahora usa
        # la interfaz abstracta ``PlatformAuth`` implementada por ``ZaiAuth``.
        try:
            from contexto_zai.platforms.zai.zai_auth import ZaiAuth
            auth = ZaiAuth()
            email = auth.get_email() or "Director (email no disponible)"
            # Nombre del Director derivado del email (parte antes del @).
            if "@" in email and "guest" not in email.lower():
                nombre_part = email.split("@")[0]
                # Capitalizar y reemplazar puntos/guiones por espacios.
                director = nombre_part.replace(".", " ").replace("_", " ").replace("-", " ").title()
            else:
                director = "Director"
        except Exception:
            email = "Director (email no disponible)"
            director = "Director"
        content = content.replace("__DIRECTOR__", director)
        content = content.replace("__EMAIL__", email)

        # __ACTA_NACIMIENTO__: primer exchange cronológico del proyecto.
        # El workspace usa orden descendente (bloque_01 = más reciente,
        # bloque_NN más alto = más antiguo). El primer exchange cronológico
        # está en el bloque más antiguo.
        # Si los bloques están en orden ascendente (caso contrario), el
        # primer exchange estaría en bloque_01. Heurística: leer el período
        # de cada bloque y elegir el de fecha más antigua.
        acta_nacimiento = "(Acta de nacimiento no disponible — ver worklog.md)"
        try:
            import re as _re_acta
            bloques = sorted(ws.glob("bloque_*.md"))
            if bloques:
                # Determinar el bloque más antiguo por período.
                bloque_mas_antiguo = None
                fecha_mas_antigua = None
                for b in bloques:
                    content_b = b.read_text(encoding="utf-8", errors="ignore")[:1500]
                    m = _re_acta.search(
                        r"\*\*Per[ií]odo:\*\*\s*(\d{4}-\d{2}-\d{2})",
                        content_b,
                    )
                    if m:
                        fecha = m.group(1)
                        if fecha_mas_antigua is None or fecha < fecha_mas_antigua:
                            fecha_mas_antigua = fecha
                            bloque_mas_antiguo = b
                # Si no encontramos períodos, fallback al último bloque por nombre
                # (asumiendo orden descendente).
                if bloque_mas_antiguo is None:
                    bloque_mas_antiguo = bloques[-1]
                bloque_content = bloque_mas_antiguo.read_text(encoding="utf-8")
                # Buscar el primer "### Director:" en el bloque.
                match_director = _re_acta.search(
                    r"### Director:\s*\n(.+?)(?=\n###|\n##|\Z)",
                    bloque_content,
                    _re_acta.DOTALL,
                )
                if match_director:
                    acta_nacimiento = match_director.group(1).strip()[:500]
        except Exception:
            pass
        content = content.replace("__ACTA_NACIMIENTO__", acta_nacimiento)

        if content != original_content:
            objetivo_path.write_text(content, encoding="utf-8")
            logger.info("v7.0 F5 (D4): placeholders reemplazados en 03_objetivo_proyecto.md")
            return True
        return False
