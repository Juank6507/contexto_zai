# Plan v3.5 — Implementación de indexación de documentos adjuntos mediante subagentes

**Versión:** 3.5
**Fecha:** 2026-09-05
**Autor:** Agente CZAI
**Estado:** Pendiente de validación por el Director.
**Spec objetivo:** v3.5 (entregada en `/home/z/my-project/download/spec_recuperacion_contexto_v3.5.md`).

---

## Principios de implementación

1. **OOP estricto:** clases con responsabilidad única, interfaces claras, type hints, docstrings.
2. **Reutilización antes que duplicación:** si una clase existente hace algo similar, se refactoriza para compartir interfaz, no se crea nueva.
3. **Scripts atómicos standalone:** autocontenidos con bloque `if __name__ == "__main__"` con auto-tests.
4. **Cambios quirúrgicos:** sobre el código existente del repo, solo se modifica lo que cambia.
5. **Compatibilidad Windows:** auto-ejecutables sin configuración previa (stub `sys.path` ya corregido en v3.4).

---

## Archivos nuevos

| Archivo | Responsabilidad |
|---|---|
| `client/attachment_client.py` | Cliente de descarga de attachments desde la API de Z.ai. |
| `processing/attachment_detector.py` | Detector de attachments en mensajes extraídos. |
| `processing/content_delegator.py` | Clase base `ContentDelegator` + `DocumentDelegator`. |
| `subagents/documento_indexer_subagent.py` | Subagente que lee, clasifica y resume documentos. |

## Archivos a modificar

| Archivo | Cambio |
|---|---|
| `models.py` | Añadir modelo `Attachment`. |
| `config.py` | Añadir constantes de delegación (`DELEGATION_THRESHOLD_TOKENS`, `DELEGATION_CONTEXT_LIMIT_PCT`, `TRIVIAL_SIZE_TOKENS`, `DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS`). |
| `chat_client.py` | Nuevo método `extract_attachments()` para extraer attachments crudos del batch. |
| `exchange_builder.py` | Refactor `_process_external_links()` para usar `DocumentDelegator`. Quitar truncado 10K. |
| `subdivider.py` | Refactor `needs_subdivision()` para implementar interfaz `ContentDelegator`. |
| `subagents/__init__.py` | Exportar `DocumentoIndexerSubagent`. |
| `pipeline.py` | Añadir `index_document()`. |
| `recovery_cycle.py` | Integrar `AttachmentDetector` + `DocumentoIndexerSubagent`. |
| `generation/indice_generator.py` | Incluir sección "Documentos indexados". |
| `tests/run_all_tests.py` | Añadir 4 nuevos módulos atómicos a la Fase 1. |
| `tests/test_e2e_pipeline.py` | Añadir tests E2E para attachments. |

---

## Fases de ejecución (milestones)

### Milestone G1 — Modelo `Attachment` y constantes de configuración

**Modificar `models.py`:**
- Añadir clase `Attachment` (Pydantic BaseModel) con campos:
  - `file_id: str`
  - `filename: str`
  - `content_type: str`
  - `size: int` (bytes)
  - `url: str` (endpoint `/api/v1/files/{id}/content`)
  - `cdn_url: str` (URL del CDN, opcional)
  - `ref_msg_id: str` (ID del mensaje del Director que adjuntó el archivo)
  - `media: str` (tipo: "doc", "file", "image")
  - `status: str` (estado: "uploaded", "indexed", "error")
  - `created_at: float` (timestamp)
- Propiedades calculadas:
  - `estimated_tokens` (size / 3.5 aproximado, o None si no es texto)
  - `is_pdf`, `is_docx`, `is_text`, `is_image` (basado en content_type)
  - `is_trivially_small` (tokens < `TRIVIAL_SIZE_TOKENS`)

**Modificar `config.py`:**
- `DELEGATION_THRESHOLD_TOKENS = 5000` (documentos >5K tokens se delegan)
- `DELEGATION_CONTEXT_LIMIT_PCT = 80` (si agente >80% ocupado, delega)
- `TRIVIAL_SIZE_TOKENS = 1000` (documentos <1K tokens se incorporan directo)
- `DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS = 500` (resumen breve que devuelve el subagente)
- `ATTACHMENTS_TEMP_DIR = WORKSPACE_ROOT / "download" / "uploads" / "temp"`
- `ATTACHMENTS_INDEXED_DIR = WORKSPACE_ROOT / "download" / "uploads" / "indexed"`

**Tests auto:** validar modelo `Attachment`, propiedades calculadas, constantes cargadas.

### Milestone G2 — `AttachmentClient` (descarga de archivos)

**Crear `client/attachment_client.py`:**
- Clase `AttachmentClient`:
  - `__init__(token: str, timeout: float = 60.0)`: cliente httpx con cookie JWT.
  - `download(attachment: Attachment) -> bytes`: descarga el contenido binario desde `/api/v1/files/{id}/content`.
  - `download_to_file(attachment: Attachment, dest_path: Path) -> Path`: descarga y guarda en disco.
  - `download_many(attachments: list[Attachment]) -> dict[str, bytes]`: descarga en lote.
- Manejo de errores: `AttachmentDownloadError` (404, 401, timeout, tamaño >límite).
- Detección de tipo por magic number (no confiar solo en content_type del server).

**Tests auto:**
- Mock de httpx para simular descarga exitosa.
- Casos edge: file_id inválido (404), token expirado (401), timeout, archivo corrupto.
- Detección de magic number: PDF (`%PDF`), DOCX (ZIP con `word/`), texto plano.
- `download_to_file` escribe en disco correctamente.

### Milestone G3 — `AttachmentDetector` (detección en mensajes)

**Crear `processing/attachment_detector.py`:**
- Clase `AttachmentDetector`:
  - `detect_in_raw_messages(raw_messages: dict) -> list[Attachment]`: recorre el JSON crudo del batch endpoint y extrae attachments del campo `files`.
  - `detect_in_messages(messages: list[Message]) -> dict[int, list[Attachment]]`: mapea cada mensaje procesado a sus attachments (por `ref_user_msg_id`).
  - `filter_by_type(attachments, media_type: str) -> list[Attachment]`: filtra por tipo (doc, file, image).
  - `deduplicate(attachments) -> list[Attachment]`: elimina duplicados por `file_id`.
- Mapeo `file.raw` → `Attachment` (Pydantic).

**Tests auto:**
- Mensaje sin attachments → lista vacía.
- Mensaje con 1 attachment → detecta correctamente.
- Mensaje con múltiples attachments → detecta todos.
- Deduplicación por `file_id`.
- Filtrado por tipo (`media` field).

### Milestone G4 — `ContentDelegator` (clase base + `DocumentDelegator`)

**Crear `processing/content_delegator.py`:**
- Clase abstracta `ContentDelegator`:
  - `should_delegate(content_size_tokens: int, agent_context_available_pct: float, director_override: Optional[str] = None) -> bool`
  - Método `_parse_override(director_override: str) -> Optional[bool]` que interpreta frases del Director ("lee completo", "no leas", etc.).
- Clase concreta `DocumentDelegator(ContentDelegator)`:
  - Usa constantes de `config.py` (`DELEGATION_THRESHOLD_TOKENS`, etc.).
  - Devuelve `True` (delegar) si: tamaño > umbral Y no hay override.
  - Devuelve `False` (leer directo) si: override del Director dice "lee completo" O tamaño < trivial.
  - Devuelve `False` si: contexto del agente > 80% Y no override.

**Refactorizar `subdivider.py`:**
- `Subdivider.needs_subdivision()` refactorizado para implementar `ContentDelegator` (sin romper API existente).
- Añadir método `should_delegate()` que llama a `needs_subdivision()` internamente.

**Tests auto:**
- Delegación automática: documento grande → True, pequeño → False.
- Override del Director: "lee completo" → False siempre.
- Override del Director: "no leas" → True siempre (pero marca como ignorado).
- Contexto del agente: 90% ocupado → True aunque el documento sea pequeño.
- `Subdivider` refactorizado sigue pasando sus tests existentes.

### Milestone G5 — `DocumentoIndexerSubagent` (subagente efímero)

**Crear `subagents/documento_indexer_subagent.py`:**
- Dataclass `DocumentoIndexResult`:
  - `attachment_id: str`
  - `filename: str`
  - `resumen_breve: str` (≤500 chars)
  - `temas_detectados: list[ThemeSection]`
  - `archivo_indexado_path: Path` (dónde quedó guardado para futuras consultas)
  - `success: bool`
  - `error: str = ""`
- Dataclass `ThemeSection`:
  - `tema: str`
  - `descripcion: str`
  - `secciones: list[str]` (referencias a secciones del documento)
- Clase `DocumentoIndexerSubagent`:
  - `__init__(launcher: SubagentLauncher, attachment_client: AttachmentClient, max_resumen_chars: int = 500)`.
  - `run(attachment: Attachment) -> DocumentoIndexResult`:
    1. Descarga el archivo con `AttachmentClient`.
    2. Lo guarda en `ATTACHMENTS_TEMP_DIR`.
    3. Construye prompt para el subagente: "Lee este archivo en {ruta}, clasifica por temas, genera un resumen de {max_resumen_chars} chars".
    4. Lanza subagente con `SubagentLauncher.launch()`.
    5. Parsea respuesta del subagente (formato estructurado similar a `DiscriminatorSubagent`).
    6. Mueve archivo de `temp/` a `indexed/`.
    7. Devuelve `DocumentoIndexResult`.

**Tests auto:**
- Mock invoker que devuelve clasificación estructurada → parsea correctamente.
- Casos edge: archivo no descargable, subagente que falla, respuesta mal formada.
- Validación: resumen ≤ max_chars, todos los temas tienen descripción.
- Archivo movido correctamente de `temp/` a `indexed/`.

### Milestone G6 — Refactor de `exchange_builder.py` (links externos + attachments unificados)

**Modificar `exchange_builder.py`:**
- Refactor `_process_external_links()` → `_process_external_content()` que maneja tanto URLs como attachments.
- Para cada URL o attachment detectado:
  1. Estimar tokens del contenido.
  2. Llamar `DocumentDelegator.should_delegate()`.
  3. Si delega: lanzar `DocumentoIndexerSubagent` (para attachments) o `WebReader+Subagente` (para URLs).
  4. Si no delega: leer directamente con `WebReader` (URLs) o `AttachmentClient` (attachments).
- **Quitar el truncado a 10K chars** (`content.content[:10000]`). El `Subdivider` se encarga de partir contenido grande.

**Tests auto:**
- URL pequeña → leída directamente (sin subagente).
- URL grande → delegada al subagente.
- Attachment pequeño → leído directamente.
- Attachment grande → delegado al subagente.
- Override del Director "lee completo" → siempre lee directo.
- Sin truncado a 10K (contenido completo en el intercambio).

### Milestone G7 — Integración en `recovery_cycle.py`

**Modificar `recovery_cycle.py`:**
- En `run()`, después de `extract_all()`:
  1. Extraer attachments crudos del batch endpoint con `ChatClient.extract_attachments()`.
  2. Detectar attachments con `AttachmentDetector`.
  3. Para cada attachment, decidir delegación con `DocumentDelegator`.
  4. Lanzar `DocumentoIndexerSubagent` para los delegados.
  5. Crear intercambios virtuales con los resúmenes (no con el contenido completo).
- Añadir campo `attachments_indexados: list[DocumentoIndexResult]` a `RecoveryCycleResult`.

**Modificar `chat_client.py`:**
- Nuevo método `extract_attachments(chat_id, message_ids) -> list[Attachment]`:
  - Llama al batch endpoint.
  - Recorre el JSON crudo buscando campo `files`.
  - Construye objetos `Attachment`.

**Tests auto:**
- RecoveryCycle con attachments → se indexan correctamente.
- `attachments_indexados` en `RecoveryCycleResult` se llena.
- El agente principal no consume tokens del PDF en su contexto.

### Milestone G8 — `IndiceGenerator` con sección de documentos indexados

**Modificar `generation/indice_generator.py`:**
- `generate()` acepta parámetro nuevo `attachments_indexados: list[DocumentoIndexResult]`.
- Añade sección "## Documentos indexados" al `01_indice_recuperacion.md`:
  - Tabla: `| Documento | Temas | Resumen | Ruta |`
  - Cada documento indexado se lista con sus temas y la ruta donde está guardado.

**Tests auto:**
- Índice generado con 0 documentos → sección omitida.
- Índice generado con 3 documentos → tabla con 3 filas.
- Formato markdown correcto.

### Milestone G9 — `pipeline.py` con `index_document()`

**Modificar `pipeline.py`:**
- Añadir función `index_document(chat_id, file_id, jwt, force_direct: bool = False) -> DocumentoIndexResult`:
  - Construye un `Attachment` a partir de `file_id` (consulta metadata con `AttachmentClient`).
  - Llama a `DocumentoIndexerSubagent.run()`.
  - Devuelve el resultado.
- Usable en tiempo real (sin necesidad de activar la recuperación completa).

**Tests auto:**
- `index_document` disponible y con firma correcta.
- `force_direct=True` omite la delegación.

### Milestone G10 — Tests E2E

**Modificar `tests/test_e2e_pipeline.py`:**
- `test_e2e_v35_attachment_detection`: simula batch endpoint con attachments, verifica que `AttachmentDetector` los encuentra.
- `test_e2e_v35_attachment_delegation_large`: documento >5K tokens → se delega al subagente.
- `test_e2e_v35_attachment_direct_small`: documento <1K tokens → se lee directamente.
- `test_e2e_v35_attachment_override`: "lee completo" → se lee directamente sin subagente.
- `test_e2e_v35_indice_with_documents`: índice generado incluye sección de documentos indexados.
- `test_e2e_v35_pipeline_real_pdf`: usa el PDF real `CZAI-01.pdf` del chat de prueba para validar el flujo completo.

**Tests de integración:**
- `tests/test_attachment_flow.py` (nuevo): test aislado del flujo completo de un attachment desde detección hasta indexación.

### Milestone G11 — Actualizar `run_all_tests.py` y documentación

**Modificar `tests/run_all_tests.py`:**
- Añadir 4 nuevos módulos atómicos a la Fase 1:
  - `client/attachment_client.py`
  - `processing/attachment_detector.py`
  - `processing/content_delegator.py`
  - `subagents/documento_indexer_subagent.py`

**Documentación:**
- Actualizar `estrategia/worklog_template.md` con el Paso 2c: "Indexación de documentos adjuntos".
- Actualizar `download/LEEME_INSTALACION.md` con las nuevas funciones.

### Milestone G12 — Refactor de `Subdivider` para implementar `ContentDelegator`

**Modificar `processing/subdivider.py`:**
- `Subdivider` hereda de `ContentDelegator`.
- `needs_subdivision()` se mantiene (compatibilidad hacia atrás) pero internamente llama a `should_delegate()`.
- Nuevo método `should_delegate()` que implementa la interfaz común.

**Tests auto:**
- `Subdivider.should_delegate()` funciona igual que `needs_subdivision()` para los casos existentes.
- Tests existentes siguen pasando sin cambios.

---

## Orden de ejecución

```
G1 (models + config)
    ↓
G2 (AttachmentClient)  ←── G3 (AttachmentDetector)  [paralelizables]
    ↓                          ↓
G4 (ContentDelegator) ────────┘
    ↓
G5 (DocumentoIndexerSubagent)
    ↓
G6 (refactor exchange_builder)
    ↓
G7 (recovery_cycle + chat_client)
    ↓
G8 (IndiceGenerator)
    ↓
G9 (pipeline.index_document)
    ↓
G10 (tests E2E)
    ↓
G11 (run_all_tests + docs)
    ↓
G12 (refactor Subdivider, último para no romper nada)
```

---

## Cobertura de los cambios de la spec v3.5

| Cambio spec v3.5 | Milestone |
|---|---|
| Modelo `Attachment` | G1 |
| Constantes de delegación en `config.py` | G1 |
| `AttachmentClient` (descarga) | G2 |
| `AttachmentDetector` (detección) | G3 |
| `ContentDelegator` + `DocumentDelegator` | G4 |
| `DocumentoIndexerSubagent` (subagente) | G5 |
| Refactor `exchange_builder` (links + attachments unificados) | G6 |
| Integración en `recovery_cycle` + `chat_client` | G7 |
| `IndiceGenerator` con documentos indexados | G8 |
| `pipeline.index_document()` | G9 |
| Tests E2E | G10 |
| `run_all_tests` + docs | G11 |
| Refactor `Subdivider` para implementar `ContentDelegator` | G12 |

**Cobertura total:** 12/12 cambios cubiertos.

---

## Pendiente de validación

Espero tu validación para pasar a la fase de EJECUCIÓN del plan v3.5.
