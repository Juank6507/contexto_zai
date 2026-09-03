"""Pipeline orquestador del sistema Contexto Z.ai.

Coordina las 5 fases: Autenticación → Extracción → Clasificación → Generación → Verificación.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import IO

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from contexto_zai.client.auth_client import AuthClient
from contexto_zai.client.chat_client import ChatClient
from contexto_zai.config import (
    API_CONFIG,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_THEME_RULES,
    TOKEN_LIMITS,
)
from contexto_zai.generation.recovery_generator import RecoveryGenerator
from contexto_zai.models import (
    Exchange,
    FileCategory,
    PipelinePhase,
    PipelineResult,
    RecoveryFile,
    ThematicBlock,
)
from contexto_zai.processing.block_manager import BlockManager
from contexto_zai.processing.classifier import MessageClassifier
from contexto_zai.processing.content_cleaner import ContentCleaner
from contexto_zai.processing.exchange_builder import ExchangeBuilder
from contexto_zai.verification.verifier import Verifier

logger = logging.getLogger(__name__)


class Pipeline:
    """Orquestador del sistema de recuperación de contexto.

    Coordina todas las fases del proceso:
        1. Autenticación (opcional) y creación de share
        2. Extracción de mensajes
        3. Clasificación en bloques temáticos
        4. Generación de archivos de recuperación
        5. Verificación de límites de tokens

    Args:
        console: Instancia de Rich Console para output (por defecto crea una nueva).
        verbose: Si True, muestra logging detallado.

    Usage:
        >>> pipeline = Pipeline(verbose=True)
        >>> result = pipeline.run(
        ...     share_id="abc-123",
        ...     chat_label="Mi Chat",
        ...     output_dir="./contexto_recuperacion",
        ... )
        >>> print(result.success)
    """

    def __init__(self, console: Console | None = None, verbose: bool = False) -> None:
        self._console = console or Console()
        self._verbose = verbose
        self._setup_logging()

        # Componentes internos (inicializados perezosamente)
        self._exchange_builder: ExchangeBuilder | None = None
        self._classifier: MessageClassifier | None = None
        self._cleaner: ContentCleaner | None = None
        self._block_manager: BlockManager | None = None
        self._recovery_generator: RecoveryGenerator | None = None
        self._verifier: Verifier | None = None

    # ── Propiedades lazy ───────────────────────────────────────

    @property
    def exchange_builder(self) -> ExchangeBuilder:
        if self._exchange_builder is None:
            self._exchange_builder = ExchangeBuilder()
        return self._exchange_builder

    @property
    def classifier(self) -> MessageClassifier:
        if self._classifier is None:
            self._classifier = MessageClassifier()
        return self._classifier

    @property
    def cleaner(self) -> ContentCleaner:
        if self._cleaner is None:
            self._cleaner = ContentCleaner()
        return self._cleaner

    @property
    def block_manager(self) -> BlockManager:
        if self._block_manager is None:
            self._block_manager = BlockManager(
                max_chars_per_block=TOKEN_LIMITS.max_chars_bloque,
            )
        return self._block_manager

    @property
    def recovery_generator(self) -> RecoveryGenerator:
        if self._recovery_generator is None:
            self._recovery_generator = RecoveryGenerator()
        return self._recovery_generator

    @property
    def verifier(self) -> Verifier:
        if self._verifier is None:
            self._verifier = Verifier()
        return self._verifier

    # ── Método principal ───────────────────────────────────────

    def run(
        self,
        *,
        share_id: str | None = None,
        chat_id: str | None = None,
        token: str | None = None,
        messages_file: str | Path | None = None,
        output_dir: str | Path = DEFAULT_OUTPUT_DIR,
        chat_label: str = "",
        save_raw: bool = False,
    ) -> PipelineResult:
        """Ejecuta el pipeline completo de recuperación de contexto.

        Se puede proporcionar:
            - share_id: para extraer directamente de la API.
            - chat_id + token: para autenticar y crear share automáticamente.
            - messages_file: para usar un JSON previamente exportado.

        Args:
            share_id: UUID del share link.
            chat_id: UUID interno del chat (requiere token).
            token: JWT token para autenticación.
            messages_file: Ruta a JSON de mensajes previamente exportado.
            output_dir: Directorio de salida para los archivos.
            chat_label: Etiqueta descriptiva para el chat.
            save_raw: Si True, guarda los mensajes crudos como JSON.

        Returns:
            PipelineResult con el resultado completo.
        """
        result = PipelineResult(output_dir=str(output_dir))

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                console=self._console,
                transient=False,
            ) as progress:
                # ── Fase 0: Resolución de share_id ──────────────
                if messages_file:
                    progress.add_task(description="Cargando mensajes desde archivo...", total=None)
                    resolved_share = None
                elif share_id:
                    progress.add_task(description="Share ID proporcionado, listo para extraer.", total=None)
                    resolved_share = share_id
                elif chat_id and token:
                    task_auth = progress.add_task(description="Autenticando y creando share...", total=None)
                    resolved_share = self._authenticate_and_share(chat_id, token)
                    progress.update(task_auth, completed=True)
                    result.phases_completed.append(PipelinePhase.AUTH)
                else:
                    result.success = False
                    result.error = (
                        "Se requiere uno de: --share-id, --chat-id con --token, o --messages-file"
                    )
                    return result

                # ── Fase 1: Extracción ──────────────────────────
                task_extract = progress.add_task(description="Extrayendo mensajes...", total=None)
                messages, extracted_share_id = self._extract_messages(
                    share_id=resolved_share,
                    messages_file=messages_file,
                )
                result.messages_extracted = len(messages)
                progress.update(task_extract, completed=True)
                result.phases_completed.append(PipelinePhase.EXTRACTION)

                if not messages:
                    result.success = False
                    result.error = "No se encontraron mensajes."
                    return result

                # ── Fase 2: Clasificación ────────────────────────
                task_class = progress.add_task(description="Clasificando mensajes...", total=None)
                exchanges, blocks = self._classify_and_block(messages)
                result.exchanges_built = len(exchanges)
                result.blocks_generated = len(blocks)
                progress.update(task_class, completed=True)
                result.phases_completed.append(PipelinePhase.CLASSIFICATION)

                # ── Fase 3: Generación ──────────────────────────
                task_gen = progress.add_task(description="Generando archivos de recuperación...", total=None)
                recovery_files = self._generate_recovery(
                    exchanges=exchanges,
                    blocks=blocks,
                    chat_label=chat_label or extracted_share_id or "Chat",
                )
                result.files_generated = [f.filename for f in recovery_files]
                progress.update(task_gen, completed=True)
                result.phases_completed.append(PipelinePhase.GENERATION)

                # ── Fase 4: Verificación ────────────────────────
                task_verify = progress.add_task(description="Verificando límites de tokens...", total=None)
                verification = self._verify(recovery_files)
                result.verification = verification
                progress.update(task_verify, completed=True)
                result.phases_completed.append(PipelinePhase.VERIFICATION)

            # ── Escritura a disco ───────────────────────────────
            self._write_files(recovery_files, output_dir)

            if save_raw and messages:
                self._save_raw_messages(messages, output_dir)

            # ── Resumen final ──────────────────────────────────
            self._print_summary(result, recovery_files)

            return result

        except Exception as exc:
            logger.exception("Error en el pipeline")
            result.success = False
            result.error = str(exc)
            self._console.print(f"\n[bold red]Error:[/bold red] {exc}")
            return result

    # ── Fases privadas ─────────────────────────────────────────

    def _authenticate_and_share(self, chat_id: str, token: str) -> str:
        """Fase 0: Autenticar y crear share.

        Returns:
            share_id del chat.
        """
        with AuthClient(token=token) as auth:
            profile = auth.validate_token()
            self._console.print(
                f"[green]Autenticado:[/green] {profile.get('email', '?')} "
                f"(role: {profile.get('role', '?')})"
            )

            share_id = auth.create_share(chat_id)
            self._console.print(f"[green]Share creado:[/green] {share_id}")
            return share_id

    def _extract_messages(
        self,
        share_id: str | None,
        messages_file: str | Path | None,
    ) -> tuple[list, str | None]:
        """Fase 1: Extraer mensajes desde API o archivo.

        Returns:
            Tupla (messages, share_id_or_None).
        """
        if messages_file:
            with ChatClient() as client:
                messages = client.load_from_file(messages_file)
            self._console.print(
                f"[green]Cargados:[/green] {len(messages)} mensajes desde archivo"
            )
            return messages, None

        if not share_id:
            raise ValueError("share_id es requerido cuando no se usa messages_file")

        with ChatClient() as client:
            messages = client.extract_all(share_id)

        self._console.print(
            f"[green]Extraídos:[/green] {len(messages)} mensajes desde share {share_id[:8]}..."
        )
        return messages, share_id

    def _classify_and_block(
        self, messages: list,
    ) -> tuple[list[Exchange], list[ThematicBlock]]:
        """Fase 2: Construir exchanges, clasificar y crear bloques.

        Returns:
            Tupla (exchanges, blocks).
        """
        # Construir exchanges
        exchanges = self.exchange_builder.build(messages)
        self._console.print(f"[cyan]Exchanges:[/cyan] {len(exchanges)} construidos")

        # Clasificar
        classified = self.classifier.classify(exchanges)
        topic_counts = {k: len(v) for k, v in classified.items()}
        self._console.print(f"[cyan]Temas:[/cyan] {topic_counts}")

        # Crear bloques
        rules_map = {r.name: r for r in self.classifier.get_rules()}
        blocks = self.block_manager.create_blocks(classified, rules_map, self.cleaner)
        self._console.print(f"[cyan]Bloques:[/cyan] {len(blocks)} generados")

        for block in blocks:
            tokens_k = block.estimated_tokens / 1000
            self._console.print(
                f"  [dim]• {block.full_filename} (~{tokens_k:.1f}K tokens, "
                f"{block.exchange_count} exchanges)[/dim]"
            )

        return exchanges, blocks

    def _generate_recovery(
        self,
        exchanges: list[Exchange],
        blocks: list[ThematicBlock],
        chat_label: str,
    ) -> list[RecoveryFile]:
        """Fase 3: Generar todos los archivos de recuperación."""
        recovery_files = self.recovery_generator.generate_all(exchanges, blocks, chat_label)

        for f in recovery_files:
            tokens_k = f.estimated_tokens / 1000
            limit_k = f.token_limit / 1000
            self._console.print(
                f"  [dim]📄 {f.filename} (~{tokens_k:.1f}K / {limit_k:.0f}K tokens)[/dim]"
            )

        return recovery_files

    def _verify(self, files: list[RecoveryFile]) -> VerificationReport:
        """Fase 4: Verificar límites de tokens."""
        report = self.verifier.verify(files)
        self._console.print(self.verifier.format_report(report))
        return report

    # ── Escritura a disco ──────────────────────────────────────

    def _write_files(self, files: list[RecoveryFile], output_dir: str | Path) -> None:
        """Escribe todos los archivos de recuperación al directorio de salida."""
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        for f in files:
            file_path = out_path / f.filename
            file_path.write_text(f.content, encoding="utf-8")
            logger.info("Escrito: %s (%d chars)", file_path, len(f.content))

        self._console.print(f"\n[bold green]Archivos escritos en:[/bold green] {out_path.resolve()}")

    def _save_raw_messages(self, messages: list, output_dir: str | Path) -> None:
        """Guarda los mensajes crudos como JSON."""
        out_path = Path(output_dir)
        raw_path = out_path / "_raw_messages.json"

        data = [
            {
                "seq": m.seq,
                "role": m.role.value,
                "timestamp": m.timestamp,
                "model": m.model,
                "content": m.content,
            }
            for m in messages
        ]

        raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._console.print(f"[dim]Mensajes crudos guardados: {raw_path}[/dim]")

    # ── Resumen visual ─────────────────────────────────────────

    def _print_summary(self, result: PipelineResult, files: list[RecoveryFile]) -> None:
        """Imprime un resumen final del pipeline."""
        total_chars = sum(f.char_count for f in files)
        total_tokens = sum(f.estimated_tokens for f in files)

        summary = (
            f"[bold]Resumen del Pipeline[/bold]\n"
            f"  Mensajes extraídos: [cyan]{result.messages_extracted}[/cyan]\n"
            f"  Exchanges construidos: [cyan]{result.exchanges_built}[/cyan]\n"
            f"  Bloques temáticos: [cyan]{result.blocks_generated}[/cyan]\n"
            f"  Archivos generados: [cyan]{len(result.files_generated)}[/cyan]\n"
            f"  Tamaño total: [cyan]{total_chars:,}[/cyan] chars (~[cyan]{total_tokens/1000:.1f}K[/cyan] tokens)\n"
            f"  Fases completadas: [green]{' → '.join(p.value for p in result.phases_completed)}[/green]"
        )

        self._console.print(Panel(summary, title="Contexto Z.ai", border_style="green"))

    # ── Logging ────────────────────────────────────────────────

    def _setup_logging(self) -> None:
        """Configura el logging con RichHandler."""
        level = logging.DEBUG if self._verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[RichHandler(console=self._console, rich_tracebacks=True)],
        )

    def __repr__(self) -> str:
        return "Pipeline(console=..., verbose={})".format(self._verbose)
