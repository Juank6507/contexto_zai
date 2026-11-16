# contexto_zai/generation/contexto_generator.py -- ContextoGenerator (v6.7 F3): clase base abstracta con hook _debe_generar_recuperacion() basado en cronología (Principio 3: los 4 archivos se generan solo si la info es cronológica y posterior).
"""ContextoGenerator (v6.6) — Clase base abstracta para los generadores de contexto.

QUÉ SOLUCIONA:
- v6.5: los caminos de generación (RecoveryCycle, IncrementalCycle, ampliar_contexto)
  iban por rutas paralelas que duplicaban lógica (escribir bloques, actualizar
  metadata, regenerar índice, enriquecer, consolidar decisiones) y divergían en
  estructura (nombres, headers, ubicación de bloques externos).
- v6.6: esta clase base define el flujo común y las subclases solo especializan
  la parte que realmente distingue: de dónde sacan los intercambios y si
  generan o no los archivos de recuperación (estado, decisiones).

PRINCIPIOS (conciliados con el Director):
1. OOP para lo común: lo común se hereda, lo divergente se especializa.
2. Estructura uniforme del contexto: mismos archivos, mismos nombres, mismos
   headers, venga de donde venga.
3. El estado siempre se genera desde el último intercambio — pero solo cuando
   hay pérdida de contexto. Cuando es ampliación (fuente externa), NO se
   generan los archivos de recuperación (spec v4.4 línea 36).
4. Bloques secuenciales, índices abarcadores: el BlockPacker ya hace
   reempaquetado selectivo correctamente (no se toca).

Atómico standalone: importa config, models, logging. No tiene dependencias
circulares con los ciclos (los ciclos lo usan a él, no al revés).
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
_package_root = None
for _ in range(10):
    if not _os.path.isfile(_os.path.join(_candidate, '__init__.py')):
        break
    _parent = _os.path.dirname(_candidate)
    if not _os.path.isfile(_os.path.join(_parent, '__init__.py')):
        _package_root = _candidate
        break
    _candidate = _parent
if _package_root:
    _workspace = _os.path.dirname(_package_root)
    if _workspace not in _sys.path:
        _sys.path.insert(0, _workspace)
else:
    _parent = _os.path.dirname(_here)
    if _parent not in _sys.path:
        _sys.path.insert(0, _parent)

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from contexto_zai.config import WORKSPACE_OUTPUT_DIR
from contexto_zai.models import RecoveryFile, ThematicBlock

logger = logging.getLogger(__name__)


class ContextoGenerator(ABC):
    """Clase base abstracta que unifica el flujo común de generación de contexto.

    Define el esqueleto del flujo común (Template Method pattern). Las
    subclases concretas implementan los métodos abstractos que especializan
    el comportamiento.

    Subclases esperadas:
    - RecoveryCycleGenerator: extrae del chat completo, genera recuperación.
    - IncrementalCycleGenerator: extrae solo nuevos, genera recuperación.
    - AmpliarGenerator: extrae de fuente externa, NO genera recuperación.
    """

    def __init__(
        self,
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
        chat_label: str = "",
    ) -> None:
        self._workspace_dir = Path(workspace_dir)
        self._chat_label = chat_label
        logger.debug(
            "ContextoGenerator inicializado: workspace=%s, chat_label='%s'",
            self._workspace_dir.name, chat_label,
        )

    # -- API pública ------------------------------------------------

    def ejecutar(self) -> dict:
        """Ejecuta el flujo común de generación de contexto.

        Secuencia (Template Method):
        1. Extraer intercambios (abstracto — cada subclase lo implementa).
        2. Empaquetar en bloques (común — usa BlockPacker).
        3. Escribir bloques físicos al disco (común — usa BloqueGenerator).
        4. Actualizar metadata (común — usa MetadataManager).
        5. Actualizar índice (común — usa IndiceGenerator).
        6. Post-procesar (común — enriquecer, consolidar decisiones, normalizar).
        7. Si _debe_generar_recuperacion() es True, generar los 4 archivos
           (estado, decisiones, índice, bloques) vía RecoveryGenerator.

        Returns:
            Dict con: success, exchanges_count, blocks_count, files_count, error.
        """
        try:
            exchanges = self._extraer_intercambios()
            if not exchanges:
                logger.info("ContextoGenerator: sin intercambios, nada que hacer")
                return {"success": True, "exchanges_count": 0, "blocks_count": 0, "files_count": 0}

            # v6.7 F3: cachear intercambios y ultimo_timestamp ANTES de
            # actualizar metadata, para que _debe_generar_recuperacion() pueda
            # comparar los nuevos contra el último conocido (no contra sí mismos).
            self._intercambios_cache = exchanges
            self._ultimo_timestamp_previo = self._leer_ultimo_timestamp_previo()

            blocks = self._empaquetar(exchanges)
            self._escribir_bloques(blocks)
            self._actualizar_metadata(blocks, exchanges)
            self._actualizar_indice(blocks)
            self._post_procesar(blocks)

            files_count = 0
            if self._debe_generar_recuperacion():
                files_count = self._generar_archivos_recuperacion(exchanges, blocks)

            logger.info(
                "ContextoGenerator completado: %d intercambios, %d bloques, %d archivos recuperación",
                len(exchanges), len(blocks), files_count,
            )
            return {
                "success": True,
                "exchanges_count": len(exchanges),
                "blocks_count": len(blocks),
                "files_count": files_count,
            }
        except Exception as e:
            logger.exception("Error en ContextoGenerator.ejecutar()")
            return {"success": False, "error": str(e), "exchanges_count": 0, "blocks_count": 0, "files_count": 0}

    # -- Métodos abstractos (las subclases los implementan) --------

    @abstractmethod
    def _extraer_intercambios(self) -> list:
        """Extrae los intercambios desde la fuente correspondiente."""
        ...

    def _debe_generar_recuperacion(self) -> bool:
        """v6.7 F3: Hook basado en cronología (Principio 3).

        Los 4 archivos de recuperación (estado, decisiones, índice, objetivo)
        se generan cuando la información nueva permite identificar un "último
        intercambio" cronológico que sea el más reciente del contexto.

        No depende del origen (chat o externo), depende de:
        1. Si los intercambios nuevos tienen marca cronológica (timestamp > 0).
        2. Si son posteriores al ultimo_timestamp conocido en el metadata.

        Casos:
        - Caso 1 (chat incremental): cronológico + posterior → SÍ.
        - Caso 2 (chat recuperación completa): cronológico + posterior → SÍ.
        - Caso 3 (externo con timestamps, posterior): cronológico + posterior → SÍ.
        - Caso 4 (externo con timestamps, anterior): cronológico + NO posterior → NO.
        - Caso 5 (externo sin timestamps): NO cronológico → NO.

        Subclases pueden sobrescribir este hook para casos especiales.
        """
        intercambios = getattr(self, '_intercambios_cache', []) or []
        if not intercambios:
            return False

        # 1. Verificar si los intercambios tienen marca cronológica
        if not self._intercambios_tienen_marca_cronologica(intercambios):
            logger.info("v6.7 F3: sin marca cronológica → NO genera recuperación")
            return False

        # 2. Verificar si son posteriores al ultimo_timestamp conocido
        if not self._intercambios_son_posteriores_a_ultimo_timestamp(intercambios):
            logger.info("v6.7 F3: intercambios anteriores al último → NO genera recuperación")
            return False

        logger.info("v6.7 F3: cronológico + posterior → SÍ genera recuperación")
        return True

    def _intercambios_tienen_marca_cronologica(self, intercambios: list) -> bool:
        """v6.7 F3: Verifica si los intercambios tienen timestamps > 0."""
        for ex in intercambios:
            ts = getattr(ex, 'start_timestamp', 0) or getattr(ex, 'timestamp', 0) or 0
            if ts and ts > 0:
                return True
        return False

    def _leer_ultimo_timestamp_previo(self) -> float:
        """v6.7 F3: Lee el ultimo_timestamp del metadata ANTES de actualizarlo."""
        try:
            from contexto_zai.metadata.manager import MetadataManager
            mgr = MetadataManager(output_dir=self._workspace_dir)
            metadata = mgr.read()
            return metadata.ultimo_timestamp or 0
        except Exception:
            return 0

    def _intercambios_son_posteriores_a_ultimo_timestamp(self, intercambios: list) -> bool:
        """v6.7 F3: Compara el timestamp máximo de los nuevos contra el ultimo_timestamp previo."""
        ultimo_ts = getattr(self, '_ultimo_timestamp_previo', 0) or 0
        if ultimo_ts == 0:
            # No hay último timestamp conocido → los nuevos son los más recientes
            return True
        for ex in intercambios:
            ts = getattr(ex, 'start_timestamp', 0) or getattr(ex, 'timestamp', 0) or 0
            if ts and ts > ultimo_ts:
                return True
        return False

    # -- Métodos comunes (implementados en la base) -----------------

    def _empaquetar(self, exchanges: list) -> list[ThematicBlock]:
        from contexto_zai.processing.block_packer import BlockPacker
        packer = BlockPacker()
        blocks = packer.pack_from_exchanges(exchanges)
        logger.info("ContextoGenerator: %d intercambios → %d bloques", len(exchanges), len(blocks))
        return blocks

    def _escribir_bloques(self, blocks: list[ThematicBlock]) -> None:
        from contexto_zai.generation.bloque_generator import BloqueGenerator
        from contexto_zai.processing.content_cleaner import ContentCleaner

        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        gen = BloqueGenerator()
        cleaner = ContentCleaner()
        escritos = 0
        for block in blocks:
            content = gen.generate(block=block, cleaner=cleaner)
            path = self._workspace_dir / block.filename
            path.write_text(content, encoding="utf-8")
            escritos += 1
        logger.info("ContextoGenerator: %d bloques escritos en %s", escritos, self._workspace_dir)

    def _actualizar_metadata(self, blocks: list[ThematicBlock], exchanges: list) -> None:
        from contexto_zai.metadata.manager import MetadataManager
        from datetime import datetime, timezone

        mgr = MetadataManager(output_dir=self._workspace_dir)
        metadata = mgr.read()
        for block in blocks:
            for tema in block.temas:
                metadata.registrar_tema(tema, block.filename)
        if exchanges:
            timestamps = [getattr(ex, 'start_timestamp', 0) for ex in exchanges]
            timestamps = [t for t in timestamps if t > 0]
            if timestamps:
                metadata.ultimo_timestamp = max(timestamps)
            metadata.total_exchanges = len(exchanges)
        metadata.ultima_activacion = datetime.now(timezone.utc).isoformat()
        mgr.write(metadata)
        logger.info("ContextoGenerator: metadata actualizada")

    def _actualizar_indice(self, blocks: list[ThematicBlock]) -> None:
        from contexto_zai.generation.indice_generator import IndiceGenerator
        from contexto_zai.metadata.manager import MetadataManager

        indice_gen = IndiceGenerator()
        mgr = MetadataManager(output_dir=self._workspace_dir)
        metadata = mgr.read()

        content = indice_gen.generate(
            blocks=blocks,
            chat_label=self._chat_label or "Chat",
            metadata=metadata,
            workspace_dir=str(self._workspace_dir),
        )
        path = self._workspace_dir / "01_indice_recuperacion.md"
        path.write_text(content, encoding="utf-8")
        logger.info("ContextoGenerator: índice regenerado (%d chars)", len(content))

    def _post_procesar(self, blocks: list[ThematicBlock]) -> None:
        """Post-procesamiento común: enriquecer, consolidar decisiones, normalizar.

        Las importa de pipeline.py para no duplicar lógica.
        """
        try:
            from contexto_zai.pipeline import (
                _enriquecer_bloques_con_fallback,
                _consolidar_decisiones_llm,
                _normalizar_bloques_externos,
            )
            _enriquecer_bloques_con_fallback(
                blocks=blocks,
                workspace_dir=self._workspace_dir,
                chat_label=self._chat_label,
            )
            _consolidar_decisiones_llm(workspace_dir=self._workspace_dir)
            _normalizar_bloques_externos(workspace_dir=self._workspace_dir)
            logger.info("ContextoGenerator: post-procesamiento completado")
        except Exception as e:
            logger.warning("ContextoGenerator: error en post-procesamiento: %s", e)

    def _generar_archivos_recuperacion(
        self,
        exchanges: list,
        blocks: list[ThematicBlock],
    ) -> int:
        from contexto_zai.generation.recovery_generator import RecoveryGenerator
        from contexto_zai.metadata.manager import MetadataManager
        from contexto_zai.models import FileCategory

        mgr = MetadataManager(output_dir=self._workspace_dir)
        metadata = mgr.read()

        gen = RecoveryGenerator(workspace_dir=str(self._workspace_dir))
        recovery_files = gen.generate_all(
            exchanges=exchanges,
            blocks=blocks,
            chat_label=self._chat_label or "Chat",
            metadata=metadata,
            workspace_dir=str(self._workspace_dir),
        )

        escritos = 0
        for rf in recovery_files:
            if rf.category == FileCategory.BLOQUE:
                continue  # ya escrito
            path = self._workspace_dir / rf.filename
            path.write_text(rf.content, encoding="utf-8")
            escritos += 1
        logger.info("ContextoGenerator: %d archivos de recuperación escritos", escritos)
        return escritos

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(workspace={self._workspace_dir.name})"


if __name__ == "__main__":
    # Compatibilidad Windows: reconfigurar stdout/stderr a UTF-8
    import io as _io, sys as _sys
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
        if hasattr(_sys.stderr, 'buffer') and 'utf' not in (getattr(_sys.stderr, 'encoding', '') or '').lower():
            _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass
    print("=== Validacion de contexto_generator.py ===\n")

    import tempfile
    from contexto_zai.models import Exchange, Message, MessageRole

    # Test 1: ContextoGenerator es abstracta
    try:
        gen = ContextoGenerator(workspace_dir="/tmp/test")
        assert False, "Debería haber lanzado TypeError (clase abstracta)"
    except TypeError as e:
        assert "abstract" in str(e).lower() or "instantiat" in str(e).lower()
        print(f"[OK] ContextoGenerator es abstracta (no se instancia directo)")

    # Test 2: Subclase concreta mínima funciona
    class _GeneradorTest(ContextoGenerator):
        def __init__(self, workspace_dir, exchanges_mock):
            super().__init__(workspace_dir=workspace_dir, chat_label="Test")
            self._exchanges_mock = exchanges_mock
        def _extraer_intercambios(self):
            return self._exchanges_mock
        def _debe_generar_recuperacion(self):
            return False
        def _post_procesar(self, blocks):
            pass  # no invocar Worker Bun en tests

    with tempfile.TemporaryDirectory() as tmpdir:
        ex = Exchange(
            id=1,
            director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="test"),
            topic="test_tema",
            start_timestamp=1, end_timestamp=2,
        )
        gen = _GeneradorTest(workspace_dir=tmpdir, exchanges_mock=[ex])
        result = gen.ejecutar()
        assert result["success"] is True
        assert result["exchanges_count"] == 1
        bloque_path = Path(tmpdir) / "bloque_01.md"
        assert bloque_path.exists(), f"Bloque no escrito: {bloque_path}"
        assert (Path(tmpdir) / "_metadata.json").exists()
        assert (Path(tmpdir) / "01_indice_recuperacion.md").exists()
        assert not (Path(tmpdir) / "00_estado_actual.md").exists(), "No debería generar estado"
        print(f"[OK] Subclase concreta: ejecutar() escribe bloque + metadata + índice, sin estado")

    # Test 3: Subclase que SÍ genera recuperación
    class _GeneradorRecovery(ContextoGenerator):
        def __init__(self, workspace_dir, exchanges_mock):
            super().__init__(workspace_dir=workspace_dir, chat_label="Recovery")
            self._exchanges_mock = exchanges_mock
        def _extraer_intercambios(self):
            return self._exchanges_mock
        def _post_procesar(self, blocks):
            pass

    with tempfile.TemporaryDirectory() as tmpdir:
        ex = Exchange(
            id=1,
            director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="test"),
            topic="test_tema",
            start_timestamp=1, end_timestamp=2,
        )
        gen = _GeneradorRecovery(workspace_dir=tmpdir, exchanges_mock=[ex])
        result = gen.ejecutar()
        assert result["success"] is True
        assert (Path(tmpdir) / "00_estado_actual.md").exists(), "Debería generar estado"
        assert (Path(tmpdir) / "02_decisiones_clave.md").exists(), "Debería generar decisiones"
        print(f"[OK] Subclase recovery: genera estado + decisiones")

    # Test 4: repr
    class _GeneradorVacio(ContextoGenerator):
        def _extraer_intercambios(self):
            return []
    gen_repr = _GeneradorVacio(workspace_dir="/tmp/test_repr")
    assert "_GeneradorVacio" in repr(gen_repr)
    print(f"[OK] repr: {gen_repr!r}")

    print("\n[PASS] contexto_generator.py: todos los tests pasaron")
