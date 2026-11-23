"""contexto_zai/pipeline_cascada.py -- Cascada de acceso al LLM (v7.0 modularizado).

Contiene:
- ``CascadaAccesoLLM`` (v6.15 F3-F5) — clase que ejecuta la cascada
  3 niveles por bloque (N1 Worker Bun → N2 Proxy Z.ai → N3 subagentes
  del agente CZAI).
- 7 funciones módulo-nivel (migradas como ``@staticmethod`` de
  ``EnriquecimientoOrquestador`` en v6.x):
    * ``_proxy_zai_disponible`` (v6.2)
    * ``_arrancar_worker_y_esperar`` (v6.12)
    * ``_persistir_pending_task_en_disco`` (v6.17 F11)
    * ``_post_bloque`` (v6.16 F8)
    * ``_actualizar_estado_daemon`` (v6.17 F5 → v6.19 F6)
    * ``_escribir_artefactos_bloque`` (v6.20 F1)
    * ``_enriquecer_con_proxy_zai`` (v6.13 F5)

El atributo de clase ``_ultimo_error_proxy_429`` vive ahora en
``CascadaAccesoLLM`` (antes en ``EnriquecimientoOrquestador``). Lo
gestionan ``_nivel2_proxy_zai``, ``_procesar_bloque_nivel2``,
``_enriquecer_con_proxy_zai`` y ``_llamar_cascada_llm`` (este último
se mudó a ``pipeline_w3``).

No cambia el grafo de flujo interno: solo mueve código.

v7.0 F2 — Abstracción de plataforma:
- ``CascadaAccesoLLM.__init__`` recibe ``llm: PlatformLLM = None`` por
  constructor. Si no se inyecta, se usa ``ZaiLLM()`` (default Zai).
- ``_proxy_zai_disponible`` delega en ``PlatformLLM.is_available()``.
- ``_enriquecer_con_proxy_zai`` recibe ``llm: PlatformLLM = None`` y
  usa ``llm.call()`` en vez de ``urllib`` directo. El modelo
  ``"glm-4-plus"`` hardcoded se reemplaza por
  ``llm.get_default_model_heavy()``.
"""

from __future__ import annotations

import logging
import os as _os
import time
import json
from pathlib import Path
from typing import Optional

# v7.0 F2: import tipado de la ABC (no se instancia directamente).
from platforms.interfaces import PlatformLLM  # noqa: F401

from pipeline_auditoria import AuditorWorkspace, ProgressMonitor

logger = logging.getLogger(__name__)


# ============================================================
# v6.2 / v6.12 / v6.17 F11 / v6.16 F8 / v6.20 F1 —
# Funciones módulo-nivel migradas de EnriquecimientoOrquestador
# ============================================================

def _proxy_zai_disponible(llm: Optional[PlatformLLM] = None) -> bool:
    """v6.2: Hace un ping mínimo al proxy Zai. Devuelve True si responde 200.

    v7.0 F2: delega en ``PlatformLLM.is_available()``. Si ``llm`` es
    ``None``, se construye un ``ZaiLLM()`` por defecto. El
    comportamiento es idéntico al de v6.2 (ping con ``max_tokens=3`` al
    proxy APA, devolver True solo si HTTP 200).

    Args:
        llm: Implementación ``PlatformLLM`` opcional. Si es ``None``,
            se usa ``ZaiLLM()`` (default Zai).
    """
    try:
        if llm is None:
            # Lazy import para evitar dependencia circular en tiempo de
            # carga del módulo (ZaiLLM importa platforms.interfaces que
            # importa typing, no problema en runtime).
            from platforms.zai.zai_llm import ZaiLLM
            llm = ZaiLLM()
        return llm.is_available()
    except Exception as e:
        logger.info("v6.2 _proxy_zai_disponible(): error %s", e)
        return False


def _arrancar_worker_y_esperar(
    workspace_dir: Path | str,
    timeout: Optional[int] = None,
) -> bool:
    """v6.12: Arranca el Worker Bun y monitorea progreso con ProgressMonitor.

    v6.12 F2: Reemplaza el timeout fijo por monitoreo de progreso.
    El Worker Bun arranca en background (no bloqueante) y
    ProgressMonitor comprueba cada intervalo si hay progreso
    (mas bloques completos). Si no progresa en 2 intervalos
    seguidos, se declara que cayo y se devuelve False.

    v6.8.2 F2: verifica si el puerto 8090 ya está en uso antes
    de intentar arrancar otro Worker Bun.

    Args:
        workspace_dir: Directorio del workspace.
        timeout: Ignorado en v6.12 (se usa ProgressMonitor).

    Returns:
        True si el Worker Bun completo todos los bloques.
        False si no progresa o falla.
    """
    import subprocess
    import socket as _socket
    try:
        from config import WORKER_BUN_DIR
    except ImportError:
        logger.warning("v6.12: no se pudo importar WORKER_BUN_DIR, fallback desactivado")
        return False
    if not Path(WORKER_BUN_DIR).exists():
        logger.warning("v6.12: WORKER_BUN_DIR no existe: %s", WORKER_BUN_DIR)
        return False

    # v6.8.2 F2: verificar si el puerto 8090 ya está en uso
    WORKER_BUN_PORT = 8090
    puerto_en_uso = False
    try:
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.settimeout(1)
        result_sock = sock.connect_ex(("localhost", WORKER_BUN_PORT))
        sock.close()
        puerto_en_uso = (result_sock == 0)
    except Exception:
        puerto_en_uso = False

    if puerto_en_uso:
        logger.info("v6.12: puerto %d en uso — Worker Bun ya corriendo, monitoreando progreso",
                   WORKER_BUN_PORT)
        # v6.12 F2: usar ProgressMonitor en vez de sleep fijo
        return ProgressMonitor.esperar_y_verificar(workspace_dir)

    # v6.12 F2: arrancar Worker Bun en background (no bloqueante)
    env = {**_os.environ, "CZAI_WORKSPACE_DIR": str(workspace_dir)}
    try:
        proc = subprocess.Popen(
            ["bun", "run", "cli.ts", "run"],
            cwd=WORKER_BUN_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        logger.info("v6.12: Worker Bun arrancado en background (PID %d). Monitoreando progreso...", proc.pid)

        # v6.12 F2: ProgressMonitor decide si hay progreso
        todo_completo = ProgressMonitor.esperar_y_verificar(workspace_dir)

        # Si el proceso sigue corriendo, dejarlo (puede seguir procesando)
        if proc.poll() is None:
            logger.info("v6.12: Worker Bun sigue corriendo en background.")

        return todo_completo

    except FileNotFoundError:
        logger.warning("v6.12: 'bun' no está en PATH. Fallback desactivado.")
        return False
    except Exception as e:
        logger.warning("v6.12: Error arrancando Worker Bun: %s", e)
        return False


def _persistir_pending_task_en_disco(
    workspace_dir: Path | str, task,
) -> None:
    """v6.17 F11 (criterio 11): función única para persistir pending_tasks.

    Usada por:
    - ``_post_bloque`` — llamado cuando un bloque cae a Nivel 3 desde la cascada.
    - ``CascadaAccesoLLM._nivel3_subagentes`` — llamado para cada
      pending_task publicada por Nivel 3.
    - ``CicloD7._bucle_d7_completitud`` (F12) — llamado para cada
      pending_task corregida que publica el bucle D7.

    Las pending_tasks pueden caer desde cualquier nivel de la cascada
    (N1, N2 o N3). Esta función es idempotente en cuanto al archivo:
    lee, añade, escribe (append, no sobrescribir).

    Args:
        workspace_dir: Directorio del workspace.
        task: SubagentTask (pydantic BaseModel) o dict a persistir.
    """
    import json as _json
    ws = Path(workspace_dir)
    path = ws / "_pending_tasks.json"
    data: dict = {"tasks": []}
    if path.exists():
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "tasks" not in data:
                data = {"tasks": []}
            if not isinstance(data.get("tasks"), list):
                data["tasks"] = []
        except Exception as e:
            logger.warning(
                "v6.17 F11: _pending_tasks.json corrupto, se reinicia: %s", e
            )
            data = {"tasks": []}
    # Serializar la task — pydantic BaseModel usa model_dump(), otros
    # objetos se caen a default=str para no romper el JSON.
    try:
        if hasattr(task, "model_dump"):
            task_data = task.model_dump(mode="json")
        elif isinstance(task, dict):
            task_data = task
        else:
            task_data = _json.loads(_json.dumps(task, default=str))
    except Exception as e:
        logger.warning(
            "v6.17 F11: no se pudo serializar pending_task (%s): %s",
            type(task).__name__, e,
        )
        return
    # Idempotencia: si la task ya está en el saco (mismo task_id), no
    # añadir de nuevo. Esto permite que _post_bloque y el D7 llamen a
    # esta función sin duplicar entradas.
    new_task_id = task_data.get("task_id", "") if isinstance(task_data, dict) else ""
    if new_task_id:
        existing_ids = {
            t.get("task_id", "")
            for t in data["tasks"]
            if isinstance(t, dict)
        }
        if new_task_id in existing_ids:
            logger.info(
                "v6.17 F11: pending_task %s ya persistida — idempotencia (no duplicar).",
                new_task_id,
            )
            return
    data["tasks"].append(task_data)
    data["total"] = len(data["tasks"])
    try:
        path.write_text(
            _json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(
            "v6.17 F11: no se pudo escribir _pending_tasks.json: %s", e
        )


def _post_bloque(
    workspace_dir: Path | str,
    bloque,
    resultado: bool,
    cascada: "CascadaAccesoLLM",
) -> None:
    """v6.16 F8 (propuesta del Director): encapsula tareas post-bloque.

    Ejecuta la secuencia de pasos que siempre son los mismos tras
    procesar un bloque:

    1. Escribir checkpoint (``_cascada_checkpoint.json``) — refresca el
       estado físico real.
    2. Si el bloque cayó a Nivel 3 (``resultado == False``) → persistir
       pending_task en ``_pending_tasks.json`` (idempotente por block_id)
       vía ``_persistir_pending_task_en_disco`` (F11).
    3. Actualizar ``_processed_blocks.json`` (marcar completed o pending)
       vía ``AuditorWorkspace.sincronizar_registro``.
    4. Actualizar ``_pending_blocks.json`` (quitar el bloque de pendientes
       si se completó).

    Es **stateless** (criterio del Actuador: función, no clase): toma el
    estado actual y lo persiste. No preserva nada entre llamadas. Vive
    como función módulo-nivel de ``pipeline_cascada`` por encapsulación,
    pero su contrato es funcional.

    Args:
        workspace_dir: Directorio del workspace.
        bloque: ThematicBlock que se acaba de procesar.
        resultado: True si el bloque quedó completo; False si cayó a
            Nivel 3 (pending_task publicada en ``cascada._pending_tasks``).
        cascada: Instancia de ``CascadaAccesoLLM`` con los métodos
            ``_escribir_checkpoint`` y ``_pending_tasks``.
    """
    import json as _json
    ws = Path(workspace_dir)
    filename = getattr(bloque, "filename", str(bloque))
    block_id = filename.replace(".md", "")

    # 1. Escribir checkpoint.
    if cascada is not None and hasattr(cascada, "_escribir_checkpoint"):
        try:
            cascada._escribir_checkpoint()
        except Exception as e:
            logger.warning("v6.16 F8: _escribir_checkpoint falló: %s", e)

    # 2. Si el bloque cayó a Nivel 3 → persistir pending_task (idempotente).
    #    v6.17 F11: usar la función única _persistir_pending_task_en_disco.
    if not resultado and cascada is not None:
        pending_path = ws / "_pending_tasks.json"
        ya_persistida = False
        try:
            if pending_path.exists():
                data = _json.loads(pending_path.read_text(encoding="utf-8"))
                tasks = data.get("tasks", []) if isinstance(data, dict) else []
                # Idempotencia: buscar por task_id == "enriquecer_{block_id}"
                # o por context.filename == filename.
                for t in tasks:
                    if not isinstance(t, dict):
                        continue
                    if t.get("task_id") == f"enriquecer_{block_id}":
                        ya_persistida = True
                        break
                    ctx = t.get("context") or {}
                    if isinstance(ctx, dict) and ctx.get("filename") == filename:
                        ya_persistida = True
                        break
        except Exception as e:
            logger.warning(
                "v6.16 F8: leer _pending_tasks.json para idempotencia falló: %s", e
            )
        if not ya_persistida:
            # Buscar la task en cascada._pending_tasks para este bloque.
            pending_tasks = getattr(cascada, "_pending_tasks", []) or []
            for task in pending_tasks:
                task_id = getattr(task, "task_id", "")
                ctx = getattr(task, "context", {}) or {}
                if task_id == f"enriquecer_{block_id}" or ctx.get("filename") == filename:
                    try:
                        _persistir_pending_task_en_disco(
                            workspace_dir=workspace_dir, task=task
                        )
                    except Exception as e:
                        logger.warning(
                            "v6.16 F8: _persistir_pending_task_en_disco falló: %s", e
                        )
                    break

    # 3. Actualizar _processed_blocks.json (marcar completed o pending).
    #    ``sincronizar_registro`` ya hace esto en bloque (recorre todos los
    #    bloque_*.md), pero lo invocamos aquí para que el estado refleje
    #    este bloque específico justo después de procesarse.
    try:
        AuditorWorkspace.sincronizar_registro(workspace_dir)
    except Exception as e:
        logger.warning("v6.16 F8: sincronizar_registro falló: %s", e)

    # 4. Actualizar _pending_blocks.json (quitar el bloque de pendientes
    #    si se completó). Si no se completó, la entrada ya existe (la
    #    creó RecoveryCycle o _integrar_documento) y se deja.
    if resultado:
        pending_blocks_path = ws / "_pending_blocks.json"
        try:
            if pending_blocks_path.exists():
                data = _json.loads(pending_blocks_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("blocks"), list):
                    antes = len(data["blocks"])
                    data["blocks"] = [
                        b for b in data["blocks"]
                        if not (isinstance(b, dict) and b.get("block_id") == block_id)
                    ]
                    if len(data["blocks"]) < antes:
                        pending_blocks_path.write_text(
                            _json.dumps(data, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                        logger.info(
                            "v6.16 F8: %s quitado de _pending_blocks.json "
                            "(completado).", filename,
                        )
        except Exception as e:
            logger.warning(
                "v6.16 F8: actualizar _pending_blocks.json falló: %s", e
            )

    # 5. v6.17 F5 (criterio 4): actualizar _daemon_status.json.
    #    El daemon lee el estado del workspace y escribe progreso para
    #    que el agente CZAI lo incluya en la frase de control.
    try:
        _actualizar_estado_daemon(
            workspace_dir=workspace_dir,
            tarea_actual=block_id,
        )
    except Exception as e:
        logger.warning("v6.17 F5: actualizar_estado_daemon falló: %s", e)


def _actualizar_estado_daemon(
    workspace_dir: Path | str,
    status: str = "running",
    tarea_actual: str = "",
) -> None:
    """v6.17 F5 → v6.19 F6: escribe ``_daemon_status.json`` en el workspace.

    v6.19 F6 (autonomía): añade estado ``waiting_for_agent`` para cuando
    el daemon publica pending_tasks de Nivel 3. También corrige el bug
    donde ``status=running`` se mantenía aunque todos los bloques estuvieran
    completos: si ``pendientes == 0`` y ``completados == total``, el
    status se cambia automáticamente a ``done``.

    Cuenta bloques completos/pendientes con
    ``_descubrir_bloques_incompletos()`` (F1) y escribe el estado del
    daemon en ``_daemon_status.json``:

    .. code-block:: json

        {
          "status": "running|idle|done|waiting_for_agent",
          "total_bloques": 50,
          "completados": 23,
          "pendientes": 27,
          "tarea_actual": "bloque_24",
          "timestamp": 1234567890
        }

    El agente CZAI lee ``_daemon_status.json`` antes de responder al
    Director e incluye el estado en la frase de control. Si el daemon
    no está haciendo nada (status=idle), lo dice. Cuando termina
    (status=done), lo dice.

    Args:
        workspace_dir: Directorio del workspace.
        status: ``running``, ``idle`` o ``done``.
        tarea_actual: ``block_id`` del bloque en proceso (o vacío si idle).
    """
    import json as _json_d
    import time as _time_d
    ws = Path(workspace_dir)
    if not ws.exists():
        return
    try:
        total = len(list(ws.glob("bloque_*.md")))
        # Lazy import para evitar dependencia circular (pipeline_w3 importa
        # pipeline_cascada en runtime).
        from pipeline_w3 import _descubrir_bloques_incompletos
        incompletos = _descubrir_bloques_incompletos(workspace_dir)
        pendientes = len(incompletos)
        completados = max(0, total - pendientes)
    except Exception as e:
        logger.warning("v6.17 F5: contar bloques falló: %s", e)
        total = completados = pendientes = 0
    # v6.19 F6 (bug fix): si status=running pero todos los bloques están
    # completos (pendientes=0, completados=total), cambiar a done.
    # Evita el bug donde _daemon_status.json decía "running" cuando el
    # proceso ya había terminado.
    if status == "running" and total > 0 and pendientes == 0:
        status = "done"
        logger.info(
            "v6.19 F6 (bug fix): status running→done (todos los bloques completos)"
        )
    status_path = ws / "_daemon_status.json"
    payload = {
        "status": status,
        "total_bloques": total,
        "completados": completados,
        "pendientes": pendientes,
        "tarea_actual": tarea_actual,
        "timestamp": int(_time_d.time()),
    }
    try:
        status_path.write_text(
            _json_d.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("v6.17 F5: escribir _daemon_status.json falló: %s", e)


def _escribir_artefactos_bloque(
    workspace_dir: Path | str,
    bloque,
    respuesta: dict,
) -> None:
    """v6.20 F1: Escribe los 4 artefactos del bloque tras validar con el Crítico."""
    ws = Path(workspace_dir)
    bloque_path = ws / bloque.filename

    # Leer contenido original
    original = ""
    if bloque_path.exists():
        content = bloque_path.read_text(encoding="utf-8", errors="ignore")
        if content.startswith("RESUMEN:"):
            parts = content.split("\n\n---\n\n", 1)
            original = parts[1] if len(parts) > 1 else content
        else:
            original = content

    # Escribir RESUMEN al inicio
    resumen = respuesta.get("resumen", "").strip()
    nombre = respuesta.get("nombre", "").strip()
    decisiones = respuesta.get("decisiones", [])
    temas = respuesta.get("temas", [])

    bloque_path.write_text(
        f"RESUMEN: {resumen}\n\n---\n\n{original}",
        encoding="utf-8",
    )

    # Escribir archivos auxiliares
    responses_dir = ws / "_responses"
    responses_dir.mkdir(exist_ok=True)
    block_id = bloque.filename.replace(".md", "")

    (responses_dir / f"{block_id}_nombre.txt").write_text(nombre, encoding="utf-8")

    decisiones_text = "\n".join(
        str(d) if isinstance(d, str) else str(d)
        for d in (decisiones if isinstance(decisiones, list) else [decisiones])
    )
    (responses_dir / f"{block_id}_decisiones.txt").write_text(decisiones_text, encoding="utf-8")

    temas_text = "\n".join(
        str(t) if isinstance(t, str) else str(t)
        for t in (temas if isinstance(temas, list) else [temas])
    )
    (responses_dir / f"{block_id}_temas.txt").write_text(temas_text, encoding="utf-8")


def _enriquecer_con_proxy_zai(
    bloque,
    workspace_dir: Path | str,
    llm: Optional[PlatformLLM] = None,
) -> bool:
    """v6.13 F5: Nivel 2 del arnés - enriquecer un bloque con W1+W2+W3 fusionados en 1 llamada.

    Lee el bloque, llama al proxy Z.ai con el prompt fusionado W1+W2+W3,
    y escribe los 4 artefactos (RESUMEN + 3 archivos) a partir de una sola
    respuesta JSON.

    v6.13 C10: Si el RESUMEN no cumple el formato rígido (600-900, 4 oraciones,
    sin etiquetas), reintenta hasta MAX_ITER_W3=5 con feedback al LLM.

    v7.0 F2: el modelo ``"glm-4-plus"`` hardcoded se reemplaza por
    ``llm.get_default_model_heavy()``. La llamada HTTP se delega en
    ``llm.call()`` (en vez de ``urllib`` directo). ``llm`` se inyecta
    por parámetro; si es ``None``, se construye ``ZaiLLM()`` (default
    Zai). El timeout se pasa como ``PROXY_LLM_TIMEOUT * 6`` (60s) para
    preservar el comportamiento del v6.13.

    Args:
        bloque: ThematicBlock con filename.
        workspace_dir: Directorio del workspace.
        llm: Implementación ``PlatformLLM`` opcional. Si es ``None``,
            se construye ``ZaiLLM()`` (default Zai).

    Returns:
        True si el bloque se completo, False si fallo.
    """
    import json as _json
    import urllib.error as _ue
    import hashlib as _hashlib

    ws = Path(workspace_dir)
    filename = bloque.filename
    block_id = filename.replace(".md", "")
    bloque_path = ws / filename
    responses_dir = ws / "_responses"
    cache_dir = responses_dir / "cache"

    if not bloque_path.exists():
        logger.warning("v6.13 Nivel 2: bloque %s no existe.", filename)
        return False

    responses_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    bloque_content = bloque_path.read_text(encoding="utf-8")
    if len(bloque_content) < 100:
        logger.warning("v6.13 Nivel 2: bloque %s demasiado corto.", filename)
        return False

    max_chars = 50000
    if len(bloque_content) > max_chars:
        bloque_content = bloque_content[:max_chars] + "\n...(contenido truncado)..."

    # v7.0 F2: resolver el LLM a usar. Default ZaiLLM() si no se inyecta.
    if llm is None:
        try:
            from platforms.zai.zai_llm import ZaiLLM
            llm = ZaiLLM()
        except Exception as e:
            logger.warning("v7.0 F2: no se pudo construir ZaiLLM default: %s", e)
            return False

    # v7.0 F2: PROXY_LLM_TIMEOUT reemplaza PROXY_ZAI_TIMEOUT (alias deprecated
    # en config.py que apunta al mismo valor 10). El timeout efectivo de la
    # llamada es PROXY_LLM_TIMEOUT * 6 (60s) para no cortar respuestas largas.
    try:
        from config import PROXY_LLM_TIMEOUT
    except ImportError:
        # Fallback: alias deprecated (backward-compat).
        try:
            from config import PROXY_ZAI_TIMEOUT as PROXY_LLM_TIMEOUT
        except ImportError:
            logger.warning("v6.13 Nivel 2: no se pudo importar config del proxy.")
            return False

    # v6.13 F5: Prompt fusionado W1+W2+W3
    # Lazy import para evitar dependencia circular (pipeline_w3 importa
    # pipeline_cascada en runtime).
    from pipeline_w3 import PROMPT_FUSIONADO_W1W2W3
    prompt = PROMPT_FUSIONADO_W1W2W3.format(bloque_content=bloque_content)

    # v6.16 F7 (criterio 40): el hash de caché incluye la versión del
    # pipeline. Si la versión cambia, el hash cambia y la caché se
    # invalida, forzando re-generación de RESUMEN+artefactos con el
    # prompt vigente.
    try:
        from config import PIPELINE_VERSION
        prompt_hash = _hashlib.sha256(
            (prompt + PIPELINE_VERSION).encode("utf-8")
        ).hexdigest()
    except ImportError:
        # Fallback: sin PIPELINE_VERSION, hash solo del prompt.
        prompt_hash = _hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    cache_file = cache_dir / f"{prompt_hash}.json"

    if cache_file.exists():
        logger.info("v6.13 Nivel 2: caché hit para %s (hash %s...)", block_id, prompt_hash[:8])
        try:
            result = _json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            result = None
    else:
        # v6.20 F1: la cascada NO hace W3. Solo hace 1 llamada al LLM.
        # El W3 (con Crítico y feedback) lo hace _ciclo_w3 externamente.
        CascadaAccesoLLM._ultimo_error_proxy_429 = False

        messages = [{"role": "user", "content": prompt}]
        result = None

        # v7.0 F2: llamada al LLM vía PlatformLLM.call() en vez de
        # urllib directo. El modelo ``"glm-4-plus"`` hardcoded se
        # reemplaza por ``llm.get_default_model_heavy()``. El timeout
        # pasa explícito (PROXY_LLM_TIMEOUT * 6 = 60s) para preservar
        # el comportamiento del v6.13.
        try:
            proxy_resp = llm.call(
                messages=messages,
                model=llm.get_default_model_heavy(),
                max_tokens=3000,
                temperature=0.3,
                timeout=PROXY_LLM_TIMEOUT * 6,
            )
        except _ue.HTTPError as e:
            if e.code == 429:
                CascadaAccesoLLM._ultimo_error_proxy_429 = True
                logger.warning("v6.20 Cascada N2: HTTP 429 para %s", block_id)
            else:
                logger.warning("v6.20 Cascada N2: HTTP %d para %s", e.code, block_id)
            return False
        except Exception as e:
            logger.warning("v6.20 Cascada N2: error %s para %s", e, block_id)
            return False

        # Parsear respuesta del proxy
        try:
            content_text = proxy_resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception:
            logger.warning("v6.20 Cascada N2: respuesta no parseable para %s", block_id)
            return False

        # Parsear JSON del contenido
        try:
            content_text = content_text.strip()
            if content_text.startswith("```json"):
                content_text = content_text[7:]
            if content_text.startswith("```"):
                content_text = content_text[3:]
            if content_text.endswith("```"):
                content_text = content_text[:-3]
            content_text = content_text.strip()
            result = _json.loads(content_text)
        except Exception:
            logger.warning("v6.20 Cascada N2: JSON no parseable para %s", block_id)
            return False

        # Guardar en caché
        cache_file.write_text(_json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        # v6.20 F1: la cascada NO valida. El Crítico (en _ciclo_w3) lo hará.
        logger.info("v6.20 Cascada N2: %s respuesta recibida", block_id)

        if result is None:
            return False

    # Extraer campos del JSON
    resumen = result.get("resumen", "").strip()
    nombre = result.get("nombre", "").strip()
    decisiones = result.get("decisiones", [])
    temas = result.get("temas", [])
    verificacion = result.get("verificacion", {})
    completo = verificacion.get("completo", True)
    observaciones = verificacion.get("observaciones", "")

    # v6.17 F9 (criterio 9): enriquecimiento ATÓMICO.
    # Generar los 4 contenidos primero. Si los 4 son válidos (no vacíos),
    # escribirlos todos. Si alguno falla, NO escribir ninguno — el bloque
    # queda en su estado anterior.
    # Implementación: escribir a archivos temporales primero, luego
    # renombrar todos a sus paths finales. Si cualquier write falla,
    # eliminar los temporales y devolver False (sin tocar los reales).
    decisiones_text = "\n".join(decisiones) if decisiones else "SIN_DECISIONES_REALES"
    temas_text = ", ".join(temas) if temas else "general"

    # Validar los 4 contenidos antes de escribir nada.
    artefactos_validos = bool(resumen) and bool(nombre) and bool(decisiones_text) and bool(temas_text)
    if not artefactos_validos:
        logger.warning(
            "v6.17 F9: %s - contenido inválido (alguno vacío). No se escribe "
            "nada — el bloque queda en su estado anterior.",
            block_id,
        )
        return False

    # Generar el contenido del .md con RESUMEN al inicio.
    current_content = bloque_path.read_text(encoding="utf-8")
    if current_content.startswith("RESUMEN:"):
        parts = current_content.split("\n\n---\n\n", 1)
        new_content = f"RESUMEN: {resumen}\n\n---\n\n" + (parts[1] if len(parts) > 1 else "")
    else:
        new_content = f"RESUMEN: {resumen}\n\n---\n\n{current_content}"

    # Escribir a archivos temporales primero (átomico por archivo).
    # Si cualquier write falla, eliminar los temporales y devolver False.
    import os as _os_mod
    tmp_paths: list = []
    try:
        # Temporal 1: bloque_NN.md.tmp
        bloque_tmp = bloque_path.with_suffix(bloque_path.suffix + ".tmp")
        bloque_tmp.write_text(new_content, encoding="utf-8")
        tmp_paths.append(bloque_tmp)
        # Temporal 2: bloque_NN_nombre.txt.tmp
        nombre_tmp = responses_dir / f"{block_id}_nombre.txt.tmp"
        nombre_tmp.write_text(nombre, encoding="utf-8")
        tmp_paths.append(nombre_tmp)
        # Temporal 3: bloque_NN_decisiones.txt.tmp
        decisiones_tmp = responses_dir / f"{block_id}_decisiones.txt.tmp"
        decisiones_tmp.write_text(decisiones_text, encoding="utf-8")
        tmp_paths.append(decisiones_tmp)
        # Temporal 4: bloque_NN_temas.txt.tmp
        temas_tmp = responses_dir / f"{block_id}_temas.txt.tmp"
        temas_tmp.write_text(temas_text, encoding="utf-8")
        tmp_paths.append(temas_tmp)
    except Exception as e:
        logger.warning(
            "v6.17 F9: %s - fallo escribiendo temporales (%s). Limpiando — "
            "el bloque queda en su estado anterior.",
            block_id, e,
        )
        for tp in tmp_paths:
            try:
                if tp.exists():
                    tp.unlink()
            except Exception:
                pass
        return False

    # Renombrar todos los temporales a sus paths finales (átomico).
    # En Linux, rename sobrescribe. En Windows, hay que eliminar el
    # destino primero.
    try:
        # 1. RESUMEN al inicio del bloque.
        if bloque_path.exists():
            bloque_path.unlink()
        bloque_tmp.rename(bloque_path)
        # 2. _nombre.txt
        nombre_final = responses_dir / f"{block_id}_nombre.txt"
        if nombre_final.exists():
            nombre_final.unlink()
        nombre_tmp.rename(nombre_final)
        # 3. _decisiones.txt
        decisiones_final = responses_dir / f"{block_id}_decisiones.txt"
        if decisiones_final.exists():
            decisiones_final.unlink()
        decisiones_tmp.rename(decisiones_final)
        # 4. _temas.txt
        temas_final = responses_dir / f"{block_id}_temas.txt"
        if temas_final.exists():
            temas_final.unlink()
        temas_tmp.rename(temas_final)
    except Exception as e:
        logger.warning(
            "v6.17 F9: %s - fallo renombrando temporales (%s). Los temporales "
            "pueden haber quedado en disco — el bloque puede estar en estado "
            "inconsistente. Reintentar con bucle D7 lo resolverá.",
            block_id, e,
        )
        # Limpiar temporales que puedan haber quedado.
        for tp in tmp_paths:
            try:
                if tp.exists():
                    tp.unlink()
            except Exception:
                pass
        return False

    # W3 final: confirmar completitud (ya validado arriba, pero mantener log informativo)
    if not completo:
        logger.info("v6.13 W3: %s - LLM reportó completo=False, observaciones: %s",
                    block_id, observaciones)

    logger.info("v6.13 Nivel 2 + v6.17 F9: %s completado atómicamente (W1+W2+W3 en 1 llamada, %d intento(s)).",
                block_id, intento)
    return True


# ============================================================
# v6.15 F3+F4+F5 (criterios 29-32): CascadaAccesoLLM
# ============================================================

class CascadaAccesoLLM:
    """v6.15 F3-F5: Cascada de acceso al LLM por tarea individual.

    La cascada baja niveles 1→2→3. En cada transición de nivel hay un bucle
    D7 corto que hace polling de progreso (``_esperar_y_verificar_progreso``):
    intervalo fijo de ``CASCADA_INTERVALO_PROGRESO=5s``, umbral de
    ``CASCADA_UMBRAL_SIN_PROGRESO=3`` intervalos consecutivos sin progreso
    = 15s sin progreso = caída del nivel. Se eliminó el backoff exponencial
    de v6.13 C10 (criterio 32).

    Las ``pending_tasks`` se acumulan en ``self._pending_tasks`` durante
    todo P14 y se resuelven en P17 (``_bucle_d7_completitud``). El nivel 3
    (subagentes del agente CZAI) no las ejecuta directamente: las publica
    para que el agente CZAI las procese con Task tool, llame
    ``collect_responses()``, y el proceso re-verifique (criterio 31).

    Una instancia se crea una vez y se reutiliza por tarea (criterio 30).

    Flujo (criterios 29, 30, 31, 32) — v6.17 D3+D5: cascada secuencial,
    sin reintentos dentro de la cascada:

    1. Nivel 1 (Worker Bun) → si todas completas, return True.
    2. Nivel 2 (proxy Z.ai directo, 1 intento por tarea) → si todas
       completas, return True.
    3. Si Nivel 2 cayó (429 u otra causa) → cae directo a Nivel 3. NO se
       reintenta Nivel 1 dentro de la cascada (conciliado: "Si Nivel 1 cae
       por 429, no tiene sentido probar Nivel 2 (mismo proxy). Caer a
       Nivel 3.").
    4. Nivel 3 (subagentes del agente CZAI): publica pending_tasks en
       ``self._pending_tasks`` y devuelve False si hay pendientes.
       Los reintentos los hace el bucle D7 (F12) sobre pending_tasks, no
       la cascada. El D7 no baja niveles.

    Filtra tareas ya completas (idempotencia con
    ``_bloque_esta_completo``) al inicio y tras cada nivel.

    Atributo de clase ``_ultimo_error_proxy_429`` (v6.15 F5, criterio 32):
    flag para señalar que ``_enriquecer_con_proxy_zai()`` falló por HTTP
    429 (rate limit). La gestión del 429 la hace ``_nivel2_proxy_zai()``
    con polling de progreso (5s × 3 = 15s), NO la función de
    enriquecimiento (que hace un solo intento por llamada y devuelve
    False inmediatamente al recibir 429, seteando este flag).
    """

    # v6.15 F5 (criterio 32): flag de clase para señalar 429 del proxy.
    _ultimo_error_proxy_429: bool = False

    def __init__(
        self,
        workspace_dir: Path | str,
        llm: Optional[PlatformLLM] = None,
    ) -> None:
        """Inicializa la cascada con el workspace_dir.

        v7.0 F2: el parámetro ``llm`` se inyecta por constructor. Si
        no se inyecta, se construye ``ZaiLLM()`` (default Zai) para
        preservar el comportamiento previo. El ``llm`` se pasa a
        ``_enriquecer_con_proxy_zai`` vía ``_procesar_bloque_nivel2``
        para que las llamadas LLM usen la abstracción.

        Args:
            workspace_dir: Directorio del workspace donde viven los bloques
                bloque_*.md y el directorio _responses/.
            llm: Implementación ``PlatformLLM`` opcional. Si es
                ``None``, se construye ``ZaiLLM()`` (default Zai).
        """
        self._workspace_dir = workspace_dir
        # v7.0 F2: default ZaiLLM() si no se inyecta nada.
        if llm is None:
            try:
                from platforms.zai.zai_llm import ZaiLLM
                llm = ZaiLLM()
            except Exception as e:
                logger.warning(
                    "v7.0 F2: no se pudo construir ZaiLLM default: %s", e
                )
                llm = None
        self._llm = llm
        # v6.15 F3 (criterio 31): las pending_tasks se acumulan aquí durante
        # todo P14 y se resuelven en P17. Se rellenan solo en Nivel 3.
        self._pending_tasks: list = []

    def procesar_tarea(self, tarea_o_lote) -> bool:
        """Ejecuta la cascada para una tarea individual o un lote.

        v6.17 F8 (criterio 8) — conciliado P19: NO se hacen pings al proxy.
        La llamada de enriquecimiento ES la verificación: si Nivel 2 recibe
        429 o error al llamar ``_enriquecer_con_proxy_zai()``, la tarea cae
        a Nivel 3. Si Nivel 1 cae por causa que NO es 429 → Nivel 2 SÍ se
        prueba.

        Filtra tareas ya completas (idempotencia con
        ``_bloque_esta_completo``) al inicio y tras cada nivel.

        Args:
            tarea_o_lote: ThematicBlock individual o lista de ThematicBlock.

        Returns:
            True si todas las tareas quedaron completas tras la cascada.
            False si alguna tarea quedó pendiente (publicada en
            ``self._pending_tasks`` para que el agente CZAI la procese vía
            Nivel 3 y P17).
        """
        # Lazy import para evitar dependencia circular (pipeline_w3 importa
        # pipeline_cascada en runtime).
        from pipeline_w3 import _bloque_esta_completo

        # Normalizar a lista.
        if isinstance(tarea_o_lote, list):
            tareas_originales = list(tarea_o_lote)
        else:
            tareas_originales = [tarea_o_lote]

        # Idempotencia: filtrar tareas ya completas.
        tareas = [
            t for t in tareas_originales
            if not _bloque_esta_completo(
                t, workspace_dir=self._workspace_dir
            )
        ]
        if not tareas:
            logger.info(
                "CascadaAccesoLLM: todas las tareas ya completas (idempotencia)."
            )
            # v6.16 F2: aun sin trabajo que hacer, refrescar el checkpoint para
            # que _cascada_checkpoint.json refleje el estado fisico actual.
            self._escribir_checkpoint()
            # v6.16 F8: post-bloque para todas las tareas (ya completas).
            for bloque in tareas_originales:
                _post_bloque(
                    self._workspace_dir, bloque, True, self
                )
            return True

        # Nivel 1: Worker Bun.
        if self._nivel1_worker_bun(tareas):
            logger.info(
                "CascadaAccesoLLM: Nivel 1 (Worker Bun) completó %d tarea(s).",
                len(tareas),
            )
            # v6.16 F2 (criterio 35): checkpoint tras procesar el bloque.
            self._escribir_checkpoint()
            # v6.16 F8: post-bloque para todas las tareas (N1 completó).
            for bloque in tareas_originales:
                _post_bloque(
                    self._workspace_dir, bloque, True, self
                )
            return True

        # Filtrar completas tras Nivel 1.
        tareas_restantes = [
            t for t in tareas
            if not _bloque_esta_completo(
                t, workspace_dir=self._workspace_dir
            )
        ]
        if not tareas_restantes:
            # v6.16 F2 (criterio 35): checkpoint.
            self._escribir_checkpoint()
            # v6.16 F8: post-bloque para todas las tareas (completas tras N1).
            for bloque in tareas_originales:
                _post_bloque(
                    self._workspace_dir, bloque, True, self
                )
            return True

        # Nivel 2: proxy Z.ai directo. Se prueba SIEMPRE que N1 cayó
        # (sea por 429 o por otra causa). Si N2 recibe 429 o error, la
        # verificación la hace la propia llamada de enriquecimiento
        # (conciliado P19: no hay ping previo).
        nivel2_ok = self._nivel2_proxy_zai(tareas_restantes)
        if nivel2_ok:
            logger.info(
                "CascadaAccesoLLM: Nivel 2 (proxy Z.ai) completó %d tarea(s).",
                len(tareas_restantes),
            )
            # v6.16 F2 (criterio 35): checkpoint.
            self._escribir_checkpoint()
            # v6.16 F8: post-bloque para todas las tareas (N2 completó).
            for bloque in tareas_originales:
                _post_bloque(
                    self._workspace_dir, bloque, True, self
                )
            return True

        # Nivel 3: subagentes del agente CZAI.
        # v6.17 D3: si Nivel 2 cayó (por 429 o por otra causa), cae directo a
        # Nivel 3 — no se reintenta Nivel 1 (conciliado: 'Si Nivel 1 cae por
        # 429, no tiene sentido probar Nivel 2 (mismo proxy). Caer a Nivel 3').
        # La cascada queda secuencial: N1 → N2 → N3 sin reintentos dentro de
        # la cascada. Los reintentos los hace el D7 sobre pending_tasks.
        ok = self._nivel3_subagentes(tareas_restantes)
        # v6.16 F2 (criterio 35): checkpoint tras procesar el bloque (haya
        # ido o no a Nivel 3 — el estado fisico pudo cambiar).
        self._escribir_checkpoint()
        # v6.16 F8: post-bloque para todas las tareas originales.
        # ``resultado`` por bloque = si está completo físicamente tras la cascada.
        for bloque in tareas_originales:
            bloque_ok = _bloque_esta_completo(
                bloque, workspace_dir=self._workspace_dir
            )
            _post_bloque(
                self._workspace_dir, bloque, bloque_ok, self
            )
        return ok

    def _escribir_checkpoint(self) -> None:
        """v6.16 F2 (criterios 35, 36): escribe ``_cascada_checkpoint.json``.

        Persiste el estado de la cascada a disco tras procesar cada bloque.
        Contiene la lista de bloques completos, pendientes y un timestamp.
        Al relanzar la cascada (``_enriquecer_bloques_con_fallback``), se lee
        el checkpoint y se saltan los bloques ya completos (criterio 36).

        Es stateless respecto a ``self._todos_los_bloques``: descubre los
        bloques físicos del workspace con ``AuditorWorkspace`` en cada
        invocación — no necesita que se le pase el lote por parámetro.
        """
        import json as _json
        import time as _time
        ws = Path(self._workspace_dir)
        try:
            audit = AuditorWorkspace.auditar_bloques(self._workspace_dir)
            completos = list(audit.get("completos", []))
            completos_set = set(completos)
            # Pendientes: todos los bloque_*.md físicos menos los completos.
            pendientes = []
            try:
                for p in sorted(ws.glob("bloque_*.md")):
                    if p.stem not in completos_set:
                        pendientes.append(p.name)
            except Exception as e:
                logger.warning(
                    "CascadaAccesoLLM._escribir_checkpoint: glob falló: %s", e
                )
            checkpoint = {
                "completados": completos,
                "pendientes": pendientes,
                "timestamp": _time.time(),
            }
            checkpoint_path = ws / "_cascada_checkpoint.json"
            checkpoint_path.write_text(
                _json.dumps(checkpoint, indent=2), encoding="utf-8"
            )
            logger.info(
                "v6.16 F2: checkpoint escrito (%d completos, %d pendientes)",
                len(completos), len(pendientes),
            )
        except Exception as e:
            logger.warning(
                "v6.16 F2: _escribir_checkpoint falló: %s", e
            )

    def _nivel1_worker_bun(self, tareas: list) -> bool:
        """v6.16 F5 (criterio 39): arranca Worker Bun y monitorea con ``_esperar_y_verificar_progreso()``.

        Reemplaza la llamada a ``_arrancar_worker_y_esperar()``
        (que usa ``ProgressMonitor.esperar_y_verificar()`` con 20s+40s=60s) por:

        1. Arrancar el Worker Bun (subprocess, igual que antes).
        2. Usar ``self._esperar_y_verificar_progreso()`` (5s×3=15s) para monitorear.
        3. Si hay progreso → seguir esperando.
        4. Si 3 intervalos sin progreso → return False (caída).

        Args:
            tareas: Lista de ThematicBlock pendientes.

        Returns:
            True si todas las tareas quedaron completas. False si el nivel
            cayó (sin progreso en 15s) o si hay tareas aún incompletas.
        """
        if not tareas:
            return True
        # Lazy import para evitar dependencia circular (pipeline_w3 importa
        # pipeline_cascada en runtime).
        from pipeline_w3 import _bloque_esta_completo
        # v6.16 F5 (criterio 39): arrancar el Worker Bun directamente aquí con
        # subprocess (igual que ``_arrancar_worker_y_esperar``), sin llamar a
        # ``ProgressMonitor.esperar_y_verificar()`` (que tarda 60s). El
        # monitoreo de progreso lo hace el bucle de abajo con
        # ``_esperar_y_verificar_progreso()`` (5s × 3 = 15s por ronda).
        import subprocess as _subprocess
        import socket as _socket
        import os as _os_mod
        try:
            from config import WORKER_BUN_DIR
        except ImportError:
            logger.warning(
                "v6.16 F5: no se pudo importar WORKER_BUN_DIR, fallback desactivado"
            )
            return False
        if not Path(WORKER_BUN_DIR).exists():
            logger.warning("v6.16 F5: WORKER_BUN_DIR no existe: %s", WORKER_BUN_DIR)
            return False

        # v6.8.2 F2: verificar si el puerto 8090 ya está en uso.
        WORKER_BUN_PORT = 8090
        puerto_en_uso = False
        try:
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            sock.settimeout(1)
            result_sock = sock.connect_ex(("localhost", WORKER_BUN_PORT))
            sock.close()
            puerto_en_uso = (result_sock == 0)
        except Exception:
            puerto_en_uso = False

        proc = None
        if not puerto_en_uso:
            env = {**_os_mod.environ, "CZAI_WORKSPACE_DIR": str(self._workspace_dir)}
            try:
                proc = _subprocess.Popen(
                    ["bun", "run", "cli.ts", "run"],
                    cwd=WORKER_BUN_DIR,
                    env=env,
                    stdout=_subprocess.PIPE,
                    stderr=_subprocess.PIPE,
                    text=True,
                )
                logger.info(
                    "v6.16 F5: Worker Bun arrancado en background (PID %d). "
                    "Monitoreando con _esperar_y_verificar_progreso (5s×3=15s).",
                    proc.pid,
                )
            except FileNotFoundError:
                logger.warning("v6.16 F5: 'bun' no está en PATH. Fallback desactivado.")
                return False
            except Exception as e:
                logger.warning("v6.16 F5: Error arrancando Worker Bun: %s", e)
                return False
        else:
            logger.info(
                "v6.16 F5: puerto %d en uso — Worker Bun ya corriendo, "
                "monitoreando progreso con _esperar_y_verificar_progreso.",
                WORKER_BUN_PORT,
            )

        # Bucle de monitoreo: mientras haya progreso, seguir esperando.
        # Si una ronda completa (3 intervalos = 15s) no detecta progreso →
        # caída del nivel, return False.
        MAX_RONDAS = 12  # 12 rondas × 15s = 180s como techo de seguridad.
        for ronda in range(MAX_RONDAS):
            progreso = self._esperar_y_verificar_progreso()
            # ¿Todas las tareas completas tras la ronda?
            completas = [
                t for t in tareas
                if _bloque_esta_completo(
                    t, workspace_dir=self._workspace_dir
                )
            ]
            if len(completas) == len(tareas):
                logger.info(
                    "v6.16 F5: Nivel 1 completó %d tarea(s) en ronda %d.",
                    len(tareas), ronda + 1,
                )
                return True
            if not progreso:
                # 3 intervalos sin progreso → caída del nivel.
                logger.info(
                    "v6.16 F5: Nivel 1 caído tras ronda %d (sin progreso 15s).",
                    ronda + 1,
                )
                return False
            # Hay progreso pero faltan tareas → otra ronda.
            logger.info(
                "v6.16 F5: progreso detectado en ronda %d, continuando.",
                ronda + 1,
            )
        # Techo de seguridad: tras MAX_RONDAS sin completar todo, cae.
        logger.warning(
            "v6.16 F5: Nivel 1 agotó %d rondas sin completar todas las tareas.",
            MAX_RONDAS,
        )
        return False

    def _nivel2_proxy_zai(self, tareas: list) -> bool:
        """v6.16 F6 (criterio 40): procesa un lote de bloques en paralelo con ``ThreadPoolExecutor``.

        Reemplaza el bucle secuencial (1 bloque a la vez) por una ejecución
        paralela de hasta 5 llamadas HTTP simultáneas al proxy Z.ai. Cada
        thread ejecuta ``_procesar_bloque_nivel2(bloque)`` que hace 1
        intento de ``_enriquecer_con_proxy_zai()``. Si recibe 429, espera
        progreso (15s) y reintenta 1 vez. Si no hay progreso → return False
        (caída a Nivel 3 vía ``procesar_tarea``).

        Los bloques que fallan (por cualquier motivo) NO se completan aquí;
        ``procesar_tarea`` decide si reintenta Nivel 1 (429) o cae a Nivel 3.

        Args:
            tareas: Lista de ThematicBlock pendientes.

        Returns:
            True si todas las tareas quedaron completas. False si alguna
            tarea falló (429 sostenido, W3 fallida tras MAX_ITER_W3, etc.).
        """
        if not tareas:
            return True
        # Reset del flag 429 antes de empezar (lo gestiona esta función,
        # no _enriquecer_con_proxy_zai que solo lo setea).
        CascadaAccesoLLM._ultimo_error_proxy_429 = False

        # v6.16 F6 (criterio 40): paralelismo con ThreadPoolExecutor(5).
        from concurrent.futures import ThreadPoolExecutor, as_completed
        # Lazy import para evitar dependencia circular.
        from pipeline_w3 import _bloque_esta_completo

        # Idempotencia: filtrar tareas ya completas (no lanzar threads
        # innecesarios sobre bloques que otra ronda ya completó).
        pendientes = [
            t for t in tareas
            if not _bloque_esta_completo(
                t, workspace_dir=self._workspace_dir
            )
        ]
        if not pendientes:
            return True

        max_workers = min(5, len(pendientes))
        resultados: dict = {}  # bloque -> (ok, was_429)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._procesar_bloque_nivel2, b): b
                for b in pendientes
            }
            for future in as_completed(futures):
                bloque = futures[future]
                try:
                    ok, was_429 = future.result()
                except Exception as e:
                    logger.warning(
                        "CascadaAccesoLLM._nivel2_proxy_zai: excepción %s para %s",
                        e, getattr(bloque, "filename", str(bloque)),
                    )
                    ok, was_429 = False, False
                resultados[bloque.filename] = (ok, was_429)
                # Si el bloque se completó, refrescar checkpoint (criterio 35).
                if ok:
                    self._escribir_checkpoint()
                # Si el flag de 429 quedó activo en algún thread, propagarlo
                # al flag de clase para que ``procesar_tarea`` active el
                # retry-Nivel-1 (criterio 32). Es conservador: si ALGÚN
                # bloque vio 429, el lote cae por 429.
                if was_429:
                    CascadaAccesoLLM._ultimo_error_proxy_429 = True

        # Verificar que todas las tareas quedaron completas.
        completas = [
            t for t in tareas
            if _bloque_esta_completo(
                t, workspace_dir=self._workspace_dir
            )
        ]
        return len(completas) == len(tareas)

    def _procesar_bloque_nivel2(self, bloque) -> tuple:
        """v6.16 F6 (criterio 40): procesa 1 bloque en Nivel 2 (worker del ThreadPool).

        Llama ``_enriquecer_con_proxy_zai()`` (1 intento). Si 429 → espera
        progreso (``_esperar_y_verificar_progreso()``). Si hay progreso →
        reintenta. Si no → return (False, True) (429 sin progreso, caída).

        Args:
            bloque: ThematicBlock a enriquecer.

        Returns:
            Tupla ``(ok, was_429)``:
            - ``ok=True`` si el bloque quedó completo.
            - ``ok=False, was_429=True`` si cayó por 429 sostenido.
            - ``ok=False, was_429=False`` si cayó por otra razón (W3, JSON,
              HTTP != 429, etc.) — caída directa a Nivel 3.

        Nota sobre thread-safety: ``_ultimo_error_proxy_429`` es un atributo
        de clase compartido entre threads. Cada worker lo resetea antes de
        su llamada y captura su valor inmediatamente después. La race window
        es estrecha y el comportamiento conservador (propagar 429 al lote
        si ALGÚN thread lo vio) previene pérdida de señales 429.
        """
        # Lazy import para evitar dependencia circular.
        from pipeline_w3 import _bloque_esta_completo
        # Idempotencia: si otra ronda ya completó este bloque, ok.
        if _bloque_esta_completo(
            bloque, workspace_dir=self._workspace_dir
        ):
            return (True, False)
        # Reset del flag 429 antes de mi llamada (mi sección crítica).
        CascadaAccesoLLM._ultimo_error_proxy_429 = False
        try:
            ok = _enriquecer_con_proxy_zai(
                bloque, workspace_dir=self._workspace_dir, llm=self._llm
            )
        except Exception as e:
            logger.warning(
                "CascadaAccesoLLM._procesar_bloque_nivel2: excepción %s para %s",
                e, getattr(bloque, "filename", str(bloque)),
            )
            return (False, False)
        # Capturar el flag inmediatamente (mi sección crítica).
        was_429 = bool(CascadaAccesoLLM._ultimo_error_proxy_429)

        if ok:
            return (True, False)
        if not was_429:
            # Falló por otra razón (W3, JSON parse, HTTP != 429, etc.) → Nivel 3.
            logger.info(
                "CascadaAccesoLLM._procesar_bloque_nivel2: %s falló por razón "
                "distinta a 429, caída a Nivel 3.",
                getattr(bloque, "filename", str(bloque)),
            )
            return (False, False)
        # 429: polling de progreso (15s).
        progreso = self._esperar_y_verificar_progreso()
        if not progreso:
            logger.info(
                "CascadaAccesoLLM._procesar_bloque_nivel2: sin progreso tras 429 "
                "para %s, return (False, True) (caída a Nivel 3).",
                getattr(bloque, "filename", str(bloque)),
            )
            return (False, True)
        logger.info(
            "CascadaAccesoLLM._procesar_bloque_nivel2: progreso detectado tras "
            "429, reintentando %s.",
            getattr(bloque, "filename", str(bloque)),
        )
        # Reset del flag antes de reintentar.
        CascadaAccesoLLM._ultimo_error_proxy_429 = False
        try:
            ok = _enriquecer_con_proxy_zai(
                bloque, workspace_dir=self._workspace_dir, llm=self._llm
            )
        except Exception as e:
            logger.warning(
                "CascadaAccesoLLM._procesar_bloque_nivel2 (retry): %s", e
            )
            return (False, True)
        was_429_retry = bool(CascadaAccesoLLM._ultimo_error_proxy_429)
        return (bool(ok), was_429_retry)

    def _nivel3_subagentes(self, tareas: list) -> bool:
        """Nivel 3: subagentes del agente CZAI — v6.17 F2 + D1.

        El proceso Python NO puede invocar el Task tool directamente. Pero
        puede publicar pending_tasks y devolver el control al agente CZAI
        para que las ejecute. Ese es el "mecanismo que el proceso tenga
        para invocar subagentes" (plan F2).

        Para cada bloque en Nivel 3:

        1. Construir el prompt con ``PROMPT_FUSIONADO_W1W2W3`` (el mismo
           prompt fusionado W1+W2+W3 que usa Nivel 2 al llamar al proxy).
        2. Publicar la pending_task en ``_pending_tasks.json`` (con el
           prompt construido) vía ``_persistir_pending_task_en_disco``.
        3. Devolver False (indicando que el agente CZAI debe procesar las
           pending_tasks).

        Nivel 3 no llama al proxy: si lo hiciera, sería Nivel 2. Nivel 3
        publica pending_tasks para que el agente CZAI las resuelva con
        Task tool.

        Args:
            tareas: Lista de ThematicBlock pendientes que Ni Nivel 1 ni
                Nivel 2 pudieron completar.

        Returns:
            True si no hay tareas que procesar. False si hay pending_tasks
            publicadas en ``self._pending_tasks`` para que el agente CZAI
            las procese con Task tool (y el bucle D7 las reintente con
            feedback hasta ``MAX_ITER_D7=5``).
        """
        if not tareas:
            return True

        from models import SubagentTask
        # Lazy import para evitar dependencia circular.
        from pipeline_w3 import PROMPT_FUSIONADO_W1W2W3

        ws = Path(self._workspace_dir)

        # v6.17 F2 + D1: Nivel 3 publica pending_tasks con el prompt
        # construido con PROMPT_FUSIONADO_W1W2W3. El agente CZAI las procesa
        # con Task tool (mecanismo que el proceso tiene para invocar
        # subagentes). Nivel 3 no llama al proxy directamente.
        for tarea in tareas:
            filename = getattr(tarea, "filename", "")
            block_id = filename.replace(".md", "")
            bloque_path = ws / filename

            # 1. Construir el prompt con PROMPT_FUSIONADO_W1W2W3.
            #    Leer el bloque del disco para incluir su contenido en el prompt.
            bloque_content = ""
            try:
                if bloque_path.exists():
                    bloque_content = bloque_path.read_text(
                        encoding="utf-8", errors="ignore"
                    )
                    max_chars = 50000
                    if len(bloque_content) > max_chars:
                        bloque_content = (
                            bloque_content[:max_chars]
                            + "\n...(contenido truncado)..."
                        )
            except Exception as e:
                logger.warning(
                    "v6.17 F2: Nivel 3 no pudo leer bloque %s: %s", filename, e,
                )

            prompt = PROMPT_FUSIONADO_W1W2W3.format(bloque_content=bloque_content)

            # 2. Publicar la pending_task en _pending_tasks.json (con el
            #    prompt construido).
            task = SubagentTask(
                task_id=f"enriquecer_{block_id}",
                purpose=f"v6.17.nivel3.{filename}",
                prompt=prompt,
                context={"filename": filename, "chat_label": "cascada_n3"},
            )
            self._pending_tasks.append(task)
            # v6.17 F11: persistencia vía _persistir_pending_task_en_disco
            # (la misma función que usa _post_bloque y el bucle D7).
            _persistir_pending_task_en_disco(
                workspace_dir=self._workspace_dir, task=task
            )
            logger.info(
                "v6.17 F2: Nivel 3 publicó pending_task para %s con "
                "PROMPT_FUSIONADO_W1W2W3 (para que el agente CZAI la "
                "procese con Task tool).",
                filename,
            )

        # 3. Devolver False (el agente CZAI debe procesar las pending_tasks).
        return False

    def _esperar_y_verificar_progreso(self) -> bool:
        """Polling fijo de ``CASCADA_INTERVALO_PROGRESO``s × ``CASCADA_UMBRAL_SIN_PROGRESO``.

        Usa ``AuditorWorkspace.auditar_completitud()`` para contar completados.
        Si en 3 intervalos consecutivos (5s cada uno = 15s total) no hay
        nuevo bloque completo → devuelve False (nivel caído). Si hay
        progreso en algún intervalo → devuelve True inmediatamente.

        Returns:
            True si se detectó progreso (al menos un bloque nuevo completo).
            False si tras 15s no hay progreso (caída del nivel).
        """
        from config import (
            CASCADA_INTERVALO_PROGRESO as _INTERVALO,
            CASCADA_UMBRAL_SIN_PROGRESO as _UMBRAL,
        )
        try:
            audit = AuditorWorkspace.auditar_completitud(self._workspace_dir)
        except Exception as e:
            logger.warning(
                "CascadaAccesoLLM._esperar_y_verificar_progreso: audit inicial falló: %s",
                e,
            )
            return False
        prev_completos = set(audit.get("completos", []))
        for i in range(_UMBRAL):
            time.sleep(_INTERVALO)
            try:
                audit = AuditorWorkspace.auditar_completitud(self._workspace_dir)
            except Exception as e:
                logger.warning(
                    "CascadaAccesoLLM._esperar_y_verificar_progreso: audit falló: %s",
                    e,
                )
                return False
            curr_completos = set(audit.get("completos", []))
            nuevos = curr_completos - prev_completos
            if nuevos:
                logger.info(
                    "CascadaAccesoLLM: progreso detectado (+%d completos): %s",
                    len(nuevos), sorted(nuevos),
                )
                return True
            prev_completos = curr_completos
        logger.info(
            "CascadaAccesoLLM: sin progreso tras %d×%ds = %ds. Caída del nivel.",
            _UMBRAL, _INTERVALO, _UMBRAL * _INTERVALO,
        )
        return False

    def get_pending_tasks(self) -> list:
        """Devuelve las ``pending_tasks`` acumuladas durante P14.

        Se rellenan en Nivel 3 (subagentes). El llamador (típicamente
        ``_enriquecer_bloques_con_fallback`` o ``_enriquecer_bloques_post_run``)
        las propaga al ``OrchestratorResult.pending_tasks`` para que el
        agente CZAI las ejecute con Task tool.

        Returns:
            Lista de SubagentTask pendientes (vacía si todas las tareas
            se completaron en Nivel 1 o Nivel 2).
        """
        return self._pending_tasks
