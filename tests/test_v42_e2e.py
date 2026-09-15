# contexto_zai/tests/test_v42_e2e.py -- Tests E2E v4.2: flujo completo con la arquitectura F2+F4.
"""Tests E2E v4.2.

Valida el flujo completo:
1. pipeline.run() (con datos sintéticos) genera los archivos.
2. El proceso publica tareas vía EntregadorTareas.
3. (Simula que) el agente lanza subagentes que escriben respuestas.
4. collect_responses() lee respuestas, las integra, y devuelve resultado estructurado.
5. Los archivos se actualizan con las respuestas reales.

Script de dependencia: importa atómicos de coordinador y procesadores.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Auto-configuracion de sys.path
_here = Path(__file__).resolve().parent
_workspace = _here.parent.parent
if str(_workspace) not in sys.path:
    sys.path.insert(0, str(_workspace))

from contexto_zai.coordinador import (
    EntregadorTareas,
    IntegradorRespuestas,
    Orquestador,
    RecogedorRespuestas,
)
from contexto_zai.models import SubagentResponse, SubagentTask
from contexto_zai.pipeline import collect_responses


def test_entregador_publicar_leer():
    """EntregadorTareas publica y lee tareas en _pending_tasks.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ent = EntregadorTareas(workspace_dir=tmpdir)
        tasks = [
            SubagentTask(task_id="t1", purpose="estado.d4", prompt="p1"),
            SubagentTask(task_id="t2", purpose="decisiones", prompt="p2"),
        ]
        ent.publicar(tasks)
        assert ent.hay_tareas_pendientes()
        leidas = ent.leer()
        assert len(leidas) == 2
        assert leidas[0].task_id == "t1"
        print("[OK] EntregadorTareas: publicar+leer")


def test_recogedor_escribir_leer():
    """RecogedorRespuestas escribe y lee respuestas en _responses/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        rec = RecogedorRespuestas(workspace_dir=tmpdir)
        rec.escribir_respuesta("t1", "respuesta 1")
        rec.escribir_respuesta("t2", "respuesta 2", success=False, error="timeout")
        assert rec.total_respuestas() == 2
        responses = rec.leer_todas()
        assert len(responses) == 2
        assert responses[0].success
        assert not responses[1].success
        print("[OK] RecogedorRespuestas: escribir+leer")


def test_orquestador_coordinacion_completa():
    """Orquestador coordina publicar tareas, recibir respuestas, aplicar."""
    with tempfile.TemporaryDirectory() as tmpdir:
        orch = Orquestador(workspace_dir=tmpdir)
        # Publicar tareas
        orch.publicar_tareas([SubagentTask(task_id="t1", prompt="p1")])
        assert orch.hay_tareas_pendientes()
        # Escribir respuesta
        orch.recogedor.escribir_respuesta("t1", "r1")
        assert orch.hay_respuestas_listas()
        # Aplicar (sin integrador, solo lee)
        resultado = orch.aplicar_respuestas()
        assert resultado["total_leidas"] == 1
        # Limpia tras aplicar
        assert not orch.hay_tareas_pendientes()
        assert not orch.hay_respuestas_listas()
        print("[OK] Orquestador: coordinación completa")


def test_integrador_d4():
    """IntegradorRespuestas actualiza D4 en 00_estado_actual.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        Path(tmpdir, "00_estado_actual.md").write_text(
            "# Estado\n\n## Sección D4 -- Restricciones\n\nViejo.\n\n## A1\n", encoding="utf-8"
        )
        resp = SubagentResponse(
            task_id="estado_d4", success=True,
            response="RESTRICCION: No usar indigo\nALCANCE: general",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        content = Path(tmpdir, "00_estado_actual.md").read_text(encoding="utf-8")
        assert "indigo" in content
        print("[OK] Integrador D4: restricción actualizada")


def test_integrador_decisiones():
    """IntegradorRespuestas actualiza 02_decisiones_clave.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        Path(tmpdir, "02_decisiones_clave.md").write_text("# Decisiones\n\nViejo.\n", encoding="utf-8")
        resp = SubagentResponse(
            task_id="decisiones_lote_0", success=True,
            response="DECISION: Usar OOP\nALCANCE: ClasificadorSubagent\nRAZON: Directiva.",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        content = Path(tmpdir, "02_decisiones_clave.md").read_text(encoding="utf-8")
        assert "OOP" in content
        assert "ClasificadorSubagent" in content
        print("[OK] Integrador decisiones: decisión real con alcance")


def test_integrador_subdivider_nombre():
    """IntegradorRespuestas actualiza _metadata.json con nombre legible."""
    with tempfile.TemporaryDirectory() as tmpdir:
        integrador = IntegradorRespuestas(workspace_dir=tmpdir)
        Path(tmpdir, "_metadata.json").write_text(json.dumps({
            "tema_a_archivo": {"general_2026sep09": "bloque_01.md"}
        }), encoding="utf-8")
        resp = SubagentResponse(
            task_id="subdivider_nombre_general_2026sep09", success=True,
            response="autenticacion_jwt",
        )
        result = integrador.integrar([resp])
        assert result["total_applied"] == 1
        metadata = json.loads(Path(tmpdir, "_metadata.json").read_text(encoding="utf-8"))
        assert "autenticacion_jwt" in metadata["tema_a_archivo"]
        print("[OK] Integrador subdivider: metadata actualizada")


def test_flujo_completo_collect_responses():
    """Flujo completo: publicar tareas → escribir respuestas → collect_responses()."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. Crear archivos de recuperación (regex fallback)
        Path(tmpdir, "00_estado_actual.md").write_text(
            "# Estado\n\n## Sección D4 -- Restricciones\n\nPlaceholder.\n\n## A1\n",
            encoding="utf-8",
        )
        Path(tmpdir, "02_decisiones_clave.md").write_text("# Decisiones\n\nPlaceholder.\n", encoding="utf-8")
        Path(tmpdir, "_metadata.json").write_text(json.dumps({
            "tema_a_archivo": {"general_2026sep09": "bloque_01.md"}
        }), encoding="utf-8")

        # 2. Proceso publica tareas
        orch = Orquestador(workspace_dir=tmpdir)
        tasks = [
            SubagentTask(task_id="estado_d4", purpose="estado.d4", prompt="p1"),
            SubagentTask(task_id="decisiones_lote_0", purpose="decisiones", prompt="p2"),
            SubagentTask(task_id="subdivider_nombre_general_2026sep09", purpose="subdivider.nombre", prompt="p3"),
        ]
        orch.publicar_tareas(tasks)
        assert orch.total_pendientes if hasattr(orch, 'total_pendientes') else True

        # 3. Agente "lanzó" subagentes que escribieron respuestas
        recogedor = RecogedorRespuestas(workspace_dir=tmpdir)
        recogedor.escribir_respuesta("estado_d4", "RESTRICCION: No usar hardcoding\nALCANCE: general")
        recogedor.escribir_respuesta("decisiones_lote_0", "DECISION: Usar OOP\nALCANCE: ClasificadorSubagent\nRAZON: Directiva.")
        recogedor.escribir_respuesta("subdivider_nombre_general_2026sep09", "autenticacion_jwt")

        # 4. collect_responses() integra todo
        resultado = collect_responses(workspace_dir=tmpdir)
        assert resultado["total_leidas"] == 3
        assert resultado["total_aplicadas"] == 3
        assert len(resultado["errores"]) == 0

        # 5. Verificar archivos actualizados
        estado = Path(tmpdir, "00_estado_actual.md").read_text(encoding="utf-8")
        decisiones = Path(tmpdir, "02_decisiones_clave.md").read_text(encoding="utf-8")
        metadata = json.loads(Path(tmpdir, "_metadata.json").read_text(encoding="utf-8"))

        assert "hardcoding" in estado
        assert "OOP" in decisiones
        assert "autenticacion_jwt" in metadata["tema_a_archivo"]

        # 6. Tareas y respuestas limpiadas
        assert not orch.hay_tareas_pendientes()
        assert not orch.hay_respuestas_listas()

        print("[OK] Flujo completo: 3 tareas publicadas → 3 respuestas aplicadas → archivos actualizados")


def test_procesadores_documentos():
    """ProcesadorDocumento decide según tamaño (trivial, mediano, grande)."""
    from contexto_zai.procesadores import ProcesadorDocumento

    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorDocumento(workspace_dir=tmpdir)

        # Trivial
        small = Path(tmpdir, "small.txt")
        small.write_text("Hola", encoding="utf-8")
        result = proc.procesar(source_type="file", source_path=str(small))
        assert result["needs_agent_read"]
        assert result["tokens_estimados"] < 1000

        # Mediano
        medium = Path(tmpdir, "medium.txt")
        medium.write_text("x" * 17500, encoding="utf-8")
        result = proc.procesar(source_type="file", source_path=str(medium))
        assert not result["needs_agent_read"]
        assert len(result["pending_tasks"]) == 1

        # Grande
        large = Path(tmpdir, "large.txt")
        large.write_text("x" * 210000, encoding="utf-8")
        result = proc.procesar(source_type="file", source_path=str(large))
        assert result.get("flujo") == "3_niveles"

        print("[OK] ProcesadorDocumento: trivial/mediano/grande")


def test_procesador_intercambios():
    """ProcesadorIntercambios procesa intercambios en distintos modos."""
    from contexto_zai.procesadores import ProcesadorIntercambios
    from contexto_zai.models import Exchange, Message, MessageRole

    with tempfile.TemporaryDirectory() as tmpdir:
        proc = ProcesadorIntercambios(workspace_dir=tmpdir)
        exchanges = [
            Exchange(
                id=1,
                director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1.0, content="test"),
                agent_msgs=[Message(seq=2, role=MessageRole.ASSISTANT, timestamp=2.0, content="reply")],
                topic="general",
                start_timestamp=1.0,
                end_timestamp=2.0,
            )
        ]

        # Modo RESTRICCIONES_TEMA
        result = proc.procesar(modo="RESTRICCIONES_TEMA", intercambios=exchanges)
        assert result["modo"] == "RESTRICCIONES_TEMA"
        assert len(result["pending_tasks"]) == 1

        # Modo DECISIONES por lotes
        result = proc.procesar_por_lotes(modo="DECISIONES", intercambios=exchanges * 5, lote_size=2)
        assert result["total_lotes"] == 3
        assert len(result["pending_tasks"]) == 3

        print("[OK] ProcesadorIntercambios: modos y lotes")


def test_procesador_consulta():
    """ProcesadorConsulta identifica bloques candidatos y decide modo."""
    from contexto_zai.procesadores import ProcesadorConsulta

    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear contexto simulado
        Path(tmpdir, "01_indice_recuperacion.md").write_text("# Índice\n\n## jwt\n", encoding="utf-8")
        Path(tmpdir, "_metadata.json").write_text(json.dumps({
            "tema_a_archivo": {"jwt_autenticacion": "bloque_01.md"}
        }), encoding="utf-8")
        Path(tmpdir, "bloque_01.md").write_text("Contenido sobre JWT y autenticación.", encoding="utf-8")

        proc = ProcesadorConsulta(workspace_dir=tmpdir)
        result = proc.procesar(pregunta="¿qué se decidió sobre jwt?")
        assert result["modo"] == "directo"
        assert len(result["pending_tasks"]) == 1
        assert result["pending_tasks"][0].purpose == "consulta.bloque"

        print("[OK] ProcesadorConsulta: modo directo identificado")


def test_clasificacion_temas_e2e():
    """E2E CLASIFICACION_TEMAS (F4 v4.2): publicar tarea → simular respuesta → integrar.

    Verifica que el flujo completo de Capa 3 funcione:
    1. ProcesadorIntercambios.procesar(CLASIFICACION_TEMAS) publica una tarea.
    2. La tarea tiene el prompt correcto (SUBTEMA/EXCHANGES, no RESTRICCIONES).
    3. (Simula) el agente lanza un subagente que responde con subtemas.
    4. collect_responses() integra la respuesta actualizando _metadata.json.
    """
    from contexto_zai.procesadores import ProcesadorIntercambios

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)

        # Setup: metadata inicial con un tema grande
        (ws / "_metadata.json").write_text(json.dumps({
            "tema_a_archivo": {"validaciones": "bloque_03.md"}
        }), encoding="utf-8")

        # 1. ProcesadorIntercambios publica la tarea CLASIFICACION_TEMAS
        proc = ProcesadorIntercambios(workspace_dir=ws, orquestador=Orquestador(workspace_dir=ws))
        result = proc.procesar(
            modo="CLASIFICACION_TEMAS",
            intercambios=[
                # Mock simplificado de intercambios
                type("X", (), {"id": 1, "director_msg": type("M", (), {"content": "msg 1"})(),
                               "agent_msgs": [], "topic": "validaciones",
                               "datetime_str": "2026-09-09"})(),
                type("X", (), {"id": 2, "director_msg": type("M", (), {"content": "msg 2"})(),
                               "agent_msgs": [], "topic": "validaciones",
                               "datetime_str": "2026-09-09"})(),
            ],
            context={"tema_padre": "validaciones"},
            task_id_suffix="capa3_validaciones",
        )
        assert len(result["pending_tasks"]) == 1
        task = result["pending_tasks"][0]
        # 2. El prompt es el correcto (no alias de RESTRICCIONES)
        assert "SUBTEMA:" in task.prompt
        assert "EXCHANGES:" in task.prompt
        assert "RESTRICCION:" not in task.prompt

        # 3. Simular: el agente lanza el subagente y escribe la respuesta
        mock_response = """SUBTEMA: validaciones_server
DESCRIPCION: Validaciones del servidor backend
EXCHANGES: 1

SUBTEMA: validaciones_router
DESCRIPCION: Validaciones del router HTTP
EXCHANGES: 2"""
        RecogedorRespuestas(workspace_dir=ws).escribir_respuesta(task.task_id, mock_response)

        # 4. collect_responses() integra la respuesta
        resultado = collect_responses(workspace_dir=str(ws))
        assert resultado.get("total_aplicadas", 0) >= 1, f"Esperaba ≥1 aplicada, obtuvo: {resultado}"

        # Verificar que metadata se actualizó con los subtemas
        metadata = json.loads((ws / "_metadata.json").read_text(encoding="utf-8"))
        assert "validaciones_validaciones_server" in metadata["tema_a_archivo"]
        assert "validaciones_validaciones_router" in metadata["tema_a_archivo"]
        # El tema padre se mantiene
        assert "validaciones" in metadata["tema_a_archivo"]

        print("[OK] CLASIFICACION_TEMAS E2E: tarea publicada → respuesta integrada → metadata actualizada")


def test_query_context_encuentra_bloque_externo():
    """E2E v4.2 unificación: query_context() encuentra bloques externos de ampliar_contexto().

    Flujo completo:
    1. ampliar_contexto() publica tarea (simulado vía ProcesadorDocumento).
    2. Subagente indexador responde con temas reales (TEMA/DESCRIPCION/SECCIONES).
    3. collect_responses() integra la respuesta: crea bloque_externo_*.md y
       registra los temas reales en _metadata.json (no nombre genérico).
    4. query_context() encuentra el bloque externo por el tema real, sin
       necesitar 01_indice_recuperacion.md.
    """
    from contexto_zai.coordinador import Orquestador, RecogedorRespuestas
    from contexto_zai.procesadores import ProcesadorDocumento
    from contexto_zai.pipeline import collect_responses, query_context

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)

        # _metadata.json vacío inicial
        (ws / "_metadata.json").write_text(json.dumps({"tema_a_archivo": {}}), encoding="utf-8")

        # 1. ProcesadorDocumento publica la tarea de indexación
        proc = ProcesadorDocumento(workspace_dir=ws, orquestador=Orquestador(workspace_dir=ws))
        # Crear un archivo PDF simulado
        pdf_path = ws / "documento_seguridad.pdf"
        pdf_path.write_bytes(b"PDF simulado sobre autenticacion JWT y control de acceso" * 200)

        result = proc.procesar(
            source_type="file",
            source_path=str(pdf_path),
            jwt="",
            metadata={"filename": "documento_seguridad.pdf"},
        )
        assert len(result["pending_tasks"]) >= 1
        task = result["pending_tasks"][0]
        assert "documento_" in task.task_id

        # 2. Simular: el agente lanza el subagente indexador y responde con temas reales
        mock_response = """RESUMEN: Documento sobre el sistema de seguridad y autenticación.

TEMA: autenticacion_jwt
DESCRIPCION: Sistema de autenticación basado en JWT
SECCIONES: header, payload, signature

TEMA: control_acceso
DESCRIPCION: Control de acceso por roles
SECCIONES: roles, permisos"""
        RecogedorRespuestas(workspace_dir=ws).escribir_respuesta(task.task_id, mock_response)

        # 3. collect_responses() integra la respuesta
        resultado = collect_responses(workspace_dir=str(ws))
        assert resultado.get("total_aplicadas", 0) >= 1, f"Esperaba ≥1 aplicada: {resultado}"

        # Verificar que el bloque externo físico existe
        bloques_externos = list(ws.glob("bloque_externo_*.md"))
        assert len(bloques_externos) >= 1, f"Esperaba ≥1 bloque externo: {bloques_externos}"

        # Verificar que los temas reales están en _metadata.json (no nombres genéricos)
        metadata = json.loads((ws / "_metadata.json").read_text(encoding="utf-8"))
        assert "autenticacion_jwt" in metadata["tema_a_archivo"], \
            f"Falta tema real 'autenticacion_jwt': {metadata['tema_a_archivo']}"
        assert "control_acceso" in metadata["tema_a_archivo"]

        # 4. query_context() encuentra el bloque externo por el tema real
        # SIN necesidad de 01_indice_recuperacion.md (no existe en este workspace)
        assert not (ws / "01_indice_recuperacion.md").exists(), \
            "Este test valida que NO se necesita el índice del chat"

        query_result = query_context("¿qué dice sobre jwt?", workspace_dir=str(ws))
        assert "error" not in query_result, f"Esperaba encontrar bloque, obtuvo error: {query_result}"
        assert query_result["mode"] == "direct"
        # El bloque encontrado es el externo
        assert any("bloque_externo_" in b for b in query_result["bloques"]), \
            f"Esperaba bloque externo en candidatos: {query_result['bloques']}"
        # El tema real está en los candidatos
        assert "autenticacion_jwt" in query_result["bloques_info"][0]["temas"]

        print("[OK] query_context E2E: encuentra bloque externo por tema real (sin 01_indice)")


def main():
    print("=== Tests E2E v4.2 ===\n")

    tests = [
        test_entregador_publicar_leer,
        test_recogedor_escribir_leer,
        test_orquestador_coordinacion_completa,
        test_integrador_d4,
        test_integrador_decisiones,
        test_integrador_subdivider_nombre,
        test_flujo_completo_collect_responses,
        test_procesadores_documentos,
        test_procesador_intercambios,
        test_procesador_consulta,
        test_clasificacion_temas_e2e,
        test_query_context_encuentra_bloque_externo,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n=== Resumen: {passed} pasaron, {failed} fallaron ===")
    if failed == 0:
        print("[PASS] Todos los tests E2E v4.2 pasaron")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import io as _io, sys as _sys
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass
    sys.exit(main())
