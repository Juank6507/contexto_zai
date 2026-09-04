# contexto_zai/detection/token_counter.py -- Contador preventivo de tokens: dispara recuperacion al 90% de capacidad util.
"""Contador preventivo de tokens consumidos (v3.2).

Estima los tokens consumidos por el agente desde la última recuperación.
Cuando se acerca al umbral de compresión (90% de capacidad útil),
dispara la recuperación antes de que la plataforma lo provoque.

Atómico standalone: importa config y models, nada más del proyecto.
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
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

import logging
from typing import TYPE_CHECKING

from contexto_zai.config import TOKEN_LIMITS

if TYPE_CHECKING:
    from contexto_zai.models import Exchange

logger = logging.getLogger(__name__)

class TokenCounter:
    """Estima tokens consumidos y dispara recuperación preventiva.

    Args:
        threshold_pct: Porcentaje de la capacidad útil a partir del cual
            se dispara la recuperación (por defecto 0.90 = 90%).

    Usage:
        >>> counter = TokenCounter()
        >>> counter.estimate(exchanges_since_last_recovery)
        >>> if counter.should_trigger():
        ...     # disparar recuperación
    """

    def __init__(
        self,
        threshold_pct: float = TOKEN_LIMITS.umbral_compresion_pct,
    ) -> None:
        self._threshold_pct = threshold_pct
        self._threshold_tokens = int(
            TOKEN_LIMITS.capacidad_util * threshold_pct
        )
        self._last_estimated_tokens = 0
        logger.debug(
            "TokenCounter inicializado: threshold=%d tokens (%.0f%% de %d)",
            self._threshold_tokens,
            threshold_pct * 100,
            TOKEN_LIMITS.capacidad_util,
        )

    # -- API pública ------------------------------------------------

    def estimate(self, exchanges: list["Exchange"]) -> int:
        """Estima los tokens consumidos por una lista de intercambios.

        Args:
            exchanges: Intercambios desde la última recuperación.

        Returns:
            Tokens estimados (chars / 3.5).
        """
        total_chars = sum(ex.total_chars for ex in exchanges)
        self._last_estimated_tokens = int(total_chars / TOKEN_LIMITS.conversion_rate)
        logger.debug(
            "Estimacion: %d intercambios, %d chars, ~%d tokens",
            len(exchanges),
            total_chars,
            self._last_estimated_tokens,
        )
        return self._last_estimated_tokens

    def should_trigger(self, current_tokens: int = None) -> bool:
        """Verifica si se debe disparar la recuperación.

        Args:
            current_tokens: Tokens consumidos. Si None, usa la última estimación.

        Returns:
            True si se supera el umbral de disparo.
        """
        tokens = current_tokens if current_tokens is not None else self._last_estimated_tokens
        triggered = tokens >= self._threshold_tokens
        if triggered:
            logger.info(
                "Disparo preventivo: %d tokens >= %d (%.0f%%)",
                tokens, self._threshold_tokens, self._threshold_pct * 100,
            )
        return triggered

    def remaining_tokens(self, current_tokens: int = None) -> int:
        """Tokens restantes antes del disparo."""
        tokens = current_tokens if current_tokens is not None else self._last_estimated_tokens
        return max(0, self._threshold_tokens - tokens)

    def utilization_pct(self, current_tokens: int = None) -> float:
        """Porcentaje de uso del umbral de disparo (0-100)."""
        tokens = current_tokens if current_tokens is not None else self._last_estimated_tokens
        if self._threshold_tokens == 0:
            return 0.0
        return (tokens / self._threshold_tokens) * 100

    # -- Propiedades ------------------------------------------------

    @property
    def threshold_tokens(self) -> int:
        """Umbral de tokens a partir del cual se dispara."""
        return self._threshold_tokens

    @property
    def last_estimated_tokens(self) -> int:
        """Última estimación de tokens consumidos."""
        return self._last_estimated_tokens

    def __repr__(self) -> str:
        return f"TokenCounter(threshold={self._threshold_tokens} tokens)"

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
    # -- Validación interna de token_counter.py --
    print("=== Validacion de token_counter.py ===\n")

    from contexto_zai.models import Exchange, Message, MessageRole

    # Counter con umbral bajo para tests
    counter = TokenCounter(threshold_pct=0.5)  # 50% para tests

    # Test 1: estimación básica
    exchanges = [
        Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="x" * 1000), topic="general", start_timestamp=1, end_timestamp=2),
        Exchange(id=2, director_msg=Message(seq=2, role=MessageRole.USER, timestamp=3, content="y" * 1000), topic="general", start_timestamp=3, end_timestamp=4),
    ]
    tokens = counter.estimate(exchanges)
    assert tokens == int(2000 / 3.5)  # 571 tokens
    print(f"[OK] Estimacion: 2 intercambios = {tokens} tokens")

    # Test 2: should_trigger con umbral bajo
    # Threshold es 50% de 102400 = 51200
    assert not counter.should_trigger()  # 571 < 51200
    print(f"[OK] should_trigger: no dispara con pocos tokens")

    # Test 3: disparo cuando se supera el umbral
    big_exchanges = [
        Exchange(id=i, director_msg=Message(seq=i, role=MessageRole.USER, timestamp=i, content="x" * 200000), topic="general", start_timestamp=i, end_timestamp=i+1)
        for i in range(1, 5)  # 4 * 200000 / 3.5 = 228571 tokens > 51200
    ]
    big_tokens = counter.estimate(big_exchanges)
    assert counter.should_trigger()
    print(f"[OK] should_trigger: dispara con {big_tokens} tokens (> {counter.threshold_tokens})")

    # Test 4: remaining_tokens
    remaining = counter.remaining_tokens(current_tokens=10000)
    assert remaining == counter.threshold_tokens - 10000
    print(f"[OK] remaining_tokens: {remaining} (con 10000 consumidos)")

    # Test 5: utilization_pct
    pct = counter.utilization_pct(current_tokens=counter.threshold_tokens // 2)
    assert abs(pct - 50.0) < 0.1
    print(f"[OK] utilization_pct: {pct:.1f}% (esperado 50%)")

    # Test 6: umbral por defecto (90%)
    default_counter = TokenCounter()
    assert default_counter.threshold_tokens == int(102_400 * 0.90)
    print(f"[OK] Umbral por defecto: {default_counter.threshold_tokens} tokens (90% de capacidad util)")

    # Test 7: lista vacía
    assert counter.estimate([]) == 0
    assert not counter.should_trigger()
    print(f"[OK] Lista vacia: 0 tokens, no dispara")

    # Test 8: propiedades (usar un counter con estimación conocida)
    counter_with_estimation = TokenCounter(threshold_pct=0.5)
    counter_with_estimation.estimate([
        Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="x" * 1000), topic="general", start_timestamp=1, end_timestamp=2),
    ])
    assert counter_with_estimation.last_estimated_tokens > 0
    print(f"[OK] last_estimated_tokens: {counter_with_estimation.last_estimated_tokens}")

    print("\n[PASS] token_counter.py: todos los tests pasaron")
