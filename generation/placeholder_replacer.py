# contexto_zai/generation/placeholder_replacer.py -- Reemplazador de placeholders del 03_objetivo_proyecto.md (v7.0 F5 tarea 6).
"""PlaceholderReplacer (v7.0 F5).

Reemplaza los cuatro placeholders del ``03_objetivo_proyecto.md``:

- ``__MODELO_AGENTE__``: modelo del agente CZAI (leído de ZaiLLM).
- ``__DIRECTOR__``: nombre del Director (derivado del email del CredentialManager).
- ``__EMAIL__``: email del Director (leído del CredentialManager vía PlatformAuth).
- ``__ACTA_NACIMIENTO__``: primer exchange cronológico del proyecto (leído del bloque más antiguo por período).

También elimina la nota residual ``_(El agente que contesta debe rellenar
este placeholder...)_`` después del reemplazo.

Atómico standalone: importa config, models, pathlib y logging.
"""
from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
_package_root = None
for _ in range(10):
    if not _os.path.isfile(_os.path.join(_candidate, '__init__.py')):
        break
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
from pathlib import Path

logger = logging.getLogger(__name__)


class PlaceholderReplacer:
    """Reemplaza los placeholders del ``03_objetivo_proyecto.md``.

    Usage:
        >>> from contexto_zai.generation.placeholder_replacer import PlaceholderReplacer
        >>> replacer = PlaceholderReplacer()
        >>> replacer.reemplazar("/path/to/workspace")
        True
    """

    # Nota residual que acompaña al placeholder __ACTA_NACIMIENTO__.
    _NOTA_RESIDUAL = (
        "_(El agente que contesta debe rellenar este placeholder con el primer "
        "exchange del proyecto y/o la primera decisión explícita o implícita de "
        "convertirlo en proyecto, leído desde el contexto del chat actual.)_"
    )

    def reemplazar(self, workspace_dir: Path | str) -> bool:
        """Reemplaza los cuatro placeholders del 03_objetivo_proyecto.md.

        Args:
            workspace_dir: Directorio del workspace.

        Returns:
            True si se reemplazó algún placeholder, False si no.
        """
        ws = Path(workspace_dir)
        objetivo_path = ws / "03_objetivo_proyecto.md"
        if not objetivo_path.exists():
            return False

        content = objetivo_path.read_text(encoding="utf-8")
        original_content = content

        # __MODELO_AGENTE__: leer del ZaiLLM. Sin fallback hardcoded.
        try:
            from contexto_zai.platforms.zai.zai_llm import ZaiLLM
            llm = ZaiLLM()
            modelo_agente = llm.get_default_model_heavy()
        except Exception as e:
            logger.warning("PlaceholderReplacer: no se pudo leer modelo del ZaiLLM: %s", e)
            modelo_agente = None
        if modelo_agente:
            content = content.replace("__MODELO_AGENTE__", modelo_agente)

        # __EMAIL__ y __DIRECTOR__: leer via PlatformAuth.
        try:
            from contexto_zai.platforms.zai.zai_auth import ZaiAuth
            auth = ZaiAuth()
            email = auth.get_email() or "Director (email no disponible)"
            if "@" in email and "guest" not in email.lower():
                nombre_part = email.split("@")[0]
                director = nombre_part.replace(".", " ").replace("_", " ").replace("-", " ").title()
            else:
                director = "Director"
        except Exception:
            email = "Director (email no disponible)"
            director = "Director"
        content = content.replace("__DIRECTOR__", director)
        content = content.replace("__EMAIL__", email)

        # __ACTA_NACIMIENTO__: primer exchange cronológico del proyecto.
        acta_nacimiento = "(Acta de nacimiento no disponible — ver worklog.md)"
        try:
            bloques = sorted(ws.glob("bloque_*.md"))
            if bloques:
                bloque_mas_antiguo = None
                fecha_mas_antigua = None
                for b in bloques:
                    content_b = b.read_text(encoding="utf-8", errors="ignore")[:1500]
                    m = re.search(r"\*\*Per[ií]odo:\*\*\s*(\d{4}-\d{2}-\d{2})", content_b)
                    if m:
                        fecha = m.group(1)
                        if fecha_mas_antigua is None or fecha < fecha_mas_antigua:
                            fecha_mas_antigua = fecha
                            bloque_mas_antiguo = b
                if bloque_mas_antiguo is None:
                    bloque_mas_antiguo = bloques[-1]
                bloque_content = bloque_mas_antiguo.read_text(encoding="utf-8")
                match_director = re.search(
                    r"### Director:\s*\n(.+?)(?=\n###|\n##|\Z)",
                    bloque_content,
                    re.DOTALL,
                )
                if match_director:
                    acta_nacimiento = match_director.group(1).strip()[:500]
        except Exception:
            pass
        content = content.replace("__ACTA_NACIMIENTO__", acta_nacimiento)

        # Eliminar la nota residual del placeholder (C6).
        content = content.replace(self._NOTA_RESIDUAL, "")

        if content != original_content:
            objetivo_path.write_text(content, encoding="utf-8")
            logger.info("PlaceholderReplacer: placeholders reemplazados en 03_objetivo_proyecto.md")
            return True
        return False
