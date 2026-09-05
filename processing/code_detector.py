# contexto_zai/processing/code_detector.py -- Detector de codigo: identifica scripts y artefactos versionables en el contenido de intercambios.
"""Detector de codigo y artefactos versionables (v3.3).

Identifica scripts y artefactos versionables en el contenido de
intercambios del chat. Extrae bloques de codigo, identifica el
nombre del script (por ruta de archivo, comentario # Destino:, o
patrones de codigo), y asigna nombres propios (con apellido/DNI
si hay duplicados).

Patrones de deteccion:
1. Bloques de codigo entre triple backtick con identificador de lenguaje.
2. Comentarios `# Destino: ruta/al/archivo.py` en la primera linea.
3. Rutas de archivo mencionadas en el texto del intercambio.
4. Bloques de codigo sin lenguaje explicito que contienen patrones
   de codigo (imports, def, class, function, const, require).

Nombres propios:
- El nombre del script se extrae del nombre del archivo (sin extension).
- Si dos scripts tienen el mismo nombre pero diferente ruta, se distinguen
  por su apellido/DNI: el directorio padre como sufijo (ej: config_client,
  config_server).

Atómico standalone: importa config y models, nada mas del proyecto.
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
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ── Modelos de datos del detector ──────────────────────────────


@dataclass
class CodeBlock:
    """Un bloque de codigo detectado en el contenido.

    Attributes:
        content: Contenido del bloque de codigo (sin los backticks).
        language: Lenguaje identificado (python, javascript, etc.) o vacio.
        start_line: Linea donde empieza el bloque (1-based).
        end_line: Linea donde termina el bloque (1-based).
        destComment: Comentario # Destino: si existe, sino None.
        filePath: Ruta de archivo detectada cerca del bloque, sino None.
    """

    content: str
    language: str = ""
    start_line: int = 0
    end_line: int = 0
    dest_comment: Optional[str] = None
    file_path: Optional[str] = None

    @property
    def has_name(self) -> bool:
        """True si se puede identificar el nombre del script."""
        return self.dest_comment is not None or self.file_path is not None


@dataclass
class DetectedScript:
    """Un script detectado y nombrado en el contenido.

    Attributes:
        name: Nombre propio del script (ej: server, router, config).
        full_path: Ruta completa del archivo (DNI/apellido).
        content: Contenido del codigo del script.
        start_line: Linea donde empieza en el contenido original.
        language: Lenguaje del script.
        exchange_id: ID del intercambio donde aparecio (0 si no asignado).
    """

    name: str
    full_path: str
    content: str
    start_line: int = 0
    language: str = ""
    exchange_id: int = 0

    @property
    def unique_name(self) -> str:
        """Nombre unico: nombre propio + apellido si hay duplicados."""
        return self.name


# ── Detector de codigo ─────────────────────────────────────────


class CodeDetector:
    """Detecta scripts y artefactos versionables en el contenido de intercambios.

    Usage:
        >>> detector = CodeDetector()
        >>> scripts = detector.detect_scripts(content="```python\\n# Destino: server.py\\nprint('hola')\\n```")
        >>> print(scripts[0].name)  # "server"
    """

    # Patron para bloques de codigo entre triple backtick
    # Captura: ```python\n...\n``` o ```\n...\n```
    CODE_BLOCK_PATTERN = re.compile(
        r'```(\w*)\n(.*?)```',
        re.DOTALL,
    )

    # Patron para comentario # Destino: ruta/al/archivo.py
    DEST_COMMENT_PATTERN = re.compile(
        r'#\s*Destino:\s*(.+?)\s*$',
        re.MULTILINE,
    )

    # Patron para rutas de archivo con extension de codigo
    # Captura rutas como: contexto_zai/config.py, server.py, /home/z/my-project/server.py
    FILE_PATH_PATTERN = re.compile(
        r'`?([\w/.\-]+\.(?:py|ts|js|json|yaml|yml|toml|env|md|cfg|ini|sh))`?',
    )

    # Patrones de codigo para bloques sin lenguaje explicito
    CODE_PATTERNS = [
        r'^\s*(?:import|from\s+\S+\s+import)\s+',  # Python imports
        r'^\s*def\s+\w+\s*\(',  # Python function
        r'^\s*class\s+\w+\s*[:\(]',  # Python class
        r'^\s*(?:const|let|var)\s+\w+\s*=',  # JavaScript variables
        r'^\s*function\s+\w+\s*\(',  # JavaScript function
        r'^\s*require\s*\(',  # Node.js require
        r'^\s*export\s+',  # JavaScript export
        r'^\s*package\s+\w+',  # Go package
        r'^\s*func\s+\w+\s*\(',  # Go function
        r'^\s*(?:public|private|protected)\s+',  # Java/C# modifiers
    ]

    CODE_REGEX = re.compile(
        "|".join(f"(?:{p})" for p in CODE_PATTERNS),
        re.MULTILINE,
    )

    def __init__(self) -> None:
        logger.debug("CodeDetector inicializado")

    # ── API publica ────────────────────────────────────────────

    def detect_scripts(
        self,
        content: str,
        exchange_id: int = 0,
    ) -> list[DetectedScript]:
        """Detecta todos los scripts en el contenido de un intercambio.

        Args:
            content: Texto del mensaje del agente.
            exchange_id: ID del intercambio donde aparece (0 si no asignado).

        Returns:
            Lista de DetectedScript con nombres propios resueltos.
        """
        if not content:
            return []

        # Paso 1: extraer bloques de codigo
        blocks = self.extract_code_blocks(content)

        # Paso 2: identificar nombres y rutas
        scripts: list[DetectedScript] = []
        for block in blocks:
            script = self._block_to_script(block, exchange_id)
            if script:
                scripts.append(script)

        # Paso 3: resolver duplicados (apellido/DNI)
        scripts = self._resolve_duplicates(scripts)

        logger.info(
            "Detectados %d scripts en intercambio %d",
            len(scripts), exchange_id,
        )
        return scripts

    def extract_code_blocks(self, content: str) -> list[CodeBlock]:
        """Extrae todos los bloques de codigo del contenido.

        Busca bloques entre triple backtick y verifica si contienen
        patrones de codigo aunque no tengan lenguaje explicito.

        Args:
            content: Texto a analizar.

        Returns:
            Lista de CodeBlock detectados.
        """
        blocks: list[CodeBlock] = []

        for match in self.CODE_BLOCK_PATTERN.finditer(content):
            language = match.group(1) or ""
            code_content = match.group(2)

            # Calcular linea de inicio (1-based)
            start_line = content[:match.start()].count("\n") + 1
            end_line = content[:match.end()].count("\n") + 1

            # Buscar comentario # Destino: en las primeras lineas del bloque
            dest_comment = self._find_dest_comment(code_content)

            # Buscar ruta de archivo cerca del bloque
            file_path = self._find_file_path_near(content, match.start())

            # Si no tiene lenguaje, verificar si parece codigo
            if not language:
                if not self._looks_like_code(code_content):
                    continue  # No parece codigo, saltar

            blocks.append(CodeBlock(
                content=code_content,
                language=language,
                start_line=start_line,
                end_line=end_line,
                dest_comment=dest_comment,
                file_path=file_path,
            ))

        logger.debug("Extraidos %d bloques de codigo", len(blocks))
        return blocks

    def extract_artifacts(
        self,
        content: str,
        exchange_id: int = 0,
    ) -> list[DetectedScript]:
        """Detecta artefactos versionables (specs, planes, configs) en el texto.

        Busca archivos mencionados en el texto que no estan en bloques
        de codigo pero que son referenciados como entregables.

        Args:
            content: Texto a analizar.
            exchange_id: ID del intercambio.

        Returns:
            Lista de DetectedScript (artefactos sin contenido de codigo).
        """
        scripts: list[DetectedScript] = []

        # Buscar todas las rutas de archivo mencionadas
        for match in self.FILE_PATH_PATTERN.finditer(content):
            path = match.group(1)
            name = self._extract_name_from_path(path)

            # Verificar que no este ya en un bloque de codigo
            # (para no duplicar)
            already_detected = any(
                s.full_path == path for s in scripts
            )
            if already_detected:
                continue

            start_line = content[:match.start()].count("\n") + 1

            scripts.append(DetectedScript(
                name=name,
                full_path=path,
                content="",  # Sin contenido, solo referencia
                start_line=start_line,
                language="",
                exchange_id=exchange_id,
            ))

        return scripts

    # ── Propiedades ────────────────────────────────────────────

    def __repr__(self) -> str:
        return "CodeDetector()"

    # ── Metodos privados ───────────────────────────────────────

    def _block_to_script(
        self,
        block: CodeBlock,
        exchange_id: int,
    ) -> Optional[DetectedScript]:
        """Convierte un CodeBlock en un DetectedScript con nombre propio.

        Returns:
            DetectedScript o None si no se puede identificar el nombre.
        """
        # Prioridad 1: comentario # Destino:
        if block.dest_comment:
            path = block.dest_comment.strip()
            name = self._extract_name_from_path(path)
            return DetectedScript(
                name=name,
                full_path=path,
                content=block.content,
                start_line=block.start_line,
                language=block.language,
                exchange_id=exchange_id,
            )

        # Prioridad 2: ruta de archivo cerca del bloque
        if block.file_path:
            name = self._extract_name_from_path(block.file_path)
            return DetectedScript(
                name=name,
                full_path=block.file_path,
                content=block.content,
                start_line=block.start_line,
                language=block.language,
                exchange_id=exchange_id,
            )

        # Prioridad 3: sin nombre identificable
        # Generar nombre basado en el lenguaje o posicion
        if block.language:
            name = f"{block.language}_script_{block.start_line}"
        else:
            name = f"script_{block.start_line}"

        return DetectedScript(
            name=name,
            full_path=name,
            content=block.content,
            start_line=block.start_line,
            language=block.language,
            exchange_id=exchange_id,
        )

    def _find_dest_comment(self, code_content: str) -> Optional[str]:
        """Busca un comentario # Destino: en las primeras 3 lineas del codigo."""
        lines = code_content.split("\n")[:3]
        for line in lines:
            match = self.DEST_COMMENT_PATTERN.search(line)
            if match:
                return match.group(1)
        return None

    def _find_file_path_near(
        self,
        content: str,
        position: int,
    ) -> Optional[str]:
        """Busca una ruta de archivo en las 200 chars anteriores al bloque."""
        start = max(0, position - 200)
        context = content[start:position]

        for match in self.FILE_PATH_PATTERN.finditer(context):
            return match.group(1)

        return None

    def _looks_like_code(self, content: str) -> bool:
        """Verifica si un bloque sin lenguaje explicito parece codigo."""
        return bool(self.CODE_REGEX.search(content))

    def _extract_name_from_path(self, path: str) -> str:
        """Extrae el nombre del script desde una ruta de archivo.

        Ej: "contexto_zai/config.py" -> "config"
        Ej: "server.py" -> "server"
        """
        # Normalizar separadores
        path = path.replace("\\", "/")
        # Obtener el nombre del archivo sin extension
        filename = path.split("/")[-1]
        if "." in filename:
            name = filename.rsplit(".", 1)[0]
        else:
            name = filename
        return name

    def _resolve_duplicates(
        self,
        scripts: list[DetectedScript],
    ) -> list[DetectedScript]:
        """Resuelve nombres duplicados anadiendo apellido/DNI.

        Si dos scripts tienen el mismo nombre pero diferente ruta,
        se anade el directorio padre como sufijo (apellido).

        Ej: config de client/config.py -> config_client
        Ej: config de server/config.py -> config_server
        """
        # Contar cuantas veces aparece cada nombre
        name_counts: dict[str, int] = {}
        for script in scripts:
            name_counts[script.name] = name_counts.get(script.name, 0) + 1

        # Resolver duplicados
        resolved: list[DetectedScript] = []
        for script in scripts:
            if name_counts[script.name] > 1:
                # Hay duplicados: anadir apellido (directorio padre)
                parent_dir = self._get_parent_dir(script.full_path)
                if parent_dir:
                    script.name = f"{script.name}_{parent_dir}"
            resolved.append(script)

        return resolved

    def _get_parent_dir(self, path: str) -> Optional[str]:
        """Obtiene el nombre del directorio padre de una ruta.

        Ej: "contexto_zai/client/config.py" -> "client"
        Ej: "config.py" -> None
        """
        path = path.replace("\\", "/")
        parts = path.split("/")
        if len(parts) >= 2:
            return parts[-2]
        return None


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

    # ── Validacion interna de code_detector.py (atomico standalone) ──
    print("=== Validacion de code_detector.py ===\n")

    detector = CodeDetector()

    # Test 1: detectar bloque de codigo con # Destino:
    content1 = """Aqui el codigo:

```python
# Destino: server.py
import httpx

class Server:
    pass
```

Fin del mensaje."""

    scripts1 = detector.detect_scripts(content1, exchange_id=1)
    assert len(scripts1) == 1, f"Esperaba 1 script, obtuve {len(scripts1)}"
    assert scripts1[0].name == "server", f"Nombre esperado 'server', obtuvo '{scripts1[0].name}'"
    assert scripts1[0].full_path == "server.py"
    assert "class Server" in scripts1[0].content
    assert scripts1[0].language == "python"
    print(f"[OK] Detectar bloque con # Destino: name='{scripts1[0].name}', path='{scripts1[0].full_path}'")

    # Test 2: detectar bloque sin # Destino: pero con ruta cerca
    content2 = """Modifique contexto_zai/config.py:

```python
TOKEN_LIMITS = TokenLimits()
```
"""

    scripts2 = detector.detect_scripts(content2, exchange_id=2)
    assert len(scripts2) == 1
    assert scripts2[0].name == "config"
    assert "contexto_zai/config.py" in scripts2[0].full_path
    print(f"[OK] Detectar bloque con ruta cerca: name='{scripts2[0].name}'")

    # Test 3: detectar multiples scripts en un intercambio
    content3 = """Aqui ambos scripts:

```python
# Destino: server.py
def run():
    pass
```

Y tambien:

```python
# Destino: router.py
def route():
    pass
```
"""

    scripts3 = detector.detect_scripts(content3, exchange_id=3)
    assert len(scripts3) == 2, f"Esperaba 2 scripts, obtuve {len(scripts3)}"
    names = {s.name for s in scripts3}
    assert names == {"server", "router"}, f"Nombres esperados {{server, router}}, obtuvo {names}"
    print(f"[OK] Multiples scripts: {names}")

    # Test 4: resolver duplicados con apellido/DNI
    content4 = """Ambos configs:

```python
# Destino: client/config.py
CLIENT = True
```

```python
# Destino: server/config.py
SERVER = True
```
"""

    scripts4 = detector.detect_scripts(content4, exchange_id=4)
    assert len(scripts4) == 2
    names4 = {s.name for s in scripts4}
    assert "config_client" in names4, f"Esperaba 'config_client' en {names4}"
    assert "config_server" in names4, f"Esperaba 'config_server' en {names4}"
    assert "config" not in names4, "No debe quedar 'config' sin apellido"
    print(f"[OK] Duplicados resueltos con apellido: {names4}")

    # Test 5: bloque sin lenguaje explicito pero con patrones de codigo
    content5 = """Aqui codigo sin lenguaje:

```
import os
def main():
    pass
```
"""

    scripts5 = detector.detect_scripts(content5, exchange_id=5)
    assert len(scripts5) == 1, f"Esperaba 1 script, obtuve {len(scripts5)}"
    print(f"[OK] Bloque sin lenguaje pero con patrones: detectado")

    # Test 6: texto sin codigo no detecta nada
    content6 = "Hola, como estas? Esto es texto plano sin codigo."
    scripts6 = detector.detect_scripts(content6, exchange_id=6)
    assert len(scripts6) == 0
    print(f"[OK] Texto sin codigo: 0 scripts detectados")

    # Test 7: contenido vacio
    scripts7 = detector.detect_scripts("", exchange_id=7)
    assert len(scripts7) == 0
    print(f"[OK] Contenido vacio: 0 scripts")

    # Test 8: extract_code_blocks directamente
    blocks = detector.extract_code_blocks(content1)
    assert len(blocks) == 1
    assert blocks[0].language == "python"
    assert blocks[0].dest_comment == "server.py"
    print(f"[OK] extract_code_blocks: {len(blocks)} bloque(s)")

    # Test 9: extract_artifacts (rutas mencionadas sin bloques de codigo)
    content9 = "Modifique los archivos server.py y router.py en el proyecto."
    artifacts = detector.extract_artifacts(content9, exchange_id=9)
    assert len(artifacts) == 2
    artifact_names = {a.name for a in artifacts}
    assert "server" in artifact_names
    assert "router" in artifact_names
    print(f"[OK] extract_artifacts: {artifact_names}")

    # Test 10: _extract_name_from_path
    assert detector._extract_name_from_path("contexto_zai/config.py") == "config"
    assert detector._extract_name_from_path("server.py") == "server"
    assert detector._extract_name_from_path("path/to/file.ts") == "file"
    print(f"[OK] _extract_name_from_path: nombres extraidos correctamente")

    # Test 11: _get_parent_dir
    assert detector._get_parent_dir("client/config.py") == "client"
    assert detector._get_parent_dir("server/config.py") == "server"
    assert detector._get_parent_dir("config.py") is None
    print(f"[OK] _get_parent_dir: directorios padres correctos")

    # Test 12: _looks_like_code
    assert detector._looks_like_code("import os\ndef main():\n    pass")
    assert detector._looks_like_code("const x = 1;")
    assert not detector._looks_like_code("Hola esto es texto plano")
    print(f"[OK] _looks_like_code: deteccion de patrones correcta")

    # Test 13: intercambio con codigo y texto mixto
    content13 = """He modificado el archivo. Aqui el codigo:

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

Pero no toque config.py.
"""

    scripts13 = detector.detect_scripts(content13, exchange_id=13)
    assert len(scripts13) == 2
    names13 = {s.name for s in scripts13}
    assert names13 == {"pipeline", "test_pipeline"}
    print(f"[OK] Codigo y texto mixto: {len(scripts13)} scripts detectados ({names13})")

    # Test 14: bloque con # Destino: en segunda linea
    content14 = """```python
# Destino: auth.py
class AuthClient:
    pass
```
"""
    scripts14 = detector.detect_scripts(content14, exchange_id=14)
    assert len(scripts14) == 1
    assert scripts14[0].name == "auth"
    print(f"[OK] # Destino: en primera linea del bloque: detectado")

    print("\n[PASS] code_detector.py: todos los tests pasaron")
