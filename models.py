"""Modelos de datos del sistema Contexto Z.ai.

Usa Pydantic v2 para validación estricta y serialización.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class FileCategory(str, Enum):
    ESTADO = "estado_actual"
    INDICE = "indice_recuperacion"
    DECISIONES = "decisiones_clave"
    BLOQUE = "bloque_tematico"


class PipelinePhase(str, Enum):
    AUTH = "auth"
    EXTRACTION = "extraction"
    CLASSIFICATION = "classification"
    GENERATION = "generation"
    VERIFICATION = "verification"


class Verdict(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


# ── Mensajes ───────────────────────────────────────────────────────


class Message(BaseModel):
    """Un mensaje individual del chat.

    Attributes:
        seq: Número secuencial (1-based).
        role: Rol del emisor (user/assistant).
        timestamp: Unix timestamp del mensaje.
        model: Nombre del modelo (solo para assistant).
        content: Contenido textual del mensaje.
    """

    seq: int
    role: MessageRole
    timestamp: float
    model: str = ""
    content: str = ""

    @property
    def datetime(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc)

    @property
    def date_str(self) -> str:
        return self.datetime.strftime("%Y-%m-%d")

    @property
    def datetime_str(self) -> str:
        return self.datetime.strftime("%Y-%m-%d %H:%M")

    @property
    def is_user(self) -> bool:
        return self.role == MessageRole.USER

    @property
    def is_assistant(self) -> bool:
        return self.role == MessageRole.ASSISTANT

    @property
    def estimated_tokens(self) -> float:
        return len(self.content) / 3.5


class Exchange(BaseModel):
    """Unidad de conversación: mensaje del Director + respuestas del agente.

    Attributes:
        id: Identificador secuencial (1-based).
        director_msg: Mensaje del Director que inicia el exchange.
        agent_msgs: Lista de respuestas del agente.
        topic: Tema clasificado (nombre de ThemeRule).
        start_timestamp: Timestamp del primer mensaje del exchange.
        end_timestamp: Timestamp del último mensaje del exchange.
    """

    id: int
    director_msg: Message
    agent_msgs: list[Message] = Field(default_factory=list)
    topic: str = "general"
    start_timestamp: float = 0.0
    end_timestamp: float = 0.0

    @property
    def start_datetime(self) -> datetime:
        ts = self.start_timestamp or self.director_msg.timestamp
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    @property
    def end_datetime(self) -> datetime:
        ts = self.end_timestamp or (
            self.agent_msgs[-1].timestamp if self.agent_msgs
            else self.director_msg.timestamp
        )
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    @property
    def period_str(self) -> str:
        return f"{self.start_datetime.strftime('%Y-%m-%d')} → {self.end_datetime.strftime('%Y-%m-%d')}"

    @property
    def datetime_str(self) -> str:
        return self.start_datetime.strftime("%Y-%m-%d %H:%M")

    @property
    def all_messages(self) -> list[Message]:
        return [self.director_msg, *self.agent_msgs]

    @property
    def total_chars(self) -> int:
        return sum(len(m.content) for m in self.all_messages)

    @property
    def estimated_tokens(self) -> float:
        return self.total_chars / 3.5

    @property
    def director_count(self) -> int:
        return 1

    @property
    def agent_count(self) -> int:
        return len(self.agent_msgs)


# ── Bloques temáticos ──────────────────────────────────────────────


class ThematicBlock(BaseModel):
    """Bloque de exchanges agrupados por tema.

    Attributes:
        name: Nombre del tema.
        display_name: Nombre legible.
        filename: Nombre del archivo de salida.
        description: Descripción del contenido.
        exchanges: Lista de exchanges clasificados en este bloque.
        part_number: Número de parte (1 si no se subdividió).
    """

    name: str
    display_name: str
    filename: str
    description: str = ""
    exchanges: list[Exchange] = Field(default_factory=list)
    part_number: int = 1

    @property
    def total_chars(self) -> int:
        return sum(ex.total_chars for ex in self.exchanges)

    @property
    def estimated_tokens(self) -> float:
        return self.total_chars / 3.5

    @property
    def exchange_count(self) -> int:
        return len(self.exchanges)

    @property
    def director_count(self) -> int:
        return sum(ex.director_count for ex in self.exchanges)

    @property
    def agent_count(self) -> int:
        return sum(ex.agent_count for ex in self.exchanges)

    @property
    def period_str(self) -> str:
        if not self.exchanges:
            return "sin datos"
        first = self.exchanges[0].start_datetime.strftime("%Y-%m-%d")
        last = self.exchanges[-1].end_datetime.strftime("%Y-%m-%d")
        return f"{first} → {last}"

    @property
    def full_filename(self) -> str:
        if self.part_number > 1:
            stem = self.filename.replace(".md", "")
            return f"{stem}_parte{self.part_number}.md"
        return self.filename


# ── Archivos de recuperación ───────────────────────────────────────


class RecoveryFile(BaseModel):
    """Archivo de recuperación generado.

    Attributes:
        filename: Nombre del archivo.
        category: Tipo de archivo.
        content: Contenido en markdown.
        token_limit: Límite máximo de tokens para este tipo.
    """

    filename: str
    category: FileCategory
    content: str = ""
    token_limit: int = 0

    @property
    def char_count(self) -> int:
        return len(self.content)

    @property
    def estimated_tokens(self) -> float:
        return self.char_count / 3.5

    @property
    def within_limit(self) -> bool:
        return self.estimated_tokens <= self.token_limit

    @property
    def utilization_pct(self) -> float:
        if self.token_limit == 0:
            return 0.0
        return (self.estimated_tokens / self.token_limit) * 100


# ── Regla de clasificación ─────────────────────────────────────────


class ClassificationRule(BaseModel):
    """Regla para clasificar exchanges por tema.

    Attributes:
        name: Nombre interno del tema.
        display_name: Nombre legible.
        keywords: Palabras clave para clasificación.
        block_filename: Nombre del archivo de bloque.
        description: Descripción para el índice.
    """

    name: str
    display_name: str
    keywords: list[str] = Field(default_factory=list)
    block_filename: str = ""
    description: str = ""


# ── Resultados de verificación ─────────────────────────────────────


class FileVerification(BaseModel):
    """Resultado de verificación de un archivo.

    Attributes:
        filename: Nombre del archivo.
        estimated_tokens: Tokens estimados.
        token_limit: Límite permitido.
        verdict: Veredicto (ok/warning/error).
        message: Mensaje descriptivo.
    """

    filename: str
    estimated_tokens: float
    token_limit: int
    verdict: Verdict = Verdict.OK
    message: str = ""


class VerificationReport(BaseModel):
    """Reporte completo de verificación.

    Attributes:
        files: Verificaciones individuales.
        total_main_load: Suma de tokens de los 3 archivos principales.
        main_load_ok: Si la carga principal está dentro del límite.
        overall_verdict: Veredicto global.
    """

    files: list[FileVerification] = Field(default_factory=list)
    total_main_load: float = 0.0
    main_load_limit: int = 23_000
    main_load_ok: bool = True
    overall_verdict: Verdict = Verdict.OK

    @property
    def has_errors(self) -> bool:
        return any(f.verdict == Verdict.ERROR for f in self.files)

    @property
    def has_warnings(self) -> bool:
        return any(f.verdict == Verdict.WARNING for f in self.files)


# ── Resultado del pipeline ─────────────────────────────────────────


class PipelineResult(BaseModel):
    """Resultado completo de la ejecución del pipeline.

    Attributes:
        success: Si el pipeline completó sin errores fatales.
        phases_completed: Fases completadas exitosamente.
        messages_extracted: Total de mensajes extraídos.
        exchanges_built: Total de exchanges construidos.
        blocks_generated: Total de bloques temáticos.
        files_generated: Lista de archivos generados.
        verification: Reporte de verificación.
        output_dir: Directorio de salida.
        error: Mensaje de error si hubo fallo.
    """

    success: bool = True
    phases_completed: list[PipelinePhase] = Field(default_factory=list)
    messages_extracted: int = 0
    exchanges_built: int = 0
    blocks_generated: int = 0
    files_generated: list[str] = Field(default_factory=list)
    verification: VerificationReport | None = None
    output_dir: str = ""
    error: str = ""
