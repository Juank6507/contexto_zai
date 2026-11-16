# contexto_zai/subagents/clasificador_subagent.py -- Clase base OOP abstracta para subagentes clasificadores (M7 v4.0).
"""Clase base abstracta para subagentes clasificadores (v4.0, M7).

Unifica la lógica común de los subagentes que:
- Reciben un contexto (intercambios del chat, contenido de un archivo, o
  contenido de un bloque).
- Hacen una tarea semántica sobre ese contexto (detectar decisiones,
  interpretar restricciones, hacer truncado inteligente, responder
  consultas, asignar nombres legibles, clasificar documentos).
- Devuelven una respuesta estructurada o texto plano.

Las subclases concretas se diferencian por el tipo de input, no por la
lógica de invocación del subagente. Esta clase base provee:

- `run(context)`: orquesta invocar el launcher y parsear la respuesta.
- `build_prompt(context)`: abstracto. Cada subclase construye su prompt.
- `parse_response(raw)`: abstracto. Cada subclase parsea su respuesta.

Comunicación de errores (regla v4.0):
- Si el launcher falla (timeout, TaskBridgeServer no responde, etc.),
  el error se propaga al llamador en `resultado.error` y `resultado.success=False`.
- El llamador es responsable de comunicar el error al Director, no de
  caer a fallback regex silencioso.

Atómico standalone: importa launcher, config, models. Nada más.
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
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, Optional, TypeVar

from contexto_zai.config import CLASIFICADOR_MAX_CONTEXT_TOKENS, CLASIFICADOR_TIMEOUT_SECONDS
from contexto_zai.subagents.launcher import SubagentLauncher, SubagentResponse

logger = logging.getLogger(__name__)

# Tipo genérico del contexto que recibe la subclase.
# Puede ser list[Exchange], Attachment, str (ruta de bloque), etc.
ContextT = TypeVar("ContextT")

# Tipo genérico del resultado que devuelve la subclase parseada.
# Puede ser str, list[ThemeSection], dict, etc.
ResultT = TypeVar("ResultT")


@dataclass
class ClasificadorResult(Generic[ResultT]):
    """Resultado estandarizado de un subagente clasificador.

    Attributes:
        success: True si el subagente completó sin errores.
        resultado: El resultado parseado (tipo depende de la subclase).
        raw_response: Texto crudo devuelto por el subagente (para debug).
        error: Mensaje de error si success=False. Detallado: timeout,
            TaskBridgeServer no responde, respuesta vacía, error de parseo.
        contexto_recortado: Si se truncó el contexto de entrada, indica
            cuántos tokens aproximados se pasaron al subagente.
    """

    success: bool = False
    resultado: Optional[ResultT] = None
    raw_response: str = ""
    error: str = ""
    contexto_recortado: bool = False


class ClasificadorSubagent(ABC, Generic[ContextT, ResultT]):
    """Clase base abstracta para subagentes clasificadores.

    Args:
        launcher: SubagentLauncher para invocar el Task de Z.ai.
        max_context_tokens: Límite aproximado de tokens del contexto
            que se le pasa al subagente. Default de config.py.
        timeout_seconds: Timeout para esperar la respuesta del subagente.
            Default de config.py.
        max_response_chars: Tamaño máximo de la respuesta cruda del
            subagente. Default del launcher.

    Subclases concretas deben implementar:
        - build_prompt(context) -> str
        - parse_response(raw) -> ResultT

    Usage (típico en una subclase):
        >>> class MiClasificador(ClasificadorSubagent[list[Exchange], str]):
        ...     def build_prompt(self, context):
        ...         return f"Analiza: {context}"
        ...     def parse_response(self, raw):
        ...         return raw.strip()
        >>> sub = MiClasificador(launcher=launcher)
        >>> result = sub.run(exchanges)
        >>> if result.success:
        ...     print(result.resultado)
    """

    def __init__(
        self,
        launcher: SubagentLauncher,
        max_context_tokens: int = CLASIFICADOR_MAX_CONTEXT_TOKENS,
        timeout_seconds: int = CLASIFICADOR_TIMEOUT_SECONDS,
        max_response_chars: Optional[int] = None,
    ) -> None:
        self._launcher = launcher
        self._max_context_tokens = max_context_tokens
        self._timeout_seconds = timeout_seconds
        # El launcher tiene su propio max_response_chars (default 5000).
        # Si se especifica uno distinto, se respeta pasándolo en launch().
        self._max_response_chars = max_response_chars
        logger.debug(
            "%s inicializado: max_context_tokens=%d, timeout=%ds",
            self.__class__.__name__, max_context_tokens, timeout_seconds,
        )

    # -- API pública ------------------------------------------------

    def run(self, context: ContextT) -> ClasificadorResult[ResultT]:
        """Ejecuta el subagente: construye prompt, invoca, parsea.

        Args:
            context: El contexto de entrada (tipo depende de la subclase).

        Returns:
            ClasificadorResult con el resultado parseado o el error detallado.
            El error nunca es silencioso: si algo falla, error contiene
            el motivo específico (timeout, sin respuesta, error de parseo).
        """
        # 1. Construir el prompt
        try:
            prompt, files_to_read, contexto_recortado = self.build_prompt(context)
        except Exception as e:
            err_msg = f"Error construyendo prompt: {e}"
            logger.error("%s: %s", self.__class__.__name__, err_msg)
            return ClasificadorResult(
                success=False,
                error=err_msg,
            )

        if not prompt:
            err_msg = "build_prompt devolvió un prompt vacío"
            logger.error("%s: %s", self.__class__.__name__, err_msg)
            return ClasificadorResult(
                success=False,
                error=err_msg,
            )

        # 2. Invocar el launcher
        launch_kwargs: dict[str, Any] = {
            "prompt": prompt,
            "files_to_read": files_to_read,
            "description": self._default_description(),
        }
        if self._max_response_chars is not None:
            # El launcher acepta max_response_chars en __init__, no en launch().
            # Si se quiere cambiar, hay que crear otro launcher o pasar el invoker.
            # Por ahora respetamos el max_response_chars del launcher.
            pass

        try:
            response: SubagentResponse = self._launcher.launch(**launch_kwargs)
        except Exception as e:
            err_msg = f"Excepción lanzando subagente: {e}"
            logger.error("%s: %s", self.__class__.__name__, err_msg)
            return ClasificadorResult(
                success=False,
                error=err_msg,
                contexto_recortado=contexto_recortado,
            )

        # 3. Verificar si el launcher devolvió error
        if not response.success:
            err_msg = f"Subagente falló: {response.error or 'sin detalle'}"
            logger.error("%s: %s", self.__class__.__name__, err_msg)
            return ClasificadorResult(
                success=False,
                error=err_msg,
                raw_response=response.content,
                contexto_recortado=contexto_recortado,
            )

        if not response.content or not response.content.strip():
            err_msg = "Subagente devolvió respuesta vacía"
            logger.error("%s: %s", self.__class__.__name__, err_msg)
            return ClasificadorResult(
                success=False,
                error=err_msg,
                contexto_recortado=contexto_recortado,
            )

        # 4. Parsear la respuesta
        try:
            resultado = self.parse_response(response.content)
        except Exception as e:
            err_msg = f"Error parseando respuesta del subagente: {e}"
            logger.error("%s: %s", self.__class__.__name__, err_msg)
            return ClasificadorResult(
                success=False,
                error=err_msg,
                raw_response=response.content,
                contexto_recortado=contexto_recortado,
            )

        logger.info(
            "%s completado: resultado=%s, contexto_recortado=%s",
            self.__class__.__name__,
            type(resultado).__name__,
            contexto_recortado,
        )

        return ClasificadorResult(
            success=True,
            resultado=resultado,
            raw_response=response.content,
            contexto_recortado=contexto_recortado,
        )

    # -- Métodos abstractos (las subclases los implementan) --------

    @abstractmethod
    def build_prompt(self, context: ContextT) -> tuple[str, list[str], bool]:
        """Construye el prompt para el subagente.

        Args:
            context: El contexto de entrada (intercambios, archivo, etc.).

        Returns:
            Tupla de 3 elementos:
            - prompt (str): El prompt completo para el subagente.
            - files_to_read (list[str]): Rutas de archivos que el subagente
              debe leer (puede ser [] si no lee archivos).
            - contexto_recortado (bool): True si el contexto de entrada
              se truncó para caber en max_context_tokens.
        """
        raise NotImplementedError

    @abstractmethod
    def parse_response(self, raw: str) -> ResultT:
        """Parsea la respuesta cruda del subagente en un resultado tipado.

        Args:
            raw: Texto crudo devuelto por el subagente.

        Returns:
            El resultado parseado (tipo depende de la subclase).

        Raises:
            Exception: Si la respuesta no se puede parsear.
        """
        raise NotImplementedError

    # -- Métodos protegidos (helpers compartidos) ------------------

    def _default_description(self) -> str:
        """Descripción por defecto para logging del launcher."""
        return f"{self.__class__.__name__} run"

    def _truncar_a_tokens(self, texto: str, max_tokens: int) -> tuple[str, bool]:
        """Trunca un texto a un máximo aproximado de tokens.

        Aproxima 1 token ≈ 3.5 caracteres (regla de oro del proyecto).

        Args:
            texto: Texto a truncar.
            max_tokens: Máximo aproximado de tokens.

        Returns:
            Tupla (texto_truncado, se_trunco):
            - texto_truncado: El texto, posiblemente truncado.
            - se_trunco: True si se aplicó truncado.
        """
        max_chars = int(max_tokens * 3.5)
        if len(texto) <= max_chars:
            return texto, False
        return texto[:max_chars], True

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
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

    # -- Validación interna de clasificador_subagent.py --
    print("=== Validacion de clasificador_subagent.py ===\n")

    # Test 1: la clase base es abstracta, no se puede instanciar
    try:
        ClasificadorSubagent(launcher=None)  # type: ignore
        assert False, "Debería haber lanzado TypeError (clase abstracta)"
    except TypeError as e:
        assert "abstract" in str(e).lower() or "instantiate" in str(e).lower()
        print(f"[OK] Clase base abstracta: no se puede instanciar directamente")

    # Test 2: subclase concreta mínima funciona
    class SubclaseTest(ClasificadorSubagent[str, str]):
        """Subclase de prueba: recibe un string, devuelve un string."""

        def build_prompt(self, context: str) -> tuple[str, list[str], bool]:
            prompt_text, recortado = self._truncar_a_tokens(
                f"Analiza esto: {context}",
                self._max_context_tokens,
            )
            return prompt_text, [], recortado

        def parse_response(self, raw: str) -> str:
            return raw.strip()

    # Mock invoker: simula el Task tool
    def mock_invoker(prompt: str) -> str:
        return "Respuesta simulada del subagente"

    launcher = SubagentLauncher(task_invoker=mock_invoker)
    sub = SubclaseTest(launcher=launcher)

    result = sub.run("contexto de prueba")
    assert result.success, f"Debería ser success, error={result.error}"
    assert result.resultado == "Respuesta simulada del subagente"
    assert result.contexto_recortado is False
    print(f"[OK] Subclase concreta: run() devuelve resultado correcto")

    # Test 3: error del launcher se propaga (no silencioso)
    def mock_invoker_falla(prompt: str) -> str:
        raise RuntimeError("TaskBridgeServer no responde")

    launcher_falla = SubagentLauncher(task_invoker=mock_invoker_falla)
    sub_falla = SubclaseTest(launcher=launcher_falla)

    result_falla = sub_falla.run("contexto")
    assert not result_falla.success
    assert "TaskBridgeServer" in result_falla.error or "Task invoker error" in result_falla.error
    print(f"[OK] Error del launcher se propaga: {result_falla.error[:60]}...")

    # Test 4: respuesta vacía del subagente se reporta como error
    def mock_invoker_vacio(prompt: str) -> str:
        return ""

    launcher_vacio = SubagentLauncher(task_invoker=mock_invoker_vacio)
    sub_vacio = SubclaseTest(launcher=launcher_vacio)

    result_vacio = sub_vacio.run("contexto")
    assert not result_vacio.success
    assert "vacía" in result_vacio.error.lower() or "vacia" in result_vacio.error.lower()
    print(f"[OK] Respuesta vacía reportada como error")

    # Test 5: error de parseo se reporta con detalle
    class SubclaseParseoFalla(ClasificadorSubagent[str, str]):
        def build_prompt(self, context: str) -> tuple[str, list[str], bool]:
            return f"Analiza: {context}", [], False

        def parse_response(self, raw: str) -> str:
            raise ValueError("Formato inesperado en respuesta")

    launcher_ok = SubagentLauncher(task_invoker=mock_invoker)
    sub_parseo = SubclaseParseoFalla(launcher=launcher_ok)

    result_parseo = sub_parseo.run("contexto")
    assert not result_parseo.success
    assert "parseando" in result_parseo.error.lower()
    assert result_parseo.raw_response == "Respuesta simulada del subagente"
    print(f"[OK] Error de parseo reportado con raw_response preservado")

    # Test 6: _truncar_a_tokens funciona
    sub_truncar = SubclaseTest(launcher=launcher, max_context_tokens=10)
    texto_largo = "x" * 1000
    truncado, se_trunco = sub_truncar._truncar_a_tokens(texto_largo, 10)
    assert se_trunco is True
    assert len(truncado) == int(10 * 3.5)
    print(f"[OK] _truncar_a_tokens: trunca a {len(truncado)} chars (10 tokens)")

    # Test 7: _truncar_a_tokens no trunca si no hace falta
    texto_corto = "corto"
    no_truncado, no_se_trunco = sub_truncar._truncar_a_tokens(texto_corto, 10)
    assert no_se_trunco is False
    assert no_truncado == texto_corto
    print(f"[OK] _truncar_a_tokens: no trunca si el texto es corto")

    # Test 8: contexto_recortado se propaga al resultado
    sub_recorte = SubclaseTest(launcher=launcher, max_context_tokens=5)
    result_recorte = sub_recorte.run("x" * 500)
    assert result_recorte.contexto_recortado is True
    print(f"[OK] contexto_recortado se propaga al resultado")

    # Test 9: build_prompt que lanza excepción se reporta como error
    class SubclaseBuildFalla(ClasificadorSubagent[str, str]):
        def build_prompt(self, context: str) -> tuple[str, list[str], bool]:
            raise RuntimeError("Error construyendo prompt")

        def parse_response(self, raw: str) -> str:
            return raw

    sub_build = SubclaseBuildFalla(launcher=launcher)
    result_build = sub_build.run("contexto")
    assert not result_build.success
    assert "construyendo prompt" in result_build.error
    print(f"[OK] Error en build_prompt se reporta como error")

    # Test 10: __repr__ contiene el nombre de la subclase
    repr_str = repr(sub)
    assert "SubclaseTest" in repr_str
    assert "max_context_tokens" in repr_str
    print(f"[OK] __repr__: {repr_str}")

    print("\n[PASS] clasificador_subagent.py: todos los tests pasaron")
