# contexto_zai/process/recovery_cycle.py -- Ciclo de recuperacion completo: orquesta pasos 5-9 (extraccion -> clasificacion -> generacion).
"""Ciclo de recuperación completo (v3.2).

Coordina los pasos 5-9 del flujo de la spec:
5. Extracción de mensajes desde chat.z.ai.
6. Clasificación y empaquetado en bloques temáticos.
7. Generación de los 3 archivos (estado, índice, decisiones).
8. Subagente de estado actual (extrae contexto del tema activo).
9. Barrido por temas cuando sigue faltando contexto.

Es un script de dependencia: orquesta varios atómicos.
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
for _ in range(5):
    if _os.path.isdir(_os.path.join(_candidate, 'contexto_zai')):
        if _candidate not in _sys.path:
            _sys.path.insert(0, _candidate)
        break
    _candidate = _os.path.dirname(_candidate)
else:
    _parent = _os.path.dirname(_here)
    if _parent not in _sys.path:
        _sys.path.insert(0, _parent)

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from contexto_zai.client.auth_client import AuthClient
from contexto_zai.client.chat_client import ChatClient
from contexto_zai.config import DOWNLOAD_OUTPUT_DIR, WORKSPACE_OUTPUT_DIR
from contexto_zai.generation.recovery_generator import RecoveryGenerator
from contexto_zai.metadata.manager import MetadataManager
from contexto_zai.models import RecoveryFile
from contexto_zai.processing.block_packer import BlockPacker
from contexto_zai.processing.classifier import MessageClassifier
from contexto_zai.processing.exchange_builder import ExchangeBuilder
from contexto_zai.processing.subdivider import Subdivider
from contexto_zai.subagents.decisiones_subagent import DecisionesSubagent

logger = logging.getLogger(__name__)

@dataclass
class RecoveryCycleResult:
    """Resultado del ciclo de recuperación.

    Attributes:
        success: Si el ciclo completó sin errores.
        messages_count: Mensajes extraídos.
        exchanges_count: Intercambios construidos.
        blocks_count: Bloques generados.
        files_count: Archivos escritos.
        share_id: Share utilizado.
        error: Mensaje de error si falló.
    """

    success: bool
    messages_count: int = 0
    exchanges_count: int = 0
    blocks_count: int = 0
    files_count: int = 0
    share_id: str = ""
    error: str = ""

class RecoveryCycle:
    """Orquesta el ciclo completo de recuperación (pasos 5-9).

    Args:
        jwt: JWT del Director (para autenticación).
        chat_id: UUID interno del chat.
        workspace_dir: Directorio del workspace (donde viven los archivos).
        download_dir: Directorio de descarga (copia para el Director).
        decision_extractor: Extractor LLM de decisiones (opcional).

    Usage:
        >>> cycle = RecoveryCycle(jwt="...", chat_id="...")
        >>> result = cycle.run()
    """

    def __init__(
        self,
        jwt: str,
        chat_id: str,
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
        download_dir: Path | str = DOWNLOAD_OUTPUT_DIR,
        decision_extractor=None,
    ) -> None:
        self._jwt = jwt
        self._chat_id = chat_id
        self._workspace_dir = Path(workspace_dir)
        self._download_dir = Path(download_dir)
        self._decision_extractor = decision_extractor

        # Componentes atómicos (inyectados en constructor)
        self._exchange_builder = ExchangeBuilder()
        self._classifier = MessageClassifier()
        self._subdivider = Subdivider()
        self._packer = BlockPacker()
        self._recovery_gen = RecoveryGenerator(
            decisiones_generator=self._build_decisiones_generator(),
        )
        self._metadata_mgr = MetadataManager(output_dir=self._workspace_dir)

    def _build_decisiones_generator(self):
        """Construye el generador de decisiones con extractor real."""
        from contexto_zai.generation.decisiones_generator import DecisionesGenerator
        from contexto_zai.processing.decision_extractor import DecisionExtractor

        # Usar extractor real por defecto (v3.3)
        if self._decision_extractor:
            # Si se proporciona un extractor personalizado, usarlo
            if hasattr(self._decision_extractor, "extract"):
                extractor = self._decision_extractor.extract
            else:
                extractor = self._decision_extractor
        else:
            # Extractor real por defecto
            real_extractor = DecisionExtractor()
            extractor = real_extractor.extract

        return DecisionesGenerator(extractor=extractor)

    # -- API pública ------------------------------------------------

    def run(
        self,
        chat_label: str = "",
    ) -> RecoveryCycleResult:
        """Ejecuta el ciclo completo de recuperación.

        Args:
            chat_label: Etiqueta descriptiva del chat.

        Returns:
            RecoveryCycleResult con el resultado.
        """
        try:
            # PASO 5: Extracción de mensajes
            logger.info("Paso 5: Extrayendo mensajes...")
            with AuthClient(token=self._jwt) as auth:
                share_id = auth.create_share(self._chat_id)
            with ChatClient(token=self._jwt) as client:
                messages = client.extract_all(
                    share_id=share_id, chat_id=self._chat_id
                )

            if not messages:
                return RecoveryCycleResult(
                    success=False,
                    error="No se extrajeron mensajes del chat.",
                )

            logger.info(
                "Extraidos: %d mensajes (%d chars)",
                len(messages),
                sum(len(m.content) for m in messages),
            )

            # PASO 6: Clasificación y empaquetado
            logger.info("Paso 6: Clasificando y empaquetando...")
            exchanges = self._exchange_builder.build(messages)
            self._classifier.classify_exchanges(exchanges)

            # Agrupar por tema
            by_topic: dict = {}
            for ex in exchanges:
                by_topic.setdefault(ex.topic, []).append(ex)

            # Subdividir temas que superen el limite
            # Iterar hasta que ningun tema necesite subdivision (puede requerir varias pasadas)
            expanded: dict = {}
            for tema, exs in by_topic.items():
                if self._subdivider.needs_subdivision(tema, exs):
                    result = self._subdivider.subdivide(tema, exs)
                    for name, sub_exs in result.subtemas:
                        for ex in sub_exs:
                            ex.topic = name
                        expanded[name] = sub_exs
                else:
                    expanded[tema] = exs

            # Segunda pasada: verificar si algun subtema sigue necesitando subdivision
            # (puede ocurrir si la subdivision lexica genero subtemas con multiples intercambios grandes)
            max_pasadas = 5
            for pasada in range(max_pasadas):
                needs_more = False
                new_expanded: dict = {}
                for tema, exs in expanded.items():
                    if self._subdivider.needs_subdivision(tema, exs):
                        needs_more = True
                        result = self._subdivider.subdivide(tema, exs)
                        for name, sub_exs in result.subtemas:
                            for ex in sub_exs:
                                ex.topic = name
                            new_expanded[name] = sub_exs
                    else:
                        new_expanded[tema] = exs
                expanded = new_expanded
                if not needs_more:
                    break

            # Empaquetar en bloques por tamano
            blocks = self._packer.pack(expanded)

            # Actualizar metadata con mapeo tema->archivo
            metadata = self._metadata_mgr.read()
            metadata.chat_id = self._chat_id
            metadata.share_id = share_id
            metadata.total_exchanges = len(exchanges)
            for block in blocks:
                for tema in block.temas:
                    metadata.registrar_tema(tema, block.filename)
            metadata.ultimo_timestamp = max(
                m.timestamp for m in messages
            )
            from datetime import datetime, timezone
            metadata.ultima_activacion = datetime.now(timezone.utc).isoformat()
            self._metadata_mgr.write(metadata)

            # PASO 6b (v3.3): Detectar y versionar scripts
            logger.info("Paso 6b: Detectando scripts y construyendo grafos de cambios...")
            self._detect_and_version_scripts(exchanges)

            # PASO 7: Generación de los 3 archivos + bloques
            logger.info("Paso 7: Generando archivos de recuperacion...")
            recovery_files = self._recovery_gen.generate_all(
                exchanges=exchanges,
                blocks=blocks,
                chat_label=chat_label or self._chat_id[:8],
                metadata=metadata,
            )

            # PASO 8: (Subagente de estado actual) ya integrado en la generación
            # El estado_actual.md se genera con el contexto del tema del último exchange.
            # El subagente de estado se lanzaría en runtime para extraer contexto más rico,
            # pero la generación base del archivo se hace aquí.

            # PASO 9: (Barrido por temas) se lanza bajo demanda del agente,
            # no en este ciclo automático.

            # Escribir archivos en workspace y en download
            self._write_files(recovery_files, self._workspace_dir)
            self._write_files(recovery_files, self._download_dir)

            logger.info(
                "Ciclo completado: %d archivos, %d bloques, %d intercambios",
                len(recovery_files),
                len(blocks),
                len(exchanges),
            )

            return RecoveryCycleResult(
                success=True,
                messages_count=len(messages),
                exchanges_count=len(exchanges),
                blocks_count=len(blocks),
                files_count=len(recovery_files),
                share_id=share_id,
            )

        except Exception as e:
            logger.exception("Error en ciclo de recuperacion")
            return RecoveryCycleResult(success=False, error=str(e))

    # -- Métodos privados -------------------------------------------

    def _detect_and_version_scripts(self, exchanges: list) -> None:
        """Detecta scripts en los intercambios y construye grafos de cambios (v3.3).

        Para cada intercambio, usa CodeDetector para identificar scripts.
        Agrupa versiones del mismo script y construye un ChangeGraph
        con diffs forward y reverse.
        """
        try:
            from contexto_zai.processing.code_detector import CodeDetector
            from contexto_zai.processing.version_graph import VersionGraphBuilder
        except ImportError as e:
            logger.warning("CodeDetector o VersionGraph no disponibles: %s", e)
            return

        detector = CodeDetector()
        builder = VersionGraphBuilder()

        # Recopilar todas las versiones de cada script
        script_versions: dict[str, list[tuple[str, float, int, str]]] = {}

        for ex in exchanges:
            if not ex.agent_msgs:
                continue
            for msg in ex.agent_msgs:
                scripts = detector.detect_scripts(msg.content, exchange_id=ex.id)
                for script in scripts:
                    name = script.name
                    if name not in script_versions:
                        script_versions[name] = []
                    version_id = f"v{len(script_versions[name]) + 1}"
                    script_versions[name].append((
                        version_id,
                        msg.timestamp,
                        ex.id,
                        script.content,
                    ))

        # Construir y guardar grafos
        if script_versions:
            for name, versions in script_versions.items():
                graph = builder.build(name, versions)
                builder.save_graph(graph, self._workspace_dir)
                logger.info(
                    "Script '%s' versionado: %d versiones",
                    name, len(versions),
                )
        else:
            logger.info("No se detectaron scripts versionables en el chat")

    def _write_files(
        self,
        files: list[RecoveryFile],
        output_dir: Path,
    ) -> None:
        """Escribe los archivos de recuperación en el directorio."""
        output_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            file_path = output_dir / f.filename
            file_path.write_text(f.content, encoding="utf-8")
        logger.info("Escritos %d archivos en %s", len(files), output_dir)

    def __repr__(self) -> str:
        return f"RecoveryCycle(chat_id={self._chat_id[:8]}...)"

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
    # -- Validación interna de recovery_cycle.py (atómico standalone) --
    # Tests básicos de construcción e invariante.
    # Los tests de integración con API simulada están en tests/test_recovery_cycle.py
    print("=== Validacion de recovery_cycle.py ===\n")

    import tempfile
    from pathlib import Path

    # Test 1: construcción del ciclo con componentes inyectados
    with tempfile.TemporaryDirectory() as tmpdir:
        cycle = RecoveryCycle(
            jwt="fake-jwt",
            chat_id="fake-chat-id",
            workspace_dir=Path(tmpdir) / "workspace",
            download_dir=Path(tmpdir) / "download",
        )
        assert cycle._jwt == "fake-jwt"
        assert cycle._chat_id == "fake-chat-id"
        assert cycle._exchange_builder is not None
        assert cycle._classifier is not None
        assert cycle._packer is not None
        assert cycle._recovery_gen is not None
        assert cycle._metadata_mgr is not None
        print(f"[OK] Construccion con componentes inyectados")

    # Test 2: paths multiplataforma (no hardcodear /home/z/...)
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_dir = Path(tmpdir) / "workspace"
        dl_dir = Path(tmpdir) / "download"
        cycle = RecoveryCycle(
            jwt="fake-jwt",
            chat_id="fake-chat-id",
            workspace_dir=ws_dir,
            download_dir=dl_dir,
        )
        # Los paths deben ser objetos Path, no strings
        assert isinstance(cycle._workspace_dir, Path)
        assert isinstance(cycle._download_dir, Path)
        # En Windows, los paths deben usar backslashes automáticamente
        assert cycle._workspace_dir == ws_dir
        assert cycle._download_dir == dl_dir
        print(f"[OK] Paths multiplataforma (Path objects, no strings)")

    # Test 3: ResultType estructura correcta
    result = RecoveryCycleResult(success=True, messages_count=10, exchanges_count=5, blocks_count=3, files_count=8, share_id="abc")
    assert result.success
    assert result.messages_count == 10
    assert result.exchanges_count == 5
    assert result.blocks_count == 3
    assert result.files_count == 8
    assert result.share_id == "abc"
    print(f"[OK] RecoveryCycleResult: estructura correcta")

    # Test 4: repr
    cycle = RecoveryCycle(jwt="x", chat_id="abc-123-def")
    assert "abc-123" in repr(cycle)
    print(f"[OK] repr: {cycle!r}")

    print("\n[PASS] recovery_cycle.py: tests basicos pasaron")
    print("   Tests de integracion con API simulada: tests/test_recovery_cycle.py")
