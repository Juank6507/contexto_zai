# tests/test_version_graph.py -- Test de integracion: grafo de cambios reversible con diffs forward y reverse.
"""Test de integracion: VersionGraphBuilder (v3.3).

Valida la funcionalidad completa del grafo de cambios:
1. Construccion de grafos con multiples versiones.
2. Calculo de diffs forward y reverse.
3. Retroceso desde version actual a versiones anteriores.
4. Serializacion a/desde JSON.
5. Casos edge: 1 version, 0 versiones, versiones sin cambios.
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

from contexto_zai.processing.version_graph import VersionGraphBuilder, ChangeGraph, VersionNode


def test_build_graph_with_3_versions():
    """Test 1: construir grafo con 3 versiones."""
    print("\n=== Test 1: grafo con 3 versiones ===")
    builder = VersionGraphBuilder()
    versions = [
        ("v1", 100.0, 1, "def hello():\n    pass\n"),
        ("v2", 200.0, 3, "def hello():\n    print('hi')\n"),
        ("v3", 300.0, 5, "def hello():\n    print('hello')\n    return True\n"),
    ]
    graph = builder.build("server", versions)
    assert graph.script_name == "server"
    assert graph.version_count == 3
    assert graph.current_version_id == "v3"
    print(f"  [OK] {graph.version_count} versiones, actual={graph.current_version_id}")
    print(f"  [PASS]")


def test_first_node_has_no_parent():
    """Test 2: nodo inicial no tiene padre."""
    print("\n=== Test 2: nodo v1 sin padre ===")
    builder = VersionGraphBuilder()
    versions = [("v1", 100.0, 1, "x = 1\n")]
    graph = builder.build("test", versions)
    v1 = graph.get_node("v1")
    assert v1 is not None
    assert v1.parent_version_id is None
    assert v1.forward_diff == ""
    assert v1.reverse_diff == ""
    print(f"  [OK] v1 sin padre ni diffs")
    print(f"  [PASS]")


def test_diffs_calculated_between_versions():
    """Test 3: diffs calculados entre versiones consecutivas."""
    print("\n=== Test 3: diffs entre versiones ===")
    builder = VersionGraphBuilder()
    versions = [
        ("v1", 100.0, 1, "x = 1\n"),
        ("v2", 200.0, 2, "x = 2\n"),
    ]
    graph = builder.build("config", versions)
    v2 = graph.get_node("v2")
    assert v2 is not None
    assert v2.parent_version_id == "v1"
    assert v2.forward_diff != ""
    assert v2.reverse_diff != ""
    assert "+" in v2.forward_diff
    assert "-" in v2.forward_diff
    print(f"  [OK] diffs forward y reverse calculados")
    print(f"  [PASS]")


def test_rollback_to_previous_version():
    """Test 4: retroceder desde v3 hasta v1."""
    print("\n=== Test 4: retroceso v3 -> v1 ===")
    builder = VersionGraphBuilder()
    versions = [
        ("v1", 100.0, 1, "def hello():\n    pass\n"),
        ("v2", 200.0, 3, "def hello():\n    print('hi')\n"),
        ("v3", 300.0, 5, "def hello():\n    print('hello')\n    return True\n"),
    ]
    graph = builder.build("server", versions)
    content = builder.rollback_to(graph, "v1")
    assert content is not None
    assert "pass" in content
    assert "print" not in content
    print(f"  [OK] contenido de v1 recuperado")
    print(f"  [PASS]")


def test_rollback_to_intermediate_version():
    """Test 5: retroceder desde v3 hasta v2."""
    print("\n=== Test 5: retroceso v3 -> v2 ===")
    builder = VersionGraphBuilder()
    versions = [
        ("v1", 100.0, 1, "x = 1\n"),
        ("v2", 200.0, 2, "x = 2\ny = 3\n"),
        ("v3", 300.0, 3, "x = 2\ny = 3\nz = 4\n"),
    ]
    graph = builder.build("config", versions)
    content = builder.rollback_to(graph, "v2")
    assert content is not None
    assert "z = 4" not in content
    assert "y = 3" in content
    print(f"  [OK] contenido de v2 recuperado")
    print(f"  [PASS]")


def test_rollback_to_current_version():
    """Test 6: retroceder a la version actual (sin cambios)."""
    print("\n=== Test 6: retroceso a version actual ===")
    builder = VersionGraphBuilder()
    versions = [("v1", 100.0, 1, "x = 1\n")]
    graph = builder.build("test", versions)
    content = builder.rollback_to(graph, "v1")
    assert content == "x = 1\n"
    print(f"  [OK] sin cambios")
    print(f"  [PASS]")


def test_rollback_to_nonexistent_version():
    """Test 7: retroceder a version inexistente devuelve None."""
    print("\n=== Test 7: version inexistente ===")
    builder = VersionGraphBuilder()
    versions = [("v1", 100.0, 1, "x = 1\n")]
    graph = builder.build("test", versions)
    content = builder.rollback_to(graph, "v999")
    assert content is None
    print(f"  [OK] None")
    print(f"  [PASS]")


def test_empty_graph():
    """Test 8: grafo vacio."""
    print("\n=== Test 8: grafo vacio ===")
    builder = VersionGraphBuilder()
    graph = builder.build("empty", [])
    assert graph.version_count == 0
    assert graph.current_node is None
    print(f"  [OK] 0 versiones")
    print(f"  [PASS]")


def test_single_version_graph():
    """Test 9: grafo con una sola version."""
    print("\n=== Test 9: 1 version ===")
    builder = VersionGraphBuilder()
    versions = [("v1", 100.0, 1, "x = 1\n")]
    graph = builder.build("test", versions)
    assert graph.version_count == 1
    assert graph.current_version_id == "v1"
    content = builder.rollback_to(graph, "v1")
    assert content == "x = 1\n"
    print(f"  [OK] 1 version, retroceso OK")
    print(f"  [PASS]")


def test_versions_without_changes():
    """Test 10: versiones sin cambios (contenido identico)."""
    print("\n=== Test 10: versiones sin cambios ===")
    builder = VersionGraphBuilder()
    versions = [
        ("v1", 100.0, 1, "x = 1\n"),
        ("v2", 200.0, 2, "x = 1\n"),  # sin cambios
    ]
    graph = builder.build("config", versions)
    v2 = graph.get_node("v2")
    assert v2 is not None
    assert v2.forward_diff == ""
    assert v2.reverse_diff == ""
    print(f"  [OK] diffs vacios")
    print(f"  [PASS]")


def test_save_and_load_graph():
    """Test 11: guardar y cargar grafo desde JSON."""
    print("\n=== Test 11: guardar y cargar ===")
    import tempfile
    from pathlib import Path

    builder = VersionGraphBuilder()
    versions = [
        ("v1", 100.0, 1, "x = 1\n"),
        ("v2", 200.0, 2, "x = 2\n"),
    ]
    graph = builder.build("server", versions)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = builder.save_graph(graph, tmpdir)
        assert path.exists()

        loaded = builder.load_graphs(path)
        assert "server" in loaded
        assert loaded["server"].version_count == 2
        assert loaded["server"].current_version_id == "v2"

    print(f"  [OK] guardado y cargado correctamente")
    print(f"  [PASS]")


def test_current_node():
    """Test 12: current_node devuelve el ultimo."""
    print("\n=== Test 12: current_node ===")
    builder = VersionGraphBuilder()
    versions = [
        ("v1", 100.0, 1, "a\n"),
        ("v2", 200.0, 2, "b\n"),
        ("v3", 300.0, 3, "c\n"),
    ]
    graph = builder.build("test", versions)
    assert graph.current_node is not None
    assert graph.current_node.version_id == "v3"
    print(f"  [OK] current_node = v3")
    print(f"  [PASS]")


def main():
    print("=" * 60)
    print("TEST DE INTEGRACION: VersionGraphBuilder (v3.3)")
    print("=" * 60)
    tests = [
        test_build_graph_with_3_versions,
        test_first_node_has_no_parent,
        test_diffs_calculated_between_versions,
        test_rollback_to_previous_version,
        test_rollback_to_intermediate_version,
        test_rollback_to_current_version,
        test_rollback_to_nonexistent_version,
        test_empty_graph,
        test_single_version_graph,
        test_versions_without_changes,
        test_save_and_load_graph,
        test_current_node,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except (AssertionError, Exception) as e:
            print(f"  [FAIL] {e}")
            failed += 1
    print(f"\n{'=' * 60}")
    print(f"RESULTADO: {passed} pasaron, {failed} fallaron de {len(tests)} tests")
    print(f"{'=' * 60}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    _exit_code = 0
    try:
        _exit_code = main()
    except SystemExit:
        pass
    _sys.exit(_exit_code)
