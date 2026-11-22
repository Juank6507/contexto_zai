"""contexto_zai/platforms/zai/__init__.py -- Subpaquete Zai (v7.0 F2).

Implementaciones concretas de las 4 ABCs de ``platforms.interfaces`` para
la plataforma Z.ai. Cada clase envuelve el cliente correspondiente en
``contexto_zai.client`` (no lo reemplaza): la abstraccion vive arriba y
la implementacion abajo.

Modulos:
- ``zai_config`` — constantes Zai concretas (URL del proxy LLM, timeout,
  modelos heavy/light). Re-exporta ``APIConfig`` de ``client.zai_config``.
- ``zai_auth`` — ``ZaiAuth(PlatformAuth)`` envolviendo ``AuthClient`` +
  ``CredentialManager``.
- ``zai_chat`` — ``ZaiChat(PlatformChat)`` envolviendo ``ChatClient``.
- ``zai_links`` — ``ZaiLinks(PlatformLinks)`` envolviendo ``AttachmentClient``.
- ``zai_llm`` — ``ZaiLLM(PlatformLLM)`` envolviendo la llamada HTTP al
  proxy APA interno del sandbox Next.js.
"""
