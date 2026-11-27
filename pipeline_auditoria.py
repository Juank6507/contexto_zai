"""contexto_zai/pipeline_auditoria.py -- Módulo de auditoría del workspace (v7.0 modularizado).

Contiene las clases reusables de auditoría que antes vivían en ``pipeline.py``:

- ``AuditorWorkspace`` (v6.13 F3) — recorre el workspace físico y reporta
  bloques completos/incompletos (RESUMEN + 3 archivos ``_responses/``).
  Sincroniza ``_processed_blocks.json`` con el estado físico real.
- ``ProgressMonitor`` (v6.12 F1) — monitorea el progreso del Worker Bun
  contando bloques completos en intervalos progresivos. Decide si hay
  progreso o si el Worker Bun cayó.

Este módulo es la base de la cascada de acceso LLM y del bucle D7 —
ambos consultan ``AuditorWorkspace`` para decidir qué bloques están
incompletos y cuándo detenerse.

No cambia el grafo de flujo interno: solo mueve código.
"""

from __future__ import annotations

import logging
import time as _time
import json as _json_module
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================
# v7.1 F6/AUD: constantes de tipo para pending_tasks
# ------------------------------------------------------------
# Cada carencia detectada por ``auditar_workspace_completo`` se encola
# como ``SubagentTask`` con un campo ``tipo`` que enruta al módulo
# responsable. Las constantes evitan strings mágicos (NH21/R4).
# ============================================================

TIPO_AUXILIAR_BLOQUE = "auxiliar_bloque"
TIPO_RESUMEN_BLOQUE = "resumen_bloque"
TIPO_HEADER_BLOQUE = "header_bloque"
TIPO_CONTENIDO_BLOQUE = "contenido_bloque"
TIPO_METADATA = "metadata"
TIPO_PROCESSED_BLOCKS = "processed_blocks"
TIPO_ARCHIVO_RECUPERACION_00 = "archivo_recuperacion_00"
TIPO_ARCHIVO_RECUPERACION_01 = "archivo_recuperacion_01"
TIPO_ARCHIVO_RECUPERACION_02 = "archivo_recuperacion_02"
TIPO_ARCHIVO_RECUPERACION_03 = "archivo_recuperacion_03"
TIPO_OBJETIVO_PROYECTO = "objetivo_proyecto"
TIPO_SECCION_ESTADO = "seccion_estado"


class ProgressMonitor:
    """v6.12 F1: Monitorea el progreso del Worker Bun contando bloques completos.

    Un bloque esta completo cuando tiene RESUMEN al inicio Y los 3 archivos
    en _responses/ (nombre, decisiones, temas). ProgressMonitor cuenta
    bloques completos en intervalos y decide si hay progreso.

    Separada del arnés (OOP): la comprobacion de progreso es una cosa,
    el uso de los componentes del arnés (Worker Bun, proxy Z.ai, subagentes)
    es otra.
    """

    @staticmethod
    def contar_bloques_completos(workspace_dir: Path | str) -> int:
        """Cuenta cuantos bloques estan realmente completos.

        Un bloque esta completo cuando tiene:
        1. RESUMEN: al inicio del archivo bloque_NN.md
        2. _responses/bloque_NN_nombre.txt
        3. _responses/bloque_NN_decisiones.txt
        4. _responses/bloque_NN_temas.txt

        Args:
            workspace_dir: Directorio del workspace.

        Returns:
            Numero de bloques completos.
        """
        ws = Path(workspace_dir)
        if not ws.exists():
            return 0

        responses_dir = ws / "_responses"
        completos = 0

        for p in sorted(ws.glob("bloque_*.md")):
            block_id = p.stem  # "bloque_01"
            content = p.read_text(encoding="utf-8", errors="ignore")
            if not content.startswith("RESUMEN:"):
                continue
            # Verificar los 3 archivos de _responses/
            if not responses_dir.exists():
                continue
            if not (responses_dir / f"{block_id}_nombre.txt").exists():
                continue
            if not (responses_dir / f"{block_id}_decisiones.txt").exists():
                continue
            if not (responses_dir / f"{block_id}_temas.txt").exists():
                continue
            completos += 1

        return completos

    @staticmethod
    def contar_bloques_totales(workspace_dir: Path | str) -> int:
        """Cuenta el total de bloques en el workspace."""
        ws = Path(workspace_dir)
        if not ws.exists():
            return 0
        return len(list(ws.glob("bloque_*.md")))

    @staticmethod
    def esperar_y_verificar(
        workspace_dir: Path | str,
        intervalo_inicial: int = 20,
        max_intervalos: int = 10,
        crecimiento: float = 2.0,
    ) -> bool:
        """Espera al Worker Bun monitoreando progreso en intervalos progresivos.

        Comienza tras 20s iniciales. Despues comprueba cada intervalo
        (que crece progresivamente). Si hay progreso (mas bloques completos
        que antes), sigue esperando. Si no hay progreso en 2 intervalos
        seguidos, declara que el Worker Bun cayo.

        Args:
            workspace_dir: Directorio del workspace.
            intervalo_inicial: Segundos del primer intervalo (default 20).
            max_intervalos: Maximo numero de comprobaciones (default 10).
            crecimiento: Factor de crecimiento del intervalo (default 1.5).

        Returns:
            True si el Worker Bun completo todos los bloques.
            False si no progreso en 2 intervalos seguidos o se agotaron los intervalos.
        """
        import time as _time

        total_bloques = ProgressMonitor.contar_bloques_totales(workspace_dir)

        # Espera inicial
        logger.info(
            "v6.12 ProgressMonitor: esperando %ds iniciales (%d bloques totales)...",
            intervalo_inicial, total_bloques,
        )
        _time.sleep(intervalo_inicial)

        completos_anterior = ProgressMonitor.contar_bloques_completos(workspace_dir)
        sin_progreso_consecutivos = 0
        intervalo_actual = intervalo_inicial

        for i in range(max_intervalos):
            _time.sleep(intervalo_actual)
            completos_ahora = ProgressMonitor.contar_bloques_completos(workspace_dir)

            logger.info(
                "v6.12 ProgressMonitor: intervalo %d/%d - %d/%d bloques completos (intervalo=%ds)",
                i + 1, max_intervalos, completos_ahora, total_bloques, intervalo_actual,
            )

            if completos_ahora >= total_bloques:
                logger.info("v6.12 ProgressMonitor: todos los bloques completos.")
                return True

            if completos_ahora > completos_anterior:
                sin_progreso_consecutivos = 0
                logger.info(
                    "v6.12 ProgressMonitor: progreso detectado (%d -> %d).",
                    completos_anterior, completos_ahora,
                )
            else:
                sin_progreso_consecutivos += 1
                logger.warning(
                    "v6.12 ProgressMonitor: sin progreso (%d/%d consecutivos).",
                    sin_progreso_consecutivos, 2,
                )
                if sin_progreso_consecutivos >= 2:
                    logger.warning(
                        "v6.12 ProgressMonitor: Worker Bun sin progreso en 2 intervalos. Cayo."
                    )
                    return False

            completos_anterior = completos_ahora
            intervalo_actual = int(intervalo_actual * crecimiento)

        logger.warning("v6.12 ProgressMonitor: maximo de intervalos alcanzado.")
        return completos_ahora >= total_bloques


class AuditorWorkspace:
    """v6.13 F3: Clase reutilizable para auditar el workspace.
    
    Se ejecuta en 2 momentos:
    1. Al inicio (antes de decidir recovery vs incremental).
    2. Al final (después de procesar, para validar completitud).
    """
    
    @staticmethod
    def auditar_bloques(workspace_dir: Path | str) -> dict:
        """Recorre bloque_*.md y verifica RESUMEN + 3 archivos _responses/.
        
        Returns:
            dict con 'completos' (lista) e 'incompletos' (lista).
        """
        ws = Path(workspace_dir)
        if not ws.exists():
            return {"completos": [], "incompletos": []}
        
        responses_dir = ws / "_responses"
        completos = []
        incompletos = []
        
        for p in sorted(ws.glob("bloque_*.md")):
            block_id = p.stem
            content = p.read_text(encoding="utf-8", errors="ignore")
            
            tiene_resumen = content.startswith("RESUMEN:")
            tiene_nombre = (responses_dir / f"{block_id}_nombre.txt").exists()
            tiene_decisiones = (responses_dir / f"{block_id}_decisiones.txt").exists()
            tiene_temas = (responses_dir / f"{block_id}_temas.txt").exists()
            
            if tiene_resumen and tiene_nombre and tiene_decisiones and tiene_temas:
                completos.append(block_id)
            else:
                faltantes = []
                if not tiene_resumen: faltantes.append("RESUMEN")
                if not tiene_nombre: faltantes.append("nombre.txt")
                if not tiene_decisiones: faltantes.append("decisiones.txt")
                if not tiene_temas: faltantes.append("temas.txt")
                incompletos.append({"block_id": block_id, "faltantes": faltantes})
        
        logger.info("AuditorWorkspace: %d completos, %d incompletos", len(completos), len(incompletos))
        return {"completos": completos, "incompletos": incompletos}
    
    @staticmethod
    def auditar_metadata(workspace_dir: Path | str) -> bool:
        """Verifica que _metadata.json coincide con los bloques físicos.
        
        Returns:
            True si la metadata es válida, False si no.
        """
        ws = Path(workspace_dir)
        meta_path = ws / "_metadata.json"
        if not meta_path.exists():
            return False
        
        try:
            import json as _json
            metadata = _json.loads(meta_path.read_text(encoding="utf-8"))
            tema_a_archivo = metadata.get("tema_a_archivo", {})
            ultimo_timestamp = metadata.get("ultimo_timestamp")
            
            if not tema_a_archivo:
                return False
            if ultimo_timestamp is None:
                return False
            
            # Verificar que los archivos referenciados existen
            bloques_fisicos = set(p.name for p in ws.glob("bloque_*.md"))
            for tema, archivo in tema_a_archivo.items():
                if isinstance(archivo, list):
                    for a in archivo:
                        if a not in bloques_fisicos and not (ws / a).exists():
                            logger.info("AuditorWorkspace: metadata referencia %s que no existe", a)
                            return False
                elif isinstance(archivo, str):
                    if archivo not in bloques_fisicos and not (ws / archivo).exists():
                        logger.info("AuditorWorkspace: metadata referencia %s que no existe", archivo)
                        return False
            
            return True
        except Exception as e:
            logger.warning("AuditorWorkspace: error leyendo metadata: %s", e)
            return False
    
    @staticmethod
    def auditar_calidad(workspace_dir: Path | str) -> dict:
        """F1-F7: Audita la calidad del contenido de los 4 archivos de recuperación.

        Verifica no solo que los archivos existen (eso lo hace auditar_bloques)
        sino que el CONTENIDO cumple los criterios de calidad conciliados.

        Returns:
            dict con:
            - 'deficiencias': lista de strings describiendo cada deficiencia.
            - 'calidad_ok': True si no hay deficiencias.
        """
        import re as _re
        ws = Path(workspace_dir)
        deficiencias: list[str] = []

        # F2: 00_estado_actual.md
        estado_path = ws / "00_estado_actual.md"
        if estado_path.exists():
            estado = estado_path.read_text(encoding="utf-8")
            # Placeholders embebidos
            if "__" in estado and _re.search(r"__[A-Z_]+__", estado):
                deficiencias.append("00_estado: placeholders __*__ sin reemplazar embebidos")
            # G0.A duplicada
            if estado.count("## G0.A") > 1:
                deficiencias.append("00_estado: sección G0.A duplicada")
            # Paths con caracteres especiales en A2
            if "## Sección A2" in estado:
                a2_section = estado[estado.find("## Sección A2"):]
                a2_section = a2_section[:a2_section.find("## Sección A3")] if "## Sección A3" in a2_section else a2_section[:2000]
                # Buscar paths con -- o > pegados
                if _re.search(r"(/[^\s]+)(\s*--\s)", a2_section) or _re.search(r"(/[^\s]+)(\s*>)", a2_section):
                    deficiencias.append("00_estado: paths con caracteres especiales en A2")
            # Traceback sin stack trace en A3
            if "## Sección A3" in estado:
                a3_section = estado[estado.find("## Sección A3"):]
                a3_section = a3_section[:a3_section.find("## Sección A4")] if "## Sección A4" in a3_section else a3_section[:2000]
                if "Traceback" in a3_section and "most recent call last" not in a3_section:
                    deficiencias.append("00_estado: Traceback sin stack trace en A3 (mención, no error real)")
            # Caracteres escapados en G0.B
            if "## G0.B" in estado:
                g0b_section = estado[estado.find("## G0.B"):]
                g0b_section = g0b_section[:g0b_section.find("## G1")] if "## G1" in g0b_section else g0b_section[:3000]
                if "\\*" in g0b_section or "\\-" in g0b_section or "\\(" in g0b_section:
                    deficiencias.append("00_estado: caracteres escapados en G0.B (re.escape mal aplicado)")

        # F3: 03_objetivo_proyecto.md
        objetivo_path = ws / "03_objetivo_proyecto.md"
        if objetivo_path.exists():
            objetivo = objetivo_path.read_text(encoding="utf-8")
            if "__" in objetivo and _re.search(r"__[A-Z_]+__", objetivo):
                deficiencias.append("03_objetivo: placeholders __*__ sin reemplazar")
            if "Proyecto sobre:" in objetivo and len(objetivo) < 500:
                deficiencias.append("03_objetivo: contenido automático (Proyecto sobre:) en vez de plantilla real")

        # F4: 01_indice_recuperacion.md
        indice_path = ws / "01_indice_recuperacion.md"
        if indice_path.exists():
            indice = indice_path.read_text(encoding="utf-8")
            # Buscar si todos los valores de tokens son iguales (hardcodeados)
            tokens_matches = _re.findall(r"~(\d+\.\d+)K", indice)
            if len(tokens_matches) > 5:
                unique_tokens = set(tokens_matches)
                if len(unique_tokens) == 1:
                    deficiencias.append(f"01_indice: todos los tokens hardcodeados a ~{tokens_matches[0]}K")

        # F5: 02_decisiones_clave.md
        decisiones_path = ws / "02_decisiones_clave.md"
        if decisiones_path.exists():
            decisiones = decisiones_path.read_text(encoding="utf-8")
            # Contar decisiones
            num_decisiones = decisiones.count("## D")
            # Verificar duplicadas por texto
            dec_texts = _re.findall(r"\*\*Decisión:\*\*\s*(.+?)(?:\n|$)", decisiones)
            if dec_texts:
                normalized = [" ".join(t.lower().split()) for t in dec_texts]
                duplicates = len(normalized) - len(set(normalized))
                if duplicates > 0:
                    deficiencias.append(f"02_decisiones: {duplicates} decisión(es) duplicada(s)")
            # Verificar cantidad excesiva (más de 1 decisión por cada 3 intercambios es sospechoso)
            try:
                import json as _json_f5
                meta_path = ws / "_metadata.json"
                if meta_path.exists():
                    meta = _json_f5.loads(meta_path.read_text(encoding="utf-8"))
                    total_exchanges = meta.get("total_exchanges", 0)
                    if total_exchanges > 0 and num_decisiones > total_exchanges / 3:
                        deficiencias.append(f"02_decisiones: {num_decisiones} decisiones para {total_exchanges} intercambios (excesivo, ratio > 1/3)")
            except Exception:
                pass

        return {
            "deficiencias": deficiencias,
            "calidad_ok": len(deficiencias) == 0,
        }

    @staticmethod
    def auditar_completitud(workspace_dir: Path | str) -> dict:
        """Auditoría integral: bloques + enriquecimiento + metadata + calidad.

        F1: ahora incluye auditar_calidad además de auditar_bloques.

        v7.1 F6/AUD.1: también llama a ``auditar_workspace_completo`` y
        devuelve las ``pending_tasks`` nuevas (con campo ``tipo`` que
        enruta al módulo responsable) en ``resultado["pending_tasks"]``.

        Returns:
            dict con:
            - 'completos': lista de block_id completos.
            - 'incompletos': lista de {block_id, faltantes}.
            - 'metadata_valida': bool.
            - 'deficiencias_calidad': lista de deficiencias de calidad (F7).
            - 'calidad_ok': bool.
            - 'pending_tasks' (v7.1): lista de SubagentTask con campo
              ``tipo`` que enruta al módulo responsable (D7 despacha).
        """
        bloques = AuditorWorkspace.auditar_bloques(workspace_dir)
        metadata_valida = AuditorWorkspace.auditar_metadata(workspace_dir)
        calidad = AuditorWorkspace.auditar_calidad(workspace_dir)
        # v7.1 F6/AUD.1: auditoría completa del workspace → pending_tasks con tipo.
        workspace_audit = AuditorWorkspace.auditar_workspace_completo(workspace_dir)

        return {
            "completos": bloques["completos"],
            "incompletos": bloques["incompletos"],
            "metadata_valida": metadata_valida,
            "deficiencias_calidad": calidad["deficiencias"],
            "calidad_ok": calidad["calidad_ok"],
            # v7.1 F6/AUD.2: pending_tasks con campo `tipo` para enrutar.
            "pending_tasks": workspace_audit["pending_tasks"],
            "total_carencias": workspace_audit["total_carencias"],
        }

    @staticmethod
    def auditar_workspace_completo(workspace_dir: Path | str) -> dict:
        """v7.1 F6/AUD.1: auditoría completa del workspace con pending_tasks tipadas.

        Verifica existencia y calidad de TODOS los archivos del workspace:

        1. **Bloques** (``bloque_*.md``): header (``# Bloque temático:`` o
           ``# Bloque cronológico``), primera línea ``RESUMEN:`` con
           longitud en rango ``RESUMEN_MIN_CHARS..RESUMEN_MAX_CHARS``,
           separador ``\\n\\n---\\n\\n`` entre RESUMEN y contenido,
           contenido no vacío. Las carencias generan pending_tasks con
           ``tipo`` en ``{resumen_bloque, header_bloque, contenido_bloque}``.
        2. **Auxiliares** (``_responses/bloque_NN_{nombre,decisiones,temas}.txt``):
           existence + no vacío + formato esperado. Las carencias generan
           pending_tasks con ``tipo="auxiliar_bloque"``.
        3. **Metadata** (``_metadata.json``): existence + campos obligatorios
           (``tema_a_archivo``, ``ultimo_timestamp``, ``total_exchanges``) +
           consistencia con bloques físicos. Las carencias generan
           pending_tasks con ``tipo="metadata"``.
        4. **Processed blocks** (``_processed_blocks.json``): existence +
           todos los bloques físicos representados + sin entradas huérfanas.
           Las carencias generan pending_tasks con ``tipo="processed_blocks"``.
        5. **Los 4 archivos de recuperación**: delega al ``auditar_calidad``
           existente, pero mapea las deficiencias a pending_tasks con
           ``tipo`` en ``{archivo_recuperacion_00, _01, _02, _03,
           objetivo_proyecto, seccion_estado}`` según la deficiencia.

        Cada pending_task generada es un ``SubagentTask`` con campos
        ``task_id``, ``purpose``, ``prompt``, ``context`` (con
        ``workspace_dir``, ``bloque_id`` si aplica, ``tipo``), ``tipo``
        (la clave de enrutamiento).

        P1 conciliado: la auditoría NO llama a ``CicloW3``,
        ``SubprocesoArchivos``, ni ``EstadoGenerator``. Solo detecta y
        encola. El bucle D7 consume las pending_tasks y despacha por
        ``tipo`` (ver ``pipeline_d7.despachar_por_tipo``).

        Args:
            workspace_dir: Directorio del workspace.

        Returns:
            dict con:
            - 'pending_tasks': lista de ``SubagentTask`` con campo ``tipo``.
            - 'deficiencias': lista de strings describiendo cada deficiencia.
            - 'total_carencias': int (len(pending_tasks)).
        """
        from contexto_zai.models import SubagentTask
        try:
            from contexto_zai.config import (
                RESUMEN_MIN_CHARS as _R_MIN,
                RESUMEN_MAX_CHARS as _R_MAX,
            )
        except ImportError:
            _R_MIN, _R_MAX = 600, 900

        ws = Path(workspace_dir)
        pending_tasks: list = []
        deficiencias: list[str] = []

        def _emit(tipo: str, bloque_id: str, purpose: str, prompt: str, extra_ctx: dict | None = None) -> None:
            """Helper: construye y encola una SubagentTask con tipo."""
            ctx = {"workspace_dir": str(ws), "tipo": tipo}
            if bloque_id:
                ctx["bloque_id"] = bloque_id
            if extra_ctx:
                ctx.update(extra_ctx)
            task_id = f"auditar_{tipo}" + (f"_{bloque_id}" if bloque_id else "")
            pending_tasks.append(SubagentTask(
                task_id=task_id,
                purpose=purpose,
                prompt=prompt,
                context=ctx,
                tipo=tipo,
            ))

        if not ws.exists():
            return {"pending_tasks": [], "deficiencias": ["workspace no existe"], "total_carencias": 0}

        # 1. Bloques (bloque_*.md): header, RESUMEN, separador, contenido.
        for p in sorted(ws.glob("bloque_*.md")):
            block_id = p.stem
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                deficiencias.append(f"{block_id}: no se pudo leer ({e})")
                _emit(TIPO_CONTENIDO_BLOQUE, block_id,
                      purpose=f"auditar.contenido_bloque.{p.name}",
                      prompt=f"El bloque {p.name} no se pudo leer. Regenerarlo desde los intercambios originales.")
                continue

            # 1a. Header.
            first_line = content.split("\n", 1)[0].strip() if content else ""
            has_header = (
                first_line.startswith("# Bloque tematico:")
                or first_line.startswith("# Bloque temático:")
                or first_line.startswith("# Bloque cronológico")
                or first_line.startswith("# Bloque cronologico")
                or first_line.startswith("# Bloque externo")
            )
            # Si el bloque empieza con RESUMEN:, el header puede faltar pero
            # el RESUMEN es lo crítico (backward compat con bloques v6.x).
            if not has_header and not content.startswith("RESUMEN:"):
                deficiencias.append(f"{block_id}: sin header '# Bloque ...'")
                _emit(TIPO_HEADER_BLOQUE, block_id,
                      purpose=f"auditar.header_bloque.{p.name}",
                      prompt=f"El bloque {p.name} no tiene header '# Bloque temático: ...' o '# Bloque cronológico ...'. Regenerar el bloque con el header correcto.")

            # 1b. RESUMEN.
            if not content.startswith("RESUMEN:"):
                deficiencias.append(f"{block_id}: sin RESUMEN al inicio")
                _emit(TIPO_RESUMEN_BLOQUE, block_id,
                      purpose=f"auditar.resumen_bloque.{p.name}",
                      prompt=f"El bloque {p.name} no tiene RESUMEN al inicio. Enriquecerlo vía W3 (cascada + Crítico) para generar el RESUMEN + 3 archivos auxiliares.")
            else:
                parts = content.split("\n\n---\n\n", 1)
                resumen_text = parts[0][len("RESUMEN:"):].strip()
                if len(resumen_text) < _R_MIN or len(resumen_text) > _R_MAX:
                    deficiencias.append(
                        f"{block_id}: RESUMEN con longitud {len(resumen_text)} fuera de rango [{_R_MIN},{_R_MAX}]"
                    )
                    _emit(TIPO_RESUMEN_BLOQUE, block_id,
                          purpose=f"auditar.resumen_bloque.{p.name}",
                          prompt=f"El bloque {p.name} tiene un RESUMEN con longitud {len(resumen_text)} fuera del rango [{_R_MIN},{_R_MAX}]. Regenerar el RESUMEN vía W3.")

            # 1c. Separador + contenido.
            if "\n\n---\n\n" not in content:
                deficiencias.append(f"{block_id}: sin separador '\\n\\n---\\n\\n' entre RESUMEN y contenido")
                _emit(TIPO_CONTENIDO_BLOQUE, block_id,
                      purpose=f"auditar.contenido_bloque.{p.name}",
                      prompt=f"El bloque {p.name} no tiene separador '\\n\\n---\\n\\n' entre RESUMEN y contenido. Regenerar el bloque con el formato correcto.")
            else:
                contenido = content.split("\n\n---\n\n", 1)[1].strip()
                if len(contenido) < 100:
                    deficiencias.append(f"{block_id}: contenido vacío o casi vacío ({len(contenido)} chars)")
                    _emit(TIPO_CONTENIDO_BLOQUE, block_id,
                          purpose=f"auditar.contenido_bloque.{p.name}",
                          prompt=f"El bloque {p.name} tiene contenido vacío o casi vacío ({len(contenido)} chars). Regenerar el contenido desde los intercambios originales.")

            # 2. Auxiliares (_responses/bloque_NN_*.txt).
            responses_dir = ws / "_responses"
            for aux_suffix in ("nombre", "decisiones", "temas"):
                aux_path = responses_dir / f"{block_id}_{aux_suffix}.txt"
                if not aux_path.exists():
                    deficiencias.append(f"{block_id}: falta _responses/{block_id}_{aux_suffix}.txt")
                    _emit(TIPO_AUXILIAR_BLOQUE, block_id,
                          purpose=f"auditar.auxiliar_bloque.{block_id}_{aux_suffix}",
                          prompt=f"Falta _responses/{block_id}_{aux_suffix}.txt. Generarlo desde el contenido del bloque.",
                          extra_ctx={"auxiliar": aux_suffix})
                else:
                    try:
                        aux_content = aux_path.read_text(encoding="utf-8", errors="ignore").strip()
                        if not aux_content:
                            deficiencias.append(f"{block_id}: _responses/{block_id}_{aux_suffix}.txt vacío")
                            _emit(TIPO_AUXILIAR_BLOQUE, block_id,
                                  purpose=f"auditar.auxiliar_bloque.{block_id}_{aux_suffix}",
                                  prompt=f"_responses/{block_id}_{aux_suffix}.txt está vacío. Regenerarlo desde el contenido del bloque.",
                                  extra_ctx={"auxiliar": aux_suffix})
                    except Exception:
                        deficiencias.append(f"{block_id}: no se pudo leer _responses/{block_id}_{aux_suffix}.txt")
                        _emit(TIPO_AUXILIAR_BLOQUE, block_id,
                              purpose=f"auditar.auxiliar_bloque.{block_id}_{aux_suffix}",
                              prompt=f"No se pudo leer _responses/{block_id}_{aux_suffix}.txt. Regenerarlo.",
                              extra_ctx={"auxiliar": aux_suffix})

        # 3. Metadata (_metadata.json).
        meta_path = ws / "_metadata.json"
        metadata_ok = True
        if not meta_path.exists():
            deficiencias.append("_metadata.json no existe")
            _emit(TIPO_METADATA, "",
                  purpose="auditar.metadata.inexistente",
                  prompt="_metadata.json no existe. Regenerarlo desde los bloques físicos (tema_a_archivo, ultimo_timestamp, total_exchanges).")
            metadata_ok = False
        else:
            try:
                meta = _json_module.loads(meta_path.read_text(encoding="utf-8"))
                campos_obligatorios = ["tema_a_archivo", "ultimo_timestamp", "total_exchanges"]
                faltan_meta = [c for c in campos_obligatorios if c not in meta or meta[c] in (None, "", {})]
                if faltan_meta:
                    deficiencias.append(f"_metadata.json: faltan campos obligatorios {faltan_meta}")
                    _emit(TIPO_METADATA, "",
                          purpose="auditar.metadata.campos_faltantes",
                          prompt=f"_metadata.json falta campos obligatorios: {faltan_meta}. Regenerar metadata + índice.",
                          extra_ctx={"campos_faltantes": faltan_meta})
                    metadata_ok = False
                else:
                    # Consistencia: tema_a_archivo referencia bloques físicos.
                    bloques_fisicos = {p.name for p in ws.glob("bloque_*.md")}
                    tema_a_archivo = meta.get("tema_a_archivo", {})
                    for tema, archivo in tema_a_archivo.items():
                        archivos = archivo if isinstance(archivo, list) else [archivo]
                        for a in archivos:
                            if a not in bloques_fisicos:
                                deficiencias.append(f"_metadata.json: tema '{tema}' referencia '{a}' que no existe como bloque físico")
                                _emit(TIPO_METADATA, "",
                                      purpose="auditar.metadata.inconsistencia",
                                      prompt=f"_metadata.json: tema '{tema}' referencia '{a}' que no existe. Regenerar metadata + índice.",
                                      extra_ctx={"tema": tema, "archivo_inexistente": a})
                                metadata_ok = False
            except Exception as e:
                deficiencias.append(f"_metadata.json: no se pudo parsear ({e})")
                _emit(TIPO_METADATA, "",
                      purpose="auditar.metadata.parse_error",
                      prompt=f"_metadata.json no se pudo parsear ({e}). Regenerar metadata + índice.")
                metadata_ok = False

        # 4. Processed blocks (_processed_blocks.json).
        pb_path = ws / "_processed_blocks.json"
        if not pb_path.exists():
            deficiencias.append("_processed_blocks.json no existe")
            _emit(TIPO_PROCESSED_BLOCKS, "",
                  purpose="auditar.processed_blocks.inexistente",
                  prompt="_processed_blocks.json no existe. Sincronizar el registro con el estado físico real (AuditorWorkspace.sincronizar_registro).")
        else:
            try:
                pb = _json_module.loads(pb_path.read_text(encoding="utf-8"))
                bloques_fisicos_set = {p.stem for p in ws.glob("bloque_*.md")}
                pb_blocks = {b.get("block_id", "") for b in pb.get("blocks", []) if isinstance(b, dict)}
                # Bloques físicos no representados.
                sin_representar = bloques_fisicos_set - pb_blocks
                if sin_representar:
                    deficiencias.append(f"_processed_blocks.json: {len(sin_representar)} bloque(s) físico(s) sin representar: {sorted(sin_representar)[:5]}")
                    _emit(TIPO_PROCESSED_BLOCKS, "",
                          purpose="auditar.processed_blocks.sin_representar",
                          prompt=f"_processed_blocks.json no representa {len(sin_representar)} bloque(s) físico(s). Sincronizar el registro.",
                          extra_ctx={"bloques_sin_representar": sorted(sin_representar)[:10]})
                # Entradas huérfanas.
                huerfanas = pb_blocks - bloques_fisicos_set
                if huerfanas:
                    deficiencias.append(f"_processed_blocks.json: {len(huerfanas)} entrada(s) huérfana(s): {sorted(huerfanas)[:5]}")
                    _emit(TIPO_PROCESSED_BLOCKS, "",
                          purpose="auditar.processed_blocks.huerfanas",
                          prompt=f"_processed_blocks.json tiene {len(huerfanas)} entrada(s) huérfana(s) (bloques que ya no existen físicamente). Sincronizar el registro.",
                          extra_ctx={"entradas_huerfanas": sorted(huerfanas)[:10]})
            except Exception as e:
                deficiencias.append(f"_processed_blocks.json: no se pudo parsear ({e})")
                _emit(TIPO_PROCESSED_BLOCKS, "",
                      purpose="auditar.processed_blocks.parse_error",
                      prompt=f"_processed_blocks.json no se pudo parsear ({e}). Sincronizar el registro.")

        # 5. Los 4 archivos de recuperación: delega a auditar_calidad y mapea.
        calidad = AuditorWorkspace.auditar_calidad(workspace_dir)
        for def_str in calidad["deficiencias"]:
            deficiencias.append(def_str)
            # Mapear la deficiencia al tipo correspondiente.
            if def_str.startswith("00_estado"):
                _emit(TIPO_SECCION_ESTADO, "",
                      purpose="auditar.seccion_estado",
                      prompt=f"Deficiencia en 00_estado_actual.md: {def_str}. Regenerar 00 vía SubprocesoArchivos (que invoca al W3 para D4/A3/A4).")
            elif def_str.startswith("03_objetivo"):
                _emit(TIPO_OBJETIVO_PROYECTO, "",
                      purpose="auditar.objetivo_proyecto",
                      prompt=f"Deficiencia en 03_objetivo_proyecto.md: {def_str}. Regenerar 03 vía SubprocesoArchivos (que invoca al W3 para objetivo).")
            elif def_str.startswith("01_indice"):
                _emit(TIPO_ARCHIVO_RECUPERACION_01, "",
                      purpose="auditar.archivo_recuperacion_01",
                      prompt=f"Deficiencia en 01_indice_recuperacion.md: {def_str}. Regenerar 01 vía SubprocesoArchivos._regenerar_indice_tras_enriquecimiento.")
            elif def_str.startswith("02_decisiones"):
                _emit(TIPO_ARCHIVO_RECUPERACION_02, "",
                      purpose="auditar.archivo_recuperacion_02",
                      prompt=f"Deficiencia en 02_decisiones_clave.md: {def_str}. Regenerar 02 vía SubprocesoArchivos._consolidar_decisiones_llm.")
            else:
                # Deficiencia genérica → archivo_recuperacion_00 (default).
                _emit(TIPO_ARCHIVO_RECUPERACION_00, "",
                      purpose="auditar.archivo_recuperacion_00",
                      prompt=f"Deficiencia genérica en archivos de recuperación: {def_str}. Regenerar vía SubprocesoArchivos._generar_archivos_recuperacion.")

        logger.info(
            "v7.1 F6/AUD.1 auditar_workspace_completo: %d carencia(s) detectada(s), "
            "%d pending_task(s) generadas con tipo.",
            len(deficiencias), len(pending_tasks),
        )
        return {
            "pending_tasks": pending_tasks,
            "deficiencias": deficiencias,
            "total_carencias": len(pending_tasks),
        }

    @staticmethod
    def sincronizar_registro(workspace_dir: Path | str) -> None:
        """Sincroniza _processed_blocks.json con el estado físico.
        
        Antes de devolver el OrchestratorResult, recorre todos los bloques
        y actualiza el registro con el estado físico real.
        """
        ws = Path(workspace_dir)
        registro_path = ws / "_processed_blocks.json"
        
        audit = AuditorWorkspace.auditar_bloques(workspace_dir)
        completos_set = set(audit["completos"])
        
        registro = {"blocks": []}
        for p in sorted(ws.glob("bloque_*.md")):
            block_id = p.stem
            if block_id in completos_set:
                registro["blocks"].append({
                    "block_id": block_id,
                    "status": "completed",
                    "processed_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                    "error": None,
                })
            else:
                registro["blocks"].append({
                    "block_id": block_id,
                    "status": "pending",
                    "processed_at": None,
                    "error": "incomplete",
                })
        
        registro_path.write_text(_json_module.dumps(registro, indent=2), encoding="utf-8")
        logger.info("AuditorWorkspace: _processed_blocks.json sincronizado (%d completed, %d pending)",
                    len(completos_set), len(registro["blocks"]) - len(completos_set))
