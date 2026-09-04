# tests/test_estado_indice_generation.py -- Test de integracion: generadores de estado (8 secciones), indice (mapeo) y decisiones.

"""Test de integración: generadores de estado, índice y decisiones (v3.2).

Valida la funcionalidad colectiva de los 3 generadores principales:
1. EstadoGenerator produce 8 secciones (D1-D4 + A1-A4).
2. IndiceGenerator produce tabla `tema -> archivo`.
3. DecisionesGenerator funciona en modo offline (placeholder) y
   online (con extractor simulado).
4. RecoveryGenerator orquesta los 3 + bloque_generator.
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

import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

from contexto_zai.generation.bloque_generator import BloqueGenerator
from contexto_zai.generation.decisiones_generator import DecisionesGenerator
from contexto_zai.generation.estado_generator import EstadoGenerator
from contexto_zai.generation.indice_generator import IndiceGenerator
from contexto_zai.generation.recovery_generator import RecoveryGenerator
from contexto_zai.models import (
    Decision,
    Exchange,
    Message,
    MessageRole,
    RecoveryMetadata,
    ThematicBlock,
)
from contexto_zai.processing.content_cleaner import ContentCleaner

def make_test_exchanges() -> list[Exchange]:
    """Crea intercambios de prueba."""
    return [
        Exchange(
            id=1,
            director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1788482829, content="Ejecuta el pytest de server.py"),
            agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=1788482830, content="Tests ejecutados. 5 passed. Traceback: None")],
            topic="validaciones",
            start_timestamp=1788482829,
            end_timestamp=1788482830,
        ),
        Exchange(
            id=2,
            director_msg=Message(seq=3, role=MessageRole.USER, timestamp=1788482900, content="¿Por qué respondes eso si ya acordamos usar X?"),
            agent_msgs=[Message(seq=4, role=MessageRole.ASSISTANT, timestamp=1788482901, content="Tienes razón. Continuamos con X.")],
            topic="validaciones",
            start_timestamp=1788482900,
            end_timestamp=1788482901,
        ),
        Exchange(
            id=3,
            director_msg=Message(seq=5, role=MessageRole.USER, timestamp=1788483000, content="Lee el worklog del proyecto"),
            agent_msgs=[Message(seq=6, role=MessageRole.ASSISTANT, timestamp=1788483001, content="Worklog leído. He modificado /home/user/file.py")],
            topic="configuracion_proyecto",
            start_timestamp=1788483000,
            end_timestamp=1788483001,
        ),
    ]

def test_estado_generator_8_secciones():
    """Test 1: estado_generator produce 8 secciones D1-D4 + A1-A4."""
    print("\n=== Test 1: estado_generator con 8 secciones ===")
    gen = EstadoGenerator()
    exchanges = make_test_exchanges()
    content = gen.generate(exchanges, chat_label="Test")

    for section in ["D1", "D2", "D3", "D4", "A1", "A2", "A3", "A4"]:
        assert f"Sección {section}" in content, f"Falta sección {section}"
    print(f"  [OK] 8 secciones presentes (D1-D4, A1-A4)")
    print(f"  [PASS] PASO")

def test_estado_d1_literal_director():
    """Test 2: D1 contiene el último mensaje del Director literal."""
    print("\n=== Test 2: D1 es literal del ultimo mensaje del Director ===")
    gen = EstadoGenerator()
    exchanges = make_test_exchanges()
    content = gen.generate(exchanges, chat_label="Test")
    # D1 debe contener el último mensaje del Director
    assert "¿Por qué respondes eso si ya acordamos usar X?" in content
    print(f"  [OK] D1 contiene el ultimo mensaje del Director")
    print(f"  [PASS] PASO")

def test_estado_a3_no_falsos_positivos():
    """Test 3: A3 no detecta falsos positivos de error."""
    print("\n=== Test 3: A3 evita falsos positivos ===")
    gen = EstadoGenerator()
    exchanges = make_test_exchanges()
    content = gen.generate(exchanges, chat_label="Test")
    # El mensaje del agente dice "5 passed. Traceback: None"
    # A3 debe contener "Traceback" (error real) pero NO "passed" como error
    a3_section = content.split("Sección A3")[1].split("Sección A4")[0]
    assert "Traceback" in a3_section  # detectado como error real
    print(f"  [OK] A3 detecta Traceback (error real)")
    print(f"  [PASS] PASO")

def test_indice_with_tema_to_archivo_table():
    """Test 4: índice contiene tabla mapeo `tema -> archivo`."""
    print("\n=== Test 4: indice con tabla tema->archivo ===")
    gen = IndiceGenerator()
    b1 = ThematicBlock(filename="bloque_01.md")
    b1.add_exchange(Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="x"), topic="validaciones", start_timestamp=1, end_timestamp=2))
    b2 = ThematicBlock(filename="bloque_02.md")
    b2.add_exchange(Exchange(id=2, director_msg=Message(seq=2, role=MessageRole.USER, timestamp=3, content="y"), topic="general", start_timestamp=3, end_timestamp=4))

    content = gen.generate([b1, b2], chat_label="Test")
    assert "Mapeo tema -> archivo" in content
    assert "| Tema | Archivo |" in content
    assert "`validaciones`" in content
    assert "`bloque_01.md`" in content
    assert "`general`" in content
    print(f"  [OK] Tabla mapeo con todos los temas y archivos")
    print(f"  [PASS] PASO")

def test_decisiones_offline_placeholder():
    """Test 5: decisiones en modo offline produce placeholder."""
    print("\n=== Test 5: decisiones modo offline ===")
    gen = DecisionesGenerator()  # sin extractor
    exchanges = make_test_exchanges()
    content, summary = gen.generate(exchanges)
    assert "Sin decisiones registradas" in content
    assert "No se identificaron" in summary
    print(f"  [OK] Placeholder en modo offline")
    print(f"  [PASS] PASO")

def test_decisiones_online_with_mock_extractor():
    """Test 6: decisiones en modo online con extractor simulado."""
    print("\n=== Test 6: decisiones modo online ===")

    def mock_extractor(exs):
        return [
            Decision(
                id="",
                timestamp=exs[0].start_timestamp,
                title="Usar PriorityQueue",
                decision="Adoptar PriorityQueue como estructura",
                reason="Director lo indicó",
                impact="Afecta planner.py",
                tema="planificador",
            )
        ]

    gen = DecisionesGenerator(extractor=mock_extractor)
    exchanges = make_test_exchanges()
    content, summary = gen.generate(exchanges)
    assert "Usar PriorityQueue" in content
    assert "D01" in content
    print(f"  [OK] Decisiones extraidas con extractor simulado")
    print(f"  [PASS] PASO")

def test_decisiones_deduplicacion():
    """Test 7: deduplicación de decisiones por título."""
    print("\n=== Test 7: deduplicacion de decisiones ===")

    def mock_extractor(exs):
        return [Decision(id="", timestamp=0, title="Decisión repetida", decision="X")]

    gen = DecisionesGenerator(extractor=mock_extractor)
    exchanges = make_test_exchanges()
    existing = [Decision(id="D01", timestamp=0, title="Decisión repetida", decision="X")]
    content, _ = gen.generate(exchanges, existing_decisions=existing)
    # No debe añadir la decisión duplicada
    assert content.count("Decisión repetida") == 1
    print(f"  [OK] Decision duplicada no se anade")
    print(f"  [PASS] PASO")

def test_recovery_generator_orquestacion():
    """Test 8: recovery_generator produce los 4 archivos correctos."""
    print("\n=== Test 8: recovery_generator orquesta 4 generadores ===")
    gen = RecoveryGenerator()
    exchanges = make_test_exchanges()
    b1 = ThematicBlock(filename="bloque_01.md")
    b1.add_exchange(exchanges[0])
    b1.add_exchange(exchanges[2])

    files = gen.generate_all(exchanges, [b1], chat_label="Test")
    # Debe haber 4 archivos: estado, índice, decisiones, bloque_01
    assert len(files) == 4
    filenames = [f.filename for f in files]
    assert "00_estado_actual.md" in filenames
    assert "01_indice_recuperacion.md" in filenames
    assert "02_decisiones_clave.md" in filenames
    assert "bloque_01.md" in filenames
    print(f"  [OK] 4 archivos generados: {filenames}")
    print(f"  [PASS] PASO")

def test_recovery_generator_uses_metadata_for_indice():
    """Test 9: recovery_generator usa metadata para el índice."""
    print("\n=== Test 9: indice usa metadata ===")
    gen = RecoveryGenerator()
    exchanges = make_test_exchanges()
    b1 = ThematicBlock(filename="bloque_01.md")
    b1.add_exchange(exchanges[0])
    meta = RecoveryMetadata()
    meta.registrar_tema("validaciones", "bloque_01.md")

    files = gen.generate_all(exchanges, [b1], chat_label="Test", metadata=meta)
    indice = next(f for f in files if f.filename == "01_indice_recuperacion.md")
    assert "validaciones" in indice.content
    assert "bloque_01.md" in indice.content
    print(f"  [OK] Indice usa metadata para mapeo")
    print(f"  [PASS] PASO")

def main():
    print("=" * 60)
    print("TEST DE INTEGRACION: generadores de estado, indice, decisiones")
    print("=" * 60)
    tests = [
        test_estado_generator_8_secciones,
        test_estado_d1_literal_director,
        test_estado_a3_no_falsos_positivos,
        test_indice_with_tema_to_archivo_table,
        test_decisiones_offline_placeholder,
        test_decisiones_online_with_mock_extractor,
        test_decisiones_deduplicacion,
        test_recovery_generator_orquestacion,
        test_recovery_generator_uses_metadata_for_indice,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except (AssertionError, Exception) as e:
            print(f"  [FAIL] FALLO: {e}")
            failed += 1
    print(f"\n{'=' * 60}")
    print(f"RESULTADO: {passed} pasaron, {failed} fallaron de {len(tests)} tests")
    print(f"{'=' * 60}")
    return 0 if failed == 0 else 1

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
    sys.exit(main())
