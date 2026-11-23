"""contexto_zai/platforms/__init__.py -- Paquete de abstraccion de plataforma (v7.0 F2).

Marca el paquete ``platforms`` que contiene la capa de abstraccion de
plataforma introducida en v7.0 F2 para restaurar la separacion de capas
v5.0 con implementaciones concretas de Zai.

Contenido:
- ``interfaces`` — 4 ABCs (``PlatformAuth``, ``PlatformChat``,
  ``PlatformLinks``, ``PlatformLLM``) que definen el contrato de cualquier
  plataforma de chat/LLM.
- ``zai/`` — subpaquete con las implementaciones concretas para Z.ai
  (envuelven los clientes existentes en ``contexto_zai.client``).

Para cambiar de plataforma, basta con crear un nuevo subpaquete (por
ejemplo ``platforms/otra/``) con clases que implementen las 4 ABCs. Los
modulos generales (pipeline, processing, etc.) no se tocan: reciben la
implementacion por inyeccion de constructor con default Zai.
"""
