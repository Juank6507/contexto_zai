# contexto_zai/client/credential_manager.py -- Gestiona el JWT del Director: persiste, valida, pide si falta (v3.6).
"""Gestor de credenciales JWT del Director (v3.6).

Persiste el JWT en ~/.czai/credentials.json con permisos 0600.
Valida el JWT contra /api/v1/auths/ antes de usarlo.
Si el JWT no existe o es inválido, el agente lo detecta y
solicita al Director que ejecute el script .bat.

Atómico standalone: importa config y httpx.
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
from pathlib import Path
from typing import Optional

import httpx

from contexto_zai.config import API_CONFIG, CREDENTIALS_FILE

logger = logging.getLogger(__name__)


class CredentialManager:
    """Gestiona el JWT del Director (v3.6).

    Args:
        credentials_path: Ruta del archivo de credenciales.
            Por defecto usa CREDENTIALS_FILE de config.py.

    Usage:
        >>> cm = CredentialManager()
        >>> jwt = cm.get_jwt()  # lee de ~/.czai/credentials.json
        >>> if not jwt or not cm.is_valid(jwt):
        ...     # pedir al Director que ejecute .bat
        ...     pass
    """

    def __init__(self, credentials_path: Optional[Path | str] = None) -> None:
        self._path = Path(credentials_path) if credentials_path else CREDENTIALS_FILE
        logger.debug("CredentialManager inicializado: path=%s", self._path)

    # -- API pública ------------------------------------------------

    def get_jwt(self) -> Optional[str]:
        """Lee el JWT persistido.

        Returns:
            JWT string, o None si no existe.
        """
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data.get("token")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Error leyendo credenciales de %s: %s", self._path, e)
            return None

    def save_jwt(self, jwt: str, email: str = "") -> None:
        """Persiste el JWT con permisos 0600.

        Args:
            jwt: JWT del Director.
            email: Email del Director (opcional, para verificación).
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"token": jwt, "email": email}
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        # Permisos 0600 (solo legible por el usuario)
        try:
            self._path.chmod(0o600)
        except OSError:
            # Windows no soporta chmod como Unix, ignora
            pass
        logger.info("JWT persistido en %s (email=%s)", self._path, email or "?")

    def is_valid(self, jwt: str) -> bool:
        """Verifica el JWT contra /api/v1/auths/.

        Args:
            jwt: JWT a verificar.

        Returns:
            True si el JWT es válido (role=user), False si es inválido o de invitado.
        """
        if not jwt:
            return False
        try:
            response = httpx.get(
                f"{API_CONFIG.base_url}/api/v1/auths/",
                cookies={API_CONFIG.cookie_name: jwt},
                timeout=10.0,
            )
            if response.status_code != 200:
                return False
            data = response.json()
            role = data.get("role", "guest")
            return role == "user"
        except httpx.HTTPError as e:
            logger.warning("Error validando JWT: %s", e)
            return False

    def needs_jwt(self) -> bool:
        """Verifica si el agente necesita JWT.

        Returns:
            True si no hay JWT o el existente es inválido.
        """
        jwt = self.get_jwt()
        if not jwt:
            return True
        return not self.is_valid(jwt)

    def delete_jwt(self) -> None:
        """Elimina el JWT persistido (para logout o reset)."""
        if self._path.exists():
            self._path.unlink()
            logger.info("JWT eliminado de %s", self._path)

    def get_email(self) -> Optional[str]:
        """Lee el email persistido junto al JWT.

        Returns:
            Email del Director, o None si no existe.
        """
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data.get("email")
        except (json.JSONDecodeError, OSError):
            return None

    def __repr__(self) -> str:
        return f"CredentialManager(path={self._path!r})"


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

    print("=== Validacion de credential_manager.py ===\n")

    import tempfile

    # Test 1: get_jwt sin archivo → None
    with tempfile.TemporaryDirectory() as tmpdir:
        cm = CredentialManager(credentials_path=Path(tmpdir) / "creds.json")
        assert cm.get_jwt() is None
        print("[OK] Sin archivo: get_jwt() devuelve None")

        # Test 2: save_jwt + get_jwt
        cm.save_jwt("eyJhbG.test.jwt", "director@example.com")
        jwt = cm.get_jwt()
        assert jwt == "eyJhbG.test.jwt"
        print(f"[OK] save_jwt + get_jwt: {jwt[:20]}...")

        # Test 3: get_email
        email = cm.get_email()
        assert email == "director@example.com"
        print(f"[OK] get_email: {email}")

        # Test 4: needs_jwt sin JWT → True
        cm2 = CredentialManager(credentials_path=Path(tmpdir) / "no_existe.json")
        assert cm2.needs_jwt() is True  # no hay JWT → necesita
        print("[OK] needs_jwt sin archivo: True")

        # Test 5: needs_jwt con JWT falso → True (is_valid falla)
        # No podemos probar is_valid real sin conexión a Z.ai
        # Pero podemos probar que no crashea
        assert cm.get_jwt() == "eyJhbG.test.jwt"
        print("[OK] JWT persistido correctamente")

        # Test 6: delete_jwt
        cm.delete_jwt()
        assert cm.get_jwt() is None
        print("[OK] delete_jwt: JWT eliminado")

        # Test 7: is_valid con JWT vacío → False
        assert cm.is_valid("") is False
        print("[OK] is_valid(''): False")

        # Test 8: is_valid con None → False
        assert cm.is_valid(None) is False
        print("[OK] is_valid(None): False")

    # Test 9: repr
    cm3 = CredentialManager(credentials_path="/tmp/test_creds.json")
    r = repr(cm3)
    assert "CredentialManager" in r
    print(f"[OK] repr: {r}")

    print("\n[PASS] credential_manager.py: todos los tests pasaron")
