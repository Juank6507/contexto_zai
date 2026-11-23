# contexto_zai/processing/content_cleaner.py -- Limpiador de contenido: elimina reasoning JSON, conserva codigo y rutas de archivo.
"""Módulo de limpieza y formateo de contenido de mensajes.

Se encarga de eliminar bloques de razonamiento (reasoning) insertados
por algunos modelos en las respuestas del agente, y de formatear
los exchanges como markdown para su inclusión en bloques temáticos.
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
            logger.debug("Contenido vacio, nada que limpiar")
            return ""

        result = self._remove_reasoning_block(content)
        cleaned = result.strip()

        if cleaned:
            logger.debug(
                "Razonamiento eliminado: %d -> %d caracteres",
                len(content),
                len(cleaned),
            )
        else:
            logger.debug(
                "Todo el contenido era razonamiento (%d chars) -> vacío",
                len(content),
            )

        return cleaned

    def format_exchange(self, exchange: Exchange, exchange_num: int | None = None) -> str:
        """Formatea un exchange como markdown para inclusión en un bloque temático.

        Genera un bloque markdown con el número de exchange, la fecha
        del mensaje del Director, el contenido limpio del Director y
        las respuestas concatenadas del agente (también limpias).

        Formato de salida::

            ## Exchange {N} -- [{fecha}]

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
            f"## Exchange {num} -- [{datetime_str}]",
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

        Para mensajes del agente (assistant):
        1. Elimina los bloques de razonamiento (reasoning).
        2. v6.0: Parsea los tool_calls y los formatea como bloques legibles:
           - Write/Edit: muestra el archivo como bloque de código separado.
           - Bash: muestra el comando como bloque de código.
           - Read/Glob/Grep: muestra qué se consultó.
           - Task: muestra la descripción del subagente lanzado.
        Para mensajes del usuario (user) y del sistema (system), devuelve
        el contenido tal cual.

        Args:
            content: Contenido textual del mensaje.
            role: Rol del emisor del mensaje.

        Returns:
            Contenido procesado según el rol.
        """
        if role.value == "assistant":
            cleaned = self.clean(content)
            # v6.0: parsear y formatear tool_calls
            return self._parse_tool_calls(cleaned)
        return content

    # v6.0: Parseo de tool_calls --------------------------------

    def _parse_tool_calls(self, content: str) -> str:
        """v6.0: Parsea los tool_calls del contenido y los formatea como bloques legibles.

        El contenido del agente puede incluir bloques JSON como:
        - {"type": "text", "content": "Voy a hacer X"}
        - {"type": "tool_calls", "content": [...], "results": [...]}

        Este método:
        1. Extrae el texto plano (type: text).
        2. Parsea cada tool_call y lo formatea según la herramienta:
           - Write: bloque de código con nombre de archivo.
           - Edit: referencia al archivo modificado.
           - Bash: bloque de código con el comando.
           - Read/Glob/Grep: referencia a qué se consultó.
           - Task: descripción del subagente.
        3. Elimina el JSON crudo de tool_calls.
        4. Devuelve texto + bloques formateados, separados y legibles.

        Args:
            content: Contenido del agente con posibles tool_calls.

        Returns:
            Contenido procesado con tool_calls formateados.
        """
        if not content:
            return content

        # Si no hay tool_calls, devolver tal cual
        if '{"type": "tool_calls"' not in content:
            return content

        parts: list[str] = []
        remaining = content

        while remaining:
            # Buscar el inicio de un bloque JSON
            json_start = remaining.find('{"type":')

            if json_start == -1:
                # No hay más JSON, añadir el resto como texto
                text = remaining.strip()
                if text:
                    parts.append(text)
                break

            # Texto antes del JSON
            text_before = remaining[:json_start].strip()
            if text_before:
                parts.append(text_before)

            # Extraer el bloque JSON completo
            json_block, json_end = self._extract_json_block(remaining, json_start)

            if json_block:
                try:
                    data = json.loads(json_block)
                    formatted = self._format_tool_call_block(data)
                    if formatted:
                        parts.append(formatted)
                except (json.JSONDecodeError, ValueError):
                    # Si no se puede parsear, dejar el JSON como texto
                    parts.append(json_block)

            remaining = remaining[json_end:] if json_end > 0 else ""

        result = "\n\n".join(parts)
        return result if result.strip() else content

    def _extract_json_block(self, content: str, start: int) -> tuple[str, int]:
        """Extrae un bloque JSON completo desde la posición start.

        Busca el balance de llaves para encontrar el cierre del JSON.

        Returns:
            Tupla (bloque_json, posición_final).
        """
        depth = 0
        in_string = False
        escape = False
        i = start

        while i < len(content):
            char = content[i]

            if escape:
                escape = False
                i += 1
                continue

            if char == '\\' and in_string:
                escape = True
                i += 1
                continue

            if char == '"' and not escape:
                in_string = not in_string

            if not in_string:
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        # Encontramos el cierre del JSON
                        block = content[start:i + 1]
                        return block, i + 1

            i += 1

        # No se encontró cierre — devolver todo
        return content[start:], len(content)

    def _format_tool_call_block(self, data: dict) -> str:
        """Formatea un bloque JSON parseado como texto legible.

        Args:
            data: Diccionario parseado del JSON.

        Returns:
            Texto formateado con la información de la herramienta.
        """
        block_type = data.get("type", "")

        if block_type == "text":
            # Texto plano del agente
            return data.get("content", "").strip()

        if block_type == "tool_calls":
            calls = data.get("content", [])
            results = data.get("results", [])
            parts: list[str] = []

            for call in calls:
                func = call.get("function", {})
                name = func.get("name", "desconocido")
                args_str = func.get("arguments", "{}")

                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except (json.JSONDecodeError, ValueError):
                    args = {}

                # Buscar el resultado correspondiente
                call_id = call.get("id", "")
                result_content = ""
                for r in results:
                    if r.get("tool_call_id") == call_id:
                        result_content = r.get("content", "")
                        break

                formatted = self._format_single_tool(name, args, result_content)
                if formatted:
                    parts.append(formatted)

            return "\n\n".join(parts)

        # Tipo desconocido — devolver vacío
        return ""

    def _format_single_tool(self, name: str, args: dict, result: str) -> str:
        """Formatea una llamada individual a herramienta.

        Args:
            name: Nombre de la herramienta (Write, Edit, Bash, Read, etc.)
            args: Argumentos parseados de la herramienta.
            result: Resultado de la herramienta (si hay).

        Returns:
            Texto formateado según el tipo de herramienta.
        """
        if name == "Write":
            filepath = args.get("filepath", "")
            content_arg = args.get("content", "")
            filename = filepath.split("/")[-1].split("\\")[-1] if filepath else "archivo"
            # Determinar lenguaje por extensión
            ext = filename.split(".")[-1] if "." in filename else ""
            lang_map = {"py": "python", "ts": "typescript", "tsx": "tsx",
                       "js": "javascript", "md": "markdown", "json": "json",
                       "sh": "bash", "bat": "batch"}
            lang = lang_map.get(ext, "")
            # Truncar contenido si es muy largo (máximo 5000 chars)
            if len(content_arg) > 5000:
                content_arg = content_arg[:5000] + "\n... (contenido truncado, archivo completo en el workspace)"
            return f"**Archivo creado:** `{filepath}`\n\n```{lang}\n{content_arg}\n```"

        elif name == "Edit":
            filepath = args.get("filepath", "")
            return f"**Archivo modificado:** `{filepath}`"

        elif name == "MultiEdit":
            filepath = args.get("filepath", "")
            edits = args.get("edits", [])
            return f"**Archivo modificado:** `{filepath}` ({len(edits)} cambios)"

        elif name == "Bash":
            command = args.get("command", "")
            description = args.get("description", "")
            # Truncar comando si es muy largo
            if len(command) > 500:
                command = command[:500] + "..."
            header = f"**Comando:** {description}\n" if description else ""
            return f"{header}```bash\n{command}\n```"

        elif name == "Read":
            filepath = args.get("filepath", "")
            return f"**Lectura:** `{filepath}`"

        elif name == "Glob":
            pattern = args.get("pattern", "")
            path = args.get("path", "")
            return f"**Búsqueda:** `{pattern}` en `{path}`"

        elif name == "Grep":
            pattern = args.get("pattern", "")
            return f"**Búsqueda:** `{pattern}`"

        elif name == "Task":
            description = args.get("description", "")
            prompt = args.get("prompt", "")
            prompt_short = prompt[:200] + "..." if len(prompt) > 200 else prompt
            return f"**Subagente lanzado:** {description}\n\n> {prompt_short}"

        elif name == "TodoWrite":
            todos = args.get("todos", [])
            return f"**Tareas actualizadas:** {len(todos)} items"

        else:
            # Herramienta desconocida — resumen breve
            return f"**{name}:** {str(args)[:200]}"

    # -- Métodos internos (legacy) --------------------------------

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

        # Estrategia 1: JSON estricto -- todo el contenido es el bloque
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
                logger.debug("Bloque de razonamiento (JSON completo) -- contenido vacío tras limpieza")
                return ""
        except (json.JSONDecodeError, ValueError):
            pass

        # Estrategia 2: JSON de prefijo -- el bloque está al inicio
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
                logger.debug("Bloque de razonamiento (regex) -- contenido vacío tras limpieza")
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
    # Compatibilidad Windows: reconfigurar stdout/stderr a UTF-8
    import io as _io, sys as _sys
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
        if hasattr(_sys.stderr, 'buffer') and 'utf' not in (getattr(_sys.stderr, 'encoding', '') or '').lower():
            _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass
    # -- Validación interna de content_cleaner.py (atómico standalone) --
    print("=== Validacion de content_cleaner.py ===\n")

    from contexto_zai.models import Exchange, Message, MessageRole

    cc = ContentCleaner()

    # Test 1: eliminar bloques de reasoning JSON
    texto_con_reasoning = '{"type":"reasoning","content":"pensamiento oculto"} Respuesta visible'
    limpio = cc.clean(texto_con_reasoning)
    assert "visible" in limpio
    print(f"[OK] Eliminacion de reasoning: OK")

    # Test 2: conservar código en bloques triple backtick
    texto_con_codigo = "Aquí el código:\n```python\nprint('hola')\n```\nFin"
    limpio2 = cc.clean(texto_con_codigo)
    assert "print('hola')" in limpio2
    print(f"[OK] Conservacion de codigo: OK")

    # Test 3: conservar rutas de archivos (multiplataforma: usa Path)
    from pathlib import Path as _Path
    ruta_ejemplo = str(_Path.home() / "project" / "file.py")
    texto_con_rutas = f"Modifiqué {ruta_ejemplo} y otro/path/to/file.ts"
    limpio3 = cc.clean(texto_con_rutas)
    assert ruta_ejemplo in limpio3
    print(f"[OK] Conservacion de rutas: OK")

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
    print(f"[OK] Formateo de exchange como markdown: OK")

    print("\n[PASS] content_cleaner.py: todos los tests pasaron")
