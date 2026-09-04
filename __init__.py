"""Contexto Z.ai — Sistema de recuperación de contexto para agentes.

Proceso autónomo (v3.2) que se instala en el workspace del agente
y se activa cuando el agente detecta pérdida de contexto o el Director
lo indica. Reemplaza la arquitectura CLI de v1.0/v2.3.

Estado de implementación por milestone:
- M0 Foundation: ✅ completado (config, models)
- M1 Autenticación: ✅ completado (client/browser_session, auth_client, chat_client)
- M2 Procesamiento multi-tema: ⏳ pendiente (processing/classifier, block_packer, subdivider)
- M3 Metadata: ⏳ pendiente (metadata/manager)
- M4 Generación: ⏳ pendiente (generation/estado, indice, decisiones)
- M5 Detección: ⏳ pendiente (detection/lexic, token_counter, self_questions)
- M6 Subagentes: ⏳ pendiente (subagents/launcher + 4 subagentes)
- M7 Orquestación: ⏳ pendiente (process/orchestrator, recovery_cycle, incremental_cycle, pipeline)
- M8 Verificación: ⏳ pendiente (refinar verifier, actualizar contrato.md)
- M9 Validación E2E: ⏳ pendiente

Uso (cuando M7 esté completo)::

    from contexto_zai.process.orchestrator import Orchestrator
    orchestrator = Orchestrator(chat_id="...", jwt="...")
    orchestrator.activate(trigger=DetectionTrigger.EXPLICITO)
"""

__version__ = "3.2.0"
__all__ = [
    "TOKEN_LIMITS",
    "API_CONFIG",
    "DEFAULT_THEME_RULES",
    "BrowserSession",
    "AuthClient",
    "ChatClient",
    "ExchangeBuilder",
    "ContentCleaner",
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
from contexto_zai.processing.content_cleaner import ContentCleaner
from contexto_zai.processing.exchange_builder import ExchangeBuilder
from contexto_zai.verification.verifier import Verifier
