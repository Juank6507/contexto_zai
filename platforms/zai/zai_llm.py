"""contexto_zai/platforms/zai/zai_llm.py -- Implementacion Zai de PlatformLLM (v7.0 F2).

Envuelve la llamada HTTP al proxy APA interno del sandbox Next.js
(``/api/zai-proxy/v1/chat/completions``). NO reemplaza el proxy: la
abstraccion vive aqui, el endpoint Next.js sigue en
``src/app/api/zai-proxy/v1/chat/completions/route.ts``.

Inyeccion por constructor: si un llamador no inyecta nada, se usa la
implementacion Zai por defecto (URL y timeout de ``zai_config``).
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Optional

from platforms.interfaces import PlatformLLM
from platforms.zai.zai_config import (
    ZAI_PROXY_LLM_URL,
    ZAI_PROXY_LLM_TIMEOUT,
    ZAI_DEFAULT_MODEL_HEAVY,
    ZAI_DEFAULT_MODEL_LIGHT,
)

logger = logging.getLogger(__name__)


class ZaiLLM(PlatformLLM):
    """Implementacion Zai de ``PlatformLLM``.

    Llama al proxy APA del sandbox Next.js via HTTP POST. El proxy
    enruta a GLM-4-plus (heavy) o GLM-4-flash (light) segun el modelo
    indicado.

    Args:
        proxy_url: URL del proxy APA. Default:
            ``ZAI_PROXY_LLM_URL`` (``http://localhost:3000/api/zai-proxy/v1/chat/completions``).
        timeout: Timeout base en segundos para llamadas HTTP. Default:
            ``ZAI_PROXY_LLM_TIMEOUT`` (10s). Los llamadores que hacen
            llamadas LLM reales (enriquecer bloques, Crítico, etc.)
            pueden pasar ``timeout=PROXY_LLM_TIMEOUT * 6`` para no
            cortar respuestas largas.

    Usage:
        >>> llm = ZaiLLM()
        >>> resp = llm.call(messages=[{"role": "user", "content": "hola"}],
        ...                 model=llm.get_default_model_heavy())
        >>> content = resp["choices"][0]["message"]["content"]
    """

    def __init__(
        self,
        proxy_url: str = ZAI_PROXY_LLM_URL,
        timeout: int = ZAI_PROXY_LLM_TIMEOUT,
    ) -> None:
        self._proxy_url = proxy_url
        self._timeout = timeout

    # -- PlatformLLM API --------------------------------------------

    def call(
        self,
        messages: list,
        model: str = "",
        max_tokens: int = 3000,
        temperature: float = 0.3,
        timeout: Optional[int] = None,
    ) -> dict:
        """Llama al LLM con ``messages`` y devuelve la respuesta parseada.

        Args:
            messages: Lista de mensajes [{role, content}, ...].
            model: Nombre del modelo. Si es vacio, usa el heavy por defecto.
            max_tokens: Maximo de tokens a generar.
            temperature: Temperatura de muestreo.
            timeout: Timeout opcional en segundos. Si es None, usa
                ``self._timeout`` (default 10s).

        Returns:
            Dict con la respuesta del proxy (estructura OpenAI):
            ``{"choices": [{"message": {"content": "..."}}], ...}``.

        Raises:
            urllib.error.HTTPError: Si el proxy devuelve HTTP != 200
                (429 rate limit, 500 server error, etc.).
            urllib.error.URLError: Si el proxy no responde.
            json.JSONDecodeError: Si la respuesta no es JSON valido.
        """
        effective_model = model if model else ZAI_DEFAULT_MODEL_HEAVY
        effective_timeout = timeout if timeout is not None else self._timeout
        payload = json.dumps({
            "model": effective_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }).encode("utf-8")
        req = urllib.request.Request(self._proxy_url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw)

    def is_available(self) -> bool:
        """Ping minimo al proxy. Devuelve True si responde 200.

        Usa el modelo light (mas rapido) y ``max_tokens=3`` para
        minimizar coste. Si recibe cualquier error (HTTP 429, timeout,
        conexion rechazada), devuelve False.
        """
        try:
            payload = json.dumps({
                "model": ZAI_DEFAULT_MODEL_LIGHT,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 3,
            }).encode("utf-8")
            req = urllib.request.Request(self._proxy_url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as e:
            logger.info("ZaiLLM.is_available: HTTP %d", e.code)
            return False
        except Exception as e:
            logger.info("ZaiLLM.is_available: error %s", e)
            return False

    def get_default_model_heavy(self) -> str:
        """Devuelve el nombre del modelo heavy por defecto (calidad)."""
        return ZAI_DEFAULT_MODEL_HEAVY

    def get_default_model_light(self) -> str:
        """Devuelve el nombre del modelo light por defecto (rapido)."""
        return ZAI_DEFAULT_MODEL_LIGHT

    def __repr__(self) -> str:
        return (
            f"ZaiLLM(proxy_url={self._proxy_url!r}, timeout={self._timeout}s, "
            f"heavy={ZAI_DEFAULT_MODEL_HEAVY!r}, light={ZAI_DEFAULT_MODEL_LIGHT!r})"
        )
