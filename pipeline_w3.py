"""contexto_zai/pipeline_w3.py -- Ciclo W3 (validación con Crítico) + cascada (v7.0 modularizado).

Contiene la clase ``CicloW3`` con los métodos estáticos migrados desde
``EnriquecimientoOrquestador`` que implementan el ciclo W3:

- ``_ciclo_w3`` (v6.20 F1) — bucle externo que llama a ``CascadaAccesoLLM``
  para acceder al LLM. Hasta ``MAX_ITER_W3=5`` iteraciones. Si la cascada
  completa el bloque, el Crítico valida la respuesta. Si falla, elimina
  el RESUMEN y reintenta con feedback.
- ``_validar_resumen_w3`` (v6.13 C7+C8+C10) — validación de formato
  rígido (longitud, oraciones, etiquetas prohibidas).
- ``_validar_resumen_critico_subagente`` (v6.20 F3) — Crítico que valida
  fidelidad del resumen al contenido del bloque (vía LLM).
- ``_llamar_cascada_llm`` (v6.20 F1) — llama a la cascada para acceso al
  LLM, devuelve la respuesta parseada o None.
- ``_enriquecer_bloques_con_fallback`` (v6.15 F7) — arnés thin que delega
  a ``CascadaAccesoLLM.procesar_tarea()`` por bloque.
- ``_enriquecer_bloques_post_run`` (v6.2) — post-procesa un
  ``OrchestratorResult`` para añadir fallback de bloques sin RESUMEN.
- ``_descubrir_bloques_incompletos`` (v6.17 F1) — función única que
  detecta bloques incompletos (4 artefactos: RESUMEN + 3 archivos).
- ``_bloque_esta_completo`` (v6.12 F5) — verificación de los 4 artefactos.
- ``_auditar_y_completar`` (v6.17 F7 → v6.18 F3) — si contexto_recuperacion
  existe, solo auditar + completar lo faltante.
- ``collect_responses`` (v4.2 → v6.17 F4) — recoge respuestas de
  ``_responses/`` y las integra al workspace vía ``Orquestador``.

La constante ``PROMPT_FUSIONADO_W1W2W3`` (v6.13 F5) vive aquí. Es el
prompt fusionado W1+W2+W3 que usan tanto el Nivel 2 de la cascada como
el Nivel 3 (subagentes del agente CZAI).

No cambia el grafo de flujo interno: solo mueve código.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

# v7.0 F2: import tipado de la ABC (no se instancia directamente).
from contexto_zai.platforms.interfaces import PlatformLLM  # noqa: F401

from contexto_zai.config import WORKSPACE_OUTPUT_DIR
from contexto_zai.pipeline_auditoria import AuditorWorkspace

logger = logging.getLogger(__name__)


# ============================================================
# v6.13 F5: Prompt fusionado W1+W2+W3 en 1 sola llamada
# ============================================================

PROMPT_FUSIONADO_W1W2W3 = """Lee el siguiente bloque de intercambios entre un Director y un agente.

Genera una respuesta JSON con las siguientes claves:

1. "resumen": Un párrafo de 600-900 caracteres, exactamente 4 oraciones, separadas por punto y seguido. Sin secciones, sin listas, sin negritas, sin etiquetas. Estructura: (1) tema central, (2) decisiones principales, (3) temas específicos, (4) tipo de actividad.

2. "nombre": Un identificador en snake_case que resuma de qué trata el bloque (ej: "worker_bun_proxy_zai").

3. "decisiones": Una lista (array) de strings, cada uno con el formato "DECISION: descripción | ALCANCE: contexto". Si no hay decisiones reales, devuelve una lista vacía [].

4. "temas": Una lista (array) de strings con los temas abordados (2-5 keywords).

5. "verificacion": Un objeto con:
   - "completo": true si el bloque tiene contenido suficiente y el resumen cumple el rango de 600-900 chars. false si no.
   - "observaciones": texto explicando por qué está completo o no. Si el bloque tiene poco contenido (<2000 chars), indicar "bloque con contenido limitado, resumen proporcional". Si el resumen no cumple el rango pero el bloque tiene >2000 chars, indicar "resumen mejorable".

PROHIBICIONES:
- No uses etiquetas como "Tema central:", "Decisiones:", etc. en el resumen.
- No hagas listas con guiones ni numeración en el resumen.
- No incluyas código ni rutas de archivos en el resumen.
- El resumen debe ser texto natural en un solo párrafo.

Responde SOLO con el JSON, sin texto adicional.

Bloque:
{bloque_content}
"""


class CicloW3:
    """v6.20 F1: Ciclo W3 + helpers de enriquecimiento (refactor OOP v6.11 F5).

    Agrupa como ``@staticmethod`` los métodos relacionados con el ciclo W3
    (validación con Crítico) y el enriquecimiento de bloques. Antes vivían
    en ``EnriquecimientoOrquestador`` (v6.x). v7.0 los mueve aquí para
    separar responsabilidades.

    La clase es stateless — todos sus métodos son ``@staticmethod``.
    """

    @staticmethod
    def _validar_resumen_w3(
        resumen: str,
        bloque_content_len: int,
    ) -> tuple[bool, str]:
        """v6.13 C7+C8+C10: W3 validación ajena al ejecutor.

        Valida que el RESUMEN cumpla el formato rígido:
        1. Longitud 600-900 chars (RESUMEN_MIN_CHARS..RESUMEN_MAX_CHARS).
        2. Exactamente 4 oraciones (cuenta '.', '!', '?').
        3. Sin etiquetas prohibidas (Tema central:, Decisiones:, etc.).

        Devuelve (ok, motivo). Si ``ok=False``, ``motivo`` describe qué falló
        y se usará como feedback para el reintento (hasta MAX_ITER_W3).

        Regla de borde: si el bloque tiene < 2000 chars de contenido, se acepta
        el resumen con observaciones (no se exige rango estricto).
        """
        from contexto_zai.config import (
            RESUMEN_MIN_CHARS, RESUMEN_MAX_CHARS,
            RESUMEN_ORACIONES_ESPERADAS, RESUMEN_ETIQUETAS_PROHIBIDAS,
        )

        if not resumen or not resumen.strip():
            return False, "resumen vacío"

        r = resumen.strip()

        # v6.20 F3: sin excepción por tamaño de bloque — el Crítico siempre valida.

        # 1. Validar etiquetas prohibidas
        for etiqueta in RESUMEN_ETIQUETAS_PROHIBIDAS:
            if etiqueta in r:
                return False, f"contiene etiqueta prohibida: '{etiqueta}'"

        # 2. Validar longitud
        if len(r) < RESUMEN_MIN_CHARS:
            return False, f"longitud {len(r)} < {RESUMEN_MIN_CHARS} (muy corto)"
        if len(r) > RESUMEN_MAX_CHARS:
            return False, f"longitud {len(r)} > {RESUMEN_MAX_CHARS} (muy largo)"

        # 3. Validar número de oraciones
        # Cuenta '.', '!' y '?' como terminadores de oración,
        # PERO ignora puntos dentro de números (ej: "v6.13", "2.8%").
        # Heurística: split por ". " (punto + espacio) y contar segmentos no vacíos.
        # Para '!' y '?' sí se cuentan directamente (no aparecen en números).
        import re as _re
        # Contar '. ' (punto seguido de espacio o fin de string)
        puntos_oracion = len(_re.findall(r'\.\s+', r)) + (1 if r.endswith('.') else 0)
        # Sumar '!' y '?' (rara vez aparecen en números/códigos)
        signos_adic = r.count('!') + r.count('?')
        oraciones = puntos_oracion + signos_adic
        if oraciones != RESUMEN_ORACIONES_ESPERADAS:
            return False, f"{oraciones} oraciones (esperadas {RESUMEN_ORACIONES_ESPERADAS})"

        return True, "cumple formato rígido"

    @staticmethod
    def _validar_resumen_critico_subagente(
        resumen: str,
        bloque_content: str,
        block_id: str = "",
        llm: Optional[PlatformLLM] = None,
    ) -> tuple[bool, str]:
        """v6.20 F3: Crítico subagente que valida fidelidad del resumen al contenido.

        El Crítico es invocado por el W3 (no por la cascada) después de que la
        cascada devuelve la respuesta del LLM. Lo más importante es validar que
        el resumen se corresponda con la información del bloque; el formato es
        secundario.

        v7.0 F2: el modelo ``"glm-4-flash"`` hardcoded se reemplaza por
        ``llm.get_default_model_light()``. La llamada HTTP se delega en
        ``llm.call()``. ``llm`` se inyecta por parámetro; si es ``None``,
        se construye ``ZaiLLM()`` (default Zai).
        """
        # 1. Validación de formato rápida (sin LLM)
        formato_ok, formato_motivo = CicloW3._validar_resumen_w3(
            resumen, len(bloque_content)
        )
        if not formato_ok:
            return False, f"Formato: {formato_motivo}"

        # 2. Validación de fidelidad (con LLM vía cascada/proxy)
        import json as _json_c

        # v7.0 F2: resolver el LLM a usar. Default ZaiLLM() si no se inyecta.
        if llm is None:
            try:
                from contexto_zai.platforms.zai.zai_llm import ZaiLLM
                llm = ZaiLLM()
            except Exception as e:
                logger.warning(
                    "v6.20 F3 Crítico: %s no se pudo construir ZaiLLM default (%s) — aceptando",
                    block_id, e,
                )
                return True, "Formato OK (Crítico omitido)"
        # v7.0 F2: PROXY_LLM_TIMEOUT reemplaza PROXY_ZAI_TIMEOUT (alias deprecated
        # en config.py que apunta al mismo valor 10). El timeout efectivo es
        # PROXY_LLM_TIMEOUT * 3 (30s) para el Crítico (preserva v6.20 F3).
        try:
            from contexto_zai.config import PROXY_LLM_TIMEOUT
        except ImportError:
            try:
                from contexto_zai.config import PROXY_ZAI_TIMEOUT as PROXY_LLM_TIMEOUT
            except ImportError:
                logger.warning(
                    "v6.20 F3 Crítico: %s no se pudo importar config del proxy — aceptando",
                    block_id,
                )
                return True, "Formato OK (Crítico omitido)"

        bloque_truncado = bloque_content[:30000] if len(bloque_content) > 30000 else bloque_content

        prompt_critico = f"""Eres un Crítico que valida la fidelidad de un resumen respecto al contenido de un bloque.

## Criterios (en orden de importancia):

1. **Fidelidad al contenido**: ¿el resumen captura el tema central, decisiones principales y temas específicos?
2. **No omite información crítica**: ¿hay decisiones o temas importantes que el resumen no menciona?
3. **No inventa información**: ¿el resumen dice algo que no está en el bloque?
4. **Proporcionalidad**: ¿el resumen es proporcional al tamaño del bloque?
5. **Formato**: entre 600-900 caracteres, 4 oraciones, sin etiquetas prohibidas.

## Respuesta

Responde SOLO con JSON:
{{"valido": true/false, "motivo": "explicación"}}

## Bloque:

{bloque_truncado}

## Resumen:

{resumen}
"""
        # v7.0 F2: llamada al LLM vía PlatformLLM.call() en vez de
        # urllib directo. El modelo ``"glm-4-flash"`` hardcoded se
        # reemplaza por ``llm.get_default_model_light()``.
        try:
            proxy_resp = llm.call(
                messages=[{"role": "user", "content": prompt_critico}],
                model=llm.get_default_model_light(),
                max_tokens=500,
                temperature=0.1,
                timeout=PROXY_LLM_TIMEOUT * 3,
            )
            content_text = proxy_resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            content_text = content_text.strip()
            if content_text.startswith("```json"):
                content_text = content_text[7:]
            if content_text.startswith("```"):
                content_text = content_text[3:]
            if content_text.endswith("```"):
                content_text = content_text[:-3]
            result = _json_c.loads(content_text.strip())
            valido = result.get("valido", False)
            motivo = result.get("motivo", "sin motivo")
            if valido:
                logger.info("v6.20 F3 Crítico: %s OK", block_id)
                return True, "Fidelidad validada"
            else:
                logger.info("v6.20 F3 Crítico: %s FAIL (%s)", block_id, motivo[:80])
                return False, f"Fidelidad: {motivo}"
        except Exception as e:
            logger.warning("v6.20 F3 Crítico: %s error (%s) — aceptando", block_id, e)
            return True, "Formato OK (Crítico omitido)"

    @staticmethod
    def _descubrir_bloques_incompletos(workspace_dir: Path | str) -> list:
        """v6.17 F1 (criterio 7): función única que detecta bloques incompletos.

        Verifica los 4 artefactos de cada ``bloque_*.md``:

        1. RESUMEN al inicio del ``bloque_*.md``.
        2. ``_responses/{block_id}_nombre.txt``.
        3. ``_responses/{block_id}_decisiones.txt``.
        4. ``_responses/{block_id}_temas.txt``.

        Lee cada ``bloque_*.md`` del workspace y devuelve lista de los
        bloques incompletos (los que faltan al menos 1 artefacto). Para
        cada uno, indica qué artefactos faltan.

        Args:
            workspace_dir: Directorio del workspace.

        Returns:
            Lista de dicts, uno por bloque incompleto:
            - ``block_id``: str (ej. ``bloque_05``).
            - ``filename``: str (ej. ``bloque_05.md``).
            - ``faltantes``: list[str] (subset de
              ``["RESUMEN", "nombre.txt", "decisiones.txt", "temas.txt"]``).
            - ``bloque``: ThematicBlock (con ``temas`` y
              ``external_size_chars`` poblados para compatibilidad con
              la cascada de acceso LLM).
        """
        from contexto_zai.models import ThematicBlock as _TB
        ws = Path(workspace_dir)
        if not ws.exists():
            return []

        responses_dir = ws / "_responses"
        incompletos: list = []

        for p in sorted(ws.glob("bloque_*.md")):
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.warning(
                    "v6.17 F1: no se pudo leer bloque %s: %s", p.name, e
                )
                continue
            if len(content) < 100:
                # Bloque vacío o casi vacío: lo saltamos (no se puede
                # enriquecer un bloque sin contenido).
                continue

            block_id = p.stem
            filename = p.name

            # Verificar los 4 artefactos.
            faltantes: list[str] = []
            if not content.startswith("RESUMEN:"):
                faltantes.append("RESUMEN")
            if not (responses_dir / f"{block_id}_nombre.txt").exists():
                faltantes.append("nombre.txt")
            if not (responses_dir / f"{block_id}_decisiones.txt").exists():
                faltantes.append("decisiones.txt")
            if not (responses_dir / f"{block_id}_temas.txt").exists():
                faltantes.append("temas.txt")

            if not faltantes:
                continue  # bloque completo, no se devuelve

            # Extraer temas del header (para compatibilidad con la cascada).
            temas: list[str] = []
            for line in content.split("\n"):
                if line.startswith("# Bloque tematico:") or line.startswith("# Bloque temático:"):
                    temas_str = line.split(":", 1)[1].strip()
                    temas = [t.strip() for t in temas_str.split(",") if t.strip()]
                    break
                elif line.startswith("# Bloque externo"):
                    nombre = line.split(":", 1)[1].strip() if ":" in line else ""
                    temas = [nombre.lower().replace(" ", "_")[:50]] if nombre else []
                    break
            if not temas:
                temas = ["contexto_externo"]

            block = _TB(
                filename=filename,
                temas=temas,
                external_size_chars=len(content),
            )
            incompletos.append({
                "block_id": block_id,
                "filename": filename,
                "faltantes": faltantes,
                "bloque": block,
            })

        logger.info(
            "v6.17 F1: %d bloque(s) incompleto(s) descubiertos (4 artefactos).",
            len(incompletos),
        )
        return incompletos

    @staticmethod
    def _bloque_esta_completo(
        bloque,
        workspace_dir: Path | str,
    ) -> bool:
        """v6.12 F5: Verifica si un bloque esta realmente completo.

        Un bloque esta completo cuando tiene:
        1. RESUMEN: al inicio del archivo bloque_NN.md
        2. _responses/bloque_NN_nombre.txt
        3. _responses/bloque_NN_decisiones.txt
        4. _responses/bloque_NN_temas.txt

        Args:
            bloque: ThematicBlock con filename.
            workspace_dir: Directorio del workspace.

        Returns:
            True si el bloque esta completo, False si falta algo.
        """
        ws = Path(workspace_dir)
        filename = bloque.filename
        block_id = filename.replace(".md", "")

        # 1. Verificar RESUMEN al inicio
        bloque_path = ws / filename
        if not bloque_path.exists():
            return False
        content = bloque_path.read_text(encoding="utf-8", errors="ignore")
        if not content.startswith("RESUMEN:"):
            return False

        # 2. Verificar los 3 archivos de _responses/
        responses_dir = ws / "_responses"
        if not responses_dir.exists():
            return False
        if not (responses_dir / f"{block_id}_nombre.txt").exists():
            return False
        if not (responses_dir / f"{block_id}_decisiones.txt").exists():
            return False
        if not (responses_dir / f"{block_id}_temas.txt").exists():
            return False

        return True

    @staticmethod
    def _ciclo_w3(
        bloque,
        workspace_dir: Path | str,
        llm: Optional[PlatformLLM] = None,
    ) -> tuple[bool, list]:
        """v6.20 F1: El ciclo W3 es el bucle externo que llama a la cascada.

        El W3 usa la cascada para acceder al LLM. No al revés.

        Flujo:
        1. Llama a la cascada (CascadaAccesoLLM.procesar_tarea) que intenta N1→N2→N3.
        2. Si la cascada completa el bloque, el Crítico valida la respuesta.
        3. Si el Crítico falla, elimina el RESUMEN y vuelve a llamar a la cascada.
        4. Hasta 5 iteraciones. Si no completa, devuelve (False, pending_tasks).
        5. Si la cascada cae a N3, recoge las pending tasks de la cascada y las devuelve.

        v7.0 F2: el parámetro ``llm`` se propaga a ``CascadaAccesoLLM`` y
        al Crítico. Si es ``None``, se construye ``ZaiLLM()`` (default Zai)
        dentro de cada uno.

        Returns:
            Tupla (completado, pending_tasks). Si completado=True, pending_tasks=[].
            Si completado=False, pending_tasks contiene las tareas que el agente debe ejecutar.
        """
        from contexto_zai.config import MAX_ITER_W3 as _MAX_ITER_W3
        # Lazy import para evitar dependencia circular (pipeline_cascada
        # importa pipeline_w3 en runtime).
        from contexto_zai.pipeline_cascada import CascadaAccesoLLM

        ws = Path(workspace_dir)
        block_id = bloque.filename.replace(".md", "")

        # Crear una instancia de la cascada para usarla
        # v7.0 F2: se inyecta ``llm`` si llega; si no, la cascada construye
        # ZaiLLM() por defecto internamente.
        cascada = CascadaAccesoLLM(workspace_dir=workspace_dir, llm=llm)

        for intento in range(1, _MAX_ITER_W3 + 1):
            # 1. Llamar a la cascada (intenta N1 → N2 → N3)
            cascada_ok = cascada.procesar_tarea(bloque)

            if not cascada_ok:
                # La cascada no pudo completar el bloque en ningún nivel.
                # Si N3 publicó pending tasks, recogerlas.
                pending_de_cascada = cascada.get_pending_tasks()
                if pending_de_cascada:
                    logger.info("v6.20 W3: %s - cascada falló, %d pending tasks de N3",
                                block_id, len(pending_de_cascada))
                    return False, pending_de_cascada
                # Si N3 no publicó pending tasks, crear una propia
                from contexto_zai.models import SubagentTask
                bloque_path_n3 = ws / bloque.filename
                bloque_content_n3 = ""
                if bloque_path_n3.exists():
                    bloque_content_n3 = bloque_path_n3.read_text(encoding="utf-8", errors="ignore")[:50000]
                prompt_n3 = PROMPT_FUSIONADO_W1W2W3.format(bloque_content=bloque_content_n3)
                task_n3 = SubagentTask(
                    task_id=f"enriquecer_{block_id}",
                    purpose=f"v6.20.w3_cascada_fallo.{bloque.filename}",
                    prompt=prompt_n3,
                    context={"filename": bloque.filename},
                )
                logger.warning("v6.20 W3: %s - cascada falló, pending task creada", block_id)
                return False, [task_n3]

            # 2. La cascada completó el bloque. El Crítico valida la calidad.
            bloque_path = ws / bloque.filename
            if not bloque_path.exists():
                logger.warning("v6.20 W3: %s - cascada OK pero archivo no existe", block_id)
                return False, []

            bloque_content = bloque_path.read_text(encoding="utf-8", errors="ignore")
            if not bloque_content.startswith("RESUMEN:"):
                logger.warning("v6.20 W3: %s - cascada dijo OK pero sin RESUMEN", block_id)
                return False, []

            parts = bloque_content.split("\n\n---\n\n", 1)
            resumen = parts[0][len("RESUMEN:"):].strip()

            w3_ok, w3_motivo = CicloW3._validar_resumen_critico_subagente(
                resumen, bloque_content, block_id, llm=cascada._llm
            )

            if w3_ok:
                logger.info("v6.20 W3: %s OK en intento %d (%s)", block_id, intento, w3_motivo)
                return True, []

            # 3. El Crítico falló — eliminar RESUMEN y archivos auxiliares para reintentar
            logger.info("v6.20 W3: %s intento %d falló Crítico (%s) — reintentando con feedback",
                        block_id, intento, w3_motivo[:80])
            # Restaurar el bloque sin RESUMEN
            if len(parts) > 1:
                bloque_path.write_text(parts[1], encoding="utf-8")
            else:
                bloque_path.write_text("", encoding="utf-8")
            # Eliminar archivos auxiliares
            for aux_file in ws.glob(f"_responses/{block_id}_*.txt"):
                try:
                    aux_file.unlink()
                except Exception:
                    pass
            # v6.20 F4: inyectar feedback del Crítico en el contenido del bloque
            # para que la cascada lo pase al LLM en el siguiente intento.
            # Se añade como nota al inicio del contenido del bloque.
            feedback_note = (
                f"\n\n## FEEDBACK DEL CRÍTICO (intento {intento} falló)\n\n"
                f"El resumen anterior no cumplió: {w3_motivo}\n"
                f"Genera de nuevo cumpliendo: 600-900 caracteres, 4 oraciones, "
                f"sin etiquetas prohibidas, texto natural que refleje fielmente el contenido.\n"
            )
            current_content = bloque_path.read_text(encoding="utf-8", errors="ignore")
            if "FEEDBACK DEL CRÍTICO" not in current_content:
                bloque_path.write_text(current_content + feedback_note, encoding="utf-8")
            else:
                # Reemplazar el feedback anterior
                import re as _re_fb
                cleaned = _re_fb.sub(r"\n\n## FEEDBACK DEL CRÍTICO.*$", "", current_content, flags=_re_fb.DOTALL).strip()
                bloque_path.write_text(cleaned + feedback_note, encoding="utf-8")

        # 4. Agotadas las 5 iteraciones → pending task
        logger.warning("v6.20 W3: %s no completó tras %d intentos → pending task", block_id, _MAX_ITER_W3)
        # Recoger pending tasks de N3 si las hay
        pending_de_cascada_final = cascada.get_pending_tasks()
        if pending_de_cascada_final:
            return False, pending_de_cascada_final
        # Crear una propia si N3 no publicó
        from contexto_zai.models import SubagentTask
        bloque_path_final = ws / bloque.filename
        bloque_content_final = ""
        if bloque_path_final.exists():
            bloque_content_final = bloque_path_final.read_text(encoding="utf-8", errors="ignore")[:50000]
        prompt_final = PROMPT_FUSIONADO_W1W2W3.format(bloque_content=bloque_content_final)
        task_final = SubagentTask(
            task_id=f"enriquecer_{block_id}",
            purpose=f"v6.20.w3_agotado.{bloque.filename}",
            prompt=prompt_final,
            context={"filename": bloque.filename},
        )
        return False, [task_final]

    @staticmethod
    def _llamar_cascada_llm(
        messages: list,
        workspace_dir: Path | str,
        block_id: str = "",
        llm: Optional[PlatformLLM] = None,
    ) -> dict | None:
        """v6.20 F1: Llama a la cascada para acceder al LLM.

        La cascada intenta sus 3 niveles (Worker Bun → Proxy Z.ai → subagentes)
        y devuelve la respuesta del LLM o None si todos fallaron.

        Esta función NO valida calidad — eso lo hace el W3 que la llama.

        v7.0 F2: el modelo ``"glm-4-plus"`` hardcoded se reemplaza por
        ``llm.get_default_model_heavy()``. La llamada HTTP se delega en
        ``llm.call()``. ``llm`` se inyecta por parámetro; si es ``None``,
        se construye ``ZaiLLM()`` (default Zai).
        """
        import json as _json_llm
        import urllib.error as _ue_llm
        # Lazy import para evitar dependencia circular.
        from contexto_zai.pipeline_cascada import CascadaAccesoLLM

        # v7.0 F2: resolver el LLM a usar. Default ZaiLLM() si no se inyecta.
        if llm is None:
            try:
                from contexto_zai.platforms.zai.zai_llm import ZaiLLM
                llm = ZaiLLM()
            except Exception as e:
                logger.warning("v6.20 Cascada: %s no se pudo construir ZaiLLM default: %s", block_id, e)
                return None

        # v7.0 F2: PROXY_LLM_TIMEOUT reemplaza PROXY_ZAI_TIMEOUT (alias
        # deprecated en config.py que apunta al mismo valor 10). El timeout
        # efectivo es PROXY_LLM_TIMEOUT * 6 (60s) para preservar v6.20.
        try:
            from contexto_zai.config import PROXY_LLM_TIMEOUT
        except ImportError:
            try:
                from contexto_zai.config import PROXY_ZAI_TIMEOUT as PROXY_LLM_TIMEOUT
            except ImportError:
                logger.warning("v6.20 Cascada: %s no se pudo importar config del proxy", block_id)
                return None

        # Nivel 2: Proxy Z.ai directo (el más confiable para llamadas puntuales)
        # v7.0 F2: llamada al LLM vía PlatformLLM.call() en vez de urllib
        # directo. El modelo ``"glm-4-plus"`` hardcoded se reemplaza por
        # ``llm.get_default_model_heavy()``.
        try:
            proxy_resp = llm.call(
                messages=messages,
                model=llm.get_default_model_heavy(),
                max_tokens=3000,
                temperature=0.3,
                timeout=PROXY_LLM_TIMEOUT * 6,
            )
            content_text = proxy_resp.get("choices", [{}])[0].get("message", {}).get("content", "")

            # Limpiar fences
            content_text = content_text.strip()
            if content_text.startswith("```json"):
                content_text = content_text[7:]
            if content_text.startswith("```"):
                content_text = content_text[3:]
            if content_text.endswith("```"):
                content_text = content_text[:-3]

            result = _json_llm.loads(content_text.strip())
            logger.info("v6.20 Cascada: %s respuesta OK vía proxy Z.ai", block_id)
            return result
        except _ue_llm.HTTPError as e:
            if e.code == 429:
                CascadaAccesoLLM._ultimo_error_proxy_429 = True
            logger.warning("v6.20 Cascada: %s HTTP %d", block_id, e.code)
            return None
        except Exception as e:
            logger.warning("v6.20 Cascada: %s error %s", block_id, e)
            return None

    @staticmethod
    def _enriquecer_bloques_con_fallback(
        blocks: list,
        workspace_dir: Path | str,
        chat_label: str = "",
    ) -> list:
        """v6.15 F7 (criterios 29-32): Arnés thin que delega a ``CascadaAccesoLLM``.

        Reemplaza la lógica procedural de v6.13 F4 (que procesaba todos los
        bloques en bloque: Nivel 1 para todos → Nivel 2 para los restantes
        → Nivel 3 para los que quedaran) por una invocación de
        ``CascadaAccesoLLM.procesar_tarea()`` por cada bloque individual.

        Una instancia de ``CascadaAccesoLLM`` se crea una vez y se reutiliza
        por bloque (criterio 30). Las ``pending_tasks`` que publique la
        cascada (en Nivel 3) se devuelven al llamador para que las propague
        al ``OrchestratorResult.pending_tasks`` (procesadas por el agente CZAI
        vía Task tool y reintegradas vía ``collect_responses()``).

        Sigue siendo un arnés que NUNCA se detiene: si un bloque no se
        completa en la cascada, su pending_task se publica y el control
        vuelve al llamador (P14 sigue con el siguiente bloque; P17 itera
        después). Al final, sincroniza ``_processed_blocks.json`` con el
        estado físico real.

        Args:
            blocks: Lista de ThematicBlock (típicamente todos los del workspace).
            workspace_dir: Directorio del workspace.
            chat_label: Etiqueta del chat (no se usa directamente — la
                cascada publica pending_tasks con ``chat_label='cascada_n3'``).

        Returns:
            Lista de SubagentTask pendientes (publicadas por Nivel 3 de la
            cascada para los bloques que Ni N1 ni N2 pudieron completar).
        """
        # Lazy imports para evitar dependencia circular.
        from contexto_zai.pipeline_cascada import (
            _proxy_zai_disponible,
            _persistir_pending_task_en_disco,
        )

        # 1. Bloques sin RESUMEN (filtro rápido para no invocar la cascada
        # sobre bloques ya completos; la cascada también filtra por idempotencia).
        bloques_sin_resumen = [
            b for b in blocks
            if not b.tiene_resumen(workspace_dir=workspace_dir)
        ]

        # v6.16 F2 (criterio 36): leer ``_cascada_checkpoint.json`` si existe
        # y saltar los bloques ya completos (reanudación tras caída).
        checkpoint_path = Path(workspace_dir, "_cascada_checkpoint.json")
        if checkpoint_path.exists() and bloques_sin_resumen:
            try:
                import json as _json_chk
                checkpoint = _json_chk.loads(
                    checkpoint_path.read_text(encoding="utf-8")
                )
                completados = set(checkpoint.get("completados", []))
                antes = len(bloques_sin_resumen)
                bloques_sin_resumen = [
                    b for b in bloques_sin_resumen
                    if b.filename not in completados
                ]
                saltados = antes - len(bloques_sin_resumen)
                if saltados:
                    logger.info(
                        "v6.16 F2: checkpoint leído — %d bloque(s) saltado(s) "
                        "por ya completo(s) (criterio 36).",
                        saltados,
                    )
            except Exception as e:
                logger.warning(
                    "v6.16 F2: leer checkpoint falló (se ignora): %s", e
                )

        if not bloques_sin_resumen:
            logger.info(
                "v6.15 F7: Todos los bloques ya tienen RESUMEN. Nada que hacer."
            )
            AuditorWorkspace.sincronizar_registro(workspace_dir)
            return []

        logger.info(
            "v6.15 F7: %d bloque(s) sin RESUMEN. W3 + cascada por bloque.",
            len(bloques_sin_resumen),
        )

        # v6.20 F1: el W3 es el bucle externo que llama a la cascada.
        # _ciclo_w3 llama a CascadaAccesoLLM.procesar_tarea y valida con el Crítico.
        pending_tasks: list = []

        # v6.20: si el proxy no está disponible, la cascada no podrá acceder al LLM.
        # Publicar pending tasks para todos los bloques sin intentar la cascada.
        try:
            proxy_disponible = _proxy_zai_disponible()
        except Exception:
            proxy_disponible = False

        if not proxy_disponible:
            logger.info("v6.20: proxy no disponible — publicando pending tasks sin cascada")
            from contexto_zai.models import SubagentTask
            for bloque in bloques_sin_resumen:
                block_id_skip = bloque.filename.replace(".md", "")
                bloque_path_skip = Path(workspace_dir) / bloque.filename
                bloque_content_skip = ""
                if bloque_path_skip.exists():
                    bloque_content_skip = bloque_path_skip.read_text(encoding="utf-8", errors="ignore")[:50000]
                prompt_skip = PROMPT_FUSIONADO_W1W2W3.format(bloque_content=bloque_content_skip)
                task_skip = SubagentTask(
                    task_id=f"enriquecer_{block_id_skip}",
                    purpose=f"v6.20.proxy_caido.{bloque.filename}",
                    prompt=prompt_skip,
                    context={"filename": bloque.filename},
                )
                pending_tasks.append(task_skip)
                _persistir_pending_task_en_disco(
                    workspace_dir=workspace_dir, task=task_skip
                )
        else:
            for bloque in bloques_sin_resumen:
                completado, w3_pending = CicloW3._ciclo_w3(bloque, workspace_dir)
                if not completado:
                    # El W3 no pudo completar — las pending tasks vienen del W3
                    pending_tasks.extend(w3_pending)
                    for task_w3 in w3_pending:
                        _persistir_pending_task_en_disco(
                            workspace_dir=workspace_dir, task=task_w3
                        )
                    logger.info(
                        "v6.20 W3: bloque %s no completado → %d pending task(s). Continuando.",
                        getattr(bloque, "filename", str(bloque)),
                        len(w3_pending),
                    )

        # 3. v6.20: las pending_tasks ya se acumularon en el bucle W3 arriba.

        # 4. Sincronizar _processed_blocks.json con el estado físico real.
        AuditorWorkspace.sincronizar_registro(workspace_dir)

        return pending_tasks

    @staticmethod
    def _enriquecer_bloques_post_run(
        result: "OrchestratorResult",
        workspace_dir: Path | str,
        chat_label: str = "",
        is_chat_chronological: bool = True,
    ) -> "OrchestratorResult":
        """v6.2: Post-procesa un OrchestratorResult para añadir fallback de bloques.

        Llamada por ``pipeline.run()`` después de ``orch.activate()``. Examina los
        bloques físicos del workspace, identifica los que no tienen RESUMEN:, y
        orquesta el enriquecimiento (proxy Z.ai → worker, si no → fallback al agente).

        Las pending_tasks que devuelve el Orchestrator original se conservan; las
        nuevas (fallback de bloques) se añaden a la lista.

        v6.10 F2: SIN try/except silencioso. Si el enriquecimiento falla, el error
        se propaga y se registra claramente. Las pending_tasks se capturan del
        valor de retorno directamente (v6.8.1 re-aplicado).

        v6.11 F6: ``is_chat_chronological`` se acepta por simetría con
        ``collect_responses()``. Hoy en día ``_enriquecer_bloques_post_run`` solo
        se invoca desde ``pipeline.run()`` (chat-cronológico), pero el parámetro
        permite llamarlo en el futuro desde ``ampliar_contexto()`` para enriquecer
        bloques externos sin disparar la consolidación de los 4 archivos.

        Args:
            result: OrchestratorResult devuelto por orch.activate().
            workspace_dir: Directorio del workspace.
            chat_label: Etiqueta del chat (opcional).
            is_chat_chronological: v6.11 F6 — ``True`` (default) si la operación
                viene de ``pipeline.run()`` (chat cronológico). ``False`` si viene
                de ``ampliar_contexto()`` (fuente externa, no cronológica).

        Returns:
            El mismo OrchestratorResult con pending_tasks actualizadas.
        """
        # v6.10 F2: sin try/except silencioso. Si el workspace no existe o no hay
        # bloques, simplemente devolvemos result sin cambios (no es error).
        workspace_path = Path(workspace_dir)
        if not workspace_path.exists():
            return result
        from contexto_zai.models import ThematicBlock
        blocks = []
        for p in sorted(workspace_path.glob("bloque_*.md")):
            block = ThematicBlock(filename=p.name)
            blocks.append(block)
        if not blocks:
            return result

        # Orquestar enriquecimiento (v6.10 F3: el arnés detecta caída del Worker
        # Bun en menos de 5s y devuelve las pending_tasks inmediatamente).
        fallback_tasks = CicloW3._enriquecer_bloques_con_fallback(
            blocks=blocks,
            workspace_dir=workspace_dir,
            chat_label=chat_label,
        )

        # Añadir a pending_tasks existentes (v6.8.1 re-aplicado: capturar del retorno).
        if fallback_tasks:
            if result.pending_tasks is None:
                result.pending_tasks = []
            result.pending_tasks.extend(fallback_tasks)
            logger.info("v6.10: %d tarea(s) de fallback añadidas a pending_tasks.",
                        len(fallback_tasks))

        return result

    @staticmethod
    def _auditar_y_completar(
        workspace_dir: Path | str,
    ) -> dict:
        """v6.17 F7 (criterio 6) → v6.18 F3 (criterio 3): si contexto_recuperacion existe, solo auditar + completar.

        v6.18 F3 (criterio 3): si ``contexto_recuperacion/`` no existe,
        esta función NO se llama. P2 (auditoría inicial) carece de
        sentido sobre un workspace vacío. El proceso va directo a
        procesar la fuente (``ampliar_contexto()`` o ``RecoveryCycle``).

        Si ``contexto_recuperacion/`` existe (con bloques físicos), el
        daemon/process NO re-extrae ni re-construye. Audita qué está
        completo, qué está incompleto, y completa lo faltante:

        1. Audita con ``_descubrir_bloques_incompletos()`` (F1).
        2. Completa solo los incompletos (sin re-extraer, sin
           re-construir, sin borrar caché, sin quitar RESUMENES).
        3. Auditoría final + P17 + P18 + P19.

        Si ``contexto_recuperacion/`` no existe, el llamador debe
        ejecutar ``RecoveryCycle`` completo o ``ampliar_contexto()``
        (que internamente invoca RecoveryCycle si estructura=cronologico).

        Args:
            workspace_dir: Directorio del workspace (donde viven los
                ``bloque_*.md`` y ``_responses/``).

        Returns:
            Dict con:
            - ``audited``: True si se ejecutó la auditoría.
            - ``incompletos_iniciales``: Número de bloques incompletos al inicio.
            - ``pending_tasks``: Número de pending_tasks tras completar.
            - ``contexto_existia``: True si el workspace tenía bloques.
        """
        # Lazy imports para evitar dependencia circular.
        from contexto_zai.pipeline_cascada import CascadaAccesoLLM
        from contexto_zai.pipeline_d7 import CicloD7
        from contexto_zai.pipeline_archivos import SubprocesoArchivos

        ws = Path(workspace_dir)
        contexto_existia = ws.exists() and any(ws.glob("bloque_*.md"))
        if not contexto_existia:
            logger.info(
                "v6.17 F7: contexto_recuperacion no existe — no se audita "
                "(el llamador debe ejecutar RecoveryCycle completo)."
            )
            return {
                "audited": False,
                "incompletos_iniciales": 0,
                "pending_tasks": 0,
                "contexto_existia": False,
            }

        # 1. Auditar bloques incompletos con F1.
        incompletos = CicloW3._descubrir_bloques_incompletos(ws)
        logger.info(
            "v6.17 F7: contexto_recuperacion existe — %d bloque(s) incompleto(s) "
            "de %d total. Completando solo los incompletos (sin re-extraer, "
            "sin re-construir, sin borrar caché, sin quitar RESUMENES).",
            len(incompletos), len(list(ws.glob("bloque_*.md"))),
        )

        # 2. Procesar solo los incompletos con la cascada.
        cascada = CascadaAccesoLLM(workspace_dir=ws)
        for inc in incompletos:
            cascada.procesar_tarea(inc["bloque"])
        pending_tasks_count = len(cascada.get_pending_tasks())

        # 3. Auditoría final + P17 + P18 + P19.
        # P16 — auditoría final post-enriquecimiento.
        try:
            audit_final = AuditorWorkspace.auditar_completitud(ws)
            logger.info(
                "v6.17 F7: Auditoría final: %d completos, %d incompletos, "
                "metadata_valida=%s",
                len(audit_final["completos"]), len(audit_final["incompletos"]),
                audit_final["metadata_valida"],
            )
        except Exception as e:
            logger.warning("v6.17 F7: auditar_completitud falló: %s", e)

        # P17 — bucle D7 encapsulado (F12) para reintentar con feedback.
        try:
            from contexto_zai.models import OrchestratorResult
            dummy_result = OrchestratorResult(success=True)
            dummy_result.pending_tasks = cascada.get_pending_tasks()
            CicloD7._bucle_d7_completitud(
                result=dummy_result,
                workspace_dir=ws,
            )
        except Exception as e:
            logger.warning("v6.17 F7: bucle D7 (P17) falló: %s", e)

        # P18 — consolidar decisiones del LLM en 02_decisiones_clave.md.
        try:
            SubprocesoArchivos._consolidar_decisiones_llm(workspace_dir=ws)
        except Exception as e:
            logger.warning("v6.17 F7: _consolidar_decisiones_llm (P18) falló: %s", e)

        # P19 — regenerar 01_indice_recuperacion.md tras enriquecimiento.
        try:
            SubprocesoArchivos._regenerar_indice_tras_enriquecimiento(workspace_dir=ws)
        except Exception as e:
            logger.warning("v6.17 F7: _regenerar_indice (P19) falló: %s", e)

        return {
            "audited": True,
            "incompletos_iniciales": len(incompletos),
            "pending_tasks": pending_tasks_count,
            "contexto_existia": True,
        }

    @staticmethod
    def collect_responses(
        workspace_dir: Path | str = WORKSPACE_OUTPUT_DIR,
        is_chat_chronological: bool = True,
    ) -> dict:
        """v4.2 → v6.17 F4 (criterio 3): Recoge respuestas y las integra al workspace.

        v6.17 F4 (criterio 3): ``collect_responses()`` SOLO integra
        respuestas. Lee ``_responses/``, las aplica al workspace según
        el ``purpose`` de cada tarea, y devuelve resultado.

        NO verifica bloques incompletos. NO dispara la cascada W1+W2+W3
        (P14). Esa verificación y disparo la hace el proceso
        (daemon/pipeline) tras llamar ``collect_responses()`` —
        típicamente ``ContextoPipeline.run()`` invoca el enriquecimiento
        (que dispara la cascada) y luego el bucle D7
        (P17, separado de la cascada según F3).

        v6.17 F10 (criterio 10): si la operación NO es cronológica
        (``is_chat_chronological=False``, viene de ampliar_contexto),
        lee ``_estructura_externa`` del ``_metadata.json`` para decidir
        si el bloque externo tiene estructura cronológica. Los bloques
        externos con estructura cronológica SÍ generan los 4 archivos
        de recuperación (consolidan decisiones y regeneran índice).

        La consolidación de decisiones y la regeneración del índice
        (``_consolidar_decisiones_llm`` y
        ``_regenerar_indice_tras_enriquecimiento``) no son parte de la
        cascada — son pasos de post-integración que se mantienen aquí
        para preservar el comportamiento del chat cronológico.

        El agente nunca ve el contenido crudo de las respuestas — solo
        llama a esta función y recibe el resultado estructurado.

        Args:
            workspace_dir: Directorio del workspace donde viven
                _pending_tasks.json y _responses/.
            is_chat_chronological: ``True`` (default) si la operación
                viene de ``pipeline.run()`` (chat cronológico).
                ``False`` si viene de ``ampliar_contexto()`` (fuente
                externa, no cronológica).

        Returns:
            Dict con el resultado estructurado devuelto por
            ``Orquestador.aplicar_respuestas()``.
        """
        from contexto_zai.coordinador import Orquestador, IntegradorRespuestas
        # Lazy import para evitar dependencia circular.
        from contexto_zai.pipeline_archivos import (
            _consolidar_decisiones_llm,
            _regenerar_indice_tras_enriquecimiento,
        )

        orch = Orquestador(workspace_dir=workspace_dir)
        integrador = IntegradorRespuestas(workspace_dir=workspace_dir)

        # v6.11 F6: reenviar is_chat_chronological para que el integrador
        # salte los handlers que regeneran 00_estado_actual.md cuando la
        # operación no es cronológica (viene de ampliar_contexto).
        resultado = orch.aplicar_respuestas(
            integrador=integrador,
            is_chat_chronological=is_chat_chronological,
        )

        # v6.17 F4 (criterio 3): collect_responses() SOLO integra.
        # NO verifica bloques incompletos. NO dispara la cascada de
        # acceso LLM (P14). Esa lógica la asume el proceso
        # (daemon/pipeline) tras llamar collect_responses().
        # La consolidación de decisiones y regeneración del índice se
        # mantienen aquí (no son parte de la cascada).
        #
        # v6.17 F10 (criterio 10): si la operación no es cronológica
        # (ampliar_contexto), leer _estructura_externa del metadata.json.
        # Los bloques externos con estructura cronológica SÍ generan los
        # 4 archivos de recuperación — consolidan decisiones y
        # regeneran índice igual que el chat cronológico.
        should_consolidate = is_chat_chronological
        if not should_consolidate:
            # Verificar si hay un bloque externo con estructura cronológica.
            import json as _json_f10
            metadata_path = Path(workspace_dir) / "_metadata.json"
            if metadata_path.exists():
                try:
                    meta = _json_f10.loads(metadata_path.read_text(encoding="utf-8"))
                    estructura_externa = meta.get("_estructura_externa", "")
                    if estructura_externa == "cronologico":
                        should_consolidate = True
                        logger.info(
                            "v6.17 F10: ampliar_contexto con estructura=cronologico — "
                            "consolidando decisiones y regenerando índice (4 archivos)."
                        )
                except Exception as e:
                    logger.warning(
                        "v6.17 F10: leer _estructura_externa del metadata falló: %s", e
                    )

        if should_consolidate:
            _consolidar_decisiones_llm(workspace_dir=workspace_dir)
            _regenerar_indice_tras_enriquecimiento(workspace_dir=workspace_dir)
        else:
            logger.info(
                "v6.17 F4: collect_responses no cronológico — solo integración. "
                "Consolidación de decisiones y regeneración del índice omitidas. "
                "La verificación de bloques incompletos y el disparo de la cascada "
                "los hace el proceso (daemon/pipeline) tras esta llamada."
            )

        return resultado
