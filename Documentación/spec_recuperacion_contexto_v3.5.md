# Spec v3.5 — Indexación de documentos adjuntos mediante subagentes efímeros

**Versión:** 3.5
**Fecha:** 2026-09-05
**Autor:** Agente CZAI
**Estado:** Pendiente de validación por el Director.
**Especifica continuación de:** spec v3.4 (links externos, clasificación por capas, truncamiento lógico, export/import).

---

## 1. Problema

El Director necesita poder **entregar documentos pesados** (PDFs, DOCX, TXT, etc.) al agente para que este los incorpore al contexto del proyecto. El mecanismo de entrega debe ser el **botón "+" del chat de Z.ai** (adjuntar archivo nativo, no rutas ni links externos).

El problema crítico: **si el agente principal lee el documento directamente, su contexto se llena y se acaba su capacidad de trabajo.** Hoy el proceso hace exactamente esto con los links externos (`WebReader` lee el contenido en el contexto del agente y trunca a 10K chars).

## 2. Solución

Cuando el proceso detecta que un mensaje del Director tiene archivos adjuntos:

1. **No los lee directamente.** El agente principal nunca consume su contexto con el contenido del documento.
2. **Lanza un subagente efímero** para que haga el trabajo pesado: leer, clasificar, resumir.
3. **El subagente devuelve al agente principal** solo un resumen breve + la referencia al índice donde está disponible el detalle.
4. **El índice de materias** (`01_indice_recuperacion.md`) se actualiza con el nuevo documento y sus temas.

### 2.1. Decisión de delegación (regla de 3 niveles)

Por defecto, **el proceso decide automáticamente** si delegar la lectura al subagente. El criterio es:

- **Delegar al subagente** (default): siempre que el documento tenga >5K tokens estimados o el agente principal tenga >80% de su contexto ocupado.
- **Leer directamente** (override del Director): si el Director dice explícitamente "lee este documento completo", el agente lo lee directamente sin subagente.
- **No delegar, no leer**: si el documento es trivialmente pequeño (<1K tokens) y el agente tiene contexto disponible, se incorpora al intercambio directamente.

### 2.2. Cuándo se procesa

**En el momento.** El proceso de contexto está activo desde el inicio de la sesión del agente. En cuanto llega un documento adjunto, el proceso lo detecta y lanza el subagente. No se espera a la activación de la recuperación de contexto completa.

### 2.3. Formatos soportados

**Cualquiera que el subagente de Z.ai pueda leer.** No se imponen límites desde el código. Los formatos típicos que el subagente de Z.ai maneja nativamente: PDF, DOCX, TXT, MD, imágenes, XLSX, PPTX.

## 3. Hallazgos de la investigación de la API

Se investigó a fondo la API de Z.ai para entender cómo expone los attachments. Los hallazgos:

### 3.1. Estructura del campo `files` en `messages/batch`

Cada mensaje del batch endpoint incluye un campo `files` (array de objetos) con la estructura:

```json
{
  "files": [
    {
      "type": "doc",  // o "file", "image"
      "file": {
        "id": "096b178e-a6be-4239-a571-7c15d9229c5f",
        "user_id": "229a58c8-...",
        "filename": "CZAI-01.pdf",
        "meta": {
          "name": "CZAI-01.pdf",
          "content_type": "application/pdf",
          "size": 1652025,
          "cdn_url": "https://z-cdn-media.chatglm.cn/files/...pdf?auth_key=..."
        },
        "created_at": 1788445359
      },
      "id": "096b178e-a6be-4239-a571-7c15d9229c5f",
      "url": "/api/v1/files/096b178e-...",
      "name": "CZAI-01.pdf",
      "status": "uploaded",
      "size": 1652025,
      "media": "doc",  // o "file", "image"
      "ref_user_msg_id": "30354b73-..."
    }
  ]
}
```

### 3.2. Endpoint de descarga de contenido

El endpoint correcto para descargar el contenido del archivo es:

```
GET /api/v1/files/{file_id}/content
```

Requiere autenticación (cookie `token` con JWT del Director). Devuelve el archivo binario directamente con `Content-Type` correcto y header `Content-Disposition: inline; filename*=UTF-8''<nombre>`.

**Verificado:** descarga con `httpx.get(url, cookies={'token': jwt})` funciona correctamente. Un PDF de 1.6 MB y 208 páginas se descarga y lee con `pdfplumber` sin problemas.

### 3.3. Endpoints que NO funcionan

- `/api/v1/files/{id}` devuelve solo metadata (JSON), no el contenido.
- `/api/v1/files/{id}/download`, `/raw`, `/blob` devuelven 404.
- Descarga directa del CDN (`z-cdn-media.chatglm.cn`) falla con 403 desde fuera del navegador (el `auth_key` expira rápido y requiere contexto del navegador).

## 4. Arquitectura OOP reutilizable

### 4.1. Patrón `ContentDelegator` (clase base abstracta)

Define la interfaz para decidir si un contenido debe procesarse en el contexto principal o delegarse a un subagente.

```python
class ContentDelegator(ABC):
    """Decide si un contenido debe delegarse a un subagente."""

    @abstractmethod
    def should_delegate(
        self,
        content_size_tokens: int,
        agent_context_available_pct: float,
        director_override: Optional[str] = None,
    ) -> bool:
        """Devuelve True si el contenido debe delegarse a un subagente."""
        ...
```

### 4.2. Subclases concretas

- `ThemeDelegator` — ya existe como `Subdivider.needs_subdivision`. Se refactoriza para implementar la interfaz `ContentDelegator`.
- `DocumentDelegator` — nueva. Decide si un documento adjunto debe delegarse.

### 4.3. Patrón de subagente (clase base implícita)

Los subagentes existentes siguen el mismo patrón:
- Reciben un contenido (archivo, tema, intercambio).
- Lo leen con su contexto independiente.
- Devuelven al agente principal un resumen o índice, no el contenido completo.

Subagentes existentes que ya implementan este patrón:
- `EstadoSubagent` — lee el archivo del tema activo, devuelve contexto extraído.
- `BarridoSubagent` — busca información puntual en un archivo, devuelve la respuesta.
- `DiscriminatorSubagent` (v3.4 F5) — lee un tema grande, propone subdivisión.

**Nuevo subagente: `DocumentoIndexerSubagent`** — lee un documento completo, lo clasifica por temas, genera un resumen breve y actualiza el índice de materias.

### 4.4. Diagrama de clases

```
ContentDelegator (abstract)
├── ThemeDelegator (= Subdivider.needs_subdivision, refactorizado)
└── DocumentDelegator (nuevo, decide si documento → agente o subagente)

SubagentLauncher (ya existe, genérico)
└── lanza:
    ├── EstadoSubagent (ya existe)
    ├── BarridoSubagent (ya existe)
    ├── DiscriminatorSubagent (ya existe v3.4 F5)
    └── DocumentoIndexerSubagent (nuevo)

AttachmentClient (nuevo, descarga archivos adjuntos desde la API de Z.ai)
├── list_attachments(messages) -> list[Attachment]
└── download(attachment) -> bytes

AttachmentDetector (nuevo, detecta attachments en mensajes extraídos)
├── detect_in_messages(messages) -> list[Attachment]
└── get_messages_with_attachments(messages) -> dict[msg_id, list[Attachment]]
```

## 5. Flujo completo del proceso

### Paso 1: Extracción de mensajes (sin cambios)

`ChatClient.extract_all()` extrae los mensajes del chat como hasta ahora. Los mensajes devueltos incluyen el campo `files` en el JSON crudo, pero `ChatClient._extract_content()` no lo procesa (solo extrae texto).

### Paso 2: Detección de attachments (NUEVO)

`AttachmentDetector.detect_in_messages(messages)` recorre los mensajes y devuelve la lista de attachments con su metadata (file_id, filename, content_type, size, ref_user_msg_id).

### Paso 3: Para cada attachment detectado, decidir delegación (NUEVO)

`DocumentDelegator.should_delegate(content_size, context_available, override)` decide:

- Si el Director dijo "lee completo" → `False` (agente principal lee).
- Si el documento es trivial (<1K tokens) y hay contexto → `False`.
- Si no → `True` (delegar a subagente).

### Paso 4a: Si delega (default), lanzar subagente (NUEVO)

`DocumentoIndexerSubagent.run(attachment)`:

1. Descarga el archivo con `AttachmentClient.download(attachment)`.
2. Lo guarda temporalmente en `download/uploads/temp/`.
3. Lanza el subagente efímero con el prompt: "Lee este archivo, clasifica por temas, genera resumen".
4. El subagente lee el archivo (con `Read` de Z.ai o `pdfplumber` si es PDF).
5. El subagente devuelve:
   - `resumen_breve` (≤500 chars).
   - `temas_detectados` (lista de `{tema, descripcion, secciones}`).
   - `archivo_indexado_path` (dónde quedó guardado el archivo para consultas futuras).
6. El proceso mueve el archivo de `temp/` a `download/uploads/indexed/`.
7. El proceso actualiza el `01_indice_recuperacion.md` con la nueva materia.

### Paso 4b: Si no delega, el agente principal lee (excepcional)

El proceso descarga el archivo con `AttachmentClient.download(attachment)`, lo lee directamente (con `pdfplumber` o el extractor adecuado), y crea un intercambio virtual con el contenido completo (sin truncar).

### Paso 5: Integración al contexto

El intercambio virtual (sea del subagente o directo) se clasifica con tema `documento_adjunto` y entra al pipeline normal: `BlockPacker` lo empaqueta, `EstadoGenerator` lo referencia en el estado actual, `IndiceGenerator` lo mapea en el índice.

## 6. Refactorización pendiente (fix de deuda técnica)

### 6.1. Fix del `WebReader` actual (links externos)

Hoy `ExchangeBuilder._process_external_links()` llama a `WebReader.read()` directamente en el contexto del agente principal y trunca a 10K chars. **Eso viola el consenso.**

**Fix:** refactorizar para que `_process_external_links()` use el mismo patrón:
1. Detectar URLs.
2. Decidir delegación con `DocumentDelegator.should_delegate()` (mismo criterio que attachments).
3. Si delega: lanzar `DocumentoIndexerSubagent` con la URL en vez de file_id.
4. Si no delega (default para links pequeños): leer con `WebReader` directamente.

Esto unifica los dos mecanismos (links externos + archivos adjuntos) bajo el mismo patrón OOP.

### 6.2. Quitar truncado a 10K chars

El `content.content[:10000]` en `exchange_builder.py:195` se elimina. El `Subdivider` y `DiscriminatorSubagent` se encargan de partir contenido grande en subtemas automáticamente.

## 7. Archivos nuevos

| Archivo | Responsabilidad |
|---|---|
| `client/attachment_client.py` | Descarga archivos adjuntos desde la API de Z.ai (`/api/v1/files/{id}/content`). |
| `processing/attachment_detector.py` | Detecta attachments en mensajes extraídos. |
| `processing/content_delegator.py` | Clase base abstracta + `DocumentDelegator` concreto. |
| `subagents/documento_indexer_subagent.py` | Subagente que lee, clasifica y resume documentos. |

## 8. Archivos a modificar

| Archivo | Cambio |
|---|---|
| `models.py` | Añadir modelo `Attachment` (file_id, filename, content_type, size, url, ref_msg_id). |
| `config.py` | Añadir `DELEGATION_THRESHOLD_TOKENS=5000`, `DELEGATION_CONTEXT_LIMIT_PCT=80`, `TRIVIAL_SIZE_TOKENS=1000`, `DOCUMENTO_INDEXER_RESUMEN_MAX_CHARS=500`. |
| `chat_client.py` | `extract_all()` debe devolver también los attachments detectados. Nuevo método `extract_attachments(messages_raw)`. |
| `exchange_builder.py` | Refactor `_process_external_links()`: usar `DocumentDelegator` + `DocumentoIndexerSubagent` en vez de leer directamente. Quitar truncado 10K. |
| `subdivider.py` | `needs_subdivision()` refactorizado para implementar interfaz `ContentDelegator` (sin romper API existente). |
| `subagents/__init__.py` | Exportar `DocumentoIndexerSubagent`. |
| `pipeline.py` | Añadir `index_document(attachment)` para procesar un documento en tiempo real. |
| `recovery_cycle.py` | Integrar `AttachmentDetector` después de extracción. Lanzar `DocumentoIndexerSubagent` para cada attachment. |
| `generation/indice_generator.py` | Incluir sección "Documentos indexados" en el índice de materias. |
| `tests/run_all_tests.py` | Añadir 4 nuevos módulos atómicos a la Fase 1. |
| `tests/test_e2e_pipeline.py` | Añadir tests E2E para attachments. |

## 9. Compatibilidad con versiones anteriores

- El flujo existente (sin attachments) sigue funcionando igual.
- Los links externos pequeños (<5K tokens) se leen directamente con `WebReader` como antes.
- Los links externos grandes se delegan al subagente (nuevo comportamiento, mejora la v3.4).
- La exportación/importación de contexto (v3.4 F10/F11) incluye los documentos indexados en el ZIP.

## 10. Validación

### 10.1. Auto-tests atómicos (Fase 1, 4 nuevos módulos)

- `client/attachment_client.py`: descarga con mock, manejo de errores, casos edge.
- `processing/attachment_detector.py`: detección en mensajes, filtrado, deduplicación.
- `processing/content_delegator.py`: criterios de delegación, override del Director.
- `subagents/documento_indexer_subagent.py`: leer+clasificar+resumir con mock invoker.

### 10.2. Tests E2E

- Adjuntar PDF real en un chat de prueba y verificar que se indexa.
- Verificar que el agente principal no consume tokens del PDF en su contexto.
- Verificar que el índice de materias se actualiza con el documento.
- Verificar que el override del Director ("lee completo") funciona.

## 11. Pendiente de validación

Espero tu validación para pasar a la fase de EJECUCIÓN del plan v3.5.
