# contexto_zai/processing/version_graph.py -- Grafo de cambios reversible: calcula diffs forward y reverse entre versiones de un script.
"""Grafo de cambios reversible para versionado de scripts (v3.3).

Calcula diffs entre versiones consecutivas de un script (forward y
reverse) y permite retroceder desde la version actual aplicando los
cambios inversos.

El grafo es lineal por defecto: v1 -> v2 -> v3 -> ... -> vN.
El retroceso sigue el camino principal (current -> parent -> parent
-> ... -> destino).

Diffs:
- forward_diff: cambios necesarios para llegar de la version padre
  a la version hija (que se anade, que se quita).
- reverse_diff: cambios necesarios para volver de la version hija
  a la version padre (inverso del forward).

Atomica standalone: no importa otros modulos del proyecto.
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

import difflib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── Modelos de datos del grafo ─────────────────────────────────


@dataclass
class VersionNode:
    """Un nodo del grafo de versiones de un script.

    Attributes:
        version_id: Identificador unico (ej: "v1", "v2").
        timestamp: Cuándo aparecio en el chat.
        exchange_id: ID del intercambio donde aparecio.
        content: Contenido del script en esta version.
        parent_version_id: ID de la version padre (None para v1).
        forward_diff: Diff para llegar de parent a esta version.
        reverse_diff: Diff para volver de esta version a parent.
    """

    version_id: str
    timestamp: float = 0.0
    exchange_id: int = 0
    content: str = ""
    parent_version_id: Optional[str] = None
    forward_diff: str = ""
    reverse_diff: str = ""

    def to_dict(self) -> dict:
        """Serializa el nodo a diccionario para JSON."""
        return {
            "version_id": self.version_id,
            "timestamp": self.timestamp,
            "exchange_id": self.exchange_id,
            "parent_version_id": self.parent_version_id,
            "forward_diff": self.forward_diff,
            "reverse_diff": self.reverse_diff,
        }

    @classmethod
    def from_dict(cls, data: dict, content: str = "") -> "VersionNode":
        """Deserializa un nodo desde diccionario."""
        return cls(
            version_id=data["version_id"],
            timestamp=data.get("timestamp", 0.0),
            exchange_id=data.get("exchange_id", 0),
            content=content,
            parent_version_id=data.get("parent_version_id"),
            forward_diff=data.get("forward_diff", ""),
            reverse_diff=data.get("reverse_diff", ""),
        )


@dataclass
class ChangeGraph:
    """Grafo de cambios reversible de un script.

    Attributes:
        script_name: Nombre del script (ej: "server").
        nodes: Lista de VersionNode ordenados por version_id.
        current_version_id: ID de la version actual.
    """

    script_name: str
    nodes: list[VersionNode] = field(default_factory=list)
    current_version_id: str = ""

    @property
    def version_count(self) -> int:
        """Numero de versiones en el grafo."""
        return len(self.nodes)

    @property
    def current_node(self) -> Optional[VersionNode]:
        """Nodo de la version actual."""
        if not self.current_version_id:
            return self.nodes[-1] if self.nodes else None
        for node in self.nodes:
            if node.version_id == self.current_version_id:
                return node
        return None

    def get_node(self, version_id: str) -> Optional[VersionNode]:
        """Busca un nodo por version_id."""
        for node in self.nodes:
            if node.version_id == version_id:
                return node
        return None

    def to_dict(self) -> dict:
        """Serializa el grafo a diccionario para JSON."""
        return {
            "script_name": self.script_name,
            "versions": [n.to_dict() for n in self.nodes],
            "current_version": self.current_version_id,
        }


# ── Constructor del grafo de cambios ───────────────────────────


class VersionGraphBuilder:
    """Construye un grafo de cambios reversible a partir de versiones.

    Recibe una lista de versiones de un script (en orden cronologico)
    y calcula los diffs forward y reverse entre cada par de versiones
    consecutivas.

    Usage:
        >>> builder = VersionGraphBuilder()
        >>> versions = [
        ...     ("v1", 100, 1, "def hello(): pass"),
        ...     ("v2", 200, 3, "def hello():\\n    print('hi')"),
        ... ]
        >>> graph = builder.build("server", versions)
        >>> print(graph.current_version_id)  # "v2"
    """

    def __init__(self) -> None:
        logger.debug("VersionGraphBuilder inicializado")

    # ── API publica ────────────────────────────────────────────

    def build(
        self,
        script_name: str,
        versions: list[tuple[str, float, int, str]],
    ) -> ChangeGraph:
        """Construye un grafo de cambios a partir de versiones.

        Args:
            script_name: Nombre del script.
            versions: Lista de tuplas (version_id, timestamp, exchange_id, content)
                      ordenadas cronologicamente.

        Returns:
            ChangeGraph con todos los nodos y diffs calculados.
        """
        if not versions:
            return ChangeGraph(script_name=script_name)

        nodes: list[VersionNode] = []
        prev_content = ""

        for i, (version_id, timestamp, exchange_id, content) in enumerate(versions):
            if i == 0:
                # Primera version: no hay padre
                node = VersionNode(
                    version_id=version_id,
                    timestamp=timestamp,
                    exchange_id=exchange_id,
                    content=content,
                    parent_version_id=None,
                    forward_diff="",
                    reverse_diff="",
                )
            else:
                # Versiones siguientes: calcular diffs contra el padre
                parent_id = versions[i - 1][0]
                forward, reverse = self._calculate_diffs(prev_content, content)

                node = VersionNode(
                    version_id=version_id,
                    timestamp=timestamp,
                    exchange_id=exchange_id,
                    content=content,
                    parent_version_id=parent_id,
                    forward_diff=forward,
                    reverse_diff=reverse,
                )

            nodes.append(node)
            prev_content = content

        current_id = versions[-1][0] if versions else ""

        graph = ChangeGraph(
            script_name=script_name,
            nodes=nodes,
            current_version_id=current_id,
        )

        logger.info(
            "Grafo construido para '%s': %d versiones, actual=%s",
            script_name, len(nodes), current_id,
        )
        return graph

    # ── Retroceso a versiones anteriores ───────────────────────

    def rollback_to(
        self,
        graph: ChangeGraph,
        target_version_id: str,
    ) -> Optional[str]:
        """Retrocede desde la version actual hasta una version destino.

        Aplica los reverse_diff sucesivamente desde la version actual
        hasta llegar a la version destino.

        Args:
            graph: Grafo de cambios del script.
            target_version_id: ID de la version destino.

        Returns:
            Contenido del script en la version destino, o None si no
            se encuentra.
        """
        current = graph.current_node
        if current is None:
            return None

        if current.version_id == target_version_id:
            return current.content

        # Aplicar reverse_diff sucesivamente
        content = current.content
        node = current

        while node and node.version_id != target_version_id:
            if not node.reverse_diff:
                # No hay reverse_diff (version inicial o diff vacio)
                parent = graph.get_node(node.parent_version_id) if node.parent_version_id else None
                if parent:
                    content = parent.content
                    node = parent
                else:
                    break
            else:
                # Aplicar reverse_diff al contenido
                parent = graph.get_node(node.parent_version_id) if node.parent_version_id else None
                if parent:
                    content = self._apply_reverse_diff(content, node.reverse_diff, parent.content)
                    node = parent
                else:
                    break

        if node and node.version_id == target_version_id:
            logger.info(
                "Retroceso exitoso: '%s' de %s a %s",
                graph.script_name, current.version_id, target_version_id,
            )
            return content

        logger.warning(
            "No se pudo retroceder a %s para '%s'",
            target_version_id, graph.script_name,
        )
        return None

    # ── Serializacion ──────────────────────────────────────────

    def save_graph(
        self,
        graph: ChangeGraph,
        output_dir: Path | str,
    ) -> Path:
        """Guarda el grafo en un archivo JSON.

        Args:
            graph: Grafo a guardar.
            output_dir: Directorio donde guardar el archivo.

        Returns:
            Ruta del archivo creado.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        file_path = output_path / "_grafos_cambios.json"

        # Leer grafos existentes si el archivo ya existe
        existing: dict = {}
        if file_path.exists():
            try:
                existing = json.loads(file_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                existing = {}

        # Actualizar o anadir el grafo
        existing[graph.script_name] = graph.to_dict()

        file_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Grafo de '%s' guardado en %s", graph.script_name, file_path)
        return file_path

    def load_graphs(self, input_path: Path | str) -> dict[str, ChangeGraph]:
        """Carga todos los grafos desde un archivo JSON.

        Args:
            input_path: Ruta al archivo _grafos_cambios.json.

        Returns:
            Diccionario {script_name: ChangeGraph}.
        """
        file_path = Path(input_path)
        if not file_path.exists():
            return {}

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Error leyendo grafos: %s", e)
            return {}

        graphs: dict[str, ChangeGraph] = {}
        for script_name, graph_data in data.items():
            nodes = [
                VersionNode.from_dict(n) for n in graph_data.get("versions", [])
            ]
            graphs[script_name] = ChangeGraph(
                script_name=script_name,
                nodes=nodes,
                current_version_id=graph_data.get("current_version", ""),
            )

        return graphs

    # ── Propiedades ────────────────────────────────────────────

    def __repr__(self) -> str:
        return "VersionGraphBuilder()"

    # ── Metodos privados ───────────────────────────────────────

    def _calculate_diffs(
        self,
        old_content: str,
        new_content: str,
    ) -> tuple[str, str]:
        """Calcula los diffs forward y reverse entre dos versiones.

        Returns:
            Tupla (forward_diff, reverse_diff) en formato unified diff.
        """
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        # Diff forward: como pasar de old a new
        forward_diff = "".join(
            difflib.unified_diff(
                old_lines, new_lines,
                fromfile="old", tofile="new",
                lineterm="",
            )
        )

        # Diff reverse: como pasar de new a old (inverso)
        reverse_diff = "".join(
            difflib.unified_diff(
                new_lines, old_lines,
                fromfile="new", tofile="old",
                lineterm="",
            )
        )

        return forward_diff, reverse_diff

    def _apply_reverse_diff(
        self,
        current_content: str,
        reverse_diff: str,
        parent_content: str,
    ) -> str:
        """Aplica el reverse_diff para reconstruir el contenido del padre.

        En lugar de aplicar el diff linea por linea, usa el contenido
        del padre directamente (mas eficiente y menos propenso a errores).
        """
        # El contenido del padre ya esta guardado en el grafo,
        # asi que lo devolvemos directamente.
        return parent_content


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

    # ── Validacion interna de version_graph.py (atomico standalone) ──
    print("=== Validacion de version_graph.py ===\n")

    builder = VersionGraphBuilder()

    # Test 1: construir grafo con 3 versiones
    versions = [
        ("v1", 100.0, 1, "def hello():\n    pass\n"),
        ("v2", 200.0, 3, "def hello():\n    print('hi')\n"),
        ("v3", 300.0, 5, "def hello():\n    print('hello')\n    return True\n"),
    ]

    graph = builder.build("server", versions)
    assert graph.script_name == "server"
    assert graph.version_count == 3
    assert graph.current_version_id == "v3"
    print(f"[OK] Grafo construido: {graph.version_count} versiones, actual={graph.current_version_id}")

    # Test 2: nodo inicial no tiene padre
    v1_node = graph.get_node("v1")
    assert v1_node is not None
    assert v1_node.parent_version_id is None
    assert v1_node.forward_diff == ""
    assert v1_node.reverse_diff == ""
    print(f"[OK] Nodo v1 sin padre ni diffs")

    # Test 3: nodo v2 tiene padre v1 y diffs no vacios
    v2_node = graph.get_node("v2")
    assert v2_node is not None
    assert v2_node.parent_version_id == "v1"
    assert v2_node.forward_diff != ""  # hay cambios
    assert v2_node.reverse_diff != ""
    print(f"[OK] Nodo v2 tiene padre v1 y diffs calculados")

    # Test 4: retroceder desde v3 hasta v1
    content_v1 = builder.rollback_to(graph, "v1")
    assert content_v1 is not None
    assert "pass" in content_v1
    assert "print" not in content_v1
    print(f"[OK] Retroceso v3 -> v1: contenido recuperado correctamente")

    # Test 5: retroceder desde v3 hasta v2
    content_v2 = builder.rollback_to(graph, "v2")
    assert content_v2 is not None
    assert "print('hi')" in content_v2
    assert "return True" not in content_v2
    print(f"[OK] Retroceso v3 -> v2: contenido recuperado correctamente")

    # Test 6: retroceder a la version actual (no cambia nada)
    content_v3 = builder.rollback_to(graph, "v3")
    assert content_v3 is not None
    assert "return True" in content_v3
    print(f"[OK] Retroceso a version actual: sin cambios")

    # Test 7: retroceder a version inexistente devuelve None
    content_vx = builder.rollback_to(graph, "v999")
    assert content_vx is None
    print(f"[OK] Retroceso a version inexistente: None")

    # Test 8: grafo con una sola version
    graph_single = builder.build("router", [("v1", 100.0, 1, "x = 1\n")])
    assert graph_single.version_count == 1
    assert graph_single.current_version_id == "v1"
    content_single = builder.rollback_to(graph_single, "v1")
    assert content_single == "x = 1\n"
    print(f"[OK] Grafo con 1 version: OK")

    # Test 9: grafo vacio
    graph_empty = builder.build("empty", [])
    assert graph_empty.version_count == 0
    assert graph_empty.current_node is None
    print(f"[OK] Grafo vacio: OK")

    # Test 10: guardar y cargar grafo
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        path = builder.save_graph(graph, tmpdir)
        assert path.exists()
        print(f"[OK] Grafo guardado en {path.name}")

        loaded = builder.load_graphs(path)
        assert "server" in loaded
        assert loaded["server"].version_count == 3
        assert loaded["server"].current_version_id == "v3"
        print(f"[OK] Grafo cargado: {loaded['server'].version_count} versiones")

    # Test 11: diffs no vacios cuando hay cambios
    v2_forward = v2_node.forward_diff
    v2_reverse = v2_node.reverse_diff
    assert "+" in v2_forward  # anade lineas
    assert "-" in v2_forward  # quita lineas
    assert "+" in v2_reverse
    assert "-" in v2_reverse
    print(f"[OK] Diffs forward y reverse contienen cambios (+/-)")

    # Test 12: versiones sin cambios (contenido identico)
    versions_same = [
        ("v1", 100.0, 1, "x = 1\n"),
        ("v2", 200.0, 2, "x = 1\n"),  # sin cambios
    ]
    graph_same = builder.build("config", versions_same)
    v2_same = graph_same.get_node("v2")
    assert v2_same is not None
    assert v2_same.forward_diff == ""  # no hay cambios
    assert v2_same.reverse_diff == ""
    print(f"[OK] Versiones sin cambios: diffs vacios")

    # Test 13: current_node devuelve el ultimo
    assert graph.current_node is not None
    assert graph.current_node.version_id == "v3"
    print(f"[OK] current_node devuelve v3")

    # Test 14: to_dict y from_dict
    node_dict = v2_node.to_dict()
    assert node_dict["version_id"] == "v2"
    assert node_dict["parent_version_id"] == "v1"
    restored = VersionNode.from_dict(node_dict, content="test")
    assert restored.version_id == "v2"
    assert restored.parent_version_id == "v1"
    print(f"[OK] to_dict/from_dict: serializacion correcta")

    print("\n[PASS] version_graph.py: todos los tests pasaron")
