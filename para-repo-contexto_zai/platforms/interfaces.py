"""contexto_zai/platforms/interfaces.py -- Interfaces abstractas de plataforma (v7.0 F2).

Define 4 ABCs (Abstract Base Classes) que conforman el contrato de
cualquier plataforma de chat + LLM:

- ``PlatformAuth`` -- autenticacion y creacion de shares.
- ``PlatformChat`` -- extraccion de mensajes (arbol, batch, todos).
- ``PlatformLinks`` -- gestion de attachments/links.
- ``PlatformLLM`` -- acceso al LLM (proxy, modelos heavy/light).

Las implementaciones concretas viven en ``platforms.<vendor>`` (por
ejemplo ``platforms.zai``). Los modulos generales (pipeline, processing,
etc.) operan contra estas ABCs y desconocen el vendor concreto. La
inyeccion es por constructor: si un llamador no inyecta nada, se usa la
implementacion Zai por defecto.

Notas de diseno:

- ``PlatformAuth.create_share`` se anade como 4o metodo abstracto
  (ademas de los 3 del spec) porque ``MessageExtractor._ensure_share()``
  lo invoca. Es una operacion generica (muchas plataformas tienen
  conceptos de "share link").

- ``PlatformChat`` expone los 3 metodos del spec
  (``get_message_tree``, ``get_messages_batch``, ``get_all_messages``)
  mas ``extract_all`` (wrapper de ``ChatClient.extract_all``) y
  ``extract_content`` (wrapper del ``_extract_content`` estatico).
  Estos 2 metodos extra los consume ``MessageExtractor`` para no romper
  el comportamiento actual.

- ``PlatformLLM.call`` acepta un ``timeout`` opcional (extiende el spec)
  para que los llamadores puedan alargar el timeout de la llamada HTTP
  (por ejemplo, ``PROXY_LLM_TIMEOUT * 6`` para enriquecer bloques
  largos). El default es el timeout del proxy (``ZAI_PROXY_LLM_TIMEOUT``).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class PlatformAuth(ABC):
    """Interfaz abstracta para autenticacion en una plataforma de chat.

    Define el contrato para:
    - Leer el JWT/email persistido.
    - Verificar si el usuario esta autenticado.
    - Crear shares (links publicos) de un chat.

    Las implementaciones concretas (por ejemplo ``ZaiAuth``) envuelven
    los clientes HTTP correspondientes (``AuthClient``,
    ``CredentialManager``). No los reemplazan.
    """

    @abstractmethod
    def get_jwt(self) -> str:
        """Devuelve el JWT del Director (string vacio si no hay)."""
        ...

    @abstractmethod
    def get_email(self) -> str:
        """Devuelve el email del Director (string vacio si no hay)."""
        ...

    @abstractmethod
    def is_authenticated(self) -> bool:
        """True si el JWT existe y el email NO es de invitado (guest)."""
        ...

    @abstractmethod
    def create_share(self, chat_id: str) -> str:
        """Crea o reutiliza un share link del chat. Devuelve el share_id.

        Es idempotente: si el chat ya tiene un share, devuelve el
        existente. La implementacion Zai delega en ``AuthClient.create_share``.
        """
        ...


class PlatformChat(ABC):
    """Interfaz abstracta para extraer mensajes de un chat.

    Define el contrato para:
    - Obtener el arbol de mensajes (solo metadata, sin contenido).
    - Extraer el contenido de un lote de mensajes (batch autenticado).
    - Extraer todos los mensajes con contenido en una llamada.
    - Extraer el contenido textual de un mensaje crudo.

    Las implementaciones concretas (por ejemplo ``ZaiChat``) envuelven
    ``ChatClient``. No lo reemplazan.
    """

    @abstractmethod
    def get_message_tree(
        self,
        chat_id: str,
        share_id: Optional[str] = None,
    ) -> dict:
        """Obtiene el arbol de mensajes de un chat compartido.

        Args:
            chat_id: UUID interno del chat (algunas plataformas lo
                exigen, otras lo descubren del arbol).
            share_id: UUID del share link. En plataformas que requieren
                share (Zai v3.2), es obligatorio.

        Returns:
            Diccionario con la estructura del chat. Clave relevante:
                - chat.id -> chat_id interno
                - chat.history.messages -> mapa {msg_id: metadata}
        """
        ...

    @abstractmethod
    def get_messages_batch(
        self,
        chat_id: str,
        message_ids: list,
        share_id: Optional[str] = None,
    ) -> dict:
        """Extrae el contenido completo de una lista de mensajes (batch).

        Args:
            chat_id: UUID interno del chat (autenticacion).
            message_ids: Lista de IDs de mensajes a extraer.
            share_id: UUID del share (algunas plataformas lo requieren,
                otras lo ignoran).

        Returns:
            Diccionario {data: {msg_id: {content, content_blocks, ...}}}.
        """
        ...

    @abstractmethod
    def get_all_messages(
        self,
        chat_id: str,
        from_timestamp: float = 0.0,
    ) -> list:
        """Extrae TODOS los mensajes del chat con contenido.

        Orquesta: get_message_tree -> ordenar IDs -> get_messages_batch
        -> parsear a objetos Message.

        Args:
            chat_id: UUID interno del chat.
            from_timestamp: Si > 0, filtra solo mensajes posteriores.

        Returns:
            Lista de objetos Message ordenados cronologicamente.
        """
        ...

    @abstractmethod
    def extract_all(
        self,
        share_id: str,
        chat_id: Optional[str] = None,
    ) -> list:
        """Extrae todos los mensajes de un chat compartido (wrapper).

        Orquesta: get_message_tree -> ordenar IDs -> get_messages_batch
        -> parsear a objetos Message. Es el wrapper historico de Zai
        (``ChatClient.extract_all``). Se mantiene por compatibilidad con
        ``MessageExtractor``.

        Args:
            share_id: UUID del share link.
            chat_id: UUID interno del chat. Si es None, se descubre del
                arbol de mensajes.

        Returns:
            Lista de objetos Message ordenados cronologicamente.
        """
        ...

    @abstractmethod
    def extract_content(self, msg_raw: dict) -> str:
        """Extrae el contenido textual de un mensaje crudo.

        Prioriza el campo 'content' string si no es vacio. Si es un
        dict o tiene 'content_blocks', los concatena (filtrando
        'reasoning').

        Args:
            msg_raw: Diccionario con el mensaje crudo del batch endpoint.

        Returns:
            String con el contenido textual del mensaje.
        """
        ...


class PlatformLinks(ABC):
    """Interfaz abstracta para gestionar attachments/links de una plataforma.

    Define el contrato para:
    - Descargar un attachment por file_id (devuelve ruta local).
    - Listar los attachments de un chat.

    Las implementaciones concretas (por ejemplo ``ZaiLinks``) envuelven
    ``AttachmentClient``. No lo reemplazan.
    """

    @abstractmethod
    def download_attachment(self, file_id: str, filename: str) -> str:
        """Descarga un attachment y lo guarda en disco. Devuelve la ruta.

        Args:
            file_id: UUID del archivo en la plataforma.
            filename: Nombre de archivo destino (sin ruta).

        Returns:
            Ruta local donde se guardo el attachment.
        """
        ...

    @abstractmethod
    def list_attachments(self, chat_id: str) -> list:
        """Lista los attachments de un chat.

        Args:
            chat_id: UUID interno del chat.

        Returns:
            Lista de dicts {file_id, filename, size, ...} con los
            attachments del chat.
        """
        ...


class PlatformLLM(ABC):
    """Interfaz abstracta para acceder al LLM via la cascada.

    Define el contrato para:
    - Llamar al LLM con un modelo (heavy/light) y parametros.
    - Verificar disponibilidad del proxy (ping).
    - Obtener los nombres de los modelos heavy/light por defecto.

    Las implementaciones concretas (por ejemplo ``ZaiLLM``) envuelven
    la llamada HTTP al proxy APA interno del sandbox Next.js.
    """

    @abstractmethod
    def call(
        self,
        messages: list,
        model: str = "",
        max_tokens: int = 3000,
        temperature: float = 0.3,
        timeout: Optional[int] = None,
    ) -> dict:
        """Llama al LLM con ``messages`` y devuelve la respuesta parseada.

        Args:
            messages: Lista de mensajes [{role, content}, ...].
            model: Nombre del modelo. Si es vacio, usa el heavy por
                defecto.
            max_tokens: Maximo de tokens a generar.
            temperature: Temperatura de muestreo.
            timeout: Timeout opcional en segundos. Si es None, usa el
                default del proxy (``ZAI_PROXY_LLM_TIMEOUT``).

        Returns:
            Dict con la respuesta del proxy (estructura OpenAI:
            ``{"choices": [{"message": {"content": "..."}}]}``).
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Hace un ping minimo al proxy. Devuelve True si responde 200."""
        ...

    @abstractmethod
    def get_default_model_heavy(self) -> str:
        """Devuelve el nombre del modelo heavy por defecto (calidad)."""
        ...

    @abstractmethod
    def get_default_model_light(self) -> str:
        """Devuelve el nombre del modelo light por defecto (rapido)."""
        ...
