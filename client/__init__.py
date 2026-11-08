# contexto_zai/client/__init__.py -- Subpaquete de clientes HTTP para la API de chat.z.ai (AuthClient, ChatClient, BrowserSession).
"""Cliente HTTP para interactuar con la API de chat.z.ai (v3.2).

Exporta:
    AuthClient       -- Autenticación y gestión de shares (legacy + v3.2).
    ChatClient       -- Extracción de mensajes (legacy + v3.2).
    BrowserSession   -- Sesión del navegador para autenticación automática (v3.2).
"""

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

from contexto_zai.client.auth_client import AuthClient
from contexto_zai.client.browser_session import BrowserSession
from contexto_zai.client.chat_client import ChatClient

__all__ = ["AuthClient", "ChatClient", "BrowserSession"]
