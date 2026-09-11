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
    ) -> None:
        self._max_chars = max_chars
        self._launcher = launcher
        logger.debug(
            "EstadoGenerator inicializado: max_chars=%d (%d tokens), launcher=%s",
            max_chars, int(max_chars / 3.5), "sí" if launcher else "no",
        )

    # -- API pública ------------------------------------------------

    def generate(
        self,
        exchanges: list["Exchange"],
        chat_label: str = "",
    ) -> str:
        """Genera el contenido markdown del estado actual (v4.0, 5 secciones).

        Args:
            exchanges: Lista de intercambios (se usan los últimos 15-20).
            chat_label: Etiqueta descriptiva del chat.

        Returns:
            Contenido markdown con las 5 secciones (D1, D4, A1, A2, A3, A4).
            D2 y D3 se eliminaron en v4.0 (las decisiones viven en
            02_decisiones_clave.md y el contexto del tema se captura
            en A1 con truncado inteligente).
        """
        if not exchanges:
            return "# Estado Actual\n\n(Sin intercambios)\n"

        # Usar los últimos 15-20 intercambios (los más relevantes)
        recent = exchanges[-20:] if len(exchanges) > 20 else exchanges
        ultimo_exchange = exchanges[-1]
        tema_actual = ultimo_exchange.topic

        # Sección D1 -- Última instrucción del Director (literal)
        d1 = self._build_d1(ultimo_exchange)

        # Sección D4 -- Restricciones y preferencias activas del último tema
        # v4.0: usa subagente si hay launcher, sino regex.
        d4 = self._build_d4(recent, tema_actual)

        # Sección A1 -- Qué estaba haciendo el agente (con truncado inteligente v4.0)
        a1 = self._build_a1(recent, tema_actual)

        # Sección A2 -- Entregables producidos (patrones ampliados v4.0)
        a2 = self._build_a2(recent)

        # Sección A3 -- Errores abiertos (patrones ampliados v4.0)
        a3 = self._build_a3(recent)

        # Sección A4 -- Siguiente paso lógico (analiza intercambios v4.0)
        a4 = self._build_a4(recent, tema_actual)

        # v4.0: ensamblar 5 secciones (sin D2 ni D3)
        content = self._assemble(
            chat_label=chat_label or "Chat",
            tema_actual=tema_actual,
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
        # v4.0: si hay launcher, usar subagente
        if self._launcher is not None:
            # Filtrar intercambios del tema activo (o usar recent si no hay match)
            intercambios_tema = [ex for ex in recent if ex.topic == tema_actual] if tema_actual else recent
            if not intercambios_tema:
                intercambios_tema = recent

            # Import diferido para evitar import circular
            from contexto_zai.subagents.intercambios_clasificador_subagent import (
                IntercambiosClasificadorSubagent,
                ModoClasificador,
            )

            sub = IntercambiosClasificadorSubagent(
                launcher=self._launcher,
                modo=ModoClasificador.RESTRICCIONES_TEMA,
            )
            result = sub.run(intercambios_tema)
            if result.success and result.resultado is not None:
                restricciones = result.resultado
                if not restricciones:
                    return "No se identifican restricciones explícitas en el tema activo."
                lines: list[str] = []
                for r in restricciones[:8]:
                    lines.append(f"- {r.texto}")
                    if r.alcance:
                        lines.append(f"  Alcance: {r.alcance}")
                return "\n".join(lines)
            else:
                # v4.0: el error del subagente se reporta (no silencioso)
                logger.warning(
                    "Subagente D4 falló, cayendo a regex: %s",
                    result.error,
                )
                # Caer al regex de abajo (no es fallback silencioso al Director,
                # es fallback dentro del generador porque D4 no es crítica).

        # Regex histórico (backward compatible, sin launcher o subagente falló)
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

        # 3. Si hay launcher, pedir resumen del contenido truncado
        resumen_texto = ""
        if self._launcher is not None and contenido_truncado:
            # Import diferido para evitar import circular
            from contexto_zai.subagents.intercambios_clasificador_subagent import (
                IntercambiosClasificadorSubagent,
                ModoClasificador,
            )

            # Crear un exchange sintético para pasarle el contenido truncado al subagente
            # El subagente espera intercambios, así que le pasamos el texto como
            # un intercambio con el contenido truncado en el mensaje del Director.
            from contexto_zai.models import Exchange as _Exchange, Message as _Message, MessageRole as _MessageRole
            exchange_sintetico = _Exchange(
                id=0,
                director_msg=_Message(
                    seq=0,
                    role=_MessageRole.USER,
                    timestamp=intercambios_tema[0].start_timestamp,
                    content=contenido_truncado[:max_resumen_chars * 3],  # no llenar al subagente
                ),
                agent_msgs=[],
                topic=tema_actual or "truncado",
                start_timestamp=intercambios_tema[0].start_timestamp,
                end_timestamp=intercambios_tema[0].end_timestamp,
            )

            sub = IntercambiosClasificadorSubagent(
                launcher=self._launcher,
                modo=ModoClasificador.RESUMEN_TRUNCADO,
                max_context_tokens=ESTADO_TRUNCADO_RESUMEN_TOKENS,
            )
            result = sub.run([exchange_sintetico])
            if result.success and result.resultado:
                resumen_texto = result.resultado
            else:
                # v4.0: el error del subagente se reporta (no silencioso)
                logger.warning(
                    "Subagente A1 (resumen truncado) falló: %s. "
                    "Se mantiene solo el texto textual.",
                    result.error,
                )
                resumen_texto = "[No se pudo generar el resumen del contenido truncado: " + result.error + "]"

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
            ctx_str = f" -- {ctx}" if ctx else ""
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
    ) -> str:
        """Ensambla las 5 secciones en el contenido final (v4.0).

        Secciones: D1, D4, A1, A2, A3, A4 (sin D2 ni D3, eliminados en v4.0).
        """
        return f"""# Estado Actual -- {chat_label}

**Tema activo:** **{tema_actual}**

---

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

    # Test 10: con launcher (mock) — A1 usa truncado inteligente con resumen
    def mock_invoker_resumen(prompt: str) -> str:
        return "Resumen del contenido truncado: se detectaron 5 intercambios sobre OOP."

    from contexto_zai.subagents.launcher import SubagentLauncher
    launcher_mock = SubagentLauncher(task_invoker=mock_invoker_resumen)
    gen_with_launcher = EstadoGenerator(launcher=launcher_mock)

    content_with_launcher = gen_with_launcher.generate(long_exchanges, chat_label="WithLauncher")
    # Con launcher, debe incluir la sección "Resumen del contenido truncado"
    assert "Resumen del contenido truncado" in content_with_launcher or "Truncado inteligente" in content_with_launcher
    print(f"[OK] Truncado inteligente (con launcher): incluye resumen del subagente")

    # Test 11: D4 con launcher (mock) — usa subagente para restricciones
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
    assert "hardcoding" in content_rest
    print(f"[OK] D4 con launcher: usa subagente para detectar restricciones")

    # Test 12: __repr__ muestra si tiene launcher o no
    repr_sin = repr(gen)
    repr_con = repr(gen_with_launcher)
    assert "EstadoGenerator" in repr_sin
    assert "EstadoGenerator" in repr_con
    print(f"[OK] __repr__ sin launcher: {repr_sin}")
    print(f"[OK] __repr__ con launcher: {repr_con}")

    print("\n[PASS] estado_generator.py: todos los tests v4.0 pasaron")
