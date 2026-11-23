# contexto_zai/processing/divisor.py -- Clase base abstracta Divisor + DocumentoDivisor (v3.6).
"""Divisor de documentos grandes (v3.6).

Clase base abstracta `Divisor` que define la interfaz para partir
un contenido grande en porciones manejables por subagentes N2.

Implementación concreta `DocumentoDivisor` para PDFs (usa pdfplumber
para contar páginas y estimar tokens por página).

Atómico standalone: importa config y models.
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
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from contexto_zai.config import MAX_TOKENS_POR_SUBAGENTE_N2
from contexto_zai.models import Porcion

if TYPE_CHECKING:
    # Evitar import circular: divisor.py ← subagents/__init__.py ← divisor_subagent.py ← divisor.py
    from contexto_zai.subagents.launcher import SubagentLauncher, SubagentRequest, SubagentResponse

logger = logging.getLogger(__name__)


class Divisor(ABC):
    """Clase base abstracta para dividir contenido grande en porciones.

    Subclases concretas:
    - `DocumentoDivisor`: para PDFs (particiona por páginas).
    - Futuras: `BusquedaDivisor` para particionar por bloques temáticos.
    """

    @abstractmethod
    def particionar(
        self,
        contenido_path: Path | str,
        max_tokens_por_porcion: int = MAX_TOKENS_POR_SUBAGENTE_N2,
    ) -> list[Porcion]:
        """Divide un contenido en porciones manejables.

        Args:
            contenido_path: Ruta del archivo a particionar.
            max_tokens_por_porcion: Tokens máximos por porción.

        Returns:
            Lista de Porcion, cada una con ruta temporal y tokens estimados.
        """
        ...

    def lanzar_subagentes(
        self,
        porciones: list[Porcion],
        launcher: SubagentLauncher,
        max_paralelos: int = 3,
        prompt_builder: Optional[Callable[[Porcion], str]] = None,
    ) -> list[SubagentResponse]:
        """Lanza un subagente N2 por cada porción, en paralelo.

        Args:
            porciones: Lista de porciones a procesar.
            launcher: SubagentLauncher para invocar los Tasks.
            max_paralelos: Máximo de subagentes en paralelo.
            prompt_builder: Función que construye el prompt para cada porción.
                Si es None, usa un prompt por defecto.

        Returns:
            Lista de SubagentResponse en el mismo orden que las porciones.
        """
        if not porciones:
            return []

        if prompt_builder is None:
            prompt_builder = self._default_prompt_builder

        # Lazy import para evitar import circular
        from contexto_zai.subagents.launcher import SubagentRequest

        requests = [
            SubagentRequest(
                prompt=prompt_builder(p),
                files_to_read=[p.contenido_path] if p.contenido_path else [],
                description=f"Procesar porción {p.id} ({p.paginas_str})",
            )
            for p in porciones
        ]

        logger.info(
            "Lanzando %d subagentes N2 en paralelo (max_paralelos=%d)",
            len(porciones), max_paralelos,
        )
        responses = launcher.launch_parallel(requests, max_workers=max_paralelos)
        return responses

    @staticmethod
    def _default_prompt_builder(porcion: Porcion) -> str:
        """Prompt por defecto para procesar una porción."""
        return f"""Eres un subagente clasificador de documentos (Nivel 2).
Lee la porción {porcion.id} del documento ({porcion.paginas_str}, ~{porcion.tokens_estimados} tokens)
y haz lo siguiente:

1. Lee el archivo indicado.
2. Identifica los temas principales de esta porción.
3. Genera un resumen breve de esta porción (máximo 200 caracteres).
4. Lista los temas con sus secciones.

Formato de respuesta EXACTO:

RESUMEN: <resumen breve de la porción>

TEMA: <nombre_snake_case>
DESCRIPCION: <descripción corta>
SECCIONES: <sección1, sección2>

(Repetir TEMA/DESCRIPCION/SECCIONES por cada tema detectado)

Respuesta:"""


class DocumentoDivisor(Divisor):
    """Divisor concreto para documentos PDF (v3.6).

    Usa pdfplumber para contar páginas y estimar tokens por página.
    Agrupa páginas en porciones que no superen max_tokens_por_porcion.
    """

    def particionar(
        self,
        contenido_path: Path | str,
        max_tokens_por_porcion: int = MAX_TOKENS_POR_SUBAGENTE_N2,
    ) -> list[Porcion]:
        """Particiona un PDF por páginas hasta alcanzar max_tokens_por_porcion.

        Args:
            contenido_path: Ruta del archivo PDF.
            max_tokens_por_porcion: Tokens máximos por porción (default 30K).

        Returns:
            Lista de Porcion, cada una con un rango de páginas.
        """
        contenido_path = Path(contenido_path)
        if not contenido_path.exists():
            logger.warning("Archivo no encontrado: %s", contenido_path)
            return []

        try:
            import pdfplumber
        except ImportError:
            logger.error("pdfplumber no está instalado. No se puede particionar PDF.")
            return []

        try:
            with pdfplumber.open(contenido_path) as pdf:
                total_paginas = len(pdf.pages)
                # Estimar tokens por página (muestrear primeras 5 páginas)
                tokens_por_pagina = self._estimate_tokens_per_page(pdf, sample=5)

                logger.info(
                    "PDF: %d páginas, ~%d tokens/página = ~%d tokens totales",
                    total_paginas, tokens_por_pagina,
                    total_paginas * tokens_por_pagina,
                )

                # Calcular páginas por porción
                paginas_por_porcion = max(1, max_tokens_por_porcion // max(1, tokens_por_pagina))

                porciones: list[Porcion] = []
                porcion_id = 0
                pag_actual = 1

                while pag_actual <= total_paginas:
                    porcion_id += 1
                    pag_fin = min(pag_actual + paginas_por_porcion - 1, total_paginas)
                    tokens_estimados = (pag_fin - pag_actual + 1) * tokens_por_pagina

                    porcion = Porcion(
                        id=porcion_id,
                        contenido_path=str(contenido_path),
                        tokens_estimados=tokens_estimados,
                        pagina_inicio=pag_actual,
                        pagina_fin=pag_fin,
                    )
                    porciones.append(porcion)
                    pag_actual = pag_fin + 1

                logger.info(
                    "PDF particionado en %d porciones (max %d tokens/porción, ~%d páginas/porción)",
                    len(porciones), max_tokens_por_porcion, paginas_por_porcion,
                )
                return porciones

        except Exception as e:
            logger.error("Error particionando PDF %s: %s", contenido_path, e)
            return []

    @staticmethod
    def _estimate_tokens_per_page(pdf, sample: int = 5) -> int:
        """Estima tokens por página muestreando las primeras N páginas.

        Args:
            pdf: Objeto pdfplumber.PDF abierto.
            sample: Número de páginas a muestrear.

        Returns:
            Promedio de tokens por página (mínimo 100).
        """
        total_chars = 0
        pages_sampled = 0
        for i, page in enumerate(pdf.pages):
            if i >= sample:
                break
            text = page.extract_text() or ""
            total_chars += len(text)
            pages_sampled += 1

        if pages_sampled == 0:
            return 500  # estimación por defecto

        avg_chars = total_chars / pages_sampled
        # 3.5 chars/token (promedio español/código)
        avg_tokens = int(avg_chars / 3.5)
        return max(100, avg_tokens)  # mínimo 100 tokens por página

    def __repr__(self) -> str:
        return f"DocumentoDivisor(max_tokens={MAX_TOKENS_POR_SUBAGENTE_N2})"


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

    print("=== Validacion de divisor.py ===\n")

    import tempfile

    # Test 1: DocumentoDivisor con PDF real (CZAI-01.pdf si existe)
    czai_pdf = Path("/home/z/my-project/contexto_zai/Documentación/CZAI-01.pdf")
    divisor = DocumentoDivisor()  # crear siempre para que repr funcione
    if czai_pdf.exists():
        porciones = divisor.particionar(czai_pdf, max_tokens_por_porcion=30000)
        assert len(porciones) > 0, "Debe particionar el PDF real"
        print(f"[OK] PDF real particionado: {len(porciones)} porciones")
        for p in porciones[:3]:
            print(f"  Porción {p.id}: {p.paginas_str}, ~{p.tokens_estimados} tokens")
        if len(porciones) > 3:
            print(f"  ... y {len(porciones) - 3} más")
    else:
        print("[SKIP] CZAI-01.pdf no encontrado, saltando test con PDF real")

    # Test 2: particionar archivo inexistente
    divisor2 = DocumentoDivisor()
    porciones2 = divisor2.particionar("/tmp/no_existe.pdf")
    assert porciones2 == []
    print(f"[OK] Archivo inexistente: lista vacía")

    # Test 3: particionar archivo no-PDF
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Texto de prueba\n" * 100)
        f.flush()
        txt_path = f.name

    porciones3 = divisor2.particionar(txt_path)
    # txt no es PDF, pdfplumber fallará y devolverá []
    assert porciones3 == []
    print(f"[OK] Archivo no-PDF: lista vacía (esperado)")

    # Test 4: lanzar_subagentes con mock launcher
    # Evitar import circular: definir mock local completo sin importar desde subagents
    class MockResponse:
        def __init__(self, content, success=True, error=""):
            self.content = content
            self.success = success
            self.error = error

    class MockRequest:
        def __init__(self, prompt, files_to_read=None, description=""):
            self.prompt = prompt
            self.files_to_read = files_to_read or []
            self.description = description

    class MockLauncher:
        def __init__(self, task_invoker=None):
            self._invoker = task_invoker
        def launch_parallel(self, requests, max_workers=3):
            responses = []
            for req in requests:
                content = self._invoker(req.prompt) if self._invoker else "ok"
                responses.append(MockResponse(content=content, success=True))
            return responses

    def mock_invoker(prompt: str) -> str:
        return "RESUMEN: Porción procesada\n\nTEMA: tema_test\nDESCRIPCION: desc\nSECCIONES: s1, s2"

    launcher = MockLauncher(task_invoker=mock_invoker)
    divisor3 = DocumentoDivisor()
    porciones4 = [
        Porcion(id=1, contenido_path="/tmp/p1.pdf", tokens_estimados=25000, pagina_inicio=1, pagina_fin=50),
        Porcion(id=2, contenido_path="/tmp/p2.pdf", tokens_estimados=25000, pagina_inicio=51, pagina_fin=100),
        Porcion(id=3, contenido_path="/tmp/p3.pdf", tokens_estimados=25000, pagina_inicio=101, pagina_fin=150),
    ]
    responses = divisor3.lanzar_subagentes(porciones4, launcher, max_paralelos=3)
    assert len(responses) == 3
    assert all(r.success for r in responses)
    print(f"[OK] lanzar_subagentes: 3 subagentes N2 en paralelo")

    # Test 5: lanzar_subagentes con lista vacía
    assert divisor3.lanzar_subagentes([], launcher) == []
    print(f"[OK] lanzar_subagentes: lista vacía devuelve []")

    # Test 6: lanzar_subagentes con prompt_builder custom
    def custom_prompt(porcion):
        return f"Custom prompt para porción {porcion.id}"

    responses2 = divisor3.lanzar_subagentes(
        porciones4[:2], launcher, max_paralelos=2, prompt_builder=custom_prompt,
    )
    assert len(responses2) == 2
    assert all(r.success for r in responses2)
    print(f"[OK] lanzar_subagentes con prompt_builder custom: 2 subagentes")

    # Test 7: _default_prompt_builder
    p_test = Porcion(id=1, contenido_path="/tmp/test.pdf", tokens_estimados=5000, pagina_inicio=1, pagina_fin=10)
    prompt = Divisor._default_prompt_builder(p_test)
    assert "porción 1" in prompt or "porci" in prompt.lower()
    assert "páginas 1-10" in prompt
    assert "RESUMEN:" in prompt
    assert "TEMA:" in prompt
    print(f"[OK] _default_prompt_builder: incluye id, páginas y formato")

    # Test 8: DocumentoDivisor con max_tokens pequeño
    if czai_pdf.exists():
        porciones_small = divisor.particionar(czai_pdf, max_tokens_por_porcion=5000)
        # Con max_tokens=5000, debería haber más porciones que con 30000
        if len(porciones) > 0 and len(porciones_small) > 0:
            assert len(porciones_small) >= len(porciones), \
                f"Con max_tokens=5000 debe haber >= porciones que con 30000: {len(porciones_small)} vs {len(porciones)}"
            print(f"[OK] max_tokens=5000: {len(porciones_small)} porciones (>= {len(porciones)} con 30K)")

    # Test 9: repr
    r = repr(divisor)
    assert "DocumentoDivisor" in r
    print(f"[OK] repr: {r}")

    print("\n[PASS] divisor.py: todos los tests pasaron")
