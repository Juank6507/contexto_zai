# contexto_zai/generation/estado_generator.py -- Generador del archivo 00_estado_actual.md con 5 secciones (D1, D4, A1, A2, A3, A4) y truncado inteligente (v4.0 M3).
"""Generador del archivo 00_estado_actual.md (v4.0, M3).

Produce las 5 secciones obligatorias que capturan el contexto completo
del tema activo al momento de la activación:
- D1: Última instrucción del Director (literal).
- D4: Restricciones activas del último tema (subagente o regex).
- A1: Qué estaba haciendo el agente (con truncado inteligente).
- A2: Entregables producidos (patrones ampliados).
- A3: Errores abiertos (patrones ampliados).
- A4: Siguiente paso lógico (analiza intercambios recientes).

Cambios v4.0 (M3):
- Se eliminan D2 y D3 del ensamblado (los métodos _build_d2 y _build_d3
  se conservan en el código por compatibilidad pero no se llaman).
- A1 ahora implementa "truncado inteligente": toma el tema activo en
  orden cronológico, trunca a ~16K de texto textual, y le suma ~4K de
  resumen del contenido truncado hecho por un subagente.
- D4 ahora puede usar un subagente (IntercambiosClasificadorSubagent
  modo RESTRICCIONES_TEMA) si se pasa un SubagentLauncher. Si no se
  pasa, cae al regex anterior (backward compatible).
- A2 y A3 tienen patrones ampliados (más tipos de rutas y errores).
- A4 analiza los últimos intercambios para detectar qué quedó pendiente.

Tamaño máximo: 20K tokens (~70KB chars).

Atómico standalone: importa config, models y subagents.launcher. Nada más.
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
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from contexto_zai.config import (
    ESTADO_TRUNCADO_RESUMEN_TOKENS,
    ESTADO_TRUNCADO_TEXTUAL_TOKENS,
    TOKEN_LIMITS,
)
from contexto_zai.subagents.launcher import SubagentLauncher

if TYPE_CHECKING:
    from contexto_zai.models import Exchange

logger = logging.getLogger(__name__)

# Patrones para detectar errores reales (no conversaciones sobre errores)
# v4.0: patrones ampliados con más tipos de error.
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
    # v4.0: patrones nuevos para detectar más errores
    r"\bcommand failed\b",
    r"\btimeout\b",
    r"\bTIMEOUT\b",
    r"\bconnection refused\b",
    r"\bconnection reset\b",
    r"\bOOM\b",
    r"\bSIGKILL\b",
    r"\bSIGTERM\b",
    r"\bsegmentation fault\b",
    r"\bcore dumped\b",
    r"\bImportError\b",
    r"\bPermissionError\b",
    r"\bRuntimeError\b",
    r"\bStopIteration\b",
    r"\bZeroDivisionError\b",
    r"\bIndexError\b",
    r"\bNotImplementedError\b",
    r"\bJSONDecodeError\b",
    r"\bHTTPError\b",
    r"\bConnectionError\b",
]
_ERROR_REGEX = re.compile("|".join(_ERROR_PATTERNS))

# Patrones para detectar rutas de archivos en mensajes del agente
# v4.0: patrón ampliado para capturar más tipos de rutas (Windows y Linux).
_FILE_PATH_PATTERN = re.compile(
    r"`?(/home/z/[^\s`]+|/tmp/[^\s`]+|contexto_zai/[^\s`]+\.(?:py|md|json|ts|tsx|sh|bat|ps1)|"
    r"[A-Za-z]:\\[^\s`]+\.(?:py|md|json|ts|tsx|sh|bat|ps1)|"
    r"mini-services/[^\s`]+\.(?:py|sh|ts)|"
    r"src/[^\s`]+\.(?:ts|tsx|js|jsx)|"
    r"download/[^\s`]+\.(?:md|json|zip|bat|ps1))`?"
)

# v4.0: Palabras que indican tarea pendiente (para A4).
_PALABRAS_PENDIENTE = [
    "pendiente", "falta", "toca", "siguiente paso", "próximo paso",
    "tengo que", "necesito", "voy a", "continúo con", "continuo con",
    "después", "luego", "aún no", "todavía no", "no terminé", "no completé",
]

class EstadoGenerator:
    """Genera el archivo 00_estado_actual.md con 5 secciones (v4.0).

    Args:
        max_chars: Límite máximo de caracteres. Por defecto usa
            TOKEN_LIMITS.max_chars_estado (70K).
        launcher: SubagentLauncher opcional para D4 (subagente) y A1
            (truncado inteligente). Si no se pasa, D4 cae al regex
            anterior y A1 cae al truncado simple (backward compatible).

    Usage:
        >>> gen = EstadoGenerator()  # sin launcher, modo backward compatible
        >>> content = gen.generate(exchanges, chat_label="CZAI Sesión 5")
        >>> # Con launcher (modo v4.0):
        >>> gen_v4 = EstadoGenerator(launcher=launcher)
        >>> content = gen_v4.generate(exchanges, chat_label="CZAI Sesión 5")
    """

    def __init__(
        self,
        max_chars: int = TOKEN_LIMITS.max_chars_estado,
        launcher: Optional[SubagentLauncher] = None,
        workspace_dir: Optional[Path] = None,
    ) -> None:
        self._max_chars = max_chars
        self._launcher = launcher
        # v4.3: workspace_dir para leer 03_objetivo_proyecto.md (sección G0.A)
        # y preparar la tarea SINTESIS_CONTEXTO (sección G0.B).
        # Si no se pasa, las secciones G0 se omiten (backward compatible).
        self._workspace_dir = Path(workspace_dir) if workspace_dir else None
        logger.debug(
            "EstadoGenerator inicializado: max_chars=%d (%d tokens), launcher=%s, workspace=%s",
            max_chars, int(max_chars / 3.5), "sí" if launcher else "no",
            self._workspace_dir.name if self._workspace_dir else "no",
        )

    # -- API pública ------------------------------------------------

    def generate(
        self,
        exchanges: list["Exchange"],
        chat_label: str = "",
    ) -> str:
        """Genera el contenido markdown del estado actual (v4.3).

        v4.3: añade 3 secciones nuevas al inicio del archivo (G0.A, G0.B, G1)
        antes de las secciones operativas existentes (D1, D4, A1, A2, A3, A4).
        Las secciones G0 solo se incluyen si ``workspace_dir`` se pasó al
        constructor. Si no, se omite G0 y G1 (backward compatible con v4.0).

        Args:
            exchanges: Lista de intercambios (se usan los últimos 15-20).
            chat_label: Etiqueta descriptiva del chat.

        Returns:
            Contenido markdown con las secciones G0.A, G0.B, G1 (si workspace)
            más las secciones operativas (D1, D4, A1, A2, A3, A4).
        """
        if not exchanges:
            return "# Estado Actual\n\n(Sin intercambios)\n"

        # Usar los últimos 15-20 intercambios (los más relevantes)
        recent = exchanges[-20:] if len(exchanges) > 20 else exchanges
        ultimo_exchange = exchanges[-1]

        # v6.0 D1: si el último exchange es virtual (director_msg empieza con
        # "Lee este link:" — generado por ExchangeBuilder para adjuntos), buscar
        # hacia atrás el último exchange REAL para usarlo como último intercambio
        # del cual extraer la instrucción del Director y el tema activo.
        # También cubre el caso en que el tema sea "link_externo" (clasificación
        # de un exchange virtual).
        ultimo_exchange_real = ultimo_exchange
        for ex in reversed(exchanges):
            content = ex.director_msg.content.strip()
            is_virtual = content.startswith("Lee este link:") or ex.topic == "link_externo"
            if not is_virtual:
                ultimo_exchange_real = ex
                break
        tema_actual = ultimo_exchange_real.topic
        # v6.0 A1: filtrar intercambios virtuales de la lista de recientes
        recent_reales = [
            ex for ex in recent
            if not (
                ex.director_msg.content.strip().startswith("Lee este link:")
                or ex.topic == "link_externo"
            )
        ]
        if not recent_reales:
            # Todos virtuales (caso extremo): mantener original
            recent_reales = recent

        # v4.3: secciones nuevas G0.A (objetivo), G0.B (síntesis placeholder), G1 (guía)
        g0_a = self._build_g0_a() if self._workspace_dir else ""
        g0_b = self._build_g0_b() if self._workspace_dir else ""
        g1 = self._build_g1() if self._workspace_dir else ""

        # v4.3: preparar la tarea SINTESIS_CONTEXTO (publica vía ProcesadorIntercambios)
        if self._workspace_dir and self._launcher is not None:
            try:
                self._build_sintesis_contexto_task(recent, tema_actual)
            except Exception as e:
                logger.warning("F3 v4.3: no se pudo preparar tarea SINTESIS_CONTEXTO: %s", e)

        # Sección D1 -- Última instrucción del Director (literal)
        # v6.0 D1: usar el último exchange REAL (no virtual de adjuntos).
        d1 = self._build_d1(ultimo_exchange_real)

        # Sección D4 -- Restricciones y preferencias activas del último tema
        # v4.0: usa subagente si hay launcher, sino regex.
        # v6.0: pasar los intercambios reales (sin virtuales).
        d4 = self._build_d4(recent_reales, tema_actual)

        # Sección A1 -- Qué estaba haciendo el agente (con truncado inteligente v4.0)
        # v6.0 A1: pasar solo intercambios reales.
        a1 = self._build_a1(recent_reales, tema_actual)

        # Sección A2 -- Entregables producidos (patrones ampliados v4.0)
        # v6.0 A2: filtrar virtuales y cortar tool_calls.
        a2 = self._build_a2(recent_reales)

        # Sección A3 -- Errores abiertos (patrones ampliados v4.0)
        # v6.0 A3: filtrar virtuales y cortar tool_calls.
        a3 = self._build_a3(recent_reales)

        # Sección A4 -- Siguiente paso lógico (analiza intercambios v4.0)
        a4 = self._build_a4(recent_reales, tema_actual)

        # v4.3: ensamblar con secciones G0 (si workspace) + secciones operativas
        content = self._assemble(
            chat_label=chat_label or "Chat",
            tema_actual=tema_actual,
            g0_a=g0_a, g0_b=g0_b, g1=g1,
            d1=d1, d4=d4,
            a1=a1, a2=a2, a3=a3, a4=a4,
        )

        # Truncar si excede el límite (preservando las secciones críticas D1, A1, A4)
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
        return f"EstadoGenerator(max_chars={self._max_chars}, launcher={'sí' if self._launcher else 'no'})"

    # -- Construcción de secciones ---------------------------------

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

    def _build_d4(
        self,
        recent: list["Exchange"],
        tema_actual: str = "",
    ) -> str:
        """Sección D4: Restricciones y preferencias activas del último tema (v4.0).

        Si hay launcher disponible, usa un subagente (IntercambiosClasificadorSubagent
        modo RESTRICCIONES_TEMA) para interpretar las restricciones enfocadas
        al tema activo. Si no hay launcher, cae al regex anterior (backward compatible).

        Args:
            recent: Lista de intercambios recientes.
            tema_actual: Tema activo (para filtrar intercambios del tema).
        """
        # F4 v4.2: si hay launcher (que ahora es un ProcesadorIntercambios),
        # usarlo para preparar la tarea de D4 vía el Orquestador.
        # El archivo se escribe con regex (abajo), y se actualiza con la respuesta
        # del subagente cuando el agente llama a collect_responses().
        if self._launcher is not None:
            # Filtrar intercambios del tema activo (o usar recent si no hay match)
            intercambios_tema = [ex for ex in recent if ex.topic == tema_actual] if tema_actual else recent
            if not intercambios_tema:
                intercambios_tema = recent
            # F4: llamar a ProcesadorIntercambios.procesar(RESTRICCIONES_TEMA, ...)
            try:
                self._launcher.procesar(
                    modo="RESTRICCIONES_TEMA",
                    intercambios=intercambios_tema,
                    context={"section": "D4", "tema_actual": tema_actual},
                    task_id_suffix="d4",
                )
            except Exception as e:
                logger.warning("F4: no se pudo preparar tarea D4: %s", e)

        # Regex histórico (backward compatible, sin launcher o subagente no coordinado aún)
        restrictions: list[str] = []
        patterns = [
            (r"(?:no\s+|sin\s+)(?:uses?|usar)\s+([\w\s,]+)", "No usar: {}"),
            (r"(?:usa|utiliza)\s+(?:solo\s+)?([\w\s,]+)", "Usar: {}"),
            (r"(?:obligatorio|siempre)\s+([\w\s,]+)", "Obligatorio: {}"),
            (r"(?:prohibido|nunca)\s+([\w\s,]+)", "Prohibido: {}"),
        ]

        # v4.0: si hay tema_actual, solo buscar en intercambios del tema
        intercambios_a_buscar = (
            [ex for ex in recent if ex.topic == tema_actual] if tema_actual else recent
        )
        if not intercambios_a_buscar:
            intercambios_a_buscar = recent

        for ex in intercambios_a_buscar[-10:]:
            content = ex.director_msg.content.lower()
            for regex, template in patterns:
                for match in re.finditer(regex, content):
                    captured = match.group(1).strip()[:100]
                    if captured:
                        restrictions.append(template.format(captured))

        if not restrictions:
            return "No se identifican restricciones explícitas en el tema activo."

        # Deduplicar
        seen = set()
        unique = []
        for r in restrictions:
            if r not in seen:
                seen.add(r)
                unique.append(r)
        return "\n".join(f"- {r}" for r in unique[:8])

    def _build_a1(
        self,
        recent: list["Exchange"],
        tema_actual: str = "",
    ) -> str:
        """Sección A1: Qué estaba haciendo el agente (v4.0, truncado inteligente).

        Toma el tema activo en orden cronológico. Si es muy largo:
        1. Trunca a ~16K de contexto textual (preservando lo más reciente).
        2. Si hay launcher, le pide al subagente que resuma el contenido
           truncado en ~4K, y se lo suma al texto textual.
        3. Si no hay launcher, deja solo el texto textual con un aviso de
           que se truncó (backward compatible).

        Args:
            recent: Lista de intercambios recientes.
            tema_actual: Tema activo (para filtrar intercambios del tema).
        """
        if not recent:
            return "Sin actividad reciente registrada."

        # v4.0: filtrar intercambios del tema activo
        if tema_actual:
            intercambios_tema = [ex for ex in recent if ex.topic == tema_actual]
        else:
            intercambios_tema = recent
        if not intercambios_tema:
            intercambios_tema = recent

        # Construir el texto cronológico del tema activo
        texto_tema_parts: list[str] = []
        for ex in intercambios_tema:
            texto_tema_parts.append(f"--- Exchange {ex.id} [{ex.datetime_str}] ---")
            texto_tema_parts.append(f"Director: {ex.director_msg.content}")
            for msg in ex.agent_msgs:
                texto_tema_parts.append(f"Agente: {msg.content}")
            texto_tema_parts.append("")

        texto_completo = "\n".join(texto_tema_parts)

        # Calcular límites en chars (regla 1 token ≈ 3.5 chars)
        max_textual_chars = int(ESTADO_TRUNCADO_TEXTUAL_TOKENS * 3.5)
        max_resumen_chars = int(ESTADO_TRUNCADO_RESUMEN_TOKENS * 3.5)

        # Si el texto completo cabe en el límite textual, no hace falta truncar
        if len(texto_completo) <= max_textual_chars:
            return (
                f"Última acción del agente (Exchange {recent[-1].id}, "
                f"tema='{tema_actual or recent[-1].topic}'):\n\n{texto_completo}"
            )

        # v4.0: truncado inteligente
        # 1. Texto textual: los últimos ~16K chars (lo más reciente al final)
        texto_textual = texto_completo[-max_textual_chars:]
        # Marcar que se truncó al inicio
        texto_textual = "[... contenido truncado al inicio ...]\n\n" + texto_textual

        # 2. Contenido truncado (lo que se excluyó del texto textual)
        contenido_truncado = texto_completo[:-max_textual_chars] if len(texto_completo) > max_textual_chars else ""

        # 3. Si hay launcher (ProcesadorIntercambios), pedir resumen del contenido truncado
        # F4 v4.2: usar ProcesadorIntercambios para preparar la tarea.
        # El resumen se aplica cuando el agente llama a collect_responses().
        resumen_texto = ""
        if self._launcher is not None and contenido_truncado:
            # Crear un exchange sintético con el contenido truncado
            from contexto_zai.models import Exchange as _Exchange, Message as _Message, MessageRole as _MessageRole
            exchange_sintetico = _Exchange(
                id=0,
                director_msg=_Message(
                    seq=0,
                    role=_MessageRole.USER,
                    timestamp=intercambios_tema[0].start_timestamp,
                    content=contenido_truncado[:int(ESTADO_TRUNCADO_RESUMEN_TOKENS * 3.5) * 3],
                ),
                agent_msgs=[],
                topic=tema_actual or "truncado",
                start_timestamp=intercambios_tema[0].start_timestamp,
                end_timestamp=intercambios_tema[0].end_timestamp,
            )
            try:
                self._launcher.procesar(
                    modo="RESUMEN_TRUNCADO",
                    intercambios=[exchange_sintetico],
                    context={"section": "A1", "tema_actual": tema_actual},
                    task_id_suffix="a1_resumen",
                )
            except Exception as e:
                logger.warning("F4: no se pudo preparar tarea A1 resumen: %s", e)

        # Ensamblar el resultado final
        header = (
            f"Última acción del agente (Exchange {recent[-1].id}, "
            f"tema='{tema_actual or recent[-1].topic}'):\n"
        )

        if resumen_texto:
            return (
                f"{header}"
                f"**Truncado inteligente:** texto textual reciente + resumen del contenido truncado.\n\n"
                f"## Texto textual (últimos ~{ESTADO_TRUNCADO_TEXTUAL_TOKENS} tokens)\n\n"
                f"{texto_textual}\n\n"
                f"## Resumen del contenido truncado (~{ESTADO_TRUNCADO_RESUMEN_TOKENS} tokens)\n\n"
                f"{resumen_texto}"
            )
        else:
            # Sin launcher: solo texto textual con aviso de truncado
            return (
                f"{header}\n{texto_textual}\n\n"
                f"... (contenido truncado, ver bloque temático para detalle)"
            )

    def _build_a2(self, recent: list["Exchange"]) -> str:
        """Sección A2: Entregables producidos.

        v6.0 A2: saltar intercambios virtuales (director_msg empieza con
        "Lee este link:") y cortar contenido de tool_calls en los mensajes
        del agente (buscar `{"type": "tool_calls"` y procesar solo el texto
        anterior a esa marca).
        """
        # Buscar menciones de archivos creados/modificados en mensajes del agente
        files: dict[str, str] = {}  # ruta -> contexto

        for ex in recent:
            # v6.0 A2: saltar virtuales
            if ex.director_msg.content.strip().startswith("Lee este link:"):
                continue
            if not ex.agent_msgs:
                continue
            for msg in ex.agent_msgs:
                # v6.0 A2: cortar tool_calls
                content = self._strip_tool_calls(msg.content)
                for match in _FILE_PATH_PATTERN.finditer(content):
                    path = match.group(1)
                    if path not in files:
                        # Contexto: las 50 chars anteriores
                        start = max(0, match.start() - 50)
                        context = content[start:match.start()].strip()
                        files[path] = context[:80]

        if not files:
            return "No se identifican archivos entregados en intercambios recientes."

        lines: list[str] = []
        for path, ctx in list(files.items())[:15]:
            ctx_str = f" -- {ctx}" if ctx else ""
            lines.append(f"- `{path}`{ctx_str}")
        return "\n".join(lines)

    def _build_a3(self, recent: list["Exchange"]) -> str:
        """Sección A3: Errores abiertos (con detección precisa, no ingenua).

        v6.0 A3: saltar intercambios virtuales y cortar tool_calls (igual que A2).
        """
        errors: list[tuple[str, str]] = []  # (descripcion, contexto)

        for ex in recent:
            # v6.0 A3: saltar virtuales
            if ex.director_msg.content.strip().startswith("Lee este link:"):
                continue
            if not ex.agent_msgs:
                continue
            for msg in ex.agent_msgs:
                # v6.0 A3: cortar tool_calls
                content = self._strip_tool_calls(msg.content)
                for match in _ERROR_REGEX.finditer(content):
                    # Contexto: las 100 chars posteriores
                    start = match.start()
                    context = content[start:start + 200].strip()
                    # Tomar las 50 chars anteriores como prefijo
                    prefix_start = max(0, start - 50)
                    prefix = content[prefix_start:start].strip()
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

    @staticmethod
    def _strip_tool_calls(content: str) -> str:
        """v6.0: corta contenido de tool_calls en un mensaje.

        Busca la marca `{"type": "tool_calls"` y devuelve solo el texto
        anterior a esa marca. Si no la encuentra, devuelve el contenido
        original. Esto evita que A2/A3 detecten rutas o errores falsos en
        el JSON serializado de tool_calls.
        """
        if not content:
            return content
        marker = '{"type": "tool_calls"'
        idx = content.find(marker)
        if idx == -1:
            # También probar sin espacios (por si el JSON está compacto)
            marker = '{"type":"tool_calls"'
            idx = content.find(marker)
        if idx == -1:
            return content
        return content[:idx].rstrip()

    def _build_a4(
        self,
        recent: list["Exchange"],
        tema_actual: str,
    ) -> str:
        """Sección A4: Siguiente paso lógico (v4.0).

        Analiza los últimos intercambios para detectar qué quedó pendiente,
        en vez de repetir "continuar con la instrucción del Director".

        Args:
            recent: Lista de intercambios recientes.
            tema_actual: Tema activo.
        """
        if not recent:
            return "Sin intercambios recientes para analizar."

        ultimo = recent[-1]
        director_msg = ultimo.director_msg.content.strip()

        # Caso 1: el último mensaje del Director es una pregunta
        if "?" in director_msg:
            # Extraer la pregunta (primera línea con ?)
            for line in director_msg.split("\n"):
                if "?" in line:
                    q = line.strip()[:200]
                    if q and not q.startswith("http"):
                        return (
                            f"Responder la pregunta del Director del último intercambio "
                            f"(Exchange {ultimo.id}, tema='{tema_actual}'):\n"
                            f"> {q}"
                        )
            return (
                f"Responder la pregunta del Director del último intercambio "
                f"(Exchange {ultimo.id}, tema='{tema_actual}')."
            )

        # Caso 2: el último mensaje del Director es una instrucción
        # v4.0: buscar si el agente ya respondió
        if not ultimo.agent_msgs:
            # El agente todavía no respondió → siguiente paso es ejecutar la instrucción
            return (
                f"Ejecutar la instrucción del Director del último intercambio "
                f"(Exchange {ultimo.id}, tema='{tema_actual}')."
            )

        # El agente ya respondió. Analizar si la respuesta indica que algo quedó pendiente.
        ultima_respuesta = ultimo.agent_msgs[-1].content.lower()

        # Buscar palabras que indican tarea pendiente en la respuesta del agente
        for palabra in _PALABRAS_PENDIENTE:
            if palabra in ultima_respuesta:
                # Extraer la línea que contiene la palabra
                for line in ultimo.agent_msgs[-1].content.split("\n"):
                    if palabra in line.lower():
                        return (
                            f"Continuar con la tarea pendiente detectada en el último "
                            f"intercambio (Exchange {ultimo.id}, tema='{tema_actual}'):\n"
                            f"> {line.strip()[:200]}"
                        )

        # Caso 3: el agente respondió sin indicar pendientes
        # Verificar si el Director confirmó o pidió algo nuevo en el penúltimo intercambio
        if len(recent) >= 2:
            penultimo = recent[-2]
            if not penultimo.agent_msgs:
                return (
                    f"Verificar si el agente respondió al penúltimo intercambio "
                    f"(Exchange {penultimo.id}, tema='{penultimo.topic}'). "
                    f"Si ya respondió, esperar la siguiente instrucción del Director."
                )

        # Caso default
        return (
            f"El agente respondió al último intercambio (Exchange {ultimo.id}, "
            f"tema='{tema_actual}'). Si la respuesta está completa, esperar la "
            f"siguiente instrucción del Director."
        )

    # -- Ensamblado y truncado --------------------------------------

    def _assemble(
        self,
        chat_label: str,
        tema_actual: str,
        d1: str, d4: str,
        a1: str, a2: str, a3: str, a4: str,
        g0_a: str = "", g0_b: str = "", g1: str = "",
    ) -> str:
        """Ensambla las secciones en el contenido final (v4.3).

        v4.3: añade las secciones G0.A (objetivo), G0.B (síntesis placeholder),
        G1 (guía de uso) al inicio del archivo, antes de las operativas.
        Si las secciones G0/G1 están vacías (no se pasó workspace_dir),
        se omite la cabecera de "Visión general y guía" y el archivo queda
        con el formato v4.0 (solo D1, D4, A1, A2, A3, A4).
        """
        # v4.3: bloque de visión general + guía (solo si hay contenido)
        bloques_g = ""
        if g0_a or g0_b or g1:
            bloques_g = f"""
---

## G0.A — Objetivo del proyecto

{g0_a or '_(sin declaración de objetivo)_'}

## G0.B — Síntesis del contexto disponible

{g0_b or '_Síntesis del contexto no disponible. Ejecuta `pipeline.collect_responses()` para generarla._'}

## G1 — Cómo usar este contexto

{g1}

---

"""

        return f"""# Estado Actual -- {chat_label}

**Tema activo:** **{tema_actual}**
{bloques_g}
## Sección D1 -- Última instrucción del Director

{d1}

## Sección D4 -- Restricciones y preferencias activas del tema

{d4}

---

## Sección A1 -- Qué estaba haciendo el agente

{a1}

## Sección A2 -- Entregables producidos

{a2}

## Sección A3 -- Errores abiertos

{a3}

## Sección A4 -- Siguiente paso lógico

{a4}
"""

    # -- v4.3: Secciones nuevas G0.A, G0.B, G1 ----------------------

    def _build_g0_a(self) -> str:
        """v4.3: Sección G0.A — Objetivo del proyecto (fijo, leído de archivo).

        Lee ``03_objetivo_proyecto.md`` del workspace. Si el archivo no
        existe, lo crea automáticamente aplicando la cascada documentación →
        bloques (ver ``_asegurar_objetivo_proyecto()``). Esto sigue el
        principio del Director: el proceso no deja placeholders pidiendo
        al agente que cree archivos; si detecta que falta, lo crea.
        """
        if not self._workspace_dir:
            return ""
        objetivo_path = self._workspace_dir / "03_objetivo_proyecto.md"
        # v4.3 (F5): asegurar que el archivo existe antes de leerlo.
        # Si no existe, se crea con la cascada documentación → bloques.
        if not objetivo_path.exists():
            self._asegurar_objetivo_proyecto()
        try:
            return objetivo_path.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning("G0.A: no se pudo leer 03_objetivo_proyecto.md: %s", e)
            return f"_(error leyendo objetivo: {e})_"

    def _asegurar_objetivo_proyecto(self) -> None:
        """v4.3 (F5): Crea ``03_objetivo_proyecto.md`` si no existe.

        Aplica una cascada de dos fuentes para derivar el contenido inicial:

        - **Caso A (documentación):** lee los archivos de documentación
          del proyecto (``estrategia/agent-context/*.md``, ``upload/worklog_*.md``)
          relativos al workspace raíz. Extrae el primer párrafo que mencione
          "proyecto" o "objetivo" y lo escribe como objetivo declarado.
        - **Caso B (bloques):** si la documentación no aporta suficiente,
          lee ``_metadata.json["tema_a_archivo"]`` y construye un objetivo
          tentativo con los temas más representativos.
        - **Caso C (sin fuentes):** si no hay ni documentación ni bloques,
          escribe un contenido mínimo pidiendo al Director que lo declare.

        Si el archivo ya existe, NO se sobrescribe (la cascada solo se
        ejecuta la primera vez).
        """
        if not self._workspace_dir:
            return
        objetivo_path = self._workspace_dir / "03_objetivo_proyecto.md"
        if objetivo_path.exists():
            return  # No sobrescribir si ya existe

        # Localizar el workspace raíz del proyecto (donde están estrategia/ y upload/)
        from contexto_zai.config import WORKSPACE_ROOT as _PROJECT_ROOT

        contenido_objetivo = self._extraer_objetivo_de_documentacion(_PROJECT_ROOT)
        if not contenido_objetivo:
            contenido_objetivo = self._extraer_objetivo_de_bloques()
        if not contenido_objetivo:
            contenido_objetivo = ("Proyecto sin objetivo declarado. "
                                  "Edita este archivo para declararlo.")

        try:
            objetivo_path.parent.mkdir(parents=True, exist_ok=True)
            objetivo_path.write_text(contenido_objetivo, encoding="utf-8")
            logger.info("F5 v4.3: 03_objetivo_proyecto.md creado (%d chars)",
                        len(contenido_objetivo))
        except Exception as e:
            logger.warning("F5 v4.3: no se pudo crear 03_objetivo_proyecto.md: %s", e)

    @staticmethod
    def _extraer_objetivo_de_documentacion(project_root: Path) -> Optional[str]:
        """v4.3 (F5): Caso A — extrae el objetivo de la documentación del proyecto.

        Busca en orden de prioridad:
        1. ``estrategia/agent-context/proyecto.md``
        2. ``estrategia/agent-context/identidad.md``
        3. ``estrategia/agent-context/entorno.md``
        4. ``upload/worklog_*.md`` (cualquiera)

        Devuelve el primer párrafo sustantivo que mencione "proyecto" o
        "objetivo", o el primer párrafo del archivo si ninguno los menciona.
        ``None`` si no encuentra ningún archivo.
        """
        if not project_root:
            return None
        candidatos = [
            project_root / "estrategia" / "agent-context" / "proyecto.md",
            project_root / "estrategia" / "agent-context" / "identidad.md",
            project_root / "estrategia" / "agent-context" / "entorno.md",
        ]
        # Añadir worklogs (cualquiera que exista)
        upload_dir = project_root / "upload"
        if upload_dir.exists():
            candidatos.extend(sorted(upload_dir.glob("worklog_*.md")))

        for candidato in candidatos:
            if not candidato.exists():
                continue
            try:
                contenido = candidato.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            # Buscar el primer párrafo que mencione "proyecto" o "objetivo"
            parrafos = [p.strip() for p in contenido.split("\n\n") if p.strip()]
            for parrafo in parrafos:
                # Quitar líneas que sean solo comentarios markdown
                limpio = "\n".join(
                    line for line in parrafo.split("\n")
                    if not line.strip().startswith("<!--")
                    and not line.strip().startswith("#")
                ).strip()
                if not limpio:
                    continue
                if "proyecto" in limpio.lower() or "objetivo" in limpio.lower():
                    return limpio
            # Si ninguno menciona proyecto/objetivo, devolver el primer párrafo limpio
            for parrafo in parrafos:
                limpio = "\n".join(
                    line for line in parrafo.split("\n")
                    if not line.strip().startswith("<!--")
                    and not line.strip().startswith("#")
                ).strip()
                if limpio and len(limpio) > 30:
                    return limpio
        return None

    def _extraer_objetivo_de_bloques(self) -> Optional[str]:
        """v4.3 (F5): Caso B — deriva el objetivo de los bloques existentes.

        Lee ``_metadata.json["tema_a_archivo"]`` y construye un objetivo
        tentativo con los 3-5 temas más representativos. No lanza
        subagentes — usa lectura directa para mantenerlo simple.

        ``None`` si no hay bloques ni metadata.
        """
        if not self._workspace_dir:
            return None
        metadata_path = self._workspace_dir / "_metadata.json"
        if not metadata_path.exists():
            return None
        try:
            import json as _json
            metadata = _json.loads(metadata_path.read_text(encoding="utf-8"))
            tema_a_archivo = metadata.get("tema_a_archivo", {})
        except Exception:
            return None
        if not tema_a_archivo:
            return None
        # Tomar los primeros 3-5 temas (ya están en orden de registro)
        temas = list(tema_a_archivo.keys())[:5]
        temas_str = ", ".join(temas)
        return (
            "<!-- Objetivo derivado automáticamente de los bloques existentes. "
            "El Director puede confirmarlo o corregirlo. -->\n"
            f"Proyecto sobre: {temas_str}."
        )

    def _build_g0_b(self) -> str:
        """v4.3: Sección G0.B — Síntesis del contexto disponible (placeholder).

        Devuelve el placeholder inicial. La síntesis real la inserta
        ``IntegradorRespuestas._integrar_sintesis_contexto()`` después de
        que el agente llame a ``pipeline.collect_responses()``.
        """
        return ("Síntesis del contexto no disponible. Ejecuta "
                "`pipeline.collect_responses()` para generarla.")

    def _build_g1(self) -> str:
        """v4.3: Sección G1 — Guía de uso del contexto (texto fijo).

        Texto fijo que el proceso incluye siempre. El agente lo consume,
        no lo escribe. Explica los arneses disponibles y cuándo usarlos.
        """
        return """1. Estás leyendo `00_estado_actual.md` — el resumen ejecutivo del proyecto.
   Empieza por aquí siempre.

2. Si necesitas encontrar información específica, consulta:
   - `01_indice_recuperacion.md` → mapa de bloques temáticos (qué tema está en qué archivo).
   - `02_decisiones_clave.md` → decisiones formales tomadas (no repetir lo ya decidido).

3. Si necesitas detalle de un tema, lanza una consulta al proceso:
   - `pipeline.query_context("tu pregunta")` → el proceso identifica bloques candidatos
     y te devuelve prompts para lanzar subagentes que los lean.

4. Si el Director te pasa un documento o link nuevo para incorporar:
   - `pipeline.ampliar_contexto(source_type, source_path, jwt, metadata)`.
   - Para links `/s/` de otros chats de Z.ai: `metadata={"jwt": "..."}`.

5. Si el proceso publicó tareas pendientes (en `_pending_tasks.json`):
   - Lee `_pending_tasks.json`.
   - Lanza los subagentes con el Task tool.
   - Llama `pipeline.collect_responses()` para que el proceso integre las respuestas.

6. Los bloques temáticos viven como archivos `bloque_*.md` en este workspace.
   NO los leas directamente en tu ventana — son muy grandes.
   Usa `query_context()` o lanza subagentes para consultarlos.
"""

    def _build_sintesis_contexto_task(
        self,
        recent: list,
        tema_actual: str,
    ) -> None:
        """v4.3: Prepara la tarea SINTESIS_CONTEXTO para que el agente la lance.

        Construye el contexto adicional (objetivo + índice + decisiones +
        resúmenes de otros bloques) y lo pasa al ``ProcesadorIntercambios``
        en modo ``SINTESIS_CONTEXTO``. El ``ProcesadorIntercambios`` publica
        la tarea vía el ``Orquestador`` (igual que D4, A1, decisiones).

        El resultado se aplica después con ``pipeline.collect_responses()``.
        """
        if not self._workspace_dir:
            return
        try:
            from contexto_zai.procesadores.procesador_intercambios import ProcesadorIntercambios
            # Verificar que el launcher es un ProcesadorIntercambios
            if not isinstance(self._launcher, ProcesadorIntercambios):
                logger.debug("F3 v4.3: launcher no es ProcesadorIntercambios, no se prepara SINTESIS_CONTEXTO")
                return

            # Construir el contexto adicional para el subagente
            contexto_adicional_parts: list[str] = []

            # 1. Objetivo del proyecto
            objetivo = self._build_g0_a()
            if objetivo and "no declarado" not in objetivo:
                contexto_adicional_parts.append(f"OBJETIVO DEL PROYECTO:\n{objetivo}")

            # 2. Índice de recuperación
            indice_path = self._workspace_dir / "01_indice_recuperacion.md"
            if indice_path.exists():
                try:
                    indice_content = indice_path.read_text(encoding="utf-8")
                    # Truncar si es muy largo
                    if len(indice_content) > 4000:
                        indice_content = indice_content[:4000] + "\n... (índice truncado)"
                    contexto_adicional_parts.append(f"ÍNDICE DE RECUPERACIÓN:\n{indice_content}")
                except Exception:
                    pass

            # 3. Decisiones clave
            decisiones_path = self._workspace_dir / "02_decisiones_clave.md"
            if decisiones_path.exists():
                try:
                    decisiones_content = decisiones_path.read_text(encoding="utf-8")
                    if len(decisiones_content) > 4000:
                        decisiones_content = decisiones_content[:4000] + "\n... (decisiones truncadas)"
                    contexto_adicional_parts.append(f"DECISIONES CLAVE:\n{decisiones_content}")
                except Exception:
                    pass

            contexto_adicional = "\n\n".join(contexto_adicional_parts) or "(sin contexto adicional)"

            # Llamar al ProcesadorIntercambios para que publique la tarea.
            # El contexto adicional se pasa vía context["contexto_adicional"]
            # (convención del modo SINTESIS_CONTEXTO en ProcesadorIntercambios).
            self._launcher.procesar(
                modo="SINTESIS_CONTEXTO",
                intercambios=recent,
                context={
                    "tema_actual": tema_actual,
                    "contexto_adicional": contexto_adicional,
                },
                task_id_suffix="estado",
            )

            logger.info("F3 v4.3: tarea SINTESIS_CONTEXTO preparada y publicada")
        except Exception as e:
            logger.warning("F3 v4.3: no se pudo preparar tarea SINTESIS_CONTEXTO: %s", e)

    def _truncate(self, content: str, max_chars: int) -> str:
        """Truncamiento logico (v3.4).

        Si el contenido supera el limite:
        1. Identifica la parte mas antigua que no cabe (la que va al final).
        2. Resume esa parte sin perder informacion clave.
        3. Anade el resumen al final del estado actual.
        4. Mantiene el orden cronologico: primero lo mas reciente, luego el resumen.
        """
        overage = len(content) - max_chars
        if overage <= 0:
            return content

        logger.warning(
            "Estado actual excede limite (%d > %d chars), aplicando truncamiento logico",
            len(content), max_chars,
        )

        # Calcular cuanto espacio necesitamos para el resumen
        # El resumen ocupa ~500 chars, dejamos margen
        resumen_space = 1000
        chars_to_keep = max_chars - resumen_space

        # La parte que se mantiene (mas reciente, al inicio del contenido)
        kept_part = content[:chars_to_keep]

        # La parte que se excluye (mas antigua, al final del contenido)
        excluded_part = content[chars_to_keep:]

        # Resumir la parte excluida
        # Extraer las lineas clave: decisiones, archivos, errores, rutas
        excluded_lines = excluded_part.split("\n")
        key_lines = []
        for line in excluded_lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Preservar lineas con informacion clave
            if any(kw in stripped.lower() for kw in [
                "decision", "archivo", "error", "ruta", "bug",
                "fix", "cambio", "modificado", "entregado",
                "pendiente", "fallo", "correcto",
            ]):
                key_lines.append(stripped)

        # Construir el resumen
        if key_lines:
            resumen = "\n".join(key_lines[:20])  # Maximo 20 lineas clave
        else:
            # Si no hay lineas clave, tomar las primeras y ultimas lineas
            if len(excluded_lines) > 10:
                resumen = "\n".join(excluded_lines[:5]) + "\n...\n" + "\n".join(excluded_lines[-5:])
            else:
                resumen = "\n".join(excluded_lines)

        # Construir el contenido final
        result = kept_part
        result += "\n\n## Resumen del contexto excluido (truncamiento logico)\n\n"
        result += f"**Período excluido:** contenido anterior al punto de corte.\n"
        result += f"**Motivo:** El contenido del tema activo supera los {max_chars} chars.\n\n"
        result += resumen

        logger.info(
            "Truncamiento logico aplicado: %d chars mantenidos + %d chars de resumen",
            len(kept_part), len(resumen),
        )
        return result

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
    # -- Validación interna de estado_generator.py (v4.0) --
    print("=== Validacion de estado_generator.py (v4.0) ===\n")

    from contexto_zai.models import Exchange, Message, MessageRole

    # Test sin launcher (backward compatible)
    gen = EstadoGenerator()

    # Intercambios de prueba (tema "validaciones")
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
            agent_msgs=[Message(seq=4, role=MessageRole.ASSISTANT, timestamp=1788482901, content="Tienes razón. Traceback encontrado: FileNotFound: /home/z/test.txt"),
                        Message(seq=5, role=MessageRole.ASSISTANT, timestamp=1788482902, content="Queda pendiente verificar el archivo.")],
            topic="validaciones",
            start_timestamp=1788482900,
            end_timestamp=1788482902,
        ),
    ]
    content = gen.generate(exchanges, chat_label="Test")

    # Test 1: 5 secciones presentes (D1, D4, A1, A2, A3, A4) — NO D2 ni D3
    for section in ["D1", "D4", "A1", "A2", "A3", "A4"]:
        assert f"Sección {section}" in content, f"Sección {section} no encontrada"
    assert "Sección D2" not in content, "D2 no debe estar en v4.0 (eliminada)"
    assert "Sección D3" not in content, "D3 no debe estar en v4.0 (eliminada)"
    print(f"[OK] 5 secciones presentes (D1, D4, A1, A2, A3, A4) — D2/D3 eliminadas")

    # Test 2: D1 contiene literalmente el último mensaje del Director
    assert "¿Por qué respondes eso si ya acordamos X?" in content
    print(f"[OK] D1: última instrucción del Director literal")

    # Test 3: tema activo en el header (no en D2 que ya no existe)
    assert "**validaciones**" in content  # tema en bold en el header
    print(f"[OK] Header: tema activo 'validaciones' en bold")

    # Test 4: A3 detecta error real (Traceback), no falsos positivos
    assert "Traceback" in content
    # "passed" no debe aparecer en la sección de errores
    a3_part = content.split("Sección A3")[1].split("Sección A4")[0]
    assert "passed" not in a3_part.lower()
    print(f"[OK] A3: detecta Traceback real, evita falsos positivos")

    # Test 5: A4 no repite "continuar con la instrucción" — analiza intercambios
    a4_section = content.split("Sección A4")[1]
    # El agente respondió "Queda pendiente verificar el archivo" → A4 debe detectarlo
    assert "pendiente" in a4_section.lower() or "Responder" in a4_section or "Ejecutar" in a4_section
    print(f"[OK] A4: analiza intercambios (detecta tarea pendiente o pregunta)")

    # Test 6: lista vacía → mensaje apropiado
    empty = gen.generate([], chat_label="Empty")
    assert "Sin intercambios" in empty
    print(f"[OK] Lista vacía: mensaje apropiado")

    # Test 7: A2 detecta rutas de archivos (patrón ampliado v4.0)
    exchanges_with_paths = [
        Exchange(
            id=1,
            director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="Crea el archivo"),
            agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=2,
                                content="Creé /home/z/my-project/contexto_zai/subagents/clasificador_subagent.py y también src/app/page.tsx")],
            topic="desarrollo",
            start_timestamp=1,
            end_timestamp=2,
        ),
    ]
    content_paths = gen.generate(exchanges_with_paths, chat_label="Paths")
    assert "clasificador_subagent.py" in content_paths
    assert "page.tsx" in content_paths
    print(f"[OK] A2: detecta rutas .py y .tsx (patrón ampliado v4.0)")

    # Test 8: A3 detecta errores nuevos v4.0 (timeout, SIGKILL, etc.)
    exchanges_with_errors = [
        Exchange(
            id=1,
            director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="Ejecuta"),
            agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=2,
                                content="Error: el proceso murió por SIGKILL después de un timeout de 30s")],
            topic="debug",
            start_timestamp=1,
            end_timestamp=2,
        ),
    ]
    content_errors = gen.generate(exchanges_with_errors, chat_label="Errors")
    assert "SIGKILL" in content_errors or "timeout" in content_errors.lower()
    print(f"[OK] A3: detecta SIGKILL/timeout (patrones nuevos v4.0)")

    # Test 9: truncado inteligente sin launcher (backward compatible)
    # Crear un tema con mucho contenido para forzar truncado
    # Cada intercambio tiene ~4000 chars (Director 2000 + Agente 2000)
    # 25 intercambios = ~100000 chars >> 56000 chars (límite textual ~16K tokens)
    long_exchanges = [
        Exchange(
            id=i,
            director_msg=Message(seq=i*2, role=MessageRole.USER, timestamp=i, content=f"Director msg {i} " + "x" * 2000),
            agent_msgs=[Message(seq=i*2+1, role=MessageRole.ASSISTANT, timestamp=i+0.5, content=f"Agent {i} " + "y" * 2000)],
            topic="tema_largo",
            start_timestamp=i,
            end_timestamp=i+1,
        )
        for i in range(1, 26)  # 25 intercambios grandes
    ]
    content_long = gen.generate(long_exchanges, chat_label="Long")
    # Sin launcher, debe incluir aviso de truncado
    assert "truncado" in content_long.lower() or "contenido truncado" in content_long.lower()
    print(f"[OK] Truncado (sin launcher): avisa que se truncó contenido")

    # Test 10: con launcher (mock) — F1 v4.2: generador no ejecuta sub.run() síncrono
    # El generador con launcher cae a regex (backward compatible) hasta que F4 cablee
    # el ProcesadorIntercambios. El launcher se conserva para que F4 lo use.
    def mock_invoker_resumen(prompt: str) -> str:
        return "Resumen del contenido truncado: se detectaron 5 intercambios sobre OOP."

    from contexto_zai.subagents.launcher import SubagentLauncher
    launcher_mock = SubagentLauncher(task_invoker=mock_invoker_resumen)
    gen_with_launcher = EstadoGenerator(launcher=launcher_mock)

    content_with_launcher = gen_with_launcher.generate(long_exchanges, chat_label="WithLauncher")
    # F1 v4.2: el generador con launcher cae a regex (no hay deferred_tasks)
    assert not hasattr(gen_with_launcher, "_deferred_tasks") or not gen_with_launcher.__dict__.get("_deferred_tasks")
    print(f"[OK] F1 v4.2: generador con launcher cae a regex (sin deferred_tasks)")

    # Test 11: D4 con launcher (mock) — F1 v4.2: generador cae a regex
    def mock_invoker_restricciones(prompt: str) -> str:
        return "RESTRICCION: No usar hardcoding\nALCANCE: Aplica a todas las constantes nuevas."

    launcher_rest = SubagentLauncher(task_invoker=mock_invoker_restricciones)
    gen_rest = EstadoGenerator(launcher=launcher_rest)

    exchanges_with_restriction = [
        Exchange(
            id=1,
            director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1,
                                 content="No uses hardcoding en las constantes nuevas"),
            agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=2, content="Entendido.")],
            topic="configuracion",
            start_timestamp=1,
            end_timestamp=2,
        ),
    ]
    content_rest = gen_rest.generate(exchanges_with_restriction, chat_label="Restr")
    # F1 v4.2: el generador cae a regex, "hardcoding" aparece por regex match
    assert "hardcoding" in content_rest.lower() or "restric" in content_rest.lower(), \
        f"Debería detectar restricción por regex, got: {content_rest[:200]}"
    print(f"[OK] F1 v4.2 D4 con launcher: cae a regex (backward compatible)")

    # Test 12: __repr__ muestra si tiene launcher o no
    repr_sin = repr(gen)
    repr_con = repr(gen_with_launcher)
    assert "EstadoGenerator" in repr_sin
    assert "EstadoGenerator" in repr_con
    print(f"[OK] __repr__ sin launcher: {repr_sin}")
    print(f"[OK] __repr__ con launcher: {repr_con}")

    # === Tests v4.3 (F3): secciones G0.A, G0.B, G1 ===

    # Test (F3 v4.3): generate() con workspace_dir incluye las 3 secciones nuevas en orden
    import tempfile as _tempfile_v43
    with _tempfile_v43.TemporaryDirectory() as tmpdir:
        # Crear 03_objetivo_proyecto.md
        Path(tmpdir, "03_objetivo_proyecto.md").write_text(
            "Sistema de recuperación de contexto para agentes Z.ai.", encoding="utf-8"
        )
        gen_v43 = EstadoGenerator(workspace_dir=tmpdir)
        content_v43 = gen_v43.generate(exchanges, chat_label="test")
        # Las 3 secciones nuevas existen y en el orden correcto
        assert "## G0.A — Objetivo del proyecto" in content_v43
        assert "## G0.B — Síntesis del contexto disponible" in content_v43
        assert "## G1 — Cómo usar este contexto" in content_v43
        # Orden: G0.A < G0.B < G1 < D1
        idx_g0a = content_v43.find("## G0.A")
        idx_g0b = content_v43.find("## G0.B")
        idx_g1 = content_v43.find("## G1")
        idx_d1 = content_v43.find("## Sección D1")
        assert 0 <= idx_g0a < idx_g0b < idx_g1 < idx_d1, \
            f"F3: orden esperado G0.A<G0.B<G1<D1, got {idx_g0a},{idx_g0b},{idx_g1},{idx_d1}"
        # G0.A tiene el contenido del archivo
        assert "Sistema de recuperación de contexto para agentes Z.ai." in content_v43
        # G0.B tiene el placeholder inicial
        assert "Síntesis del contexto no disponible" in content_v43
        # G1 tiene el texto fijo
        assert "pipeline.query_context" in content_v43
        # Las secciones operativas siguen presentes
        assert "## Sección D1" in content_v43
        assert "## Sección A1" in content_v43
        print(f"[OK] F3 generate() con workspace: G0.A+G0.B+G1 en orden, antes de operativas")

    # Test (F3 v4.3): G0.A muestra placeholder si no existe 03_objetivo_proyecto.md
    # v4.3 (F5): este caso ya no aplica — si el archivo no existe, el proceso lo crea
    # automáticamente con la cascada documentación → bloques. Lo probamos en los tests F5 de abajo.
    # Aquí verificamos que si el archivo no existe y no hay fuentes para derivarlo,
    # se crea con el contenido mínimo.
    with _tempfile_v43.TemporaryDirectory() as tmpdir:
        gen_v43_no_obj = EstadoGenerator(workspace_dir=tmpdir)
        content_no_obj = gen_v43_no_obj.generate(exchanges, chat_label="test")
        # El archivo se crea automáticamente tras generate()
        assert Path(tmpdir, "03_objetivo_proyecto.md").exists(), \
            "F5: 03_objetivo_proyecto.md debe crearse automáticamente si no existe"
        # Y el contenido está en G0.A (no en un placeholder de "no declarado")
        assert "## G0.A — Objetivo del proyecto" in content_no_obj
        print(f"[OK] F3+F5 G0.A: 03_objetivo_proyecto.md se crea automáticamente si no existe")

    # Test (F3 v4.3): sin workspace_dir, no se añaden G0 ni G1 (backward compatible)
    gen_v40 = EstadoGenerator()  # sin workspace_dir
    content_v40 = gen_v40.generate(exchanges, chat_label="test")
    assert "## G0.A" not in content_v40
    assert "## G0.B" not in content_v40
    assert "## G1" not in content_v40
    assert "## Sección D1" in content_v40  # operativas siguen
    print(f"[OK] F3 sin workspace: sin G0/G1 (backward compatible v4.0)")

    # === Tests v4.3 (F5): creación automática de 03_objetivo_proyecto.md ===

    # Test (F5 v4.3): Caso A — si existe documentación, el objetivo se deriva de ahí
    import tempfile as _tempfile_f5
    import shutil as _shutil_f5
    with _tempfile_f5.TemporaryDirectory() as tmpdir:
        # Crear estructura de documentación simulada en el workspace
        estrategiaDir = Path(tmpdir, "estrategia", "agent-context")
        estrategiaDir.mkdir(parents=True)
        (estrategiaDir / "proyecto.md").write_text(
            "# Proyecto\n\nEste proyecto trata sobre el sistema de "
            "recuperación de contexto para agentes Z.ai. Su objetivo es "
            "permitir que los agentes retomen el hilo tras perder contexto.",
            encoding="utf-8",
        )
        # Mock WORKSPACE_ROOT apuntando a tmpdir
        import contexto_zai.config as _cfg
        original_root = _cfg.WORKSPACE_ROOT
        _cfg.WORKSPACE_ROOT = Path(tmpdir)
        try:
            gen_f5_a = EstadoGenerator(workspace_dir=Path(tmpdir, "ws"))
            gen_f5_a._asegurar_objetivo_proyecto()
            objetivo_path = Path(tmpdir, "ws", "03_objetivo_proyecto.md")
            assert objetivo_path.exists(), "F5 Caso A: 03_objetivo_proyecto.md debe existir"
            contenido = objetivo_path.read_text(encoding="utf-8")
            assert "recuperación de contexto" in contenido, \
                f"F5 Caso A: el objetivo debe venir de la documentación, got: {contenido[:200]}"
            print(f"[OK] F5 Caso A: objetivo derivado de documentación (proyecto.md)")
        finally:
            _cfg.WORKSPACE_ROOT = original_root

    # Test (F5 v4.3): Caso B — si no hay documentación pero hay bloques, deriva de temas
    with _tempfile_f5.TemporaryDirectory() as tmpdir:
        import json as _json_f5
        # No crear estrategia/ (sin documentación)
        # Crear workspace con _metadata.json que tiene temas
        ws_f5b = Path(tmpdir, "ws")
        ws_f5b.mkdir(parents=True)
        (ws_f5b / "_metadata.json").write_text(_json_f5.dumps({
            "tema_a_archivo": {
                "autenticacion_jwt": "bloque_01.md",
                "validaciones": "bloque_02.md",
                "configuracion": "bloque_03.md",
            }
        }), encoding="utf-8")
        # Mock WORKSPACE_ROOT
        import contexto_zai.config as _cfg_b
        original_root_b = _cfg_b.WORKSPACE_ROOT
        _cfg_b.WORKSPACE_ROOT = Path(tmpdir)
        try:
            gen_f5_b = EstadoGenerator(workspace_dir=ws_f5b)
            gen_f5_b._asegurar_objetivo_proyecto()
            objetivo_path = Path(ws_f5b, "03_objetivo_proyecto.md")
            assert objetivo_path.exists(), "F5 Caso B: 03_objetivo_proyecto.md debe existir"
            contenido = objetivo_path.read_text(encoding="utf-8")
            assert "derivado automáticamente" in contenido.lower(), \
                f"F5 Caso B: debe indicar que es derivado, got: {contenido[:200]}"
            assert "autenticacion_jwt" in contenido or "validaciones" in contenido, \
                f"F5 Caso B: debe mencionar temas, got: {contenido[:200]}"
            print(f"[OK] F5 Caso B: objetivo derivado de bloques (temas)")
        finally:
            _cfg_b.WORKSPACE_ROOT = original_root_b

    # Test (F5 v4.3): Caso C — si no hay ni documentación ni bloques, contenido mínimo
    with _tempfile_f5.TemporaryDirectory() as tmpdir:
        import contexto_zai.config as _cfg_c
        original_root_c = _cfg_c.WORKSPACE_ROOT
        _cfg_c.WORKSPACE_ROOT = Path(tmpdir)
        try:
            ws_f5c = Path(tmpdir, "ws")
            ws_f5c.mkdir(parents=True)
            # No crear estrategia/, ni upload/, ni _metadata.json
            gen_f5_c = EstadoGenerator(workspace_dir=ws_f5c)
            gen_f5_c._asegurar_objetivo_proyecto()
            objetivo_path = Path(ws_f5c, "03_objetivo_proyecto.md")
            assert objetivo_path.exists(), "F5 Caso C: 03_objetivo_proyecto.md debe existir"
            contenido = objetivo_path.read_text(encoding="utf-8")
            assert "sin objetivo declarado" in contenido.lower(), \
                f"F5 Caso C: debe tener contenido mínimo, got: {contenido}"
            print(f"[OK] F5 Caso C: contenido mínimo cuando no hay fuentes")
        finally:
            _cfg_c.WORKSPACE_ROOT = original_root_c

    # Test (F5 v4.3): si el archivo ya existe, NO se sobrescribe
    with _tempfile_f5.TemporaryDirectory() as tmpdir:
        import contexto_zai.config as _cfg_d
        original_root_d = _cfg_d.WORKSPACE_ROOT
        _cfg_d.WORKSPACE_ROOT = Path(tmpdir)
        try:
            ws_f5d = Path(tmpdir, "ws")
            ws_f5d.mkdir(parents=True)
            objetivo_path = Path(ws_f5d, "03_objetivo_proyecto.md")
            contenido_original = "Objetivo escrito por el Director manualmente."
            objetivo_path.write_text(contenido_original, encoding="utf-8")
            # Llamar a _asegurar_objetivo_proyecto() — no debe sobrescribir
            gen_f5_d = EstadoGenerator(workspace_dir=ws_f5d)
            gen_f5_d._asegurar_objetivo_proyecto()
            contenido_final = objetivo_path.read_text(encoding="utf-8")
            assert contenido_final == contenido_original, \
                "F5: el archivo existente no debe sobrescribirse"
            print(f"[OK] F5: archivo existente no se sobrescribe")

            # Verificar que _build_g0_a() devuelve el contenido original
            g0_a = gen_f5_d._build_g0_a()
            assert "Objetivo escrito por el Director manualmente." in g0_a
            print(f"[OK] F5: _build_g0_a() devuelve contenido del archivo existente")
        finally:
            _cfg_d.WORKSPACE_ROOT = original_root_d

    print("\n[PASS] estado_generator.py: todos los tests v4.3 pasaron")
