# contexto_zai/subagents/discriminator_subagent.py -- Subagente discriminador (Capa 3): lee un tema grande y propone subdivisión en temas específicos.
"""Subagente discriminador (v3.4).

Capa 3 del sistema de clasificación temática. Cuando un tema
(especialmente "general") sigue siendo demasiado grande después
de las Capas 1 (léxica) y 2 (intención), este subagente:

1. Lee todos los intercambios del tema.
2. Identifica qué se está discutiendo realmente en cada intercambio.
3. Propone temas específicos para cada grupo de intercambios.
4. Devuelve una propuesta de subdivisión (tema -> intercambios).

El proceso principal (recovery_cycle) aplica la subdivisión
reasignando los intercambios a los nuevos temas.

Atómico standalone: importa launcher y models, nada más del proyecto.
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
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from contexto_zai.subagents.launcher import SubagentLauncher, SubagentResponse

if TYPE_CHECKING:
    from contexto_zai.models import Exchange

logger = logging.getLogger(__name__)


# ── Modelo de salida ──────────────────────────────────────────────


@dataclass
class SubdivisionProposal:
    """Propuesta de subdivisión de un tema en temas específicos.

    Attributes:
        tema_padre: Tema original que se está subdividiendo (ej: "general").
        subtemas: Lista de propuestas de subtemas.
        applied: Si la propuesta ya fue aplicada al conjunto de intercambios.
        error: Mensaje de error si el subagente falló.
    """

    tema_padre: str
    subtemas: list["SubtemaProposal"] = field(default_factory=list)
    applied: bool = False
    error: str = ""

    @property
    def is_valid(self) -> bool:
        """Una propuesta es válida si tiene al menos 2 subtemas (sino no subdivide)."""
        return len(self.subtemas) >= 2

    @property
    def total_exchanges(self) -> int:
        """Total de intercambios asignados a los subtemas."""
        return sum(s.exchange_ids.__len__() for s in self.subtemas)

    def get_subtema_for_exchange(self, exchange_id: int) -> Optional[str]:
        """Devuelve el subtema asignado a un intercambio, o None si no está mapeado."""
        for sub in self.subtemas:
            if exchange_id in sub.exchange_ids:
                return sub.tema
        return None


@dataclass
class SubtemaProposal:
    """Propuesta de un subtema específico.

    Attributes:
        tema: Nombre del subtema propuesto (ej: "validaciones_auth").
        description: Descripción corta del subtema.
        exchange_ids: Lista de IDs de intercambios que pertenecen a este subtema.
    """

    tema: str
    description: str = ""
    exchange_ids: list[int] = field(default_factory=list)

    @property
    def exchange_count(self) -> int:
        return len(self.exchange_ids)


# ── Subagente discriminador ───────────────────────────────────────


class DiscriminatorSubagent:
    """Subagente que discrimina intercambios de un tema grande.

    Se lanza cuando un tema (típicamente "general") sigue siendo
    demasiado grande después de Capa 1 (léxica) y Capa 2 (intención).
    Lee todos los intercambios del tema y propone una subdivisión
    en temas específicos basándose en el contenido real.

    Args:
        launcher: SubagentLauncher para invocar el Task.
        max_subtemas: Número máximo de subtemas a proponer (default 5).
        min_exchanges_per_subtema: Mínimo de intercambios por subtema (default 2).

    Usage:
        >>> sub = DiscriminatorSubagent(launcher=launcher)
        >>> proposal = sub.run(tema="general", exchanges=lista_exchanges)
        >>> if proposal.is_valid:
        ...     # aplicar subdivisión
        ...     for sub in proposal.subtemas:
        ...         print(f"{sub.tema}: {sub.exchange_ids}")
    """

    def __init__(
        self,
        launcher: SubagentLauncher,
        max_subtemas: int = 5,
        min_exchanges_per_subtema: int = 2,
    ) -> None:
        self._launcher = launcher
        self._max_subtemas = max_subtemas
        self._min_exchanges_per_subtema = min_exchanges_per_subtema
        logger.debug(
            "DiscriminatorSubagent inicializado: max_subtemas=%d, min_exchanges=%d",
            max_subtemas, min_exchanges_per_subtema,
        )

    # ── API pública ──────────────────────────────────────────────

    def run(
        self,
        tema: str,
        exchanges: list["Exchange"],
    ) -> SubdivisionProposal:
        """Lee los intercambios del tema y propone una subdivisión.

        Args:
            tema: Tema a subdividir (típicamente "general").
            exchanges: Lista de intercambios clasificados en ese tema.

        Returns:
            SubdivisionProposal con los subtemas propuestos.
        """
        if not exchanges:
            logger.warning(
                "DiscriminatorSubagent: lista vacía para tema '%s'", tema
            )
            return SubdivisionProposal(
                tema_padre=tema,
                subtemas=[],
                applied=False,
                error="Lista de intercambios vacía",
            )

        # Caso trivial: pocos intercambios, no se subdivide
        if len(exchanges) < self._min_exchanges_per_subtema * 2:
            logger.info(
                "DiscriminatorSubagent: tema '%s' tiene %d intercambios (< %d), no se subdivide",
                tema, len(exchanges), self._min_exchanges_per_subtema * 2,
            )
            return SubdivisionProposal(tema_padre=tema, subtemas=[])

        # Construir prompt con el contenido de los intercambios
        prompt = self._build_prompt(tema, exchanges)

        # Lanzar subagente (sin archivos adicionales: el contenido va en el prompt)
        response: SubagentResponse = self._launcher.launch(
            prompt=prompt,
            files_to_read=[],
            description=f"Discriminar tema '{tema}' en subtemas específicos",
        )

        if not response.success:
            logger.error(
                "DiscriminatorSubagent falló para tema '%s': %s",
                tema, response.error,
            )
            return SubdivisionProposal(
                tema_padre=tema,
                subtemas=[],
                applied=False,
                error=response.error,
            )

        # Parsear la respuesta en una SubdivisionProposal
        proposal = self._parse_response(response.content, tema, exchanges)

        # Validar que la propuesta cubre todos los intercambios
        self._validate_coverage(proposal, exchanges)

        logger.info(
            "DiscriminatorSubagent: tema '%s' subdividido en %d subtemas (cubre %d/%d intercambios)",
            tema, len(proposal.subtemas), proposal.total_exchanges, len(exchanges),
        )

        return proposal

    def apply(
        self,
        proposal: SubdivisionProposal,
        exchanges: list["Exchange"],
    ) -> list["Exchange"]:
        """Aplica una propuesta de subdivisión a una lista de intercambios.

        Reasigna el tema de cada intercambio según el subtema propuesto.
        Los intercambios no mapeados se quedan con el tema padre.

        Args:
            proposal: Propuesta de subdivisión.
            exchanges: Lista de intercambios a reclasificar.

        Returns:
            La misma lista con los temas actualizados (mutada in-place).
        """
        if not proposal.is_valid:
            logger.warning(
                "Apply: propuesta no válida (%d subtemas), no se aplica",
                len(proposal.subtemas),
            )
            return exchanges

        applied_count = 0
        for ex in exchanges:
            new_tema = proposal.get_subtema_for_exchange(ex.id)
            if new_tema:
                old_tema = ex.topic
                ex.topic = new_tema
                applied_count += 1
                logger.debug(
                    "Exchange %d: '%s' -> '%s'", ex.id, old_tema, new_tema
                )

        proposal.applied = True
        logger.info(
            "Apply: %d/%d intercambios reclasificados en subtemas",
            applied_count, len(exchanges),
        )
        return exchanges

    # ── Métodos privados ─────────────────────────────────────────

    def _build_prompt(self, tema: str, exchanges: list["Exchange"]) -> str:
        """Construye el prompt para el subagente discriminador.

        El prompt incluye los intercambios inline (no como archivos) porque
        son el contenido a discriminar, no archivos a consultar.
        """
        exchanges_block = "\n\n".join(
            f"--- Exchange {ex.id} ---\n"
            f"Director: {ex.director_msg.content[:500]}"
            + (f"\nAgente: {ex.agent_msgs[0].content[:300]}..." if ex.agent_msgs else "")
            for ex in exchanges
        )
        return f"""Eres un subagente discriminador de temas. Tu objetivo es leer
un conjunto de intercambios clasificados como '{tema}' y proponer una
subdivisión en temas específicos basándose en el contenido real.

Intercambios a discriminar (total: {len(exchanges)}):

{exchanges_block}

Tu tarea:
1. Lee cada intercambio e identifica qué se está discutiendo realmente.
2. Agrupa intercambios que traten el mismo subtema.
3. Propón entre 2 y {self._max_subtemas} subtemas específicos.
4. Asigna cada intercambio a un subtema (todos deben estar asignados).
5. Cada subtema debe tener al menos {self._min_exchanges_per_subtema} intercambios.

Formato de respuesta EXACTO (un subtema por bloque):

SUBTEMA: <nombre_snake_case>
DESCRIPCION: <descripción corta>
EXCHANGES: <id1>, <id2>, <id3>

SUBTEMA: <nombre_snake_case>
DESCRIPCION: <descripción corta>
EXCHANGES: <id1>, <id2>

Reglas:
- Nombres de subtemas en snake_case (sin espacios, sin acentos).
- Máximo {self._max_subtemas} subtemas.
- Todos los intercambios deben estar asignados a exactamente un subtema.
- Si no encuentras subdivisión posible, responde "NO_SUBDIVISION".

Respuesta:"""

    def _parse_response(
        self,
        content: str,
        tema_padre: str,
        exchanges: list["Exchange"],
    ) -> SubdivisionProposal:
        """Parsea la respuesta del subagente en una SubdivisionProposal.

        Formato esperado:
            SUBTEMA: nombre
            DESCRIPCION: descripción
            EXCHANGES: 1, 2, 3

            SUBTEMA: otro
            DESCRIPCION: descripción
            EXCHANGES: 4, 5
        """
        # Detectar el caso de no subdivisión
        if "NO_SUBDIVISION" in content.upper():
            logger.info(
                "Subagente respondió NO_SUBDIVISION para tema '%s'", tema_padre
            )
            return SubdivisionProposal(tema_padre=tema_padre, subtemas=[])

        # Valid IDs para filtrar IDs inventados por el subagente
        valid_ids = {ex.id for ex in exchanges}

        # Regex para parsear bloques
        pattern = re.compile(
            r"SUBTEMA:\s*(\S+)\s*\n\s*DESCRIPCION:\s*(.+?)\s*\n\s*EXCHANGES:\s*([\d,\s]+)",
            re.IGNORECASE,
        )

        subtemas: list[SubtemaProposal] = []
        for match in pattern.finditer(content):
            nombre = match.group(1).strip()
            descripcion = match.group(2).strip()
            ids_str = match.group(3)

            # Parsear lista de IDs
            try:
                ids = [
                    int(x.strip())
                    for x in ids_str.split(",")
                    if x.strip().isdigit()
                ]
            except ValueError:
                continue

            # Filtrar IDs que no existen en los intercambios reales
            ids = [i for i in ids if i in valid_ids]

            # Validar que tenga el mínimo de intercambios
            if len(ids) < self._min_exchanges_per_subtema:
                logger.debug(
                    "Subtema '%s' descartado: solo %d intercambios (< %d)",
                    nombre, len(ids), self._min_exchanges_per_subtema,
                )
                continue

            # Sanitizar nombre del subtema (snake_case)
            nombre = self._sanitize_tema_name(nombre)

            subtemas.append(SubtemaProposal(
                tema=nombre,
                description=descripcion,
                exchange_ids=ids,
            ))

        # Si no se parseó ningún subtema válido
        if not subtemas:
            logger.warning(
                "No se parsearon subtemas válidos de la respuesta del subagente"
            )
            return SubdivisionProposal(tema_padre=tema_padre, subtemas=[])

        # Si solo hay 1 subtema, no es subdivisión real
        if len(subtemas) == 1:
            logger.info(
                "Solo 1 subtema propuesto para '%s': no es subdivisión", tema_padre
            )
            return SubdivisionProposal(tema_padre=tema_padre, subtemas=[])

        # Limitar al máximo de subtemas
        if len(subtemas) > self._max_subtemas:
            subtemas = subtemas[: self._max_subtemas]
            logger.info(
                "Subtemas limitados a %d (propuesta original: %d)",
                self._max_subtemas, len(subtemas),
            )

        return SubdivisionProposal(tema_padre=tema_padre, subtemas=subtemas)

    def _validate_coverage(
        self,
        proposal: SubdivisionProposal,
        exchanges: list["Exchange"],
    ) -> None:
        """Valida y corrige la cobertura de la propuesta.

        Si hay intercambios sin asignar, los añade al primer subtema
        disponible para garantizar cobertura total.
        """
        if not proposal.is_valid:
            return

        assigned_ids: set[int] = set()
        for sub in proposal.subtemas:
            assigned_ids.update(sub.exchange_ids)

        unassigned = [ex for ex in exchanges if ex.id not in assigned_ids]
        if unassigned:
            # Asignar al primer subtema (mantiene cobertura total)
            fallback = proposal.subtemas[0]
            for ex in unassigned:
                fallback.exchange_ids.append(ex.id)
            logger.info(
                "Cobertura: %d intercambios sin asignar añadidos a '%s'",
                len(unassigned), fallback.tema,
            )

    @staticmethod
    def _sanitize_tema_name(name: str) -> str:
        """Convierte un nombre a snake_case válido.

        - Minúsculas.
        - Acentos eliminados.
        - Espacios y símbolos -> '_'.
        - Múltiples '_' colapsados a uno.
        - Sin '_' al inicio/final.
        """
        # Normalizar acentos
        import unicodedata
        normalized = unicodedata.normalize("NFKD", name)
        ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
        # Minúsculas y reemplazar no-alfanuméricos
        ascii_str = ascii_str.lower()
        sanitized = re.sub(r"[^a-z0-9]+", "_", ascii_str)
        # Quitar '_' al inicio/final
        return sanitized.strip("_")

    def __repr__(self) -> str:
        return (
            f"DiscriminatorSubagent(max_subtemas={self._max_subtemas}, "
            f"min_exchanges={self._min_exchanges_per_subtema})"
        )


# ── Auto-tests atómicos ───────────────────────────────────────────

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

    print("=== Validacion de discriminator_subagent.py ===\n")

    from contexto_zai.models import Exchange, Message, MessageRole

    # Helper: crear intercambios de prueba
    def _make_exchanges(start_id: int, contents: list[str]) -> list[Exchange]:
        return [
            Exchange(
                id=start_id + i,
                director_msg=Message(
                    seq=start_id + i,
                    role=MessageRole.USER,
                    timestamp=float(start_id + i),
                    content=c,
                ),
                topic="general",
                start_timestamp=float(start_id + i),
                end_timestamp=float(start_id + i + 1),
            )
            for i, c in enumerate(contents)
        ]

    # ── Test 1: subagente devuelve subdivisión válida ──
    def mock_subdivider_valid(prompt: str) -> str:
        return """SUBTEMA: auth_jwt
DESCRIPCION: Discusión sobre autenticación JWT y cookies
EXCHANGES: 1, 2

SUBTEMA: validaciones_pytest
DESCRIPCION: Tests y validaciones con pytest
EXCHANGES: 3, 4

SUBTEMA: config_db
DESCRIPCION: Configuración de base de datos
EXCHANGES: 5, 6"""

    exchanges = _make_exchanges(1, [
        "Hablemos del JWT y la cookie",
        "La autenticación JWT usa cookies",
        "Ejecuta el pytest de server.py",
        "Valida los tests del módulo",
        "Configura la base de datos",
        "El SQLite está en /tmp/db.sqlite",
    ])
    launcher = SubagentLauncher(task_invoker=mock_subdivider_valid)
    sub = DiscriminatorSubagent(launcher=launcher)
    proposal = sub.run(tema="general", exchanges=exchanges)

    assert proposal.is_valid, f"Propuesta debe ser válida (subtemas={len(proposal.subtemas)})"
    assert len(proposal.subtemas) == 3
    assert proposal.subtemas[0].tema == "auth_jwt"
    assert proposal.subtemas[1].tema == "validaciones_pytest"
    assert proposal.subtemas[2].tema == "config_db"
    assert proposal.total_exchanges == 6
    print(f"[OK] Subdivisión válida: 3 subtemas, {proposal.total_exchanges} intercambios")

    # ── Test 2: apply() reclasifica intercambios ──
    sub.apply(proposal, exchanges)
    assert exchanges[0].topic == "auth_jwt"
    assert exchanges[1].topic == "auth_jwt"
    assert exchanges[2].topic == "validaciones_pytest"
    assert exchanges[3].topic == "validaciones_pytest"
    assert exchanges[4].topic == "config_db"
    assert exchanges[5].topic == "config_db"
    assert proposal.applied
    print("[OK] apply(): 6 intercambios reclasificados a 3 subtemas")

    # ── Test 3: subagente responde NO_SUBDIVISION ──
    def mock_no_subdivision(prompt: str) -> str:
        return "NO_SUBDIVISION"

    exchanges2 = _make_exchanges(10, ["uno", "dos", "tres", "cuatro"])
    launcher2 = SubagentLauncher(task_invoker=mock_no_subdivision)
    sub2 = DiscriminatorSubagent(launcher=launcher2)
    proposal2 = sub2.run(tema="general", exchanges=exchanges2)

    assert not proposal2.is_valid
    assert len(proposal2.subtemas) == 0
    print("[OK] NO_SUBDIVISION: propuesta vacía correctamente")

    # ── Test 4: lista vacía -> propuesta vacía ──
    launcher3 = SubagentLauncher(task_invoker=mock_subdivider_valid)
    sub3 = DiscriminatorSubagent(launcher=launcher3)
    proposal3 = sub3.run(tema="general", exchanges=[])
    assert not proposal3.is_valid
    assert "vacía" in proposal3.error.lower() or "vac\u00eda" in proposal3.error.lower()
    print("[OK] Lista vacía: error reportado")

    # ── Test 5: pocos intercambios (< 4) -> no se subdivide ──
    exchanges5 = _make_exchanges(20, ["solo uno", "solo dos"])
    launcher5 = SubagentLauncher(task_invoker=mock_subdivider_valid)
    sub5 = DiscriminatorSubagent(launcher=launcher5)
    proposal5 = sub5.run(tema="general", exchanges=exchanges5)
    assert not proposal5.is_valid
    assert len(proposal5.subtemas) == 0
    print("[OK] Pocos intercambios (<4): no se subdivide")

    # ── Test 6: cobertura — intercambios sin asignar se añaden al primer subtema ──
    def mock_partial_coverage(prompt: str) -> str:
        # Solo cubre 4 de 6 intercambios
        return """SUBTEMA: tema_a
DESCRIPCION: Tema A
EXCHANGES: 1, 2

SUBTEMA: tema_b
DESCRIPCION: Tema B
EXCHANGES: 3, 4"""

    exchanges6 = _make_exchanges(1, ["a", "b", "c", "d", "e", "f"])
    launcher6 = SubagentLauncher(task_invoker=mock_partial_coverage)
    sub6 = DiscriminatorSubagent(launcher=launcher6)
    proposal6 = sub6.run(tema="general", exchanges=exchanges6)

    assert proposal6.is_valid
    assert proposal6.total_exchanges == 6  # cobertura total garantizada
    # Los intercambios 5 y 6 deben estar en el primer subtema
    assert 5 in proposal6.subtemas[0].exchange_ids
    assert 6 in proposal6.subtemas[0].exchange_ids
    print("[OK] Cobertura: 2 intercambios sin asignar añadidos al primer subtema")

    # ── Test 7: sanitización de nombres de subtemas ──
    assert DiscriminatorSubagent._sanitize_tema_name("Auth JWT!") == "auth_jwt"
    assert DiscriminatorSubagent._sanitize_tema_name("Configuración DB") == "configuracion_db"
    assert DiscriminatorSubagent._sanitize_tema_name("  múltiples   espacios  ") == "multiples_espacios"
    assert DiscriminatorSubagent._sanitize_tema_name("tema-con-guiones") == "tema_con_guiones"
    print("[OK] _sanitize_tema_name: acentos y símbolos normalizados a snake_case")

    # ── Test 8: subagente falla -> propuesta con error ──
    def failing_invoker(prompt: str) -> str:
        raise RuntimeError("Task API no disponible")

    exchanges8 = _make_exchanges(1, ["a", "b", "c", "d"])
    launcher8 = SubagentLauncher(task_invoker=failing_invoker)
    sub8 = DiscriminatorSubagent(launcher=launcher8)
    proposal8 = sub8.run(tema="general", exchanges=exchanges8)

    assert not proposal8.is_valid
    assert "Task invoker error" in proposal8.error
    print("[OK] Invoker que falla: error capturado en proposal.error")

    # ── Test 9: solo 1 subtema -> no es subdivisión real ──
    def mock_one_subtema(prompt: str) -> str:
        return """SUBTEMA: unico_tema
DESCRIPCION: Todo va aquí
EXCHANGES: 1, 2, 3, 4"""

    exchanges9 = _make_exchanges(1, ["a", "b", "c", "d"])
    launcher9 = SubagentLauncher(task_invoker=mock_one_subtema)
    sub9 = DiscriminatorSubagent(launcher=launcher9)
    proposal9 = sub9.run(tema="general", exchanges=exchanges9)

    assert not proposal9.is_valid
    assert len(proposal9.subtemas) == 0
    print("[OK] Solo 1 subtema: no es subdivisión real, propuesta vacía")

    # ── Test 10: límite de subtemas (max_subtemas=2) ──
    exchanges10 = _make_exchanges(1, ["a", "b", "c", "d", "e", "f"])
    launcher10 = SubagentLauncher(task_invoker=mock_subdivider_valid)
    sub10 = DiscriminatorSubagent(launcher=launcher10, max_subtemas=2)
    proposal10 = sub10.run(tema="general", exchanges=exchanges10)

    assert proposal10.is_valid
    assert len(proposal10.subtemas) == 2  # limitado a 2
    print(f"[OK] max_subtemas=2: propuesta limitada a {len(proposal10.subtemas)} subtemas")

    # ── Test 11: get_subtema_for_exchange ──
    proposal11 = sub.run(tema="general", exchanges=exchanges)  # re-usa mock_subdivider_valid
    assert proposal11.get_subtema_for_exchange(1) == "auth_jwt"
    assert proposal11.get_subtema_for_exchange(3) == "validaciones_pytest"
    assert proposal11.get_subtema_for_exchange(999) is None  # ID inexistente
    print("[OK] get_subtema_for_exchange: mapeo correcto (None para ID inexistente)")

    # ── Test 12: filtros IDs inventados por el subagente ──
    def mock_invented_ids(prompt: str) -> str:
        return """SUBTEMA: tema_x
DESCRIPCION: Tema X
EXCHANGES: 1, 2, 99

SUBTEMA: tema_y
DESCRIPCION: Tema Y
EXCHANGES: 3, 4, 100"""

    exchanges12 = _make_exchanges(1, ["a", "b", "c", "d"])
    launcher12 = SubagentLauncher(task_invoker=mock_invented_ids)
    sub12 = DiscriminatorSubagent(launcher=launcher12)
    proposal12 = sub12.run(tema="general", exchanges=exchanges12)

    assert proposal12.is_valid
    # IDs 99 y 100 (inventados) deben haberse filtrado
    assert 99 not in proposal12.subtemas[0].exchange_ids
    assert 100 not in proposal12.subtemas[1].exchange_ids
    print("[OK] IDs inventados (99, 100) filtrados correctamente")

    print("\n[PASS] discriminator_subagent.py: todos los tests pasaron")
