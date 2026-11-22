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
    def auditar_completitud(workspace_dir: Path | str) -> dict:
        """Auditoría integral: bloques + enriquecimiento + metadata.
        
        Returns:
            dict con:
            - 'completos': lista de block_id completos.
            - 'incompletos': lista de {block_id, faltantes}.
            - 'metadata_valida': bool.
        """
        bloques = AuditorWorkspace.auditar_bloques(workspace_dir)
        metadata_valida = AuditorWorkspace.auditar_metadata(workspace_dir)
        
        return {
            "completos": bloques["completos"],
            "incompletos": bloques["incompletos"],
            "metadata_valida": metadata_valida,
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
