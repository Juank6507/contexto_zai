# contexto_zai/processing/conciliador.py -- Clase base abstracta Conciliador + DocumentoConciliador (v3.6).
"""Conciliador de índices parciales (v3.6).

Clase base abstracta `Conciliador` que define la interfaz para
combinar los índices parciales devueltos por los subagentes N2
en un índice consolidado.

Implementación concreta `DocumentoConciliador` que combina los
índices parciales de un documento grande, deduplica temas similares
y genera un resumen final coherente.

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
import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from contexto_zai.config import DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS
from contexto_zai.models import IndiceConsolidado, IndiceParcial

if TYPE_CHECKING:
    # Evitar import circular: conciliador.py ← subagents/__init__.py ← conciliador_subagent.py ← conciliador.py
    from contexto_zai.subagents.launcher import SubagentResponse

logger = logging.getLogger(__name__)


@dataclass
class ThemeSection:
    """Sección temática detectada (reutilizada de documento_indexer_subagent).

    Attributes:
        tema: Nombre del tema (snake_case).
        descripcion: Descripción corta del tema.
        secciones: Lista de secciones o subtemas dentro del tema.
    """

    tema: str
    descripcion: str = ""
    secciones: list[str] = field(default_factory=list)


class Conciliador(ABC):
    """Clase base abstracta para conciliar índices parciales.

    Subclases concretas:
    - `DocumentoConciliador`: para índices de documentos grandes.
    - Futuras: `BusquedaConciliador` para combinar resultados de búsqueda.
    """

    @abstractmethod
    def conciliar(
        self,
        respuestas: list[SubagentResponse],
        indices_parciales: list[IndiceParcial] = None,
    ) -> IndiceConsolidado:
        """Combina índices parciales en un índice consolidado.

        Args:
            respuestas: Lista de SubagentResponse de los N2.
            indices_parciales: Lista de IndiceParcial (opcional, si ya están parseados).

        Returns:
            IndiceConsolidado con temas consolidados (sin duplicados).
        """
        ...

    @abstractmethod
    def producir_resumen_final(
        self,
        consolidado: IndiceConsolidado,
    ) -> str:
        """Genera resumen final del documento completo.

        Args:
            consolidado: Índice consolidado con todos los temas.

        Returns:
            Resumen breve (≤ DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS chars).
        """
        ...

    @staticmethod
    def _sanitize_tema_name(name: str) -> str:
        """Convierte un nombre a snake_case válido."""
        if not name:
            return "tema"
        normalized = unicodedata.normalize("NFKD", name)
        ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
        ascii_str = ascii_str.lower()
        sanitized = re.sub(r"[^a-z0-9]+", "_", ascii_str)
        return sanitized.strip("_") or "tema"

    @staticmethod
    def _normalize_tema_for_dedup(tema: str) -> str:
        """Normaliza un nombre de tema para comparación de duplicados.

        Elimina acentos, convierte a minúsculas, reemplaza separadores.
        """
        normalized = unicodedata.normalize("NFKD", tema)
        ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
        ascii_str = ascii_str.lower()
        # Quitar separadores y sufijos comunes
        normalized_str = re.sub(r"[_\-\s]+", "", ascii_str)
        # Quitar sufijos comunes como "s", "es" (plurales)
        # (no hacemos stemming completo, solo comparación directa sin separadores)
        return normalized_str


class DocumentoConciliador(Conciliador):
    """Conciliador concreto para índices de documentos grandes (v3.6).

    Combina los índices parciales devueltos por los subagentes N2,
    deduplica temas similares (ej: "auth_jwt" y "autenticacion_jwt" →
    fusiona si la normalización coincide), y genera un resumen final.
    """

    def conciliar(
        self,
        respuestas: list[SubagentResponse],
        indices_parciales: list[IndiceParcial] = None,
    ) -> IndiceConsolidado:
        """Combina índices parciales de N2 en un índice consolidado.

        Args:
            respuestas: Lista de SubagentResponse de los N2.
            indices_parciales: Lista de IndiceParcial (opcional).

        Returns:
            IndiceConsolidado con temas consolidados (sin duplicados).
        """
        # 1. Parsear respuestas en índices parciales
        if indices_parciales is None:
            indices_parciales = []
            for i, resp in enumerate(respuestas):
                if not resp.success or not resp.content:
                    continue
                temas_parciales = self._parse_temas_from_response(resp.content)
                resumen_parcial = self._parse_resumen_from_response(resp.content)
                indices_parciales.append(IndiceParcial(
                    porcion_id=i + 1,
                    temas=temas_parciales,
                    resumen_parcial=resumen_parcial,
                ))

        # 2. Consolidar temas (deduplicación)
        temas_consolidados: list[ThemeSection] = []
        temas_vistos: dict[str, int] = {}  # nombre_normalizado -> índice en temas_consolidados

        for indice in indices_parciales:
            for tema in indice.temas:
                if not isinstance(tema, ThemeSection):
                    # Si es dict (de Pydantic), convertir
                    if isinstance(tema, dict):
                        tema = ThemeSection(
                            tema=tema.get("tema", ""),
                            descripcion=tema.get("descripcion", ""),
                            secciones=tema.get("secciones", []),
                        )
                    else:
                        continue

                nombre_normalizado = self._normalize_tema_for_dedup(tema.tema)

                if nombre_normalizado in temas_vistos:
                    # Tema duplicado: fusionar secciones
                    idx_existente = temas_vistos[nombre_normalizado]
                    existente = temas_consolidados[idx_existente]
                    # Añadir secciones nuevas (sin duplicados)
                    for sec in tema.secciones:
                        if sec not in existente.secciones:
                            existente.secciones.append(sec)
                    # Combinar descripciones si la existente es más corta
                    if len(tema.descripcion) > len(existente.descripcion):
                        existente.descripcion = tema.descripcion
                    logger.debug(
                        "Tema '%s' fusionado con '%s' (%d secciones total)",
                        tema.tema, existente.tema, len(existente.secciones),
                    )
                else:
                    # Tema nuevo
                    temas_vistos[nombre_normalizado] = len(temas_consolidados)
                    temas_consolidados.append(ThemeSection(
                        tema=self._sanitize_tema_name(tema.tema),
                        descripcion=tema.descripcion,
                        secciones=list(tema.secciones),
                    ))

        # 3. Generar resumen final
        resumen_final = self.producir_resumen_final(
            IndiceConsolidado(
                temas_consolidados=temas_consolidados,
                indices_parciales=indices_parciales,
            )
        )

        logger.info(
            "Conciliación: %d índices parciales → %d temas consolidados",
            len(indices_parciales), len(temas_consolidados),
        )

        return IndiceConsolidado(
            temas_consolidados=temas_consolidados,
            resumen_final=resumen_final,
            indices_parciales=indices_parciales,
        )

    def producir_resumen_final(
        self,
        consolidado: IndiceConsolidado,
    ) -> str:
        """Genera resumen breve del documento completo.

        Sintetiza los temas consolidados en un resumen coherente.

        Args:
            consolidado: Índice consolidado con todos los temas.

        Returns:
            Resumen breve (≤ DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS chars).
        """
        if not consolidado.indices_parciales and not consolidado.temas_consolidados:
            return ""

        # Recopilar resúmenes parciales
        resumenes_parciales = [
            ip.resumen_parcial for ip in consolidado.indices_parciales
            if ip.resumen_parcial
        ]

        if resumenes_parciales:
            # Combinar los resúmenes parciales en uno final
            tema_nombres = [t.tema for t in consolidado.temas_consolidados[:5]]
            temas_str = ", ".join(tema_nombres) if tema_nombres else "sin temas específicos"

            resumen = (
                f"Documento procesado en {len(consolidado.indices_parciales)} partes. "
                f"Temas principales: {temas_str}. "
            )
            # Añadir primer resumen parcial como contexto
            if resumenes_parciales:
                resumen += resumenes_parciales[0][:200]
        else:
            # Sin resúmenes parciales, generar desde temas
            tema_nombres = [t.tema for t in consolidado.temas_consolidados[:5]]
            resumen = f"Documento con {len(consolidado.temas_consolidados)} temas: {', '.join(tema_nombres)}."

        # Truncar si excede el máximo
        if len(resumen) > DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS:
            resumen = resumen[:DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS - 3] + "..."

        return resumen

    @staticmethod
    def _parse_temas_from_response(content: str) -> list[ThemeSection]:
        """Parsea los temas de la respuesta de un subagente N2.

        Formato esperado:
            TEMA: <nombre>
            DESCRIPCION: <desc>
            SECCIONES: <s1, s2>
        """
        pattern = re.compile(
            r"TEMA:\s*(\S+)\s*\n\s*DESCRIPCION:\s*(.+?)\s*\n\s*SECCIONES:\s*(.+?)(?=\n\s*TEMA:|\Z)",
            re.DOTALL,
        )

        temas: list[ThemeSection] = []
        for match in pattern.finditer(content):
            nombre = match.group(1).strip()
            descripcion = match.group(2).strip()
            secciones_str = match.group(3).strip()

            nombre = Conciliador._sanitize_tema_name(nombre)
            secciones = [s.strip() for s in secciones_str.split(",") if s.strip()]

            if nombre:
                temas.append(ThemeSection(
                    tema=nombre,
                    descripcion=descripcion,
                    secciones=secciones,
                ))

        return temas

    @staticmethod
    def _parse_resumen_from_response(content: str) -> str:
        """Extrae el resumen de la respuesta de un subagente N2.

        Formato esperado:
            RESUMEN: <texto>
        """
        match = re.search(r"RESUMEN:\s*(.+?)(?=\n\s*TEMA:|\Z)", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    def __repr__(self) -> str:
        return f"DocumentoConciliador(max_resumen={DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS})"


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

    print("=== Validacion de conciliador.py ===\n")

    conciliador = DocumentoConciliador()

    # Test 1: conciliar 3 respuestas con temas diferentes
    # Construir respuestas mock sin importar SubagentResponse (evitar circular import)
    class MockResponse:
        def __init__(self, content, success=True, error=""):
            self.content = content
            self.success = success
            self.error = error
    
    respuestas = [
        MockResponse(content="""RESUMEN: Porción 1 sobre autenticación.

TEMA: auth_jwt
DESCRIPCION: Sistema de autenticación JWT
SECCIONES: login, logout, refresh

TEMA: config_db
DESCRIPCION: Configuración de base de datos
SECCIONES: sqlite, prisma
""", success=True),
        MockResponse(content="""RESUMEN: Porción 2 sobre validaciones.

TEMA: validaciones_pytest
DESCRIPCION: Tests con pytest
SECCIONES: unitarias, integracion

TEMA: auth_jwt
DESCRIPCION: Sistema de autenticación JWT (más detalle)
SECCIONES: login, cookie, refresh
""", success=True),
        MockResponse(content="""RESUMEN: Porción 3 sobre documentación.

TEMA: documentacion
DESCRIPCION: Specs y manuales
SECCIONES: spec_v3, manual
""", success=True),
    ]

    consolidado = conciliador.conciliar(respuestas)

    # Debe tener 4 temas únicos (auth_jwt se fusiona)
    assert len(consolidado.temas_consolidados) == 4, \
        f"Debe tener 4 temas únicos, got {len(consolidado.temas_consolidados)}"
    print(f"[OK] 3 respuestas → 4 temas consolidados (auth_jwt fusionado)")

    # auth_jwt debe tener secciones combinadas
    auth_jwt = next(t for t in consolidado.temas_consolidados if t.tema == "auth_jwt")
    assert "login" in auth_jwt.secciones
    assert "logout" in auth_jwt.secciones
    assert "cookie" in auth_jwt.secciones
    assert "refresh" in auth_jwt.secciones
    print(f"[OK] auth_jwt fusionado: {len(auth_jwt.secciones)} secciones combinadas")

    # Test 2: resumen final
    resumen = consolidado.resumen_final
    assert len(resumen) > 0
    assert len(resumen) <= 500
    print(f"[OK] Resumen final: {len(resumen)} chars")

    # Test 3: conciliar lista vacía
    consolidado_empty = conciliador.conciliar([])
    assert len(consolidado_empty.temas_consolidados) == 0
    assert consolidado_empty.resumen_final == ""
    print(f"[OK] Lista vacía: 0 temas, resumen vacío")

    # Test 4: respuesta sin temas (mal formada)
    resp_malformed = [MockResponse(content="No tiene formato", success=True)]
    consolidado_malformed = conciliador.conciliar(resp_malformed)
    assert len(consolidado_malformed.temas_consolidados) == 0
    print(f"[OK] Respuesta mal formada: 0 temas")

    # Test 5: respuesta con error
    resp_error = [MockResponse(content="", success=False, error="Task failed")]
    consolidado_error = conciliador.conciliar(resp_error)
    assert len(consolidado_error.temas_consolidados) == 0
    print(f"[OK] Respuesta con error: 0 temas")

    # Test 6: deduplicación con nombres similares
    resp_similar = [
        MockResponse(content="""RESUMEN: Test.

TEMA: autenticacion_jwt
DESCRIPCION: Auth JWT
SECCIONES: s1
""", success=True),
        MockResponse(content="""RESUMEN: Test 2.

TEMA: auth_jwt
DESCRIPCION: Auth JWT (variación)
SECCIONES: s2
""", success=True),
    ]
    consolidado_similar = conciliador.conciliar(resp_similar)
    # "autenticacion_jwt" y "auth_jwt" normalizan diferente (autenticacionjwt vs authjwt)
    # así que NO se fusionan. Son 2 temas diferentes.
    assert len(consolidado_similar.temas_consolidados) == 2, \
        f"Debe tener 2 temas (no se fusionan porque normalizan diferente), got {len(consolidado_similar.temas_consolidados)}"
    print(f"[OK] Nombres similares pero diferentes: 2 temas (no fusionados)")

    # Test 7: _sanitize_tema_name
    assert Conciliador._sanitize_tema_name("Auth JWT!") == "auth_jwt"
    assert Conciliador._sanitize_tema_name("Configuración DB") == "configuracion_db"
    assert Conciliador._sanitize_tema_name("Tema-Con-Guiones") == "tema_con_guiones"
    print(f"[OK] _sanitize_tema_name: snake_case correcto")

    # Test 8: _normalize_tema_for_dedup
    assert Conciliador._normalize_tema_for_dedup("auth_jwt") == "authjwt"
    assert Conciliador._normalize_tema_for_dedup("auth-jwt") == "authjwt"
    assert Conciliador._normalize_tema_for_dedup("Auth JWT") == "authjwt"
    print(f"[OK] _normalize_tema_for_dedup: normalización correcta")

    # Test 9: _parse_temas_from_response
    temas = DocumentoConciliador._parse_temas_from_response("""TEMA: tema1
DESCRIPCION: desc1
SECCIONES: s1, s2

TEMA: tema2
DESCRIPCION: desc2
SECCIONES: s3""")
    assert len(temas) == 2
    assert temas[0].tema == "tema1"
    assert temas[1].tema == "tema2"
    print(f"[OK] _parse_temas_from_response: 2 temas parseados")

    # Test 10: _parse_resumen_from_response
    resumen = DocumentoConciliador._parse_resumen_from_response("""RESUMEN: Resumen de prueba.

TEMA: tema1
DESCRIPCION: desc""")
    assert "Resumen de prueba" in resumen
    print(f"[OK] _parse_resumen_from_response: resumen extraído")

    # Test 11: producir_resumen_final directo
    consolidado_directo = IndiceConsolidado(
        temas_consolidados=[
            ThemeSection(tema="tema1", descripcion="desc1", secciones=["s1"]),
            ThemeSection(tema="tema2", descripcion="desc2", secciones=["s2"]),
        ],
    )
    resumen_directo = conciliador.producir_resumen_final(consolidado_directo)
    assert "tema1" in resumen_directo
    assert "tema2" in resumen_directo
    print(f"[OK] producir_resumen_final: {len(resumen_directo)} chars")

    # Test 12: repr
    r = repr(conciliador)
    assert "DocumentoConciliador" in r
    print(f"[OK] repr: {r}")

    print("\n[PASS] conciliador.py: todos los tests pasaron")
