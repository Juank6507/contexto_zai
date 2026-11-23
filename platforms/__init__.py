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

"""contexto_zai/platforms/__init__.py -- Paquete de abstraccion de plataforma (v7.0 F2).

Marca el paquete ``platforms`` que contiene la capa de abstraccion de
plataforma introducida en v7.0 F2 para restaurar la separacion de capas
v5.0 con implementaciones concretas de Zai.

Contenido:
- ``interfaces`` — 4 ABCs (``PlatformAuth``, ``PlatformChat``,
  ``PlatformLinks``, ``PlatformLLM``) que definen el contrato de cualquier
  plataforma de chat/LLM.
- ``zai/`` — subpaquete con las implementaciones concretas para Z.ai
  (envuelven los clientes existentes en ``contexto_zai.client``).

Para cambiar de plataforma, basta con crear un nuevo subpaquete (por
ejemplo ``platforms/otra/``) con clases que implementen las 4 ABCs. Los
modulos generales (pipeline, processing, etc.) no se tocan: reciben la
implementacion por inyeccion de constructor con default Zai.
"""
