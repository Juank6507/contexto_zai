/**
 * CZAI JWT Bridge - Bookmarklet (v2: form POST approach)
 *
 * Este bookmarklet se ejecuta en chat.z.ai y:
 * 1. Extrae el chat_id de la URL actual
 * 2. Hace fetch('/api/v1/auths/') para obtener el JWT (mismo origen, sin CORS)
 * 3. Crea un <form> oculto con action = sandbox, method = POST, target = _blank
 * 4. Lo submit. El navegador abre una nueva pestana del sandbox con la respuesta HTML
 *
 * Ventajas sobre el enfoque anterior (hash + window.open):
 * - No usa window.open (no hay bloqueo de pop-ups)
 * - El form POST cross-origin SI esta permitido (no bloqueado por CORS)
 * - Funciona aunque el sandbox no tenga JS habilitado
 * - El JWT va en el body del POST (no en URL, no en logs de acceso)
 */

export const BOOKMARKLET_SOURCE = `javascript:(function(){
  var m = location.pathname.match(/\\/c\\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/);
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
})();`;

/**
 * Devuelve el codigo del bookmarklet con la URL del sandbox pre-construida.
 */
export function buildBookmarklet(sandboxBaseUrl: string): string {
  const escaped = sandboxBaseUrl.replace(/'/g, "\\'");
  return `javascript:(function(){
  var w = window.open('about:blank', '_blank');
  if (!w) { alert('CZAI: Permite pop-ups para chat.z.ai.'); return; }
  fetch('/api/v1/auths/', { credentials: 'include' })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d.token || d.role !== 'user') {
        w.close();
        alert('CZAI: No estas autenticado. Inicia sesion primero.');
        return;
      }
      w.location.href = '${escaped}' + '#jwt=' + encodeURIComponent(d.token) + '&email=' + encodeURIComponent(d.email || '');
    })
    .catch(function(e) { w.close(); alert('CZAI: Error: ' + e.message); });
})();`;
}

/**
 * Parsea el hash fragment de la URL del sandbox para extraer el JWT y el email.
 * Formato esperado: #jwt={token}&email={email}
 */
export function parseJwtFromHash(hash: string): { token: string; email: string } | null {
  if (!hash || !hash.startsWith('#')) return null;
  const params = new URLSearchParams(hash.substring(1));
  const token = params.get('jwt');
  const email = params.get('email') || '';
  if (!token) return null;
  return { token, email };
}
