# contexto_zai/process/recovery_cycle.py -- Ciclo de recuperacion completo: orquesta pasos 5-9 (extraccion -> clasificacion -> generacion).
"""Ciclo de recuperación completo (v3.4).

Coordina los pasos 5-9 del flujo de la spec:
5. Extracción de mensajes desde chat.z.ai.
6. Clasificación por capas y empaquetado en bloques temáticos.
   - Capa 1: léxica (MessageClassifier).
   - Capa 2: intención (IntentionClassifier, integrada en MessageClassifier).
   - Capa 3: subagente discriminador (DiscriminatorSubagent) cuando un tema
     sigue siendo demasiado grande después de Capas 1+2.
7. Generación de los 3 archivos (estado, índice, decisiones).
8. Subagente de estado actual (extrae contexto del tema activo).
9. Barrido por temas cuando sigue faltando contexto.

Es un script de dependencia: orquesta varios atómicos.
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
from contexto_zai.processing.attachment_detector import AttachmentDetector
from contexto_zai.processing.block_packer import BlockPacker
from contexto_zai.processing.classifier import MessageClassifier
from contexto_zai.processing.content_delegator import DocumentDelegator
from contexto_zai.processing.exchange_builder import ExchangeBuilder
from contexto_zai.processing.subdivider import Subdivider
from contexto_zai.subagents.decisiones_subagent import DecisionesSubagent
from contexto_zai.subagents.discriminator_subagent import DiscriminatorSubagent
from contexto_zai.subagents.documento_indexer_subagent import (
    DocumentoIndexResult,
    DocumentoIndexerSubagent,
)
from contexto_zai.subagents.launcher import SubagentLauncher

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
        temas_subdivididos: Lista de temas que fueron subdivididos por Capa 3.
        attachments_indexados: Lista de attachments indexados por subagente (v3.5).
    """

    success: bool
    messages_count: int = 0
    exchanges_count: int = 0
    blocks_count: int = 0
    files_count: int = 0
    share_id: str = ""
    error: str = ""
    temas_subdivididos: list[str] = None
    attachments_indexados: list = None

    def __post_init__(self):
        if self.temas_subdivididos is None:
            self.temas_subdivididos = []
        if self.attachments_indexados is None:
            self.attachments_indexados = []

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
        subagent_launcher: Optional[SubagentLauncher] = None,
        enable_capa3: bool = True,
        enable_attachments: bool = True,
    ) -> None:
        self._jwt = jwt
        self._chat_id = chat_id
        self._workspace_dir = Path(workspace_dir)
        self._download_dir = Path(download_dir)
        self._decision_extractor = decision_extractor
        self._enable_capa3 = enable_capa3
        self._enable_attachments = enable_attachments

        # Componentes atómicos (inyectados en constructor)
        # v3.5: ExchangeBuilder recibe delegator y attachments
        self._delegator = DocumentDelegator() if enable_attachments else None
        self._exchange_builder = ExchangeBuilder(delegator=self._delegator)
        self._classifier = MessageClassifier()
        self._subdivider = Subdivider()
        self._packer = BlockPacker()
        self._recovery_gen = RecoveryGenerator(
            decisiones_generator=self._build_decisiones_generator(),
        )
        self._metadata_mgr = MetadataManager(output_dir=self._workspace_dir)

        # Subagente discriminador (Capa 3) — se inicializa bajo demanda
        self._launcher = subagent_launcher
        self._discriminator: Optional[DiscriminatorSubagent] = None
        if enable_capa3:
            self._discriminator = DiscriminatorSubagent(
                launcher=subagent_launcher or SubagentLauncher(),
            )

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
                messages, raw_messages = client.extract_all_with_raw(
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

            # PASO 5b (v3.5): Detectar y procesar attachments
            attachments_indexados: list[DocumentoIndexResult] = []
            if self._enable_attachments:
                attachments_indexados = self._index_attachments(raw_messages)
                if attachments_indexados:
                    # Pasar attachments al ExchangeBuilder para que cree intercambios virtuales
                    attachments_objs = [att for att in attachments_indexados]  # placeholders
                    # Nota: el indexer ya creó el intercambio virtual internamente
                    logger.info(
                        "Paso 5b: %d attachments indexados",
                        len(attachments_indexados),
                    )

            # PASO 6: Clasificación por capas y empaquetado
            logger.info("Paso 6: Clasificando por capas (1=lexica, 2=intencion, 3=discriminador)...")
            exchanges = self._exchange_builder.build(messages)
            self._classifier.classify_exchanges(exchanges)

            # Agrupar por tema
            by_topic: dict = {}
            for ex in exchanges:
                by_topic.setdefault(ex.topic, []).append(ex)

            # CAPA 3 (v3.4): Subagente discriminador para temas grandes
            # que no fueron subdivididos por las Capas 1 y 2.
            temas_subdivididos_capa3: list[str] = []
            if self._enable_capa3 and self._discriminator is not None:
                by_topic = self._apply_capa3_discriminator(
                    by_topic, temas_subdivididos_capa3
                )

            # Subdividir temas que superen el limite (subdivision lexica por keyword)
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
                attachments_indexados=attachments_indexados,
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
                temas_subdivididos=temas_subdivididos_capa3,
                attachments_indexados=attachments_indexados,
            )

        except Exception as e:
            logger.exception("Error en ciclo de recuperacion")
            return RecoveryCycleResult(success=False, error=str(e))

    # -- Métodos privados -------------------------------------------

    def _index_attachments(self, raw_messages: dict) -> list[DocumentoIndexResult]:
        """Detecta y procesa attachments del chat (v3.5).

        Args:
            raw_messages: JSON crudo del batch endpoint.

        Returns:
            Lista de DocumentoIndexResult con los attachments indexados.
        """
        if not raw_messages:
            return []

        detector = AttachmentDetector()
        attachments = detector.detect_in_raw_messages(raw_messages)

        if not attachments:
            logger.info("No se detectaron attachments en el chat")
            return []

        logger.info("Detectados %d attachments para indexar", len(attachments))

        # Cliente para descargar attachments
        try:
            from contexto_zai.client.attachment_client import AttachmentClient
            att_client = AttachmentClient(token=self._jwt)
        except Exception as e:
            logger.warning("No se pudo inicializar AttachmentClient: %s", e)
            return []

        # Subagente indexador
        launcher = self._launcher or SubagentLauncher()
        indexer = DocumentoIndexerSubagent(
            launcher=launcher,
            attachment_client=att_client,
        )

        results: list[DocumentoIndexResult] = []
        for att in attachments:
            try:
                result = indexer.run(att)
                if result.success:
                    results.append(result)
                    logger.info(
                        "Attachment indexado: %s (%d temas, %d chars resumen)",
                        att.filename, len(result.temas_detectados),
                        len(result.resumen_breve),
                    )
                else:
                    logger.warning(
                        "Error indexando %s: %s", att.filename, result.error
                    )
            except Exception as e:
                logger.error("Excepción indexando %s: %s", att.filename, e)

        att_client.close()
        return results

    def _apply_capa3_discriminator(
        self,
        by_topic: dict,
        temas_subdivididos: list[str],
    ) -> dict:
        """Aplica la Capa 3 (subagente discriminador) a temas grandes.

        Para cada tema que siga siendo demasiado grande después de las
        Capas 1 (léxica) y 2 (intención), lanza el subagente discriminador
        que lee los intercambios y propone una subdivisión en temas
        específicos basándose en el contenido real.

        Args:
            by_topic: Diccionario tema -> lista de intercambios.
            temas_subdivididos: Lista donde se registran los temas subdivididos.

        Returns:
            Nuevo diccionario con los temas subdivididos aplicados.
        """
        if not self._discriminator:
            return by_topic

        new_by_topic: dict = {}
        for tema, exs in by_topic.items():
            # Solo subdividir si el tema es grande (> límite efectivo)
            # Y tiene al menos 4 intercambios (mínimo para discriminación útil)
            if not self._subdivider.needs_subdivision(tema, exs) or len(exs) < 4:
                new_by_topic[tema] = exs
                continue

            logger.info(
                "Capa 3: lanzando discriminador para tema '%s' (%d intercambios, %d tokens)",
                tema, len(exs), int(sum(e.estimated_tokens for e in exs)),
            )

            try:
                proposal = self._discriminator.run(tema=tema, exchanges=exs)
            except Exception as e:
                logger.warning(
                    "Capa 3 falló para tema '%s': %s. Manteniendo tema original.",
                    tema, e,
                )
                new_by_topic[tema] = exs
                continue

            if not proposal.is_valid:
                logger.info(
                    "Capa 3: tema '%s' no se subdividió (propuesta no válida: %s)",
                    tema, proposal.error or "sin subtemas suficientes",
                )
                new_by_topic[tema] = exs
                continue

            # Aplicar la subdivisión: reclasificar intercambios a los nuevos subtemas
            self._discriminator.apply(proposal, exs)
            temas_subdivididos.append(tema)

            # Reconstruir el diccionario con los nuevos subtemas
            for sub in proposal.subtemas:
                sub_exs = [ex for ex in exs if ex.topic == sub.tema]
                if sub_exs:
                    new_by_topic[sub.tema] = sub_exs
                    logger.info(
                        "  -> subtema '%s': %d intercambios",
                        sub.tema, len(sub_exs),
                    )

            logger.info(
                "Capa 3: tema '%s' subdividido en %d subtemas",
                tema, len(proposal.subtemas),
            )

        return new_by_topic

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

    # Test 5: Capa 3 integrada (DiscriminatorSubagent)
    # Verifica que el ciclo tiene el subagente discriminador cuando enable_capa3=True
    cycle_with_capa3 = RecoveryCycle(
        jwt="fake-jwt",
        chat_id="fake-chat-id",
        enable_capa3=True,
    )
    assert cycle_with_capa3._discriminator is not None
    assert cycle_with_capa3._enable_capa3 is True
    print(f"[OK] Capa 3 (DiscriminatorSubagent) integrado")

    # Test 6: Capa 3 desactivable
    cycle_no_capa3 = RecoveryCycle(
        jwt="fake-jwt",
        chat_id="fake-chat-id",
        enable_capa3=False,
    )
    assert cycle_no_capa3._discriminator is None
    assert cycle_no_capa3._enable_capa3 is False
    print(f"[OK] Capa 3 desactivable (enable_capa3=False)")

    # Test 7: _apply_capa3_discriminator con mock invoker
    from contexto_zai.subagents.launcher import SubagentLauncher
    from contexto_zai.models import Exchange, Message, MessageRole

    def mock_subdivider_valid(prompt: str) -> str:
        return """SUBTEMA: auth_jwt
DESCRIPCION: Autenticacion JWT
EXCHANGES: 1, 2, 3

SUBTEMA: validaciones_pytest
DESCRIPCION: Tests con pytest
EXCHANGES: 4, 5, 6"""

    launcher = SubagentLauncher(task_invoker=mock_subdivider_valid)
    cycle_mock = RecoveryCycle(
        jwt="x",
        chat_id="abc",
        subagent_launcher=launcher,
        enable_capa3=True,
    )

    # Crear 6 intercambios grandes (para forzar needs_subdivision=True)
    big_content = "x" * 100000  # ~28K tokens cada uno
    exchanges_mock = [
        Exchange(
            id=i,
            director_msg=Message(seq=i, role=MessageRole.USER, timestamp=float(i), content=big_content),
            topic="general",
            start_timestamp=float(i),
            end_timestamp=float(i+1),
        )
        for i in range(1, 7)
    ]
    by_topic = {"general": exchanges_mock}
    subdivididos: list[str] = []
    new_by_topic = cycle_mock._apply_capa3_discriminator(by_topic, subdivididos)

    assert "general" in subdivididos, f"general debe estar en subdivididos: {subdivididos}"
    assert "auth_jwt" in new_by_topic, f"auth_jwt debe estar en new_by_topic: {list(new_by_topic.keys())}"
    assert "validaciones_pytest" in new_by_topic
    # Los intercambios deben haber sido reclasificados
    assert exchanges_mock[0].topic == "auth_jwt"
    assert exchanges_mock[3].topic == "validaciones_pytest"
    print(f"[OK] _apply_capa3_discriminator: tema 'general' subdividido en {len(new_by_topic)} subtemas")

    # Test 8: _apply_capa3_discriminator no subdivide temas pequeños
    small_exchanges = [
        Exchange(
            id=i,
            director_msg=Message(seq=i, role=MessageRole.USER, timestamp=float(i), content="short"),
            topic="pequeno",
            start_timestamp=float(i),
            end_timestamp=float(i+1),
        )
        for i in range(1, 5)
    ]
    by_topic_small = {"pequeno": small_exchanges}
    subdivididos_small: list[str] = []
    new_by_topic_small = cycle_mock._apply_capa3_discriminator(by_topic_small, subdivididos_small)
    assert len(subdivididos_small) == 0, f"no debe subdividir: {subdivididos_small}"
    assert "pequeno" in new_by_topic_small
    print(f"[OK] _apply_capa3_discriminator: tema pequeño no se subdivide")

    # Test 9: _apply_capa3_discriminator no subdivide temas con <4 intercambios
    few_exchanges = [
        Exchange(
            id=i,
            director_msg=Message(seq=i, role=MessageRole.USER, timestamp=float(i), content=big_content),
            topic="general",
            start_timestamp=float(i),
            end_timestamp=float(i+1),
        )
        for i in range(1, 4)  # solo 3 intercambios
    ]
    by_topic_few = {"general": few_exchanges}
    subdivididos_few: list[str] = []
    new_by_topic_few = cycle_mock._apply_capa3_discriminator(by_topic_few, subdivididos_few)
    assert len(subdivididos_few) == 0, f"no debe subdividir con <4 exchanges: {subdivididos_few}"
    print(f"[OK] _apply_capa3_discriminator: <4 intercambios no se subdivide")

    # Test 10: RecoveryCycleResult con temas_subdivididos
    result_with_subdiv = RecoveryCycleResult(
        success=True,
        messages_count=30,
        exchanges_count=15,
        blocks_count=5,
        files_count=8,
        share_id="abc",
        temas_subdivididos=["general"],
    )
    assert result_with_subdiv.temas_subdivididos == ["general"]
    print(f"[OK] RecoveryCycleResult: temas_subdivididos = {result_with_subdiv.temas_subdivididos}")

    print("\n[PASS] recovery_cycle.py: tests basicos pasaron")
    print("   Tests de integracion con API simulada: tests/test_recovery_cycle.py")
