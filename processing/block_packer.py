# contexto_zai/processing/block_packer.py -- Empaquetador de bloques: agrupa varios temas en archivos de hasta 70K tokens (multi-bloque v6.0).
"""Empaquetador de intercambios en bloques temáticos por tamaño (v6.0).

Diferencia crítica respecto a v1.0 (BlockManager):
- v1.0: un bloque por tema. Si un tema supera 70K tokens, lo subdivide
  como `tema_parte1`, `tema_parte2` (prohibido por spec v3.2).
- v3.2: varios temas por bloque, hasta llenar el límite de 70K tokens.
  Si un tema individual supera el límite, lo subdivide en subtemas
  derivados únicos (lo hace Subdivider, no BlockPacker).
- v6.0: si un tema individual supera el límite, NO lanza error ni subdividirá.
  Reparte sus intercambios en varios bloques consecutivos (multi-bloque).
  El mismo nombre de tema puede aparecer en múltiples archivos.

Garantías de BlockPacker (v6.0):
- Ningún bloque supera MAX_TOKENS_BLOQUE.
- Un tema puede abarcar varios bloques (multi-bloque v6.0).
- Si un intercambio individual no cabe solo en un bloque vacío,
  se reporta como error (intercambio demasiado grande).

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
from typing import Optional

from contexto_zai.config import TOKEN_LIMITS
from contexto_zai.models import Exchange, ThematicBlock

logger = logging.getLogger(__name__)

class BlockPacker:
    """Empaqueta intercambios clasificados en bloques por tamaño.

    Args:
        max_tokens_per_block: Límite de tokens por bloque.
            Por defecto usa TOKEN_LIMITS.max_tokens_bloque (70K).

    Usage:
        >>> packer = BlockPacker()
        >>> blocks = packer.pack(exchanges_by_topic={"validaciones": [...], "general": [...]})
        >>> # Devuelve lista de ThematicBlock, cada uno con varios temas
    """

    def __init__(
        self,
        max_tokens_per_block: int = TOKEN_LIMITS.max_tokens_bloque,
    ) -> None:
        self._max_tokens = max_tokens_per_block
        logger.debug(
            "BlockPacker inicializado: max_tokens=%d (%d chars)",
            max_tokens_per_block,
            max_tokens_per_block * 3.5,
        )

    # -- API pública ------------------------------------------------

    def pack(
        self,
        exchanges_by_topic: dict[str, list[Exchange]],
    ) -> list[ThematicBlock]:
        """Empaqueta intercambios en bloques por tamaño (v6.0 multi-bloque).

        Estrategia:
        1. Para cada tema, procesar sus intercambios.
        2. Si el tema completo cabe en el bloque actual, se añade ahí.
        3. Si no cabe pero es más chico que el límite, se crea un bloque nuevo.
        4. Si el tema supera el límite individual, se reparte en varios
           bloques consecutivos (multi-bloque v6.0): se van añadiendo
           intercambios al bloque actual hasta llenarlo, luego se pasa
           al siguiente bloque, y así sucesivamente. El mismo tema puede
           aparecer en múltiples archivos.

        Args:
            exchanges_by_topic: Diccionario {tema: [intercambios]}.

        Returns:
            Lista de ThematicBlock, cada uno con uno o varios temas.

        Raises:
            ValueError: Solo si un intercambio individual no cabe en un
                bloque vacío (es demasiado grande para cualquier bloque).
        """
        blocks: list[ThematicBlock] = []
        block_counter = 0
        current_block: Optional[ThematicBlock] = None

        # Procesar temas ordenados por nombre (determinístico)
        for tema in sorted(exchanges_by_topic.keys()):
            exchanges = exchanges_by_topic[tema]
            if not exchanges:
                continue

            tema_tokens = sum(ex.estimated_tokens for ex in exchanges)
            tema_es_grande = tema_tokens > self._max_tokens

            if not tema_es_grande:
                # Intentar añadir el tema completo al bloque actual, o crear uno nuevo
                added = False
                if current_block is not None:
                    if self._tema_fits_in_block(exchanges, current_block):
                        for ex in exchanges:
                            current_block.add_exchange(ex)
                        added = True
                        logger.debug(
                            "Tema '%s' anadido a bloque existente %s (%d intercambios)",
                            tema, current_block.filename, len(exchanges),
                        )

                if not added:
                    block_counter += 1
                    current_block = ThematicBlock(
                        filename=f"bloque_{block_counter:02d}.md",
                    )
                    for ex in exchanges:
                        current_block.add_exchange(ex)
                    blocks.append(current_block)
                    logger.debug(
                        "Tema '%s' inicio nuevo bloque %s (%d intercambios, %.0f tokens)",
                        tema, current_block.filename, len(exchanges), tema_tokens,
                    )
            else:
                # v6.0: tema grande -> repartir en varios bloques consecutivos
                logger.info(
                    "Tema '%s' supera el limite (%.0f > %d tokens). "
                    "Repartiendo en varios bloques (multi-bloque v6.0).",
                    tema, tema_tokens, self._max_tokens,
                )
                for ex in exchanges:
                    # Si no hay bloque actual o el exchange no cabe, crear uno nuevo
                    if current_block is None or current_block.would_exceed_limit(
                        ex, self._max_tokens
                    ):
                        # Si el exchange individual no cabe ni en bloque vacío, error
                        if ex.estimated_tokens > self._max_tokens:
                            raise ValueError(
                                f"Intercambio del tema '{tema}' es demasiado grande "
                                f"({ex.estimated_tokens:.0f} > {self._max_tokens} tokens). "
                                f"No cabe en ningún bloque."
                            )
                        block_counter += 1
                        current_block = ThematicBlock(
                            filename=f"bloque_{block_counter:02d}.md",
                        )
                        blocks.append(current_block)
                    current_block.add_exchange(ex)
                logger.debug(
                    "Tema grande '%s' repartido en bloques (termina en %s)",
                    tema, current_block.filename if current_block else "?",
                )

        logger.info(
            "Empaquetado completo: %d bloques para %d temas",
            len(blocks),
            len(exchanges_by_topic),
        )
        return blocks

    def pack_from_exchanges(
        self,
        exchanges: list[Exchange],
    ) -> list[ThematicBlock]:
        """Empaqueta una lista plana de intercambios ya clasificados.

        Agrupa por tema internamente y delega a `pack`.

        Args:
            exchanges: Lista de intercambios con `.topic` asignado.

        Returns:
            Lista de ThematicBlock.
        """
        by_topic: dict[str, list[Exchange]] = {}
        for ex in exchanges:
            by_topic.setdefault(ex.topic, []).append(ex)
        return self.pack(by_topic)

    # -- Propiedades ------------------------------------------------

    @property
    def max_tokens(self) -> int:
        """Límite de tokens por bloque."""
        return self._max_tokens

    @property
    def max_chars(self) -> int:
        """Límite de chars por bloque (tokens * 3.5)."""
        return int(self._max_tokens * 3.5)

    def __repr__(self) -> str:
        return f"BlockPacker(max_tokens={self._max_tokens})"

    # -- Métodos privados -------------------------------------------

    def _tema_fits_in_block(
        self,
        exchanges: list[Exchange],
        block: ThematicBlock,
    ) -> bool:
        """Verifica si añadir todos los intercambios del tema cabe en el bloque."""
        new_tokens = sum(ex.estimated_tokens for ex in exchanges)
        return (block.estimated_tokens + new_tokens) <= self._max_tokens

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
    # -- Validación interna de block_packer.py (atómico standalone) --
    print("=== Validacion de block_packer.py ===\n")

    from contexto_zai.models import Message, MessageRole

    packer = BlockPacker(max_tokens_per_block=1000)  # límite bajo para tests

    # Test 1: un tema, un bloque
    exchanges_1 = [
        Exchange(
            id=1,
            director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="test pytest"),
            topic="validaciones",
            start_timestamp=1,
            end_timestamp=2,
        ),
    ]
    blocks1 = packer.pack_from_exchanges(exchanges_1)
    assert len(blocks1) == 1
    assert "validaciones" in blocks1[0].temas
    print(f"[OK] Un tema, un bloque: {blocks1[0].filename} con {blocks1[0].exchange_count} intercambio")

    # Test 2: varios temas en un solo bloque (si caben)
    exchanges_2 = [
        Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="test pytest"), topic="validaciones", start_timestamp=1, end_timestamp=2),
        Exchange(id=2, director_msg=Message(seq=2, role=MessageRole.USER, timestamp=3, content="worklog repositorio"), topic="configuracion_proyecto", start_timestamp=3, end_timestamp=4),
    ]
    blocks2 = packer.pack_from_exchanges(exchanges_2)
    assert len(blocks2) == 1, f"Esperaba 1 bloque, obtuve {len(blocks2)}"
    assert set(blocks2[0].temas) == {"configuracion_proyecto", "validaciones"}
    print(f"[OK] Varios temas en un bloque: {blocks2[0].temas}")

    # Test 3: tema que supera el límite -> multi-bloque (v6.0)
    # Cada intercambio cabe individualmente (~285 tokens), pero el tema
    # completo (5 * 285 = 1428) supera el límite (1000).
    big_exchanges = [
        Exchange(id=i, director_msg=Message(seq=i, role=MessageRole.USER, timestamp=i, content="x" * 1000), topic="general", start_timestamp=i, end_timestamp=i+1)
        for i in range(1, 6)  # 5 intercambios de ~285 tokens cada uno = 1428 tokens
    ]
    blocks3 = packer.pack_from_exchanges(big_exchanges)
    assert len(blocks3) > 1, f"Esperaba varios bloques (multi-bloque), obtuve {len(blocks3)}"
    # Ningún bloque supera el límite
    for b in blocks3:
        assert b.estimated_tokens <= packer.max_tokens, (
            f"Bloque {b.filename} supera el limite: {b.estimated_tokens:.0f} > {packer.max_tokens}"
        )
    # El tema 'general' puede estar en varios bloques
    bloques_con_general = [b.filename for b in blocks3 if "general" in b.temas]
    assert len(bloques_con_general) >= 1, "El tema 'general' debería estar en al menos un bloque"
    print(f"[OK] Tema grande repartido en {len(blocks3)} bloques (multi-bloque v6.0)")

    # Test 4: cuando un tema llena el bloque, el siguiente tema va a bloque nuevo
    exchanges_4 = [
        # Tema A: llena el bloque casi completo (5 intercambios de ~285 tokens = 1425)
        *[Exchange(id=i, director_msg=Message(seq=i, role=MessageRole.USER, timestamp=i, content="x" * 1000), topic="tema_a", start_timestamp=i, end_timestamp=i+1) for i in range(1, 6)],
        # Tema B: 1 intercambio que no cabe en el bloque A (1425 + 285 = 1710 > 1500)
        Exchange(id=10, director_msg=Message(seq=10, role=MessageRole.USER, timestamp=10, content="y" * 1000), topic="tema_b", start_timestamp=10, end_timestamp=11),
    ]
    packer_4 = BlockPacker(max_tokens_per_block=1500)
    blocks4 = packer_4.pack_from_exchanges(exchanges_4)
    assert len(blocks4) >= 2, f"Esperaba >=2 bloques, obtuve {len(blocks4)}"
    print(f"[OK] Tema que llena bloque, siguiente tema en bloque nuevo: {len(blocks4)} bloques")

    # Test 5: unicidad temática (un tema vive en un solo archivo)
    exchanges_5 = [
        Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="test"), topic="validaciones", start_timestamp=1, end_timestamp=2),
        Exchange(id=2, director_msg=Message(seq=2, role=MessageRole.USER, timestamp=3, content="test"), topic="validaciones", start_timestamp=3, end_timestamp=4),
        Exchange(id=3, director_msg=Message(seq=3, role=MessageRole.USER, timestamp=5, content="test"), topic="validaciones", start_timestamp=5, end_timestamp=6),
    ]
    blocks5 = packer.pack_from_exchanges(exchanges_5)
    # Todas los intercambios de "validaciones" deben estar en un solo bloque
    all_tema_files = [b.filename for b in blocks5 if "validaciones" in b.temas]
    assert len(all_tema_files) == 1, f"El tema aparece en {len(all_tema_files)} bloques, debería ser 1"
    print(f"[OK] Unicidad tematica: 'validaciones' en un solo bloque ({all_tema_files[0]})")

    # Test 6: ningún bloque supera el límite
    packer_real = BlockPacker()  # 70K tokens por defecto
    exchanges_6 = [
        Exchange(id=i, director_msg=Message(seq=i, role=MessageRole.USER, timestamp=i, content="x" * 1000), topic=f"tema_{i}", start_timestamp=i, end_timestamp=i+1)
        for i in range(1, 50)  # 49 intercambios de 49 temas diferentes
    ]
    blocks6 = packer_real.pack_from_exchanges(exchanges_6)
    for b in blocks6:
        assert b.estimated_tokens <= packer_real.max_tokens, (
            f"Bloque {b.filename} supera el límite: {b.estimated_tokens:.0f} > {packer_real.max_tokens}"
        )
    print(f"[OK] Ningun bloque supera el limite: {len(blocks6)} bloques generados")

    # Test 7: max_chars es correcto
    assert packer_real.max_chars == int(70_000 * 3.5)
    print(f"[OK] max_chars: {packer_real.max_chars}")

    print("\n[PASS] block_packer.py: todos los tests pasaron")
