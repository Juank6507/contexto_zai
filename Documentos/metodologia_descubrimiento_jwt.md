# Metodología de Descubrimiento del JWT Token de Autenticación

**Fecha:** 2025-08-21
**Proyecto:** Contexto Z.ai — Sistema de Recuperación de Contexto
**Autor:** Agente

---

## 1. Objetivo

Documentar la cadena de razonamiento y los pasos experimentales que permitieron descubrir cómo autenticar `agent-browser` como el Director en `chat.z.ai`, logrando así la automatización completa del Paso -1 del sistema de recuperación de contexto.

---

## 2. Contexto inicial

El sistema de recuperación de contexto necesita un `share_id` para extraer mensajes de un chat. En la v2.2 del spec, este paso requería intervención manual del Director (compartir el chat manualmente). El objetivo era eliminar esa intervención.

**Restricciones conocidas (de sesiones anteriores):**
- `agent-browser` inicia siempre como invitado (sin sesión del Director)
- La cookie de autenticación es HttpOnly (no accesible vía `document.cookie` desde la consola del navegador del Director)
- El Director no puede ejecutar comandos largos en la consola de DevTools (el navegador no es Chrome estándar, no soporta `allow pasting`)
- El batch endpoint usa `share_id` (no `chat_id`) — descubierto en sesión 5
- Toda la extracción funciona como invitado una vez que el chat está compartido

---

## 3. Cadena de descubrimiento

### Paso 1 — El Director indica dónde está el token

El Director revisó los Request Headers en la pestaña Network de DevTools y reportó:

> "No veo la palabra cookie por ningún lado. Lo que veo es esto Bearer:
> Bearer eyJhbG... en request header"

**Inferencia inicial:** La plataforma envía el token como header `Authorization: Bearer <JWT>`. El Director no ve una cookie porque es HttpOnly.

**Dato clave:** El Director proporcionó el token completo desde el Authorization header.

Decodificación del payload JWT:
```json
{"id": "229a58c8-df7f-48e8-be56-5b02ebbe2c1b", "email": "juanca6507@gmail.com"}
```

Header JWT:
```json
{"alg": "ES256", "typ": "JWT"}
```

**Observación:** No hay campo `exp` (expiración) en el payload. El token no expira por diseño JWT.

---

### Paso 2 — Inspección de cookies del invitado

Abrí `chat.z.ai` con agent-browser (como invitado) y ejecuté:

```bash
agent-browser cookies
```

**Hallazgo:** Existe una cookie llamada `token` con un JWT de invitado:
```
token=eyJhbG... (payload: {"id":"cb99c085-...", "email":"guest-1788311811176@guest.com"})
```

**Inferencia:** La cookie se llama `token`. El frontend de chat.z.ai lee esta cookie y la envía como `Authorization: Bearer <token>` en las requests API. El Director no la ve en DevTools porque es HttpOnly.

**Esto fue el descubrimiento fundamental.** Sabiendo el nombre de la cookie, se puede reemplazar su valor.

---

### Paso 3 — Primer intento: set cookie + navigate (FALLÓ)

```bash
agent-browser cookies set token "<JWT_DEL_DIRECTOR>"
agent-browser open "https://chat.z.ai/c/{chat_id}"
```

**Resultado:** La página redirigió a `https://chat.z.ai/` (home). La cookie fue sobrescrita por el servidor.

**Verificación post-fallo:**
```bash
agent-browser cookies | rg token
# → token=eyJhbG...(guest token DIFERENTE al que acababa de setear)
```

**Análisis del fallo:** Al navegar a una nueva URL, el servidor responde con `Set-Cookie: token=<nuevo_guest_token>`, sobrescribiendo la cookie inyectada. El servidor no reconoce el token del Director en este contexto porque la request inicial de navegación ya trae la cookie guest.

---

### Paso 4 — Segundo intento: set headers Authorization (PARCIAL)

En lugar de depender solo de la cookie, añadí el header Authorization a TODAS las requests del navegador:

```bash
agent-browser set headers '{"Authorization": "Bearer <JWT_DEL_DIRECTOR>"}'
agent-browser open "https://chat.z.ai/c/{chat_id}"
```

**Resultado:** La URL se mantuvo en `/c/{chat_id}` (no redirigió). El header Authorization fue aceptado por el servidor.

**Pero:** La página estaba en blanco. La consola mostró:
```
{detail: "failed to get chat: chat not found: 371ba778-..."}
```

**Análisis:** El header Authorization previno la redirección del servidor, pero el código frontend (React) hizo sus propias API calls usando la cookie (que seguía siendo de invitado). La cookie guest no tiene acceso al chat privado → "chat not found".

**Conclusión del Paso 4:** El header funciona para la request del documento HTML, pero las API calls internas del frontend usan la cookie. Necesito la cookie correcta.

---

### Paso 5 — Tercer intento: set cookie + reload (ÉXITO)

**Insight clave:** En lugar de navegar a una nueva URL (que genera una request fresca con Set-Cookie), recargué la página actual con `location.reload()`. La diferencia:

| Acción | ¿Servidor envía Set-Cookie? | ¿Cookie inyectada sobrevive? |
|--------|------------------------------|------------------------------|
| `agent-browser open <url>` | Sí (navegación completa) | No (se sobrescribe) |
| `location.reload()` | Depende | **Sí** (si el token es válido, el servidor lo refresca en lugar de reemplazarlo) |

**Procedimiento exacto:**

```bash
# 1. Abrir chat.z.ai (establece dominio, cookie guest inicial)
agent-browser open "https://chat.z.ai"

# 2. Establecer headers Authorization (previene redirecciones)
agent-browser set headers '{"Authorization": "Bearer <JWT>"}'

# 3. Navegar al chat (URL se mantiene gracias al header)
agent-browser open "https://chat.z.ai/c/{chat_id}"

# 4. Inyectar cookie con el token del Director
agent-browser cookies set token "<JWT_DEL_DIRECTOR>"

# 5. Recargar la página
agent-browser eval "location.reload()"
agent-browser wait 3000
```

**Resultado:**
- URL se mantuvo: `/c/{chat_id}`
- Sin errores en consola (el "chat not found" desapareció)
- La cookie fue **refrescada** por el servidor (nueva firma, mismo payload del Director)

**Verificación del refresh:**
```
Antes del reload:
token=eyJhbG...fQiKg  (firma original del Director)

Después del reload:
token=eyJhbG...0e5g  (firma NUEVA, payload idéntico)
```

El servidor validó el token del Director, lo refrescó, y respondió con `Set-Cookie` con el nuevo token. La cookie guest fue reemplazada permanentemente.

---

### Paso 6 — Verificación de autenticación

Llamé al endpoint de auth para confirmar:

```javascript
fetch('/api/v1/auths/').then(r => r.json())
```

**Respuesta:**
```json
{
  "id": "229a58c8-df7f-48e8-be56-5b02ebbe2c1b",
  "email": "juanca6507@gmail.com",
  "name": "Juan Carlos González",
  "role": "user",
  "idp": "google",
  "permissions": {
    "chat": {"controls": true, "delete": true, "edit": true, ...},
    "features": {"code_interpreter": true, "image_generation": true, ...},
    "sharing": {...},
    "workspace": {...}
  },
  "token": "eyJhbG... (token refrescado)",
  "token_type": "Bearer",
  "expires_at": null
}
```

**Confirmaciones:**
- Autenticación completa como Juan Carlos González
- Permisos completos (delete, edit, file_upload)
- `expires_at: null` — el token no expira

---

### Paso 7 — Llamada al Share API

Con la autenticación funcionando, llamé al endpoint de share:

```javascript
fetch('/api/v1/chats/371ba778-.../share', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'}
}).then(r => r.json())
```

**Respuesta (200):**
```json
{
  "id": "db717d70-95a7-4e2d-8992-fb4b6ba10df6",
  "user_id": "shared-371ba778-...",
  "title": "EP 02",
  "chat": { ... }
}
```

**El share_id fue obtenido sin intervención del Director.**

---

### Paso 8 — Persistencia del estado

Para eliminar la necesidad del token en futuras sesiones:

```bash
agent-browser state save /home/z/my-project/.browser_auth_state.json
```

**Prueba en sesión nueva:**

```bash
agent-browser close
agent-browser state load /home/z/my-project/.browser_auth_state.json
agent-browser open "https://chat.z.ai/c/{chat_id}"

# Verificar cookie
agent-browser cookies | rg token
# → token=eyJhbG...(token refrescado del Director, firma diferente pero mismo payload)

# Probar share API
fetch('/api/v1/chats/{chat_id}/share', {method:'POST'}).then(r=>r.json()).then(d=>d.id)
# → "db717d70-95a7-4e2d-8992-fb4b6ba10df6"
```

**Resultado:** La sesión persiste. El share API funciona sin proporcionar el token nuevamente.

---

## 4. Resumen de la cadena de descubrimiento

```
Director ve Bearer token en DevTools
  → El token está en Authorization header, no visible como cookie
  → PERO: agente descubre cookie `token` con JWT guest inspeccionando agent-browser
  → Hipótesis: el frontend lee la cookie y la envía como Bearer header
  → Experimento 1: set cookie + navigate → FALLÓ (servidor sobrescribe con guest)
  → Experimento 2: set headers Authorization → PARCIAL (URL correcta, pero API calls usan cookie guest)
  → Experimento 3: set cookie + reload (no navigate) → ÉXITO
    → El servidor reconoce el token válido y lo refresca en lugar de sobrescribirlo
  → Verificación: auth API confirma perfil completo del Director
  → Share API funciona → share_id obtenido automáticamente
  → State save/load persiste la sesión entre sesiones del agente
```

## 5. Modelo mental de la autenticación de chat.z.ai

```
┌─────────────────────────────────────────────────────────┐
│                    NAVEGADOR                            │
│                                                         │
│  Cookie: token=<JWT>  ──→  Frontend lee cookie         │
│                                │                        │
│                                ▼                        │
│                    Authorization: Bearer <JWT>          │
│                                │                        │
└────────────────────────────────┼────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────┐
│                  SERVIDOR chat.z.ai                     │
│                                                         │
│  1. Recibe request con Bearer token                    │
│  2. Valida firma ES256                                 │
│  3. Si válido: refresca token (nueva firma)             │
│  4. Responde con Set-Cookie: token=<nuevo_JWT>         │
│  5. Si inválido/expirado: responde con guest token      │
│                                                         │
│  Excepción: la navegación inicial (/) siempre genera   │
│  un nuevo guest token sin importar la cookie enviada.  │
│  El reload() en una página ya autenticada sí respeta   │
│  la cookie existente.                                  │
└─────────────────────────────────────────────────────────┘
```

## 6. Lecciones aprendidas

1. **El nombre de la cookie es el dato más valioso.** Una vez que sabes que se llama `token`, todo lo demás sigue.

2. **`navigate` ≠ `reload`.** Una navegación completa genera una request fresca que puede sobrescribir cookies. Un reload preserva el contexto de la página actual.

3. **Los tokens se refrescan, no se reutilizan.** El servidor genera una nueva firma en cada response. Esto es normal y esperado.

4. **`state save/load` es la clave para la persistencia.** Sin esto, el agente necesitaría el token del Director en cada sesión.

5. **La UI no necesita funcionar.** Aunque React no renderizó el chat en agent-browser, todas las API calls funcionan. La extracción es 100% via API, no vía UI.

6. **El JWT no expira por diseño.** Sin campo `exp` y `expires_at: null`. La única forma de invalidación es actions del servidor (logout, cambio de contraseña, etc.).

---

## 7. Procedimiento reproducible (para cualquier chat)

### Setup inicial (una vez por usuario)

1. El usuario abre DevTools en chat.z.ai
2. Pestaña Network → cualquier request → header `Authorization: Bearer <token>`
3. Copiar el token
4. El agente lo guarda en `/home/z/my-project/.auth_token`
5. El agente ejecuta el protocolo de inyección (Paso 5 arriba)
6. El agente guarda el estado: `agent-browser state save .browser_auth_state.json`

### Uso recurrente (cero intervención)

1. `agent-browser state load .browser_auth_state.json`
2. `agent-browser open "https://chat.z.ai/c/{chat_id}"`
3. `fetch('/api/v1/chats/{chat_id}/share', {method:'POST'})` → share_id
4. Proceder con Fase 1 (extracción) usando el share_id