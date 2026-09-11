# contexto_zai/subagents/intercambios_clasificador_subagent.py -- Subagente clasificador que recibe intercambios del chat (M7 v4.0).
"""Subagente clasificador que recibe intercambios del chat (v4.0, M7).

Hereda de ClasificadorSubagent. Su input es una lista de Exchange (los
intercambios del chat entre el Director y el agente). Se diferencia de
DocumentoIndexerSubagent (que recibe archivos/links) solo en el input.

Se usa en:
- M3 D4: interpretar restricciones activas del último tema.
- M3 A1: truncado inteligente del tema activo (resumir contenido truncado).
- M4:    detectar decisiones reales con alcance.
- M7:    asignar nombre legible a un subtema.
- M8:    responder consulta sobre un bloque (intercambios del bloque).

Para no crear 5 clases paralelas, esta subclase soporta varios modos
de operación. Cada modo tiene su propio prompt y su propio parser.
El modo se selecciona en __init__ con el parámetro `modo`.

Comunicación de errores (regla v4.0):
- Si el subagente falla, el error se propaga al llamador en `resultado.error`
  y `resultado.success=False`. El llamador debe comunicar el error al Director.

Atómico standalone: importa clasificador_subagent, launcher, models, config.
Auto-tests en __main__ usando mocks del launcher.
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
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from contexto_zai.config import CLASIFICADOR_MAX_CONTEXT_TOKENS, CLASIFICADOR_TIMEOUT_SECONDS
from contexto_zai.subagents.clasificador_subagent import (
    ClasificadorResult,
    ClasificadorSubagent,
)
from contexto_zai.subagents.launcher import SubagentLauncher

if True:  # TYPE_CHECKING equivalente para runtime
    from contexto_zai.models import Exchange

logger = logging.getLogger(__name__)


# ── Modos de operación ───────────────────────────────────────────


class ModoClasificador(str, Enum):
    """Modos de operación del IntercambiosClasificadorSubagent.

    Cada modo define:
    - Qué prompt se construye en build_prompt().
    - Qué parser se aplica en parse_response().
    - Límites de contexto específicos (si los hay).
    """

    # M3 D4: interpretar restricciones activas del último tema.
    # Devuelve texto plano con la lista de restricciones.
    RESTRICCIONES_TEMA = "restricciones_tema"

    # M3 A1: resumir contenido truncado del tema activo (truncado inteligente).
    # Devuelve texto plano con el resumen del contenido que se truncó.
    RESUMEN_TRUNCADO = "resumen_truncado"

    # M4: detectar decisiones reales con alcance.
    # Devuelve lista de Decision detectadas (descarta aprobaciones genéricas).
    DECISIONES = "decisiones"

    # M7: asignar nombre legible a un subtema.
    # Devuelve string con nombre snake_case de máximo 5 palabras.
    NOMBRE_LEGIBLE = "nombre_legible"

    # M8: responder consulta sobre un bloque.
    # Devuelve texto plano con respuesta completa y abarcadora.
    CONSULTA_BLOQUE = "consulta_bloque"


# ── Resultados tipados por modo ──────────────────────────────────


@dataclass
class Decision:
    """Una decisión real detectada por el subagente (M4).

    Attributes:
        descripcion: Qué decidió el Director.
        alcance: A qué tarea se refiere, qué incluye, qué no incluye.
        razon: Por qué se detectó como decisión (no aprobación genérica).
        exchange_id: ID del intercambio donde se detectó.
        tema: Tema del intercambio donde se detectó.
    """

    descripcion: str = ""
    alcance: str = ""
    razon: str = ""
    exchange_id: int = 0
    tema: str = ""


@dataclass
class Restriccion:
    """Una restricción o preferencia activa del Director (M3 D4).

    Attributes:
        texto: Texto de la restricción.
        alcance: A qué tema/tarea aplica.
    """

    texto: str = ""
    alcance: str = ""


# ── Subclase concreta ────────────────────────────────────────────


class IntercambiosClasificadorSubagent(
    ClasificadorSubagent["list[Exchange]", object]
):
    """Subagente clasificador que recibe intercambios del chat.

    Args:
        launcher: SubagentLauncher para invocar el Task de Z.ai.
        modo: Modo de operación (ver ModoClasificador). Define el prompt
            y el parser que se aplican.
        max_context_tokens: Límite aproximado de tokens del contexto.
        timeout_seconds: Timeout para esperar la respuesta del subagente.
        pregunta: Para modo CONSULTA_BLOQUE, la pregunta concreta del
            agente sobre el bloque.

    Usage:
        >>> sub = IntercambiosClasificadorSubagent(
        ...     launcher=launcher,
        ...     modo=ModoClasificador.DECISIONES,
        ... )
        >>> result = sub.run(exchanges)
        >>> if result.success:
        ...     for d in result.resultado:
        ...         print(d.descripcion, d.alcance)
    """

    def __init__(
        self,
        launcher: SubagentLauncher,
        modo: ModoClasificador = ModoClasificador.CONSULTA_BLOQUE,
        max_context_tokens: int = CLASIFICADOR_MAX_CONTEXT_TOKENS,
        timeout_seconds: int = CLASIFICADOR_TIMEOUT_SECONDS,
        pregunta: Optional[str] = None,
    ) -> None:
        super().__init__(
            launcher=launcher,
            max_context_tokens=max_context_tokens,
            timeout_seconds=timeout_seconds,
        )
        self._modo = modo
        self._pregunta = pregunta
        logger.debug(
            "IntercambiosClasificadorSubagent modo=%s, pregunta=%s",
            modo.value, bool(pregunta),
        )

    # -- API pública ------------------------------------------------

    @property
    def modo(self) -> ModoClasificador:
        return self._modo

    # -- Implementación de métodos abstractos ----------------------

    def build_prompt(
        self,
        context: "list[Exchange]",
    ) -> tuple[str, list[str], bool]:
        """Construye el prompt según el modo de operación.

        Args:
            context: Lista de intercambios del chat.

        Returns:
            Tupla (prompt, files_to_read, contexto_recortado).
        """
        # Construir el texto de contexto (común a todos los modos)
        context_text, contexto_recortado = self._build_context_text(context)

        # Despachar al prompt específico del modo
        if self._modo == ModoClasificador.RESTRICCIONES_TEMA:
            prompt = self._prompt_restricciones(context_text)
        elif self._modo == ModoClasificador.RESUMEN_TRUNCADO:
            prompt = self._prompt_resumen_truncado(context_text)
        elif self._modo == ModoClasificador.DECISIONES:
            prompt = self._prompt_decisiones(context_text)
        elif self._modo == ModoClasificador.NOMBRE_LEGIBLE:
            prompt = self._prompt_nombre_legible(context_text)
        elif self._modo == ModoClasificador.CONSULTA_BLOQUE:
            prompt = self._prompt_consulta_bloque(context_text)
        else:
            # No debería llegar aquí (Enum cubre todos los casos)
            raise ValueError(f"Modo no soportado: {self._modo}")

        # Los intercambios no requieren archivos externos: el contexto va
        # embebido en el prompt. El subagente no necesita leer archivos.
        return prompt, [], contexto_recortado

    def parse_response(self, raw: str) -> object:
        """Parsea la respuesta según el modo de operación.

        Args:
            raw: Texto crudo devuelto por el subagente.

        Returns:
            - RESTRICCIONES_TEMA: list[Restriccion]
            - RESUMEN_TRUNCADO: str
            - DECISIONES: list[Decision]
            - NOMBRE_LEGIBLE: str
            - CONSULTA_BLOQUE: str
        """
        if self._modo == ModoClasificador.RESTRICCIONES_TEMA:
            return self._parse_restricciones(raw)
        elif self._modo == ModoClasificador.RESUMEN_TRUNCADO:
            return raw.strip()
        elif self._modo == ModoClasificador.DECISIONES:
            return self._parse_decisiones(raw)
        elif self._modo == ModoClasificador.NOMBRE_LEGIBLE:
            return self._parse_nombre_legible(raw)
        elif self._modo == ModoClasificador.CONSULTA_BLOQUE:
            return raw.strip()
        else:
            raise ValueError(f"Modo no soportado: {self._modo}")

    # -- Construcción del contexto común ---------------------------

    def _build_context_text(
        self,
        exchanges: "list[Exchange]",
    ) -> tuple[str, bool]:
        """Construye el texto de contexto con los intercambios.

        Formato: para cada intercambio, muestra el número, timestamp,
        tema, mensaje del Director y respuesta del agente. Trunca al
        límite de tokens configurado.

        Returns:
            Tupla (texto, se_trunco).
        """
        lines: list[str] = []
        for ex in exchanges:
            lines.append(f"--- Exchange {ex.id} [{ex.datetime_str}] (tema: {ex.topic}) ---")
            lines.append(f"Director: {ex.director_msg.content}")
            if ex.agent_msgs:
                last_msg = ex.agent_msgs[-1]
                content = last_msg.content
                # Truncar mensajes individuales muy largos para que entren más intercambios
                if len(content) > 2000:
                    content = content[:2000] + "..."
                lines.append(f"Agente: {content}")
            lines.append("")

        full_text = "\n".join(lines)
        return self._truncar_a_tokens(full_text, self._max_context_tokens)

    # -- Prompts por modo ------------------------------------------

    def _prompt_restricciones(self, context_text: str) -> str:
        """Prompt para M3 D4: interpretar restricciones del último tema."""
        return f"""Eres un subagente que analiza las restricciones y preferencias activas del Director
sobre el último tema trabajado. Tu tarea es extraer las restricciones reales, no duplicar
lo que ya está en otros archivos.

## Contexto de los intercambios

{context_text}

## Tu tarea

1. Identifica las restricciones y preferencias explícitas del Director en estos intercambios.
2. Solo documenta restricciones reales: "no uses X", "usa Y obligatoriamente", "siempre Z",
   "prohibido W", "necesito que sea de esta forma".
3. NO documents aprobaciones genéricas ("Correcto", "OK") ni preguntas del Director.
4. Para cada restricción, indica el alcance: a qué tema o tarea aplica.

## Formato de respuesta EXACTO

Devuelve una lista de restricciones. Si no hay restricciones, responde exactamente:

SIN_RESTRICCIONES

Si hay restricciones, devuélvelas así (una por bloque):

RESTRICCION: <texto de la restricción>
ALCANCE: <a qué tema o tarea aplica>

RESTRICCION: <texto de otra restricción>
ALCANCE: <a qué tema o tarea aplica>

Reglas:
- Máximo 8 restricciones.
- Sé conciso pero específico.
- Si una restricción aplica a varios temas, indícalo en ALCANCE.

Respuesta:"""

    def _prompt_resumen_truncado(self, context_text: str) -> str:
        """Prompt para M3 A1: resumir contenido truncado (truncado inteligente)."""
        return f"""Eres un subagente que resume contenido truncado de un tema activo. El agente principal
tiene las primeras ~16K tokens del tema en texto literal, pero se truncó el resto.
Tu tarea es resumir el contenido truncado para que el agente no pierda el hilo.

## Contenido truncado a resumir

{context_text}

## Tu tarea

1. Identifica la información operativa del contenido truncado: decisiones tomadas,
   archivos modificados, errores encontrados, tareas pendientes.
2. Resume en máximo 4K tokens (no más de 14.000 caracteres).
3. Conserva rutas de archivos, nombres de funciones, mensajes de error literales.
4. No agregues interpretación: solo extrae lo que está en el contenido.

## Formato de respuesta

Devuelve el resumen en texto plano (no markdown), con secciones separadas por
líneas en blanco. Sin prefijos como "RESUMEN:". Solo el contenido del resumen.

Respuesta:"""

    def _prompt_decisiones(self, context_text: str) -> str:
        """Prompt para M4: detectar decisiones reales con alcance."""
        return f"""Eres un subagente que detecta decisiones reales del Director en intercambios de un chat.
Tu objetivo es distinguir decisiones reales de aprobaciones genéricas, y para cada decisión
real, capturar el alcance en el contexto del trabajo actual.

## Contexto de los intercambios

{context_text}

## Qué es una decisión real (SÍ documentar)

- Directivas operativas: "Quiero que reinicies como agente nuevo", "Necesito que
  actualices la implementación", "Vamos a usar 3 niveles de subagentes".
- Decisiones de arquitectura: "Usaremos OOP para los subagentes", "Eliminamos
  el modo light sin subagentes".
- Autorizaciones específicas: "A ejecutar este PLAN", "Correcto a implementar"
  (cuando "Correcto" aprueba una propuesta concreta previa).

## Qué NO es una decisión (descartar)

- Aprobaciones genéricas: "Correcto", "OK", "Bien", "Está bien" sin contexto.
- Preguntas del Director: "¿Puedes hacerlo?".
- Continuaciones: "Continúa con lo Milestone V2 a..." (no es decisión, es autorización
  de continuar; solo documentar si la continuación autoriza algo nuevo).
- Confirmaciones de recepción: "Entendido", "Recibido".

## Formato de respuesta EXACTO

Si no hay decisiones reales, responde exactamente:

SIN_DECISIONES

Si hay decisiones, devuélvelas así (una por bloque):

DECISION: <descripción corta de qué se decidió>
ALCANCE: <a qué tarea se refiere, qué incluye, qué no incluye>
RAZON: <por qué esto es decisión real y no aprobación genérica>
EXCHANGE: <id del intercambio donde se detectó>
TEMA: <tema del intercambio donde se detectó>

(Repetir bloque por cada decisión real detectada)

Reglas:
- Máximo 15 decisiones por lote.
- El ALCANCE debe ser específico: "aplica a la implementación del EstadoGenerator,
  incluye eliminar D2 y D3, no incluye tocar A2-A4".
- Si una decisión se detecta en varios intercambios, documentala una sola vez con
  el exchange_id del primer intercambio donde aparece.

Respuesta:"""

    def _prompt_nombre_legible(self, context_text: str) -> str:
        """Prompt para M7: asignar nombre legible a un subtema."""
        return f"""Eres un subagente que asigna nombres legibles a subtemas de un chat. El sistema de
recuperación de contexto necesita nombres snake_case legibles por humanos para que
el agente pueda encontrar temas rápidamente.

## Contexto del subtema

{context_text}

## Tu tarea

1. Identifica el tema principal de los intercambios mostrados.
2. Asigna un nombre en snake_case que sea legible y específico.
3. El nombre debe reflejar el contenido, no la fecha o un sufijo numérico.

## Ejemplos

- Si los intercambios tratan sobre obtener el JWT de chat.z.ai:
  NOMBRE: autenticacion_jwt
- Si tratan sobre subdividir temas grandes en subtemas:
  NOMBRE: subdivision_temas
- Si tratan sobre la spec de recuperación de contexto v3.6:
  NOMBRE: spec_recuperacion_v3_6

## Formato de respuesta EXACTO

Devuelve solo el nombre, sin prefijo NOMBRE:, sin explicaciones:

autenticacion_jwt

Reglas:
- Máximo 5 palabras.
- snake_case (sin espacios, sin acentos, solo minúsculas y guiones bajos).
- Si el contenido es ambiguo, elige el nombre más representativo.

Respuesta:"""

    def _prompt_consulta_bloque(self, context_text: str) -> str:
        """Prompt para M8: responder consulta sobre un bloque."""
        pregunta = self._pregunta or "(sin pregunta específica)"
        return f"""Eres un subagente que responde a una consulta específica del agente principal sobre
un bloque temático. Tu objetivo es entregar una respuesta completa y abarcadora de
lo que se preguntó, no un resumen cortado.

## Bloque temático (intercambios)

{context_text}

## Pregunta del agente principal

{pregunta}

## Tu tarea

1. Lee los intercambios del bloque buscando información relevante a la pregunta.
2. Si encuentras información, respóndela de forma completa y abarcadora.
3. Si la pregunta abarca varios aspectos, cubre todos.
4. Si no encuentras nada relevante, responde exactamente:

   No hay información relevante en este bloque.

5. No inventes información. Solo reporta lo que encuentras en los intercambios.
6. Conserva rutas de archivos, nombres de funciones, decisiones literales cuando aplique.

## Formato de respuesta

Texto plano (no markdown con headers), respuesta directa a la pregunta.
Sin prefijos como "RESPUESTA:". Solo el contenido de la respuesta.

Respuesta:"""

    # -- Parsers por modo ------------------------------------------

    def _parse_restricciones(self, raw: str) -> list[Restriccion]:
        """Parser para M3 D4: lista de Restriccion."""
        raw = raw.strip()
        if raw.upper().startswith("SIN_RESTRICCIONES"):
            return []

        # Patrón: RESTRICCION: <texto>\nALCANCE: <texto>
        pattern = re.compile(
            r"RESTRICCION:\s*(.+?)\s*\n\s*ALCANCE:\s*(.+?)(?=\n\s*RESTRICCION:|\Z)",
            re.DOTALL,
        )
        restricciones: list[Restriccion] = []
        for match in pattern.finditer(raw):
            texto = match.group(1).strip()
            alcance = match.group(2).strip()
            if texto:
                restricciones.append(Restriccion(texto=texto, alcance=alcance))

        return restricciones

    def _parse_decisiones(self, raw: str) -> list[Decision]:
        """Parser para M4: lista de Decision."""
        raw = raw.strip()
        if raw.upper().startswith("SIN_DECISIONES"):
            return []

        # Patrón: DECISION: <desc>\nALCANCE: <alc>\nRAZON: <rz>\nEXCHANGE: <id>\nTEMA: <tema>
        pattern = re.compile(
            r"DECISION:\s*(.+?)\s*\n\s*ALCANCE:\s*(.+?)\s*\n\s*RAZON:\s*(.+?)\s*\n\s*EXCHANGE:\s*(\d+)\s*\n\s*TEMA:\s*(.+?)(?=\n\s*DECISION:|\Z)",
            re.DOTALL,
        )
        decisiones: list[Decision] = []
        for match in pattern.finditer(raw):
            decisiones.append(Decision(
                descripcion=match.group(1).strip(),
                alcance=match.group(2).strip(),
                razon=match.group(3).strip(),
                exchange_id=int(match.group(4).strip() or 0),
                tema=match.group(5).strip(),
            ))

        return decisiones

    def _parse_nombre_legible(self, raw: str) -> str:
        """Parser para M7: string con nombre snake_case."""
        nombre = raw.strip()
        # Si el subagente incluyó "NOMBRE:" prefijo, eliminarlo
        if nombre.upper().startswith("NOMBRE:"):
            nombre = nombre[len("NOMBRE:"):].strip()
        # Sanitizar a snake_case
        return self._sanitize_snake_case(nombre)

    @staticmethod
    def _sanitize_snake_case(name: str) -> str:
        """Convierte un nombre a snake_case válido."""
        if not name:
            return "tema"
        # Normalizar acentos
        normalized = unicodedata.normalize("NFKD", name)
        ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
        ascii_str = ascii_str.lower()
        # Reemplazar todo lo que no sea alfanumérico por _
        sanitized = re.sub(r"[^a-z0-9]+", "_", ascii_str)
        return sanitized.strip("_") or "tema"

    def _default_description(self) -> str:
        """Descripción para logging según el modo."""
        return f"IntercambiosClasificadorSubagent modo={self._modo.value}"

    def __repr__(self) -> str:
        return (
            f"IntercambiosClasificadorSubagent(modo={self._modo.value}, "
            f"max_context_tokens={self._max_context_tokens}, "
            f"timeout={self._timeout_seconds}s)"
        )


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

    # -- Validación interna de intercambios_clasificador_subagent.py --
    print("=== Validacion de intercambios_clasificador_subagent.py ===\n")

    from contexto_zai.models import Exchange, Message, MessageRole

    # Mock invoker por defecto: devuelve respuesta simulada
    def mock_invoker_default(prompt: str) -> str:
        return "Respuesta simulada"

    launcher = SubagentLauncher(task_invoker=mock_invoker_default)

    # Intercambios de prueba
    exchanges = [
        Exchange(
            id=1,
            director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="Quiero que uses OOP para los subagentes"),
            agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=2, content="Entendido. Usaré OOP.")],
            topic="arquitectura_subagentes",
            start_timestamp=1,
            end_timestamp=2,
        ),
        Exchange(
            id=2,
            director_msg=Message(seq=3, role=MessageRole.USER, timestamp=3, content="Correcto"),
            agent_msgs=[Message(seq=4, role=MessageRole.ASSISTANT, timestamp=4, content="Implementando..."),
                       Message(seq=5, role=MessageRole.ASSISTANT, timestamp=5, content="Hecho.")],
            topic="arquitectura_subagentes",
            start_timestamp=3,
            end_timestamp=5,
        ),
    ]

    # Test 1: modo DECISIONES detecta decisión real y descarta aprobación
    def mock_invoker_decisiones(prompt: str) -> str:
        # Simula que el subagente detecta solo 1 decisión (la de OOP),
        # no la aprobación "Correcto"
        return """DECISION: Usar OOP para los subagentes
ALCANCE: Aplica a la implementación de la clase base ClasificadorSubagent y sus subclases. Incluye crear la clase base abstracta, no incluye tocar el SubagentLauncher.
RAZON: Es directiva operativa explícita del Director, no aprobación genérica.
EXCHANGE: 1
TEMA: arquitectura_subagentes"""

    launcher_dec = SubagentLauncher(task_invoker=mock_invoker_decisiones)
    sub_dec = IntercambiosClasificadorSubagent(
        launcher=launcher_dec,
        modo=ModoClasificador.DECISIONES,
    )
    result_dec = sub_dec.run(exchanges)
    assert result_dec.success, f"Error: {result_dec.error}"
    assert isinstance(result_dec.resultado, list)
    assert len(result_dec.resultado) == 1
    dec = result_dec.resultado[0]
    assert dec.descripcion == "Usar OOP para los subagentes"
    assert "ClasificadorSubagent" in dec.alcance
    assert dec.exchange_id == 1
    print(f"[OK] Modo DECISIONES: detecta 1 decisión real con alcance")

    # Test 2: modo DECISIONES con SIN_DECISIONES
    def mock_invoker_sin_dec(prompt: str) -> str:
        return "SIN_DECISIONES"

    launcher_sin = SubagentLauncher(task_invoker=mock_invoker_sin_dec)
    sub_sin = IntercambiosClasificadorSubagent(
        launcher=launcher_sin,
        modo=ModoClasificador.DECISIONES,
    )
    result_sin = sub_sin.run(exchanges)
    assert result_sin.success
    assert result_sin.resultado == []
    print(f"[OK] Modo DECISIONES: SIN_DECISIONES devuelve lista vacía")

    # Test 3: modo RESTRICCIONES_TEMA
    def mock_invoker_restricciones(prompt: str) -> str:
        return """RESTRICCION: Usar siempre OOP, no procedural
ALCANCE: Aplica a todos los subagentes nuevos.

RESTRICCION: No crear clases paralelas con fallback regex
ALCANCE: Aplica a EstadoGenerator y DecisionesGenerator."""

    launcher_rest = SubagentLauncher(task_invoker=mock_invoker_restricciones)
    sub_rest = IntercambiosClasificadorSubagent(
        launcher=launcher_rest,
        modo=ModoClasificador.RESTRICCIONES_TEMA,
    )
    result_rest = sub_rest.run(exchanges)
    assert result_rest.success
    assert isinstance(result_rest.resultado, list)
    assert len(result_rest.resultado) == 2
    assert "OOP" in result_rest.resultado[0].texto
    assert "EstadoGenerator" in result_rest.resultado[1].alcance
    print(f"[OK] Modo RESTRICCIONES_TEMA: 2 restricciones con alcance")

    # Test 4: modo RESTRICCIONES_TEMA con SIN_RESTRICCIONES
    def mock_invoker_sin_rest(prompt: str) -> str:
        return "SIN_RESTRICCIONES"

    launcher_sr = SubagentLauncher(task_invoker=mock_invoker_sin_rest)
    sub_sr = IntercambiosClasificadorSubagent(
        launcher=launcher_sr,
        modo=ModoClasificador.RESTRICCIONES_TEMA,
    )
    result_sr = sub_sr.run(exchanges)
    assert result_sr.success
    assert result_sr.resultado == []
    print(f"[OK] Modo RESTRICCIONES_TEMA: SIN_RESTRICCIONES devuelve lista vacía")

    # Test 5: modo RESUMEN_TRUNCADO devuelve texto plano
    def mock_invoker_resumen(prompt: str) -> str:
        return "Resumen del contenido truncado. Se decidió X, se modificó Y."

    launcher_res = SubagentLauncher(task_invoker=mock_invoker_resumen)
    sub_res = IntercambiosClasificadorSubagent(
        launcher=launcher_res,
        modo=ModoClasificador.RESUMEN_TRUNCADO,
    )
    result_res = sub_res.run(exchanges)
    assert result_res.success
    assert isinstance(result_res.resultado, str)
    assert "Resumen del contenido" in result_res.resultado
    print(f"[OK] Modo RESUMEN_TRUNCADO: devuelve texto plano")

    # Test 6: modo NOMBRE_LEGIBLE devuelve snake_case
    def mock_invoker_nombre(prompt: str) -> str:
        return "autenticacion_jwt"

    launcher_nom = SubagentLauncher(task_invoker=mock_invoker_nombre)
    sub_nom = IntercambiosClasificadorSubagent(
        launcher=launcher_nom,
        modo=ModoClasificador.NOMBRE_LEGIBLE,
        max_context_tokens=2000,  # más chico para M7
    )
    result_nom = sub_nom.run(exchanges)
    assert result_nom.success
    assert result_nom.resultado == "autenticacion_jwt"
    print(f"[OK] Modo NOMBRE_LEGIBLE: devuelve 'autenticacion_jwt'")

    # Test 7: modo NOMBRE_LEGIBLE con prefijo NOMBRE: se sanitiza
    def mock_invoker_nombre_prefijo(prompt: str) -> str:
        return "NOMBRE: Autenticación JWT v3.6"

    launcher_np = SubagentLauncher(task_invoker=mock_invoker_nombre_prefijo)
    sub_np = IntercambiosClasificadorSubagent(
        launcher=launcher_np,
        modo=ModoClasificador.NOMBRE_LEGIBLE,
    )
    result_np = sub_np.run(exchanges)
    assert result_np.success
    assert result_np.resultado == "autenticacion_jwt_v3_6"
    print(f"[OK] Modo NOMBRE_LEGIBLE: sanitiza a 'autenticacion_jwt_v3_6'")

    # Test 8: modo CONSULTA_BLOQUE con pregunta
    def mock_invoker_consulta(prompt: str) -> str:
        return "El Director decidió usar OOP para los subagentes en el exchange 1."

    launcher_con = SubagentLauncher(task_invoker=mock_invoker_consulta)
    sub_con = IntercambiosClasificadorSubagent(
        launcher=launcher_con,
        modo=ModoClasificador.CONSULTA_BLOQUE,
        pregunta="¿Qué se decidió sobre los subagentes?",
    )
    result_con = sub_con.run(exchanges)
    assert result_con.success
    assert "OOP" in result_con.resultado
    print(f"[OK] Modo CONSULTA_BLOQUE: responde con la decisión encontrada")

    # Test 9: modo CONSULTA_BLOQUE sin información relevante
    def mock_invoker_no_info(prompt: str) -> str:
        return "No hay información relevante en este bloque."

    launcher_ni = SubagentLauncher(task_invoker=mock_invoker_no_info)
    sub_ni = IntercambiosClasificadorSubagent(
        launcher=launcher_ni,
        modo=ModoClasificador.CONSULTA_BLOQUE,
        pregunta="¿algo sobre X?",
    )
    result_ni = sub_ni.run(exchanges)
    assert result_ni.success
    assert "No hay información" in result_ni.resultado
    print(f"[OK] Modo CONSULTA_BLOQUE: reporta sin información")

    # Test 10: error del launcher se propaga
    def mock_invoker_falla(prompt: str) -> str:
        raise RuntimeError("TaskBridgeServer no responde")

    launcher_fail = SubagentLauncher(task_invoker=mock_invoker_falla)
    sub_fail = IntercambiosClasificadorSubagent(
        launcher=launcher_fail,
        modo=ModoClasificador.DECISIONES,
    )
    result_fail = sub_fail.run(exchanges)
    assert not result_fail.success
    assert "TaskBridgeServer" in result_fail.error or "Task invoker error" in result_fail.error
    print(f"[OK] Error del launcher se propaga: {result_fail.error[:60]}...")

    # Test 11: contexto_recortado se detecta cuando hay muchos intercambios
    many_exchanges = [ex.model_copy(update={"id": i}) for i, ex in enumerate(exchanges * 10, start=1)]
    sub_rec = IntercambiosClasificadorSubagent(
        launcher=launcher,
        modo=ModoClasificador.CONSULTA_BLOQUE,
        max_context_tokens=100,  # muy chico para forzar recorte
        pregunta="test",
    )
    result_rec = sub_rec.run(many_exchanges)
    assert result_rec.contexto_recortado is True
    print(f"[OK] contexto_recortado=True cuando el contexto excede el límite")

    # Test 12: __repr__ muestra el modo
    repr_str = repr(sub_dec)
    assert "modo=decisiones" in repr_str
    print(f"[OK] __repr__: {repr_str}")

    print("\n[PASS] intercambios_clasificador_subagent.py: todos los tests pasaron")
