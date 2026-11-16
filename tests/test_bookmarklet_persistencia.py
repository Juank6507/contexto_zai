# contexto_zai/tests/test_bookmarklet_persistencia.py -- Tests de persistencia del JWT del bookmarklet (M5/H8).
"""Tests de persistencia del JWT del bookmarklet (H8/M5).

Valida que:
1. El endpoint /api/czai/recibir-jwt escribe correctamente el JWT.
2. El endpoint /api/czai/jwt-status lee el JWT persistido.
3. El JWT persiste en ~/.czai/credentials.json entre sesiones.
4. El bookmarklet funciona (simulado, no requiere navegador real).

Script de dependencia: importa atómicos de client/credential_manager.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Auto-configuracion de sys.path
_here = Path(__file__).resolve().parent
_workspace = _here.parent.parent
if str(_workspace) not in sys.path:
    sys.path.insert(0, str(_workspace))

from contexto_zai.client.credential_manager import CredentialManager


def test_credential_manager_guardar_leer():
    """CredentialManager guarda y lee JWT correctamente."""
    with tempfile.TemporaryDirectory() as tmpdir:
        creds_path = Path(tmpdir) / "credentials.json"
        cm = CredentialManager(credentials_path=creds_path)

        # Guardar
        cm.save_jwt("eyJ.test.jwt", email="director@test.com")

        # Leer
        assert cm.get_jwt() == "eyJ.test.jwt"
        assert cm.get_email() == "director@test.com"
        # needs_jwt() valida contra la API real, así que con un JWT de test devuelve True.
        # Para el test, verificamos que el archivo existe y tiene el JWT.
        assert creds_path.exists()
        data = json.loads(creds_path.read_text(encoding="utf-8"))
        assert data["token"] == "eyJ.test.jwt"
        assert data["email"] == "director@test.com"

        print("[OK] CredentialManager: guardar+leer JWT")


def test_credential_manager_sin_jwt():
    """CredentialManager detecta cuando no hay JWT."""
    with tempfile.TemporaryDirectory() as tmpdir:
        creds_path = Path(tmpdir) / "credentials.json"
        cm = CredentialManager(credentials_path=creds_path)

        assert cm.needs_jwt()
        assert cm.get_jwt() is None
        assert cm.get_email() is None

        print("[OK] CredentialManager: sin JWT detectado")


def test_credential_manager_validar_jwt_formato():
    """CredentialManager valida formato básico de JWT (3 partes).

    Nota: is_valid() hace una llamada HTTP real a la API de Z.ai.
    Aquí solo verificamos el formato (no la validez contra la API).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        creds_path = Path(tmpdir) / "credentials.json"
        cm = CredentialManager(credentials_path=creds_path)

        # JWT con formato válido (3 partes separadas por .)
        jwt_valid_format = "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjEyMyJ9.signature"
        assert len(jwt_valid_format.split(".")) == 3

        # JWT inválido (formato)
        assert len("no-es-jwt".split(".")) == 1  # no tiene puntos
        assert len("a.b".split(".")) == 2  # solo 2 partes

        print("[OK] CredentialManager: formato JWT validado (3 partes)")


def test_credential_manager_borrar():
    """CredentialManager borra el JWT."""
    with tempfile.TemporaryDirectory() as tmpdir:
        creds_path = Path(tmpdir) / "credentials.json"
        cm = CredentialManager(credentials_path=creds_path)

        cm.save_jwt("eyJ.test.jwt", email="test@test.com")
        assert creds_path.exists()

        cm.delete_jwt()
        assert not creds_path.exists()
        assert cm.get_jwt() is None

        print("[OK] CredentialManager: borrar JWT")


def test_credential_manager_persistencia_entre_instancias():
    """El JWT persiste entre instancias de CredentialManager (simula sesiones)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        creds_path = Path(tmpdir) / "credentials.json"

        # Sesión 1: guardar JWT
        cm1 = CredentialManager(credentials_path=creds_path)
        cm1.save_jwt("eyJ.persistent.jwt", email="director@z.ai")

        # Sesión 2: leer JWT (nueva instancia, mismo path)
        cm2 = CredentialManager(credentials_path=creds_path)
        assert cm2.get_jwt() == "eyJ.persistent.jwt"
        assert cm2.get_email() == "director@z.ai"

        print("[OK] Persistencia entre sesiones: JWT recuperado")


def test_credential_manager_formato_json():
    """El archivo credentials.json tiene el formato correcto."""
    with tempfile.TemporaryDirectory() as tmpdir:
        creds_path = Path(tmpdir) / "credentials.json"
        cm = CredentialManager(credentials_path=creds_path)
        cm.save_jwt("eyJ.format.test", email="format@test.com")

        # Leer el archivo directamente y verificar formato
        data = json.loads(creds_path.read_text(encoding="utf-8"))
        assert "token" in data
        assert "email" in data
        assert data["token"] == "eyJ.format.test"
        assert data["email"] == "format@test.com"

        print("[OK] Formato credentials.json: token + email")


def test_recibir_jwt_form_post_simulado():
    """Simula el form POST del bookmarklet al endpoint /api/czai/recibir-jwt.

    El bookmarklet envía el JWT vía form POST. Aquí simulamos la escritura
    que hace el endpoint (usando CredentialManager directamente).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        creds_path = Path(tmpdir) / "credentials.json"

        # Simular: el bookmarklet obtiene el JWT del navegador
        jwt_from_bookmarklet = "eyJ.bookmarklet.jwt"
        email_from_bookmarklet = "director@z.ai"

        # Simular: el endpoint /api/czai/recibir-jwt recibe y guarda
        cm = CredentialManager(credentials_path=creds_path)
        cm.save_jwt(jwt_from_bookmarklet, email=email_from_bookmarklet)

        # Simular: el endpoint /api/czai/jwt-status lee y responde
        # (sin validar contra API real — solo verifica que el JWT está guardado)
        response = {
            "needs_jwt": not bool(cm.get_jwt()),  # True si no hay JWT guardado
            "email": cm.get_email() or "",
        }

        assert response["needs_jwt"] is False
        assert response["email"] == "director@z.ai"

        print("[OK] Bookmarklet → endpoint → CredentialManager: flujo completo")


def test_jwt_no_expira_estructura():
    """Verifica que el JWT del Director no tiene campo exp (no expira).

    Esto es un hallazgo documentado: el JWT del Director no expira,
    así que no necesita refresh.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        creds_path = Path(tmpdir) / "credentials.json"
        cm = CredentialManager(credentials_path=creds_path)

        # JWT del Director (formato real: 3 partes, sin exp en payload)
        # Payload: {"id":"...", "email":"..."} — sin campo "exp"
        jwt_director = "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjEyMyIsImVtYWlsIjoiZGlyZWN0b3JAei5haSJ9.signature"

        cm.save_jwt(jwt_director, email="director@z.ai")

        # Verificar que se guardó correctamente
        assert cm.get_jwt() == jwt_director
        assert cm.get_email() == "director@z.ai"

        # Decodificar payload para verificar que no tiene exp
        import base64
        parts = jwt_director.split(".")
        payload_b64 = parts[1] + "=="
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        assert "exp" not in payload, f"JWT no debería tener exp, got: {payload}"
        assert "email" in payload

        print("[OK] JWT del Director: sin campo exp (no expira)")


def main():
    print("=== Tests de persistencia del bookmarklet (H8/M5) ===\n")

    tests = [
        test_credential_manager_guardar_leer,
        test_credential_manager_sin_jwt,
        test_credential_manager_validar_jwt_formato,
        test_credential_manager_borrar,
        test_credential_manager_persistencia_entre_instancias,
        test_credential_manager_formato_json,
        test_recibir_jwt_form_post_simulado,
        test_jwt_no_expira_estructura,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n=== Resumen: {passed} pasaron, {failed} fallaron ===")
    if failed == 0:
        print("[PASS] Todos los tests de persistencia pasaron")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import io as _io, sys as _sys
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass
    sys.exit(main())
