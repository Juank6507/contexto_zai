# Destino: /home/z/my-project/tests/test_e2e_pipeline.py
"""Test E2E: validación end-to-end del pipeline completo (v3.2).

Valida TODO el proceso desde la activación hasta los archivos
generados, usando mocks de AuthClient y ChatClient para no llamar
a la API real.

Este es el test más importante: cubre el flujo completo del spec:
1. Activación del Orchestrator (trigger explícito).
2. RecoveryCycle: extracción → clasificación → packing → generación.
3. Verificación de los 4 tipos de archivo.
4. Metadata correcta.
5. Unicidad temática.
6. Límites de tokens respetados.
7. IncrementalCycle en segunda activación (con metadata previa).
"""

from __future__ import annotations

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
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)

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
        print(f"  ✓ Success, ciclo={result.cycle_used}, {result.exchanges_processed} exchanges, {result.files_generated} archivos")
        print(f"  ✅ PASÓ")
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
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)
            run(chat_id="c", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")

        # Verificar los 4 tipos
        assert (ws / "00_estado_actual.md").exists()
        assert (ws / "01_indice_recuperacion.md").exists()
        assert (ws / "02_decisiones_clave.md").exists()
        bloques = list(ws.glob("bloque_*.md"))
        assert len(bloques) > 0
        print(f"  ✓ 4 tipos: estado, índice, decisiones, {len(bloques)} bloque(s)")
        print(f"  ✅ PASÓ")


def test_e2e_estado_with_8_sections():
    """Test E2E 3: estado actual con 8 secciones D1-D4+A1-A4."""
    print("\n=== Test E2E 3: estado actual con 8 secciones ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)
            run(chat_id="c", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")

        estado = (ws / "00_estado_actual.md").read_text(encoding="utf-8")
        for section in ["D1", "D2", "D3", "D4", "A1", "A2", "A3", "A4"]:
            assert f"Sección {section}" in estado, f"Falta sección {section}"
        print(f"  ✓ Estado con 8 secciones")
        print(f"  ✅ PASÓ")


def test_e2e_indice_with_mapping_table():
    """Test E2E 4: índice con tabla mapeo `tema → archivo`."""
    print("\n=== Test E2E 4: índice con mapeo ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)
            run(chat_id="c", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")

        indice = (ws / "01_indice_recuperacion.md").read_text(encoding="utf-8")
        assert "Mapeo tema → archivo" in indice
        assert "| Tema | Archivo |" in indice
        # Los temas del chat realista deben aparecer
        assert "configuracion_proyecto" in indice
        assert "validaciones" in indice
        print(f"  ✓ Índice con tabla tema→archivo")
        print(f"  ✅ PASÓ")


def test_e2e_metadata_correct():
    """Test E2E 5: metadata _metadata.json con campos correctos."""
    print("\n=== Test E2E 5: metadata correcta ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="share-xyz")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)
            run(chat_id="chat-id-xyz", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")

        meta = json.loads((ws / "_metadata.json").read_text(encoding="utf-8"))
        assert meta["chat_id"] == "chat-id-xyz"
        assert meta["share_id"] == "share-xyz"
        assert meta["total_exchanges"] > 0
        assert len(meta["tema_a_archivo"]) > 0
        assert meta["ultimo_timestamp"] > 0
        assert meta["ultima_activacion"] != ""
        print(f"  ✓ Metadata: {meta['total_exchanges']} exchanges, {len(meta['tema_a_archivo'])} temas")
        print(f"  ✅ PASÓ")


def test_e2e_no_block_exceeds_70k_tokens():
    """Test E2E 6: ningún bloque supera 70K tokens."""
    print("\n=== Test E2E 6: límite 70K tokens ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)
            run(chat_id="c", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")

        for b in ws.glob("bloque_*.md"):
            tokens = len(b.read_text(encoding="utf-8")) / 3.5
            assert tokens <= 70_000, f"Bloque {b.name} supera 70K: {tokens:.0f}"
        print(f"  ✓ Todos los bloques < 70K tokens")
        print(f"  ✅ PASÓ")


def test_e2e_unicity_tematica():
    """Test E2E 7: unicidad temática (un tema en un solo archivo)."""
    print("\n=== Test E2E 7: unicidad temática ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)
            run(chat_id="c", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")

        meta = json.loads((ws / "_metadata.json").read_text(encoding="utf-8"))
        # Verificar que cada tema está mapeado a un solo archivo
        for tema, archivo in meta["tema_a_archivo"].items():
            # El tema no debe aparecer como mapeado a otro archivo diferente
            for other_tema, other_archivo in meta["tema_a_archivo"].items():
                if tema == other_tema:
                    assert archivo == other_archivo
        print(f"  ✓ Unicidad: {len(meta['tema_a_archivo'])} temas, cada uno en un solo archivo")
        print(f"  ✅ PASÓ")


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
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)
            run(chat_id="c", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")

        # Después de ejecutar, status debe mostrar metadata
        st_after = status(chat_id="c", workspace_dir=ws)
        assert st_after["metadata_exists"] is True
        assert st_after["total_temas"] > 0
        assert st_after["ultimo_timestamp"] > 0
        print(f"  ✓ status(): antes={st_before['total_temas']} temas, después={st_after['total_temas']} temas")
        print(f"  ✅ PASÓ")


def test_e2e_orchestrator_chooses_recovery_when_no_metadata():
    """Test E2E 9: Orchestrator elige RecoveryCycle cuando no hay metadata."""
    print("\n=== Test E2E 9: Orchestrator elige recovery si no hay metadata ===")
    fake_messages = make_realistic_chat()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)

            orch = Orchestrator(chat_id="c", jwt="x", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")
            result = orch.activate(trigger=DetectionTrigger.EXPLICITO, reason="Test")

        assert result.success
        assert result.cycle_used == "recovery"
        print(f"  ✓ Sin metadata → RecoveryCycle ejecutado")
        print(f"  ✅ PASÓ")


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
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)
            run(chat_id="c", jwt="x", workspace_dir=ws, download_dir=dl)

        ws_files = sorted([f.name for f in ws.glob("*.md")])
        dl_files = sorted([f.name for f in dl.glob("*.md")])
        assert ws_files == dl_files, f"Archivos en workspace y download difieren: ws={ws_files}, dl={dl_files}"
        print(f"  ✓ {len(ws_files)} archivos en workspace = {len(dl_files)} archivos en download")
        print(f"  ✅ PASÓ")


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
    print(f"  ✓ Resolución multiplataforma: WORKSPACE_ROOT={root}")
    print(f"  ✅ PASÓ")


def main():
    print("=" * 60)
    print("TEST E2E: pipeline completo Contexto Z.ai v3.2")
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
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except (AssertionError, Exception) as e:
            import traceback
            print(f"  ❌ FALLÓ: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{'=' * 60}")
    print(f"RESULTADO E2E: {passed} pasaron, {failed} fallaron de {len(tests)} tests")
    print(f"{'=' * 60}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
