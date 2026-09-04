# contexto_zai/config.py -- Constantes y configuracion del sistema (limites, rutas, reglas tematicas).
"""Constantes y configuración del sistema Contexto Z.ai.

Centraliza todos los parámetros del spec de recuperación de contexto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# -- Rutas por defecto ----------------------------------------------

DEFAULT_OUTPUT_DIR = Path("contexto_recuperacion")
DEFAULT_MESSAGES_FILE = Path("chat_messages.json")

# -- Límites de tokens (Sección 4 del spec) -------------------------

@dataclass(frozen=True)
class TokenLimits:
    """Límites de tokens definidos en el spec.

    Atributos:
        ventana_agente: Ventana total del agente (128K).
        margen_seguridad: Porcentaje reservado (20%).
        capacidad_util: Ventana - margen.
        max_tokens_bloque: Máximo por bloque temático.
        max_tokens_estado: Máximo para 00_estado_actual.md.
        max_tokens_indice: Máximo para 01_indice_recuperacion.md.
        max_tokens_decisiones: Máximo para 02_decisiones_clave.md.
        carga_principal_max: Suma de los 3 archivos de carga rápida.
        conversion_rate: Chars por token (promedio es-código).
    """

    ventana_agente: int = 128_000
    margen_seguridad_pct: float = 0.20
    max_tokens_bloque: int = 70_000
    max_tokens_estado: int = 20_000
    max_tokens_indice: int = 8_000
    max_tokens_decisiones: int = 12_000
    carga_principal_max: int = 40_000
    conversion_rate: float = 3.5
    umbral_compresion_pct: float = 0.90

    @property
    def margen_seguridad(self) -> int:
        return int(self.ventana_agente * self.margen_seguridad_pct)

    @property
    def capacidad_util(self) -> int:
        return self.ventana_agente - self.margen_seguridad

    @property
    def max_chars_estado(self) -> int:
        return int(self.max_tokens_estado * self.conversion_rate)

    @property
    def max_chars_indice(self) -> int:
        return int(self.max_tokens_indice * self.conversion_rate)

    @property
    def max_chars_decisiones(self) -> int:
        return int(self.max_tokens_decisiones * self.conversion_rate)

    @property
    def max_chars_bloque(self) -> int:
        return int(self.max_tokens_bloque * self.conversion_rate)

    @property
    def umbral_disparo_tokens(self) -> int:
        """Tokens consumidos a partir de los cuales se dispara la recuperación preventiva."""
        return int(self.capacidad_util * self.umbral_compresion_pct)

TOKEN_LIMITS = TokenLimits()

# -- API de chat.z.ai -----------------------------------------------

@dataclass(frozen=True)
class APIConfig:
    """Configuración de los endpoints de chat.z.ai.

    Nota v3.2: El batch endpoint usa chat_id con autenticación, NO share_id
    como invitado. La plataforma cambió desde v2.2.
    """

    base_url: str = "https://chat.z.ai"
    timeout_seconds: float = 30.0
    cookie_name: str = "token"

    @property
    def share_info_url(self) -> str:
        return f"{self.base_url}/api/v1/chats/share/{{share_id}}"

    @property
    def share_messages_batch_url(self) -> str:
        """Deprecated v3.2: la plataforma cambió. Usar messages_batch_by_chat_url."""
        return f"{self.base_url}/api/v1/chats/share/{{share_id}}/messages/batch"

    @property
    def messages_batch_by_chat_url(self) -> str:
        """Endpoint de batch autenticado por chat_id (v3.2)."""
        return f"{self.base_url}/api/v1/chats/{{chat_id}}/messages/batch"

    @property
    def create_share_url(self) -> str:
        return f"{self.base_url}/api/v1/chats/{{chat_id}}/share"

    @property
    def auth_check_url(self) -> str:
        return f"{self.base_url}/api/v1/auths/"

API_CONFIG = APIConfig()

# -- Reglas temáticas por defecto -----------------------------------

@dataclass
class ThemeRule:
    """Regla de clasificación temática.

    Attributes:
        name: Nombre interno del tema.
        display_name: Nombre legible para títulos de bloque.
        keywords: Lista de palabras clave para clasificación.
        block_prefix: Prefijo del nombre de archivo.
        description: Descripción del contenido para el índice.
    """

    name: str
    display_name: str
    keywords: list[str] = field(default_factory=list)
    block_prefix: str = "bloque"
    description: str = ""

DEFAULT_THEME_RULES: list[ThemeRule] = [
    ThemeRule(
        name="validaciones",
        display_name="Validaciones",
        keywords=[
            "server.py", "router.py", "broker.py", "valida", "test", "pytest",
            "passed", "failed", "assert", "ERROR", "FAIL", "SKIP",
            "test_", "_test.py", "unittest", "coverage",
        ],
        block_prefix="bloque_validaciones",
        description="Resultados de pruebas, validaciones de código, tests pasados/fallidos y correcciones.",
    ),
    ThemeRule(
        name="planificador",
        display_name="Planificador",
        keywords=[
            "planner", "planificador", "core/planner", "planificación",
            "plan de tareas", "task_queue", "Pipeline", "pipeline",
            "task_queue", "orchestrator",
        ],
        block_prefix="bloque_planificador",
        description="Diseño e implementación del planificador/orquestador, colas de tareas, estructuras de datos.",
    ),
    ThemeRule(
        name="quota_rate_limit",
        display_name="Cuotas y Rate Limits",
        keywords=[
            "quota", "429", "límite", "cuota", "rate_limit",
            "rate limit", "usage", "token_count", "throttl",
        ],
        block_prefix="bloque_quota",
        description="Gestión de cuotas, rate limiting, contadores de uso y límites de API.",
    ),
    ThemeRule(
        name="almacenamiento",
        display_name="Almacenamiento",
        keywords=[
            "NAS", "nas", "almacenam", "backup", "directorio",
            "storage", "ruta de archivos", "guardar archivos",
            "path", "sandbox", "archivo",
        ],
        block_prefix="bloque_almacenamiento",
        description="Gestión de almacenamiento, NAS, backups, rutas de archivos y sandbox.",
    ),
    ThemeRule(
        name="configuracion_proyecto",
        display_name="Configuración del Proyecto",
        keywords=[
            "worklog", "tareas_inmediatas", "estrategia", "proyecto",
            "repositorio", "repo", "clone", "branch", "estructura",
            "entorno.md", "proyecto.md", "contrato.md", "dcpa.md",
            "identidad.md", "comunicacion.md", ".env", "configur",
        ],
        block_prefix="bloque_configuracion",
        description="Configuración del proyecto, archivos de estrategia, repositorios, estructura de directorios.",
    ),
    ThemeRule(
        name="metodologia",
        display_name="Metodología y Contrato",
        keywords=[
            "DCPA", "DPCA", "diagnóstico", "consenso",
            "autorización", "comunicación", "identidad", "contrato",
            "agente", "sesión", "frase de detección", "handoff",
            "OOP", "orientada a objetos", "clase", "herencia",
        ],
        block_prefix="bloque_metodologia",
        description="Metodología de trabajo, DCPA, contratos de agente, comunicación y sesiones.",
    ),
    ThemeRule(
        name="contexto_compresion",
        display_name="Contexto y Compresión",
        keywords=[
            "tool-results", "tool_results", "caché", "compresión",
            "contexto", "ventana", "tokens", "comprimi",
            "recuperación", "amnesia", "pérdida de contexto",
        ],
        block_prefix="bloque_contexto",
        description="Mecanismos de compresión de contexto, recuperación y gestión de ventana de tokens.",
    ),
    ThemeRule(
        name="general",
        display_name="General",
        keywords=[],
        block_prefix="bloque_general",
        description="Mensajes que no clasifican en ningún tema específico.",
    ),
]

# -- Generación de archivos -----------------------------------------

ESTADO_ACTUAL_FILENAME = "00_estado_actual.md"
INDICE_RECUPERACION_FILENAME = "01_indice_recuperacion.md"
DECISIONES_CLAVE_FILENAME = "02_decisiones_clave.md"
METADATA_FILENAME = "_metadata.json"

SUPPORTED_MESSAGES_FORMATS = {".json"}

# -- Rutas del workspace v3.2 --------------------------------------
#
# Compatibilidad multiplataforma (Windows/Linux/macOS):
# - Si la variable de entorno CZAI_WORKSPACE_DIR está definida, se usa.
# - Si no, se usa el directorio padre del paquete contexto_zai (que es
#   el workspace del agente) o Path.home() / "czai_workspace" como fallback.
# - Los paths se construyen con pathlib.Path (no strings con barras).

import os

def _resolve_workspace_root() -> Path:
    """Resuelve la raíz del workspace del agente de forma multiplataforma.

    Orden de prioridad:
    1. Variable de entorno CZAI_WORKSPACE_DIR.
    2. Directorio padre del paquete contexto_zai (3 niveles arriba de este archivo).
    3. Path.home() / "czai_workspace" como fallback.
    """
    env = os.environ.get("CZAI_WORKSPACE_DIR")
    if env:
        return Path(env)
    # Este archivo está en <workspace>/contexto_zai/config.py
    # El workspace es el padre de contexto_zai.
    here = Path(__file__).resolve().parent
    workspace = here.parent
    # Verificar que el workspace parece razonable (contiene contexto_zai)
    if (workspace / "contexto_zai").is_dir():
        return workspace
    return Path.home() / "czai_workspace"

WORKSPACE_ROOT = _resolve_workspace_root()
WORKSPACE_OUTPUT_DIR = WORKSPACE_ROOT / "contexto_recuperacion"
DOWNLOAD_OUTPUT_DIR = WORKSPACE_ROOT / "download" / "contexto_recuperacion"
BROWSER_AUTH_STATE_PATH = WORKSPACE_ROOT / ".browser_auth_state.json"

# -- Detección de pérdida de contexto (Sección 6 del spec v3.2) ----

LEXIC_TRIGGER_PHRASES: list[str] = [
    "ya te dije", "lo hablamos", "no repitas", "otra vez lo mismo",
    "estás olvidando", "ya no recuerdas", "por qué respondes eso si ya acordamos",
    "olvidaste", "no recuerdas que", "ya acordamos",
]

SELF_QUESTIONS: list[str] = [
    "¿Sé en qué archivo estoy trabajando?",
    "¿Sé qué decidimos sobre esto?",
    "¿Sé qué sigue?",
]

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
    # -- Validación interna de config.py (atómico standalone) --------
    print("=== Validacion de config.py ===\n")

    # Test 1: límites v3.2 actualizados
    assert TOKEN_LIMITS.max_tokens_estado == 20_000, "max_tokens_estado debe ser 20K (v3.2)"
    assert TOKEN_LIMITS.carga_principal_max == 40_000, "carga_principal_max debe ser 40K (v3.2)"
    assert TOKEN_LIMITS.max_tokens_estado == 20_000
    print(f"[OK] Limites v3.2: estado={TOKEN_LIMITS.max_tokens_estado}, carga={TOKEN_LIMITS.carga_principal_max}")

    # Test 2: umbral de disparo
    expected_umbral = int(TOKEN_LIMITS.capacidad_util * 0.90)
    assert TOKEN_LIMITS.umbral_disparo_tokens == expected_umbral
    print(f"[OK] Umbral disparo: {TOKEN_LIMITS.umbral_disparo_tokens} tokens (90% de {TOKEN_LIMITS.capacidad_util})")

    # Test 3: API config con batch por chat_id (v3.2)
    assert "chat_id" in API_CONFIG.messages_batch_by_chat_url
    assert "share_id" not in API_CONFIG.messages_batch_by_chat_url
    print(f"[OK] Batch endpoint v3.2: {API_CONFIG.messages_batch_by_chat_url}")

    # Test 4: conversiones chars
    assert TOKEN_LIMITS.max_chars_estado == int(20_000 * 3.5)
    assert TOKEN_LIMITS.max_chars_bloque == int(70_000 * 3.5)
    print(f"[OK] Chars: estado={TOKEN_LIMITS.max_chars_estado}, bloque={TOKEN_LIMITS.max_chars_bloque}")

    # Test 5: reglas temáticas cargadas
    assert len(DEFAULT_THEME_RULES) >= 7
    assert any(r.name == "general" for r in DEFAULT_THEME_RULES)
    print(f"[OK] Reglas tematicas: {len(DEFAULT_THEME_RULES)} reglas cargadas")

    # Test 6: disparadores léxicos y auto-preguntas
    assert len(LEXIC_TRIGGER_PHRASES) >= 5
    assert len(SELF_QUESTIONS) == 3
    print(f"[OK] Disparadores lexicos: {len(LEXIC_TRIGGER_PHRASES)} frases")
    print(f"[OK] Auto-preguntas: {len(SELF_QUESTIONS)} preguntas")

    # Test 7: rutas multiplataforma (v3.2 + Windows)
    # Las rutas deben ser objetos Path, no strings con barras
    assert isinstance(WORKSPACE_ROOT, Path)
    assert isinstance(WORKSPACE_OUTPUT_DIR, Path)
    assert isinstance(DOWNLOAD_OUTPUT_DIR, Path)
    assert isinstance(BROWSER_AUTH_STATE_PATH, Path)
    # WORKSPACE_OUTPUT_DIR debe estar dentro de WORKSPACE_ROOT
    assert WORKSPACE_OUTPUT_DIR.is_relative_to(WORKSPACE_ROOT) if hasattr(WORKSPACE_OUTPUT_DIR, "is_relative_to") else str(WORKSPACE_OUTPUT_DIR).startswith(str(WORKSPACE_ROOT))
    # BROWSER_AUTH_STATE_PATH debe ser un archivo dentro del workspace
    assert BROWSER_AUTH_STATE_PATH.name == ".browser_auth_state.json"
    # Soporta variable de entorno CZAI_WORKSPACE_DIR
    import os as _os
    _os.environ["CZAI_WORKSPACE_DIR"] = "/custom/workspace"
    _custom = _resolve_workspace_root()
    assert str(_custom) == "/custom/workspace" or str(_custom).replace("\\", "/") == "/custom/workspace"
    del _os.environ["CZAI_WORKSPACE_DIR"]
    print(f"[OK] Rutas multiplataforma: WORKSPACE_ROOT={WORKSPACE_ROOT}")
    print(f"  WORKSPACE_OUTPUT_DIR={WORKSPACE_OUTPUT_DIR}")
    print(f"  DOWNLOAD_OUTPUT_DIR={DOWNLOAD_OUTPUT_DIR}")

    print("\n[PASS] config.py: todos los tests pasaron")
