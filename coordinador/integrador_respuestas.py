# contexto_zai/coordinador/integrador_respuestas.py -- IntegradorRespuestas: aplica respuestas de subagentes a los archivos de recuperación.
"""IntegradorRespuestas (v4.2).

Aplica las respuestas de los subagentes a los archivos de recuperación
del workspace. Es el "integrador" que el ``Orquestador`` llama cuando
el agente invoca ``pipeline.collect_responses()``.

Lee las respuestas de ``_responses/``, las procesa según su propósito
(``estado.d4``, ``estado.a1_resumen``, ``decisiones``, ``subdivider.nombre``,
``consulta.bloque``, etc.), y actualiza los archivos correspondientes.

Atómico standalone: importa config, models, pathlib, logging y re.
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


import json
import logging
import re
from pathlib import Path
from typing import Optional

from contexto_zai.config import WORKSPACE_OUTPUT_DIR
from contexto_zai.models import SubagentResponse

logger = logging.getLogger(__name__)


def _registrar_tema_en_dict(tema_a_archivo: dict, tema: str, archivo: str) -> None:
    """v4.5: Registra un tema en un dict ``tema_a_archivo`` (formato multi-bloque).

    Si el tema no existe → crea ``[archivo]``.
    Si el tema existe y el archivo ya está → no hace nada (idempotente).
    Si el tema existe y el archivo no está → lo añade a la lista.

    Compatible con formato viejo (``dict[str, str]``): si el valor es ``str``,
    lo convierte a ``list``.
    """
    if tema not in tema_a_archivo:
        tema_a_archivo[tema] = [archivo]
        return
    valor = tema_a_archivo[tema]
    if isinstance(valor, str):
        # Formato viejo: convertir a lista
        if valor != archivo:
            tema_a_archivo[tema] = [valor, archivo]
        else:
            tema_a_archivo[tema] = [valor]
    elif isinstance(valor, list):
        if archivo not in valor:
            valor.append(archivo)
    else:
        tema_a_archivo[tema] = [archivo]


class IntegradorRespuestas:
    """Aplica respuestas de subagentes a los archivos de recuperación.

    Attributes:
        workspace_dir: Directorio del workspace con los archivos.

    Usage (Orquestador):
        >>> integrador = IntegradorRespuestas(workspace_dir="/path/to/ws")
        >>> resultado = orquestador.aplicar_respuestas(integrador=integrador)
    """

    # Mapeo de purpose → método integrador
    PURPOSE_HANDLERS = {
        "estado.d4": "_integrar_estado_d4",
        "estado.a1_resumen": "_integrar_estado_a1_resumen",
        "intercambios.restricciones_tema": "_integrar_estado_d4",
        "intercambios.resumen_truncado": "_integrar_estado_a1_resumen",
        "intercambios.decisiones": "_integrar_decisiones",
        "decisiones": "_integrar_decisiones",
        "intercambios.nombre_legible": "_integrar_subdivider_nombre",
        "subdivider.nombre": "_integrar_subdivider_nombre",
        "consulta.bloque": "_integrar_consulta",
        "documento.mediano": "_integrar_documento",
        "documento.grande": "_integrar_documento",
    }

    def __init__(self, workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR) -> None:
        self._workspace_dir = Path(workspace_dir)
        logger.debug("IntegradorRespuestas inicializado: %s", self._workspace_dir)

    @property
    def workspace_dir(self) -> Path:
        return self._workspace_dir

    # -- API pública ------------------------------------------------

    def integrar(
        self,
        responses: list[SubagentResponse],
        workspace_dir: Optional[Path | str] = None,
    ) -> dict:
        """Aplica las respuestas a los archivos de recuperación.

        Args:
            responses: Lista de SubagentResponse leídas de _responses/.
            workspace_dir: Directorio del workspace (sobreescribe el del constructor).

        Returns:
            Dict con:
            - "total_applied": número de respuestas aplicadas.
            - "estado_updated": True si se actualizó 00_estado_actual.md.
            - "decisiones_updated": True si se actualizó 02_decisiones_clave.md.
            - "metadata_updated": True si se actualizó _metadata.json.
            - "errores": lista de errores.
        """
        ws = Path(workspace_dir) if workspace_dir else self._workspace_dir

        resultado = {
            "total_applied": 0,
            "estado_updated": False,
            "decisiones_updated": False,
            "metadata_updated": False,
            "errores": [],
        }

        for resp in responses:
            if not resp.success:
                resultado["errores"].append(f"{resp.task_id}: {resp.error}")
                continue

            handler_method = self._get_handler(resp)
            if handler_method is None:
                logger.debug("Sin handler para %s (purpose desconocido)", resp.task_id)
                continue

            try:
                applied = handler_method(resp, ws)
                if applied:
                    resultado["total_applied"] += 1
            except Exception as e:
                msg = f"Error integrando {resp.task_id}: {e}"
                resultado["errores"].append(msg)
                logger.error(msg, exc_info=True)

        return resultado

    # -- Métodos privados -------------------------------------------

    def _get_handler(self, response: SubagentResponse):
        """Obtiene el método handler según el task_id o context del response."""
        task_id = response.task_id

        # Mapear task_id a handler (formatos del ProcesadorIntercambios y legacy)
        if "restricciones_tema" in task_id or "estado_d4" in task_id or "estado.d4" in task_id:
            return self._integrar_estado_d4
        elif "resumen_truncado" in task_id or "estado_a1_resumen" in task_id or "a1_resumen" in task_id:
            return self._integrar_estado_a1_resumen
        elif "decisiones" in task_id:
            return self._integrar_decisiones
        elif "nombre_legible" in task_id or "subdivider_nombre" in task_id:
            return self._integrar_subdivider_nombre
        elif "consulta" in task_id:
            return self._integrar_consulta
        elif "documento" in task_id:
            return self._integrar_documento
        elif "clasificacion_temas" in task_id or "capa3_" in task_id:
            return self._integrar_clasificacion_temas
        elif "sintesis_contexto" in task_id:
            return self._integrar_sintesis_contexto
        else:
            return None

    def _integrar_estado_d4(self, response: SubagentResponse, ws: Path) -> bool:
        """Actualiza la sección D4 en 00_estado_actual.md."""
        estado_path = ws / "00_estado_actual.md"
        if not estado_path.exists():
            return False

        content = estado_path.read_text(encoding="utf-8")
        new_d4 = self._format_d4_response(response.response)

        # Reemplazar la sección D4
        updated = self._replace_section(content, "D4", new_d4)
        if updated != content:
            estado_path.write_text(updated, encoding="utf-8")
            logger.info("D4 actualizada en 00_estado_actual.md")
            return True
        return False

    def _integrar_estado_a1_resumen(self, response: SubagentResponse, ws: Path) -> bool:
        """Añade el resumen a la sección A1 en 00_estado_actual.md."""
        estado_path = ws / "00_estado_actual.md"
        if not estado_path.exists():
            return False

        content = estado_path.read_text(encoding="utf-8")
        marker = "## Resumen del contenido truncado"
        resumen = response.response.strip()

        if marker in content:
            # Reemplazar bloque existente
            pattern = rf"({re.escape(marker)}[^\n]*\n\n)(.*?)(?=\n## |\Z)"
            updated = re.sub(pattern, rf"\g<1>{resumen}\n", content, flags=re.DOTALL)
        else:
            # Añadir al final
            updated = content + f"\n\n{marker}\n\n{resumen}\n"

        if updated != content:
            estado_path.write_text(updated, encoding="utf-8")
            logger.info("A1 resumen actualizado en 00_estado_actual.md")
            return True
        return False

    def _integrar_decisiones(self, response: SubagentResponse, ws: Path) -> bool:
        """Actualiza 02_decisiones_clave.md con las decisiones reales."""
        decisiones_path = ws / "02_decisiones_clave.md"
        if not decisiones_path.exists():
            return False

        decisions = self._parse_decisiones_response(response.response)
        if not decisions:
            return False

        content = self._format_decisiones_markdown(decisions)
        decisiones_path.write_text(content, encoding="utf-8")
        logger.info("02_decisiones_clave.md actualizado con %d decisiones", len(decisions))
        return True

    def _integrar_subdivider_nombre(self, response: SubagentResponse, ws: Path) -> bool:
        """Actualiza _metadata.json con el nombre legible."""
        metadata_path = ws / "_metadata.json"
        if not metadata_path.exists():
            return False

        # Extraer nombre temporal del task_id
        task_id = response.task_id
        # Formato legacy: subdivider_nombre_{nombre_temporal}
        if "subdivider_nombre_" in task_id:
            nombre_temporal = task_id.split("subdivider_nombre_", 1)[1]
        # Formato nuevo: intercambios_nombre_legible_{nombre_temporal}
        elif "nombre_legible_" in task_id:
            nombre_temporal = task_id.split("nombre_legible_", 1)[1]
        else:
            return False

        nombre_legible = response.response.strip().lower().replace(" ", "_")
        if not nombre_legible or len(nombre_legible) > 50:
            return False

        # Actualizar metadata
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            tema_a_archivo = metadata.get("tema_a_archivo", {})
            new_tema_a_archivo = {}
            for tema, archivo in tema_a_archivo.items():
                # Coincidencia exacta
                if tema == nombre_temporal:
                    new_tema_a_archivo[nombre_legible] = archivo
                # Coincidencia parcial: si el tema empieza con el nombre temporal
                elif tema.startswith(nombre_temporal + "_") or tema.startswith(nombre_temporal):
                    # Reemplazar solo la parte inicial
                    new_tema = nombre_legible + tema[len(nombre_temporal):]
                    new_tema_a_archivo[new_tema] = archivo
                else:
                    new_tema_a_archivo[tema] = archivo
            metadata["tema_a_archivo"] = new_tema_a_archivo
            metadata_path.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Metadata actualizada: '%s' → '%s' (coincidencia parcial)", nombre_temporal, nombre_legible)
            return True
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Error actualizando metadata: %s", e)
            return False

    def _integrar_consulta(self, response: SubagentResponse, ws: Path) -> bool:
        """Para consultas, la respuesta se entrega al agente, no se integra a archivos."""
        # La respuesta de consulta se devuelve directamente al agente vía el resultado
        # del Orquestador. No se escribe en ningún archivo.
        logger.debug("Respuesta de consulta lista para entregar al agente")
        return True

    def _integrar_sintesis_contexto(self, response: SubagentResponse, ws: Path) -> bool:
        """v4.3 (F2): Actualiza la sección ``G0.B`` del ``00_estado_actual.md``.

        La respuesta del subagente (modo ``SINTESIS_CONTEXTO``) es un texto
        plano con el panorama actual del proyecto. Se inserta o reemplaza
        en la sección ``## G0.B — Síntesis del contexto disponible`` del
        ``00_estado_actual.md``.

        Si el subagente respondió ``SIN_SINTESIS_POSIBLE``, no se modifica
        nada (el placeholder inicial se mantiene).
        """
        if not response.success or not response.response:
            logger.warning("sintesis_contexto: respuesta vacía o fallida: %s", response.task_id)
            return False

        raw = response.response.strip()
        if raw.upper().startswith("SIN_SINTESIS_POSIBLE"):
            logger.info("sintesis_contexto: subagente respondió SIN_SINTESIS_POSIBLE, no se actualiza")
            return False

        # Truncar si excede ~2.000 caracteres (defensivo)
        if len(raw) > 2000:
            raw = raw[:1997] + "..."

        estado_path = ws / "00_estado_actual.md"
        if not estado_path.exists():
            logger.warning("sintesis_contexto: 00_estado_actual.md no existe en %s", ws)
            return False

        content = estado_path.read_text(encoding="utf-8")
        marker = "## G0.B — Síntesis del contexto disponible"

        if marker in content:
            # Reemplazar el contenido de la sección G0.B existente.
            # La sección va hasta el próximo "## " header o fin de archivo.
            pattern = rf"({re.escape(marker)}[^\n]*\n\n)(.*?)(?=\n## |\Z)"
            updated = re.sub(pattern, rf"\g<1>{raw}\n", content, flags=re.DOTALL)
        else:
            # Insertar después de G0.A (si existe) o al inicio del archivo.
            g0_a_marker = "## G0.A — Objetivo del proyecto"
            if g0_a_marker in content:
                # Buscar el final de la sección G0.A
                pattern_g0a = rf"({re.escape(g0_a_marker)}[^\n]*\n\n)(.*?)(?=\n## |\Z)"
                def _insert_after_g0a(match):
                    return match.group(0) + f"\n{marker}\n\n{raw}\n"
                updated = re.sub(pattern_g0a, _insert_after_g0a, content, flags=re.DOTALL, count=1)
            else:
                # Insertar al inicio (después del título # si existe)
                if content.startswith("# "):
                    # Buscar el primer salto de línea después del título
                    first_newline = content.find("\n")
                    if first_newline > 0:
                        updated = (content[:first_newline+1] + f"\n{marker}\n\n{raw}\n" +
                                   content[first_newline+1:])
                    else:
                        updated = f"{marker}\n\n{raw}\n" + content
                else:
                    updated = f"{marker}\n\n{raw}\n" + content

        if updated != content:
            estado_path.write_text(updated, encoding="utf-8")
            logger.info("sintesis_contexto: G0.B actualizada en 00_estado_actual.md (%d chars)", len(raw))
            return True
        return False

    def _integrar_clasificacion_temas(self, response: SubagentResponse, ws: Path) -> bool:
        """Integra la respuesta de CLASIFICACION_TEMAS (Capa 3) al contexto.

        La respuesta contiene subtemas propuestos con IDs de intercambios.
        Se actualiza _metadata.json agregando los nuevos subtemas al mapeo
        tema_a_archivo, manteniendo el archivo del bloque original (la
        subdivisión física del archivo la hace el Subdivider en el próximo
        ciclo de recuperación, no aquí).

        Si el subagente respondió NO_SUBDIVISION, no se hace nada (el tema
        original se conserva intacto).
        """
        if not response.success or not response.response:
            logger.warning("CLASIFICACION_TEMAS: respuesta vacía: %s", response.task_id)
            return False

        raw = response.response.strip()
        if "NO_SUBDIVISION" in raw.upper():
            logger.info("CLASIFICACION_TEMAS: subagente respondió NO_SUBDIVISION, no se integra")
            return False

        # Parsear las propuestas de subtemas (mismo formato que IntercambiosClasificadorSubagent)
        pattern = re.compile(
            r"SUBTEMA:\s*(\S+)\s*\n\s*DESCRIPCION:\s*(.+?)\s*\n\s*EXCHANGES:\s*([\d,\s]+)",
            re.IGNORECASE,
        )
        propuestas = []
        for match in pattern.finditer(raw):
            nombre_raw = match.group(1).strip().lower()
            # Sanitizar a snake_case simple
            nombre = re.sub(r"[^a-z0-9]+", "_", nombre_raw).strip("_")
            descripcion = match.group(2).strip()
            try:
                ids = [
                    int(x.strip())
                    for x in match.group(3).split(",")
                    if x.strip().isdigit()
                ]
            except ValueError:
                ids = []
            if nombre:
                propuestas.append((nombre, descripcion, ids))

        if not propuestas:
            logger.warning("CLASIFICACION_TEMAS: no se parsearon subtemas de la respuesta")
            return False

        # Actualizar _metadata.json
        metadata_path = ws / "_metadata.json"
        if not metadata_path.exists():
            logger.warning("CLASIFICACION_TEMAS: _metadata.json no existe en %s", ws)
            return False

        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("CLASIFICACION_TEMAS: error leyendo metadata: %s", e)
            return False

        tema_a_archivo = metadata.get("tema_a_archivo", {})

        # Extraer tema_padre del task_id (formato: intercambios_clasificacion_temas_capa3_{tema})
        task_id = response.task_id
        tema_padre = ""
        if "capa3_" in task_id:
            tema_padre = task_id.split("capa3_", 1)[1]
        elif "clasificacion_temas_" in task_id:
            tema_padre = task_id.split("clasificacion_temas_", 1)[1]

        # Buscar el archivo del tema padre para asignarlo a los subtemas
        # v4.5: tema_a_archivo es dict[str, list[str]] — tomar el primer archivo
        valor_padre = tema_a_archivo.get(tema_padre, "")
        if isinstance(valor_padre, list) and valor_padre:
            archivo_padre = valor_padre[0]
        elif isinstance(valor_padre, str):
            archivo_padre = valor_padre
        else:
            archivo_padre = ""

        # Agregar cada subtema al mapeo (sin sobrescribir el tema padre:
        # el Subdivider físico se ejecuta en el próximo ciclo).
        nuevos = 0
        for nombre, _desc, _ids in propuestas:
            clave = f"{tema_padre}_{nombre}" if tema_padre else nombre
            if clave not in tema_a_archivo and archivo_padre:
                tema_a_archivo[clave] = archivo_padre
                nuevos += 1

        metadata["tema_a_archivo"] = tema_a_archivo
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(
            "CLASIFICACION_TEMAS: %d subtemas propuestos, %d nuevos en metadata (tema padre='%s')",
            len(propuestas), nuevos, tema_padre,
        )
        return nuevos > 0

    def _integrar_documento(self, response: SubagentResponse, ws: Path) -> bool:
        """Integra la respuesta de un subagente de documento al contexto.

        Guarda el bloque temático en el workspace y actualiza
        ``_metadata.json`` con el mapeo tema → archivo.

        v4.2 (unificación): los temas reales que el subagente indexador
        ya devuelve (formato ``TEMA: nombre / DESCRIPCION: ... / SECCIONES: ...``)
        se registran en ``tema_a_archivo`` con sus nombres semánticos —
        igual que los bloques del chat. Así ``query_context()`` los ve
        por igual, sin distinguir origen (chat vs. fuente externa).

        Si el subagente no devolvió temas parseables (respuesta mal
        formada o vacía), se cae a un nombre genérico para no perder
        el bloque.
        """
        if not response.success or not response.response:
            logger.warning("documento: respuesta vacía o fallida: %s", response.task_id)
            return False

        # Extraer info del context de la tarea
        task_id = response.task_id
        filename = task_id
        # Extraer nombre de archivo del task_id (formato: documento_{filename}_lote_N)
        # o documento_{filename}
        if "_lote_" in task_id:
            parts = task_id.split("_lote_")
            filename = parts[0].replace("documento_", "")
            lote_idx = int(parts[1]) if len(parts) > 1 else 0
        else:
            filename = task_id.replace("documento_", "")
            lote_idx = 0

        # Crear un bloque con el resumen
        bloque_filename = f"bloque_externo_{filename}_lote_{lote_idx}.md"
        bloque_path = ws / bloque_filename

        # Escribir el bloque
        content = f"# Bloque externo: {filename} (lote {lote_idx})\n\n"
        content += f"**Source:** ampliar_contexto (documento externo)\n"
        content += f"**Lote:** {lote_idx}\n\n"
        content += f"---\n\n{response.response}\n"
        bloque_path.write_text(content, encoding="utf-8")

        logger.info(
            "documento: bloque externo creado: %s (%d chars)",
            bloque_filename, len(response.response),
        )

        # v4.2: Parsear los temas reales que el subagente ya devuelve
        # (formato TEMA: nombre / DESCRIPCION: ... / SECCIONES: ...).
        # Estos temas son el equivalente semántico a los temas que
        # MessageClassifier extrae del chat — se registran igual.
        temas_reales = self._parse_temas_documento(response.response)

        # Actualizar _metadata.json
        metadata_path = ws / "_metadata.json"
        if metadata_path.exists():
            try:
                import json as _json
                metadata = _json.loads(metadata_path.read_text(encoding="utf-8"))
            except (ValueError, _json.JSONDecodeError):
                metadata = {}
        else:
            metadata = {}

        if "tema_a_archivo" not in metadata:
            metadata["tema_a_archivo"] = {}

        # v4.2: Registrar los temas reales en tema_a_archivo.
        # v4.5: tema_a_archivo es dict[str, list[str]] — un tema puede apuntar
        # a varios bloques. Usar la misma lógica que registrar_tema().
        temas_registrados: list[str] = []
        if temas_reales:
            for tema in temas_reales:
                clave = self._resolver_clave_tema(
                    tema_nombre=tema["nombre"],
                    filename=filename,
                    bloque_filename=bloque_filename,
                    tema_a_archivo=metadata["tema_a_archivo"],
                )
                # v4.5: registrar como lista (multi-bloque)
                _registrar_tema_en_dict(metadata["tema_a_archivo"], clave, bloque_filename)
                temas_registrados.append(clave)
        else:
            # Fallback: nombre genérico (compatibilidad con respuestas mal formadas)
            clave_generica = f"documento_externo_{filename}_lote_{lote_idx}"
            _registrar_tema_en_dict(metadata["tema_a_archivo"], clave_generica, bloque_filename)
            temas_registrados.append(clave_generica)
            logger.warning(
                "documento: sin temas reales parseables, usando nombre genérico '%s'",
                clave_generica,
            )

        # Registrar el source (información de procedencia, no de tema)
        if "archivo_a_source" not in metadata:
            metadata["archivo_a_source"] = {}
        metadata["archivo_a_source"][bloque_filename] = {
            "source_type": "file",
            "filename": filename,
            "lote": lote_idx,
            "temas": [t["nombre"] for t in temas_reales],
        }

        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        logger.info(
            "documento: metadata actualizada — %d tema(s) real(es) → '%s': %s",
            len(temas_registrados), bloque_filename, temas_registrados,
        )

        # v4.3 (F0.1): regenerar 01_indice_recuperacion.md para que incluya los
        # bloques externos (chat + externos). El IndiceGenerator prioriza la
        # metadata como fuente de verdad, así que solo necesita los bloques
        # físicos del workspace para calcular tamaños.
        self._regenerar_indice_recuperacion(ws, metadata)

        return True

    @staticmethod
    def _resolver_clave_tema(
        tema_nombre: str,
        filename: str,
        bloque_filename: str,
        tema_a_archivo: dict,
    ) -> str:
        """v4.3 (F0.2): Resuelve la clave del tema evitando entradas fantasma.

        Distingue 4 casos:

        1. ``tema_nombre`` existe y apunta al **mismo bloque** → idempotente,
           devolver ``tema_nombre`` (no crear entrada nueva).
        2. ``tema_nombre`` existe y apunta a **otro bloque** → intentar
           ``{filename}_{tema_nombre}``.
        3. ``{filename}_{tema_nombre}`` existe y apunta al **mismo bloque** →
           idempotente, devolver esa clave.
        4. ``{filename}_{tema_nombre}`` existe y apunta a **otro bloque** →
           sufijo numérico: ``{filename}_{tema_nombre}_2``, ``_3``, etc.
        5. Ninguna existe → usar ``tema_nombre`` (caso normal, sin colisión).

        Args:
            tema_nombre: Nombre del tema (snake_case).
            filename: Nombre del archivo fuente del documento (para prefijar).
            bloque_filename: Nombre del bloque externo físico (.md).
            tema_a_archivo: Mapeo tema → archivo actual (se modifica in-place
                solo si se añade una entrada nueva — la llamada ya lo hace).

        Returns:
            La clave a usar en ``tema_a_archivo`` (puede ser igual a una
            existente o nueva).
        """
        # Sanitizar filename para usarlo en la clave (sin espacios ni slashes)
        filename_safe = re.sub(r"[^a-zA-Z0-9_]+", "_", filename).strip("_").lower()

        # v4.5: función auxiliar para verificar si un valor apunta a un bloque
        # (compatible con formato viejo str y nuevo list[str])
        def _apunta_a(valor, bloque):
            if isinstance(valor, str):
                return valor == bloque
            elif isinstance(valor, list):
                return bloque in valor
            return False

        # Caso 1 y 5: tema_nombre no existe, o existe apuntando al mismo bloque
        existente = tema_a_archivo.get(tema_nombre)
        if existente is None:
            # Caso 5: no existe, usar tema_nombre
            return tema_nombre
        if _apunta_a(existente, bloque_filename):
            # Caso 1: existe pero apunta al mismo bloque, idempotente
            return tema_nombre

        # Caso 2: existe y apunta a otro bloque → probar con prefijo
        clave_prefijada = f"{filename_safe}_{tema_nombre}"
        existente_prefijada = tema_a_archivo.get(clave_prefijada)
        if existente_prefijada is None:
            # Caso 2: no existe la prefijada, usarla
            return clave_prefijada
        if _apunta_a(existente_prefijada, bloque_filename):
            # Caso 3: existe la prefijada y apunta al mismo bloque, idempotente
            return clave_prefijada

        # Caso 4: la prefijada existe y apunta a otro bloque → sufijo numérico
        sufijo = 2
        while True:
            clave_con_sufijo = f"{clave_prefijada}_{sufijo}"
            existente_sufijo = tema_a_archivo.get(clave_con_sufijo)
            if existente_sufijo is None:
                return clave_con_sufijo
            if _apunta_a(existente_sufijo, bloque_filename):
                return clave_con_sufijo
            sufijo += 1
            # Seguridad: evitar loop infinito (en la práctica, no debería pasar)
            if sufijo > 1000:
                return clave_con_sufijo

    @staticmethod
    def _regenerar_indice_recuperacion(ws: Path, metadata: dict) -> None:
        """v4.3 (F0.1): Regenera ``01_indice_recuperacion.md`` con todos los
        bloques del workspace (chat + externos).

        Usa el ``IndiceGenerator`` que ya existe en el proceso. Lee los
        bloques físicos del workspace y los pasa al generador junto con la
        metadata actualizada (que ya incluye los bloques externos nuevos).

        Si el ``IndiceGenerator`` falla (por ejemplo, workspace sin bloques
        físicos), loguea warning y continua — no rompe el flujo principal.
        """
        try:
            from contexto_zai.generation.indice_generator import IndiceGenerator
            from contexto_zai.models import ThematicBlock, RecoveryMetadata

            indice_gen = IndiceGenerator()

            # Construir ThematicBlock a partir de los archivos físicos del workspace
            # v4.5: tema_a_archivo es dict[str, list[str]] — iterar correctamente
            tema_a_archivo_raw = metadata.get("tema_a_archivo", {})
            blocks: list[ThematicBlock] = []
            archivos_vistos: set[str] = set()
            for tema, archivos in tema_a_archivo_raw.items():
                # v4.5: archivos puede ser str (viejo) o list[str] (nuevo)
                lista_archivos = archivos if isinstance(archivos, list) else [archivos]
                for archivo in lista_archivos:
                    if archivo in archivos_vistos:
                        continue
                    archivos_vistos.add(archivo)
                    bloque_path = ws / archivo
                    if not bloque_path.exists():
                        continue
                    # Construir ThematicBlock mínimo (solo filename + temas)
                    temas_en_este_archivo = [
                        t for t, archs in tema_a_archivo_raw.items()
                        if (archivo in archs if isinstance(archs, list) else archs == archivo)
                    ]
                    block = ThematicBlock(filename=archivo)
                    block._temas = list(temas_en_este_archivo)
                    blocks.append(block)

            # Construir RecoveryMetadata para que IndiceGenerator priorice metadata
            recovery_meta = RecoveryMetadata(
                chat_id=metadata.get("chat_id", ""),
                share_id=metadata.get("share_id", ""),
                tema_a_archivo=dict(tema_a_archivo_raw),
            )

            # Generar y escribir el índice
            indice_content = indice_gen.generate(
                blocks=blocks,
                metadata=recovery_meta,
                chat_label=metadata.get("chat_label", ""),
            )
            indice_path = ws / "01_indice_recuperacion.md"
            indice_path.write_text(indice_content, encoding="utf-8")

            logger.info(
                "documento: 01_indice_recuperacion.md regenerado con %d bloques (%d temas)",
                len(blocks), len(tema_a_archivo_raw),
            )
        except Exception as e:
            logger.warning(
                "documento: no se pudo regenerar 01_indice_recuperacion.md: %s", e
            )

    @staticmethod
    def _parse_temas_documento(raw: str) -> list[dict]:
        """Parsea los temas reales de la respuesta de un subagente indexador.

        Formato esperado (definido por DocumentoIndexerSubagent._build_prompt_historico):
            RESUMEN: <texto>

            TEMA: <nombre_snake_case>
            DESCRIPCION: <descripción corta>
            SECCIONES: <s1, s2, s3>

            TEMA: <nombre>
            ...

        Returns:
            Lista de dicts ``{"nombre": str, "descripcion": str, "secciones": list}``.
            Lista vacía si no se parsea ningún tema (respuesta mal formada).
        """
        if not raw:
            return []
        pattern = re.compile(
            r"TEMA:\s*(\S+)\s*\n\s*DESCRIPCION:\s*(.+?)\s*\n\s*SECCIONES:\s*(.+?)(?=\n\s*TEMA:|\Z)",
            re.DOTALL,
        )
        temas: list[dict] = []
        for match in pattern.finditer(raw):
            nombre_raw = match.group(1).strip()
            # Sanitizar a snake_case simple (sin depender del subagente)
            nombre = re.sub(r"[^a-zA-Z0-9]+", "_", nombre_raw).lower().strip("_")
            if not nombre:
                continue
            descripcion = match.group(2).strip()
            secciones = [s.strip() for s in match.group(3).split(",") if s.strip()]
            temas.append({
                "nombre": nombre,
                "descripcion": descripcion,
                "secciones": secciones,
            })
        return temas

    # -- Métodos de formato -----------------------------------------

    def _format_d4_response(self, response: str) -> str:
        """Formatea la respuesta del subagente D4."""
        response = response.strip()
        if not response or response.upper() == "SIN_RESTRICCIONES":
            return "No se identifican restricciones explícitas en el tema activo."
        lines = []
        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("RESTRICCION:"):
                lines.append(f"- {line[len('RESTRICCION:'):].strip()}")
            elif line.startswith("ALCANCE:"):
                lines.append(f"  Alcance: {line[len('ALCANCE:'):].strip()}")
            elif line:
                lines.append(f"- {line}")
        return "\n".join(lines) if lines else response

    def _replace_section(self, content: str, section: str, new_text: str) -> str:
        """Reemplaza el contenido de una sección en el markdown."""
        pattern = rf"(## Sección {section} -- [^\n]+\n\n)"
        match = re.search(pattern, content)
        if not match:
            pattern2 = rf"(## Sección {section}[^\n]*\n\n)"
            match = re.search(pattern2, content)
            if not match:
                return content
        after_header = content[match.end():]
        next_section = re.search(r"\n## ", after_header)
        if next_section:
            rest = after_header[next_section.start():]
            return content[:match.end()] + new_text + "\n\n" + rest
        else:
            return content[:match.end()] + new_text + "\n"

    def _parse_decisiones_response(self, response: str) -> list:
        """Parsea la respuesta del subagente de decisiones."""
        response = response.strip()
        if not response or response.upper() == "SIN_DECISIONES":
            return []

        decisions = []
        current = {}
        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("DECISION:"):
                if current.get("decision"):
                    decisions.append(current)
                current = {"decision": line[len("DECISION:"):].strip()}
            elif line.startswith("ALCANCE:"):
                current["alcance"] = line[len("ALCANCE:"):].strip()
            elif line.startswith("RAZON:"):
                current["razon"] = line[len("RAZON:"):].strip()
        if current.get("decision"):
            decisions.append(current)
        return decisions

    def _format_decisiones_markdown(self, decisions: list) -> str:
        """Formatea las decisiones como markdown."""
        lines = [
            "# Decisiones Clave",
            "",
            f"**Total de decisiones:** {len(decisions)}",
            "",
            "---",
            "",
        ]
        for i, d in enumerate(decisions, 1):
            lines.append(f"## D{i:02d} -- {d.get('decision', '')[:100]}")
            lines.append("")
            lines.append(f"- **Decisión:** {d.get('decision', '')}")
            if d.get("alcance"):
                lines.append(f"- **Alcance:** {d['alcance']}")
            if d.get("razon"):
                lines.append(f"- **Razón:** {d['razon']}")
            lines.append("")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"IntegradorRespuestas(workspace_dir={self._workspace_dir!r})"


if __name__ == "__main__":
    # Compatibilidad Windows
    import io as _io, sys as _sys
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
        if hasattr(_sys.stderr, 'buffer') and 'utf' not in (getattr(_sys.stderr, 'encoding', '') or '').lower():
            _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass

    print("=== Validacion de integrador_respuestas.py ===\n")

    import tempfile

    # Test 1: integrar D4
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        estado_path = Path(tmpdir) / "00_estado_actual.md"
        estado_path.write_text(
            "# Estado Actual\n\n## Sección D4 -- Restricciones\n\nPlaceholder viejo.\n\n## Sección A1\n\n",
            encoding="utf-8",
        )
        resp = SubagentResponse(
            task_id="estado_d4",
            success=True,
            response="RESTRICCION: No usar indigo\nALCANCE: general",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        assert result["estado_updated"] or result["total_applied"] == 1
        content = estado_path.read_text(encoding="utf-8")
        assert "indigo" in content
        print(f"[OK] integrar D4: restricción actualizada")

    # Test 2: integrar A1 resumen
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        estado_path = Path(tmpdir) / "00_estado_actual.md"
        estado_path.write_text("# Estado Actual\n\n## Sección A1\n\nTexto textual.\n", encoding="utf-8")
        resp = SubagentResponse(
            task_id="estado_a1_resumen",
            success=True,
            response="Resumen del contenido truncado.",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        content = estado_path.read_text(encoding="utf-8")
        assert "Resumen del contenido truncado" in content
        print(f"[OK] integrar A1 resumen: resumen añadido")

    # Test 3: integrar decisiones
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        decisiones_path = Path(tmpdir) / "02_decisiones_clave.md"
        decisiones_path.write_text("# Decisiones Clave\n\nPlaceholder.\n", encoding="utf-8")
        resp = SubagentResponse(
            task_id="decisiones_lote_0",
            success=True,
            response="DECISION: Usar OOP\nALCANCE: ClasificadorSubagent\nRAZON: Directiva del Director.",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        content = decisiones_path.read_text(encoding="utf-8")
        assert "Usar OOP" in content
        assert "ClasificadorSubagent" in content
        print(f"[OK] integrar decisiones: decisión real con alcance")

    # Test 4: integrar subdivider nombre
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        metadata_path = Path(tmpdir) / "_metadata.json"
        metadata_path.write_text(json.dumps({
            "tema_a_archivo": {"general_2026sep09": ["bloque_01.md"]}
        }), encoding="utf-8")
        resp = SubagentResponse(
            task_id="subdivider_nombre_general_2026sep09",
            success=True,
            response="autenticacion_jwt",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert "autenticacion_jwt" in metadata["tema_a_archivo"]
        assert "general_2026sep09" not in metadata["tema_a_archivo"]
        print(f"[OK] integrar subdivider nombre: metadata actualizada")

    # Test 5: respuesta fallida reporta error
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        resp = SubagentResponse(task_id="t1", success=False, error="timeout")
        result = integrador.integrar([resp])
        assert len(result["errores"]) == 1
        assert "timeout" in result["errores"][0]
        print(f"[OK] respuesta fallida: error reportado")

    # Test 6: consulta no actualiza archivos (solo se entrega al agente)
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        resp = SubagentResponse(
            task_id="consulta_directa",
            success=True,
            response="Respuesta de la consulta.",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        print(f"[OK] consulta: no actualiza archivos (se entrega al agente)")

    # Test 7: SIN_RESTRICCIONES
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        estado_path = Path(tmpdir) / "00_estado_actual.md"
        estado_path.write_text("# Estado Actual\n\n## Sección D4 -- Restricciones\n\nViejo.\n\n## A1\n", encoding="utf-8")
        resp = SubagentResponse(task_id="estado_d4", success=True, response="SIN_RESTRICCIONES")
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        content = estado_path.read_text(encoding="utf-8")
        assert "No se identifican restricciones" in content
        print(f"[OK] SIN_RESTRICCIONES: mensaje apropiado")

    # Test 8: lista vacía
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        result = integrador.integrar([])
        assert result["total_applied"] == 0
        print(f"[OK] lista vacía: 0 aplicadas")

    # Test 9: repr
    integrador_repr = IntegradorRespuestas(workspace_dir="/tmp/test_repr")
    assert "IntegradorRespuestas" in repr(integrador_repr)
    print(f"[OK] repr: {integrador_repr!r}")

    # Test 10 (F4 v4.2): CLASIFICACION_TEMAS agrega subtemas a metadata
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        metadata_path = Path(tmpdir) / "_metadata.json"
        metadata_path.write_text(json.dumps({
            "tema_a_archivo": {"validaciones": "bloque_03.md"}
        }), encoding="utf-8")
        resp = SubagentResponse(
            task_id="intercambios_clasificacion_temas_capa3_validaciones",
            success=True,
            response="""SUBTEMA: validaciones_server
DESCRIPCION: Validaciones del servidor backend
EXCHANGES: 1, 2

SUBTEMA: validaciones_router
DESCRIPCION: Validaciones del router HTTP
EXCHANGES: 3, 4""",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1, f"Esperaba 1 aplicada, obtuvo {result['total_applied']}"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert "validaciones_validaciones_server" in metadata["tema_a_archivo"]
        assert "validaciones_validaciones_router" in metadata["tema_a_archivo"]
        # El tema padre se mantiene (no se sobrescribe)
        assert "validaciones" in metadata["tema_a_archivo"]
        # Ambos subtemas apuntan al archivo del padre
        assert metadata["tema_a_archivo"]["validaciones_validaciones_server"] == "bloque_03.md"
        print(f"[OK] CLASIFICACION_TEMAS: 2 subtemas agregados a metadata")

    # Test 11 (F4 v4.2): CLASIFICACION_TEMAS con NO_SUBDIVISION no actualiza metadata
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        metadata_path = Path(tmpdir) / "_metadata.json"
        original_metadata = {"tema_a_archivo": {"validaciones": "bloque_03.md"}}
        metadata_path.write_text(json.dumps(original_metadata), encoding="utf-8")
        resp = SubagentResponse(
            task_id="intercambios_clasificacion_temas_capa3_validaciones",
            success=True,
            response="NO_SUBDIVISION",
        )
        result = integrador.integrar([resp])
        # NO_SUBDIVISION no aplica nada (total_applied=0)
        assert result["total_applied"] == 0
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert metadata == original_metadata, "Metadata no debe cambiar con NO_SUBDIVISION"
        print(f"[OK] CLASIFICACION_TEMAS: NO_SUBDIVISION no modifica metadata")

    # Test 12 (v4.2 unificación): _integrar_documento registra temas REALES (no nombre genérico)
    # El subagente indexador devuelve formato TEMA/DESCRIPCION/SECCIONES.
    # _integrar_documento debe parsearlos y registrarlos en tema_a_archivo con sus nombres semánticos.
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        metadata_path = Path(tmpdir) / "_metadata.json"
        metadata_path.write_text(json.dumps({"tema_a_archivo": {}}), encoding="utf-8")
        resp = SubagentResponse(
            task_id="documento_doc_seguridad_lote_0",
            success=True,
            response="""RESUMEN: Documento sobre el sistema de seguridad y autenticación.

TEMA: autenticacion_jwt
DESCRIPCION: Sistema de autenticación basado en JWT
SECCIONES: header, payload, signature

TEMA: control_acceso
DESCRIPCION: Control de acceso por roles
SECCIONES: roles, permisos""",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        # Los temas reales deben estar en tema_a_archivo, no el nombre genérico
        assert "autenticacion_jwt" in metadata["tema_a_archivo"], \
            f"Esperaba 'autenticacion_jwt' en tema_a_archivo, obtuvo: {metadata['tema_a_archivo']}"
        assert "control_acceso" in metadata["tema_a_archivo"]
        # Ambos temas apuntan al mismo bloque externo
        assert metadata["tema_a_archivo"]["autenticacion_jwt"] == ["bloque_externo_doc_seguridad_lote_0.md"]
        assert metadata["tema_a_archivo"]["control_acceso"] == ["bloque_externo_doc_seguridad_lote_0.md"]
        # NO debe estar el nombre genérico (documento_externo_*)
        assert not any(k.startswith("documento_externo_") for k in metadata["tema_a_archivo"])
        # El bloque físico debe existir
        bloque_path = Path(tmpdir) / "bloque_externo_doc_seguridad_lote_0.md"
        assert bloque_path.exists()
        print(f"[OK] _integrar_documento: registra temas reales (autenticacion_jwt, control_acceso), no genéricos")

    # Test 13 (v4.2 unificación): _integrar_documento cae a nombre genérico si no hay temas parseables
    # (respuesta mal formada) — no se pierde el bloque.
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        metadata_path = Path(tmpdir) / "_metadata.json"
        metadata_path.write_text(json.dumps({"tema_a_archivo": {}}), encoding="utf-8")
        resp = SubagentResponse(
            task_id="documento_doc_mal_lote_0",
            success=True,
            response="Texto sin formato TEMA/DESCRIPCION. Respuesta mal formada.",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        # Debe caer al nombre genérico para no perder el bloque
        assert "documento_externo_doc_mal_lote_0" in metadata["tema_a_archivo"]
        print(f"[OK] _integrar_documento: fallback a nombre genérico si respuesta mal formada")

    # Test 14 (v4.2 unificación): _integrar_documento no sobrescribe tema existente del chat
    # Si el subagente devuelve un tema que ya existe en tema_a_archivo (del chat),
    # se prefija con el filename del documento para no sobrescribir.
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        metadata_path = Path(tmpdir) / "_metadata.json"
        # Ya existe un tema 'autenticacion_jwt' del chat apuntando a bloque_01.md
        metadata_path.write_text(json.dumps({
            "tema_a_archivo": {"autenticacion_jwt": ["bloque_01.md"]}
        }), encoding="utf-8")
        resp = SubagentResponse(
            task_id="documento_doc_pdf_lote_0",
            success=True,
            response="""RESUMEN: Documento sobre JWT.

TEMA: autenticacion_jwt
DESCRIPCION: Otra perspectiva del JWT
SECCIONES: firma, verificacion""",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        # El tema del chat se mantiene
        assert metadata["tema_a_archivo"]["autenticacion_jwt"] == ["bloque_01.md"]
        # El tema del documento externo se prefija con el filename
        assert "doc_pdf_autenticacion_jwt" in metadata["tema_a_archivo"]
        assert metadata["tema_a_archivo"]["doc_pdf_autenticacion_jwt"] == ["bloque_externo_doc_pdf_lote_0.md"]
        print(f"[OK] _integrar_documento: no sobrescribe tema existente (prefija con filename)")

    # Test 15 (F0.2 v4.3): reprocesar el mismo documento DOS VECES → no crea entradas fantasma
    # Caso 1 de _resolver_clave_tema: clave existe apuntando al mismo bloque → idempotente.
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        metadata_path = Path(tmpdir) / "_metadata.json"
        metadata_path.write_text(json.dumps({"tema_a_archivo": {}}), encoding="utf-8")
        resp = SubagentResponse(
            task_id="documento_doc_reprocesado_lote_0",
            success=True,
            response="""RESUMEN: Documento reprocesado.

TEMA: autenticacion_jwt
DESCRIPCION: Sistema de autenticación JWT
SECCIONES: header, payload""",
        )
        # Primera integración
        integrador.integrar([resp])
        # Segunda integración con la MISMA respuesta (simula reprocesamiento)
        integrador.integrar([resp])
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        # Debe haber SOLO UNA entrada para autenticacion_jwt (no fantasma)
        entradas_jwt = [k for k in metadata["tema_a_archivo"] if "autenticacion_jwt" in k]
        assert len(entradas_jwt) == 1, \
            f"F0.2: esperaba 1 entrada jwt, obtuvo {entradas_jwt} (entradas fantasma)"
        print(f"[OK] F0.2 reprocesamiento: idempotente, sin entradas fantasma ({len(entradas_jwt)} entrada)")

    # Test 16 (F0.2 v4.3): tres documentos distintos con el mismo tema → sufijo numérico
    # Caso 4 de _resolver_clave_tema: prefijada existe apuntando a otro bloque → sufijo.
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        metadata_path = Path(tmpdir) / "_metadata.json"
        # Tema del chat preexistente
        metadata_path.write_text(json.dumps({
            "tema_a_archivo": {"autenticacion_jwt": ["bloque_01.md"]}
        }), encoding="utf-8")

        # Doc A: tema autenticacion_jwt → crea doc_a_autenticacion_jwt
        resp_a = SubagentResponse(
            task_id="documento_doc_a_lote_0", success=True,
            response="TEMA: autenticacion_jwt\nDESCRIPCION: JWT en doc A\nSECCIONES: header",
        )
        integrador.integrar([resp_a])

        # Doc B: tema autenticacion_jwt → crea doc_b_autenticacion_jwt
        resp_b = SubagentResponse(
            task_id="documento_doc_b_lote_0", success=True,
            response="TEMA: autenticacion_jwt\nDESCRIPCION: JWT en doc B\nSECCIONES: header",
        )
        integrador.integrar([resp_b])

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert "autenticacion_jwt" in metadata["tema_a_archivo"]  # chat original
        assert "doc_a_autenticacion_jwt" in metadata["tema_a_archivo"]
        assert "doc_b_autenticacion_jwt" in metadata["tema_a_archivo"]
        # Cada uno apunta a un bloque distinto
        assert metadata["tema_a_archivo"]["doc_a_autenticacion_jwt"] != metadata["tema_a_archivo"]["doc_b_autenticacion_jwt"]
        print(f"[OK] F0.2 tres docs mismo tema: prefijados con filename ({len([k for k in metadata['tema_a_archivo'] if 'autenticacion_jwt' in k])} entradas)")

    # Test 17 (F0.1 v4.3): _integrar_documento regenera 01_indice_recuperacion.md
    # con los bloques externos nuevos.
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        metadata_path = Path(tmpdir) / "_metadata.json"
        metadata_path.write_text(json.dumps({"tema_a_archivo": {}}), encoding="utf-8")

        # Crear el bloque externo físico (lo haría _integrar_documento en su flujo)
        bloque_externo = Path(tmpdir) / "bloque_externo_doc_index_lote_0.md"
        bloque_externo.write_text("# Bloque externo\n\nTEMA: api_rest\nDESCRIPCION: API\nSECCIONES: endpoints", encoding="utf-8")

        resp = SubagentResponse(
            task_id="documento_doc_index_lote_0",
            success=True,
            response="""RESUMEN: Documento sobre API.

TEMA: api_rest
DESCRIPCION: Diseño de la API REST
SECCIONES: endpoints, auth""",
        )
        integrador.integrar([resp])

        # Verificar que 01_indice_recuperacion.md fue regenerado y contiene el tema externo
        indice_path = Path(tmpdir) / "01_indice_recuperacion.md"
        assert indice_path.exists(), "F0.1: 01_indice_recuperacion.md debe existir tras integrar documento"
        indice_content = indice_path.read_text(encoding="utf-8")
        assert "api_rest" in indice_content, \
            f"F0.1: el índice debe contener el tema externo 'api_rest', obtuvo: {indice_content[:200]}"
        print(f"[OK] F0.1 índice regenerado: 01_indice_recuperacion.md incluye tema externo 'api_rest'")

    # Test 18 (F2 v4.3): _integrar_sintesis_contexto inserta G0.B en 00_estado_actual.md sin la sección
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        estado_path = Path(tmpdir) / "00_estado_actual.md"
        estado_path.write_text(
            "# Estado Actual\n\n"
            "## G0.A — Objetivo del proyecto\n\nObjetivo X.\n\n"
            "## D1 — Última instrucción\n\nDirector dijo algo.\n",
            encoding="utf-8",
        )
        resp = SubagentResponse(
            task_id="intercambios_sintesis_contexto",
            success=True,
            response="Proyecto en fase de implementación. Tema activo: bugs. Pendiente: tests.",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        content = estado_path.read_text(encoding="utf-8")
        assert "## G0.B — Síntesis del contexto disponible" in content
        assert "Proyecto en fase de implementación" in content
        # El orden: G0.A → G0.B → D1
        idx_g0a = content.find("## G0.A")
        idx_g0b = content.find("## G0.B")
        idx_d1 = content.find("## D1")
        assert 0 <= idx_g0a < idx_g0b < idx_d1
        print(f"[OK] F2 _integrar_sintesis_contexto: inserta G0.B después de G0.A")

    # Test 19 (F2 v4.3): _integrar_sintesis_contexto reemplaza G0.B existente
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        estado_path = Path(tmpdir) / "00_estado_actual.md"
        estado_path.write_text(
            "# Estado Actual\n\n"
            "## G0.B — Síntesis del contexto disponible\n\nSíntesis vieja.\n\n"
            "## D1 — Última instrucción\n\nDirector dijo algo.\n",
            encoding="utf-8",
        )
        resp = SubagentResponse(
            task_id="intercambios_sintesis_contexto",
            success=True,
            response="Síntesis nueva y actualizada.",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        content = estado_path.read_text(encoding="utf-8")
        assert "Síntesis nueva y actualizada." in content
        assert "Síntesis vieja." not in content
        print(f"[OK] F2 _integrar_sintesis_contexto: reemplaza G0.B existente")

    # Test 20 (F2 v4.3): _integrar_sintesis_contexto no modifica con SIN_SINTESIS_POSIBLE
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        estado_path = Path(tmpdir) / "00_estado_actual.md"
        original = ("# Estado Actual\n\n"
                    "## G0.B — Síntesis del contexto disponible\n\nPlaceholder inicial.\n\n"
                    "## D1 — Última instrucción\n\nDirector dijo algo.\n")
        estado_path.write_text(original, encoding="utf-8")
        resp = SubagentResponse(
            task_id="intercambios_sintesis_contexto",
            success=True,
            response="SIN_SINTESIS_POSIBLE",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 0
        content = estado_path.read_text(encoding="utf-8")
        assert content == original, "F2: SIN_SINTESIS_POSIBLE no debe modificar el archivo"
        print(f"[OK] F2 _integrar_sintesis_contexto: SIN_SINTESIS_POSIBLE no modifica archivo")

    print("\n[PASS] integrador_respuestas.py: todos los tests pasaron")
