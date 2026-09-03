"""Interfaz de línea de comandos (CLI) para Contexto Z.ai.  

Usa Click para definir los comandos y Rich para output en consola.  Todos los comandos delegan a :class:`Pipeline` para la lógica de negocio.  
"""  

from __future__ import annotations  

import sys
from pathlib import Path


import click
from rich.console import Console

from contexto_zai.config import DEFAULT_OUTPUT_DIR
from contexto_zai.pipeline import Pipeline


# ── Opciones compartidas ─────────────────────────────────────────


def _output_dir_option(default: Path = DEFAULT_OUTPUT_DIR) -> click.Option:
    """Opción de directorio de salida reutilizable."""
    return click.option(
        "-o",
        "--output-dir",
        type=click.Path(path_type=Path),
        default=default,
        show_default=True,
        help="Directorio de salida para los archivos de recuperación.",
    )


def _verbose_option() -> click.Option:
    """Opción verbose reutilizable."""
    return click.option(
        "-v",
        "--verbose",
        is_flag=True,
        default=False,
        help="Activar logging detallado (DEBUG).",
    )


def _chat_label_option() -> click.Option:
    """Opción de etiqueta de chat reutilizable."""
    return click.option(
        "-l",
        "--chat-label",
        type=str,
        default="",
        show_default=False,
        help="Etiqueta descriptiva para el chat (se usa en los títulos de los archivos).",
    )


# ── Utilidades ───────────────────────────────────────────────────


def _create_console(verbose: bool) -> Console:
    """Crea una consola Rich con stderr si no es tty."""
    return Console(stderr=False, force_terminal=True)


def _exit_with_error(console: Console, message: str, code: int = 1) -> None:
    """Imprime un error y sale."""
    console.print(f"[bold red]Error:[/bold red] {message}")
    sys.exit(code)


# ══════════════════════════════════════════════════════════════════
# COMANDO PRINCIPAL
# ══════════════════════════════════════════════════════════════════


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.version_option(version="1.0.0", prog_name="contexto-zai")
@_verbose_option()
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Contexto Z.ai — Sistema de recuperación de contexto para agentes.

    Recupera, clasifica y genera archivos de contexto para agentes Z.ai
    que han perdido su ventana de contexto por compresión de la plataforma.
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["console"] = _create_console(verbose)

    # Si no se pasa subcomando, mostrar ayuda
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ══════════════════════════════════════════════════════════════════
# COMANDO: run  (pipeline completo)
# ══════════════════════════════════════════════════════════════════


@cli.command(name="run", help="Ejecuta el pipeline completo de recuperación de contexto.")
@click.option(
    "--share-id",
    type=str,
    default=None,
    help="UUID del share link del chat.",
)
@click.option(
    "--chat-id",
    type=str,
    default=None,
    help="UUID interno del chat (requiere --token).",
)
@click.option(
    "-t",
    "--token",
    type=str,
    default=None,
    envvar="CONTEXTO_ZAI_TOKEN",
    help=(
        "JWT token para autenticación. "
        "Se puede pasar como argumento o variable de entorno CONTEXTO_ZAI_TOKEN."
    ),
)
@click.option(
    "--messages-file",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Ruta a un archivo JSON con mensajes previamente exportados.",
)
@_output_dir_option()
@_chat_label_option()
@click.option(
    "--save-raw",
    is_flag=True,
    default=False,
    help="Guardar los mensajes crudos como JSON en el directorio de salida.",
)
@click.pass_context
def run_cmd(
    ctx: click.Context,
    share_id: str | None,
    chat_id: str | None,
    token: str | None,
    messages_file: Path | None,
    output_dir: Path,
    chat_label: str,
    save_raw: bool,
) -> None:
    """Ejecuta el pipeline completo: extrae → clasifica → genera → verifica."""
    console: Console = ctx.obj["console"]

    # Validar que se proporcionó al menos una fuente de datos
    has_share = share_id is not None
    has_chat_auth = chat_id is not None and token is not None
    has_file = messages_file is not None

    if not (has_share or has_chat_auth or has_file):
        _exit_with_error(
            console,
            "Se requiere una fuente de datos. Usa:\n"
            "  --share-id UUID         (chat ya compartido)\n"
            "  --chat-id UUID --token JWT  (autenticar y crear share)\n"
            "  --messages-file PATH    (JSON previamente exportado)",
        )

    if chat_id and not token:
        _exit_with_error(console, "--chat-id requiere --token para autenticación.")

    pipeline = Pipeline(console=console, verbose=ctx.obj["verbose"])
    result = pipeline.run(
        share_id=share_id,
        chat_id=chat_id,
        token=token,
        messages_file=messages_file,
        output_dir=output_dir,
        chat_label=chat_label,
        save_raw=save_raw,
    )

    if not result.success:
        _exit_with_error(console, f"Pipeline falló: {result.error}")

    ctx.exit(0)


# ══════════════════════════════════════════════════════════════════
# COMANDO: extract  (solo extracción)
# ══════════════════════════════════════════════════════════════════


@cli.command(name="extract", help="Extrae mensajes de un chat y los guarda como JSON.")
@click.option(
    "--share-id",
    type=str,
    required=True,
    help="UUID del share link.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    default="chat_messages.json",
    show_default=True,
    help="Archivo de salida para los mensajes extraídos.",
)
@click.pass_context
def extract_cmd(
    ctx: click.Context,
    share_id: str,
    output: Path,
) -> None:
    """Extrae todos los mensajes de un chat compartido y los guarda como JSON."""
    console: Console = ctx.obj["console"]
    import json

    from contexto_zai.client.chat_client import ChatClient

    console.print(f"[bold]Extrayendo mensajes del share:[/bold] {share_id[:12]}...")

    try:
        with ChatClient() as client:
            messages = client.extract_all(share_id)
    except Exception as exc:
        _exit_with_error(console, str(exc))

    if not messages:
        _exit_with_error(console, "No se encontraron mensajes.")

    # Serializar
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

    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(
        f"[bold green]{len(messages)} mensajes[/bold green] guardados en [bold]{output}[/bold]"
    )


# ══════════════════════════════════════════════════════════════════
# COMANDO: classify  (solo clasificación desde archivo)
# ══════════════════════════════════════════════════════════════════


@cli.command(name="classify", help="Clasifica mensajes desde un JSON y genera los bloques temáticos.")
@click.option(
    "--messages-file",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Ruta al archivo JSON con mensajes extraídos.",
)
@_output_dir_option()
@_chat_label_option()
@click.pass_context
def classify_cmd(
    ctx: click.Context,
    messages_file: Path,
    output_dir: Path,
    chat_label: str,
) -> None:
    """Clasifica mensajes y genera bloques sin ejecutar la extracción."""
    console: Console = ctx.obj["console"]

    pipeline = Pipeline(console=console, verbose=ctx.obj["verbose"])
    result = pipeline.run(
        messages_file=messages_file,
        output_dir=output_dir,
        chat_label=chat_label,
        save_raw=False,
    )

    if not result.success:
        _exit_with_error(console, f"Clasificación falló: {result.error}")

    ctx.exit(0)


# ══════════════════════════════════════════════════════════════════
# COMANDO: verify  (solo verificación)
# ══════════════════════════════════════════════════════════════════


@cli.command(name="verify", help="Verifica que los archivos de recuperación están dentro de los límites.")
@click.option(
    "-d",
    "--dir",
    "directory",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Directorio con los archivos generados.",
)
@click.pass_context
def verify_cmd(
    ctx: click.Context,
    directory: Path,
) -> None:
    """Verifica los límites de tokens de archivos ya generados."""
    console: Console = ctx.obj["console"]

    from contexto_zai.verification.verifier import Verifier
    from contexto_zai.models import FileCategory, RecoveryFile

    # Leer archivos del directorio
    recovery_files: list[RecoveryFile] = []

    for fpath in sorted(directory.iterdir()):
        if not fpath.is_file() or fpath.suffix != ".md":
            continue

        content = fpath.read_text(encoding="utf-8")

        # Determinar categoría por nombre de archivo
        fname = fpath.name
        if fname.startswith("00_"):
            category = FileCategory.ESTADO
            limit = 3_000
        elif fname.startswith("01_"):
            category = FileCategory.INDICE
            limit = 8_000
        elif fname.startswith("02_"):
            category = FileCategory.DECISIONES
            limit = 12_000
        else:
            category = FileCategory.BLOQUE
            limit = 70_000

        recovery_files.append(
            RecoveryFile(
                filename=fname,
                category=category,
                content=content,
                token_limit=limit,
            )
        )

    if not recovery_files:
        _exit_with_error(console, f"No se encontraron archivos .md en {directory}")

    verifier = Verifier()
    report = verifier.verify(recovery_files)
    console.print(verifier.format_report(report))

    if report.overall_verdict.value == "error":
        _exit_with_error(console, "Algunos archivos exceden los límites.", code=2)

    ctx.exit(0)


# ══════════════════════════════════════════════════════════════════
# COMANDO: create-share  (solo creación de share)
# ══════════════════════════════════════════════════════════════════


@cli.command(name="create-share", help="Crea un share link para un chat autenticado.")
@click.option(
    "--chat-id",
    type=str,
    required=True,
    help="UUID interno del chat.",
)
@click.option(
    "-t",
    "--token",
    type=str,
    required=True,
    envvar="CONTEXTO_ZAI_TOKEN",
    help="JWT token para autenticación.",
)
@click.pass_context
def create_share_cmd(
    ctx: click.Context,
    chat_id: str,
    token: str,
) -> None:
    """Crea un share link para un chat y muestra el share_id."""
    console: Console = ctx.obj["console"]

    from contexto_zai.client.auth_client import AuthClient

    try:
        with AuthClient(token=token) as auth:
            profile = auth.validate_token()
            console.print(
                f"[green]Autenticado:[/green] {profile.get('email', '?')} "
                f"(role: {profile.get('role', '?')})"
            )

            share_id = auth.create_share(chat_id)

        console.print(
            f"\n[bold green]Share ID:[/bold green] {share_id}"
            f"\n[bold]URL:[/bold] https://chat.z.ai/s/{share_id}"
        )

    except Exception as exc:
        _exit_with_error(console, str(exc))

    ctx.exit(0)


def main() -> None:
    """Punto de entrada principal del CLI."""
    cli()


if __name__ == "__main__":
    main()
