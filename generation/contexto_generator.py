# contexto_zai/generation/contexto_generator.py -- ContextoGenerator: clase base que unifica los caminos de generación de contexto (chat, otra sesión, fuente externa).
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

CÓMO LO HACE:
- definir_flujo_comun(): escribir bloques, actualizar metadata, regenerar
  índice, enriquecer bloques, consolidar decisiones LLM, normalizar nombres.
- generar_archivos_recuperacion(): invocar EstadoGenerator + DecisionesGenerator
  + RecoveryGenerator.generate_all() para escribir los 4 archivos.
- Las subclases implementan:
  * _extraer_intercambios() -> list[Exchange]
  * _debe_generar_recuperacion() -> bool (True para recovery/incremental,
    False para ampliar)

Atómico standalone: importa config, models, logging. No tiene dependencias
circulares con los ciclos (los ciclos lo usan a él, no al revés).
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
# Soporta Estructura A (<workspace>/contexto_zai/) y Estructura B (workspace=contexto_zai/)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
_package_root = None
for _ in range(10):
    if not _os.path.isfile(_os.path.join(_candidate, '__init__.py')):
        break  # salimos del paquete
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

    Usage (típico, desde una subclase):
        >>> class MiGenerador(ContextoGenerator):
        ...     def _extraer_intercambios(self):
        ...         return [...]  # implementación específica
        ...     def _debe_generar_recuperacion(self):
        ...         return True
        >>> gen = MiGenerador(workspace_dir="/path/to/ws")
        >>> resultado = gen.ejecutar()
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
            # 1. Extraer intercambios (abstracto)
            exchanges = self._extraer_intercambios()
            if not exchanges:
                logger.info("ContextoGenerator: sin intercambios, nada que hacer")
                return {"success": True, "exchanges_count": 0, "blocks_count": 0, "files_count": 0}

            # 2. Empaquetar en bloques (común)
            blocks = self._empaquetar(exchanges)

            # 3. Escribir bloques físicos (común)
            self._escribir_bloques(blocks)

            # 4. Actualizar metadata (común)
            self._actualizar_metadata(blocks, exchanges)

            # 5. Actualizar índice (común)
            self._actualizar_indice(blocks)

            # 6. Post-procesar (común)
            self._post_procesar(blocks)

            # 7. Generar archivos de recuperación (solo si aplica)
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
        """Extrae los intercambios desde la fuente correspondiente.

        Subclases concretas:
        - RecoveryCycle: extrae todo el chat de Z.ai.
        - IncrementalCycle: extrae solo los nuevos desde ultimo_timestamp.
        - AmpliarGenerator: extrae desde fuente externa (URL o archivo).

        Returns:
            Lista de Exchange con .topic asignado.
        """
        ...

    def _debe_generar_recuperacion(self) -> bool:
        """Hook: si True, genera los 4 archivos de recuperación.

        Default: True (recovery/incremental generan recuperación).
        AmpliarGenerator sobrescribe para devolver False (ampliación no
        genera recuperación, según spec v4.4 línea 36).
        """
        return True

    # -- Métodos comunes (implementados en la base) -----------------

    def _empaquetar(self, exchanges: list) -> list[ThematicBlock]:
        """Empaqueta intercambios en bloques secuenciales (común).

        Usa BlockPacker.pack_from_exchanges() que ya hace empaquetado
        secuencial con reempaquetado selectivo.
        """
        from contexto_zai.processing.block_packer import BlockPacker
        packer = BlockPacker()
        blocks = packer.pack_from_exchanges(exchanges)
        logger.info("ContextoGenerator: %d intercambios → %d bloques", len(exchanges), len(blocks))
        return blocks

    def _escribir_bloques(self, blocks: list[ThematicBlock]) -> None:
        """Escribe los bloques físicos al disco (común).

        Usa BloqueGenerator para generar el contenido canónico
        (# Bloque tematico: <temas>) y lo escribe en el workspace.
        """
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
        """Actualiza _metadata.json con el mapeo tema→archivo (común)."""
        from contexto_zai.metadata.manager import MetadataManager
        from datetime import datetime, timezone

        mgr = MetadataManager(output_dir=self._workspace_dir)
        metadata = mgr.read()
        for block in blocks:
            for tema in block.temas:
                metadata.registrar_tema(tema, block.filename)
        # Actualizar ultimo_timestamp si hay exchanges con timestamp
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
        """Regenera 01_indice_recuperacion.md (común).

        Usa IndiceGenerator. Pasa workspace_dir para que _find_tokens_for_tema
        pueda buscar bloques físicos si los ThematicBlock llegan sin exchanges.
        """
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

        Este método llama a las funciones de pipeline.py que ya existen:
        - _enriquecer_bloques_con_fallback (Worker Bun o subagentes)
        - _consolidar_decisiones_llm (decisiones del LLM → 02_decisiones_clave.md)
        - _normalizar_bloques_externos (renombrar bloque_externo_* a bloque_NN.md)

        Las importa de pipeline.py para no duplicar lógica.
        """
        try:
            # Importar de pipeline.py (las funciones ya existen ahí)
            from contexto_zai.pipeline import (
                _enriquecer_bloques_con_fallback,
                _consolidar_decisiones_llm,
                _normalizar_bloques_externos,
            )
            # Enriquecer bloques (Worker Bun o fallback a subagentes)
            _enriquecer_bloques_con_fallback(
                blocks=blocks,
                workspace_dir=self._workspace_dir,
                chat_label=self._chat_label,
            )
            # Consolidar decisiones del LLM
            _consolidar_decisiones_llm(workspace_dir=self._workspace_dir)
            # Normalizar nombres de bloques externos a bloque_NN.md
            _normalizar_bloques_externos(workspace_dir=self._workspace_dir)
            logger.info("ContextoGenerator: post-procesamiento completado")
        except Exception as e:
            logger.warning("ContextoGenerator: error en post-procesamiento: %s", e)

    def _generar_archivos_recuperacion(
        self,
        exchanges: list,
        blocks: list[ThematicBlock],
    ) -> int:
        """Genera los 4 archivos de recuperación (solo si _debe_generar_recuperacion).

        Invoca RecoveryGenerator.generate_all() y escribe los archivos en el
        workspace. Esto genera:
        - 00_estado_actual.md (EstadoGenerator desde último intercambio)
        - 01_indice_recuperacion.md (IndiceGenerator)
        - 02_decisiones_clave.md (DecisionesGenerator)
        - bloques físicos (BloqueGenerator)

        Returns:
            Número de archivos escritos.
        """
        from contexto_zai.generation.recovery_generator import RecoveryGenerator
        from contexto_zai.metadata.manager import MetadataManager

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

        # Escribir los archivos (excepto los bloques, que ya se escribieron en _escribir_bloques)
        escritos = 0
        from contexto_zai.models import FileCategory
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
    # -- Validación interna de contexto_generator.py (atómico standalone) --
    print("=== Validacion de contexto_generator.py ===\n")

    import tempfile
    from contexto_zai.models import Exchange, Message, MessageRole

    # Test 1: ContextoGenerator es abstracta — no se puede instanciar directo
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
            return False  # como AmpliarGenerator

        # Override _post_procesar para no invocar Worker Bun en tests
        def _post_procesar(self, blocks):
            pass

    with tempfile.TemporaryDirectory() as tmpdir:
        ex = Exchange(
            id=1,
            director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="test"),
            topic="test_tema",
            start_timestamp=1, end_timestamp=2,
        )
        gen = _GeneradorTest(workspace_dir=tmpdir, exchanges_mock=[ex])
        assert isinstance(gen, ContextoGenerator)
        assert gen._debe_generar_recuperacion() is False
        # Ejecutar debe producir bloques + metadata + índice
        result = gen.ejecutar()
        assert result["success"] is True
        assert result["exchanges_count"] == 1
        # El bloque debe existir en disco
        bloque_path = Path(tmpdir) / "bloque_01.md"
        assert bloque_path.exists(), f"Bloque no escrito: {bloque_path}"
        # El metadata debe existir
        assert (Path(tmpdir) / "_metadata.json").exists()
        # El índice debe existir
        assert (Path(tmpdir) / "01_indice_recuperacion.md").exists()
        # NO debe generar estado ni decisiones (porque _debe_generar_recuperacion=False)
        assert not (Path(tmpdir) / "00_estado_actual.md").exists(), "No debería generar estado"
        print(f"[OK] Subclase concreta: ejecutar() escribe bloque + metadata + índice, sin estado")

    # Test 3: Subclase que SÍ genera recuperación
    class _GeneradorRecovery(ContextoGenerator):
        def __init__(self, workspace_dir, exchanges_mock):
            super().__init__(workspace_dir=workspace_dir, chat_label="Recovery")
            self._exchanges_mock = exchanges_mock

        def _extraer_intercambios(self):
            return self._exchanges_mock

        # Override _post_procesar para no invocar Worker Bun en tests
        def _post_procesar(self, blocks):
            pass

        # _debe_generar_recuperacion default = True

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
        # Debe generar estado y decisiones
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
