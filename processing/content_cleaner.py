"""Módulo de limpieza y formateo de contenido de mensajes.

Se encarga de eliminar bloques de razonamiento (reasoning) insertados
por algunos modelos en las respuestas del agente, y de formatear
los exchanges como markdown para su inclusión en bloques temáticos.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contexto_zai.models import Exchange, MessageRole

logger = logging.getLogger(__name__)

# Patrón regex para detectar bloques de razonamiento al inicio del contenido.
# Los bloques son cadenas JSON con estructura: {"type":"reasoning","content":"..."}
# Acepta espacios flexibles alrededor de los dos puntos y comillas.
_REASONING_PATTERN = re.compile(
    r'\A\s*\{\s*"type"\s*:\s*"reasoning"\s*,\s*"content"\s*:\s*"(.*?)"\s*\}\s*',
    re.DOTALL,
)

# Sobrecarga alternativa que usa una comilla simple o comillas escapadas
# para el campo "content".
_REASONING_PATTERN_ALT = re.compile(
    r'\A\s*\{\s*"type"\s*:\s*"reasoning"\s*,\s*"content"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}\s*',
    re.DOTALL,
)


class ContentCleaner:
    """Limpia contenido de mensajes y formatea exchanges como markdown.

    Elimina los bloques de razonamiento (reasoning) que ciertos modelos
    insertan al inicio de las respuestas del agente. También proporciona
    métodos para formatear exchanges completos como markdown con
    encabezados y separadores.

    Example::

        cleaner = ContentCleaner()
        formatted = cleaner.format_exchange(exchange)
    """

    def __init__(self) -> None:
        """Inicializa el limpiador de contenido.

        No requiere parámetros de configuración.
        """
        logger.debug("ContentCleaner inicializado")

    def clean(self, content: str) -> str:
        """Elimina bloques de razonamiento del contenido de un mensaje.

        Los bloques de razonamiento son cadenas JSON con la estructura::

            {"type": "reasoning", "content": "..."}

        que aparecen al inicio del contenido. Si el contenido completo
        es un bloque de razonamiento, se devuelve una cadena vacía.
        Si el bloque está seguido de contenido visible, se devuelve
        únicamente la parte visible. También se elimina el
        espacio en blanco sobrante al inicio y al final.

        El método intenta primero un parseo JSON estricto. Si falla,
        recurre a una aproximación por regex para mayor robustez.

        Args:
            content: Contenido textual crudo del mensaje.

        Returns:
            Contenido limpio sin el bloque de razonamiento, o cadena
            vacía si todo el contenido era razonamiento.
        """
        if not content or not content.strip():
            logger.debug("Contenido vacío, nada que limpiar")
            return ""

        result = self._remove_reasoning_block(content)
        cleaned = result.strip()

        if cleaned:
            logger.debug(
                "Razonamiento eliminado: %d → %d caracteres",
                len(content),
                len(cleaned),
            )
        else:
            logger.debug(
                "Todo el contenido era razonamiento (%d chars) → vacío",
                len(content),
            )

        return cleaned

    def format_exchange(self, exchange: Exchange, exchange_num: int | None = None) -> str:
        """Formatea un exchange como markdown para inclusión en un bloque temático.

        Genera un bloque markdown con el número de exchange, la fecha
        del mensaje del Director, el contenido limpio del Director y
        las respuestas concatenadas del agente (también limpias).

        Formato de salida::

            ## Exchange {N} — [{fecha}]

            ### Director:
            {contenido del director}

            ### Agente:
            {respuestas concatenadas del agente}

            ---

        Args:
            exchange: :class:`Exchange` a formatear.
            exchange_num: Número de exchange a usar en el encabezado.
                Si es ``None`` se usa ``exchange.id``.

        Returns:
            Cadena markdown con el exchange formateado.
        """
        num = exchange_num if exchange_num is not None else exchange.id
        datetime_str = exchange.datetime_str

        # Limpiar contenido del Director
        director_content = self.format_message_content(
            exchange.director_msg.content,
            exchange.director_msg.role,
        )

        # Limpiar y concatenar respuestas del agente
        agent_parts: list[str] = []
        for agent_msg in exchange.agent_msgs:
            cleaned = self.format_message_content(
                agent_msg.content,
                agent_msg.role,
            )
            if cleaned:
                agent_parts.append(cleaned)
        agent_content = "\n\n".join(agent_parts) if agent_parts else "(sin respuesta)"

        # Construir el bloque markdown
        lines: list[str] = [
            f"## Exchange {num} — [{datetime_str}]",
            "",
            "### Director:",
            director_content,
            "",
            "### Agente:",
            agent_content,
            "",
            "---",
        ]

        formatted = "\n".join(lines)
        logger.debug(
            "Exchange %d formateado: %d caracteres",
            exchange.id,
            len(formatted),
        )
        return formatted

    def format_message_content(self, content: str, role: MessageRole) -> str:
        """Limpia el contenido de un mensaje según su rol.

        Para mensajes del agente (assistant), elimina los bloques
        de razonamiento. Para mensajes del usuario (user) y del
        sistema (system), devuelve el contenido tal cual.

        Args:
            content: Contenido textual del mensaje.
            role: Rol del emisor del mensaje.

        Returns:
            Contenido procesado según el rol.
        """
        if role.value == "assistant":
            return self.clean(content)
        return content

    # ── Métodos internos ──────────────────────────────────────────

    def _remove_reasoning_block(self, content: str) -> str:
        """Elimina un bloque de razonamiento al inicio del contenido.

        Intenta tres estrategias en orden:

        1. Parseo JSON estricto: si el contenido completo es un JSON
           válido con ``"type": "reasoning"``, se extrae el campo
           ``content``. Si hay contenido adicional tras el JSON,
           se devuelve solo la parte adicional.
        2. Parseo JSON del prefijo: se intenta extraer un objeto JSON
           al inicio del string y, si es un bloque de razonamiento,
           se elimina.
        3. Regex: como último recurso se usa un patrón regex para
           detectar y eliminar el bloque de razonamiento.

        Args:
            content: Contenido textual crudo.

        Returns:
            Contenido sin el bloque de razonamiento.
        """
        stripped = content.strip()

        # Estrategia 1: JSON estricto — todo el contenido es el bloque
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and data.get("type") == "reasoning":
                inner = data.get("content", "")
                # Verificar si hay algo después del JSON en el contenido original
                remainder = self._extract_remainder_after_json(content)
                if remainder:
                    logger.debug("Bloque de razonamiento (JSON completo) eliminado, queda remainder")
                    return remainder.strip()
                # Solo era razonamiento
                logger.debug("Bloque de razonamiento (JSON completo) — contenido vacío tras limpieza")
                return ""
        except (json.JSONDecodeError, ValueError):
            pass

        # Estrategia 2: JSON de prefijo — el bloque está al inicio
        try:
            prefix_data, remainder = self._try_parse_prefix_json(stripped)
            if prefix_data is not None and isinstance(prefix_data, dict):
                if prefix_data.get("type") == "reasoning":
                    logger.debug("Bloque de razonamiento (prefijo JSON) eliminado")
                    return remainder.strip() if remainder else ""
        except (json.JSONDecodeError, ValueError):
            pass

        # Estrategia 3: Regex
        match = _REASONING_PATTERN_ALT.match(content)
        if match:
            after = content[match.end():]
            if after.strip():
                logger.debug("Bloque de razonamiento (regex) eliminado, queda contenido visible")
                return after.strip()
            else:
                logger.debug("Bloque de razonamiento (regex) — contenido vacío tras limpieza")
                return ""

        # No se encontró bloque de razonamiento
        return content

    @staticmethod
    def _extract_remainder_after_json(content: str) -> str:
        """Extrae el texto que queda después de un objeto JSON completo.

        Usa un decodificador JSON para encontrar dónde termina el
        primer objeto JSON y devuelve todo lo que sigue.

        Args:
            content: Contenido que inicia con un JSON válido.

        Returns:
            Cadena vacía si no hay contenido adicional, o el texto
            que sigue al JSON completo.
        """
        decoder = json.JSONDecoder()
        try:
            decoder.raw_decode(content)
            # raw_decode consume el JSON y devuelve (obj, end_index)
            _, end_idx = decoder.raw_decode(content)
            remainder = content[end_idx:].strip()
            return remainder
        except (json.JSONDecodeError, ValueError):
            return ""

    @staticmethod
    def _try_parse_prefix_json(content: str) -> tuple[object | None, str]:
        """Intenta parsear un objeto JSON al inicio del contenido.

        Args:
            content: Contenido textual que puede iniciar con JSON.

        Returns:
            Tupla ``(parsed_object, remainder)``. Si el contenido
            no inicia con JSON válido, devuelve ``(None, content)``.
        """
        decoder = json.JSONDecoder()
        try:
            obj, end_idx = decoder.raw_decode(content)
            remainder = content[end_idx:].strip()
            return obj, remainder
        except (json.JSONDecodeError, ValueError):
            return None, content


if __name__ == "__main__":
    # ── Validación interna de content_cleaner.py (atómico standalone) ──
    print("=== Validación de content_cleaner.py ===\n")

    from contexto_zai.models import Exchange, Message, MessageRole

    cc = ContentCleaner()

    # Test 1: eliminar bloques de reasoning JSON
    texto_con_reasoning = '{"type":"reasoning","content":"pensamiento oculto"} Respuesta visible'
    limpio = cc.clean(texto_con_reasoning)
    assert "visible" in limpio
    print(f"✓ Eliminación de reasoning: OK")

    # Test 2: conservar código en bloques triple backtick
    texto_con_codigo = "Aquí el código:\n```python\nprint('hola')\n```\nFin"
    limpio2 = cc.clean(texto_con_codigo)
    assert "print('hola')" in limpio2
    print(f"✓ Conservación de código: OK")

    # Test 3: conservar rutas de archivos
    texto_con_rutas = "Modifiqué /home/z/my-project/file.py y otro/path/to/file.ts"
    limpio3 = cc.clean(texto_con_rutas)
    assert "/home/z/my-project/file.py" in limpio3
    print(f"✓ Conservación de rutas: OK")

    # Test 4: formatear exchange como markdown
    ex = Exchange(
        id=1,
        director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1788482829, content="Pregunta del director"),
        agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=1788482830, content="Respuesta del agente")],
        topic="general",
        start_timestamp=1788482829,
        end_timestamp=1788482830,
    )
    md = cc.format_exchange(ex, exchange_num=1)
    assert "Pregunta del director" in md
    assert "Respuesta del agente" in md
    print(f"✓ Formateo de exchange como markdown: OK")

    print("\n✅ content_cleaner.py: todos los tests pasaron")
