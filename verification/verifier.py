"""Verificador de archivos de recuperación.

Valida que cada archivo generado cumpla con los límites de tokens
definidos en la configuración y produce un reporte legible.
"""

from __future__ import annotations

import logging

from contexto_zai.config import TOKEN_LIMITS
from contexto_zai.models import (
    FileCategory,
    FileVerification,
    RecoveryFile,
    VerificationReport,
    Verdict,
)

logger = logging.getLogger(__name__)

# Categorías que forman la "carga principal" (archivos de carga rápida).
_MAIN_LOAD_CATEGORIES: set[FileCategory] = {
    FileCategory.ESTADO,
    FileCategory.INDICE,
    FileCategory.DECISIONES,
}

# Umbrales de veredicto como proporción del límite.
_ERROR_THRESHOLD = 1.1
_WARNING_THRESHOLD = 0.9

# Símbolos para el reporte formateado.
_ICON_FILE = "\U0001F4C4"
_ICON_CHART = "\U0001F4CA"
_ICON_OK = "\u2705"
_ICON_WARN = "\u26A0\uFE0F"
_ICON_ERR = "\u274C"


def _format_tokens(value: float) -> str:
    """Formatea un valor de tokens en notación compacta (ej. ~2.1K)."""
    if value >= 1_000:
        return f"~{value / 1_000:.1f}K"
    return f"~{value:.0f}"


def _verdict_icon(verdict: Verdict) -> str:
    """Devuelve el ícono asociado a un veredicto."""
    match verdict:
        case Verdict.OK:
            return _ICON_OK
        case Verdict.WARNING:
            return _ICON_WARN
        case Verdict.ERROR:
            return _ICON_ERR


def _verdict_label(verdict: Verdict) -> str:
    """Devuelve la etiqueta legible de un veredicto."""
    match verdict:
        case Verdict.OK:
            return "OK"
        case Verdict.WARNING:
            return "ADVERTENCIA"
        case Verdict.ERROR:
            return "ERROR"


class Verifier:
    """Verifica que los archivos de recuperación respeten los límites de tokens.

    Para cada archivo se calcula el porcentaje de uso respecto a su límite
    y se asigna un veredicto:

    - **ERROR** si los tokens estimados superan el 110 % del límite.
    - **WARNING** si los tokens estimados superan el 90 % del límite.
    - **OK** en caso contrario.

    También verifica que la suma de los tres archivos de "carga principal"
    (estado, índice, decisiones) no exceda ``carga_principal_max``.
    """

    def __init__(self) -> None:
        """Inicializa el verificador con los límites globales de tokens."""
        self._limits = TOKEN_LIMITS

    # ── Lógica de verificación ──────────────────────────────────────

    def _judge_file(self, file: RecoveryFile) -> FileVerification:
        """Evalúa un archivo individual y devuelve su verificación."""
        estimated = file.estimated_tokens
        limit = file.token_limit

        # Calcular porcentaje de uso.
        pct = (estimated / limit * 100) if limit > 0 else 0.0

        # Determinar veredicto.
        if estimated > limit * _ERROR_THRESHOLD:
            verdict = Verdict.ERROR
        elif estimated > limit * _WARNING_THRESHOLD:
            verdict = Verdict.WARNING
        else:
            verdict = Verdict.OK

        # Construir mensaje descriptivo.
        msg = f"{_format_tokens(estimated)} tokens / {limit:,} límite ({pct:.0f}%)"
        if verdict == Verdict.ERROR:
            over = estimated - limit
            msg += f" — excede el límite en {_format_tokens(over)} tokens"
        elif verdict == Verdict.WARNING:
            remaining = limit - estimated
            msg += f" — {_format_tokens(remaining)} tokens de margen"

        return FileVerification(
            filename=file.filename,
            estimated_tokens=estimated,
            token_limit=limit,
            verdict=verdict,
            message=msg,
        )

    # ── API pública ─────────────────────────────────────────────────

    def verify(self, files: list[RecoveryFile]) -> VerificationReport:
        """Verifica una lista de archivos y devuelve el reporte completo.

        Args:
            files: Archivos de recuperación generados.

        Returns:
            Un :class:`VerificationReport` con la verificación de cada
            archivo, la carga principal total y el veredicto global.
        """
        verifications: list[FileVerification] = []
        total_main_load = 0.0

        for file in files:
            fv = self._judge_file(file)
            verifications.append(fv)
            logger.debug("%s → %s", fv.filename, fv.verdict.value)

            if file.category in _MAIN_LOAD_CATEGORIES:
                total_main_load += file.estimated_tokens

        # Veredicto global.
        has_errors = any(fv.verdict == Verdict.ERROR for fv in verifications)
        has_warnings = any(fv.verdict == Verdict.WARNING for fv in verifications)

        if has_errors:
            overall = Verdict.ERROR
        elif has_warnings:
            overall = Verdict.WARNING
        else:
            overall = Verdict.OK

        report = VerificationReport(
            files=verifications,
            total_main_load=total_main_load,
            main_load_limit=self._limits.carga_principal_max,
            main_load_ok=total_main_load <= self._limits.carga_principal_max,
            overall_verdict=overall,
        )

        logger.info(
            "Verificación completada: %d archivos, carga principal %s/%s, veredicto=%s",
            len(verifications),
            _format_tokens(total_main_load),
            f"{self._limits.carga_principal_max:,}",
            overall.value,
        )

        return report

    # ── Formateo del reporte ────────────────────────────────────────

    def format_report(self, report: VerificationReport) -> str:
        """Genera un resumen legible del reporte de verificación.

        Args:
            report: El reporte producido por :meth:`verify`.

        Returns:
            Cadena de texto con el reporte formateado.
        """
        sep = "═" * 40
        thin = "─" * 40
        lines: list[str] = []

        # Cabecera.
        lines.append(sep)
        lines.append("VERIFICACIÓN DE ARCHIVOS")
        lines.append(sep)

        # Archivos individuales.
        for fv in report.files:
            icon = _verdict_icon(fv.verdict)
            label = _verdict_label(fv.verdict)
            lines.append(f"{_ICON_FILE} {fv.filename}")
            lines.append(f"   {fv.message} — {icon} {label}")

        # Carga principal.
        lines.append(thin)
        load_icon = _ICON_OK if report.main_load_ok else _ICON_ERR
        lines.append(
            f"{_ICON_CHART} Carga principal: {_format_tokens(report.total_main_load)} "
            f"/ {report.main_load_limit:,} tokens — {load_icon}"
        )

        # Resultado global.
        lines.append(sep)
        ov_icon = _verdict_icon(report.overall_verdict)
        match report.overall_verdict:
            case Verdict.OK:
                result_msg = "TODOS LOS ARCHIVOS DENTRO DEL LÍMITE"
            case Verdict.WARNING:
                result_msg = "ALGUNOS ARCHIVOS CERCA DEL LÍMITE"
            case Verdict.ERROR:
                result_msg = "ARCHIVOS EXCEDEN EL LÍMITE"
        lines.append(f"Resultado: {ov_icon} {result_msg}")
        lines.append(sep)

        return "\n".join(lines)


if __name__ == "__main__":
    # ── Validación interna de verifier.py (atómico standalone) ──
    print("=== Validación de verifier.py ===\n")

    from contexto_zai.config import TOKEN_LIMITS
    from contexto_zai.models import FileCategory, RecoveryFile, Verdict

    v = Verifier()

    # Test 1: archivo dentro del límite → OK
    f_ok = RecoveryFile(
        filename="00_estado_actual.md",
        category=FileCategory.ESTADO,
        content="x" * 1000,
        token_limit=TOKEN_LIMITS.max_tokens_estado,
    )
    report = v.verify([f_ok])
    assert report.overall_verdict == Verdict.OK
    assert not report.has_errors
    print(f"✓ Archivo dentro del límite: veredicto OK")

    # Test 2: archivo que excede el límite por >1.1× → ERROR
    contenido_excedente = "x" * int(TOKEN_LIMITS.max_tokens_bloque * 3.5 * 1.2)  # 120% del límite
    f_err = RecoveryFile(
        filename="bloque_x.md",
        category=FileCategory.BLOQUE,
        content=contenido_excedente,
        token_limit=TOKEN_LIMITS.max_tokens_bloque,
    )
    report2 = v.verify([f_err])
    assert report2.has_errors, f"Esperaba errores, obtuve verdict={report2.overall_verdict}"
    print(f"✓ Bloque que excede 70K tokens (1.2x): detectado como ERROR")

    # Test 3: carga principal total (estado + indice + decisiones)
    f_estado = RecoveryFile(filename="00_estado_actual.md", category=FileCategory.ESTADO, content="x" * 1000, token_limit=TOKEN_LIMITS.max_tokens_estado)
    f_indice = RecoveryFile(filename="01_indice_recuperacion.md", category=FileCategory.INDICE, content="x" * 1000, token_limit=TOKEN_LIMITS.max_tokens_indice)
    f_dec = RecoveryFile(filename="02_decisiones_clave.md", category=FileCategory.DECISIONES, content="x" * 1000, token_limit=TOKEN_LIMITS.max_tokens_decisiones)
    report3 = v.verify([f_estado, f_indice, f_dec])
    assert report3.main_load_limit == 40_000  # v3.2
    print(f"✓ Carga principal con límite v3.2 (40K): OK")

    # Test 4: reporte formateado
    formatted = v.format_report(report3)
    assert "Resultado" in formatted or "resultado" in formatted.lower()
    print(f"✓ Formateo de reporte: OK")

    print("\n✅ verifier.py: todos los tests pasaron")
