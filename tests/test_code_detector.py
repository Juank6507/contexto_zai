# tests/test_code_detector.py -- Test de integracion: detector de codigo y artefactos versionables.
"""Test de integracion: CodeDetector (v3.3).

Valida la funcionalidad completa del detector de codigo:
1. Deteccion de bloques de codigo con # Destino:.
2. Deteccion de bloques con ruta de archivo cerca.
3. Deteccion de multiples scripts en un intercambio.
4. Resolucion de duplicados con apellido/DNI.
5. Deteccion de bloques sin lenguaje explicito.
6. Extraccion de artefactos (rutas mencionadas sin codigo).
7. Casos edge: contenido vacio, texto sin codigo, codigo mixto.
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

from contexto_zai.processing.code_detector import CodeDetector, DetectedScript


def test_detect_block_with_dest_comment():
    """Test 1: detectar bloque de codigo con # Destino:."""
    print("\n=== Test 1: bloque con # Destino: ===")
    detector = CodeDetector()
    content = """Aqui el codigo:

```python
# Destino: server.py
import httpx

class Server:
    pass
```
"""
    scripts = detector.detect_scripts(content, exchange_id=1)
    assert len(scripts) == 1
    assert scripts[0].name == "server"
    assert scripts[0].full_path == "server.py"
    assert "class Server" in scripts[0].content
    assert scripts[0].language == "python"
    print(f"  [OK] name='{scripts[0].name}', path='{scripts[0].full_path}'")
    print(f"  [PASS]")


def test_detect_block_with_nearby_path():
    """Test 2: detectar bloque con ruta de archivo cerca."""
    print("\n=== Test 2: bloque con ruta cerca ===")
    detector = CodeDetector()
    content = """Modifique contexto_zai/config.py:

```python
TOKEN_LIMITS = TokenLimits()
```
"""
    scripts = detector.detect_scripts(content, exchange_id=2)
    assert len(scripts) == 1
    assert scripts[0].name == "config"
    assert "contexto_zai/config.py" in scripts[0].full_path
    print(f"  [OK] name='{scripts[0].name}'")
    print(f"  [PASS]")


def test_detect_multiple_scripts():
    """Test 3: detectar multiples scripts en un intercambio."""
    print("\n=== Test 3: multiples scripts ===")
    detector = CodeDetector()
    content = """Aqui ambos:

```python
# Destino: server.py
def run(): pass
```

Y tambien:

```python
# Destino: router.py
def route(): pass
```
"""
    scripts = detector.detect_scripts(content, exchange_id=3)
    assert len(scripts) == 2
    names = {s.name for s in scripts}
    assert names == {"server", "router"}
    print(f"  [OK] {names}")
    print(f"  [PASS]")


def test_resolve_duplicates_with_surname():
    """Test 4: resolver duplicados con apellido/DNI."""
    print("\n=== Test 4: duplicados con apellido ===")
    detector = CodeDetector()
    content = """Ambos configs:

```python
# Destino: client/config.py
CLIENT = True
```

```python
# Destino: server/config.py
SERVER = True
```
"""
    scripts = detector.detect_scripts(content, exchange_id=4)
    assert len(scripts) == 2
    names = {s.name for s in scripts}
    assert "config_client" in names
    assert "config_server" in names
    assert "config" not in names
    print(f"  [OK] {names}")
    print(f"  [PASS]")


def test_detect_block_without_language():
    """Test 5: bloque sin lenguaje explicito pero con patrones de codigo."""
    print("\n=== Test 5: bloque sin lenguaje ===")
    detector = CodeDetector()
    content = """```
import os
def main():
    pass
```
"""
    scripts = detector.detect_scripts(content, exchange_id=5)
    assert len(scripts) == 1
    print(f"  [OK] detectado")
    print(f"  [PASS]")


def test_no_code_detected():
    """Test 6: texto sin codigo no detecta nada."""
    print("\n=== Test 6: texto sin codigo ===")
    detector = CodeDetector()
    scripts = detector.detect_scripts("Hola, como estas?", exchange_id=6)
    assert len(scripts) == 0
    print(f"  [OK] 0 scripts")
    print(f"  [PASS]")


def test_empty_content():
    """Test 7: contenido vacio."""
    print("\n=== Test 7: contenido vacio ===")
    detector = CodeDetector()
    scripts = detector.detect_scripts("", exchange_id=7)
    assert len(scripts) == 0
    print(f"  [OK] 0 scripts")
    print(f"  [PASS]")


def test_extract_artifacts():
    """Test 8: extraer artefactos (rutas mencionadas sin codigo)."""
    print("\n=== Test 8: extract_artifacts ===")
    detector = CodeDetector()
    content = "Modifique los archivos server.py y router.py en el proyecto."
    artifacts = detector.extract_artifacts(content, exchange_id=9)
    assert len(artifacts) == 2
    names = {a.name for a in artifacts}
    assert "server" in names
    assert "router" in names
    print(f"  [OK] {names}")
    print(f"  [PASS]")


def test_mixed_code_and_text():
    """Test 9: codigo y texto mixto en un intercambio."""
    print("\n=== Test 9: codigo y texto mixto ===")
    detector = CodeDetector()
    content = """He modificado el archivo. Aqui el codigo:

```python
# Destino: pipeline.py
def run():
    return True
```

Tambien he creado un test:

```python
# Destino: test_pipeline.py
def test_run():
    assert run() == True
```
"""
    scripts = detector.detect_scripts(content, exchange_id=13)
    assert len(scripts) == 2
    names = {s.name for s in scripts}
    assert names == {"pipeline", "test_pipeline"}
    print(f"  [OK] {names}")
    print(f"  [PASS]")


def test_dest_comment_on_second_line():
    """Test 10: # Destino: en segunda linea del bloque."""
    print("\n=== Test 10: # Destino: en segunda linea ===")
    detector = CodeDetector()
    content = """```python
# Destino: auth.py
class AuthClient:
    pass
```
"""
    scripts = detector.detect_scripts(content, exchange_id=14)
    assert len(scripts) == 1
    assert scripts[0].name == "auth"
    print(f"  [OK] name='{scripts[0].name}'")
    print(f"  [PASS]")


def test_extract_name_from_path():
    """Test 11: _extract_name_from_path con varios formatos."""
    print("\n=== Test 11: _extract_name_from_path ===")
    detector = CodeDetector()
    assert detector._extract_name_from_path("contexto_zai/config.py") == "config"
    assert detector._extract_name_from_path("server.py") == "server"
    assert detector._extract_name_from_path("path/to/file.ts") == "file"
    print(f"  [OK] nombres extraidos correctamente")
    print(f"  [PASS]")


def main():
    print("=" * 60)
    print("TEST DE INTEGRACION: CodeDetector (v3.3)")
    print("=" * 60)
    tests = [
        test_detect_block_with_dest_comment,
        test_detect_block_with_nearby_path,
        test_detect_multiple_scripts,
        test_resolve_duplicates_with_surname,
        test_detect_block_without_language,
        test_no_code_detected,
        test_empty_content,
        test_extract_artifacts,
        test_mixed_code_and_text,
        test_dest_comment_on_second_line,
        test_extract_name_from_path,
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
