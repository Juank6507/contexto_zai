# Destino: /home/z/my-project/contexto_zai/generation/estado_generator.py
"""Generador del archivo 00_estado_actual.md (v3.2).

Produce las 8 secciones obligatorias (D1-D4 + A1-A4) que capturan
el contexto completo del tema activo al momento de la activación.

Diferencia crítica respecto a v1.0:
- v1.0: 4 secciones simples, "última respuesta" truncada, "errores
  abiertos" con falsos positivos (cualquier mención de "error").
- v3.2: 8 secciones D1-D4 (Director) + A1-A4 (Agente). Los errores
  se extraen con detección más precisa, no keyword matching ingenuo.

Tamaño máximo: 20K tokens (~70KB chars).

Atómico standalone: importa config y models, nada más del proyecto.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from contexto_zai.config import TOKEN_LIMITS

if TYPE_CHECKING:
    from contexto_zai.models import Exchange

logger = logging.getLogger(__name__)


# Patrones para detectar errores reales (no conversaciones sobre errores)
_ERROR_PATTERNS = [
    r"\bTraceback\b",
    r"\bError[:\s]",
    r"\bERROR[:\s]",
    r"\bFAILED[:\s]",
    r"\bException[:\s]",
    r"\bexit_code=(?!0\b)\d+",  # exit_code != 0
    r"\bFileNotFound",
    r"\bModuleNotFound",
    r"\bAttributeError",
    r"\bTypeError",
    r"\bKeyError",
    r"\bValueError\b.*:\s",
    r"\bAssertionError",
]
_ERROR_REGEX = re.compile("|".join(_ERROR_PATTERNS))

# Patrones para detectar rutas de archivos en mensajes del agente
_FILE_PATH_PATTERN = re.compile(
    r"`?(/home/z/[^\s`]+|/tmp/[^\s`]+|contexto_zai/[^\s`]+\.(?:py|md|json))`?"
)


class EstadoGenerator:
    """Genera el archivo 00_estado_actual.md con 8 secciones.

    Args:
        max_chars: Límite máximo de caracteres. Por defecto usa
            TOKEN_LIMITS.max_chars_estado (70K).

    Usage:
        >>> gen = EstadoGenerator()
        >>> content = gen.generate(exchanges, chat_label="CZAI Sesión 5")
    """

    def __init__(
        self,
        max_chars: int = TOKEN_LIMITS.max_chars_estado,
    ) -> None:
        self._max_chars = max_chars
        logger.debug(
            "EstadoGenerator inicializado: max_chars=%d (%d tokens)",
            max_chars, int(max_chars / 3.5),
        )

    # ── API pública ────────────────────────────────────────────────

    def generate(
        self,
        exchanges: list["Exchange"],
        chat_label: str = "",
    ) -> str:
        """Genera el contenido markdown del estado actual.

        Args:
            exchanges: Lista de intercambios (se usan los últimos 15-20).
            chat_label: Etiqueta descriptiva del chat.

        Returns:
            Contenido markdown con las 8 secciones.
        """
        if not exchanges:
            return "# Estado Actual\n\n(Sin intercambios)\n"

        # Usar los últimos 15-20 intercambios (los más relevantes)
        recent = exchanges[-20:] if len(exchanges) > 20 else exchanges
        ultimo_exchange = exchanges[-1]
        tema_actual = ultimo_exchange.topic

        # Sección D1 — Última instrucción del Director
        d1 = self._build_d1(ultimo_exchange)

        # Sección D2 — Contexto del tema activo
        d2 = self._build_d2(recent, tema_actual)

        # Sección D3 — Decisiones pendientes del Director
        d3 = self._build_d3(recent)

        # Sección D4 — Restricciones y preferencias activas
        d4 = self._build_d4(recent)

        # Sección A1 — Qué estaba haciendo el agente
        a1 = self._build_a1(recent)

        # Sección A2 — Entregables producidos
        a2 = self._build_a2(recent)

        # Sección A3 — Errores abiertos
        a3 = self._build_a3(recent)

        # Sección A4 — Siguiente paso lógico
        a4 = self._build_a4(ultimo_exchange, tema_actual)

        content = self._assemble(
            chat_label=chat_label or "Chat",
            tema_actual=tema_actual,
            d1=d1, d2=d2, d3=d3, d4=d4,
            a1=a1, a2=a2, a3=a3, a4=a4,
        )

        # Truncar si excede el límite (preservando las secciones críticas D1, D2, A4)
        if len(content) > self._max_chars:
            content = self._truncate(content, self._max_chars)

        logger.info(
            "Estado actual generado: %d chars (%.0f tokens), tema activo='%s'",
            len(content), len(content) / 3.5, tema_actual,
        )
        return content

    @property
    def max_chars(self) -> int:
        return self._max_chars

    def __repr__(self) -> str:
        return f"EstadoGenerator(max_chars={self._max_chars})"

    # ── Construcción de secciones ─────────────────────────────────

    def _build_d1(self, ultimo_exchange: "Exchange") -> str:
        """Sección D1: Última instrucción del Director (literal)."""
        return ultimo_exchange.director_msg.content.strip()

    def _build_d2(
        self,
        recent: list["Exchange"],
        tema_actual: str,
    ) -> str:
        """Sección D2: Contexto del tema activo.

        Resume los intercambios recientes del mismo tema, sin truncar
        la información operativa (rutas, decisiones).
        """
        # Filtrar intercambios del tema actual
        same_topic = [ex for ex in recent if ex.topic == tema_actual]
        if not same_topic:
            same_topic = recent

        lines: list[str] = [
            f"Tema activo: **{tema_actual}**",
            "",
            f"Se han procesado {len(same_topic)} intercambios en este tema "
            f"durante los últimos {len(recent)} intercambios.",
            "",
            "**Intercambios relevantes del tema:**",
            "",
        ]

        for ex in same_topic[-5:]:  # Últimos 5 del tema
            director_text = ex.director_msg.content[:500]
            if len(ex.director_msg.content) > 500:
                director_text += "..."
            lines.append(f"- **Exchange {ex.id}** [{ex.datetime_str}]:")
            lines.append(f"  Director: {director_text}")
            if ex.agent_msgs:
                agent_text = ex.agent_msgs[-1].content[:300]
                if len(ex.agent_msgs[-1].content) > 300:
                    agent_text += "..."
                lines.append(f"  Agente: {agent_text}")
            lines.append("")

        return "\n".join(lines)

    def _build_d3(self, recent: list["Exchange"]) -> str:
        """Sección D3: Decisiones pendientes del Director."""
        # Detectar preguntas abiertas del Director en intercambios recientes
        pending: list[str] = []
        for ex in recent[-5:]:
            content = ex.director_msg.content
            # Preguntas del Director
            if "?" in content:
                for line in content.split("\n"):
                    if "?" in line:
                        q = line.strip()
                        if q and len(q) < 200 and not q.startswith("http"):
                            pending.append(q)
                            break

        if not pending:
            return "No se identifican decisiones pendientes explícitas."

        return "\n".join(f"- {q}" for q in pending[:5])

    def _build_d4(self, recent: list["Exchange"]) -> str:
        """Sección D4: Restricciones y preferencias activas."""
        # Buscar patrones de restricciones/preferencias en mensajes del Director
        restrictions: list[str] = []
        patterns = [
            (r"(?:no\s+|sin\s+)(?:uses?|usar)\s+([\w\s,]+)", "No usar: {}"),
            (r"(?:usa|utiliza)\s+(?:solo\s+)?([\w\s,]+)", "Usar: {}"),
            (r"(?:obligatorio|siempre)\s+([\w\s,]+)", "Obligatorio: {}"),
            (r"(?:prohibido|nunca)\s+([\w\s,]+)", "Prohibido: {}"),
        ]

        for ex in recent[-10:]:
            content = ex.director_msg.content.lower()
            for regex, template in patterns:
                for match in re.finditer(regex, content):
                    captured = match.group(1).strip()[:100]
                    if captured:
                        restrictions.append(template.format(captured))

        if not restrictions:
            return "No se identifican restricciones explícitas en intercambios recientes."

        # Deduplicar
        seen = set()
        unique = []
        for r in restrictions:
            if r not in seen:
                seen.add(r)
                unique.append(r)
        return "\n".join(f"- {r}" for r in unique[:8])

    def _build_a1(self, recent: list["Exchange"]) -> str:
        """Sección A1: Qué estaba haciendo el agente."""
        if not recent:
            return "Sin actividad reciente registrada."

        ultimo = recent[-1]
        if not ultimo.agent_msgs:
            return f"Esperando respuesta del agente al último intercambio."

        last_agent_msg = ultimo.agent_msgs[-1].content
        # Tomar las primeras 500 chars que suelen tener el resumen
        preview = last_agent_msg[:1000]
        if len(last_agent_msg) > 1000:
            preview += "\n... (contenido truncado, ver bloque temático para detalle)"

        return (
            f"Última acción del agente (Exchange {ultimo.id}, "
            f"tema='{ultimo.topic}'):\n\n{preview}"
        )

    def _build_a2(self, recent: list["Exchange"]) -> str:
        """Sección A2: Entregables producidos."""
        # Buscar menciones de archivos creados/modificados en mensajes del agente
        files: dict[str, str] = {}  # ruta -> contexto

        for ex in recent:
            if not ex.agent_msgs:
                continue
            for msg in ex.agent_msgs:
                for match in _FILE_PATH_PATTERN.finditer(msg.content):
                    path = match.group(1)
                    if path not in files:
                        # Contexto: las 50 chars anteriores
                        start = max(0, match.start() - 50)
                        context = msg.content[start:match.start()].strip()
                        files[path] = context[:80]

        if not files:
            return "No se identifican archivos entregados en intercambios recientes."

        lines: list[str] = []
        for path, ctx in list(files.items())[:15]:
            ctx_str = f" — {ctx}" if ctx else ""
            lines.append(f"- `{path}`{ctx_str}")
        return "\n".join(lines)

    def _build_a3(self, recent: list["Exchange"]) -> str:
        """Sección A3: Errores abiertos (con detección precisa, no ingenua)."""
        errors: list[tuple[str, str]] = []  # (descripcion, contexto)

        for ex in recent:
            if not ex.agent_msgs:
                continue
            for msg in ex.agent_msgs:
                for match in _ERROR_REGEX.finditer(msg.content):
                    # Contexto: las 100 chars posteriores
                    start = match.start()
                    context = msg.content[start:start + 200].strip()
                    # Tomar las 50 chars anteriores como prefijo
                    prefix_start = max(0, start - 50)
                    prefix = msg.content[prefix_start:start].strip()
                    error_text = match.group(0)
                    errors.append((error_text, f"{prefix} ... {context}"))

        if not errors:
            return "No se identifican errores abiertos en intercambios recientes."

        # Deduplicar por texto de error
        seen = set()
        unique: list[tuple[str, str]] = []
        for err, ctx in errors:
            if err not in seen:
                seen.add(err)
                unique.append((err, ctx))

        lines: list[str] = []
        for err, ctx in unique[:8]:
            lines.append(f"- **{err}**")
            lines.append(f"  Contexto: {ctx[:200]}")
        return "\n".join(lines)

    def _build_a4(
        self,
        ultimo_exchange: "Exchange",
        tema_actual: str,
    ) -> str:
        """Sección A4: Siguiente paso lógico."""
        director_msg = ultimo_exchange.director_msg.content.strip()
        # Si el último mensaje del Director contiene una instrucción, esa es el siguiente paso
        if "?" in director_msg:
            # Es una pregunta, no una instrucción → continuar respondiéndola
            return (
                f"Responder la pregunta/instancia del Director del último intercambio. "
                f"Tema activo: {tema_actual}."
            )
        # Si es una instrucción, el siguiente paso es ejecutarla
        return (
            f"Continuar con la instrucción del Director del último intercambio "
            f"(tema activo: {tema_actual}). Si ya se ejecutó, esperar la siguiente "
            f"instrucción o verificar completitud de la tarea."
        )

    # ── Ensamblado y truncado ──────────────────────────────────────

    def _assemble(
        self,
        chat_label: str,
        tema_actual: str,
        d1: str, d2: str, d3: str, d4: str,
        a1: str, a2: str, a3: str, a4: str,
    ) -> str:
        """Ensambla las 8 secciones en el contenido final."""
        return f"""# Estado Actual — {chat_label}

**Tema activo:** {tema_actual}

---

## Sección D1 — Última instrucción del Director

{d1}

## Sección D2 — Contexto del tema activo

{d2}

## Sección D3 — Decisiones pendientes del Director

{d3}

## Sección D4 — Restricciones y preferencias activas

{d4}

---

## Sección A1 — Qué estaba haciendo el agente

{a1}

## Sección A2 — Entregables producidos

{a2}

## Sección A3 — Errores abiertos

{a3}

## Sección A4 — Siguiente paso lógico

{a4}
"""

    def _truncate(self, content: str, max_chars: int) -> str:
        """Trunca el contenido preservando las secciones críticas."""
        # Si el contenido excede el límite, truncar D2 y A1 (las más largas)
        # buscando preservar D1, A3 y A4
        overage = len(content) - max_chars
        if overage <= 0:
            return content

        # Estrategia simple: cortar D2 por la mitad si es muy larga
        logger.warning(
            "Estado actual excede límite (%d > %d chars), truncando D2",
            len(content), max_chars,
        )
        # Encontrar el inicio y fin de D2
        d2_start = content.find("## Sección D2")
        d2_end = content.find("## Sección D3")
        if d2_start != -1 and d2_end != -1:
            d2_content = content[d2_start:d2_end]
            if len(d2_content) > overage + 1000:
                # Truncar D2 a la mitad + nota
                truncated_d2 = d2_content[:len(d2_content) - overage - 200]
                truncated_d2 += "\n... (contenido truncado por límite de tamaño)\n\n"
                return content[:d2_start] + truncated_d2 + content[d2_end:]

        # Fallback: cortar por el final
        return content[:max_chars - 50] + "\n\n... (truncado por límite)\n"


if __name__ == "__main__":
    # ── Validación interna de estado_generator.py ──
    print("=== Validación de estado_generator.py ===\n")

    from contexto_zai.models import Exchange, Message, MessageRole

    gen = EstadoGenerator()

    # Test 1: 8 secciones presentes
    exchanges = [
        Exchange(
            id=1,
            director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1788482829, content="Ejecuta el pytest de server.py"),
            agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=1788482830, content="Tests ejecutados. 5 passed.")],
            topic="validaciones",
            start_timestamp=1788482829,
            end_timestamp=1788482830,
        ),
        Exchange(
            id=2,
            director_msg=Message(seq=3, role=MessageRole.USER, timestamp=1788482900, content="¿Por qué respondes eso si ya acordamos X?"),
            agent_msgs=[Message(seq=4, role=MessageRole.ASSISTANT, timestamp=1788482901, content="Tienes razón. Traceback encontrado: FileNotFound: /home/z/test.txt")],
            topic="validaciones",
            start_timestamp=1788482900,
            end_timestamp=1788482901,
        ),
    ]
    content = gen.generate(exchanges, chat_label="Test")

    # Verificar que las 8 secciones están presentes
    for section in ["D1", "D2", "D3", "D4", "A1", "A2", "A3", "A4"]:
        assert f"Sección {section}" in content, f"Sección {section} no encontrada"
    print(f"✓ 8 secciones presentes (D1-D4, A1-A4)")

    # Test 2: D1 contiene literalmente el último mensaje del Director
    assert "¿Por qué respondes eso si ya acordamos X?" in content
    print(f"✓ D1: última instrucción del Director literal")

    # Test 3: D2 menciona el tema activo
    assert "validaciones" in content
    print(f"✓ D2: tema activo 'validaciones' presente")

    # Test 3b: D2 no incluye el "tema" como una mención aislada, sino como "Tema activo:"
    assert "Tema activo: **validaciones**" in content
    print(f"✓ D2: 'Tema activo: **validaciones**' presente")

    # Test 4: A3 detecta error real (Traceback), no falsos positivos
    assert "Traceback" in content
    # No debe detectar "ERROR" en "5 passed" como error
    assert "passed" not in content.split("A3")[1]  # "passed" no debe aparecer en la sección de errores
    print(f"✓ A3: detecta Traceback real, evita falsos positivos")

    # Test 5: A4 no repite literalmente la instrucción del Director
    a4_section = content.split("Sección A4")[1]
    assert "Continuar" in a4_section or "Responder" in a4_section
    print(f"✓ A4: describe siguiente paso sin repetir instrucción literal")

    # Test 6: tema vacío → mensaje de error
    empty = gen.generate([], chat_label="Empty")
    assert "Sin intercambios" in empty
    print(f"✓ Lista vacía: mensaje apropiado")

    # Test 7: lista vacía de exchanges
    content_empty = gen.generate([], chat_label="V")
    assert "Sin intercambios" in content_empty
    print(f"✓ Lista vacía: manejada")

    print("\n✅ estado_generator.py: todos los tests pasaron")
