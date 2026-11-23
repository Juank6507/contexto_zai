import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import os from 'os';

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 200,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    },
  });
}

function saveJwt(token: string, email: string): void {
  const credsDir = path.join(os.homedir(), '.czai');
  if (!fs.existsSync(credsDir)) {
    fs.mkdirSync(credsDir, { recursive: true });
  }
  const credsPath = path.join(credsDir, 'credentials.json');
  fs.writeFileSync(credsPath, JSON.stringify({ token, email }, null, 2));
}

function htmlConfirmationPage(email: string, token: string): string {
  const escapedEmail = email.replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const escapedToken = token.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  return `<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CZAI Bridge - Conectado</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0a0a0a;
    color: #e5e5e5;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
  }
  .card {
    max-width: 480px;
    width: 100%;
    background: #111;
    border: 1px solid #10b981;
    border-radius: 12px;
    padding: 2rem;
    text-align: center;
  }
  .icon {
    width: 56px;
    height: 56px;
    margin: 0 auto 1rem;
    background: rgba(16, 185, 129, 0.15);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .icon svg { width: 28px; height: 28px; stroke: #10b981; }
  h1 { font-size: 1.5rem; margin-bottom: 0.5rem; color: #10b981; }
  p { color: #a3a3a3; line-height: 1.5; margin-bottom: 0.75rem; font-size: 0.95rem; }
  .email {
    font-family: monospace;
    background: #1a1a1a;
    padding: 0.5rem 0.75rem;
    border-radius: 6px;
    color: #d1d5db;
    margin: 0.75rem 0 1.5rem;
    word-break: break-all;
    font-size: 0.85rem;
  }
  .btn {
    display: inline-block;
    background: #10b981;
    color: #000;
    text-decoration: none;
    padding: 0.65rem 1.5rem;
    border-radius: 8px;
    font-weight: 600;
    font-size: 0.9rem;
  }
  .note { margin-top: 1.5rem; font-size: 0.8rem; color: #737373; }
</style>
</head>
<body>
  <div class="card">
    <div class="icon">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
      </svg>
    </div>
    <h1>Sesion conectada</h1>
    <p>Tu sesion de Z.ai se ha conectado correctamente a este sandbox.</p>
    <div class="email">${escapedEmail || '(sin email)'}</div>
    <a class="btn" href="/">Ir al sandbox</a>
    <p class="note">Redirigiendo al sandbox automaticamente...<br>Si no redirige, haz clic en el boton de arriba.<br>El JWT se guardo en este navegador para sesiones futuras.</p>
  </div>
  <script>
    // Guardar JWT en localStorage para persistencia entre sesiones
    // El sandbox es efimero, pero el navegador del Director persiste.
    // En la proxima sesion, al abrir esta pagina, el JWT se restaurara automaticamente.
    try {
      localStorage.setItem('czai_jwt', '${escapedToken}');
      localStorage.setItem('czai_email', '${escapedEmail}');
      localStorage.setItem('czai_jwt_saved_at', new Date().toISOString());
    } catch (e) {
      console.error('No se pudo guardar JWT en localStorage:', e);
    }
    setTimeout(function() { window.location.href = '/'; }, 2500);
  </script>
</body>
</html>`;
}

function htmlErrorPage(message: string): string {
  const escaped = message.replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return `<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CZAI Bridge - Error</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0a0a0a; color: #e5e5e5; min-height: 100vh;
    display: flex; align-items: center; justify-content: center; padding: 1rem;
  }
  .card { max-width: 480px; width: 100%; background: #111; border: 1px solid #ef4444; border-radius: 12px; padding: 2rem; text-align: center; }
  .icon { width: 56px; height: 56px; margin: 0 auto 1rem; background: rgba(239, 68, 68, 0.15); border-radius: 50%; display: flex; align-items: center; justify-content: center; }
  .icon svg { width: 28px; height: 28px; stroke: #ef4444; }
  h1 { font-size: 1.5rem; margin-bottom: 0.5rem; color: #ef4444; }
  p { color: #a3a3a3; line-height: 1.5; margin-bottom: 0.75rem; font-size: 0.95rem; }
  .btn { display: inline-block; background: #404040; color: #fff; text-decoration: none; padding: 0.65rem 1.5rem; border-radius: 8px; font-weight: 600; font-size: 0.9rem; margin-top: 1rem; }
</style>
</head>
<body>
  <div class="card">
    <div class="icon">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z" />
      </svg>
    </div>
    <h1>Error</h1>
    <p>${escaped}</p>
    <a class="btn" href="/">Volver</a>
  </div>
</body>
</html>`;
}

export async function POST(request: NextRequest) {
  try {
    const contentType = request.headers.get('content-type') || '';
    let jwt = '';
    let email = '';

    if (contentType.includes('application/json')) {
      const body = await request.json();
      jwt = body.token;
      email = body.email || '';
    } else {
      // Form POST (application/x-www-form-urlencoded) - viene del bookmarklet
      const formData = await request.formData();
      jwt = (formData.get('token') as string) || '';
      email = (formData.get('email') as string) || '';
    }

    if (!jwt) {
      // Si es form POST, devolver HTML de error; si es JSON, devolver JSON
      if (contentType.includes('application/json')) {
        return NextResponse.json({ success: false, error: 'Token vacio' }, { status: 400 });
      }
      return new NextResponse(htmlErrorPage('No se recibio el token JWT.'), {
        status: 400,
        headers: { 'Content-Type': 'text/html; charset=utf-8' },
      });
    }

    saveJwt(jwt, email);

    // Si es form POST, devolver HTML de confirmacion; si es JSON, devolver JSON
    if (contentType.includes('application/json')) {
      return NextResponse.json({ success: true, email });
    }
    return new NextResponse(htmlConfirmationPage(email, jwt), {
      status: 200,
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    });
  } catch (error) {
    const msg = String(error);
    const contentType = request.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      return NextResponse.json({ success: false, error: msg }, { status: 500 });
    }
    return new NextResponse(htmlErrorPage(msg), {
      status: 500,
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    });
  }
}
