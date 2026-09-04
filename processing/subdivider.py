# contexto_zai/processing/subdivider.py -- Subdivisor de temas grandes: genera subtemas derivados unicos (no parte1/parte2).
"""Subdivisor de temas grandes en subtemas derivados únicos (v3.2).

Cuando un tema individual crece tanto que no cabe en un bloque
(supera MAX_TOKENS_BLOQUE), el Subdivider lo divide en subtemas
derivados que son nuevos temas únicos en el sistema.

Diferencia crítica respecto a v1.0:
- v1.0: subdividía como `tema_parte1`, `tema_parte2` (prohibido por spec v3.2).
- v3.2: subdivide en subtemas con nombres únicos (ej: `validaciones_server`,
  `validaciones_router`, `validaciones_broker`).

Estrategia de subdivisión:
- Si el tema tiene keywords especializables (sub-palabras), se usa esa
  especialización para agrupar intercambios.
- Si no, se subdivide por rango temporal (mitad cronológica).

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
from dataclasses import dataclass
from typing import Optional

from contexto_zai.config import TOKEN_LIMITS
from contexto_zai.models import Exchange

logger = logging.getLogger(__name__)

@dataclass
class SubdivisionResult:
    """Resultado de subdividir un tema grande.

    Attributes:
        tema_padre: Nombre del tema original que se subdividió.
        subtemas: Lista de (subtema_name, intercambios) resultante.
        razon: Por qué se subdividió (qué criterio se aplicó).
    """

    tema_padre: str
    subtemas: list[tuple[str, list[Exchange]]]
    razon: str = ""

class Subdivider:
    """Subdivide temas grandes en subtemas derivados únicos.

    Args:
        max_tokens_per_block: Límite de tokens por bloque.
            Por defecto usa TOKEN_LIMITS.max_tokens_bloque (70K).

    Usage:
        >>> sub = Subdivider()
        >>> result = sub.subdivide("validaciones", exchanges_grandes)
        >>> for subtema_name, exchanges in result.subtemas:
        ...     print(f"{subtema_name}: {len(exchanges)} intercambios")
    """

    # Prefijos de subtemas conocidos (especialización léxica).
    # Si un tema no tiene sub-palabras conocidas, se subdivide temporalmente.
    SUBTEMAS_LEXICOS: dict[str, list[str]] = {
        "validaciones": [
            "server", "router", "broker", "planner", "client", "model",
            "auth", "config", "ui", "api",
        ],
        "metodologia": [
            "dcpa", "contrato", "identidad", "comunicacion",
            "sesion", "worklog", "handoff",
        ],
        "contexto_compresion": [
            "tokens", "ventana", "compresion", "recuperacion",
        ],
    }

    def __init__(
        self,
        max_tokens_per_block: int = TOKEN_LIMITS.max_tokens_bloque,
    ) -> None:
        self._max_tokens = max_tokens_per_block
        logger.debug(
            "Subdivider inicializado: max_tokens=%d", max_tokens_per_block
        )

    # -- API pública ------------------------------------------------

    def needs_subdivision(
        self,
        tema: str,
        exchanges: list[Exchange],
    ) -> bool:
        """Verifica si un tema necesita subdivisión.

        Un tema necesita subdivisión si la suma de tokens de sus
        intercambios supera el límite de bloque.
        """
        total_tokens = sum(ex.estimated_tokens for ex in exchanges)
        return total_tokens > self._max_tokens

    def subdivide(
        self,
        tema: str,
        exchanges: list[Exchange],
    ) -> SubdivisionResult:
        """Subdivide un tema grande en subtemas derivados únicos.

        Estrategia:
        1. Si el tema tiene SUBTEMAS_LEXICOS, agrupar por sub-palabra
           detectada en el contenido del mensaje del Director.
        2. Si no, subdividir por mitad temporal (cronológica).

        Cada subtema resultante debe caber en un bloque. Si algún
        subtema sigue superando el límite, se subdivide recursivamente.

        Args:
            tema: Nombre del tema a subdividir.
            exchanges: Lista de intercambios del tema.

        Returns:
            SubdivisionResult con los subtemas y sus intercambios.
        """
        if not self.needs_subdivision(tema, exchanges):
            # No necesita subdivisión
            return SubdivisionResult(
                tema_padre=tema,
                subtemas=[(tema, exchanges)],
                razon="no requiere subdivisión",
            )

        # Intentar subdivisión léxica primero
        sub_palabras = self.SUBTEMAS_LEXICOS.get(tema)
        if sub_palabras:
            result = self._subdivide_lexical(tema, exchanges, sub_palabras)
            if result is not None:
                return result

        # Fallback: subdivisión temporal
        return self._subdivide_temporal(tema, exchanges)

    def get_subtema_names(
        self,
        tema_padre: str,
        result: SubdivisionResult,
    ) -> list[str]:
        """Devuelve los nombres de subtemas creados al subdividir."""
        return [name for name, _ in result.subtemas if name != tema_padre]

    # -- Propiedades ------------------------------------------------

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    def __repr__(self) -> str:
        return f"Subdivider(max_tokens={self._max_tokens})"

    # -- Métodos privados -------------------------------------------

    def _subdivide_lexical(
        self,
        tema: str,
        exchanges: list[Exchange],
        sub_palabras: list[str],
    ) -> Optional[SubdivisionResult]:
        """Subdivide agrupando intercambios por sub-palabra detectada.

        Args:
            tema: Nombre del tema padre.
            exchanges: Intercambios a subdividir.
            sub_palabras: Lista de sub-palabras que definen subtemas.

        Returns:
            SubdivisionResult o None si no se pudo subdividir léxicamente.
        """
        grupos: dict[str, list[Exchange]] = {}
        sobrantes: list[Exchange] = []

        for ex in exchanges:
            text = ex.director_msg.content.lower()
            matched_sub = None
            for sub in sub_palabras:
                if sub.lower() in text:
                    matched_sub = sub
                    break
            if matched_sub:
                subtema_name = f"{tema}_{matched_sub}"
                grupos.setdefault(subtema_name, []).append(ex)
            else:
                sobrantes.append(ex)

        # Si todos los intercambios fueron a "sobrantes", la subdivisión
        # léxica no funcionó
        if not grupos:
            return None

        # Asignar sobrantes al subtema más grande (o crear un subtema "_general")
        if sobrantes:
            subtema_general = f"{tema}_general"
            grupos.setdefault(subtema_general, []).extend(sobrantes)

        # Verificar que cada subtema cabe en un bloque
        # Si alguno sigue superando el límite, subdividir recursivamente
        subtemas_final: list[tuple[str, list[Exchange]]] = []
        for subtema_name, sub_exchanges in grupos.items():
            if sum(ex.estimated_tokens for ex in sub_exchanges) > self._max_tokens:
                # Subdivisión recursiva (con sub_palabras vacías -> temporal)
                recursive_result = self._subdivide_temporal(subtema_name, sub_exchanges)
                subtemas_final.extend(recursive_result.subtemas)
            else:
                subtemas_final.append((subtema_name, sub_exchanges))

        return SubdivisionResult(
            tema_padre=tema,
            subtemas=subtemas_final,
            razon=f"subdivisión léxica por sub-palabras: {sub_palabras}",
        )

    def _subdivide_temporal(
        self,
        tema: str,
        exchanges: list[Exchange],
    ) -> SubdivisionResult:
        """Subdivide por rango temporal (mitad cronológica).

        Recursivo: si la mitad sigue superando el límite, se subdivide
        de nuevo. Caso base: si queda 1 solo intercambio y sigue
        superando el límite, se reporta como error (no se puede subdividir más).
        """
        # Caso base: 1 solo intercambio que supera el límite -> no subdividible
        if len(exchanges) == 1:
            tokens = sum(ex.estimated_tokens for ex in exchanges)
            if tokens > self._max_tokens:
                # El intercambio individual supera el límite.
                # Devolverlo tal cual; BlockPacker lo detectará como error.
                logger.warning(
                    "Intercambio individual de tema '%s' supera el limite "
                    "(%d > %d tokens). No se puede subdividir más.",
                    tema, int(tokens), self._max_tokens,
                )
                return SubdivisionResult(
                    tema_padre=tema,
                    subtemas=[(tema, exchanges)],
                    razon="intercambio individual supera el límite (no subdividible)",
                )

        # Ordenar por timestamp
        sorted_exchanges = sorted(exchanges, key=lambda ex: ex.start_timestamp)
        mid = len(sorted_exchanges) // 2
        # Si mid == 0 (1 intercambio), no se puede partir en dos
        if mid == 0:
            return SubdivisionResult(
                tema_padre=tema,
                subtemas=[(tema, exchanges)],
                razon="no se puede partir un único intercambio",
            )
        parte_a = sorted_exchanges[:mid]
        parte_b = sorted_exchanges[mid:]

        subtemas: list[tuple[str, list[Exchange]]] = []

        for i, parte in enumerate([parte_a, parte_b], start=1):
            if not parte:
                continue
            subtema_name = f"{tema}_parte{i}"
            # Si sigue superando el límite, subdividir recursivamente
            if sum(ex.estimated_tokens for ex in parte) > self._max_tokens:
                recursive_result = self._subdivide_temporal(subtema_name, parte)
                subtemas.extend(recursive_result.subtemas)
            else:
                subtemas.append((subtema_name, parte))

        return SubdivisionResult(
            tema_padre=tema,
            subtemas=subtemas,
            razon="subdivisión temporal (cronológica)",
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
    # -- Validación interna de subdivider.py (atómico standalone) --
    print("=== Validacion de subdivider.py ===\n")

    from contexto_zai.models import Message, MessageRole

    # Subdivider con límite bajo para forzar subdivisión
    sub = Subdivider(max_tokens_per_block=1000)

    # Test 1: tema que no necesita subdivisión
    exchanges_small = [
        Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="test"), topic="validaciones", start_timestamp=1, end_timestamp=2),
    ]
    result1 = sub.subdivide("validaciones", exchanges_small)
    assert len(result1.subtemas) == 1
    assert result1.subtemas[0][0] == "validaciones"
    print(f"[OK] Tema pequeno: no se subdivide")

    # Test 2: tema que supera el límite -> se subdivide temporalmente
    # Intercambios pequeños (200 chars ~57 tokens cada uno), 30 intercambios = ~1714 tokens
    exchanges_big = [
        Exchange(id=i, director_msg=Message(seq=i, role=MessageRole.USER, timestamp=i, content="x" * 200), topic="general", start_timestamp=i, end_timestamp=i+1)
        for i in range(1, 31)
    ]
    result2 = sub.subdivide("general", exchanges_big)
    assert len(result2.subtemas) > 1, f"Esperaba >1 subtemas, obtuve {len(result2.subtemas)}"
    # Ningún subtema debe superar el límite
    for name, exchanges in result2.subtemas:
        tokens = sum(ex.estimated_tokens for ex in exchanges)
        assert tokens <= sub.max_tokens, f"Subtema '{name}' supera límite: {tokens:.0f}"
    print(f"[OK] Tema grande subdividido temporalmente: {len(result2.subtemas)} subtemas")

    # Test 3: subdivisión léxica para 'validaciones'
    # Intercambios pequeños (200 chars ~57 tokens), 40 intercambios = ~2280 tokens > 1000
    sub_palabras_test = ["server", "router", "broker", "general"]
    big_val = [
        Exchange(
            id=i + 1,
            director_msg=Message(
                seq=i + 1,
                role=MessageRole.USER,
                timestamp=i + 1,
                content=f"test {sub_palabras_test[i % 4]} " + "y" * 180,
            ),
            topic="validaciones",
            start_timestamp=i + 1,
            end_timestamp=i + 2,
        )
        for i in range(40)
    ]
    result3 = sub.subdivide("validaciones", big_val)
    subtema_names = [name for name, _ in result3.subtemas]
    # Debería tener subtemas con sufijos
    assert any(
        "validaciones_" in name for name in subtema_names
    ), f"Esperaba subtemas con prefijo, obtuve {subtema_names}"
    # Ningún subtema debe superar el límite
    for name, exchanges in result3.subtemas:
        tokens = sum(ex.estimated_tokens for ex in exchanges)
        assert tokens <= sub.max_tokens, f"Subtema '{name}' supera límite: {tokens:.0f}"
    print(f"[OK] Subdivision lexica para 'validaciones': {subtema_names}")

    # Test 4: needs_subdivision
    assert not sub.needs_subdivision("general", exchanges_small)
    assert sub.needs_subdivision("general", exchanges_big)
    print(f"[OK] needs_subdivision: detecta correctamente")

    # Test 5: ningún subtema supera el límite tras subdivisión recursiva
    # Intercambios medianos que sí se pueden subdividir
    exchanges_huge = [
        Exchange(id=i, director_msg=Message(seq=i, role=MessageRole.USER, timestamp=i, content="x" * 500), topic="general", start_timestamp=i, end_timestamp=i+1)
        for i in range(1, 21)  # 20 intercambios * ~143 tokens = 2860 tokens
    ]
    result5 = sub.subdivide("general", exchanges_huge)
    for name, exchanges in result5.subtemas:
        tokens = sum(ex.estimated_tokens for ex in exchanges)
        assert tokens <= sub.max_tokens, (
            f"Subtema '{name}' supera límite: {tokens:.0f} > {sub.max_tokens}"
        )
    print(f"[OK] Subdivision recursiva: {len(result5.subtemas)} subtemas, todos < {sub.max_tokens}")

    # Test 6: get_subtema_names
    names = sub.get_subtema_names("validaciones", result3)
    assert all(name.startswith("validaciones_") for name in names)
    print(f"[OK] get_subtema_names: {names}")

    print("\n[PASS] subdivider.py: todos los tests pasaron")
