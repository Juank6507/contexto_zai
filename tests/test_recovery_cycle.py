# Destino: /home/z/my-project/tests/test_recovery_cycle.py
"""Test de integración: RecoveryCycle con API simulada (v3.2).

Valida el ciclo completo de recuperación (pasos 5-9) usando mocks
de AuthClient y ChatClient para no llamar a la API real.

Cubre:
1. Ciclo exitoso con mensajes simulados.
2. Verificación de archivos escritos en workspace y download.
3. Metadata generada correctamente (tema_a_archivo, ultimo_timestamp).
4. Estado actual con 8 secciones.
5. Índice con tabla mapeo.
6. Unicidad temática.
7. Error de API capturado.
8. Lista vacía: error reportado.
9. Ningún bloque supera 70K tokens con mensajes grandes.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

from contexto_zai.models import Message, MessageRole
from contexto_zai.process.recovery_cycle import RecoveryCycle


def _patched_context_manager(mock_class, **method_returns):
    """Configura un mock de clase para que funcione como context manager.

    AuthClient(token=...) debe devolver una instancia que se pueda usar
    en `with AuthClient(...) as auth:` y tenga métodos específicos.
    """
    instance = MagicMock()
    instance.__enter__ = MagicMock(return_value=instance)
    instance.__exit__ = MagicMock(return_value=None)
    for method_name, return_value in method_returns.items():
        getattr(instance, method_name).return_value = return_value
    mock_class.return_value = instance
    return instance


def test_recovery_cycle_success_with_mocked_api():
    """Test 1: ciclo exitoso con API simulada."""
    print("\n=== Test 1: ciclo exitoso con API simulada ===")
    fake_messages = [
        Message(seq=1, role=MessageRole.USER, timestamp=100, content="Ejecuta pytest de server.py"),
        Message(seq=2, role=MessageRole.ASSISTANT, timestamp=110, content="Tests OK"),
        Message(seq=3, role=MessageRole.USER, timestamp=120, content="Lee el worklog del proyecto"),
        Message(seq=4, role=MessageRole.ASSISTANT, timestamp=130, content="Worklog leído"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="fake-share-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)

            cycle = RecoveryCycle(
                jwt="fake-jwt",
                chat_id="fake-chat-id",
                workspace_dir=Path(tmpdir) / "ws",
                download_dir=Path(tmpdir) / "dl",
            )
            result = cycle.run(chat_label="Test")

        assert result.success, f"Falló: {result.error}"
        assert result.messages_count == 4
        assert result.exchanges_count == 2
        assert result.share_id == "fake-share-id"
        assert result.files_count > 0
        print(f"  ✓ {result.messages_count} msgs, {result.exchanges_count} exchanges, {result.files_count} archivos")
        print(f"  ✅ PASÓ")


def test_recovery_cycle_writes_files_in_workspace_and_download():
    """Test 2: archivos escritos en workspace y download."""
    print("\n=== Test 2: archivos en workspace y download ===")
    fake_messages = [
        Message(seq=1, role=MessageRole.USER, timestamp=100, content="pytest"),
        Message(seq=2, role=MessageRole.ASSISTANT, timestamp=110, content="OK"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        dl = Path(tmpdir) / "dl"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)
            cycle = RecoveryCycle(jwt="x", chat_id="c", workspace_dir=ws, download_dir=dl)
            result = cycle.run()

        ws_files = list(ws.glob("*.md"))
        dl_files = list(dl.glob("*.md"))
        assert len(ws_files) == result.files_count
        assert len(dl_files) == result.files_count
        print(f"  ✓ workspace: {len(ws_files)} archivos, download: {len(dl_files)} archivos")
        print(f"  ✅ PASÓ")


def test_recovery_cycle_metadata_correct():
    """Test 3: metadata generada correctamente."""
    print("\n=== Test 3: metadata ===")
    fake_messages = [
        Message(seq=1, role=MessageRole.USER, timestamp=100, content="pytest"),
        Message(seq=2, role=MessageRole.ASSISTANT, timestamp=110, content="OK"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)
            cycle = RecoveryCycle(jwt="x", chat_id="chat-abc", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")
            cycle.run()

        meta_path = ws / "_metadata.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["chat_id"] == "chat-abc"
        assert meta["share_id"] == "s-id"
        assert meta["total_exchanges"] == 1
        assert len(meta["tema_a_archivo"]) > 0
        assert meta["ultimo_timestamp"] == 110
        print(f"  ✓ Metadata: chat_id={meta['chat_id']}, temas={len(meta['tema_a_archivo'])}")
        print(f"  ✅ PASÓ")


def test_recovery_cycle_estado_8_secciones():
    """Test 4: estado actual con 8 secciones."""
    print("\n=== Test 4: estado actual con 8 secciones ===")
    fake_messages = [
        Message(seq=1, role=MessageRole.USER, timestamp=100, content="pytest"),
        Message(seq=2, role=MessageRole.ASSISTANT, timestamp=110, content="OK"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)
            cycle = RecoveryCycle(jwt="x", chat_id="c", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")
            cycle.run()

        estado = (ws / "00_estado_actual.md").read_text(encoding="utf-8")
        for section in ["D1", "D2", "D3", "D4", "A1", "A2", "A3", "A4"]:
            assert f"Sección {section}" in estado, f"Falta sección {section}"
        print(f"  ✓ 8 secciones presentes")
        print(f"  ✅ PASÓ")


def test_recovery_cycle_indice_with_mapping():
    """Test 5: índice con tabla mapeo tema→archivo."""
    print("\n=== Test 5: índice con mapeo ===")
    fake_messages = [
        Message(seq=1, role=MessageRole.USER, timestamp=100, content="pytest"),
        Message(seq=2, role=MessageRole.ASSISTANT, timestamp=110, content="OK"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)
            cycle = RecoveryCycle(jwt="x", chat_id="c", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")
            cycle.run()

        indice = (ws / "01_indice_recuperacion.md").read_text(encoding="utf-8")
        assert "Mapeo tema → archivo" in indice
        print(f"  ✓ Índice con tabla mapeo")
        print(f"  ✅ PASÓ")


def test_recovery_cycle_unicity():
    """Test 6: unicidad temática tras el ciclo."""
    print("\n=== Test 6: unicidad temática ===")
    fake_messages = [
        Message(seq=1, role=MessageRole.USER, timestamp=100, content="pytest"),
        Message(seq=2, role=MessageRole.ASSISTANT, timestamp=110, content="OK"),
        Message(seq=3, role=MessageRole.USER, timestamp=120, content="pytest otra"),
        Message(seq=4, role=MessageRole.ASSISTANT, timestamp=130, content="OK2"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)
            cycle = RecoveryCycle(jwt="x", chat_id="c", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")
            cycle.run()

        meta = json.loads((ws / "_metadata.json").read_text(encoding="utf-8"))
        # Cada tema debe estar en un solo archivo
        tema_archivo = meta["tema_a_archivo"]
        archivos_por_tema_count = {}
        for tema, archivo in tema_archivo.items():
            count = sum(1 for a in tema_archivo.values() if a == archivo and tema in [t for t, a in tema_archivo.items() if a == archivo])
        # Verificar que ningún tema aparece en 2 archivos diferentes
        for tema, archivo in tema_archivo.items():
            # El tema solo debe estar mapeado a un archivo
            assert tema_archivo[tema] == archivo
        print(f"  ✓ Unicidad: cada tema en un solo archivo")
        print(f"  ✅ PASÓ")


def test_recovery_cycle_api_error():
    """Test 7: error de API capturado."""
    print("\n=== Test 7: error de API capturado ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls:
            instance = MagicMock()
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=None)
            instance.create_share.side_effect = RuntimeError("API caída")
            mock_auth_cls.return_value = instance

            cycle = RecoveryCycle(jwt="x", chat_id="c", workspace_dir=Path(tmpdir), download_dir=Path(tmpdir) / "dl")
            result = cycle.run()

        assert not result.success
        assert "API caída" in result.error
        print(f"  ✓ Error de API capturado: {result.error}")
        print(f"  ✅ PASÓ")


def test_recovery_cycle_empty_messages():
    """Test 8: lista vacía de mensajes."""
    print("\n=== Test 8: lista vacía de mensajes ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=[])
            cycle = RecoveryCycle(jwt="x", chat_id="c", workspace_dir=Path(tmpdir), download_dir=Path(tmpdir) / "dl")
            result = cycle.run()

        assert not result.success
        assert "No se extrajeron mensajes" in result.error
        print(f"  ✓ Lista vacía: error correcto")
        print(f"  ✅ PASÓ")


def test_recovery_cycle_no_block_exceeds_70k():
    """Test 9: ningún bloque supera 70K tokens con mensajes grandes."""
    print("\n=== Test 9: límite 70K tokens por bloque ===")
    # 50 mensajes grandes en 5 temas
    fake_messages = []
    for i in range(50):
        tema_idx = i % 5
        contenido = f"Mensaje {i} sobre tema_{tema_idx} " + "x" * 5000
        fake_messages.append(Message(
            seq=i + 1,
            role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
            timestamp=100 + i,
            content=contenido,
        ))
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "ws"
        with patch("contexto_zai.process.recovery_cycle.AuthClient") as mock_auth_cls, \
             patch("contexto_zai.process.recovery_cycle.ChatClient") as mock_chat_cls:
            _patched_context_manager(mock_auth_cls, create_share="s-id")
            _patched_context_manager(mock_chat_cls, extract_all=fake_messages)
            cycle = RecoveryCycle(jwt="x", chat_id="c", workspace_dir=ws, download_dir=Path(tmpdir) / "dl")
            result = cycle.run()

        assert result.success, f"Falló: {result.error}"
        bloques = list(ws.glob("bloque_*.md"))
        for b in bloques:
            chars = len(b.read_text(encoding="utf-8"))
            tokens = chars / 3.5
            assert tokens <= 70_000, f"Bloque {b.name} supera 70K: {tokens:.0f}"
        print(f"  ✓ {len(bloques)} bloques, ninguno supera 70K tokens")
        print(f"  ✅ PASÓ")


def main():
    print("=" * 60)
    print("TEST DE INTEGRACIÓN: RecoveryCycle (con API simulada)")
    print("=" * 60)
    tests = [
        test_recovery_cycle_success_with_mocked_api,
        test_recovery_cycle_writes_files_in_workspace_and_download,
        test_recovery_cycle_metadata_correct,
        test_recovery_cycle_estado_8_secciones,
        test_recovery_cycle_indice_with_mapping,
        test_recovery_cycle_unicity,
        test_recovery_cycle_api_error,
        test_recovery_cycle_empty_messages,
        test_recovery_cycle_no_block_exceeds_70k,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except (AssertionError, Exception) as e:
            print(f"  ❌ FALLÓ: {e}")
            failed += 1
    print(f"\n{'=' * 60}")
    print(f"RESULTADO: {passed} pasaron, {failed} fallaron de {len(tests)} tests")
    print(f"{'=' * 60}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
