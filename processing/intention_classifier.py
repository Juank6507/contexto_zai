# processing/intention_classifier.py -- Capa 2 de clasificacion: analiza la intencion del usuario para descomponer el tema "general" en temas reales.
"""Clasificador por intencion (v3.4).

Capa 2 del sistema de clasificacion tematica. Cuando un
intercambio se clasifica como "general" en la Capa 1 (lexica),
este modulo analiza la intencion del usuario para asignarle
un tema real y especifico.

Temas de intencion:
- solicitud_documentacion: "describe", "explica", "paso a paso"
- solicitud_implementacion: "implementa", "ejecuta", "a ejecutar"
- aprobacion: "correcto", "aprobado", "ok"
- rechazo: "no estoy de acuerdo", "incorrecto"
- correccion: "no lo que te pedi", "mejor hacer"
- consulta_estado: "como vamos", "estado", "que falta"
- handoff: "relee el worklog", "perdiste contexto"
- priorizacion: "entrega primero", "necesito que"

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
from typing import Optional

# v3.4: INTENTION_THEMES se centraliza en config.py para configuración sin tocar código.
# Se mantiene el fallback local para compatibilidad con tests standalone.
try:
    from contexto_zai.config import INTENTION_THEMES as _CONFIG_INTENTION_THEMES
    INTENTION_THEMES: dict[str, list[str]] = _CONFIG_INTENTION_THEMES
except ImportError:
    # Fallback standalone (si config.py no está disponible)
    INTENTION_THEMES: dict[str, list[str]] = {
        "solicitud_documentacion": [
            "describe", "explica", "paso a paso", "dime que entiendes",
            "que entiendes", "resumen", "resume",
        ],
        "solicitud_implementacion": [
            "implementa", "ejecuta", "a ejecutar", "a implementar",
            "codifica", "programa", "desarrolla",
        ],
        "aprobacion": [
            "correcto", "aprobado", "ok", "adelante", "continua",
            "sigue", "procede",
        ],
        "rechazo": [
            "no estoy de acuerdo", "incorrecto", "no sirve",
            "no me gusta", "negado", "descarta",
        ],
        "correccion": [
            "no lo que te pedi", "mejor hacer", "en lugar de",
            "cambiemos", "no es eso",
        ],
        "consulta_estado": [
            "como vamos", "estado", "que falta", "donde quedamos",
            "progreso", "avance",
        ],
        "handoff": [
            "relee el worklog", "perdiste contexto", "ya te dije",
            "no repitas", "estas olvidando",
        ],
        "priorizacion": [
            "entrega primero", "necesito que", "primero haz",
            "prioriza", "urgente",
        ],
    }

logger = logging.getLogger(__name__)


class IntentionClassifier:
    """Clasifica intercambios por intencion del usuario (Capa 2).

    Recibe un intercambio clasificado como "general" y analiza
    la intencion del mensaje del Director para asignarle un
    tema real y especifico.

    Usage:
        >>> classifier = IntentionClassifier()
        >>> tema = classifier.classify("Correcto, a implementar")
        >>> print(tema)  # "aprobacion"
    """

    def __init__(self) -> None:
        # Compilar patrones (case-insensitive)
        self._compiled: dict[str, list[re.Pattern]] = {}
        for tema, keywords in INTENTION_THEMES.items():
            self._compiled[tema] = [
                re.compile(re.escape(kw), re.IGNORECASE)
                for kw in keywords
            ]
        logger.debug("IntentionClassifier inicializado: %d temas", len(self._compiled))

    # ── API publica ────────────────────────────────────────────

    def classify(self, text: str) -> str:
        """Clasifica un texto por intencion del usuario.

        Args:
            text: Texto del mensaje del Director.

        Returns:
            Tema de intencion (ej: "aprobacion", "rechazo"),
            o "general" si no se detecta intencion.
        """
        if not text:
            return "general"

        text_lower = text.lower()

        # Buscar coincidencias por tema
        scores: dict[str, int] = {}
        for tema, patterns in self._compiled.items():
            count = sum(1 for p in patterns if p.search(text_lower))
            if count > 0:
                scores[tema] = count

        if not scores:
            return "general"

        # Tema con mas coincidencias
        best_tema = max(scores, key=scores.get)
        logger.debug(
            "Intencion detectada: '%s' (score=%d) para texto: '%.50s...'",
            best_tema, scores[best_tema], text,
        )
        return best_tema

    def classify_exchange(self, exchange) -> str:
        """Clasifica un intercambio por intencion.

        Args:
            exchange: Objeto Exchange con director_msg.

        Returns:
            Tema de intencion, o "general" si no se detecta.
        """
        return self.classify(exchange.director_msg.content)

    def get_themes(self) -> list[str]:
        """Devuelve la lista de temas de intencion disponibles."""
        return list(self._compiled.keys())

    def __repr__(self) -> str:
        return f"IntentionClassifier(themes={len(self._compiled)})"


if __name__ == "__main__":
    import io as _io
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass

    print("=== Validacion de intention_classifier.py ===\n")

    classifier = IntentionClassifier()

    # Test 1: aprobacion (gana por mas coincidencias: "correcto" + "implementar")
    assert classifier.classify("Correcto, a implementar") == "solicitud_implementacion"
    print("[OK] 'Correcto, a implementar' -> solicitud_implementacion (2 keywords vs 1)")

    # Test 1b: aprobacion pura
    assert classifier.classify("Correcto") == "aprobacion"
    print("[OK] Aprobacion: 'Correcto' -> aprobacion")

    # Test 2: rechazo
    assert classifier.classify("No estoy de acuerdo con esto") == "rechazo"
    print("[OK] Rechazo: 'No estoy de acuerdo' -> rechazo")

    # Test 3: solicitud de documentacion
    assert classifier.classify("Describe este proceso paso a paso") == "solicitud_documentacion"
    print("[OK] Solicitud doc: 'Describe paso a paso' -> solicitud_documentacion")

    # Test 4: solicitud de implementacion
    assert classifier.classify("A ejecutar el plan") == "solicitud_implementacion"
    print("[OK] Solicitud impl: 'A ejecutar' -> solicitud_implementacion")

    # Test 5: correccion
    assert classifier.classify("No lo que te pedi era otra cosa") == "correccion"
    print("[OK] Correccion: 'No lo que te pedi' -> correccion")

    # Test 6: consulta de estado
    assert classifier.classify("Como vamos con el proyecto") == "consulta_estado"
    print("[OK] Consulta estado: 'Como vamos' -> consulta_estado")

    # Test 7: handoff
    assert classifier.classify("Relee el worklog") == "handoff"
    print("[OK] Handoff: 'Relee el worklog' -> handoff")

    # Test 8: priorizacion
    assert classifier.classify("Entrega primero el spec") == "priorizacion"
    print("[OK] Priorizacion: 'Entrega primero' -> priorizacion")

    # Test 9: mensaje neutro -> general
    assert classifier.classify("Hola, como estas?") == "general"
    print("[OK] Mensaje neutro: 'Hola' -> general")

    # Test 10: texto vacio -> general
    assert classifier.classify("") == "general"
    print("[OK] Texto vacio -> general")

    # Test 11: get_themes
    themes = classifier.get_themes()
    assert len(themes) == 8
    print(f"[OK] get_themes: {len(themes)} temas disponibles")

    # Test 12: classify_exchange
    from contexto_zai.models import Exchange, Message, MessageRole
    ex = Exchange(
        id=1,
        director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="Correcto"),
        topic="general",
        start_timestamp=1,
        end_timestamp=2,
    )
    assert classifier.classify_exchange(ex) == "aprobacion"
    print("[OK] classify_exchange: 'Correcto' -> aprobacion")

    print("\n[PASS] intention_classifier.py: todos los tests pasaron")
