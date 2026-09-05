# contexto_zai/processing/decision_extractor.py -- Extractor de decisiones reales por patrones semanticos (no regex ingenuo).
"""Extractor de decisiones reales por patrones semanticos (v3.3).

Detecta decisiones reales del Director en los intercambios del chat.
No usa regex que busca la palabra "decision" (eso producia basura).
En su lugar, detecta patrones semanticos de decisiones reales:

1. Aprobaciones: "correcto", "aprobado", "a ejecutar", "autorizado",
   "continua", "adelante", "a implementar".
2. Rechazos: "no estoy de acuerdo", "incorrecto", "descarta",
   "no sirve", "no me gusta".
3. Directivas: "quiero que", "necesito que", "vamos a",
   "a implementar", "a ejecutar".
4. Cambios de rumbo: "cambiemos", "en lugar de", "mejor hacer".
5. Comunicacion explicita: "decidimos", "a partir de ahora",
   "queda descartado", "queda decidido".

Cada decision detectada se extrae con el contexto del intercambio
donde aparecio.

Atomica standalone: importa models, nada mas del proyecto.
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
for _ in range(5):
    if _os.path.isdir(_os.path.join(_candidate, 'contexto_zai')):
        if _candidate not in _sys.path:
            _sys.path.insert(0, _candidate)
        break
    _candidate = _os.path.dirname(_candidate)
else:
    _parent = _os.path.dirname(_here)
    if _parent not in _sys.path:
        _sys.path.insert(0, _parent)

import logging
import re
from typing import TYPE_CHECKING

from contexto_zai.models import Decision

if TYPE_CHECKING:
    from contexto_zai.models import Exchange

logger = logging.getLogger(__name__)


# Patrones semanticos de decisiones reales (no regex de la palabra "decision")
DECISION_PATTERNS: list[tuple[str, str, str]] = [
    # (categoria, patron_regex, tipo_de_decision)
    # Aprobaciones
    ("Aprobacion", r"(?i)^\s*correcto\b", "Aprobacion del Director"),
    ("Aprobacion", r"(?i)^\s*aprobado\b", "Aprobacion explicita"),
    ("Aprobacion", r"(?i)^\s*a ejecutar\b", "Autorizacion de ejecucion"),
    ("Aprobacion", r"(?i)^\s*a implementar\b", "Autorizacion de implementacion"),
    ("Aprobacion", r"(?i)^\s*autorizado\b", "Autorizacion explicita"),
    ("Aprobacion", r"(?i)^\s*continua\b", "Continuacion autorizada"),
    ("Aprobacion", r"(?i)^\s*adelante\b", "Continuacion autorizada"),
    ("Aprobacion", r"(?i)^\s*ok\b", "Aprobacion"),

    # Rechazos
    ("Rechazo", r"(?i)^\s*no estoy de acuerdo", "Rechazo explicito"),
    ("Rechazo", r"(?i)^\s*incorrecto\b", "Rechazo del Director"),
    ("Rechazo", r"(?i)^\s*descarta\b", "Descarte"),
    ("Rechazo", r"(?i)^\s*no sirve\b", "Rechazo"),
    ("Rechazo", r"(?i)^\s*no me gusta\b", "Rechazo"),

    # Directivas que se convierten en decisiones
    ("Directiva", r"(?i)^\s*quiero que\b", "Directiva del Director"),
    ("Directiva", r"(?i)^\s*necesito que\b", "Directiva del Director"),
    ("Directiva", r"(?i)^\s*vamos a\b", "Decision de rumbo"),

    # Cambios de rumbo
    ("Cambio de rumbo", r"(?i)^\s*cambiemos\b", "Cambio de rumbo"),
    ("Cambio de rumbo", r"(?i)^\s*en lugar de\b", "Cambio de enfoque"),
    ("Cambio de rumbo", r"(?i)^\s*mejor hacer\b", "Cambio de enfoque"),

    # Comunicacion explicita de decision
    ("Decision explicita", r"(?i)^\s*decidimos\b", "Decision tomada"),
    ("Decision explicita", r"(?i)^\s*a partir de ahora\b", "Cambio permanente"),
    ("Decision explicita", r"(?i)^\s*queda descartado\b", "Descarte formal"),
    ("Decision explicita", r"(?i)^\s*queda decidido\b", "Decision formal"),
    ("Decision explicita", r"(?i)^\s*no lo que te pedi\b", "Correccion de rumbo"),

    # Especificas del proyecto
    ("Especifica", r"(?i)^\s*entrega primero\b", "Priorizacion de entrega"),
    ("Especifica", r"(?i)^\s*describe este proceso\b", "Solicitud de documentacion"),
    ("Especifica", r"(?i)^\s*rehacer la spec\b", "Solicitud de reespecificacion"),
    ("Especifica", r"(?i)^\s*describe paso a paso\b", "Solicitud de documentacion"),
]


class DecisionExtractor:
    """Extrae decisiones reales de intercambios por patrones semanticos.

    Usage:
        >>> extractor = DecisionExtractor()
        >>> decisions = extractor.extract(exchanges)
    """

    def __init__(self) -> None:
        # Compilar patrones (los patrones ya tienen (?i) inline para case-insensitive)
        self._compiled: list[tuple[str, str, re.Pattern]] = [
            (cat, tipo, re.compile(pat, re.MULTILINE))
            for cat, pat, tipo in DECISION_PATTERNS
        ]
        logger.debug("DecisionExtractor inicializado: %d patrones", len(self._compiled))

    # ── API publica ────────────────────────────────────────────

    def extract(
        self,
        exchanges: list["Exchange"],
        existing_decisions: list[Decision] | None = None,
    ) -> list[Decision]:
        """Extrae decisiones de una lista de intercambios.

        Para cada decision detectada, busca el intercambio anterior
        para extraer el contexto de que se esta aprobando, rechazando
        o autorizando. Asi "Correcto" se convierte en "Correcto --
        en respuesta a: [lo que el agente propuso]".

        Args:
            exchanges: Lista de intercambios a procesar (orden cronologico).
            existing_decisions: Decisiones ya registradas (para deduplicar).

        Returns:
            Lista de Decision nuevas detectadas con contexto del intercambio anterior.
        """
        existing_titles = {
            d.title.lower().strip() for d in (existing_decisions or []) if d.title
        }

        new_decisions: list[Decision] = []
        decision_counter = 0

        for i, ex in enumerate(exchanges):
            director_text = ex.director_msg.content.strip()
            if not director_text:
                continue

            # Buscar patrones en el mensaje del Director
            for categoria, tipo, pattern in self._compiled:
                match = pattern.search(director_text)
                if match:
                    # Extraer el texto de la decision del Director
                    start = max(0, match.start() - 50)
                    end = min(len(director_text), match.end() + 200)
                    decision_text = director_text[start:end].strip()

                    # Buscar el intercambio anterior para obtener contexto
                    # de que se esta aprobando/rechazando/autorizando
                    context_anterior = ""
                    if i > 0:
                        prev_ex = exchanges[i - 1]
                        # El contexto es lo que el agente respondio en el
                        # intercambio anterior (lo que el Director esta
                        # aprobando o rechazando)
                        if prev_ex.agent_msgs:
                            prev_agent_text = prev_ex.agent_msgs[-1].content.strip()
                            # Limpiar JSON de tool_calls del contexto
                            prev_agent_text = self._clean_agent_context(prev_agent_text)
                            # Extraer las primeras 300 chars del agente como contexto
                            context_anterior = prev_agent_text[:300]
                            if len(prev_agent_text) > 300:
                                context_anterior += "..."

                    # Construir el titulo con contexto
                    if context_anterior:
                        # Extraer la primera linea o frase del contexto anterior
                        # como resumen de que se esta aprobando
                        primera_linea = context_anterior.split("\n")[0][:100]
                        title = f"{tipo}: {decision_text[:60]}... (en respuesta a: {primera_linea})"
                    else:
                        title = f"{tipo}: {decision_text[:80]}..."

                    title_key = title.lower().strip()

                    # Deduplicar
                    if title_key in existing_titles:
                        break
                    existing_titles.add(title_key)

                    # Construir la decision completa con contexto
                    decision_full = decision_text[:500]
                    if context_anterior:
                        decision_full = (
                            f"{decision_text}\n\n"
                            f"--- Contexto (lo que el agente propuso antes) ---\n"
                            f"{context_anterior}"
                        )

                    new_decisions.append(Decision(
                        id="",
                        timestamp=ex.start_timestamp,
                        title=title,
                        decision=decision_full,
                        reason=f"Detectada en intercambio {ex.id}, categoria: {categoria}",
                        impact="A determinar",
                        tema=ex.topic,
                    ))
                    break  # Una decision por intercambio (la primera encontrada)

        logger.info(
            "Extraccion: %d intercambios -> %d decisiones detectadas",
            len(exchanges), len(new_decisions),
        )
        return new_decisions

    def __repr__(self) -> str:
        return f"DecisionExtractor(patterns={len(self._compiled)})"

    def _clean_agent_context(self, text: str) -> str:
        """Limpia el contexto del agente para que sea legible.

        Elimina bloques JSON de tool_calls, content_blocks, y otros
        artefactos que el agente incluye en sus respuestas pero que
        no aportan valor al contexto de la decision.
        """
        import json as _json

        # Si el texto empieza con {, intentar parsear como JSON
        # y extraer solo el contenido de texto
        if text.startswith("{"):
            try:
                data = _json.loads(text)
                if isinstance(data, dict) and "content" in data:
                    content = data["content"]
                    if isinstance(content, str):
                        return content.strip()
                    elif isinstance(content, list):
                        parts = []
                        for block in content:
                            if isinstance(block, dict) and "text" in block:
                                parts.append(block["text"])
                            elif isinstance(block, str):
                                parts.append(block)
                        return "\n".join(parts).strip()
            except (_json.JSONDecodeError, ValueError):
                pass

        # Eliminar lineas que parezcan JSON de tool_calls
        lines = text.split("\n")
        clean_lines = []
        in_json = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('{"type":') or stripped.startswith('[{'):
                in_json = True
                continue
            if in_json:
                if stripped.endswith("}") or stripped.endswith("]"):
                    in_json = False
                continue
            clean_lines.append(line)

        return "\n".join(clean_lines).strip()


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

    print("=== Validacion de decision_extractor.py ===\n")

    from contexto_zai.models import Exchange, Message, MessageRole

    extractor = DecisionExtractor()

    # Helper: crear un intercambio con respuesta del agente
    def make_exchange(ex_id, director_text, agent_text="", topic="general", ts=100):
        return Exchange(
            id=ex_id,
            director_msg=Message(seq=ex_id * 2 - 1, role=MessageRole.USER, timestamp=ts, content=director_text),
            agent_msgs=[Message(seq=ex_id * 2, role=MessageRole.ASSISTANT, timestamp=ts + 1, content=agent_text)] if agent_text else [],
            topic=topic,
            start_timestamp=ts,
            end_timestamp=ts + 1,
        )

    # Test 1: aprobacion con contexto del intercambio anterior
    exchanges = [
        make_exchange(1, "Describe el plan", "He creado el plan de refactorizacion v2 con 9 milestones."),
        make_exchange(2, "Correcto, a implementar", "", ts=200),
    ]
    decisions = extractor.extract(exchanges)
    assert len(decisions) >= 1, f"Esperaba >=1 decision, obtuve {len(decisions)}"
    d1 = decisions[0]
    assert "Aprobacion" in d1.title or "Autorizacion" in d1.title
    # Debe contener contexto del intercambio anterior
    assert "en respuesta a" in d1.title or "plan" in d1.decision.lower()
    assert "plan de refactorizacion" in d1.decision
    print(f"[OK] Aprobacion con contexto: {d1.title[:80]}...")

    # Test 2: rechazo con contexto
    exchanges2 = [
        make_exchange(3, "Que propones?", "Propongo partir el contenido por fragmentos frag1, frag2."),
        make_exchange(4, "No estoy de acuerdo con lo que quieres hacer", "", ts=300),
    ]
    decisions2 = extractor.extract(exchanges2)
    assert len(decisions2) >= 1
    d2 = decisions2[0]
    assert "Rechazo" in d2.title
    assert "fragmentos" in d2.decision.lower() or "frag" in d2.decision.lower()
    print(f"[OK] Rechazo con contexto: {d2.title[:80]}...")

    # Test 3: directiva con contexto
    exchanges3 = [
        make_exchange(5, "Estado?", "El proceso esta en M4. Falta integrar subdivider."),
        make_exchange(6, "Quiero que reinicies exactamente como lo haria un agente nuevo", "", ts=500),
    ]
    decisions3 = extractor.extract(exchanges3)
    assert len(decisions3) >= 1
    d3 = decisions3[0]
    assert "Directiva" in d3.title
    assert "M4" in d3.decision or "subdivider" in d3.decision.lower()
    print(f"[OK] Directiva con contexto: {d3.title[:80]}...")

    # Test 4: priorizacion con contexto
    exchanges4 = [
        make_exchange(7, "Como seguimos?", "Puedo implementar el spec o el codigo primero."),
        make_exchange(8, "Entrega primero el spec y el plan, para despues implementarlo", "", ts=600),
    ]
    decisions4 = extractor.extract(exchanges4)
    assert len(decisions4) >= 1
    d4 = decisions4[0]
    assert "Priorizacion" in d4.title
    assert "spec" in d4.decision.lower()
    print(f"[OK] Priorizacion con contexto: {d4.title[:80]}...")

    # Test 5: deduplicacion
    existing = [Decision(id="D01", timestamp=0, title=decisions[0].title, decision="X")]
    decisions5 = extractor.extract(exchanges, existing_decisions=existing)
    assert len(decisions5) == 0, f"Deberia estar deduplicada, obtuve {len(decisions5)}"
    print(f"[OK] Deduplicacion: decision repetida no se anade")

    # Test 6: mensaje neutro no detecta nada
    exchanges6 = [
        make_exchange(10, "Hola, como estas?", "Bien, gracias.", ts=700),
    ]
    decisions6 = extractor.extract(exchanges6)
    assert len(decisions6) == 0
    print(f"[OK] Mensaje neutro: 0 decisiones")

    # Test 7: "A ejecutar" con contexto
    exchanges7 = [
        make_exchange(11, "Tienes el plan?", "Si, el plan v2 esta listo con 9 milestones."),
        make_exchange(12, "A ejecutar", "", ts=800),
    ]
    decisions7 = extractor.extract(exchanges7)
    assert len(decisions7) >= 1
    d7 = decisions7[0]
    assert "Autorizacion" in d7.title or "Aprobacion" in d7.title
    assert "plan v2" in d7.decision.lower()
    print(f"[OK] 'A ejecutar' con contexto: {d7.title[:80]}...")

    # Test 8: decision sin intercambio anterior (primera del chat)
    exchanges8 = [
        make_exchange(13, "Correcto", "", ts=900),
    ]
    decisions8 = extractor.extract(exchanges8)
    assert len(decisions8) >= 1
    d8 = decisions8[0]
    # Sin contexto anterior, el titulo no tiene "en respuesta a"
    assert "en respuesta a" not in d8.title
    print(f"[OK] Decision sin contexto anterior (primer intercambio): OK")

    # Test 9: multiples decisiones con contexto
    all_exchanges = exchanges + exchanges2 + exchanges3 + exchanges4 + exchanges7
    all_decisions = extractor.extract(all_exchanges)
    assert len(all_decisions) >= 5, f"Esperaba >=5 decisiones, obtuve {len(all_decisions)}"
    # Todas deben tener contexto del intercambio anterior (excepto la primera)
    for d in all_decisions:
        if d.timestamp > 100:
            assert "en respuesta a" in d.title or "Contexto" in d.decision, (
                f"Decision sin contexto: {d.title}"
            )
    print(f"[OK] Multiples decisiones con contexto: {len(all_decisions)} detectadas")

    # Test 10: correccion de rumbo con contexto
    exchanges10 = [
        make_exchange(14, "Hiciste lo que pedi?", "Si, valide el codigo anterior con datos simulados."),
        make_exchange(15, "No lo que te pedi en el prompt anterior no era que validaras el codigo", "", ts=1000),
    ]
    decisions10 = extractor.extract(exchanges10)
    assert len(decisions10) >= 1
    d10 = decisions10[0]
    assert "Correccion" in d10.title
    assert "valide" in d10.decision.lower() or "simulados" in d10.decision.lower()
    print(f"[OK] Correccion de rumbo con contexto: {d10.title[:80]}...")

    print("\n[PASS] decision_extractor.py: todos los tests pasaron")
