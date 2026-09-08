# Plan v3.6 — Implementación: JWT automático + Subagentes paralelos para documentos grandes

**Versión:** 3.6
**Fecha:** 2026-09-06
**Autor:** Agente CZAI
**Estado:** Pendiente de validación por el Director.
**Spec objetivo:** v3.6 (entregada en `/home/z/my-project/download/spec_recuperacion_contexto_v3.6.md`).

---

## Principios de implementación

1. **OOP estricto:** clases con responsabilidad única, interfaces claras, type hints, docstrings.
2. **Reutilización antes que duplicación:** refactorizar `SubagentLauncher` para soportar paralelismo genérico.
3. **Scripts atómicos standalone:** autocontenibles con auto-tests en `__main__`.
4. **Cambios quirúrgicos:** solo se modifica lo que cambia.
5. **Compatibilidad Windows/Linux:** todos los paths usan `pathlib.Path`.

---

## Archivos nuevos

| Archivo | Responsabilidad |
|---|---|
| `scripts/czai-jwt-bridge.bat` | Script .bat que el Director ejecuta con doble click |
| `scripts/jwt_bridge.ps1` | Script PowerShell que el .bat invoca |
| `client/credential_manager.py` | Gestiona el JWT: pide si falta, valida, persiste |
| `client/jwt_bridge_server.py` | Mini HTTP server temporal (3 endpoints) |
| `processing/divisor.py` | Clase base `Divisor` + `DocumentoDivisor` |
| `processing/conciliador.py` | Clase base `Conciliador` + `DocumentoConciliador` |
| `subagents/divisor_subagent.py` | Subagente N1 (divide + lanza N2) |
| `subagents/conciliador_subagent.py` | Subagente N3 (consolida índices) |

## Archivos a modificar

| Archivo | Cambio |
|---|---|
| `models.py` | Añadir `Porcion`, `IndiceParcial`, `IndiceConsolidado` |
| `config.py` | Añadir constantes de particionado y límites paralelos |
| `subagents/launcher.py` | Añadir `launch_parallel()` con ThreadPoolExecutor |
| `subagents/documento_indexer_subagent.py` | Añadir `run_3_levels()` |
| `subagents/__init__.py` | Exportar nuevas clases |
| `pipeline.py` | Añadir `index_document_large()` |
| `recovery_cycle.py` | Elegir entre subagente único o 3 niveles según tamaño |
| `estrategia/worklog_template.md` | Actualizar Paso 2c |
| `tests/run_all_tests.py` | Añadir nuevos módulos atómicos |
| `tests/test_v36_e2e.py` | Tests E2E nuevos |

---

## Fases de ejecución (milestones)

### Milestone H1 — Modelos y constantes

**Modificar `models.py`:**
- Clase `Porcion` (Pydantic BaseModel):
  - `id: int` (índice de la porción, 1-based)
  - `contenido_path: Path` (ruta del archivo temporal con la porción)
  - `tokens_estimados: int`
  - `paginas: tuple[int, int]` (página inicio, página fin) — solo para PDFs
- Clase `IndiceParcial` (Pydantic BaseModel):
  - `porcion_id: int`
  - `temas: list[ThemeSection]`
  - `resumen_parcial: str`
- Clase `IndiceConsolidado` (Pydantic BaseModel):
  - `temas_consolidados: list[ThemeSection]`
  - `resumen_final: str`
  - `indices_parciales: list[IndiceParcial]`

**Modificar `config.py`:**
```python
PARTITION_THRESHOLD_TOKENS = 50000
MAX_TOKENS_POR_SUBAGENTE_N2 = 30000
MAX_SUBAGENTES_LECTURA_ARCHIVOS = 5
MAX_SUBAGENTES_BUSQUEDA_PUNTUAL = 8
MAX_SUBAGENTES_CLASIFICACION_PROFUNDA = 3
MAX_SUBAGENTES_N2_PARALELOS = 3
JWT_BRIDGE_SERVER_PORT = 8086
JWT_BRIDGE_SERVER_HOST = "0.0.0.0"
```

**Tests auto:** validar modelos, constantes cargadas.

---

### Milestone H2 — `SubagentLauncher.launch_parallel()` (genérico)

**Modificar `subagents/launcher.py`:**
- Añadir método `launch_parallel(requests: list[SubagentRequest], max_workers: int = 3) -> list[SubagentResponse]`.
- Usa `concurrent.futures.ThreadPoolExecutor` para invocar el Task en paralelo.
- Cada Task se ejecuta en un thread independiente.
- `max_workers` limita cuántos Tasks corren simultáneamente.
- Devuelve las respuestas en el mismo orden que las requests.

**Tests auto:**
- 3 requests en paralelo con mock invoker → 3 respuestas.
- 5 requests con max_workers=3 → se procesan en 2 lotes (3 + 2).
- Invoker que falla → error capturado en esa response, otras responses OK.
- Orden de respuestas preservado.

---

### Milestone H3 — `Divisor` (clase base + `DocumentoDivisor`)

**Crear `processing/divisor.py`:**

```python
class Divisor(ABC):
    @abstractmethod
    def particionar(self, contenido, max_tokens_por_porcion) -> list[Porcion]:
        ...

    def lanzar_subagentes(
        self,
        porciones: list[Porcion],
        launcher: SubagentLauncher,
        max_paralelos: int,
        prompt_builder: callable,
    ) -> list[SubagentResponse]:
        """Lanza un subagente por cada porción, en paralelo."""
        requests = [
            SubagentRequest(
                prompt=prompt_builder(p),
                files_to_read=[str(p.contenido_path)],
                description=f"Procesar porción {p.id}",
            )
            for p in porciones
        ]
        return launcher.launch_parallel(requests, max_workers=max_paralelos)

class DocumentoDivisor(Divisor):
    def particionar(self, documento_path: Path, max_tokens: int) -> list[Porcion]:
        """Particiona un PDF por páginas hasta alcanzar max_tokens por porción."""
        # Usa pdfplumber para contar páginas y estimar tokens
        # Agrupa páginas en porciones que no superen max_tokens
```

**Tests auto:**
- Particionar PDF de 200 páginas con max_tokens=30K → ~5-7 porciones.
- Particionar PDF de 1 página → 1 porción.
- Particionar archivo vacío → lista vacía.
- Particionar por tamaño exacto → sin desbordamiento.

---

### Milestone H4 — `Conciliador` (clase base + `DocumentoConciliador`)

**Crear `processing/conciliador.py`:**

```python
class Conciliador(ABC):
    @abstractmethod
    def conciliar(self, respuestas: list[SubagentResponse]) -> IndiceConsolidado:
        ...

    @abstractmethod
    def producir_resumen_final(self, consolidado: IndiceConsolidado) -> str:
        ...

class DocumentoConciliador(Conciliador):
    def conciliar(self, respuestas: list[SubagentResponse]) -> IndiceConsolidado:
        """Combina índices parciales de N2 en un índice consolidado."""
        # Parsea cada respuesta (formato TEMA/DESCRIPCION/SECCIONES)
        # Deduplica temas similares (ej: "auth_jwt" y "autenticacion_jwt" → fusiona)
        # Reubica temas en categorías coherentes
        # Genera IndiceConsolidado

    def producir_resumen_final(self, consolidado: IndiceConsolidado) -> str:
        """Genera resumen breve (≤500 chars) del documento completo."""
        # Sintetiza los temas consolidados en un resumen coherente
```

**Tests auto:**
- 3 respuestas con 2 temas cada una → consolidado con temas únicos.
- Deduplicación: "auth_jwt" y "autenticacion_jwt" → 1 tema fusionado.
- Resumen final ≤500 chars.
- Caso edge: 1 sola respuesta (sin consolidación real).

---

### Milestone H5 — `DivisorSubagent` (Nivel 1)

**Crear `subagents/divisor_subagent.py`:**

```python
class DivisorSubagent:
    """Subagente Nivel 1: divide documento + lanza N2 en paralelo."""

    def __init__(self, launcher, divisor: DocumentoDivisor, max_paralelos: int):
        self._launcher = launcher
        self._divisor = divisor
        self._max_paralelos = max_paralelos

    def run(self, attachment: Attachment, documento_path: Path) -> list[IndiceParcial]:
        # 1. Particionar documento
        porciones = self._divisor.particionar(documento_path, MAX_TOKENS_POR_SUBAGENTE_N2)

        # 2. Construir prompt para cada N2
        prompt_builder = self._build_prompt_n2(attachment)

        # 3. Lanzar N2 en paralelo (lotes de max_paralelos)
        responses = self._divisor.lanzar_subagentes(
            porciones, self._launcher, self._max_paralelos, prompt_builder
        )

        # 4. Parsear respuestas en IndiceParcial
        indices_parciales = [self._parse_response(r, p) for r, p in zip(responses, porciones)]

        return indices_parciales
```

**Tests auto:**
- 3 porciones, mock invoker devuelve 3 respuestas → 3 índices parciales.
- 5 porciones con max_paralelos=3 → se procesan en 2 lotes (3+2).
- Error en 1 N2 → esa respuesta es error, otras OK.

---

### Milestone H6 — `ConciliadorSubagent` (Nivel 3)

**Crear `subagents/conciliador_subagent.py`:**

```python
class ConciliadorSubagent:
    """Subagente Nivel 3: consolida índices parciales de N2."""

    def __init__(self, launcher, conciliador: DocumentoConciliador):
        self._launcher = launcher
        self._conciliador = conciliador

    def run(self, indices_parciales: list[IndiceParcial], attachment: Attachment) -> DocumentoIndexResult:
        # 1. Construir prompt con todos los índices parciales
        prompt = self._build_prompt_n3(indices_parciales, attachment)

        # 2. Lanzar subagente N3
        response = self._launcher.launch(
            prompt=prompt,
            files_to_read=[],
            description="Consolidar índices de documento grande",
        )

        # 3. Parsear respuesta consolidada
        consolidado = self._conciliador.conciliar([response])

        # 4. Generar resumen final
        resumen_final = self._conciliador.producir_resumen_final(consolidado)

        return DocumentoIndexResult(
            attachment_id=attachment.file_id,
            filename=attachment.filename,
            resumen_breve=resumen_final,
            temas_detectados=consolidado.temas_consolidados,
            archivo_indexado_path=...,
            success=True,
        )
```

**Tests auto:**
- 3 índices parciales → N3 consolida en 1 índice.
- Deduplicación de temas entre porciones.
- Resumen final coherente (≤500 chars).
- Error en N3 → DocumentoIndexResult con success=False.

---

### Milestone H7 — `DocumentoIndexerSubagent.run_3_levels()`

**Modificar `subagents/documento_indexer_subagent.py`:**

```python
class DocumentoIndexerSubagent:
    # ... métodos existentes ...

    def run_3_levels(self, attachment: Attachment) -> DocumentoIndexResult:
        """Flujo de 3 niveles para documentos >50K tokens."""
        # 1. Descargar y guardar documento
        documento_path = self._download_and_save(attachment)

        # 2. Lanzar N1 (DivisorSubagent)
        divisor = DocumentoDivisor()
        n1 = DivisorSubagent(
            launcher=self._launcher,
            divisor=divisor,
            max_paralelos=MAX_SUBAGENTES_N2_PARALELOS,
        )
        indices_parciales = n1.run(attachment, documento_path)

        # 3. Lanzar N3 (ConciliadorSubagent)
        conciliador = DocumentoConciliador()
        n3 = ConciliadorSubagent(
            launcher=self._launcher,
            conciliador=conciliador,
        )
        result = n3.run(indices_parciales, attachment)

        # 4. Mover documento a indexed/
        self._move_to_indexed(documento_path)

        return result
```

**Tests auto:**
- Documento de 200 páginas → run_3_levels() procesa en lotes.
- Documento de 1 página → run() (subagente único, no 3 niveles).
- Error en N1 → DocumentoIndexResult con success=False.
- Error en N3 → DocumentoIndexResult con success=False.

---

### Milestone H8 — `RecoveryCycle` elige entre subagente único o 3 niveles

**Modificar `recovery_cycle.py`:**

```python
def _index_attachments(self, raw_messages):
    # ... detección existente ...

    for att in attachments:
        estimated_tokens = int(att.estimated_tokens)

        # Decidir flujo según tamaño
        if estimated_tokens > PARTITION_THRESHOLD_TOKENS:
            # Documento grande → 3 niveles
            result = indexer.run_3_levels(att)
        else:
            # Documento mediano → subagente único (flujo actual)
            result = indexer.run(att)

        results.append(result)
```

**Tests auto:**
- Attachment de 165K tokens → usa run_3_levels().
- Attachment de 5K tokens → usa run().
- Attachment de 500 tokens → lectura directa (sin subagente).

---

### Milestone H9 — `pipeline.index_document_large()`

**Modificar `pipeline.py`:**

```python
def index_document_large(
    file_id: str,
    jwt: str,
    filename: str = "",
    content_type: str = "application/pdf",
    size: int = 0,
) -> Optional[DocumentoIndexResult]:
    """Indexa un documento grande (>50K tokens) usando 3 niveles de subagentes."""
    # Construye attachment
    # Si estimated_tokens > PARTITION_THRESHOLD_TOKENS:
    #   Usa run_3_levels()
    # Else:
    #   Fallback a index_document() (subagente único)
```

**Tests auto:**
- Documento >50K → usa 3 niveles.
- Documento <50K → fallback a subagente único.
- force_direct=True → lectura directa sin subagente.

---

### Milestone H10 — `CredentialManager` + `JwtBridgeServer`

**Crear `client/credential_manager.py`:**

```python
class CredentialManager:
    """Gestiona el JWT del Director."""

    def __init__(self, credentials_path: Path = None):
        self._path = credentials_path or Path.home() / ".czai" / "credentials.json"

    def get_jwt(self) -> Optional[str]:
        """Lee el JWT persistido. Devuelve None si no existe."""
        if not self._path.exists():
            return None
        data = json.loads(self._path.read_text())
        return data.get("token")

    def save_jwt(self, jwt: str, email: str = "") -> None:
        """Persiste el JWT con permisos 0600."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"token": jwt, "email": email}))
        self._path.chmod(0o600)

    def is_valid(self, jwt: str) -> bool:
        """Verifica el JWT contra /api/v1/auths/."""
        # Hace GET /api/v1/auths/ con cookie token=jwt
        # Si responde role=user → válido
        # Si responde role=guest o 401 → inválido

    def needs_jwt(self) -> bool:
        """True si no hay JWT o el existente es inválido."""
        jwt = self.get_jwt()
        if not jwt:
            return True
        return not self.is_valid(jwt)
```

**Crear `client/jwt_bridge_server.py`:**

```python
class JwtBridgeServer:
    """Mini HTTP server temporal para recibir JWT del .bat."""

    def __init__(self, port: int = JWT_BRIDGE_SERVER_PORT, credential_manager: CredentialManager = None):
        self._port = port
        self._cm = credential_manager or CredentialManager()
        self._server = None
        self._thread = None

    def start(self) -> None:
        """Levanta el server en un thread daemon."""
        from http.server import HTTPServer, BaseHTTPRequestHandler

        class Handler(BaseHTTPRequestHandler):
            def do_GET(s):
                if s.path == "/jwt-status":
                    needs = self._cm.needs_jwt()
                    s.send_json({"needs_jwt": needs})
                elif s.path == "/czai-jwt-bridge.bat":
                    s.serve_file("scripts/czai-jwt-bridge.bat")
                else:
                    s.send_404()

            def do_POST(s):
                if s.path == "/recibir-jwt":
                    body = json.loads(s.read_body())
                    self._cm.save_jwt(body["token"], body.get("email", ""))
                    s.send_json({"success": True})
                    # Apagar server después de recibir
                    threading.Thread(target=self.stop, daemon=True).start()

        self._server = HTTPServer((JWT_BRIDGE_SERVER_HOST, self._port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
```

**Tests auto:**
- `CredentialManager.get_jwt()` sin archivo → None.
- `CredentialManager.save_jwt()` + `get_jwt()` → recupera correctamente.
- `CredentialManager.is_valid()` con mock httpx → valida correctamente.
- `JwtBridgeServer.start()` + GET /jwt-status → responde JSON.
- `JwtBridgeServer` + POST /recibir-jwt → persiste y apaga.

---

### Milestone H11 — Script `.bat` + PowerShell

**Crear `scripts/czai-jwt-bridge.bat`:**

```batch
@echo off
REM CZAI JWT Bridge - Obtiene el JWT del Director y lo envía al sandbox
REM Uso: doble click. Se cierra solo.

REM Configuración (el agente reemplaza estas variables al servir el archivo)
set SANDBOX_URL=%1
if "%SANDBOX_URL%"=="" set SANDBOX_URL=https://DEFAULT_SANDBOX_URL

REM Ejecutar script PowerShell
powershell -ExecutionPolicy Bypass -File "%~dp0jwt_bridge.ps1" -SandboxUrl "%SANDBOX_URL%"
```

**Crear `scripts/jwt_bridge.ps1`:**

```powershell
param(
    [string]$SandboxUrl = "https://DEFAULT_SANDBOX_URL"
)

# 1. Verificar que el agente necesita JWT
$status = Invoke-RestMethod -Uri "$SandboxUrl/jwt-status" -Method GET
if (-not $status.needs_jwt) {
    Write-Host "El agente ya tiene JWT. No es necesario enviarlo."
    exit 0
}

# 2. Lanzar Edge con DevTools Protocol
$edgeProcess = Start-Process -FilePath "msedge.exe" -ArgumentList @(
    "--remote-debugging-port=9222",
    "https://chat.z.ai"
) -PassThru

Start-Sleep -Seconds 5

# 3. Conectarse al DevTools Protocol
$devtoolsUrl = "http://localhost:9222/json"
$tabs = Invoke-RestMethod -Uri $devtoolsUrl -Method GET
$chatTab = $tabs | Where-Object { $_.url -like "*chat.z.ai*" } | Select-Object -First 1

if (-not $chatTab) {
    Write-Host "Error: no se encontró pestaña de chat.z.ai"
    Stop-Process -Id $edgeProcess.Id -Force
    exit 1
}

# 4. Ejecutar fetch('/api/v1/auths/') vía WebSocket
$wsUrl = $chatTab.webSocketDebuggerUrl
# (conexión WebSocket y ejecución de JS - requiere módulo o implementación nativa)

# 5. Capturar JWT de la respuesta
$jwt = $response.token
$email = $response.email

# 6. Enviar JWT al sandbox
$body = @{ token = $jwt; email = $email } | ConvertTo-Json
$result = Invoke-RestMethod -Uri "$SandboxUrl/recibir-jwt" -Method POST -Body $body -ContentType "application/json"

if ($result.success) {
    Write-Host "JWT enviado al agente correctamente."
} else {
    Write-Host "Error enviando JWT."
}

# 7. Cerrar Edge
Stop-Process -Id $edgeProcess.Id -Force
```

**Tests:**
- El `.bat` se ejecuta sin errores (con mock de sandbox).
- El PowerShell detecta pestaña de chat.z.ai.
- El flujo completo envía el JWT correctamente.

---

### Milestone H12 — Integración en `recovery_cycle` + `pipeline`

**Modificar `recovery_cycle.py`:**

```python
def _ensure_jwt(self) -> str:
    """Obtiene el JWT del Director, pidiéndolo si no está disponible."""
    cm = CredentialManager()
    jwt = cm.get_jwt()

    if jwt and cm.is_valid(jwt):
        return jwt

    # JWT no disponible → iniciar JwtBridgeServer y pedir al Director
    server = JwtBridgeServer(credential_manager=cm)
    server.start()

    sandbox_url = f"https://[sandbox-host]:{JWT_BRIDGE_SERVER_PORT}"
    print(f"Descarga y ejecuta: {sandbox_url}/czai-jwt-bridge.bat")

    # Esperar a que el Director ejecute el .bat
    # (el server se apaga solo al recibir el JWT)
    # ... loop de espera con timeout ...

    jwt = cm.get_jwt()
    server.stop()
    return jwt
```

**Modificar `pipeline.py`:**
- `run()` y `index_document()` usan `_ensure_jwt()` si no se pasa JWT explícito.

**Tests auto:**
- `_ensure_jwt()` con JWT válido existente → lo devuelve sin pedir.
- `_ensure_jwt()` sin JWT → inicia server, simula recepción, devuelve JWT.

---

### Milestone H13 — Tests E2E

**Crear `tests/test_v36_e2e.py`:**

```python
def test_e2e_v36_jwt_bridge_flow():
    """Flujo completo del JWT bridge con mock."""
    # 1. CredentialManager sin JWT → needs_jwt=True
    # 2. JwtBridgeServer.start()
    # 3. Simular POST /recibir-jwt con JWT mock
    # 4. CredentialManager ahora tiene JWT
    # 5. needs_jwt=False

def test_e2e_v36_3_levels_small_doc():
    """Doc <50K → subagente único (no 3 niveles)."""

def test_e2e_v36_3_levels_large_doc():
    """Doc >50K → 3 niveles con mock invoker."""
    # 1. Crear PDF mock de 200 páginas
    # 2. DocumentoIndexerSubagent.run_3_levels()
    # 3. N1 divide en ~7 porciones
    # 4. N2×7 procesan en paralelo (lotes de 3)
    # 5. N3 consolida
    # 6. Resultado tiene resumen + temas

def test_e2e_v36_parallel_launch():
    """launch_parallel() lanza N subagentes en paralelo real."""
    # Verificar que el tiempo total es menor que secuencial
```

---

### Milestone H14 — Actualizar `run_all_tests.py` + documentación

**Modificar `tests/run_all_tests.py`:**
- Añadir 6 nuevos módulos atómicos a la Fase 1:
  - `client/credential_manager.py`
  - `client/jwt_bridge_server.py`
  - `processing/divisor.py`
  - `processing/conciliador.py`
  - `subagents/divisor_subagent.py`
  - `subagents/conciliador_subagent.py`

**Modificar `estrategia/worklog_template.md`:**
- Actualizar Paso 2c con instrucciones del `.bat`.

**Actualizar `download/MANUAL_CZAI_v3.5.md` → MANUAL_CZAI_v3.6.md`**

---

## Orden de ejecución

```
H1 (modelos + constantes)
    ↓
H2 (launch_parallel, genérico)  ←── H3 (Divisor)  ←── H4 (Conciliador)  [paralelizables]
    ↓                                   ↓                    ↓
H5 (DivisorSubagent N1) ────────────────┘                    │
    ↓                                                        │
H6 (ConciliadorSubagent N3) ─────────────────────────────────┘
    ↓
H7 (run_3_levels en DocumentoIndexerSubagent)
    ↓
H8 (recovery_cycle elige flujo según tamaño)
    ↓
H9 (pipeline.index_document_large)
    ↓
H10 (CredentialManager + JwtBridgeServer)
    ↓
H11 (scripts .bat + .ps1)
    ↓
H12 (integración _ensure_jwt en recovery_cycle + pipeline)
    ↓
H13 (tests E2E)
    ↓
H14 (run_all_tests + docs)
```

---

## Cobertura de los cambios de la spec v3.6

| Cambio spec v3.6 | Milestone |
|---|---|
| Modelo `Porcion`, `IndiceParcial`, `IndiceConsolidado` | H1 |
| Constantes de particionado y límites paralelos | H1 |
| `SubagentLauncher.launch_parallel()` | H2 |
| Clase base `Divisor` + `DocumentoDivisor` | H3 |
| Clase base `Conciliador` + `DocumentoConciliador` | H4 |
| `DivisorSubagent` (N1) | H5 |
| `ConciliadorSubagent` (N3) | H6 |
| `DocumentoIndexerSubagent.run_3_levels()` | H7 |
| `RecoveryCycle` elige flujo | H8 |
| `pipeline.index_document_large()` | H9 |
| `CredentialManager` | H10 |
| `JwtBridgeServer` | H10 |
| Script `.bat` + `.ps1` | H11 |
| Integración `_ensure_jwt` | H12 |
| Tests E2E | H13 |
| `run_all_tests` + docs | H14 |

**Cobertura total:** 14/14 cambios cubiertos.

---

## Pendiente de validación

Espero tu validación para pasar a la fase de EJECUCIÓN del plan v3.6.
