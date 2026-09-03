from __future__ import annotations

import logging
import re

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contexto_zai.models import Exchange

logger = logging.getLogger(__name__)

# Patrones para detectar referencias a archivos.
# Captura rutas con extensiones comunes de código y configuración.
_FILE_PATH_PATTERN = re.compile(
    r'``?([\w./\-]+\.(?:py|md|json|yaml|yml|txt|toml|cfg|ini|env|sh|bash|zsh|sql|html|css|js|ts|tsx|jsx|rs|go|java|rb|php|xml|csv|log))``?',
    re.IGNORECASE,
)

# Patrones para detectar errores en mensajes.
_ERROR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'\bERROR\b', re.IGNORECASE),
    re.compile(r'\bFAIL(ED|ED)?\b', re.IGNORECASE),
    re.compile(r'\bTraceback\b', re.IGNORECASE),
    re.compile(r'\bException\b', re.IGNORECASE),
    re.compile(r'\bbug\b', re.IGNORECASE),
]

# Patrones para detectar decisiones pendientes o preguntas al Director.
_PENDING_DECISION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'¿'),
    re.compile(r'\b(opciones?|alternativas?)\b', re.IGNORECASE),
    re.compile(r'\b(prefieres?|decidas?|eliges?)\b', re.IGNORECASE),
    re.compile(r'\b(confirmation|confirmación)\b', re.IGNORECASE),
    re.compile(r'\b(qué|cual|cuál)\s+(hacemos|prefieres|quieres)\b', re.IGNORECASE),
    re.compile(r'\b(te parece bien|estás de acuerdo)\b', re.IGNORECASE),
]

# Número máximo de caracteres para truncar la tarea del Director.
_DIRECTOR_TASK_MAX_CHARS: int = 500

# Rango de exchanges a considerar (últimos 15-20).
_MIN_EXCHANGES: int = 15
_MAX_EXCHANGES: int = 20

# Número de respuestas del agente a resumir.
_MAX_AGENT_RESPONSES: int = 5
_MIN_AGENT_RESPONSES: int = 3

# Líneas máximas por respuesta del agente en el resumen.
_MAX_LINES_PER_RESPONSE: int = 5


class EstadoGenerator:
    """Generador del archivo ``00_estado_actual.md``.

    Analiza los últimos exchanges de la conversación para producir un
    resumen estructurado del estado actual de la sesión, incluyendo
    la última tarea del Director, las respuestas recientes del agente,
    entregables, errores abiertos, decisiones pendientes y el
    siguiente paso lógico.

    El contenido generado está limitado por ``max_chars`` para
    cumplir con el presupuesto de tokens del spec.

    Args:
        max_chars: Número máximo de caracteres del contenido generado.
            Por defecto 10_500 (3 000 tokens × 3,5 chars/token).
    """

    def __init__(self, max_chars: int = 10_500) -> None:
        """Inicializa el generador de estado actual.

        Args:
            max_chars: Límite de caracteres para el contenido generado.
                Valor por defecto calculado como 3 000 tokens × 3,5.
        """
        self.max_chars = max_chars
        logger.debug(
            "EstadoGenerator inicializado con max_chars=%d",
            self.max_chars,
        )

    def generate(self, exchanges: list[Exchange], chat_label: str = "") -> str:
        """Genera el contenido de ``00_estado_actual.md``.

        Toma los últimos 15-20 exchanges (o todos si hay menos) y
        produce un documento markdown con las secciones:
        última tarea del Director, última respuesta del agente,
        entregables, errores abiertos, decisiones pendientes y
        siguiente paso lógico.

        Si el contenido total excede ``max_chars``, se truncan las
        secciones en este orden: primero "Última respuesta del agente",
        luego "Entregables".

        Args:
            exchanges: Lista completa de exchanges de la conversación.
            chat_label: Etiqueta descriptiva del chat para el encabezado.

        Returns:
            Contenido markdown del archivo de estado actual.
        """
        logger.info(
            "Generando estado actual para %d exchanges (chat_label=%r)",
            len(exchanges),
            chat_label,
        )

        if not exchanges:
            logger.warning("No hay exchanges para generar estado actual")
            return self._empty_state(chat_label)

        # Seleccionar los últimos exchanges dentro del rango permitido.
        recent = self._select_recent_exchanges(exchanges)
        logger.debug(
            "Seleccionados %d exchanges recientes de %d totales",
            len(recent),
            len(exchanges),
        )

        # Construir cada sección.
        last_task = self._extract_last_director_task(recent)
        agent_summary = self._summarize_last_agent_responses(recent)
        deliverables = self._extract_deliverables(recent)
        errors = self._extract_open_errors(recent)
        decisions = self._extract_pending_decisions(recent)
        next_step = self._infer_next_step(recent)

        # Ensamblar el documento.
        content = self._assemble(
            chat_label=chat_label,
            last_task=last_task,
            agent_summary=agent_summary,
            deliverables=deliverables,
            errors=errors,
            decisions=decisions,
            next_step=next_step,
        )

        # Aplicar truncamiento si es necesario.
        content = self._enforce_char_limit(
            content=content,
            chat_label=chat_label,
            last_task=last_task,
            agent_summary=agent_summary,
            deliverables=deliverables,
            errors=errors,
            decisions=decisions,
            next_step=next_step,
        )

        logger.info(
            "Estado actual generado: %d caracteres (%.0f tokens estimados)",
            len(content),
            len(content) / 3.5,
        )
        return content

    # ── Selección de exchanges ───────────────────────────────────

    def _select_recent_exchanges(self, exchanges: list[Exchange]) -> list[Exchange]:
        """Selecciona los últimos exchanges dentro del rango 15-20.

        Si hay 20 o más exchanges, toma los últimos 20.
        Si hay entre 15 y 19, toma todos.
        Si hay menos de 15, toma todos.

        Args:
            exchanges: Lista completa de exchanges.

        Returns:
            Sublista con los exchanges más recientes.
        """
        if len(exchanges) <= _MAX_EXCHANGES:
            return list(exchanges)
        return list(exchanges[-_MAX_EXCHANGES:])

    # ── Extracción de secciones ──────────────────────────────────

    def _extract_last_director_task(self, exchanges: list[Exchange]) -> str:
        """Extrae el texto literal del último mensaje del Director.

        Busca el último exchange que tenga un mensaje del Director
        con contenido no vacío. Si el texto supera los 500
        caracteres, se trunca con puntos suspensivos.

        Args:
            exchanges: Lista de exchanges recientes a analizar.

        Returns:
            Texto de la última tarea del Director, o un mensaje
            indicando que no se encontró.
        """
        logger.debug("Extrayendo última tarea del Director")

        for exchange in reversed(exchanges):
            content = exchange.director_msg.content.strip()
            if content:
                if len(content) > _DIRECTOR_TASK_MAX_CHARS:
                    truncated = content[:_DIRECTOR_TASK_MAX_CHARS].rstrip()
                    # Evitar cortar a mitad de palabra.
                    last_space = truncated.rfind(" ")
                    if last_space > _DIRECTOR_TASK_MAX_CHARS * 0.7:
                        truncated = truncated[:last_space]
                    truncated = truncated.rstrip() + "..."
                    logger.debug(
                        "Tarea del Director truncada: %d → %d chars",
                        len(content),
                        len(truncated),
                    )
                    return truncated
                return content

        logger.debug("No se encontró tarea del Director en los exchanges")
        return "(sin tarea del Director en los exchanges recientes)"

    def _summarize_last_agent_responses(self, exchanges: list[Exchange]) -> str:
        """Resume las últimas 3-5 respuestas del agente.

        Recorre los exchanges en orden inverso, recolectando las
        respuestas del agente hasta acumular entre 3 y 5. Cada
        respuesta se trunca a ~5 líneas y se concatena con
        separadores.

        Args:
            exchanges: Lista de exchanges recientes a analizar.

        Returns:
            Resumen concatenado de las respuestas recientes del
            agente, o un mensaje indicando que no hay respuestas.
        """
        logger.debug("Resumiendo últimas respuestas del agente")

        responses: list[str] = []

        for exchange in reversed(exchanges):
            for agent_msg in exchange.agent_msgs:
                content = agent_msg.content.strip()
                if not content:
                    continue
                summary_lines = self._truncate_to_lines(
                    content, _MAX_LINES_PER_RESPONSE
                )
                responses.append("\n".join(summary_lines))
                if len(responses) >= _MAX_AGENT_RESPONSES:
                    break
            if len(responses) >= _MAX_AGENT_RESPONSES:
                break

        # Si no alcanza el mínimo, usar los que haya.
        if not responses:
            logger.debug("No se encontraron respuestas del agente")
            return "(sin respuestas del agente en los exchanges recientes)"

        # Invertir para mantener orden cronológico y concatenar.
        responses.reverse()
        result = "\n\n".join(responses)

        # Limpiar espacios múltiples y líneas vacías consecutivas.
        result = re.sub(r'\n{3,}', '\n\n', result).strip()

        logger.debug(
            "Resumen del agente: %d respuestas, %d caracteres",
            len(responses),
            len(result),
        )
        return result

    def _extract_deliverables(self, exchanges: list[Exchange]) -> str:
        """Escanea los mensajes en busca de referencias a archivos.

        Busca patrones de rutas con extensiones de archivo conocidas
        (.py, .md, .json, .yaml, .yml, .txt, .toml, etc.) en todos
        los mensajes de los exchanges proporcionados. Para cada
        archivo único encontrado, extrae una línea de contexto del
        mensaje que lo contiene.

        Args:
            exchanges: Lista de exchanges a escanear.

        Returns:
            Lista formateada de entregables con descripciones,
            o "Ninguno identificado" si no se encuentran.
        """
        logger.debug("Extrayendo entregables de los exchanges")

        seen_paths: set[str] = set()
        deliverables: list[str] = []

        for exchange in exchanges:
            for msg in exchange.all_messages:
                content = msg.content
                if not content:
                    continue
                matches = _FILE_PATH_PATTERN.findall(content)
                for file_path in matches:
                    # Normalizar la ruta.
                    normalized = file_path.replace("\\", "/").strip("./")
                    if normalized in seen_paths:
                        continue
                    seen_paths.add(normalized)

                    # Extraer una línea de contexto alrededor de la mención.
                    context_line = self._extract_context_line(
                        content, file_path
                    )
                    entry = f"- `{normalized}`: {context_line}"
                    deliverables.append(entry)

        if not deliverables:
            logger.debug("No se identificaron entregables")
            return "Ninguno identificado"

        result = "\n".join(deliverables)
        logger.debug(
            "Entregables encontrados: %d archivos", len(deliverables)
        )
        return result

    def _extract_open_errors(self, exchanges: list[Exchange]) -> str:
        """Escanea los mensajes en busca de errores abiertos.

        Busca patrones de error (ERROR, FAIL, Traceback, Exception,
        bug) en todos los mensajes de los exchanges proporcionados.
        Para cada error único encontrado, extrae el contexto
        circundante.

        Args:
            exchanges: Lista de exchanges a escanear.

        Returns:
            Lista formateada de errores con contexto,
            o "Ninguno identificado" si no se encuentran.
        """
        logger.debug("Extrayendo errores abiertos de los exchanges")

        seen_errors: set[str] = set()
        errors: list[str] = []

        for exchange in exchanges:
            for msg in exchange.all_messages:
                content = msg.content
                if not content:
                    continue

                for pattern in _ERROR_PATTERNS:
                    for match in pattern.finditer(content):
                        start = max(0, match.start() - 40)
                        end = min(len(content), match.end() + 80)
                        error_context = content[start:end].strip()
                        # Limpiar saltos de línea dentro del contexto.
                        error_context = re.sub(
                            r'\s+', ' ', error_context
                        ).strip()

                        # Crear clave de deduplicación basada en el texto.
                        # Tomar hasta 60 caracteres centrales como clave.
                        center_start = max(
                            0, len(error_context) // 2 - 30
                        )
                        center_end = center_start + 60
                        dedup_key = error_context[center_start:center_end]

                        if dedup_key in seen_errors:
                            continue
                        seen_errors.add(dedup_key)

                        entry = f"- {error_context}"
                        errors.append(entry)

        if not errors:
            logger.debug("No se identificaron errores abiertos")
            return "Ninguno identificado"

        result = "\n".join(errors)
        logger.debug(
            "Errores abiertos encontrados: %d", len(errors)
        )
        return result

    def _extract_pending_decisions(self, exchanges: list[Exchange]) -> str:
        """Escanea los mensajes en busca de decisiones pendientes del Director.

        Busca patrones que indiquen preguntas, opciones presentadas
        o solicitudes de decisión dirigidas al Director.

        Args:
            exchanges: Lista de exchanges a escanear.

        Returns:
            Lista formateada de decisiones pendientes,
            o "Ninguna pendiente" si no se encuentran.
        """
        logger.debug(
            "Extrayendo decisiones pendientes del Director"
        )

        decisions: list[str] = []

        for exchange in reversed(exchanges):
            # Buscar preguntas del agente al Director.
            for agent_msg in exchange.agent_msgs:
                content = agent_msg.content.strip()
                if not content:
                    continue
                if self._has_pending_decision(content):
                    # Extraer la oración relevante.
                    sentence = self._extract_relevant_sentence(content)
                    if sentence and sentence not in decisions:
                        decisions.append(sentence)

            # También revisar si el Director presentó opciones.
            director_content = exchange.director_msg.content.strip()
            if director_content and self._has_pending_decision(director_content):
                sentence = self._extract_relevant_sentence(director_content)
                if sentence and sentence not in decisions:
                    decisions.append(sentence)

            if len(decisions) >= 5:
                break

        if not decisions:
            logger.debug("No se identificaron decisiones pendientes")
            return "Ninguna pendiente"

        result = "\n".join(f"- {d}" for d in decisions)
        logger.debug(
            "Decisiones pendientes encontradas: %d", len(decisions)
        )
        return result

    def _infer_next_step(self, exchanges: list[Exchange]) -> str:
        """Infiere el siguiente paso lógico basado en el último exchange.

        Analiza el último exchange para determinar qué debería hacer
        el agente a continuación. Si el último mensaje es del agente,
        infiere la continuación lógica. Si es del Director,
        describe la tarea pendiente.

        Args:
            exchanges: Lista de exchanges recientes.

        Returns:
            Descripción de 1-2 oraciones del siguiente paso lógico.
        """
        logger.debug("Infiriendo siguiente paso lógico")

        if not exchanges:
            return "No hay exchanges para inferir el siguiente paso."

        last_exchange = exchanges[-1]
        director_content = last_exchange.director_msg.content.strip()

        # Si el agente aún no respondió, el siguiente paso es responder.
        if not last_exchange.agent_msgs:
            if director_content:
                preview = director_content[:100].rstrip()
                result = (
                    f"Responder a la última instrucción del Director: "
                    f"\"{preview}...\""
                )
                logger.debug("Siguiente paso: responder al Director")
                return result
            return "Esperar instrucciones del Director."

        # El agente ya respondió; inferir continuación.
        last_agent_content = ""
        for agent_msg in reversed(last_exchange.agent_msgs):
            if agent_msg.content.strip():
                last_agent_content = agent_msg.content.strip()
                break

        if not last_agent_content:
            return "Esperar instrucciones del Director."

        # Heurísticas para inferir el siguiente paso.
        result = self._apply_next_step_heuristics(
            last_agent_content, director_content
        )

        logger.debug("Siguiente paso inferido: %s", result)
        return result

    # ── Ensamblaje y truncamiento ────────────────────────────────

    def _assemble(
        self,
        chat_label: str,
        last_task: str,
        agent_summary: str,
        deliverables: str,
        errors: str,
        decisions: str,
        next_step: str,
    ) -> str:
        """Ensambla todas las secciones en el documento markdown final.

        Args:
            chat_label: Etiqueta del chat.
            last_task: Texto de la última tarea del Director.
            agent_summary: Resumen de respuestas del agente.
            deliverables: Lista de entregables.
            errors: Lista de errores abiertos.
            decisions: Lista de decisiones pendientes.
            next_step: Siguiente paso lógico.

        Returns:
            Documento markdown completo.
        """
        lines: list[str] = [
            f"# Estado Actual — {chat_label}",
            "",
            "## Última tarea en curso",
            last_task,
            "",
            "## Última respuesta del agente",
            agent_summary,
            "",
            "## Entregables producidos",
            deliverables,
            "",
            "## Errores abiertos",
            errors,
            "",
            "## Decisiones pendientes del Director",
            decisions,
            "",
            "## Siguiente paso lógico",
            next_step,
            "",
        ]
        return "\n".join(lines)

    def _enforce_char_limit(
        self,
        content: str,
        chat_label: str,
        last_task: str,
        agent_summary: str,
        deliverables: str,
        errors: str,
        decisions: str,
        next_step: str,
    ) -> str:
        """Aplica truncamiento si el contenido excede ``max_chars``.

        El orden de truncamiento es:
        1. Sección "Última respuesta del agente".
        2. Sección "Entregables producidos".

        Las demás secciones se mantienen intactas.

        Args:
            content: Contenido completo ya ensamblado.
            chat_label: Etiqueta del chat.
            last_task: Texto de la última tarea del Director.
            agent_summary: Resumen de respuestas del agente.
            deliverables: Lista de entregables.
            errors: Lista de errores abiertos.
            decisions: Lista de decisiones pendientes.
            next_step: Siguiente paso lógico.

        Returns:
            Contenido dentro del límite de caracteres.
        """
        if len(content) <= self.max_chars:
            return content

        logger.warning(
            "Contenido excede max_chars (%d > %d), aplicando truncamiento",
            len(content),
            self.max_chars,
        )

        # Calcular el espacio disponible restando las secciones fijas.
        fixed_parts = self._assemble(
            chat_label=chat_label,
            last_task=last_task,
            agent_summary="",
            deliverables="",
            errors=errors,
            decisions=decisions,
            next_step=next_step,
        )
        available = self.max_chars - len(fixed_parts)

        if available <= 0:
            logger.error(
                "Las secciones fijas ya exceden max_chars, "
                "truncando entregables también"
            )
            # Ensamblar sin agente ni entregables.
            minimal = self._assemble(
                chat_label=chat_label,
                last_task=last_task,
                agent_summary="(truncado por límite de espacio)",
                deliverables="(truncado por límite de espacio)",
                errors=errors,
                decisions=decisions,
                next_step=next_step,
            )
            if len(minimal) <= self.max_chars:
                return minimal
            # Último recurso: truncar errores.
            return minimal[: self.max_chars]

        # Truncar el resumen del agente para que quepa.
        truncated_agent = agent_summary[:available]
        # No cortar a mitad de línea si es posible.
        last_newline = truncated_agent.rfind("\n")
        if last_newline > available * 0.5:
            truncated_agent = truncated_agent[:last_newline]

        result = self._assemble(
            chat_label=chat_label,
            last_task=last_task,
            agent_summary=truncated_agent.rstrip(),
            deliverables=deliverables,
            errors=errors,
            decisions=decisions,
            next_step=next_step,
        )

        # Si aún excede, truncar también entregables.
        if len(result) > self.max_chars:
            logger.warning(
                "Aún excede tras truncar agente, truncando entregables"
            )
            over_by = len(result) - self.max_chars
            truncated_deliverables = deliverables
            if len(truncated_deliverables) > over_by + 10:
                truncated_deliverables = (
                    deliverables[: len(deliverables) - over_by - 10].rstrip()
                    + "\n- ... (truncado)"
                )
            else:
                truncated_deliverables = "(truncado por límite de espacio)"

            result = self._assemble(
                chat_label=chat_label,
                last_task=last_task,
                agent_summary=truncated_agent.rstrip(),
                deliverables=truncated_deliverables,
                errors=errors,
                decisions=decisions,
                next_step=next_step,
            )

        # Corte final de seguridad.
        if len(result) > self.max_chars:
            logger.error(
                "Contenido aún excede tras doble truncamiento, "
                "aplicando corte duro"
            )
            result = result[: self.max_chars]

        logger.debug(
            "Contenido truncado a %d caracteres", len(result)
        )
        return result

    # ── Métodos auxiliares privados ──────────────────────────────

    def _empty_state(self, chat_label: str) -> str:
        """Genera un documento de estado vacío cuando no hay exchanges.

        Args:
            chat_label: Etiqueta del chat.

        Returns:
            Documento markdown con todas las secciones vacías.
        """
        lines: list[str] = [
            f"# Estado Actual — {chat_label}",
            "",
            "## Última tarea en curso",
            "(sin exchanges)",
            "",
            "## Última respuesta del agente",
            "(sin exchanges)",
            "",
            "## Entregables producidos",
            "Ninguno identificado",
            "",
            "## Errores abiertos",
            "Ninguno identificado",
            "",
            "## Decisiones pendientes del Director",
            "Ninguna pendiente",
            "",
            "## Siguiente paso lógico",
            "No hay exchanges para determinar el siguiente paso.",
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _truncate_to_lines(text: str, max_lines: int) -> list[str]:
        """Trunca un texto a un número máximo de líneas.

        Divide el texto en líneas, toma las primeras ``max_lines``
        y añade "..." si se truncó.

        Args:
            text: Texto a truncar.
            max_lines: Número máximo de líneas a conservar.

        Returns:
            Lista de líneas truncadas.
        """
        lines = text.split("\n")
        if len(lines) <= max_lines:
            return lines
        truncated = lines[:max_lines]
        # Añadir indicador de truncamiento a la última línea.
        last_line = truncated[-1].rstrip()
        if last_line:
            truncated[-1] = last_line + "..."
        return truncated

    @staticmethod
    def _extract_context_line(
        content: str, file_path: str
    ) -> str:
        """Extrae una línea de contexto alrededor de una mención de archivo.

        Busca el archivo en el contenido y extrae la línea completa
        que lo contiene, truncada a 120 caracteres.

        Args:
            content: Contenido del mensaje.
            file_path: Ruta del archivo encontrada.

        Returns:
            Línea de contexto truncada.
        """
        # Buscar la posición del archivo en el contenido.
        idx = content.find(file_path)
        if idx == -1:
            return "(sin contexto)"

        # Encontrar el inicio y fin de la línea.
        line_start = content.rfind("\n", 0, idx) + 1
        line_end = content.find("\n", idx)
        if line_end == -1:
            line_end = len(content)

        line = content[line_start:line_end].strip()
        if len(line) > 120:
            line = line[:117].rstrip() + "..."
        return line

    @staticmethod
    def _has_pending_decision(content: str) -> bool:
        """Verifica si un mensaje contiene patrones de decisión pendiente.

        Args:
            content: Contenido del mensaje a analizar.

        Returns:
            ``True`` si se detecta algún patrón de decisión pendiente.
        """
        for pattern in _PENDING_DECISION_PATTERNS:
            if pattern.search(content):
                return True
        return False

    @staticmethod
    def _extract_relevant_sentence(content: str) -> str:
        """Extrae la oración más relevante de un mensaje.

        Busca la oración que contiene el patrón de decisión
        pendiente y la devuelve truncada a 150 caracteres.

        Args:
            content: Contenido del mensaje.

        Returns:
            Oración relevante truncada.
        """
        # Dividir en oraciones por puntos, signos de interrogación
        # y signos de exclamación.
        sentences = re.split(r'(?<=[.?!])\s+', content)

        for sentence in sentences:
            for pattern in _PENDING_DECISION_PATTERNS:
                if pattern.search(sentence):
                    s = sentence.strip()
                    if len(s) > 150:
                        s = s[:147].rstrip() + "..."
                    return s

        # Si no se encontró oración con patrón, devolver la primera.
        if sentences:
            first = sentences[0].strip()
            if len(first) > 150:
                first = first[:147].rstrip() + "..."
            return first

        return content[:150].strip()

    def _apply_next_step_heuristics(
        self, agent_content: str, director_content: str
    ) -> str:
        """Aplica heurísticas para inferir el siguiente paso del agente.

        Evalúa el contenido de la última respuesta del agente y
        la última instrucción del Director para determinar qué
        acción corresponde a continuación.

        Args:
            agent_content: Contenido de la última respuesta del agente.
            director_content: Contenido de la última instrucción del Director.

        Returns:
            Descripción de 1-2 oraciones del siguiente paso.
        """
        content_lower = agent_content.lower()

        # Si hay errores mencionados, sugerir corrección.
        if any(
            kw in content_lower
            for kw in ("error", "fail", "traceback", "exception", "bug")
        ):
            return (
                "Revisar y corregir los errores reportados en la "
                "última respuesta antes de continuar con la tarea."
            )

        # Si el agente menciona que creó o modificó archivos.
        if any(
            kw in content_lower
            for kw in ("creado", "creé", "implementé", "modifiqué", "escribí")
        ):
            return (
                "Verificar que los archivos creados o modificados "
                "funcionan correctamente y continuar con las tareas pendientes."
            )

        # Si el agente está esperando instrucciones.
        if any(
            kw in content_lower
            for kw in ("esperando", "espero", "necesito que", "dime", "indica")
        ):
            return "El agente está esperando instrucciones adicionales del Director."

        # Si el agente está en medio de una implementación.
        if any(
            kw in content_lower
            for kw in ("continuando", "siguiente", "ahora voy", "procedo")
        ):
            return (
                "Continuar con la implementación en curso según "
                "lo indicado en la última respuesta del agente."
            )

        # Si el agente completó algo.
        if any(
            kw in content_lower
            for kw in ("completado", "terminado", "finalizado", "listo")
        ):
            return (
                "La última tarea parece completada. Esperar "
                "confirmación o nuevas instrucciones del Director."
            )

        # Por defecto: continuar con la tarea del Director.
        if director_content:
            preview = director_content[:80].rstrip()
            return (
                f"Continuar trabajando en la tarea del Director: "
                f"\"{preview}...\""
            )

        return "Continuar con el trabajo en curso según el contexto de la sesión."
