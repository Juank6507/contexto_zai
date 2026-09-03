"""Constantes y configuración del sistema Contexto Z.ai.

Centraliza todos los parámetros del spec de recuperación de contexto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


# ── Rutas por defecto ──────────────────────────────────────────────

DEFAULT_OUTPUT_DIR = Path("contexto_recuperacion")
DEFAULT_MESSAGES_FILE = Path("chat_messages.json")


# ── Límites de tokens (Sección 4 del spec) ─────────────────────────

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
    max_tokens_estado: int = 3_000
    max_tokens_indice: int = 8_000
    max_tokens_decisiones: int = 12_000
    carga_principal_max: int = 23_000
    conversion_rate: float = 3.5

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


TOKEN_LIMITS = TokenLimits()


# ── API de chat.z.ai ───────────────────────────────────────────────

@dataclass(frozen=True)
class APIConfig:
    """Configuración de los endpoints de chat.z.ai."""

    base_url: str = "https://chat.z.ai"
    timeout_seconds: float = 30.0
    cookie_name: str = "token"

    @property
    def share_info_url(self) -> str:
        return f"{self.base_url}/api/v1/chats/share/{{share_id}}"

    @property
    def share_messages_batch_url(self) -> str:
        return f"{self.base_url}/api/v1/chats/share/{{share_id}}/messages/batch"

    @property
    def create_share_url(self) -> str:
        return f"{self.base_url}/api/v1/chats/{{chat_id}}/share"

    @property
    def auth_check_url(self) -> str:
        return f"{self.base_url}/api/v1/auths/"


API_CONFIG = APIConfig()


# ── Reglas temáticas por defecto ───────────────────────────────────

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


# ── Generación de archivos ─────────────────────────────────────────

ESTADO_ACTUAL_FILENAME = "00_estado_actual.md"
INDICE_RECUPERACION_FILENAME = "01_indice_recuperacion.md"
DECISIONES_CLAVE_FILENAME = "02_decisiones_clave.md"

SUPPORTED_MESSAGES_FORMATS = {".json"}
