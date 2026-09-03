"""Contexto Z.ai — Sistema de recuperación de contexto para agentes.

Recupera, clasifica y genera archivos de contexto que permiten
a los agentes Z.ai recuperar coherencia operativa tras una
compresión de contexto por la plataforma.

Uso rápido::

    from contexto_zai.pipeline import Pipeline

    pipeline = Pipeline(verbose=True)
    result = pipeline.run(share_id="uuid-del-share")

O vía CLI::

    python -m contexto_zai run --share-id uuid-del-share -o ./contexto_recuperacion
"""

__version__ = "1.0.0"
__all__ = [
    "Pipeline",
    "AuthClient",
    "ChatClient",
    "ExchangeBuilder",
    "MessageClassifier",
    "ContentCleaner",
    "BlockManager",
    "RecoveryGenerator",
    "Verifier",
]

from contexto_zai.client.auth_client import AuthClient
from contexto_zai.client.chat_client import ChatClient
from contexto_zai.generation.recovery_generator import RecoveryGenerator
from contexto_zai.pipeline import Pipeline
from contexto_zai.processing.block_manager import BlockManager
from contexto_zai.processing.classifier import MessageClassifier
from contexto_zai.processing.content_cleaner import ContentCleaner
from contexto_zai.verification.verifier import Verifier
