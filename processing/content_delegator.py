# contexto_zai/processing/content_delegator.py -- Decisión de delegación de lectura de contenido al subagente.
"""Delegación de lectura de contenido (v3.5).

Clase base abstracta `ContentDelegator` que define la interfaz para
decidir si un contenido debe procesarse en el contexto del agente
principal o delegarse a un subagente efímero.

Implementación concreta `DocumentDelegator` para documentos adjuntos.
Criterio:
- Override del Director tiene prioridad absoluta.
- Documento trivialmente pequeño (<1000 tokens) → no delegar.
- Documento grande (>5000 tokens) → delegar.
- Documento mediano + agente casi lleno (>80% contexto) → delegar.
- Otro caso → no delegar.

Atómico standalone: importa config y models, nada más del proyecto.
"""

from __future__ import annotations

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

import logging
import re
from abc import ABC, abstractmethod
from typing import Optional

from contexto_zai.config import (
    DELEGATION_CONTEXT_LIMIT_PCT,
    DELEGATION_THRESHOLD_TOKENS,
    TRIVIAL_SIZE_TOKENS,
)

logger = logging.getLogger(__name__)


class ContentDelegator(ABC):
    """Clase base abstracta para decidir delegación de contenido.

    Define la interfaz común para todos los delegadores:
    - `should_delegate(content_size, context_available, override)` → bool
    - `_parse_override(director_override)` → Optional[bool]

    Subclases concretas:
    - `DocumentDelegator`: para documentos adjuntos.
    - `Subdivider` (refactor futuro): para temas grandes del chat.
    """

    @abstractmethod
    def should_delegate(
        self,
        content_size_tokens: int,
        agent_context_available_pct: float,
        director_override: Optional[str] = None,
    ) -> bool:
        """Decide si el contenido debe delegarse a un subagente.

        Args:
            content_size_tokens: Tamaño estimado del contenido en tokens.
            agent_context_available_pct: Porcentaje de contexto del agente
                ya ocupado (0-100).
            director_override: Instrucción explícita del Director
                (ej: "lee completo", "no leas").

        Returns:
            True si debe delegarse al subagente, False si el agente principal
            debe procesarlo directamente.
        """
        ...

    @staticmethod
    def _parse_override(director_override: Optional[str]) -> Optional[bool]:
        """Interpreta frases del Director para override de la decisión automática.

        Reconoce:
        - "lee completo", "leer completo", "documento completo", "sin subagente",
          "no delegues" → False (leer directo, no delegar).
        - "no leas", "no lee", "no leer", "no lea", "no leas", "ignora",
          "solo indexa", "delega" → True (delegar siempre).

        Args:
            director_override: Texto del Director (puede ser None).

        Returns:
            None si no hay override reconocido, False/True si hay override.
        """
        if not director_override:
            return None
        text = director_override.lower()

        # Override "leer directo" (no delegar)
        if "completo" in text or "completa" in text:
            return False
        if re.search(r"sin subagente", text):
            return False
        if re.search(r"no delegu?[eé]s?", text) or re.search(r"no delegar", text):
            return False

        # Override "no leer" (delegar siempre)
        # Captura todas las conjugaciones de "leer": lee, lees, lea, leas, leer, leen
        if re.search(r"no le[eéa][rs]?", text):
            return True
        if "ignora" in text or "solo indexa" in text or "delega" in text:
            return True

        return None


class DocumentDelegator(ContentDelegator):
    """Decide si un documento adjunto debe delegarse al subagente.

    Criterio:
    1. Override del Director tiene prioridad absoluta.
    2. Documento trivialmente pequeño (<TRIVIAL_SIZE_TOKENS) → no delegar.
    3. Documento grande (>DELEGATION_THRESHOLD_TOKENS) → delegar.
    4. Documento mediano + agente casi lleno (>DELEGATION_CONTEXT_LIMIT_PCT) → delegar.
    5. Otro caso → no delegar.

    Usage:
        >>> delegator = DocumentDelegator()
        >>> if delegator.should_delegate(165000, 20):
        ...     # lanzar subagente
        ...     pass
    """

    def should_delegate(
        self,
        content_size_tokens: int,
        agent_context_available_pct: float,
        director_override: Optional[str] = None,
    ) -> bool:
        # 1. Override del Director tiene prioridad absoluta
        override = self._parse_override(director_override)
        if override is not None:
            logger.debug(
                "Override del Director detectado: %r → delegar=%s",
                director_override, override,
            )
            return override

        # 2. Documento trivialmente pequeño → no delegar
        if content_size_tokens < TRIVIAL_SIZE_TOKENS:
            logger.debug(
                "Documento trivial (%d tokens < %d) → no delegar",
                content_size_tokens, TRIVIAL_SIZE_TOKENS,
            )
            return False

        # 3. Documento grande → delegar
        if content_size_tokens > DELEGATION_THRESHOLD_TOKENS:
            logger.debug(
                "Documento grande (%d tokens > %d) → delegar",
                content_size_tokens, DELEGATION_THRESHOLD_TOKENS,
            )
            return True

        # 4. Documento mediano + agente casi lleno → delegar
        if agent_context_available_pct > DELEGATION_CONTEXT_LIMIT_PCT:
            logger.debug(
                "Agente casi lleno (%.0f%% > %d%%) → delegar",
                agent_context_available_pct, DELEGATION_CONTEXT_LIMIT_PCT,
            )
            return True

        # 5. Default: no delegar
        logger.debug(
            "Documento mediano (%d tokens) y agente con contexto disponible → no delegar",
            content_size_tokens,
        )
        return False

    def __repr__(self) -> str:
        return (
            f"DocumentDelegator(threshold={DELEGATION_THRESHOLD_TOKENS}, "
            f"trivial={TRIVIAL_SIZE_TOKENS}, context_limit={DELEGATION_CONTEXT_LIMIT_PCT}%)"
        )


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

    print("=== Validacion de content_delegator.py ===\n")

    delegator = DocumentDelegator()

    # Test 1: documento grande → delegar
    assert delegator.should_delegate(165000, 20) is True
    print("[OK] PDF 165K tokens, 20% contexto → delegar=True")

    # Test 2: documento trivial → no delegar
    assert delegator.should_delegate(500, 20) is False
    print("[OK] Documento 500 tokens, 20% contexto → delegar=False (trivial)")

    # Test 3: documento mediano, agente libre → no delegar
    assert delegator.should_delegate(3000, 50) is False
    print("[OK] Documento 3K tokens, 50% contexto → delegar=False")

    # Test 4: documento mediano, agente casi lleno → delegar
    assert delegator.should_delegate(3000, 90) is True
    print("[OK] Documento 3K tokens, 90% contexto → delegar=True")

    # Test 5: override "lee completo" → no delegar
    assert delegator.should_delegate(165000, 90, "lee completo") is False
    assert delegator.should_delegate(165000, 90, "leer completo") is False
    assert delegator.should_delegate(165000, 90, "documento completo") is False
    assert delegator.should_delegate(165000, 90, "lee esto completo") is False
    assert delegator.should_delegate(165000, 90, "sin subagente") is False
    assert delegator.should_delegate(165000, 90, "no delegues") is False
    assert delegator.should_delegate(165000, 90, "no delegar") is False
    print("[OK] 7 variaciones de 'lee completo' → todas False (no delegar)")

    # Test 6: override "no leas" → delegar siempre
    assert delegator.should_delegate(500, 20, "no leas") is True
    assert delegator.should_delegate(500, 20, "no lee") is True
    assert delegator.should_delegate(500, 20, "no leer") is True
    assert delegator.should_delegate(500, 20, "no lea") is True
    assert delegator.should_delegate(500, 20, "no leas el documento") is True
    assert delegator.should_delegate(500, 20, "ignora el documento") is True
    assert delegator.should_delegate(500, 20, "solo indexa") is True
    assert delegator.should_delegate(500, 20, "delega siempre") is True
    print("[OK] 8 variaciones de 'no leas' → todas True (delegar)")

    # Test 7: override neutro → criterio automático
    assert delegator.should_delegate(3000, 50, "esto es una prueba") is False
    assert delegator.should_delegate(165000, 20, "procesa el documento") is True
    print("[OK] Override neutro → criterio automático")

    # Test 8: _parse_override directo
    assert ContentDelegator._parse_override(None) is None
    assert ContentDelegator._parse_override("") is None
    assert ContentDelegator._parse_override("lee completo") is False
    assert ContentDelegator._parse_override("no leas") is True
    assert ContentDelegator._parse_override("texto neutro") is None
    print("[OK] _parse_override: casos directos correctos")

    # Test 9: caso edge - contexto al 100%
    assert delegator.should_delegate(3000, 100) is True  # > 80% → delegar
    assert delegator.should_delegate(500, 100) is False  # trivial → no delegar
    print("[OK] Contexto 100%: doc mediano delega, trivial no")

    # Test 10: caso edge - tamaño 0 tokens
    assert delegator.should_delegate(0, 50) is False  # trivial
    print("[OK] Documento 0 tokens → no delegar (trivial)")

    # Test 11: tamaño exacto en el umbral
    assert delegator.should_delegate(TRIVIAL_SIZE_TOKENS, 50) is False  # no <, = no delega
    assert delegator.should_delegate(TRIVIAL_SIZE_TOKENS + 1, 50) is False  # sigue mediano
    assert delegator.should_delegate(DELEGATION_THRESHOLD_TOKENS + 1, 50) is True  # > umbral
    print("[OK] Umbrales: límites correctos")

    # Test 12: repr
    r = repr(delegator)
    assert "DocumentDelegator" in r
    assert "threshold=5000" in r
    print(f"[OK] repr: {r}")

    print("\n[PASS] content_delegator.py: todos los tests pasaron")
