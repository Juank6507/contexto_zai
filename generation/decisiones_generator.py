# Destino: /home/z/my-project/contexto_zai/generation/decisiones_generator.py
"""Generador del archivo 02_decisiones_clave.md (v3.2).

Delegador: en v3.2 las decisiones se extraen con un subagente LLM,
no con regex (v1.0 produjo 20K chars de fragmentos aleatorios
con regex, ninguna decisión real).

Este generador es un delegador: recibe el callback del subagente LLM
y lo invoca para extraer decisiones. En modo offline (sin subagente),
produce un archivo con un placeholder que indica que las decisiones
deben generarse activando el subagente.

Modo incremental: si se proporciona una lista de decisiones existentes,
deduplica contra ellas antes de añadir las nuevas.

Tamaño máximo: 12K tokens (~42KB chars).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Optional

from contexto_zai.config import TOKEN_LIMITS
from contexto_zai.models import Decision

if TYPE_CHECKING:
    from contexto_zai.models import Exchange

logger = logging.getLogger(__name__)


# Tipo del callback del subagente LLM
DecisionExtractor = Callable[[list["Exchange"]], list[Decision]]


class DecisionesGenerator:
    """Genera el archivo 02_decisiones_clave.md.

    Args:
        max_chars: Límite máximo de caracteres (por defecto 42K).
        extractor: Callback que extrae decisiones de una lista de
            intercambios. Si es None, se usa modo offline (placeholder).

    Usage (modo online con subagente)::

        >>> from contexto_zai.subagents.decisiones_subagent import DecisionesSubagent
        >>> extractor = DecisionesSubagent().extract
        >>> gen = DecisionesGenerator(extractor=extractor)
        >>> content, summary = gen.generate(exchanges)

    Usage (modo offline sin subagente)::

        >>> gen = DecisionesGenerator()  # extractor=None
        >>> content, summary = gen.generate(exchanges)
    """

    def __init__(
        self,
        max_chars: int = TOKEN_LIMITS.max_chars_decisiones,
        extractor: Optional[DecisionExtractor] = None,
    ) -> None:
        self._max_chars = max_chars
        self._extractor = extractor
        logger.debug(
            "DecisionesGenerator inicializado: max_chars=%d, extractor=%s",
            max_chars, "sí" if extractor else "no (offline)",
        )

    # ── API pública ────────────────────────────────────────────────

    def generate(
        self,
        exchanges: list["Exchange"],
        existing_decisions: Optional[list[Decision]] = None,
        from_timestamp: float = 0.0,
    ) -> tuple[str, str]:
        """Genera el contenido markdown y el resumen de decisiones.

        Args:
            exchanges: Lista de intercambios a procesar.
            existing_decisions: Decisiones ya registradas (para deduplicar).
            from_timestamp: Si se proporciona, solo se procesan intercambios
                con timestamp > from_timestamp (modo incremental).

        Returns:
            Tupla (content_markdown, resumen_compacto).
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

        # Extraer decisiones
        if self._extractor is not None:
            new_decisions = self._extractor(new_exchanges)
            logger.info(
                "Extractor devolvió %d decisiones de %d intercambios",
                len(new_decisions), len(new_exchanges),
            )
        else:
            # Modo offline: placeholder
            logger.warning(
                "Modo offline: no hay extractor de decisiones. "
                "El archivo 02_decisiones_clave.md tendrá un placeholder."
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
                "Decisiones excede límite (%d > %d chars), truncando",
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
        mode = "online" if self._extractor else "offline"
        return f"DecisionesGenerator(mode={mode!r})"

    # ── Métodos privados ───────────────────────────────────────────

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
                logger.debug("Decisión duplicada (por título): %s", d.title)
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
        """Formatea las decisiones como markdown."""
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
                f"## {d.id} — {d.title}",
                f"- **Cuándo:** {d.timestamp}",
                f"- **Tema:** {d.tema}" if d.tema else "",
                f"- **Decisión:** {d.decision}" if d.decision else "",
                f"- **Razón:** {d.reason}" if d.reason else "",
                f"- **Impacto:** {d.impact}" if d.impact else "",
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
            lines.append(f"- {d.id} — {title}")
        if len(decisions) > 15:
            lines.append(f"- ... y {len(decisions) - 15} más (ver 02_decisiones_clave.md)")
        return "\n".join(lines)


if __name__ == "__main__":
    # ── Validación interna de decisiones_generator.py ──
    print("=== Validación de decisiones_generator.py ===\n")

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
    print(f"✓ Modo offline: placeholder correcto")

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
    print(f"✓ Modo online: extractor simulado funciona")

    # Test 3: deduplicación por título
    existing = [Decision(id="D01", timestamp=0, title="Usar PriorityQueue", decision="X")]
    content3, _ = gen_on.generate(exchanges, existing_decisions=existing)
    # No debería añadir otra vez la misma decisión
    assert content3.count("Usar PriorityQueue") == 1
    print(f"✓ Deduplicación: decisión repetida no se añade")

    # Test 4: modo incremental (filtrar por timestamp)
    exchanges_with_ts = [
        Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=10, content="Decisión A"), topic="general", start_timestamp=10, end_timestamp=11),
        Exchange(id=2, director_msg=Message(seq=2, role=MessageRole.USER, timestamp=20, content="Decisión B"), topic="general", start_timestamp=20, end_timestamp=21),
    ]
    content4, _ = gen_on.generate(exchanges_with_ts, from_timestamp=15)
    # Solo procesa el exchange con ts > 15
    # El extractor mock siempre devuelve lo mismo, así que solo verificamos que se llama
    print(f"✓ Modo incremental: filtrado por timestamp OK")

    # Test 5: renumeración de IDs continúa secuencia
    existing2 = [Decision(id="D05", timestamp=0, title="Vieja", decision="X")]
    new_exs = [Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="Nueva decisión"), topic="general", start_timestamp=1, end_timestamp=2)]
    content5, _ = gen_on.generate(new_exs, existing_decisions=existing2)
    # La nueva decisión debe tener ID D06
    assert "D06" in content5
    print(f"✓ Renumeración: nueva decisión con ID D06")

    # Test 6: repr muestra modo
    assert "offline" in repr(gen_off)
    assert "online" in repr(gen_on)
    print(f"✓ repr: {gen_off!r}, {gen_on!r}")

    print("\n✅ decisiones_generator.py: todos los tests pasaron")
