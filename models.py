# contexto_zai/models.py -- Modelos de datos Pydantic (Message, Exchange, ThematicBlock, RecoveryFile, etc.).
"""Modelos de datos del sistema Contexto Z.ai.

Usa Pydantic v2 para validación estricta y serialización.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

# -- Enums ----------------------------------------------------------

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

# -- Mensajes -------------------------------------------------------

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
        return f"{self.start_datetime.strftime('%Y-%m-%d')} -> {self.end_datetime.strftime('%Y-%m-%d')}"

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

# -- Bloques temáticos ----------------------------------------------

class ThematicBlock(BaseModel):
    """Bloque de exchanges agrupados por tamaño (v3.2).

    Un bloque puede contener exchanges de varios temas diferentes,
    siempre que la suma de sus tokens no supere MAX_TOKENS_BLOQUE.

    Attributes:
        filename: Nombre del archivo de salida.
        exchanges: Lista de exchanges en este bloque.
        temas: Lista de temas contenidos en este bloque.
        description: Descripción del contenido.
    """

    filename: str
    exchanges: list[Exchange] = Field(default_factory=list)
    temas: list[str] = Field(default_factory=list)
    description: str = ""

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
        return f"{first} -> {last}"

    @property
    def full_filename(self) -> str:
        return self.filename

    def add_exchange(self, exchange: Exchange) -> None:
        """Añade un exchange al bloque y registra su tema si no existe."""
        self.exchanges.append(exchange)
        if exchange.topic not in self.temas:
            self.temas.append(exchange.topic)

    def would_exceed_limit(self, exchange: Exchange, max_tokens: int) -> bool:
        """Verifica si añadir el exchange superaría el límite de tokens."""
        new_chars = self.total_chars + exchange.total_chars
        return (new_chars / 3.5) > max_tokens

# -- Archivos de recuperación ---------------------------------------

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

# -- Regla de clasificación -----------------------------------------

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

# -- Resultados de verificación -------------------------------------

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
    main_load_limit: int = 40_000
    main_load_ok: bool = True
    overall_verdict: Verdict = Verdict.OK

    @property
    def has_errors(self) -> bool:
        return any(f.verdict == Verdict.ERROR for f in self.files)

    @property
    def has_warnings(self) -> bool:
        return any(f.verdict == Verdict.WARNING for f in self.files)

# -- Resultado del pipeline -----------------------------------------

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

# -- Modelos v3.2: Metadata, Decisiones, Detección -----------------

class Decision(BaseModel):
    """Una decisión operativa extraída de la conversación.

    Attributes:
        id: Identificador (D01, D02, ...).
        timestamp: Cuándo se tomó.
        title: Título breve.
        decision: Qué se decidió.
        reason: Por qué.
        impact: Qué afecta.
        tema: Tema al que pertenece.
    """

    id: str = ""
    timestamp: float = 0.0
    title: str = ""
    decision: str = ""
    reason: str = ""
    impact: str = ""
    tema: str = ""

class RecoveryMetadata(BaseModel):
    """Metadata de recuperación (archivo _metadata.json).

    Attributes:
        chat_id: UUID interno del chat.
        share_id: UUID del share.
        ultimo_timestamp: Último mensaje procesado (para incremental).
        total_exchanges: Total de exchanges procesados.
        tema_a_archivo: Mapeo tema -> archivo (unicidad garantizada).
        subtemas_derivados: Registro de subtemas creados al subdividir.
        ultima_activacion: ISO timestamp de la última activación.
    """

    chat_id: str = ""
    share_id: str = ""
    ultimo_timestamp: float = 0.0
    total_exchanges: int = 0
    tema_a_archivo: dict[str, str] = Field(default_factory=dict)
    subtemas_derivados: dict[str, list[str]] = Field(default_factory=dict)
    ultima_activacion: str = ""

    def archivo_para_tema(self, tema: str) -> str | None:
        """Devuelve el archivo que contiene el tema, o None si no existe."""
        return self.tema_a_archivo.get(tema)

    def tiene_tema(self, tema: str) -> bool:
        """Verifica si un tema ya está registrado."""
        return tema in self.tema_a_archivo

    def registrar_tema(self, tema: str, archivo: str) -> None:
        """Registra un tema en un archivo. Falla si el tema ya existe en otro archivo."""
        if tema in self.tema_a_archivo and self.tema_a_archivo[tema] != archivo:
            raise ValueError(
                f"Violación de unicidad: tema '{tema}' ya está en "
                f"'{self.tema_a_archivo[tema]}', no puede registrarse en '{archivo}'"
            )
        self.tema_a_archivo[tema] = archivo

    def registrar_subtema(self, tema_padre: str, subtema: str, archivo: str) -> None:
        """Registra un subtema derivado de una subdivisión."""
        self.registrar_tema(subtema, archivo)
        if tema_padre not in self.subtemas_derivados:
            self.subtemas_derivados[tema_padre] = []
        if subtema not in self.subtemas_derivados[tema_padre]:
            self.subtemas_derivados[tema_padre].append(subtema)

class DetectionTrigger(str, Enum):
    """Tipos de disparador de la recuperación de contexto."""

    LEXICO = "lexico"
    CONTADOR = "contador"
    AUTO_PREGUNTAS = "auto_preguntas"
    EXPLICITO = "explicito"

class DetectionEvent(BaseModel):
    """Evento de detección de pérdida de contexto.

    Attributes:
        trigger: Tipo de disparador que lo activó.
        reason: Descripción legible del motivo.
        timestamp: Cuándo se detectó.
        tokens_estimados: Tokens consumidos al momento (si aplica).
    """

    trigger: DetectionTrigger
    reason: str = ""
    timestamp: float = 0.0
    tokens_estimados: int = 0

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
    # -- Validación interna de models.py (atómico standalone) ---------
    print("=== Validacion de models.py ===\n")

    # Test 1: Message básico
    m = Message(seq=1, role=MessageRole.USER, timestamp=1788482829, content="hola")
    assert m.is_user and not m.is_assistant
    assert m.estimated_tokens > 0
    print(f"[OK] Message: role={m.role.value}, datetime={m.datetime_str}")

    # Test 2: Exchange
    ex = Exchange(
        id=1,
        director_msg=m,
        agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=1788482830, content="respuesta")],
        topic="general",
        start_timestamp=1788482829,
        end_timestamp=1788482830,
    )
    assert ex.director_count == 1
    assert ex.agent_count == 1
    assert ex.estimated_tokens > 0
    print(f"[OK] Exchange: id={ex.id}, tema={ex.topic}, tokens={ex.estimated_tokens:.0f}")

    # Test 3: ThematicBlock v3.2 (varios temas por archivo)
    bloque = ThematicBlock(filename="bloque_01.md")
    ex2 = Exchange(id=2, director_msg=m, topic="validaciones", start_timestamp=1788482830, end_timestamp=1788482831)
    bloque.add_exchange(ex)
    bloque.add_exchange(ex2)
    assert set(bloque.temas) == {"general", "validaciones"}
    assert not bloque.would_exceed_limit(ex, max_tokens=100_000)
    print(f"[OK] ThematicBlock v3.2: {bloque.exchange_count} exchanges, {len(bloque.temas)} temas en 1 archivo")

    # Test 4: RecoveryMetadata con unicidad
    meta = RecoveryMetadata(chat_id="abc", share_id="def")
    meta.registrar_tema("validaciones", "bloque_01.md")
    meta.registrar_tema("configuracion", "bloque_01.md")  # mismo archivo, OK
    assert meta.archivo_para_tema("validaciones") == "bloque_01.md"
    assert meta.tiene_tema("validaciones")
    # Violación de unicidad debe fallar
    try:
        meta.registrar_tema("validaciones", "bloque_02.md")
        assert False, "Debería haber lanzado ValueError"
    except ValueError as e:
        print(f"[OK] Unicidad tematica: violacion detectada correctamente")
    meta.registrar_subtema("validaciones", "validaciones_server", "bloque_02.md")
    assert "validaciones_server" in meta.subtemas_derivados["validaciones"]
    print(f"[OK] Subtema derivado: 'validaciones_server' registrado en bloque_02.md")

    # Test 5: Decision
    d = Decision(id="D01", timestamp=1788482829, title="Test", decision="X", reason="Y", impact="Z")
    assert d.id == "D01"
    print(f"[OK] Decision: {d.id} - {d.title}")

    # Test 6: DetectionEvent
    de = DetectionEvent(trigger=DetectionTrigger.LEXICO, reason="ya te dije")
    assert de.trigger == DetectionTrigger.LEXICO
    print(f"[OK] DetectionEvent: trigger={de.trigger.value}")

    # Test 7: límites actualizados
    assert VerificationReport().main_load_limit == 40_000
    print(f"[OK] VerificationReport: main_load_limit=40K (v3.2)")

    print("\n[PASS] models.py: todos los tests pasaron")
