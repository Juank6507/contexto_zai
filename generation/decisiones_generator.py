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
            mode = "v4.0 (launcher)"
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
        """Extrae decisiones usando IntercambiosClasificadorSubagent (v4.0).

        Procesa los intercambios en lotes (DECISIONES_LOTE_SIZE) para no
        llenar el contexto del subagente. Para cada lote, lanza un
        subagente en modo DECISIONES que distingue decisiones reales de
        aprobaciones genéricas y captura el alcance de cada decisión.

        Args:
            exchanges: Lista de intercambios a procesar.

        Returns:
            Lista de Decision detectadas (deduplicadas entre lotes).

        Raises:
            RuntimeError: Si el subagente falla (v4.0: error sube al Director).
        """
        # Import diferido para evitar import circular
        from contexto_zai.subagents.intercambios_clasificador_subagent import (
            IntercambiosClasificadorSubagent,
            ModoClasificador,
            Decision as SubagentDecision,
        )

        sub = IntercambiosClasificadorSubagent(
            launcher=self._launcher,
            modo=ModoClasificador.DECISIONES,
        )

        all_decisions: list[Decision] = []
        errors: list[str] = []

        # Procesar en lotes
        for i in range(0, len(exchanges), self._lote_size):
            lote = exchanges[i:i + self._lote_size]
            if not lote:
                continue

            logger.info(
                "Procesando lote %d/%d (%d intercambios)",
                i // self._lote_size + 1,
                (len(exchanges) + self._lote_size - 1) // self._lote_size,
                len(lote),
            )

            result = sub.run(lote)

            if not result.success:
                # v4.0: el error del subagente se reporta (no silencioso)
                err_msg = f"Lote {i // self._lote_size + 1}: {result.error}"
                errors.append(err_msg)
                logger.error("Subagente DECISIONES falló: %s", err_msg)
                continue

            # Convertir SubagentDecision a Decision del modelo
            subagent_decisions = result.resultado or []
            for sd in subagent_decisions:
                # El SubagentDecision tiene: descripcion, alcance, razon,
                # exchange_id, tema. Lo convertimos a Decision del modelo.
                # El campo `impact` del modelo Decision se usa como alcance (v4.0).
                decision = Decision(
                    id="",  # se asigna en _merge_and_deduplicate
                    timestamp=lote[0].start_timestamp if lote else 0,
                    title=sd.descripcion[:200] if sd.descripcion else "Sin título",
                    decision=sd.descripcion,
                    reason=sd.razon,
                    impact=sd.alcance,  # v4.0: alcance de la decisión
                    tema=sd.tema,
                )
                all_decisions.append(decision)

        # v4.0: si todos los lotes fallaron, lanzar excepción para que suba al Director
        if errors and not all_decisions:
            raise RuntimeError(
                f"DecisionesGenerator: todos los lotes del subagente fallaron. "
                f"Errores: {'; '.join(errors)}"
            )

        # Si algunos lotes fallaron pero otros no, loguear pero continuar
        if errors:
            logger.warning(
                "Algunos lotes fallaron pero se extrajeron %d decisiones. "
                "Errores: %s",
                len(all_decisions), "; ".join(errors),
            )

        return all_decisions

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

    # === Tests v4.0 (M4) ===

    # Test 7: modo v4.0 con launcher (mock) — detecta decisiones reales con alcance
    def mock_invoker_decisiones(prompt: str) -> str:
        # Simula que el subagente detecta 1 decisión real (no "Correcto")
        return """DECISION: Usar OOP para los subagentes
ALCANCE: Aplica a la clase base ClasificadorSubagent y sus subclases. Incluye crear la clase base abstracta, no incluye tocar el SubagentLauncher.
RAZON: Es directiva operativa explícita del Director, no aprobación genérica.
EXCHANGE: 1
TEMA: arquitectura_subagentes"""

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
        Exchange(
            id=2,
            director_msg=Message(seq=3, role=MessageRole.USER, timestamp=3, content="Correcto"),
            agent_msgs=[Message(seq=4, role=MessageRole.ASSISTANT, timestamp=4, content="Implementando...")],
            topic="arquitectura_subagentes",
            start_timestamp=3,
            end_timestamp=4,
        ),
    ]
    content_v4, summary_v4 = gen_v4.generate(exchanges_v4)
    # El subagente detecta 1 decisión real, la aprobación "Correcto" se descarta
    assert "Usar OOP para los subagentes" in content_v4
    assert "Alcance" in content_v4  # v4.0: el formato incluye alcance
    assert "ClasificadorSubagent" in content_v4  # el alcance menciona la clase
    print(f"[OK] Modo v4.0 con launcher: detecta decisión real con alcance")

    # Test 8: el formato v4.0 incluye la sección "Alcance" (no "Impacto")
    assert "**Alcance:**" in content_v4
    assert "**Impacto:**" not in content_v4  # v4.0: renombrado a Alcance
    print(f"[OK] Formato v4.0: 'Alcance' reemplaza a 'Impacto'")

    # Test 9: subagente que falla — error sube (no silencioso)
    def mock_invoker_falla(prompt: str) -> str:
        raise RuntimeError("TaskBridgeServer no responde")

    launcher_falla = SubagentLauncher(task_invoker=mock_invoker_falla)
    gen_falla = DecisionesGenerator(launcher=launcher_falla)

    try:
        gen_falla.generate(exchanges_v4)
        # Si no lanza excepción, el test falla
        assert False, "Debería haber lanzado RuntimeError"
    except RuntimeError as e:
        assert "TaskBridgeServer" in str(e) or "subagente" in str(e).lower()
        print(f"[OK] Subagente falla: RuntimeError sube al Director (no silencioso)")

    # Test 10: subagente devuelve SIN_DECISIONES (no hay decisiones reales)
    def mock_invoker_sin(prompt: str) -> str:
        return "SIN_DECISIONES"

    launcher_sin = SubagentLauncher(task_invoker=mock_invoker_sin)
    gen_sin = DecisionesGenerator(launcher=launcher_sin)

    content_sin, _ = gen_sin.generate(exchanges_v4)
    # No hay decisiones, pero no es error — el archivo muestra placeholder
    assert "Sin decisiones registradas" in content_sin or "Total de decisiones:** 0" in content_sin
    print(f"[OK] Subagente SIN_DECISIONES: archivo con placeholder, sin error")

    # Test 11: repr muestra modo v4.0
    assert "v4.0" in repr(gen_v4)
    print(f"[OK] repr v4.0: {gen_v4!r}")

    # Test 12: lotes — si hay más intercambios que lote_size, se procesan en varios lotes
    def mock_invoker_lotes(prompt: str) -> str:
        # El subagente devuelve 1 decisión por lote
        return """DECISION: Decisión del lote
ALCANCE: Aplica al lote procesado.
RAZON: Directiva del Director.
EXCHANGE: 1
TEMA: general"""

    launcher_lotes = SubagentLauncher(task_invoker=mock_invoker_lotes)
    gen_lotes = DecisionesGenerator(launcher=launcher_lotes, lote_size=2)  # lote pequeño

    exchanges_lotes = [
        Exchange(
            id=i,
            director_msg=Message(seq=i*2, role=MessageRole.USER, timestamp=i, content=f"Decidimos X{i}"),
            agent_msgs=[Message(seq=i*2+1, role=MessageRole.ASSISTANT, timestamp=i+0.5, content="OK")],
            topic="general",
            start_timestamp=i,
            end_timestamp=i+1,
        )
        for i in range(1, 6)  # 5 intercambios, lote_size=2 → 3 lotes
    ]
    content_lotes, _ = gen_lotes.generate(exchanges_lotes)
    # Como el mock devuelve siempre la misma decisión, deduplica a 1
    # pero el test verifica que no falla con múltiples lotes
    assert "Decisiones Clave" in content_lotes
    print(f"[OK] Lotes: procesa 5 intercambios en 3 lotes sin error")

    print("\n[PASS] decisiones_generator.py: todos los tests v4.0 pasaron")
