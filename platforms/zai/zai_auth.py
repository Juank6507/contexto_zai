"""contexto_zai/platforms/zai/zai_auth.py -- Implementacion Zai de PlatformAuth (v7.0 F2).

Envuelve ``AuthClient`` (autenticacion HTTP contra chat.z.ai) y
``CredentialManager`` (persistencia del JWT en ``~/.czai/credentials.json``).
NO los reemplaza: la abstraccion vive aqui, la implementacion HTTP
sigue en ``client/``.

Inyeccion por constructor: si un llamador no inyecta nada, se usa la
implementacion Zai por defecto (carga el JWT del CredentialManager).
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


import logging
from typing import Optional

from contexto_zai.platforms.interfaces import PlatformAuth
from contexto_zai.client.credential_manager import CredentialManager
from contexto_zai.client.auth_client import AuthClient

logger = logging.getLogger(__name__)


class ZaiAuth(PlatformAuth):
    """Implementacion Zai de ``PlatformAuth``.

    Envuelve ``CredentialManager`` (lee/escribe JWT persistido) y
    ``AuthClient`` (valida JWT y crea shares contra chat.z.ai).

    Args:
        jwt: JWT del Director. Si es vacio, se carga del
            ``CredentialManager`` (donde persiste el JWT puesto por el
            bookmarklet). Si despues de cargarlo sigue vacio, los
            metodos devuelven strings vacios / False.
        email: Email del Director (opcional, verificacion extra). Si es
            vacio, se carga del ``CredentialManager``.

    Usage:
        >>> auth = ZaiAuth(jwt="eyJhbG...")
        >>> auth.is_authenticated()
        True
        >>> share_id = auth.create_share("chat-uuid-123")
    """

    def __init__(self, jwt: str = "", email: str = "") -> None:
        self._credential_manager = CredentialManager()
        self._jwt = jwt or self._credential_manager.get_jwt() or ""
        self._email = email or self._credential_manager.get_email() or ""

    # -- PlatformAuth API --------------------------------------------

    def get_jwt(self) -> str:
        """Devuelve el JWT del Director (string vacio si no hay)."""
        return self._jwt

    def get_email(self) -> str:
        """Devuelve el email del Director (string vacio si no hay)."""
        return self._email

    def is_authenticated(self) -> bool:
        """True si hay JWT y el email NO contiene 'guest' (invitado)."""
        return bool(self._jwt) and "guest" not in self._email.lower()

    def create_share(self, chat_id: str) -> str:
        """Crea o reutiliza un share link del chat. Devuelve el share_id.

        Delega en ``AuthClient.create_share`` (modo legacy con token).
        Si el JWT es invalido o el chat no existe, lanza
        ``ShareCreationError`` (propagado de AuthClient).
        """
        if not chat_id:
            logger.warning("ZaiAuth.create_share: chat_id vacio")
            return ""
        # AuthClient se usa como context manager para cerrar el httpx
        # client al terminar (igual que el MessageExtractor original).
        with AuthClient(token=self._jwt) as auth:
            share_id = auth.create_share(chat_id)
        logger.info(
            "ZaiAuth.create_share: share creado/reutilizado para chat %s: %s",
            chat_id[:12] if chat_id else "N/A",
            share_id[:12] if share_id else "N/A",
        )
        return share_id

    def __repr__(self) -> str:
        masked = (self._jwt[:12] + "...") if len(self._jwt) > 12 else self._jwt
        return f"ZaiAuth(jwt={masked!r}, email={self._email!r})"
