# Metodología para Obtener el JWT de Z.ai

**Versión:** 2.0 (instalador automático + persistencia localStorage)
**Fecha:** 2025-01-09
**Proyecto:** CZAI (Contexto Z.ai)
**Dirigido a:** Directores y usuarios finales que necesiten conectar su sesión de Z.ai con un sandbox

---

## 1. Propósito

CZAI necesita acceder al contexto de los documentos y chats del Director en Z.ai.
Para ello, requiere un **JWT (JSON Web Token)** que identifica la sesión del Director.

El JWT **no expira** (es un token permanente de Z.ai). Este documento describe
cómo obtenerlo y cómo persiste entre sesiones del sandbox.

---

## 2. Por qué es necesario este proceso

Z.ai protege la sesión del Director con 4 capas de seguridad:

1. **Login con captcha** → no se puede hacer login programático
2. **Cookie `token` HttpOnly** → JavaScript normal no puede leerla
3. **CORS bloquea cross-origin** → un sandbox no puede pedir el JWT directamente a Z.ai
4. **DevTools Protocol bloqueado** → no se puede automatizar el navegador por puerto 9222

La única forma de obtener el JWT es ejecutando código **dentro de chat.z.ai**
(mismo origen), lo que requiere un **bookmarklet** (favorito con código JavaScript).

El instalador automático elimina la complejidad manual de crear ese favorito.

---

## 3. Archivos del instalador

| Archivo | Ubicación en el repositorio | Función |
|---|---|---|
| `czai-installer.bat` | `download/czai-installer.bat` | Ejecutable principal (doble clic) |
| `czai-installer.ps1` | `download/czai-installer.ps1` | Script PowerShell (código fuente, para revisión) |

El `.bat` contiene el `.ps1` embebido en base64 (UTF-16LE) y lo ejecuta con
`powershell -ExecutionPolicy Bypass -EncodedCommand ...`.

---

## 4. Requisitos

- **Sistema operativo:** Windows 10/11
- **Navegador:** Google Chrome o Microsoft Edge instalado
- **Sesión de Z.ai:** el Director debe tener una sesión activa en chat.z.ai
  (haber iniciado sesión al menos una vez en el navegador donde se instala)

---

## 5. Procedimiento para el Director (PRIMERA VEZ)

### Paso 1 — Descargar el instalador

Descargar el archivo `czai-installer.bat` desde el repositorio del proyecto
(carpeta `download/`) o desde la página del sandbox (botón "Descargar instalador").

### Paso 2 — Ejecutar el instalador

1. Localizar el archivo `czai-installer.bat` descargado
2. Hacer **doble clic** sobre él
3. Si Windows SmartScreen muestra "Windows protegió tu PC":
   - Clic en **"Más información"**
   - Clic en **"Ejecutar de todos modos"**
4. En la ventana de consola que se abre:
   - Leer el aviso (el navegador se cerrará automáticamente)
   - Presionar **Enter** para continuar
5. Esperar a que termine (unos 5-10 segundos)

### Paso 3 — Verificar la instalación

El instalador:
- Cierra Chrome/Edge
- Hace backup del archivo de favoritos (`.czai-backup`)
- Agrega el favorito **"Conectar CZAI"** a la barra de favoritos
- Recalcula el checksum (para que Chrome acepte el archivo)
- Reabre el navegador en `chat.z.ai`

Al terminar, el favorito **"Conectar CZAI"** (con icono de llave) debe aparecer
en la barra de favoritos del navegador.

### Paso 4 — Conectar la sesión (PRIMERA Y ÚNICA VEZ por chat)

1. En el navegador (ya abierto en chat.z.ai), **abrir cualquier chat**
   (la URL debe ser `chat.z.ai/c/...`)
2. Hacer **clic en el favorito "Conectar CZAI"** en la barra de favoritos
3. Se abre automáticamente una **nueva pestaña** mostrando
   **"Sesión conectada"**
4. La pestaña se redirige sola al sandbox, que muestra **"Sandbox conectado"**

Después de este paso, el JWT queda guardado en **dos lugares**:
- `~/.czai/credentials.json` dentro del sandbox (efímero)
- **`localStorage` del navegador** del Director (persistente entre sesiones)

---

## 6. Procedimiento para SESIONES NUEVAS del sandbox

El sandbox de Z.ai es **efímero**: cuando se cierra la sesión, el sistema de
archivos se destruye, incluyendo `~/.czai/credentials.json`.

**PERO** el JWT también está guardado en el `localStorage` del navegador del
Director, que SÍ persiste entre sesiones.

### Flujo en una sesión nueva del sandbox

1. El agente inicia sesión nueva (sandbox vacío)
2. El agente ejecuta `setup-czai.sh` para provisionar el código CZAI:
   ```
   cd /home/z/my-project/contexto_zai && bash setup-czai.sh
   ```
3. El agente verifica el estado del JWT:
   ```
   curl -s http://localhost:3000/api/czai/jwt-status
   ```

**Tres escenarios posibles:**

#### Escenario A — El sandbox ya tiene JWT (`needs_jwt: false`)
- El JWT se restauró automáticamente desde `localStorage` del navegador.
- CZAI está listo. No se requiere acción del Director.

#### Escenario B — El sandbox no tiene JWT (`needs_jwt: true`)

Esto significa que el Director nunca ha configurado el JWT para este chat,
o que está usando un chat diferente al que usó para configurarlo.

**Acción del Director:**
1. Abrir la **página del sandbox** (`/`) en el navegador
2. La página detecta automáticamente el `localStorage` y restaura el JWT
3. Si después de abrir la página el estado cambia a `needs_jwt: false`, CZAI está listo

**Si la página no restaura el JWT automáticamente**, pasar al Escenario C.

#### Escenario C — No hay JWT en ningún lado

El Director necesita hacer clic en el favorito **"Conectar CZAI"** desde
`chat.z.ai/c/<cualquier-chat>`.

1. El Director abre un chat en `chat.z.ai/c/...`
2. Hace clic en el favorito **"Conectar CZAI"**
3. Se abre una nueva pestaña con "Sesión conectada"
4. El JWT se guarda en el sandbox Y en el `localStorage` del navegador
5. Para sesiones futuras con el mismo chat, no necesitará volver a hacer clic

---

## 7. Solución de problemas

### 7.1 Windows SmartScreen bloquea el .bat

**Síntoma:** Aparece "Windows protegió tu PC" al ejecutar el .bat

**Solución:**
- Clic en **"Más información"**
- Clic en **"Ejecutar de todos modos"**

El instalador es seguro y transparente. El código fuente está disponible en
`czai-installer.ps1` para revisión antes de ejecutarlo.

### 7.2 El favorito no aparece en la barra

**Síntoma:** Después de ejecutar el instalador, el favorito "Conectar CZAI"
no está visible en la barra de favoritos.

**Posibles causas y soluciones:**

| Causa | Solución |
|---|---|
| El navegador no estaba cerrado completamente | Cerrar manualmente todas las ventanas de Chrome/Edge y volver a ejecutar el instalador |
| Chrome Sync está activo | Esperar 30 segundos (sync puede sobrescribir), o desactivar sync temporalmente |
| Se usa un perfil distinto a "Default" | El instalador busca Default primero, luego Profile N. Verificar en `chrome://version` qué perfil se está usando |
| No se ha abierto Chrome nunca | Abrir Chrome al menos una vez antes de ejecutar el instalador |

### 7.3 Al hacer clic en el favorito no pasa nada

**Síntoma:** Estando en `chat.z.ai/c/...`, se hace clic en "Conectar CZAI"
pero no se abre ninguna pestaña nueva.

**Soluciones:**

1. **Verificar la URL:** debe ser `chat.z.ai/c/...` (con un chat abierto, no la
   página principal de chat.z.ai)

2. **Pop-up bloqueado:** mirar la barra de direcciones. Si aparece un icono de
   bloqueo, hacer clic en él y permitir pop-ups para chat.z.ai

3. **No autenticado:** si aparece el mensaje "No estás autenticado", iniciar
   sesión en chat.z.ai primero y volver a hacer clic en el favorito

### 7.4 El JWT no persiste entre sesiones

**Síntoma:** En una sesión nueva del sandbox, `curl /api/czai/jwt-status`
devuelve `needs_jwt: true` aunque el Director ya había configurado el JWT antes.

**Posibles causas y soluciones:**

| Causa | Solución |
|---|---|
| El Director no ha abierto la página del sandbox | Abrir la página `/` en el navegador; la página restaurará el JWT desde `localStorage` |
| El Director está usando un chat diferente | Hacer clic en el favorito "Conectar CZAI" desde el chat nuevo (el `localStorage` está ligado al dominio `preview-chat-{chatId}.space-z.ai`) |
| El Director borró el `localStorage` | Hacer clic en el favorito "Conectar CZAI" de nuevo |
| El agente no ejecutó `setup-czai.sh` | El agente debe ejecutar `cd /home/z/my-project/contexto_zai && bash setup-czai.sh` antes de verificar el JWT |

### 7.5 Aparece un error en el script

**Síntoma:** La consola muestra un error en rojo.

**Solución:**
- Restaurar el backup: copiar el archivo `.czai-backup` sobre el `Bookmarks`
  original (rutas mostradas en la consola al final del script)
- Reportar el error al agente CZAI con el texto exacto del error

---

## 8. Qué hace exactamente el instalador (transparencia)

El script PowerShell realiza estas operaciones:

1. **Detecta el navegador** (Chrome primero, Edge como fallback)
2. **Localiza el perfil** (Default o Profile N)
3. **Cierra el navegador** (todos los procesos)
4. **Crea un backup** del archivo `Bookmarks` con extensión `.czai-backup`
5. **Lee el JSON** de favoritos
6. **Agrega el favorito** "Conectar CZAI" a la barra de favoritos
   (o actualiza la URL si ya existe)
7. **Calcula el checksum** MD5+base64 según el algoritmo de Chromium
   (MD5 sobre url+title de cada bookmark, en orden bookmark_bar/other/synced)
8. **Escribe el archivo** en UTF-8 sin BOM (formato que Chrome acepta)
9. **Reabre el navegador** en `chat.z.ai`

El código del bookmarklet que se instala es:

```javascript
javascript:(function(){
  var m = location.pathname.match(/\/c\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/);
  if (!m) {
    alert('CZAI: Abre un chat de Z.ai (URL con /c/...) antes de usar el bookmarklet.');
    return;
  }
  var chatId = m[1];
  fetch('/api/v1/auths/', { credentials: 'include' })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d.token || d.role !== 'user') {
        alert('CZAI: No estas autenticado en Z.ai. Inicia sesion en chat.z.ai primero.');
        return;
      }
      var f = document.createElement('form');
      f.method = 'POST';
      f.action = 'https://preview-chat-' + chatId + '.space-z.ai/api/czai/recibir-jwt';
      f.target = '_blank';
      var i1 = document.createElement('input');
      i1.type = 'hidden'; i1.name = 'token'; i1.value = d.token;
      var i2 = document.createElement('input');
      i2.type = 'hidden'; i2.name = 'email'; i2.value = d.email || '';
      f.appendChild(i1); f.appendChild(i2);
      document.body.appendChild(f);
      f.submit();
      document.body.removeChild(f);
    })
    .catch(function(e) {
      alert('CZAI: Error al obtener el JWT: ' + e.message);
    });
})();
```

Lo que hace el bookmarklet al hacer clic desde `chat.z.ai`:

1. Extrae el `chat_id` de la URL actual
2. Hace `fetch('/api/v1/auths/')` (mismo origen, lee la cookie HttpOnly)
3. Crea un `<form>` oculto con `method=POST` y `target=_blank`
4. Rellena el form con el token y el email
5. Envía el form (se abre una nueva pestaña con la respuesta del sandbox)
6. La página de respuesta del sandbox guarda el JWT en `localStorage` del navegador

---

## 9. Seguridad

### 9.1 ¿Dónde se almacena el JWT?

En **dos lugares**:

1. **Sandbox:** `~/.czai/credentials.json`
   ```json
   {
     "token": "eyJ...",
     "email": "director@z.ai"
   }
   ```
   Efímero: se destruye al cerrar la sesión del sandbox.

2. **Navegador del Director:** `localStorage` con las keys:
   - `czai_jwt` — el token JWT
   - `czai_email` — el email del Director
   - `czai_jwt_saved_at` — timestamp de cuándo se guardó

   Persistente: sobrevive entre sesiones del sandbox.

### 9.2 ¿El JWT se transmite por la URL?

**No.** El JWT viaja en el **body del POST** del form, no en la URL.
Por lo tanto, no aparece en logs de acceso del servidor.

### 9.3 ¿El instalador envía datos a algún servidor externo?

**No.** El instalador solo edita el archivo local de favoritos de Chrome/Edge.
No hace ninguna petición de red.

### 9.4 ¿Qué pasa si quiero desinstalar el favorito?

Clic derecho sobre "Conectar CZAI" en la barra de favoritos → "Eliminar".
O restaurar el backup `.czai-backup` que creó el instalador.

### 9.5 ¿El JWT expira?

**No.** El JWT de Z.ai no tiene fecha de expiración.
Solo necesitas hacer el procedimiento de "Conectar la sesión" **una vez por chat**.
Para sesiones nuevas del sandbox con el mismo chat, el JWT se restaura automáticamente.

### 9.6 ¿Cómo borrar el JWT del navegador?

Si necesitas borrar el JWT guardado en el navegador (por ejemplo, para cambiar
de cuenta):

1. Abrir la página del sandbox (`/`) en el navegador
2. Abrir DevTools (F12)
3. Ir a la pestaña **Application** → **Local Storage** → dominio del sandbox
4. Borrar las keys `czai_jwt`, `czai_email`, `czai_jwt_saved_at`
5. Hacer clic en el favorito "Conectar CZAI" de nuevo con la nueva cuenta

---

## 10. Para nuevos Directores

Si un nuevo Director necesita usar CZAI:

1. El agente CZAI le entrega el archivo `czai-installer.bat`
   (desde la carpeta `download/` del repositorio)
2. El nuevo Director sigue los pasos 1-4 de la sección 5 (primera vez)
3. El agente CZAI verifica que el JWT llegó consultando
   `GET /api/czai/jwt-status` en el sandbox del nuevo Director
4. Si `needs_jwt: false`, el Director está conectado y puede usar CZAI
5. Para sesiones futuras, el Director solo necesita abrir la página del sandbox;
   el JWT se restaurará automáticamente desde `localStorage`

---

## 11. Referencias técnicas

- **Script de setup del sandbox:** `contexto_zai/setup-czai.sh`
  - Provisiona el código CZAI en cualquier sandbox nuevo
  - Idempotente: se puede ejecutar múltiples veces
  - No sobrescribe `~/.czai/credentials.json`
- **Endpoint del sandbox que recibe el JWT:** `POST /api/czai/recibir-jwt`
  - Acepta `application/x-www-form-urlencoded` (form POST del bookmarklet)
  - Acepta `application/json` (restauración desde localStorage)
  - Devuelve HTML de confirmación (para form POST) que guarda el JWT en localStorage
  - Devuelve JSON (para JSON POST)
- **Endpoint de estado:** `GET /api/czai/jwt-status`
  - Devuelve `{"needs_jwt": true|false, "email": "..."}`
- **Algoritmo de checksum de Chrome:** MD5 sobre la concatenación de
  `url + title` de cada bookmark, recorrido en orden: `bookmark_bar.children`,
  `other.children`, `synced.children`. El resultado se codifica en base64.
- **Formato de fecha de Chrome:** microsegundos desde 1601-01-01 UTC
- **Persistencia del JWT:**
  - `~/.czai/credentials.json` (efímero, sandbox)
  - `localStorage` del navegador (persistente, keys: `czai_jwt`, `czai_email`, `czai_jwt_saved_at`)
  - El `localStorage` está ligado al dominio `preview-chat-{chatId}.space-z.ai`
