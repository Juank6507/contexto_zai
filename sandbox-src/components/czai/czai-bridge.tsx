'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Separator } from '@/components/ui/separator';
import { Toaster } from '@/components/ui/toaster';
import { toast } from 'sonner';
import {
  ShieldCheck,
  ShieldAlert,
  Download,
  Loader2,
  KeyRound,
  Info,
  Lock,
  ExternalLink,
  FileCode,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  PlayCircle,
  MousePointerClick,
  AlertCircle,
} from 'lucide-react';
import { parseJwtFromHash } from '@/lib/czai/bookmarklet';

type BridgeState = 'idle' | 'receiving' | 'success' | 'error';

export function CzaiBridge() {
  const [state, setState] = useState<BridgeState>('idle');
  const [jwtStatus, setJwtStatus] = useState<{ needs_jwt: boolean; email?: string } | null>(null);
  const [showSource, setShowSource] = useState(false);
  const [showTroubleshooting, setShowTroubleshooting] = useState(false);
  const processedHash = useRef<string | null>(null);
  const isConnected = jwtStatus != null && !jwtStatus.needs_jwt;

  useEffect(() => {
    let cancelled = false;

    const loadStatus = async () => {
      try {
        const res = await fetch('/api/czai/jwt-status');
        const data = await res.json();
        if (cancelled) return;
        setJwtStatus({ needs_jwt: data.needs_jwt, email: data.email || '' });

        // Si el sandbox no tiene JWT, intentar restaurar desde localStorage
        // (persistencia entre sesiones via navegador del Director)
        if (data.needs_jwt && typeof window !== 'undefined') {
          const savedJwt = localStorage.getItem('czai_jwt');
          const savedEmail = localStorage.getItem('czai_email') || '';
          if (savedJwt) {
            // Hay un JWT guardado en el navegador, restaurarlo al sandbox
            try {
              const restoreRes = await fetch('/api/czai/recibir-jwt', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: savedJwt, email: savedEmail }),
              });
              const restoreData = await restoreRes.json();
              if (cancelled) return;
              if (restoreData.success) {
                setJwtStatus({ needs_jwt: false, email: savedEmail });
                toast.success('JWT restaurado del navegador', {
                  description: savedEmail ? `Sesion: ${savedEmail}` : 'Sesion autenticada',
                });
              }
            } catch {
              // Si falla la restauracion, no hacer nada (el Director tendra que hacer clic)
            }
          }
        }
      } catch {
        if (!cancelled) setJwtStatus({ needs_jwt: true, email: '' });
      }
    };

    const loadHash = async () => {
      if (typeof window === 'undefined') return;
      const hash = window.location.hash;
      if (!hash || !hash.includes('jwt=')) return;
      if (processedHash.current === hash) return;
      processedHash.current = hash;

      const parsed = parseJwtFromHash(hash);
      if (!parsed) return;

      setState('receiving');
      try {
        const res = await fetch('/api/czai/recibir-jwt', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: parsed.token, email: parsed.email }),
        });
        const data = await res.json();
        if (cancelled) return;

        if (data.success) {
          setState('success');
          setJwtStatus({ needs_jwt: false, email: parsed.email });
          // Guardar en localStorage para persistencia entre sesiones
          try {
            localStorage.setItem('czai_jwt', parsed.token);
            localStorage.setItem('czai_email', parsed.email);
            localStorage.setItem('czai_jwt_saved_at', new Date().toISOString());
          } catch {}
          toast.success('JWT conectado', {
            description: parsed.email ? `Sesion: ${parsed.email}` : 'Sesion autenticada',
          });
          window.history.replaceState(null, '', window.location.pathname);
        } else {
          setState('error');
          toast.error('No se pudo guardar el JWT', {
            description: data.error || 'Error desconocido',
          });
        }
      } catch (e) {
        if (cancelled) return;
        setState('error');
        toast.error('Error de conexion', { description: String(e) });
      }
    };

    loadStatus();
    loadHash();

    const handleHashChange = () => {
      processedHash.current = null;
      loadHash();
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => {
      cancelled = true;
      window.removeEventListener('hashchange', handleHashChange);
    };
  }, []);

  const handleVerify = useCallback(async () => {
    try {
      const res = await fetch('/api/czai/jwt-status');
      const data = await res.json();
      setJwtStatus({ needs_jwt: data.needs_jwt, email: data.email || '' });
      if (!data.needs_jwt) {
        toast.success('Sesion activa verificada');
      } else {
        toast.warning('No hay sesion activa');
      }
    } catch {
      setJwtStatus({ needs_jwt: true, email: '' });
      toast.error('No se pudo verificar el estado');
    }
  }, []);

  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      {/* Header */}
      <header className="border-b border-border/60 backdrop-blur-sm bg-background/80 sticky top-0 z-10">
        <div className="container mx-auto max-w-4xl px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
              <KeyRound className="w-5 h-5 text-emerald-500" />
            </div>
            <div>
              <h1 className="text-lg font-semibold tracking-tight">CZAI Bridge</h1>
              <p className="text-xs text-muted-foreground">Contexto Z.ai</p>
            </div>
          </div>
          {isConnected ? (
            <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
              <ShieldCheck className="w-3 h-3 mr-1.5" />
              Conectado
            </Badge>
          ) : (
            <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400">
              <ShieldAlert className="w-3 h-3 mr-1.5" />
              Sin conexion
            </Badge>
          )}
        </div>
      </header>

      {/* Contenido principal */}
      <main className="flex-1 container mx-auto max-w-4xl px-4 py-8 space-y-6">
        {/* Estado de recepcion de JWT */}
        {state === 'receiving' && (
          <Alert className="border-emerald-500/30 bg-emerald-500/5">
            <Loader2 className="h-4 w-4 animate-spin text-emerald-500" />
            <AlertTitle>Recibiendo JWT...</AlertTitle>
            <AlertDescription>
              Conectando tu sesion de Z.ai con el sandbox. Esto toma solo un momento.
            </AlertDescription>
          </Alert>
        )}

        {state === 'success' && (
          <Alert className="border-emerald-500/30 bg-emerald-500/5">
            <ShieldCheck className="h-4 w-4 text-emerald-500" />
            <AlertTitle>JWT conectado correctamente</AlertTitle>
            <AlertDescription>
              {jwtStatus?.email
                ? `Sesion autenticada como ${jwtStatus.email}.`
                : 'Sesion autenticada.'}
            </AlertDescription>
          </Alert>
        )}

        {state === 'error' && (
          <Alert variant="destructive">
            <ShieldAlert className="h-4 w-4" />
            <AlertTitle>Error al guardar el JWT</AlertTitle>
            <AlertDescription>
              Hubo un problema. Intenta de nuevo haciendo clic en el favorito desde chat.z.ai.
            </AlertDescription>
          </Alert>
        )}

        {/* Tarjeta principal: estado o instrucciones */}
        {isConnected && state !== 'receiving' ? (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-emerald-500" />
                Sandbox conectado
              </CardTitle>
              <CardDescription>
                Tu sesion de Z.ai esta conectada a este sandbox.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between rounded-lg border border-border/60 bg-muted/30 p-4">
                <div className="space-y-1">
                  <p className="text-sm font-medium">Sesion activa</p>
                  <p className="text-xs text-muted-foreground font-mono">
                    {jwtStatus?.email || 'usuario@z.ai'}
                  </p>
                </div>
                <Badge variant="secondary" className="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20">
                  Activo
                </Badge>
              </div>
              <Alert>
                <Info className="h-4 w-4" />
                <AlertTitle>Como usar CZAI</AlertTitle>
                <AlertDescription>
                  El JWT no expira. No necesitas reconectar a menos que cambies de cuenta.
                  Los subagentes ya pueden acceder al contexto de tus documentos.
                </AlertDescription>
              </Alert>
              <Button
                variant="outline"
                onClick={handleVerify}
                className="w-full"
              >
                <ShieldCheck className="w-4 h-4 mr-2" />
                Verificar estado
              </Button>
            </CardContent>
          </Card>
        ) : (
          <>
            {/* Tarjeta principal: descargar instalador */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <KeyRound className="w-5 h-5 text-emerald-500" />
                  Conecta tu sesion de Z.ai
                </CardTitle>
                <CardDescription>
                  Descarga el instalador, haz doble clic, y el favorito &laquo;Conectar CZAI&raquo;
                  aparecera en tu barra de Chrome o Edge. Luego solo haz clic en ese favorito
                  desde chat.z.ai.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                {/* Paso 1: Descargar y ejecutar */}
                <div className="space-y-3">
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-sm font-semibold text-emerald-600 dark:text-emerald-400">
                      1
                    </div>
                    <div className="flex-1 space-y-3">
                      <div>
                        <p className="text-sm font-medium">Descarga el instalador y ejecutalo</p>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          Descarga el archivo <span className="font-mono">.bat</span>, haz doble clic,
                          y sigue las instrucciones en pantalla. El instalador cerrara tu navegador
                          momentaneamente para instalar el favorito.
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <a
                          href="/api/czai/installer-bat"
                          download="czai-installer.bat"
                          className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white px-5 py-2.5 text-sm font-medium transition-colors"
                        >
                          <Download className="w-4 h-4" />
                          Descargar instalador (.bat)
                        </a>
                        <button
                          onClick={() => setShowSource(!showSource)}
                          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                        >
                          {showSource ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                          <FileCode className="w-3.5 h-3.5" />
                          Ver codigo fuente
                        </button>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Codigo fuente colapsable */}
                {showSource && (
                  <Alert>
                    <FileCode className="h-4 w-4" />
                    <AlertTitle className="text-xs">Codigo fuente del instalador (PowerShell)</AlertTitle>
                    <AlertDescription className="text-xs space-y-2">
                      <p>
                        El instalador es un script PowerShell que edita el archivo de favoritos
                        de Chrome/Edge para agregar el bookmarklet. Es transparente: puedes
                        revisar el codigo antes de ejecutarlo.
                      </p>
                      <div className="flex gap-3">
                        <a
                          href="/api/czai/installer-ps1"
                          download="czai-installer.ps1"
                          className="inline-flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 hover:underline"
                        >
                          <Download className="w-3 h-3" />
                          Descargar .ps1
                        </a>
                      </div>
                      <p className="text-[11px] text-muted-foreground/70">
                        Lo que hace: cierra el navegador &rarr; respalda el archivo de favoritos &rarr;
                        agrega el favorito &laquo;Conectar CZAI&raquo; &rarr; recalcula el checksum &rarr;
                        guarda el archivo &rarr; reabre el navegador en chat.z.ai
                      </p>
                    </AlertDescription>
                  </Alert>
                )}

                <Separator />

                {/* Paso 2: Ir a chat.z.ai */}
                <div className="space-y-3">
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-sm font-semibold text-emerald-600 dark:text-emerald-400">
                      2
                    </div>
                    <div className="flex-1 space-y-1">
                      <p className="text-sm font-medium">Ve a chat.z.ai y abre cualquier chat</p>
                      <p className="text-xs text-muted-foreground">
                        El instalador abre chat.z.ai automaticamente. Solo necesitas abrir
                        cualquier chat (URL con <span className="font-mono">chat.z.ai/c/...</span>).
                      </p>
                    </div>
                  </div>
                </div>

                <Separator />

                {/* Paso 3: Clic en el favorito */}
                <div className="space-y-3">
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-sm font-semibold text-emerald-600 dark:text-emerald-400">
                      3
                    </div>
                    <div className="flex-1 space-y-2">
                      <p className="text-sm font-medium">Haz clic en &laquo;Conectar CZAI&raquo; en la barra de favoritos</p>
                      <p className="text-xs text-muted-foreground">
                        Se abrira una nueva pestana con &laquo;Sesion conectada&raquo; y te redirigira
                        automaticamente al sandbox. No necesitas hacer nada mas.
                      </p>
                    </div>
                  </div>
                </div>

                <Separator />

                {/* Resumen visual */}
                <div className="grid grid-cols-3 gap-3">
                  <div className="rounded-lg border border-border/60 bg-muted/20 p-3 space-y-1.5">
                    <Download className="w-4 h-4 text-emerald-500" />
                    <p className="text-[11px] font-medium">Paso 1</p>
                    <p className="text-[10px] text-muted-foreground">Descargar y ejecutar</p>
                  </div>
                  <div className="rounded-lg border border-border/60 bg-muted/20 p-3 space-y-1.5">
                    <ExternalLink className="w-4 h-4 text-emerald-500" />
                    <p className="text-[11px] font-medium">Paso 2</p>
                    <p className="text-[10px] text-muted-foreground">Ir a chat.z.ai</p>
                  </div>
                  <div className="rounded-lg border border-border/60 bg-muted/20 p-3 space-y-1.5">
                    <MousePointerClick className="w-4 h-4 text-emerald-500" />
                    <p className="text-[11px] font-medium">Paso 3</p>
                    <p className="text-[10px] text-muted-foreground">Clic en favorito</p>
                  </div>
                </div>

                {/* Boton directo a chat.z.ai (por si el instalador no abrio el navegador) */}
                <div className="flex justify-center">
                  <a
                    href="https://chat.z.ai"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-emerald-500 transition-colors"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                    Abrir chat.z.ai manualmente
                  </a>
                </div>

                <Separator />

                {/* Troubleshooting colapsable */}
                <div>
                  <button
                    onClick={() => setShowTroubleshooting(!showTroubleshooting)}
                    className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {showTroubleshooting ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                    Solucion de problemas
                  </button>
                  {showTroubleshooting && (
                    <div className="mt-3 space-y-3 text-xs text-muted-foreground">
                      <Alert>
                        <AlertCircle className="h-4 w-4" />
                        <AlertTitle className="text-xs">Windows bloqueo el archivo</AlertTitle>
                        <AlertDescription className="text-xs">
                          Si Windows SmartScreen bloquea el .bat: clic en &laquo;Mas informacion&raquo; &rarr;
                          &laquo;Ejecutar de todos modos&raquo;. El instalador es seguro y transparente
                          (puedes revisar el codigo fuente).
                        </AlertDescription>
                      </Alert>
                      <Alert>
                        <AlertCircle className="h-4 w-4" />
                        <AlertTitle className="text-xs">El favorito no aparece</AlertTitle>
                        <AlertDescription className="text-xs">
                          Asegurate de que el navegador estaba completamente cerrado cuando se ejecuto
                          el instalador. Si usas Chrome Sync, el favorito puede tardar unos segundos en
                          aparecer. Cierra y reabre Chrome.
                        </AlertDescription>
                      </Alert>
                      <Alert>
                        <AlertCircle className="h-4 w-4" />
                        <AlertTitle className="text-xs">Al hacer clic en el favorito no pasa nada</AlertTitle>
                        <AlertDescription className="text-xs">
                          1. Verifica que estas en una URL <span className="font-mono">chat.z.ai/c/...</span>
                          <br />
                          2. Si Chrome bloquea la nueva pestana, mira la barra de direcciones: aparecera
                          un icono de bloqueo. Haz clic y permite pop-ups para chat.z.ai.
                          <br />
                          3. Si aparece &laquo;No estas autenticado&raquo;, inicia sesion en chat.z.ai primero.
                        </AlertDescription>
                      </Alert>
                    </div>
                  )}
                </div>

                <Separator />

                {/* Nota de seguridad */}
                <Alert>
                  <Lock className="h-4 w-4" />
                  <AlertTitle>Como funciona (y por que es seguro)</AlertTitle>
                  <AlertDescription className="space-y-1.5 text-xs">
                    <p>
                      El instalador edita el archivo <span className="font-mono">Bookmarks</span> de
                      Chrome/Edge (en <span className="font-mono">%LOCALAPPDATA%</span>) para agregar
                      un favorito con codigo JavaScript.
                    </p>
                    <p>
                      Cuando haces clic en el favorito desde chat.z.ai, el JavaScript se ejecuta
                      dentro de chat.z.ai (mismo origen), lee tu sesion via la API interna, y envia
                      el JWT al sandbox via form POST. El JWT no aparece en URLs ni logs.
                    </p>
                    <p>
                      El JWT se guarda en <span className="font-mono">~/.czai/credentials.json</span> y
                      no expira. Solo necesitas hacer esto una vez.
                    </p>
                  </AlertDescription>
                </Alert>
              </CardContent>
            </Card>
          </>
        )}
      </main>

      {/* Footer sticky */}
      <footer className="border-t border-border/60 bg-muted/20 mt-auto">
        <div className="container mx-auto max-w-4xl px-4 py-4 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-muted-foreground">
          <p>CZAI Bridge &middot; Contexto Z.ai v3.6</p>
          <p className="flex items-center gap-1.5">
            <ShieldCheck className="w-3 h-3 text-emerald-500" />
            JWT via form POST &middot; Instalador automatico
          </p>
        </div>
      </footer>

      <Toaster />
    </div>
  );
}
