# Destino: /home/z/my-project/tests/test_classifier_packer_subdivider.py
"""Test de integración: clasificador + empaquetador + subdivider (v3.2).

Valida la funcionalidad colectiva de los 3 módulos de procesamiento
multi-tema:
1. MessageClassifier clasifica intercambios en temas.
2. Subdivider subdivide temas grandes en subtemas únicos.
3. BlockPacker empaqueta varios temas en bloques por tamaño.

Invariante garantizada:
- Ningún bloque supera 70K tokens.
- Un tema (o subtema) vive en un solo archivo (unicidad).
- Los subtemas generados son únicos (no "parte1/parte2").
"""

from __future__ import annotations

import sys
from pathlib import Path

# Añadir el workspace al path para importar contexto_zai
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

from contexto_zai.processing.block_packer import BlockPacker
from contexto_zai.processing.classifier import MessageClassifier
from contexto_zai.processing.subdivider import Subdivider
from contexto_zai.models import Exchange, Message, MessageRole


def make_exchange(ex_id: int, content: str, topic: str = "", ts: int = 0) -> Exchange:
    """Crea un intercambio de prueba."""
    return Exchange(
        id=ex_id,
        director_msg=Message(seq=ex_id * 2 - 1, role=MessageRole.USER, timestamp=ts, content=content),
        agent_msgs=[Message(seq=ex_id * 2, role=MessageRole.ASSISTANT, timestamp=ts + 1, content=f"Respuesta {ex_id}")],
        topic=topic,
        start_timestamp=ts,
        end_timestamp=ts + 1,
    )


def test_classifier_packer_basic_integration():
    """Test 1: clasificador + empaquetador: 2 temas → 1 bloque si caben."""
    print("\n=== Test 1: clasificador + empaquetador básico ===")
    cl = MessageClassifier()
    packer = BlockPacker()

    exchanges = [
        make_exchange(1, "Ejecuta pytest de server.py", ts=100),
        make_exchange(2, "Lee el worklog del proyecto", ts=200),
    ]
    cl.classify_exchanges(exchanges)

    # Ambos temas son pequeños, deben caber en 1 bloque
    blocks = packer.pack_from_exchanges(exchanges)
    assert len(blocks) == 1, f"Esperaba 1 bloque, obtuve {len(blocks)}"
    assert set(blocks[0].temas) == {"validaciones", "configuracion_proyecto"}
    print(f"  ✓ 2 temas en 1 bloque: {blocks[0].temas}")
    print(f"  ✅ PASÓ")


def test_subdivider_no_subdivision_when_small():
    """Test 2: subdivider no subdivide temas pequeños."""
    print("\n=== Test 2: subdivider respeta temas pequeños ===")
    sub = Subdivider()
    exchanges = [make_exchange(i, f"test {i}", ts=i * 10) for i in range(1, 4)]
    result = sub.subdivide("validaciones", exchanges)
    assert len(result.subtemas) == 1
    assert result.subtemas[0][0] == "validaciones"
    print(f"  ✓ Tema pequeño no se subdivide")
    print(f"  ✅ PASÓ")


def test_subdivider_generates_unique_subtemas():
    """Test 3: subdivider genera subtemas únicos (no parte1/parte2)."""
    print("\n=== Test 3: subdivider genera subtemas únicos ===")
    # Forzar subdivisión léxica para 'validaciones' (tiene SUBTEMAS_LEXICOS)
    sub = Subdivider(max_tokens_per_block=500)  # límite bajo
    # 40 intercambios con sub-palabras diferentes
    exchanges = [
        make_exchange(
            i,
            f"test {['server', 'router', 'broker', 'general'][i % 4]} " + "y" * 80,
            ts=i * 10,
        )
        for i in range(1, 41)
    ]
    result = sub.subdivide("validaciones", exchanges)
    subtema_names = [name for name, _ in result.subtemas]
    # Deben ser subtemas con prefijo 'validaciones_'
    assert all(name.startswith("validaciones_") for name in subtema_names), f"Nombres: {subtema_names}"
    # Deben ser únicos
    assert len(subtema_names) == len(set(subtema_names)), f"Subtemas duplicados: {subtema_names}"
    # NO deben ser "parte1/parte2"
    assert not any("parte1" in name or "parte2" in name for name in subtema_names), f"Usó parte1/parte2: {subtema_names}"
    print(f"  ✓ Subtemas únicos generados: {subtema_names}")
    print(f"  ✅ PASÓ")


def test_packer_no_block_exceeds_limit():
    """Test 4: ningún bloque supera 70K tokens."""
    print("\n=== Test 4: límite de 70K tokens por bloque ===")
    packer = BlockPacker()  # 70K tokens por defecto
    # 50 intercambios grandes en temas diferentes
    exchanges = [
        make_exchange(i, "x" * 1000, topic=f"tema_{i}", ts=i * 10)
        for i in range(1, 51)
    ]
    blocks = packer.pack_from_exchanges(exchanges)
    for b in blocks:
        assert b.estimated_tokens <= 70_000, f"Bloque {b.filename} supera 70K: {b.estimated_tokens:.0f}"
    print(f"  ✓ {len(blocks)} bloques, ninguno supera 70K tokens")
    print(f"  ✅ PASÓ")


def test_unicity_tematica_one_tema_one_file():
    """Test 5: un tema vive en un solo archivo (unicidad)."""
    print("\n=== Test 5: unicidad temática ===")
    cl = MessageClassifier()
    packer = BlockPacker()
    exchanges = [
        make_exchange(1, "test pytest", topic="validaciones", ts=1),
        make_exchange(2, "test pytest otra vez", topic="validaciones", ts=2),
        make_exchange(3, "test pytest tercera", topic="validaciones", ts=3),
    ]
    cl.classify_exchanges(exchanges)
    blocks = packer.pack_from_exchanges(exchanges)
    # Todos los intercambios de 'validaciones' deben estar en un solo bloque
    blocks_with_validaciones = [b for b in blocks if "validaciones" in b.temas]
    assert len(blocks_with_validaciones) == 1, f"Tema en {len(blocks_with_validaciones)} bloques, debería ser 1"
    print(f"  ✓ 'validaciones' en un solo archivo: {blocks_with_validaciones[0].filename}")
    print(f"  ✅ PASÓ")


def test_full_pipeline_subdivide_then_pack():
    """Test 6: pipeline completo clasificar → subdividir → empaquetar."""
    print("\n=== Test 6: pipeline completo multi-tema ===")
    cl = MessageClassifier()
    sub = Subdivider(max_tokens_per_block=1000)
    packer = BlockPacker(max_tokens_per_block=1000)

    # 30 intercambios en 3 temas
    exchanges = []
    for i in range(30):
        tema_idx = i % 3
        if tema_idx == 0:
            content = f"test pytest server router broker {i}"
        elif tema_idx == 1:
            content = f"worklog proyecto repositorio {i}"
        else:
            content = f"DCPA contrato metodología sesión {i}"
        exchanges.append(make_exchange(i + 1, content, ts=i * 10))

    # Clasificar
    cl.classify_exchanges(exchanges)

    # Agrupar por tema
    by_topic = {}
    for ex in exchanges:
        by_topic.setdefault(ex.topic, []).append(ex)

    # Subdividir temas grandes
    expanded = {}
    for tema, exs in by_topic.items():
        if sub.needs_subdivision(tema, exs):
            result = sub.subdivide(tema, exs)
            for name, sub_exs in result.subtemas:
                for ex in sub_exs:
                    ex.topic = name
                expanded[name] = sub_exs
        else:
            expanded[tema] = exs

    # Empaquetar
    blocks = packer.pack(expanded)

    # Verificar límites y unicidad
    seen_temas = {}
    for b in blocks:
        assert b.estimated_tokens <= 1000, f"Bloque {b.filename} supera 1000 tokens: {b.estimated_tokens:.0f}"
        for t in b.temas:
            assert t not in seen_temas, f"Tema {t} duplicado en {seen_temas[t]} y {b.filename}"
            seen_temas[t] = b.filename

    print(f"  ✓ {len(blocks)} bloques, {len(seen_temas)} temas únicos, todos < 1000 tokens")
    print(f"  ✅ PASÓ")


def main():
    """Ejecuta todos los tests de integración."""
    print("=" * 60)
    print("TEST DE INTEGRACIÓN: classifier + packer + subdivider")
    print("=" * 60)
    tests = [
        test_classifier_packer_basic_integration,
        test_subdivider_no_subdivision_when_small,
        test_subdivider_generates_unique_subtemas,
        test_packer_no_block_exceeds_limit,
        test_unicity_tematica_one_tema_one_file,
        test_full_pipeline_subdivide_then_pack,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except (AssertionError, Exception) as e:
            print(f"  ❌ FALLÓ: {e}")
            failed += 1
    print(f"\n{'=' * 60}")
    print(f"RESULTADO: {passed} pasaron, {failed} fallaron de {len(tests)} tests")
    print(f"{'=' * 60}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
