# Destino: /home/z/my-project/contexto_zai/processing/block_packer.py
"""Empaquetador de intercambios en bloques temáticos por tamaño (v3.2).

Diferencia crítica respecto a v1.0 (BlockManager):
- v1.0: un bloque por tema. Si un tema supera 70K tokens, lo subdivide
  como `tema_parte1`, `tema_parte2` (prohibido por spec v3.2).
- v3.2: varios temas por bloque, hasta llenar el límite de 70K tokens.
  Si un tema individual supera el límite, lo subdivide en subtemas
  derivados únicos (lo hace Subdivider, no BlockPacker).

Garantías de BlockPacker:
- Ningún bloque supera MAX_TOKENS_BLOQUE.
- Un tema (o subtema) vive en un solo archivo (unicidad).
- Si un intercambio individual no cabe solo en un bloque vacío,
  se reporta como error (debería haberse subdividido antes).

Atómico standalone: importa config y models, nada más del proyecto.
"""

from __future__ import annotations

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

    # ── API pública ────────────────────────────────────────────────

    def pack(
        self,
        exchanges_by_topic: dict[str, list[Exchange]],
    ) -> list[ThematicBlock]:
        """Empaqueta intercambios en bloques por tamaño.

        Estrategia:
        1. Para cada tema, procesar sus intercambios.
        2. Si el tema individual cabe en un bloque, se añade al bloque actual
           si hay espacio, o se crea un bloque nuevo.
        3. Si el tema individual supera el límite, se reporta: debe
           subdividirse antes (Subdivider).

        Args:
            exchanges_by_topic: Diccionario {tema: [intercambios]}.

        Returns:
            Lista de ThematicBlock, cada uno con uno o varios temas.

        Raises:
            ValueError: Si un tema individual supera el límite de tokens
                (debe subdividirse antes con Subdivider).
        """
        blocks: list[ThematicBlock] = []
        block_counter = 0
        current_block: Optional[ThematicBlock] = None

        # Procesar temas ordenados por nombre (determinístico)
        for tema in sorted(exchanges_by_topic.keys()):
            exchanges = exchanges_by_topic[tema]
            if not exchanges:
                continue

            # Verificar que el tema completo cabe en un bloque
            tema_tokens = sum(ex.estimated_tokens for ex in exchanges)
            if tema_tokens > self._max_tokens:
                raise ValueError(
                    f"Tema '{tema}' supera el límite de tokens "
                    f"({tema_tokens:.0f} > {self._max_tokens}). "
                    f"Debe subdividirse con Subdivider antes de empaquetar."
                )

            # Intentar añadir el tema al bloque actual, o crear uno nuevo
            added = False
            if current_block is not None:
                # Verificar si todos los intercambios caben en el bloque actual
                if self._tema_fits_in_block(exchanges, current_block):
                    for ex in exchanges:
                        current_block.add_exchange(ex)
                    added = True
                    logger.debug(
                        "Tema '%s' añadido a bloque existente %s (%d intercambios)",
                        tema, current_block.filename, len(exchanges),
                    )

            if not added:
                # Crear bloque nuevo
                block_counter += 1
                current_block = ThematicBlock(
                    filename=f"bloque_{block_counter:02d}.md",
                )
                # Verificar que el primer intercambio del tema cabe
                if not self._tema_fits_in_block(exchanges, current_block):
                    # El tema no cabe ni siquiera en un bloque vacío
                    # Esto no debería pasar porque ya validamos arriba
                    raise ValueError(
                        f"Tema '{tema}' no cabe en un bloque vacío "
                        f"(inconsistencia interna)"
                    )
                for ex in exchanges:
                    current_block.add_exchange(ex)
                blocks.append(current_block)
                logger.debug(
                    "Tema '%s' inició nuevo bloque %s (%d intercambios, %.0f tokens)",
                    tema, current_block.filename, len(exchanges), tema_tokens,
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

    # ── Propiedades ────────────────────────────────────────────────

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

    # ── Métodos privados ───────────────────────────────────────────

    def _tema_fits_in_block(
        self,
        exchanges: list[Exchange],
        block: ThematicBlock,
    ) -> bool:
        """Verifica si añadir todos los intercambios del tema cabe en el bloque."""
        new_tokens = sum(ex.estimated_tokens for ex in exchanges)
        return (block.estimated_tokens + new_tokens) <= self._max_tokens


if __name__ == "__main__":
    # ── Validación interna de block_packer.py (atómico standalone) ──
    print("=== Validación de block_packer.py ===\n")

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
    print(f"✓ Un tema, un bloque: {blocks1[0].filename} con {blocks1[0].exchange_count} intercambio")

    # Test 2: varios temas en un solo bloque (si caben)
    exchanges_2 = [
        Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="test pytest"), topic="validaciones", start_timestamp=1, end_timestamp=2),
        Exchange(id=2, director_msg=Message(seq=2, role=MessageRole.USER, timestamp=3, content="worklog repositorio"), topic="configuracion_proyecto", start_timestamp=3, end_timestamp=4),
    ]
    blocks2 = packer.pack_from_exchanges(exchanges_2)
    assert len(blocks2) == 1, f"Esperaba 1 bloque, obtuve {len(blocks2)}"
    assert set(blocks2[0].temas) == {"configuracion_proyecto", "validaciones"}
    print(f"✓ Varios temas en un bloque: {blocks2[0].temas}")

    # Test 3: tema que supera el límite → ValueError
    big_exchanges = [
        Exchange(id=i, director_msg=Message(seq=i, role=MessageRole.USER, timestamp=i, content="x" * 5000), topic="general", start_timestamp=i, end_timestamp=i+1)
        for i in range(1, 6)  # 5 intercambios de ~1428 tokens cada uno = 7140 tokens
    ]
    try:
        packer.pack_from_exchanges(big_exchanges)
        assert False, "Debería haber lanzado ValueError"
    except ValueError as e:
        assert "supera el límite" in str(e)
        print(f"✓ Tema que supera límite: ValueError correcto")

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
    print(f"✓ Tema que llena bloque, siguiente tema en bloque nuevo: {len(blocks4)} bloques")

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
    print(f"✓ Unicidad temática: 'validaciones' en un solo bloque ({all_tema_files[0]})")

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
    print(f"✓ Ningún bloque supera el límite: {len(blocks6)} bloques generados")

    # Test 7: max_chars es correcto
    assert packer_real.max_chars == int(70_000 * 3.5)
    print(f"✓ max_chars: {packer_real.max_chars}")

    print("\n✅ block_packer.py: todos los tests pasaron")
