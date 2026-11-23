"""contexto_zai/platforms/zai/zai_config.py -- Constantes concretas de Z.ai (v7.0 F2).

Valores especificos de la plataforma Z.ai que las implementaciones
concretas (``ZaiAuth``, ``ZaiChat``, ``ZaiLinks``, ``ZaiLLM``) consumen.

v7.0 F2: centraliza los valores Zai aqui (antes vivian en ``config.py``
con prefijo ``PROXY_ZAI_*``). ``config.py`` mantiene los nombres viejos
(``PROXY_ZAI_URL``, ``PROXY_ZAI_TIMEOUT``) como alias deprecated por
una version mas para no romper imports externos.

Re-exporta ``APIConfig`` y ``API_CONFIG`` de ``client.zai_config`` para
evitar duplicacion: la configuracion de los endpoints HTTP de chat.z.ai
sigue viviendo donde siempre (``client.zai_config``), aqui solo
anadimos los valores del proxy LLM y los modelos.
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


# Re-export de APIConfig/API_CONFIG (no duplicar).
from contexto_zai.client.zai_config import APIConfig, API_CONFIG  # noqa: F401

# -- Base URL de chat.z.ai -----------------------------------------
# (Duplicado intencionalmente para que platforms.zai sea autocontenible.
# API_CONFIG.base_url sigue siendo la fuente canonica para clientes HTTP.)
ZAI_BASE_URL = "https://chat.z.ai"

# -- Proxy LLM (APA interno del sandbox Next.js) -------------------
# URL del proxy APA del sandbox Next.js. Es la puerta de entrada al
# LLM (GLM-4-plus / GLM-4-flash) desde el proceso Python.
ZAI_PROXY_LLM_URL = "http://localhost:3000/api/zai-proxy/v1/chat/completions"

# Timeout base en segundos para el ping inicial al proxy. Los
# llamadores que hacen llamadas LLM reales (enriquecer bloques, W3,
# crítico) usan ``ZAI_PROXY_LLM_TIMEOUT * 6`` (60s) o ``* 3`` (30s)
# para no cortar respuestas largas.
ZAI_PROXY_LLM_TIMEOUT = 10

# -- Modelos GLM por defecto ---------------------------------------
# Modelo "heavy" para tareas que requieren calidad (W1, generacion
# de archivos, enriquecer bloques, validacion Crítico).
ZAI_DEFAULT_MODEL_HEAVY = "glm-4-plus"

# Modelo "light" para tareas que requieren velocidad (W2 fusionado,
# ping de disponibilidad, extraccion simple).
ZAI_DEFAULT_MODEL_LIGHT = "glm-4-flash"
