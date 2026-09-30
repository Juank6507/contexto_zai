# client/web_reader.py -- Lector de contenido externo via link: descarga una URL y la convierte en texto para el proceso.
"""Lector de links externos (v3.4).

Permite al Director entregar un link (articulo, metodologia,
documento) escrito en el chat. El proceso lo detecta, lo lee
y lo procesa como un intercambio mas.

Usa httpx para descargar la pagina y limpieza HTML para
convertirla a texto plano.

Atomica standalone: no importa otros modulos del proyecto.
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
import re
from dataclasses import dataclass
from typing import Optional

# v3.4: URL_PATTERN se centraliza en config.py para configuración sin tocar código.
try:
    from contexto_zai.config import URL_PATTERN as _CONFIG_URL_PATTERN
    _DEFAULT_URL_PATTERN = _CONFIG_URL_PATTERN
except ImportError:
    _DEFAULT_URL_PATTERN = re.compile(r'https?://[^\s<>"\']+')

logger = logging.getLogger(__name__)


@dataclass
class ExternalContent:
    """Contenido externo leido desde un link.

    Attributes:
        url: URL original del link.
        title: Titulo del documento extraido.
        content: Contenido en texto plano.
        source: Fuente del contenido (httpx, etc.).
    """

    url: str
    title: str = ""
    content: str = ""
    source: str = ""

    @property
    def estimated_tokens(self) -> float:
        return len(self.content) / 3.5


class WebReader:
    """Lee contenido externo via link y lo convierte en texto.

    Usage:
        >>> reader = WebReader()
        >>> content = reader.read("https://ejemplo.com/articulo")
        >>> print(content.title)
    """

    URL_PATTERN = _DEFAULT_URL_PATTERN
    TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
    SCRIPT_PATTERN = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
    STYLE_PATTERN = re.compile(r"<style[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
    TAG_PATTERN = re.compile(r"<[^>]+>")
    WHITESPACE_PATTERN = re.compile(r"\s+")

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout
        logger.debug("WebReader inicializado: timeout=%s", timeout)

    # ── API publica ────────────────────────────────────────────

    def read(self, url: str) -> ExternalContent:
        """Lee el contenido de una URL y lo convierte en texto.

        Args:
            url: URL del documento a leer.

        Returns:
            ExternalContent con el titulo, contenido y fuente.
        """
        if not url or not url.startswith("http"):
            return ExternalContent(url=url or "", title="URL invalida", content="", source="error")

        try:
            return self._read_with_httpx(url)
        except Exception as e:
            logger.error("Error leyendo URL %s: %s", url, e)
            return ExternalContent(url=url, title="Error al leer", content=f"No se pudo leer {url}: {e}", source="error")

    def read_many(self, urls: list[str]) -> list[ExternalContent]:
        """Lee multiples URLs."""
        return [self.read(url) for url in urls]

    @staticmethod
    def find_urls(text: str) -> list[str]:
        """Busca URLs en un texto.

        Args:
            text: Texto donde buscar URLs.

        Returns:
            Lista de URLs encontradas (sin duplicados, en orden).
        """
        if not text:
            return []
        urls = WebReader.URL_PATTERN.findall(text)
        # Deduplicar manteniendo orden
        seen = set()
        unique = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique.append(url)
        return unique

    def __repr__(self) -> str:
        return f"WebReader(timeout={self._timeout})"

    # ── Metodos privados ───────────────────────────────────────

    def _read_with_httpx(self, url: str) -> ExternalContent:
        """Lee una URL usando httpx y limpia el HTML."""
        import httpx

        response = httpx.get(
            url,
            timeout=self._timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ContextoZAI/3.4)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        response.raise_for_status()

        html = response.text
        title = self._extract_title(html)
        content = self._html_to_text(html)

        return ExternalContent(
            url=url,
            title=title,
            content=content,
            source="httpx",
        )

    def _extract_title(self, html: str) -> str:
        """Extrae el titulo de una pagina HTML."""
        match = self.TITLE_PATTERN.search(html)
        if match:
            title = match.group(1).strip()
            title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            return title
        return "Sin titulo"

    def _html_to_text(self, html: str) -> str:
        """Convierte HTML a texto plano limpio."""
        html = self.SCRIPT_PATTERN.sub("", html)
        html = self.STYLE_PATTERN.sub("", html)
        text = self.TAG_PATTERN.sub(" ", html)
        text = text.replace("&amp;", "&").replace("&lt;", "<")
        text = text.replace("&gt;", ">").replace("&nbsp;", " ")
        text = text.replace("&quot;", '"').replace("&#39;", "'")
        text = self.WHITESPACE_PATTERN.sub(" ", text).strip()
        return text


if __name__ == "__main__":
    import io as _io
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass

    print("=== Validacion de web_reader.py ===\n")

    reader = WebReader()

    # Test 1: URL vacia
    result = reader.read("")
    assert result.source == "error"
    assert "invalida" in result.title.lower()
    print("[OK] URL vacia: error manejado")

    # Test 2: URL invalida (sin http)
    result = reader.read("no-es-una-url")
    assert result.source == "error"
    print("[OK] URL invalida: error manejado")

    # Test 3: find_urls con texto
    text = "Hola mira este link https://ejemplo.com/articulo y este https://otro.com/doc"
    urls = WebReader.find_urls(text)
    assert len(urls) == 2
    assert "https://ejemplo.com/articulo" in urls
    assert "https://otro.com/doc" in urls
    print(f"[OK] find_urls: {len(urls)} URLs encontradas")

    # Test 4: find_urls con duplicados
    text2 = "https://ejemplo.com https://ejemplo.com https://otro.com"
    urls2 = WebReader.find_urls(text2)
    assert len(urls2) == 2
    print(f"[OK] find_urls deduplica: {len(urls2)} URLs unicas")

    # Test 5: find_urls con texto vacio
    assert WebReader.find_urls("") == []
    print("[OK] find_urls con texto vacio: []")

    # Test 6: _extract_title
    html = "<html><head><title>Mi Articulo</title></head><body>Hola</body></html>"
    title = reader._extract_title(html)
    assert title == "Mi Articulo"
    print(f"[OK] _extract_title: '{title}'")

    # Test 7: _html_to_text
    html = "<html><body><p>Hola</p><p>Mundo</p></body></html>"
    text = reader._html_to_text(html)
    assert "Hola" in text
    assert "Mundo" in text
    assert "<" not in text
    print("[OK] _html_to_text: texto limpio")

    # Test 8: _html_to_text elimina scripts
    html = "<html><body><script>alert('xss')</script><p>Texto</p></body></html>"
    text = reader._html_to_text(html)
    assert "alert" not in text
    assert "Texto" in text
    print("[OK] _html_to_text: scripts eliminados")

    # Test 9: _html_to_text elimina estilos
    html = "<html><head><style>.x{color:red}</style></head><body><p>Texto</p></body></html>"
    text = reader._html_to_text(html)
    assert "color" not in text
    assert "Texto" in text
    print("[OK] _html_to_text: estilos eliminados")

    # Test 10: ExternalContent
    ec = ExternalContent(url="https://ejemplo.com", title="Test", content="Hola mundo")
    assert ec.url == "https://ejemplo.com"
    assert ec.estimated_tokens > 0
    print(f"[OK] ExternalContent: {ec.estimated_tokens:.0f} tokens")

    # Test 11: read_many
    results = reader.read_many(["", "no-url"])
    assert len(results) == 2
    print(f"[OK] read_many: {len(results)} resultados")

    print("\n[PASS] web_reader.py: todos los tests pasaron")
