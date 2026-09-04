# contexto_zai/__init__.py -- Paquete principal del sistema de recuperacion de contexto para agentes Z.ai.
"""Contexto Z.ai -- Sistema de recuperación de contexto para agentes.

Proceso autónomo (v3.2) que se instala en el workspace del agente
y se activa cuando el agente detecta pérdida de contexto o el Director
lo indica.

Estado de implementación por milestone:
- M0 Foundation: [PASS] completado (config, models)
- M1 Autenticación: [PASS] completado (client/browser_session, auth_client, chat_client)
- M2 Procesamiento multi-tema: [PASS] completado (processing/classifier, block_packer, subdivider)
- M3 Metadata: [PASS] completado (metadata/manager)
- M4 Generación: [PASS] completado (generation/estado, indice, decisiones, bloque, recovery)
- M5 Detección: [PASS] completado (detection/lexic, token_counter, self_questions)
- M6 Subagentes: [PASS] completado (subagents/launcher + 4 especializados)
- M7 Orquestación: [PASS] completado (process/orchestrator, recovery_cycle, incremental_cycle, pipeline)
- M8 Verificación y contrato: ⏳ pendiente (requiere autorización para contrato.md)
- M9 Validación E2E: ⏳ pendiente

Uso::

    from contexto_zai.pipeline import run
    from contexto_zai.models import DetectionTrigger

    result = run(
        chat_id="13b43432-...",
        jwt="eyJhbG...",
        trigger=DetectionTrigger.EXPLICITO,
        reason="Director indicó pérdida de contexto",
    )
"""

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

__version__ = "3.2.0"
__all__ = [
    # Config
    "TOKEN_LIMITS",
    "API_CONFIG",
    "DEFAULT_THEME_RULES",
    # Client
    "BrowserSession",
    "AuthClient",
    "ChatClient",
    # Processing
    "ExchangeBuilder",
    "ContentCleaner",
    "MessageClassifier",
    "BlockPacker",
    "Subdivider",
    # Generation
    "EstadoGenerator",
    "IndiceGenerator",
    "DecisionesGenerator",
    "BloqueGenerator",
    "RecoveryGenerator",
    # Metadata
    "MetadataManager",
    # Detection
    "LexicTrigger",
    "TokenCounter",
    "SelfQuestions",
    # Subagents
    "SubagentLauncher",
    "EstadoSubagent",
    "BarridoSubagent",
    "DecisionesSubagent",
    "MantenimientoSubagent",
    # Process
    "Orchestrator",
    "RecoveryCycle",
    "IncrementalCycle",
    # Verification
    "Verifier",
]

from contexto_zai.config import (
    API_CONFIG,
    DEFAULT_THEME_RULES,
    TOKEN_LIMITS,
)
from contexto_zai.client.auth_client import AuthClient
from contexto_zai.client.browser_session import BrowserSession
from contexto_zai.client.chat_client import ChatClient
from contexto_zai.detection.lexic_trigger import LexicTrigger
from contexto_zai.detection.self_questions import SelfQuestions
from contexto_zai.detection.token_counter import TokenCounter
from contexto_zai.generation.bloque_generator import BloqueGenerator
from contexto_zai.generation.decisiones_generator import DecisionesGenerator
from contexto_zai.generation.estado_generator import EstadoGenerator
from contexto_zai.generation.indice_generator import IndiceGenerator
from contexto_zai.generation.recovery_generator import RecoveryGenerator
from contexto_zai.metadata.manager import MetadataManager
from contexto_zai.process.incremental_cycle import IncrementalCycle
from contexto_zai.process.orchestrator import Orchestrator
from contexto_zai.process.recovery_cycle import RecoveryCycle
from contexto_zai.processing.block_packer import BlockPacker
from contexto_zai.processing.classifier import MessageClassifier
from contexto_zai.processing.content_cleaner import ContentCleaner
from contexto_zai.processing.exchange_builder import ExchangeBuilder
from contexto_zai.processing.subdivider import Subdivider
from contexto_zai.subagents.barrido_subagent import BarridoSubagent
from contexto_zai.subagents.decisiones_subagent import DecisionesSubagent
from contexto_zai.subagents.estado_subagent import EstadoSubagent
from contexto_zai.subagents.launcher import SubagentLauncher
from contexto_zai.subagents.mantenimiento_subagent import MantenimientoSubagent
from contexto_zai.verification.verifier import Verifier
