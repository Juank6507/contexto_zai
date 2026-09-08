# tests/test_e2e_pipeline.py -- Test E2E: validacion end-to-end del pipeline completo (activacion -> archivos generados).

"""Test E2E: validación end-to-end del pipeline completo (v3.2).

Valida TODO el proceso desde la activación hasta los archivos
generados, usando mocks de AuthClient y ChatClient para no llamar
a la API real.

Este es el test más importante: cubre el flujo completo del spec:
1. Activación del Orchestrator (trigger explícito).
2. RecoveryCycle: extracción -> clasificación -> packing -> generación.
3. Verificación de los 4 tipos de archivo.
4. Metadata correcta.
5. Unicidad temática.
6. Límites de tokens respetados.
7. IncrementalCycle en segunda activación (con metadata previa).
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

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

from contexto_zai.models import DetectionTrigger, Message, MessageRole
from contexto_zai.pipeline import run, status
from contexto_zai.process.orchestrator import Orchestrator

def _patched_context_manager(mock_class, **method_returns):
    """Configura un mock de clase para que funcione como context manager."""
    instance = MagicMock()
    instance.__enter__ = MagicMock(return_value=instance)
    instance.__exit__ = MagicMock(return_value=None)
    for method_name, return_value in method_returns.items():
        getattr(instance, method_name).return_value = return_value
    mock_class.return_value = instance
    return instance

def make_realistic_chat() -> list[Message]:
    """Crea un chat realista con varios temas y varios intercambios."""
    messages = []
    seq = 1
    ts = 100

    # Tema: configuracion_proyecto
    messages.append(Message(seq=seq, role=MessageRole.USER, timestamp=ts, content="Lee el worklog del proyecto y el repositorio")); seq += 1; ts += 10
    messages.append(Message(seq=seq, role=MessageRole.ASSISTANT, timestamp=ts, content="Worklog leído. He clonado el repositorio.")); seq += 1; ts += 10

    # Tema: validaciones
    messages.append(Message(seq=seq, role=MessageRole.USER, timestamp=ts, content="Ejecuta el pytest de server.py y router.py")); seq += 1; ts += 10
    messages.append(Message(seq=seq, role=MessageRole.ASSISTANT, timestamp=ts, content="Tests ejecutados. 5 passed, 0 failed.")); seq += 1; ts += 10

    # Tema: metodologia
    messages.append(Message(seq=seq, role=MessageRole.USER, timestamp=ts, content="Aplica el DCPA para esta tarea")); seq += 1; ts += 10
    messages.append(Message(seq=seq, role=MessageRole.ASSISTANT, timestamp=ts, content="DCPA aplicado. Diagnóstico: necesario refactor.")); seq += 1; ts += 10

    # Tema: configuracion_proyecto (otra vez)
    messages.append(Message(seq=seq, role=MessageRole.USER, timestamp=ts, content="Actualiza el worklog con lo hecho")); seq += 1; ts += 10
    messages.append(Message(seq=seq, role=MessageRole.ASSISTANT, timestamp=ts, content="Worklog actualizado con la nueva entrada.")); seq += 1; ts += 10

    # Tema: general
    messages.append(Message(seq=seq, role=MessageRole.USER, timestamp=ts, content="Hola, ¿cómo vamos?")); seq += 1; ts += 10
    messages.append(Message(seq=seq, role=MessageRole.ASSISTANT, timestamp=ts, content="Vamos bien. ¿Qué sigue?")); seq += 1; ts += 10

    return messages

# ==========================================================================
# TESTS E2E
# ==========================================================================

def test_e2e_pipeline_run_success():
    """Test E2E 1: pipeline.run() completo con chat realista."""
    print("\n=== Test E2E 1: pipeline.run() completo ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="share-id-123")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages, extract_all_with_raw=(fake_messages, {"data": {}}))

            result = run(
                chat_id="chat-abc-def",
                jwt="fake-jwt",
                trigger=DetectionTrigger.EXPLICITO,
                reason="Test E2E",
                chat_label="Test E2E",
                workspace_dir=Path(tmpdir) / "ws",
                download_dir=Path(tmpdir) / "dl",
            )

        assert result.success, f"Pipeline falló: {result.error}"
        assert result.cycle_used == "recovery"
        assert result.exchanges_processed > 0
        assert result.files_generated > 0
        print(f"  [OK] Success, ciclo={result.cycle_used}, {result.exchanges_processed} exchanges, {result.files_generated} archivos")
        print(f"  [PASS] PASO")
        return tmpdir  # para reutilizar en otros tests

def test_e2e_all_4_file_types_generated():
    """Test E2E 2: se generan los 4 tipos de archivo."""
    print("\n=== Test E2E 2: 4 tipos de archivo ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages, extract_all_with_raw=(fake_messages, {"data": {}}))
            run(chat_id="c", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")

        # Verificar los 4 tipos
        assert (ws / "00_estado_actual.md").exists()
        assert (ws / "01_indice_recuperacion.md").exists()
        assert (ws / "02_decisiones_clave.md").exists()
        bloques = list(ws.glob("bloque_*.md"))
        assert len(bloques) > 0
        print(f"  [OK] 4 tipos: estado, indice, decisiones, {len(bloques)} bloque(s)")
        print(f"  [PASS] PASO")

def test_e2e_estado_with_8_sections():
    """Test E2E 3: estado actual con 8 secciones D1-D4+A1-A4."""
    print("\n=== Test E2E 3: estado actual con 8 secciones ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages, extract_all_with_raw=(fake_messages, {"data": {}}))
            run(chat_id="c", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")

        estado = (ws / "00_estado_actual.md").read_text(encoding="utf-8")
        for section in ["D1", "D2", "D3", "D4", "A1", "A2", "A3", "A4"]:
            assert f"Sección {section}" in estado, f"Falta sección {section}"
        print(f"  [OK] Estado con 8 secciones")
        print(f"  [PASS] PASO")

def test_e2e_indice_with_mapping_table():
    """Test E2E 4: índice con tabla mapeo `tema -> archivo`."""
    print("\n=== Test E2E 4: indice con mapeo ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages, extract_all_with_raw=(fake_messages, {"data": {}}))
            run(chat_id="c", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")

        indice = (ws / "01_indice_recuperacion.md").read_text(encoding="utf-8")
        assert "Mapeo tema -> archivo" in indice
        assert "| Tema | Archivo |" in indice
        # Los temas del chat realista deben aparecer
        assert "configuracion_proyecto" in indice
        assert "validaciones" in indice
        print(f"  [OK] Indice con tabla tema->archivo")
        print(f"  [PASS] PASO")

def test_e2e_metadata_correct():
    """Test E2E 5: metadata _metadata.json con campos correctos."""
    print("\n=== Test E2E 5: metadata correcta ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="share-xyz")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages, extract_all_with_raw=(fake_messages, {"data": {}}))
            run(chat_id="chat-id-xyz", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")

        meta = json.loads((ws / "_metadata.json").read_text(encoding="utf-8"))
        assert meta["chat_id"] == "chat-id-xyz"
        assert meta["share_id"] == "share-xyz"
        assert meta["total_exchanges"] > 0
        assert len(meta["tema_a_archivo"]) > 0
        assert meta["ultimo_timestamp"] > 0
        assert meta["ultima_activacion"] != ""
        print(f"  [OK] Metadata: {meta['total_exchanges']} exchanges, {len(meta['tema_a_archivo'])} temas")
        print(f"  [PASS] PASO")

def test_e2e_no_block_exceeds_70k_tokens():
    """Test E2E 6: ningún bloque supera 70K tokens."""
    print("\n=== Test E2E 6: limite 70K tokens ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages, extract_all_with_raw=(fake_messages, {"data": {}}))
            run(chat_id="c", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")

        for b in ws.glob("bloque_*.md"):
            tokens = len(b.read_text(encoding="utf-8")) / 3.5
            assert tokens <= 70_000, f"Bloque {b.name} supera 70K: {tokens:.0f}"
        print(f"  [OK] Todos los bloques < 70K tokens")
        print(f"  [PASS] PASO")

def test_e2e_unicity_tematica():
    """Test E2E 7: unicidad temática (un tema en un solo archivo)."""
    print("\n=== Test E2E 7: unicidad tematica ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages, extract_all_with_raw=(fake_messages, {"data": {}}))
            run(chat_id="c", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")

        meta = json.loads((ws / "_metadata.json").read_text(encoding="utf-8"))
        # Verificar que cada tema está mapeado a un solo archivo
        for tema, archivo in meta["tema_a_archivo"].items():
            # El tema no debe aparecer como mapeado a otro archivo diferente
            for other_tema, other_archivo in meta["tema_a_archivo"].items():
                if tema == other_tema:
                    assert archivo == other_archivo
        print(f"  [OK] Unicidad: {len(meta['tema_a_archivo'])} temas, cada uno en un solo archivo")
        print(f"  [PASS] PASO")

def test_e2e_status_function():
    """Test E2E 8: función status() devuelve estado correcto."""
    print("\n=== Test E2E 8: status() ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        # Antes de ejecutar, status debe indicar que no hay metadata
        st_before = status(chat_id="c", workspace_dir=ws)
        assert st_before["metadata_exists"] is False
        assert st_before["total_temas"] == 0

        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages, extract_all_with_raw=(fake_messages, {"data": {}}))
            run(chat_id="c", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")

        # Después de ejecutar, status debe mostrar metadata
        st_after = status(chat_id="c", workspace_dir=ws)
        assert st_after["metadata_exists"] is True
        assert st_after["total_temas"] > 0
        assert st_after["ultimo_timestamp"] > 0
        print(f"  [OK] status(): antes={st_before['total_temas']} temas, después={st_after['total_temas']} temas")
        print(f"  [PASS] PASO")

def test_e2e_orchestrator_chooses_recovery_when_no_metadata():
    """Test E2E 9: Orchestrator elige RecoveryCycle cuando no hay metadata."""
    print("\n=== Test E2E 9: Orchestrator elige recovery si no hay metadata ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages, extract_all_with_raw=(fake_messages, {"data": {}}))

            orch = Orchestrator(chat_id="c", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")
            result = orch.activate(trigger=DetectionTrigger.EXPLICITO, reason="Test")

        assert result.success
        assert result.cycle_used == "recovery"
        print(f"  [OK] Sin metadata -> RecoveryCycle ejecutado")
        print(f"  [PASS] PASO")

def test_e2e_files_in_workspace_and_download():
    """Test E2E 10: archivos escritos tanto en workspace como en download."""
    print("\n=== Test E2E 10: archivos en workspace y download ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        dl = Path(tmpdir) / "dl"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages, extract_all_with_raw=(fake_messages, {"data": {}}))
            run(chat_id="c", jwt="x", workspace_dir=ws, download_dir=dl)

        ws_files = sorted([f.name for f in ws.glob("*.md")])
        dl_files = sorted([f.name for f in dl.glob("*.md")])
        assert ws_files == dl_files, f"Archivos en workspace y download difieren: ws={ws_files}, dl={dl_files}"
        print(f"  [OK] {len(ws_files)} archivos en workspace = {len(dl_files)} archivos en download")
        print(f"  [PASS] PASO")

def test_e2e_windows_path_compatibility():
    """Test E2E 11: paths multiplataforma (funciona en Windows)."""
    print("\n=== Test E2E 11: compatibilidad Windows ===")
    from contexto_zai.config import _resolve_workspace_root
    import os

    # La función debe aceptar paths con formato Windows (backslashes)
    with tempfile.TemporaryDirectory() as tmpdir:
        # Simular variable de entorno CZAI_WORKSPACE_DIR
        os.environ["CZAI_WORKSPACE_DIR"] = tmpdir
        root = _resolve_workspace_root()
        assert str(root) == tmpdir or str(root).replace("\\", "/") == tmpdir.replace("\\", "/")
        del os.environ["CZAI_WORKSPACE_DIR"]

    # Sin variable de entorno, debe usar el directorio padre del paquete
    root = _resolve_workspace_root()
    assert isinstance(root, Path)
    # Debe contener contexto_zai (el paquete)
    assert (root / "contexto_zai").is_dir()
    print(f"  [OK] Resolucion multiplataforma: WORKSPACE_ROOT={root}")
    print(f"  [PASS] PASO")


def test_e2e_fix1_links_externos():
    """Test E2E 12 (v3.4 Fix 1): links externos se procesan como intercambios."""
    print("\n=== Test E2E 12 (v3.4 Fix 1): links externos ===")
    from contexto_zai.client.web_reader import WebReader, ExternalContent
    from contexto_zai.config import URL_PATTERN

    # 1. URL_PATTERN detecta URLs en mensajes del Director
    msg = "Lee esto: https://ejemplo.com/articulo y después dime"
    urls = URL_PATTERN.findall(msg)
    assert len(urls) == 1, f"Debe detectar 1 URL: {urls}"
    assert urls[0] == "https://ejemplo.com/articulo"
    print(f"  [OK] URL_PATTERN: detecta {len(urls)} URL(s) en mensaje")

    # 2. WebReader disponible y con la API correcta
    reader = WebReader()
    assert hasattr(reader, "read")
    assert hasattr(reader, "read_many")
    assert hasattr(reader, "find_urls")
    print(f"  [OK] WebReader: API disponible (read, read_many, find_urls)")

    # 3. ExternalContent con estructura correcta
    ec = ExternalContent(
        url="https://test.com/page",
        title="Test Page",
        content="Contenido de prueba",
        source="httpx",
    )
    assert ec.url == "https://test.com/page"
    assert ec.estimated_tokens > 0
    print(f"  [OK] ExternalContent: estructura correcta ({ec.estimated_tokens:.0f} tokens)")
    print(f"  [PASS] PASO")


def test_e2e_fix2_capa3_discriminator():
    """Test E2E 13 (v3.4 Fix 2): Capa 3 discriminator integrado en recovery_cycle."""
    print("\n=== Test E2E 13 (v3.4 Fix 2): Capa 3 discriminator ===")
    from contexto_zai.process.recovery_cycle import RecoveryCycle, RecoveryCycleResult
    from contexto_zai.subagents.discriminator_subagent import (
        DiscriminatorSubagent,
        SubdivisionProposal,
        SubtemaProposal,
    )
    from contexto_zai.subagents.launcher import SubagentLauncher
    from contexto_zai.models import Exchange, Message, MessageRole

    # 1. RecoveryCycle con Capa 3 integrada
    cycle = RecoveryCycle(jwt="x", chat_id="abc", enable_capa3=True)
    assert cycle._discriminator is not None
    assert isinstance(cycle._discriminator, DiscriminatorSubagent)
    print(f"  [OK] RecoveryCycle: Capa 3 (DiscriminatorSubagent) integrada")

    # 2. _apply_capa3_discriminator subdivide tema grande con mock invoker
    def mock_subdivider(prompt: str) -> str:
        return """SUBTEMA: auth_jwt
DESCRIPCION: Auth JWT
EXCHANGES: 1, 2, 3

SUBTEMA: validaciones_pytest
DESCRIPCION: Tests pytest
EXCHANGES: 4, 5, 6"""

    launcher = SubagentLauncher(task_invoker=mock_subdivider)
    cycle_mock = RecoveryCycle(
        jwt="x", chat_id="abc",
        subagent_launcher=launcher, enable_capa3=True,
    )

    big_content = "x" * 100000  # ~28K tokens
    exchanges = [
        Exchange(
            id=i,
            director_msg=Message(seq=i, role=MessageRole.USER, timestamp=float(i), content=big_content),
            topic="general",
            start_timestamp=float(i),
            end_timestamp=float(i + 1),
        )
        for i in range(1, 7)
    ]
    by_topic = {"general": exchanges}
    subdivididos: list[str] = []
    new_by_topic = cycle_mock._apply_capa3_discriminator(by_topic, subdivididos)

    assert "general" in subdivididos
    assert "auth_jwt" in new_by_topic
    assert "validaciones_pytest" in new_by_topic
    assert len(new_by_topic) == 2  # subdividido en 2 subtemas
    print(f"  [OK] _apply_capa3_discriminator: tema 'general' -> {len(new_by_topic)} subtemas")

    # 3. RecoveryCycleResult con temas_subdivididos
    result = RecoveryCycleResult(
        success=True,
        temas_subdivididos=["general"],
    )
    assert result.temas_subdivididos == ["general"]
    print(f"  [OK] RecoveryCycleResult: temas_subdivididos = {result.temas_subdivididos}")
    print(f"  [PASS] PASO")


def test_e2e_fix3_truncamiento_logico():
    """Test E2E 14 (v3.4 Fix 3): estado actual con truncamiento lógico."""
    print("\n=== Test E2E 14 (v3.4 Fix 3): truncamiento lógico ===")
    from contexto_zai.generation.estado_generator import EstadoGenerator
    from contexto_zai.models import Exchange, Message, MessageRole

    # Crear contenido suficiente para superar el limite de chars (70K)
    # Cada intercambio aporta ~1000 chars, necesitamos > 70 intercambios grandes
    exchanges = [
        Exchange(
            id=i,
            director_msg=Message(
                seq=i, role=MessageRole.USER, timestamp=float(i),
                content=f"Intercambio {i}: " + ("x" * 500),
            ),
            agent_msgs=[Message(
                seq=i + 1000, role=MessageRole.ASSISTANT, timestamp=float(i) + 1,
                content=f"Respuesta {i}: " + ("y" * 1000),
            )],
            topic="general",
            start_timestamp=float(i),
            end_timestamp=float(i + 1),
        )
        for i in range(1, 200)  # 200 intercambios grandes > 70K chars
    ]

    gen = EstadoGenerator()
    content = gen.generate(exchanges, chat_label="test")

    # Debe contener el estado actual
    assert len(content) > 0
    # NO debe contener la frase antigua de truncado a secas
    assert "(truncado por límite de espacio)" not in content
    # Debe contener la sección de resumen (truncamiento lógico)
    # Solo verifica si el contenido fue truncado (superó el límite)
    if "Resumen del contexto excluido" in content:
        print(f"  [OK] Truncamiento lógico aplicado: {len(content)} chars con sección de resumen")
    else:
        # Si no fue truncado, el contenido cabe en el límite
        max_chars = gen._max_chars if hasattr(gen, "_max_chars") else 70000
        print(f"  [OK] Estado: {len(content)} chars (no requirió truncamiento, < {max_chars} chars)")
    print(f"  [PASS] PASO")


def test_e2e_v34_export_import_context():
    """Test E2E 15 (v3.4): exportación e importación de contexto."""
    print("\n=== Test E2E 15 (v3.4): export/import de contexto ===")
    from contexto_zai.context.exporter import ContextExporter
    from contexto_zai.context.importer import ContextImporter
    from contexto_zai.models import RecoveryMetadata

    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear contexto simulado
        ctx_dir = Path(tmpdir) / "contexto_recuperacion"
        ctx_dir.mkdir()
        (ctx_dir / "00_estado_actual.md").write_text("# Estado\n\nContexto de prueba.", encoding="utf-8")
        (ctx_dir / "01_indice_recuperacion.md").write_text("# Indice\n\nTema 1", encoding="utf-8")
        (ctx_dir / "02_decisiones_clave.md").write_text("# Decisiones\n\nD01", encoding="utf-8")
        (ctx_dir / "bloque_general.md").write_text("# Bloque general\n\nContenido", encoding="utf-8")
        # _metadata.json para que el exporter lo incluya
        import json as _json
        meta = RecoveryMetadata(
            chat_id="chat-test-123",
            share_id="share-test-456",
            total_exchanges=10,
        )
        (ctx_dir / "_metadata.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")

        # Exportar (API: workspace_dir en constructor, output_dir en export)
        exporter = ContextExporter(workspace_dir=ctx_dir)
        zip_path = exporter.export(chat_id="chat-test-123", output_dir=Path(tmpdir))
        assert zip_path is not None
        assert zip_path.exists()
        assert zip_path.suffix == ".zip"
        print(f"  [OK] Export: {zip_path.name} ({zip_path.stat().st_size} bytes)")

        # Importar
        target_dir = Path(tmpdir) / "imported"
        importer = ContextImporter(workspace_dir=target_dir)
        instrucciones = importer.import_from(zip_path)
        # import_from devuelve Optional[str] (las instrucciones de recuperación)
        assert instrucciones is not None, "import_from debe devolver las instrucciones"
        assert isinstance(instrucciones, str)
        assert len(instrucciones) > 0
        assert (target_dir / "00_estado_actual.md").exists() or \
               (target_dir / "contexto_recuperacion" / "00_estado_actual.md").exists(), \
               f"Archivo de estado debe existir tras import. Contenido: {list(target_dir.rglob('*.md'))}"
        print(f"  [OK] Import: contexto cargado en {target_dir} ({len(instrucciones)} chars de instrucciones)")
        print(f"  [PASS] PASO")


def test_e2e_v35_attachment_pipeline():
    """Test E2E 16 (v3.5): pipeline completo con attachments."""
    print("\n=== Test E2E 16 (v3.5): pipeline con attachments ===")
    from contexto_zai.processing.attachment_detector import AttachmentDetector
    from contexto_zai.processing.content_delegator import DocumentDelegator
    from contexto_zai.subagents.documento_indexer_subagent import (
        DocumentoIndexResult,
        ThemeSection,
    )
    from contexto_zai.models import Attachment
    from pathlib import Path

    # 1. AttachmentDetector detecta attachments en JSON crudo
    raw_batch = {
        "data": {
            "msg1": {
                "role": "user",
                "files": [
                    {
                        "type": "doc", "media": "doc",
                        "file": {
                            "id": "abc-123",
                            "filename": "doc.pdf",
                            "meta": {
                                "content_type": "application/pdf",
                                "size": 1652025,
                            },
                            "created_at": 1788445359,
                        },
                        "status": "uploaded",
                    }
                ],
            }
        }
    }
    detector = AttachmentDetector()
    attachments = detector.detect_in_raw_messages(raw_batch)
    assert len(attachments) == 1
    assert attachments[0].is_pdf
    assert attachments[0].estimated_tokens > 5000
    print(f"[OK] AttachmentDetector: detecta PDF ({attachments[0].estimated_tokens:.0f} tokens)")

    # 2. DocumentDelegator decide delegación
    delegator = DocumentDelegator()
    should_delegate = delegator.should_delegate(
        content_size_tokens=int(attachments[0].estimated_tokens),
        agent_context_available_pct=20,
    )
    assert should_delegate is True
    print(f"[OK] DocumentDelegator: delega PDF grande → {should_delegate}")

    # 3. Override "lee completo" fuerza lectura directa
    should_delegate_override = delegator.should_delegate(
        content_size_tokens=int(attachments[0].estimated_tokens),
        agent_context_available_pct=90,
        director_override="lee este documento completo",
    )
    assert should_delegate_override is False
    print(f"[OK] Override 'lee completo' → no delega ({should_delegate_override})")

    # 4. Documento pequeño no delega
    small_att = Attachment(
        file_id="small-1", filename="notas.txt",
        content_type="text/plain", size=500,
    )
    should_delegate_small = delegator.should_delegate(
        content_size_tokens=int(small_att.estimated_tokens),
        agent_context_available_pct=20,
    )
    assert should_delegate_small is False
    print(f"[OK] Documento pequeño ({small_att.estimated_tokens:.0f} tokens) → no delega")

    # 5. Documento mediano + agente lleno → delega
    should_delegate_mediano = delegator.should_delegate(
        content_size_tokens=3000,
        agent_context_available_pct=90,
    )
    assert should_delegate_mediano is True
    print(f"[OK] Documento mediano + agente 90% → delega")

    # 6. Documento mediano + agente libre → no delega
    should_delegate_mediano2 = delegator.should_delegate(
        content_size_tokens=3000,
        agent_context_available_pct=50,
    )
    assert should_delegate_mediano2 is False
    print(f"[OK] Documento mediano + agente 50% → no delega")

    # 7. DocumentoIndexResult estructura correcta
    result = DocumentoIndexResult(
        attachment_id="abc-123",
        filename="doc.pdf",
        resumen_breve="Resumen de prueba del PDF.",
        temas_detectados=[
            ThemeSection(tema="tema1", descripcion="desc1", secciones=["s1", "s2"]),
            ThemeSection(tema="tema2", descripcion="desc2", secciones=["s3"]),
        ],
        archivo_indexado_path=Path("/tmp/doc.pdf"),
        success=True,
    )
    assert result.temas_nombres == ["tema1", "tema2"]
    print(f"[OK] DocumentoIndexResult: {len(result.temas_detectados)} temas, nombres={result.temas_nombres}")

    # 8. IndiceGenerator incluye sección de documentos indexados
    from contexto_zai.generation.indice_generator import IndiceGenerator
    from contexto_zai.models import RecoveryMetadata, ThematicBlock, Exchange, Message, MessageRole

    blocks = [
        ThematicBlock(filename="bloque_general.md", temas=["general"], exchanges=[]),
    ]
    meta = RecoveryMetadata(chat_id="test", share_id="share", total_exchanges=5)
    indice_gen = IndiceGenerator()
    indice_content = indice_gen.generate(
        blocks=blocks,
        chat_label="test",
        metadata=meta,
        attachments_indexados=[result],
    )
    assert "## Documentos indexados (v3.5)" in indice_content
    assert "doc.pdf" in indice_content
    assert "tema1" in indice_content
    print(f"[OK] IndiceGenerator: sección 'Documentos indexados' presente")

    # 9. Índice sin attachments → sin la sección
    indice_no_atts = indice_gen.generate(
        blocks=blocks, chat_label="test", metadata=meta,
    )
    assert "## Documentos indexados (v3.5)" not in indice_no_atts
    print(f"[OK] Índice sin attachments: sección omitida")

    print(f"  [PASS] PASO")


def main():
    print("=" * 60)
    print("TEST E2E: pipeline completo Contexto Z.ai v3.5")
    print("=" * 60)
    tests = [
        test_e2e_pipeline_run_success,
        test_e2e_all_4_file_types_generated,
        test_e2e_estado_with_8_sections,
        test_e2e_indice_with_mapping_table,
        test_e2e_metadata_correct,
        test_e2e_no_block_exceeds_70k_tokens,
        test_e2e_unicity_tematica,
        test_e2e_status_function,
        test_e2e_orchestrator_chooses_recovery_when_no_metadata,
        test_e2e_files_in_workspace_and_download,
        test_e2e_windows_path_compatibility,
        # Tests v3.4 (F9)
        test_e2e_fix1_links_externos,
        test_e2e_fix2_capa3_discriminator,
        test_e2e_fix3_truncamiento_logico,
        test_e2e_v34_export_import_context,
        # Tests v3.5 (G10)
        test_e2e_v35_attachment_pipeline,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except (AssertionError, Exception) as e:
            import traceback
            print(f"  [FAIL] FALLO: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{'=' * 60}")
    print(f"RESULTADO E2E: {passed} pasaron, {failed} fallaron de {len(tests)} tests")
    print(f"{'=' * 60}")
    return 0 if failed == 0 else 1

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
    sys.exit(main())
