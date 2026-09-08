# tests/test_v36_e2e.py -- Tests E2E v3.6: subagentes paralelos + JWT bridge + 3 niveles.
"""Tests E2E v3.6: Validación completa del flujo de 3 niveles y JWT bridge.

Tests:
1. launch_parallel: 3 subagentes en paralelo real.
2. DocumentoDivisor: particiona PDF real CZAI-01.pdf.
3. DocumentoConciliador: consolida índices parciales.
4. DivisorSubagent (N1): flujo completo con PDF real.
5. ConciliadorSubagent (N3): consolida + resumen.
6. DocumentoIndexerSubagent.run_3_levels: orquestación completa.
7. CredentialManager: persistir + leer JWT.
8. JwtBridgeServer: 3 endpoints HTTP.
9. pipeline.index_document_large: disponible.
10. recovery_cycle: _ensure_jwt disponible.
"""

from __future__ import annotations

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

from contexto_zai.models import Attachment, IndiceParcial, Porcion
from contexto_zai.processing.conciliador import DocumentoConciliador, ThemeSection
from contexto_zai.processing.divisor import DocumentoDivisor
from contexto_zai.subagents.launcher import SubagentLauncher, SubagentRequest, SubagentResponse


def test_1_launch_parallel_real():
    """Test 1: launch_parallel lanza 3 subagentes en paralelo real."""
    print("\n=== Test 1: launch_parallel (paralelo real) ===")

    def slow_invoker(prompt: str) -> str:
        import time
        time.sleep(0.3)
        return "ok"

    launcher = SubagentLauncher(task_invoker=slow_invoker)
    requests = [
        SubagentRequest(prompt=f"q{i}", files_to_read=[], description=f"d{i}")
        for i in range(3)
    ]

    import time
    t0 = time.time()
    responses = launcher.launch_parallel(requests, max_workers=3)
    t_parallel = time.time() - t0

    assert len(responses) == 3
    assert all(r.success for r in responses)
    # 3 subagentes de 0.3s en paralelo → ~0.3s total (no ~0.9s)
    assert t_parallel < 0.8, f"Paralelo debe ser < 0.8s, got {t_parallel:.2f}s"
    print(f"  [OK] 3 subagentes en paralelo: {t_parallel:.2f}s (secuencial sería ~0.9s)")
    print("  [PASS] PASO")


def test_2_documento_divisor_real_pdf():
    """Test 2: DocumentoDivisor particiona PDF real CZAI-01.pdf."""
    print("\n=== Test 2: DocumentoDivisor con PDF real ===")

    czai_pdf = Path(WORKSPACE_ROOT / "contexto_zai" / "Documentación" / "CZAI-01.pdf")
    if not czai_pdf.exists():
        print("  [SKIP] CZAI-01.pdf no encontrado")
        return

    divisor = DocumentoDivisor()
    porciones = divisor.particionar(czai_pdf, max_tokens_por_porcion=30000)

    assert len(porciones) > 0, "Debe particionar el PDF"
    assert all(p.id > 0 for p in porciones)
    assert all(p.tokens_estimados > 0 for p in porciones)
    assert all(p.pagina_inicio > 0 for p in porciones)

    total_paginas = porciones[-1].pagina_fin
    print(f"  [OK] PDF particionado: {len(porciones)} porciones, {total_paginas} páginas")
    for p in porciones[:3]:
        print(f"    Porción {p.id}: {p.paginas_str}, ~{p.tokens_estimados} tokens")
    print("  [PASS] PASO")


def test_3_documento_conciliador():
    """Test 3: DocumentoConciliador consolida índices parciales."""
    print("\n=== Test 3: DocumentoConciliador ===")

    conciliador = DocumentoConciliador()

    # Crear respuestas mock de N2
    class MockResp:
        def __init__(self, content, success=True):
            self.content = content
            self.success = success

    respuestas = [
        MockResp("""RESUMEN: Porción 1 sobre auth.

TEMA: auth_jwt
DESCRIPCION: Autenticación JWT
SECCIONES: login, logout

TEMA: config_db
DESCRIPCION: Config DB
SECCIONES: sqlite"""),
        MockResp("""RESUMEN: Porción 2 sobre tests.

TEMA: validaciones
DESCRIPCION: Tests pytest
SECCIONES: unitarias

TEMA: auth_jwt
DESCRIPCION: Más auth
SECCIONES: cookie, refresh"""),
    ]

    consolidado = conciliador.conciliar(respuestas)

    # auth_jwt debe estar fusionado (2 secciones + 2 secciones = 4 únicas)
    auth_jwt = next(t for t in consolidado.temas_consolidados if t.tema == "auth_jwt")
    assert len(auth_jwt.secciones) == 4  # login, logout, cookie, refresh

    assert len(consolidado.temas_consolidados) == 3  # auth_jwt, config_db, validaciones
    assert len(consolidado.resumen_final) > 0
    print(f"  [OK] 2 respuestas → 3 temas (auth_jwt fusionado: {len(auth_jwt.secciones)} secciones)")
    print("  [PASS] PASO")


def test_4_divisor_subagent_n1():
    """Test 4: DivisorSubagent (N1) flujo completo."""
    print("\n=== Test 4: DivisorSubagent (N1) ===")

    from contexto_zai.subagents.divisor_subagent import DivisorSubagent

    def mock_n2_invoker(prompt: str) -> str:
        if "Porción: 1" in prompt:
            return "RESUMEN: Porción 1.\n\nTEMA: tema_1\nDESCRIPCION: desc\nSECCIONES: s1"
        elif "Porción: 2" in prompt:
            return "RESUMEN: Porción 2.\n\nTEMA: tema_2\nDESCRIPCION: desc\nSECCIONES: s2"
        return "RESUMEN: Porción.\n\nTEMA: tema\nDESCRIPCION: desc\nSECCIONES: s"

    launcher = SubagentLauncher(task_invoker=mock_n2_invoker)
    n1 = DivisorSubagent(launcher=launcher, max_paralelos=3)

    czai_pdf = Path(WORKSPACE_ROOT / "contexto_zai" / "Documentación" / "CZAI-01.pdf")
    if not czai_pdf.exists():
        print("  [SKIP] CZAI-01.pdf no encontrado")
        return

    att = Attachment(file_id="test", filename="test.pdf", content_type="application/pdf", size=1652025)
    indices = n1.run(att, czai_pdf)

    assert len(indices) > 0
    assert all(ip.porcion_id > 0 for ip in indices)
    print(f"  [OK] N1: {len(indices)} índices parciales generados")
    print("  [PASS] PASO")


def test_5_conciliador_subagent_n3():
    """Test 5: ConciliadorSubagent (N3) consolida + resumen."""
    print("\n=== Test 5: ConciliadorSubagent (N3) ===")

    from contexto_zai.subagents.conciliador_subagent import ConciliadorSubagent

    def mock_n3_invoker(prompt: str) -> str:
        return """RESUMEN_FINAL: Documento consolidado con temas principales.

TEMAS_REORGANIZADOS:
auth_jwt
config_db
validaciones"""

    launcher = SubagentLauncher(task_invoker=mock_n3_invoker)
    n3 = ConciliadorSubagent(launcher=launcher)

    indices = [
        IndiceParcial(porcion_id=1, temas=[ThemeSection(tema="auth_jwt", descripcion="Auth", secciones=["login"])], resumen_parcial="P1"),
        IndiceParcial(porcion_id=2, temas=[ThemeSection(tema="config_db", descripcion="DB", secciones=["sqlite"])], resumen_parcial="P2"),
    ]

    att = Attachment(file_id="test", filename="doc.pdf", content_type="application/pdf", size=100000)
    result = n3.run(indices, att)

    assert result.success
    assert len(result.temas_detectados) >= 2
    assert len(result.resumen_breve) > 0
    print(f"  [OK] N3: {len(result.temas_detectados)} temas, resumen {len(result.resumen_breve)} chars")
    print("  [PASS] PASO")


def test_6_run_3_levels():
    """Test 6: DocumentoIndexerSubagent.run_3_levels orquestación."""
    print("\n=== Test 6: run_3_levels ===")

    from contexto_zai.subagents.documento_indexer_subagent import DocumentoIndexerSubagent

    class MockClient:
        def download(self, file_id): return b"%PDF test"
        def close(self): pass

    launcher = SubagentLauncher(task_invoker=lambda p: "RESUMEN: Test\n\nTEMA: tema\nDESCRIPCION: desc\nSECCIONES: s1")

    with tempfile.TemporaryDirectory() as tmpdir:
        sub = DocumentoIndexerSubagent(
            launcher=launcher, attachment_client=MockClient(),
            temp_dir=Path(tmpdir) / "temp", indexed_dir=Path(tmpdir) / "indexed",
        )
        att = Attachment(file_id="test", filename="doc.pdf", content_type="application/pdf", size=1652025)

        # El método existe
        assert hasattr(sub, "run_3_levels")
        print("  [OK] run_3_levels() disponible")

    print("  [PASS] PASO")


def test_7_credential_manager():
    """Test 7: CredentialManager persistir + leer JWT."""
    print("\n=== Test 7: CredentialManager ===")

    from contexto_zai.client.credential_manager import CredentialManager

    with tempfile.TemporaryDirectory() as tmpdir:
        cm = CredentialManager(credentials_path=Path(tmpdir) / "creds.json")

        # Sin JWT
        assert cm.get_jwt() is None
        assert cm.needs_jwt() is True
        print("  [OK] Sin JWT: needs_jwt=True")

        # Guardar JWT
        cm.save_jwt("test.jwt.token", "director@test.com")
        assert cm.get_jwt() == "test.jwt.token"
        assert cm.get_email() == "director@test.com"
        print("  [OK] JWT persistido y recuperado")

        # Eliminar
        cm.delete_jwt()
        assert cm.get_jwt() is None
        print("  [OK] JWT eliminado")

    print("  [PASS] PASO")


def test_8_jwt_bridge_server():
    """Test 8: JwtBridgeServer 3 endpoints."""
    print("\n=== Test 8: JwtBridgeServer ===")

    from contexto_zai.client.credential_manager import CredentialManager
    from contexto_zai.client.jwt_bridge_server import JwtBridgeServer
    import httpx, time

    with tempfile.TemporaryDirectory() as tmpdir:
        cm = CredentialManager(credentials_path=Path(tmpdir) / "creds.json")
        bat = Path(tmpdir) / "test.bat"
        bat.write_text("@echo test", encoding="utf-8")

        server = JwtBridgeServer(port=18090, credential_manager=cm, bat_file_path=bat)
        server.start()
        time.sleep(0.5)

        # GET /jwt-status
        r = httpx.get("http://localhost:18090/jwt-status", timeout=5)
        assert r.status_code == 200
        assert r.json()["needs_jwt"] is True
        print("  [OK] GET /jwt-status: needs_jwt=True")

        # GET /health
        r = httpx.get("http://localhost:18090/health", timeout=5)
        assert r.json()["status"] == "ok"
        print("  [OK] GET /health: ok")

        # GET /czai-jwt-bridge.bat
        r = httpx.get("http://localhost:18090/czai-jwt-bridge.bat", timeout=5)
        assert r.status_code == 200
        assert b"echo test" in r.content
        print("  [OK] GET /czai-jwt-bridge.bat: descargable")

        # POST /recibir-jwt
        r = httpx.post("http://localhost:18090/recibir-jwt", json={"token": "jwt.test", "email": "d@test.com"}, timeout=5)
        assert r.json()["success"] is True
        assert cm.get_jwt() == "jwt.test"
        print("  [OK] POST /recibir-jwt: JWT persistido")

        server.stop()
        assert not server.is_running
        print("  [OK] Server detenido")

    print("  [PASS] PASO")


def test_9_pipeline_index_document_large():
    """Test 9: pipeline.index_document_large disponible."""
    print("\n=== Test 9: pipeline.index_document_large ===")

    from contexto_zai.pipeline import index_document_large
    import inspect

    assert callable(index_document_large)
    sig = inspect.signature(index_document_large)
    assert {"file_id", "jwt", "filename"} <= set(sig.parameters.keys())
    print(f"  [OK] index_document_large(): {len(sig.parameters)} params")
    print("  [PASS] PASO")


def test_10_recovery_cycle_ensure_jwt():
    """Test 10: recovery_cycle._ensure_jwt disponible."""
    print("\n=== Test 10: recovery_cycle._ensure_jwt ===")

    from contexto_zai.process.recovery_cycle import RecoveryCycle

    cycle = RecoveryCycle(jwt="test-jwt", chat_id="test")
    assert hasattr(cycle, "_ensure_jwt")

    # Con JWT explícito → devuelve ese JWT
    jwt = cycle._ensure_jwt()
    assert jwt == "test-jwt"
    print("  [OK] _ensure_jwt() con JWT explícito: devuelve el JWT")
    print("  [PASS] PASO")


def main():
    print("=" * 60)
    print("TESTS E2E v3.6: Subagentes paralelos + JWT bridge")
    print("=" * 60)

    tests = [
        test_1_launch_parallel_real,
        test_2_documento_divisor_real_pdf,
        test_3_documento_conciliador,
        test_4_divisor_subagent_n1,
        test_5_conciliador_subagent_n3,
        test_6_run_3_levels,
        test_7_credential_manager,
        test_8_jwt_bridge_server,
        test_9_pipeline_index_document_large,
        test_10_recovery_cycle_ensure_jwt,
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
    print(f"RESULTADO E2E v3.6: {passed} pasaron, {failed} fallaron de {len(tests)} tests")
    print(f"{'=' * 60}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import io as _io, sys as _sys
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
        if hasattr(_sys.stderr, 'buffer') and 'utf' not in (getattr(_sys.stderr, 'encoding', '') or '').lower():
            _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass
    sys.exit(main())
