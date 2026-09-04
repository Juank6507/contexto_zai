# Destino: /home/z/my-project/contexto_zai/detection/lexic_trigger.py
"""Disparador léxico de pérdida de contexto (v3.2).

Detecta frases del Director que indican que el agente ha perdido
contexto o está siendo incoherente. Dispara la recuperación cuando
encuentra frases como "ya te dije", "no repitas", "olvidaste", etc.

Atómico standalone: importa config, nada más del proyecto.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from contexto_zai.config import LEXIC_TRIGGER_PHRASES

logger = logging.getLogger(__name__)


class LexicTrigger:
    """Detecta pérdida de contexto analizando el lenguaje del Director.

    Args:
        phrases: Lista de frases que disparan la recuperación.
            Si None, usa LEXIC_TRIGGER_PHRASES de config.

    Usage:
        >>> trigger = LexicTrigger()
        >>> if trigger.detect("Ya te dije que no repitas"):
        ...     # disparar recuperación
    """

    def __init__(
        self,
        phrases: Optional[list[str]] = None,
    ) -> None:
        self._phrases = phrases if phrases is not None else LEXIC_TRIGGER_PHRASES
        # Compilar regex para matching case-insensitive
        escaped = [re.escape(p) for p in self._phrases]
        self._pattern = re.compile(
            "|".join(escaped),
            re.IGNORECASE,
        )
        logger.debug(
            "LexicTrigger inicializado: %d frases disparadoras",
            len(self._phrases),
        )

    # ── API pública ────────────────────────────────────────────────

    def detect(self, message: str) -> bool:
        """Detecta si el mensaje del Director contiene frases disparadoras.

        Args:
            message: Texto del mensaje del Director.

        Returns:
            True si se detectó una frase disparadora.
        """
        if not message:
            return False
        return bool(self._pattern.search(message))

    def detect_with_context(
        self,
        message: str,
    ) -> tuple[bool, list[str]]:
        """Detecta y devuelve las frases que coincidieron.

        Args:
            message: Texto del mensaje del Director.

        Returns:
            Tupla (detectado, [frases que coincidieron]).
        """
        if not message:
            return False, []

        matched: list[str] = []
        message_lower = message.lower()
        for phrase in self._phrases:
            if phrase.lower() in message_lower:
                matched.append(phrase)

        return bool(matched), matched

    @property
    def phrases(self) -> list[str]:
        """Lista de frases disparadoras."""
        return list(self._phrases)

    def add_phrase(self, phrase: str) -> None:
        """Añade una frase disparadora (no actualiza el patrón compilado)."""
        if phrase and phrase not in self._phrases:
            self._phrases.append(phrase)

    def __repr__(self) -> str:
        return f"LexicTrigger(phrases={len(self._phrases)})"


if __name__ == "__main__":
    # ── Validación interna de lexic_trigger.py ──
    print("=== Validación de lexic_trigger.py ===\n")

    lt = LexicTrigger()

    # Test 1: detección básica
    assert lt.detect("Ya te dije que esto es así")
    assert lt.detect("no repitas eso otra vez")
    assert lt.detect("estás olvidando lo que acordamos")
    print(f"✓ Detección básica: frases conocidas detectadas")

    # Test 2: case-insensitive
    assert lt.detect("YA TE DIJE")
    assert lt.detect("ya te dije")
    print(f"✓ Case-insensitive: OK")

    # Test 3: mensaje neutro no dispara
    assert not lt.detect("Ejecuta el pytest de server.py")
    assert not lt.detect("Hola, ¿cómo estás?")
    print(f"✓ Mensaje neutro: no dispara")

    # Test 4: detect_with_context devuelve frases
    detected, phrases = lt.detect_with_context("Ya te dije que no repitas eso")
    assert detected
    assert "ya te dije" in phrases
    assert "no repitas" in phrases
    print(f"✓ detect_with_context: {phrases}")

    # Test 5: mensaje vacío
    assert not lt.detect("")
    assert not lt.detect(None or "")
    detected_empty, phrases_empty = lt.detect_with_context("")
    assert not detected_empty
    assert phrases_empty == []
    print(f"✓ Mensaje vacío: manejado correctamente")

    # Test 6: add_phrase
    initial_count = len(lt.phrases)
    lt.add_phrase("nueva frase disparadora")
    assert len(lt.phrases) == initial_count + 1
    print(f"✓ add_phrase: añadida correctamente")

    # Test 7: frases por defecto cargadas
    assert len(lt.phrases) >= 10
    print(f"✓ Frases por defecto: {len(lt.phrases)} cargadas")

    print("\n✅ lexic_trigger.py: todos los tests pasaron")
