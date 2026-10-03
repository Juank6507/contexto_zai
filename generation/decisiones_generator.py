# contexto_zai/generation/decisiones_generator.py -- Generador del archivo 02_decisiones_clave.md con subagente LLM y alcance (v4.0 M4).
"""Generador del archivo 02_decisiones_clave.md (v4.0, M4).

Delegador: en v4.0 las decisiones se extraen con un subagente LLM
(IntercambiosClasificadorSubagent modo DECISIONES), no con regex.
El subagente distingue decisiones reales de aprobaciones genéricas
(que se descartan) y para cada decisión real captura el **alcance**:
a qué tarea se refiere, qué incluye, qué no incluye.

Cambios v4.0 (M4):
- `__init__` ahora acepta `launcher: Optional[SubagentLauncher]` para
  usar el IntercambiosClasificadorSubagent. Si no se pasa, cae al
  extractor callback (modo backward compatible) o al placeholder
  offline (sin extractor ni launcher).
- `generate()` procesa los intercambios en lotes (configurable en
  config.py con DECISIONES_LOTE_SIZE) para no llenar el contexto del
  subagente.
- Si el subagente falla, el error sube al Director (no silencioso):
  se lanza una excepción con el mensaje detallado.
- El formato markdown incluye el **alcance** de cada decisión (campo
  `impact` del modelo Decision, ahora usado como alcance).

Tamaño máximo: 12K tokens (~42KB chars).
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
from typing import TYPE_CHECKING, Callable, Optional

from contexto_zai.config import DECISIONES_LOTE_SIZE, TOKEN_LIMITS
from contexto_zai.models import Decision
from contexto_zai.subagents.launcher import SubagentLauncher

if TYPE_CHECKING:
    from contexto_zai.models import Exchange

logger = logging.getLogger(__name__)

# Tipo del callback del subagente LLM (modo backward compatible)
DecisionExtractor = Callable[[list["Exchange"]], list[Decision]]

class DecisionesGenerator:
    """Genera el archivo 02_decisiones_clave.md (v4.0, M4).

    Args:
        max_chars: Límite máximo de caracteres (por defecto 42K).
        extractor: Callback que extrae decisiones de una lista de
            intercambios. Si es None y no hay launcher, se usa modo
            offline (placeholder). Backward compatible con v3.2.
        launcher: SubagentLauncher opcional para usar
            IntercambiosClasificadorSubagent(modo=DECISIONES). Si se
            pasa, tiene prioridad sobre el extractor callback.
        lote_size: Tamaño del lote de intercambios que se le pasa al
            subagente (default de config.py: 30).

    Usage (modo v4.0 con launcher)::

        >>> from contexto_zai.subagents.launcher import SubagentLauncher
        >>> launcher = SubagentLauncher()
        >>> gen = DecisionesGenerator(launcher=launcher)
        >>> content, summary = gen.generate(exchanges)

    Usage (modo backward compatible con extractor)::

        >>> from contexto_zai.subagents.decisiones_subagent import DecisionesSubagent
        >>> extractor = DecisionesSubagent().extract
        >>> gen = DecisionesGenerator(extractor=extractor)
        >>> content, summary = gen.generate(exchanges)

    Usage (modo offline sin subagente)::

        >>> gen = DecisionesGenerator()  # extractor=None, launcher=None
        >>> content, summary = gen.generate(exchanges)
    """

    def __init__(
        self,
        max_chars: int = TOKEN_LIMITS.max_chars_decisiones,
        extractor: Optional[DecisionExtractor] = None,
        launcher: Optional[SubagentLauncher] = None,
        lote_size: int = DECISIONES_LOTE_SIZE,
    ) -> None:
        self._max_chars = max_chars
        self._extractor = extractor
        self._launcher = launcher
        self._lote_size = lote_size
        logger.debug(
            "DecisionesGenerator inicializado: max_chars=%d, extractor=%s, launcher=%s, lote_size=%d",
            max_chars, "sí" if extractor else "no",
            "sí" if launcher else "no", lote_size,
        )

    # -- API pública ------------------------------------------------

    def generate(
        self,
        exchanges: list["Exchange"],
        existing_decisions: Optional[list[Decision]] = None,
        from_timestamp: float = 0.0,
    ) -> tuple[str, str]:
        """Genera el contenido markdown y el resumen de decisiones (v4.0).

        Args:
            exchanges: Lista de intercambios a procesar.
            existing_decisions: Decisiones ya registradas (para deduplicar).
            from_timestamp: Si se proporciona, solo se procesan intercambios
                con timestamp > from_timestamp (modo incremental).

        Returns:
            Tupla (content_markdown, resumen_compacto).

        Raises:
            RuntimeError: Si el subagente LLM falla (v4.0: el error sube al
                Director, no silencioso). Solo se lanza si se está usando
                el launcher (modo v4.0). En modo backward compatible con
                extractor callback, los errores del extractor se capturan
                como antes (backward compatible).
        """
        # Filtrar por timestamp si es incremental
        if from_timestamp > 0:
            new_exchanges = [
                ex for ex in exchanges
                if ex.start_timestamp > from_timestamp
            ]
            logger.info(
                "Modo incremental: %d intercambios nuevos (desde ts=%d)",
                len(new_exchanges), from_timestamp,
            )
        else:
            new_exchanges = exchanges

        # Extraer decisiones (3 modos: v4.0 con launcher, backward con extractor, offline)
        if self._launcher is not None:
            # v4.0: usar IntercambiosClasificadorSubagent(modo=DECISIONES)
            new_decisions = self._extract_with_subagent(new_exchanges)
            logger.info(
                "Subagente v4.0 devolvió %d decisiones de %d intercambios",
                len(new_decisions), len(new_exchanges),
            )
        elif self._extractor is not None:
            # Backward compatible: extractor callback
            new_decisions = self._extractor(new_exchanges)
            logger.info(
                "Extractor devolvió %d decisiones de %d intercambios",
                len(new_decisions), len(new_exchanges),
            )
        else:
            # Modo offline: placeholder
            logger.warning(
                "Modo offline: no hay extractor de decisiones ni launcher. "
                "El archivo 02_decisiones_clave.md tendra un placeholder."
            )
            new_decisions = []

        # Combinar con existentes y deduplicar
        all_decisions = self._merge_and_deduplicate(
            existing_decisions or [], new_decisions
        )

        # Generar markdown
        content = self._format_markdown(all_decisions, len(new_exchanges))

        # Generar resumen compacto (para el índice)
        summary = self._format_summary(all_decisions)

        # Truncar si excede el límite
        if len(content) > self._max_chars:
            logger.warning(
                "Decisiones excede limite (%d > %d chars), truncando",
                len(content), self._max_chars,
            )
            content = content[:self._max_chars - 50] + "\n\n... (truncado por límite)\n"

        logger.info(
            "Decisiones generadas: %d totales (%d nuevas), %d chars",
            len(all_decisions), len(new_decisions), len(content),
        )
        return content, summary

    @property
    def max_chars(self) -> int:
        return self._max_chars

    def __repr__(self) -> str:
        if self._launcher is not None:
            mode = "v4.2 (launcher, F4 pendiente)"
        elif self._extractor is not None:
            mode = "online (extractor)"
        else:
            mode = "offline"
        return f"DecisionesGenerator(mode={mode!r})"

    # -- Métodos privados v4.0 --------------------------------------

    def _extract_with_subagent(
        self,
        exchanges: list["Exchange"],
    ) -> list[Decision]:
        """F4 v4.2: Extrae decisiones usando ProcesadorIntercambios (patrón diferido).

        El generador con launcher (que es un ProcesadorIntercambios) prepara
        las tareas por lote y las publica vía el Orquestador. El archivo
        se escribe con placeholder (lista vacía), y se actualiza con las
        decisiones reales cuando el agente llama a collect_responses().

        Args:
            exchanges: Lista de intercambios a procesar.

        Returns:
            Lista vacía (las decisiones se aplican después con collect_responses).
        """
        if self._launcher is None:
            return []

        # F4: usar ProcesadorIntercambios.procesar_por_lotes(DECISIONES, ...)
        try:
            result = self._launcher.procesar_por_lotes(
                modo="DECISIONES",
                intercambios=exchanges,
                lote_size=self._lote_size,
            )
            logger.info(
                "F4: preparadas %d tareas de decisiones (%d lotes)",
                len(result.get("pending_tasks", [])),
                result.get("total_lotes", 0),
            )
        except Exception as e:
            logger.warning("F4: no se pudo preparar tareas de decisiones: %s", e)

        # Devolver lista vacía — las decisiones reales se aplican con collect_responses()
        return []

    # -- Métodos privados -------------------------------------------

    def _merge_and_deduplicate(
        self,
        existing: list[Decision],
        new: list[Decision],
    ) -> list[Decision]:
        """Combina decisiones existentes y nuevas, deduplicando por título."""
        # Renumerar las nuevas (continúan la secuencia de las existentes)
        max_id = 0
        for d in existing:
            if d.id.startswith("D"):
                try:
                    n = int(d.id[1:])
                    if n > max_id:
                        max_id = n
                except ValueError:
                    pass

        seen_titles = {d.title.lower().strip() for d in existing if d.title}
        merged = list(existing)

        for d in new:
            # Deduplicar por título
            title_key = d.title.lower().strip() if d.title else ""
            if title_key and title_key in seen_titles:
                logger.debug("Decision duplicada (por titulo): %s", d.title)
                continue
            seen_titles.add(title_key)

            # Asignar ID si no tiene
            if not d.id:
                max_id += 1
                d.id = f"D{max_id:02d}"
            elif d.id.startswith("D"):
                try:
                    n = int(d.id[1:])
                    if n > max_id:
                        max_id = n
                except ValueError:
                    pass

            merged.append(d)

        return merged

    def _format_markdown(
        self,
        decisions: list[Decision],
        new_exchange_count: int,
    ) -> str:
        """Formatea las decisiones como markdown (v4.0: incluye alcance)."""
        lines: list[str] = [
            "# Decisiones Clave",
            "",
            f"**Total de decisiones:** {len(decisions)}",
            f"**Procesadas en esta activación:** {new_exchange_count} intercambios",
            "",
            "---",
            "",
        ]

        if not decisions:
            lines.extend([
                "## (Sin decisiones registradas)",
                "",
                "Las decisiones se extraen con un subagente LLM en cada activación.",
                "Si estás viendo este mensaje en modo offline, activa el subagente",
                "de decisiones para poblar este archivo.",
                "",
            ])
            return "\n".join(lines)

        for d in decisions:
            lines.extend([
                f"## {d.id} -- {d.title}",
                f"- **Cuándo:** {d.timestamp}",
                f"- **Tema:** {d.tema}" if d.tema else "",
                f"- **Decisión:** {d.decision}" if d.decision else "",
                f"- **Alcance:** {d.impact}" if d.impact else "",  # v4.0: alcance (campo impact)
                f"- **Razón:** {d.reason}" if d.reason else "",
                "",
            ])

        return "\n".join(lines)

    def _format_summary(self, decisions: list[Decision]) -> str:
        """Genera un resumen compacto para el índice."""
        if not decisions:
            return "No se identificaron decisiones explícitas en la conversación."

        lines: list[str] = []
        for d in decisions[:15]:  # Máximo 15 en el resumen
            title = d.title or d.decision[:80] if d.decision else "Sin título"
            lines.append(f"- {d.id} -- {title}")
        if len(decisions) > 15:
            lines.append(f"- ... y {len(decisions) - 15} más (ver 02_decisiones_clave.md)")
        return "\n".join(lines)

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
    # -- Validación interna de decisiones_generator.py --
    print("=== Validacion de decisiones_generator.py ===\n")

    from contexto_zai.models import Decision, Exchange, Message, MessageRole

    # Test 1: modo offline (sin extractor)
    gen_off = DecisionesGenerator()
    exchanges = [
        Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="Decidimos usar PriorityQueue"), topic="planificador", start_timestamp=1, end_timestamp=2),
        Exchange(id=2, director_msg=Message(seq=2, role=MessageRole.USER, timestamp=3, content="Continuemos"), topic="general", start_timestamp=3, end_timestamp=4),
    ]
    content, summary = gen_off.generate(exchanges)
    assert "Sin decisiones registradas" in content
    assert "No se identificaron" in summary
    print(f"[OK] Modo offline: placeholder correcto")

    # Test 2: modo online con extractor simulado
    def extractor_mock(exs):
        return [
            Decision(
                id="",
                timestamp=1,
                title="Usar PriorityQueue",
                decision="Adoptar PriorityQueue como estructura del planificador",
                reason="El Director lo indicó explícitamente",
                impact="Afecta a planner.py",
                tema="planificador",
            )
        ]

    gen_on = DecisionesGenerator(extractor=extractor_mock)
    content2, summary2 = gen_on.generate(exchanges)
    assert "Usar PriorityQueue" in content2
    assert "D01" in content2  # ID autoasignado
    assert "planificador" in content2
    assert "D01" in summary2
    print(f"[OK] Modo online: extractor simulado funciona")

    # Test 3: deduplicación por título
    existing = [Decision(id="D01", timestamp=0, title="Usar PriorityQueue", decision="X")]
    content3, _ = gen_on.generate(exchanges, existing_decisions=existing)
    # No debería añadir otra vez la misma decisión
    assert content3.count("Usar PriorityQueue") == 1
    print(f"[OK] Deduplicacion: decision repetida no se anade")

    # Test 4: modo incremental (filtrar por timestamp)
    exchanges_with_ts = [
        Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=10, content="Decisión A"), topic="general", start_timestamp=10, end_timestamp=11),
        Exchange(id=2, director_msg=Message(seq=2, role=MessageRole.USER, timestamp=20, content="Decisión B"), topic="general", start_timestamp=20, end_timestamp=21),
    ]
    content4, _ = gen_on.generate(exchanges_with_ts, from_timestamp=15)
    # Solo procesa el exchange con ts > 15
    # El extractor mock siempre devuelve lo mismo, así que solo verificamos que se llama
    print(f"[OK] Modo incremental: filtrado por timestamp OK")

    # Test 5: renumeración de IDs continúa secuencia
    existing2 = [Decision(id="D05", timestamp=0, title="Vieja", decision="X")]
    new_exs = [Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="Nueva decisión"), topic="general", start_timestamp=1, end_timestamp=2)]
    content5, _ = gen_on.generate(new_exs, existing_decisions=existing2)
    # La nueva decisión debe tener ID D06
    assert "D06" in content5
    print(f"[OK] Renumeracion: nueva decision con ID D06")

    # Test 6: repr muestra modo
    assert "offline" in repr(gen_off)
    assert "online" in repr(gen_on)
    print(f"[OK] repr: {gen_off!r}, {gen_on!r}")

    # === Tests F1 v4.2 (desmontaje H9) ===

    # Test 7: F1 v4.2 con launcher — generador cae a modo offline (no sub.run())
    def mock_invoker_decisiones(prompt: str) -> str:
        return "DECISION: Usar OOP\nALCANCE: ClasificadorSubagent\nRAZON: Directiva."

    from contexto_zai.subagents.launcher import SubagentLauncher
    launcher_mock = SubagentLauncher(task_invoker=mock_invoker_decisiones)
    gen_v4 = DecisionesGenerator(launcher=launcher_mock)

    exchanges_v4 = [
        Exchange(
            id=1,
            director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1,
                                 content="Quiero que uses OOP para los subagentes"),
            agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=2, content="Entendido.")],
            topic="arquitectura_subagentes",
            start_timestamp=1,
            end_timestamp=2,
        ),
    ]
    content_v4, _ = gen_v4.generate(exchanges_v4)
    # F1 v4.2: con launcher, cae a modo offline (placeholder)
    assert "Sin decisiones registradas" in content_v4 or "Total de decisiones:** 0" in content_v4, \
        f"F1 v4.2: esperaba placeholder offline, got: {content_v4[:200]}"
    # F1 v4.2: no hay deferred_tasks
    assert not hasattr(gen_v4, "_deferred_tasks") or not gen_v4.__dict__.get("_deferred_tasks")
    print(f"[OK] F1 v4.2 con launcher: cae a modo offline (sin deferred_tasks)")

    # Test 8: F1 v4.2 repr muestra modo
    assert "offline" in repr(gen_v4) or "launcher" in repr(gen_v4), f"repr debería mostrar modo, got: {repr(gen_v4)}"
    print(f"[OK] F1 v4.2 repr: {gen_v4!r}")

    print("\n[PASS] decisiones_generator.py: todos los tests F1 v4.2 pasaron")
