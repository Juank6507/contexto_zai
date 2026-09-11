#!/bin/bash
# /home/z/my-project/mini-services/_launch.sh -- Lanzador con doble setsid para procesos que sobreviven entre llamadas del Bash tool.
# Lanzador que desvincula completamente los procesos hijos del Bash tool.
#
# PATRÓN CRÍTICO (descubierto en Sesión 14):
# El Bash tool de Z.ai mata su process group al terminar. Un solo `nohup setsid`
# NO alcanza para que un proceso sobreviva entre llamadas del Bash tool.
# El patrón que SÍ funciona es el DOBLE setsid:
#   1. Este launcher se lanza con: nohup setsid bash _launch.sh </dev/null >log 2>&1 & disown
#   2. Dentro del launcher, cada proceso se lanza con: nohup setsid python3 ... </dev/null >log 2>&1 & disown
# Esto desvincula completamente el proceso del process group del Bash tool.
#
# Sin este patrón, los procesos mueren entre llamadas del Bash tool.
# Con este patrón, sobreviven indefinidamente hasta que se matan explícitamente
# o terminan su trabajo.

set -e
cd /home/z/my-project

# -- jwt-bridge (puerto 8086) --
# Se levanta solo cuando hace falta el JWT. Se cierra solo tras recibirlo.
nohup setsid python3 /home/z/my-project/mini-services/jwt-bridge/index.py \
  </dev/null >/home/z/my-project/mini-services/jwt-bridge/serve.log 2>&1 &
disown $! 2>/dev/null || true

# -- task-bridge (puerto 8087) --
# Puente entre el pipeline Python y el Task tool del agente. Debe estar activo
# mientras el pipeline corre y necesite lanzar subagentes.
nohup setsid python3 /home/z/my-project/mini-services/task-bridge/index.py \
  </dev/null >/home/z/my-project/mini-services/task-bridge/serve.log 2>&1 &
disown $! 2>/dev/null || true

# Pequeña espera para que arranquen
sleep 3

# Reportar PIDs
echo "Lanzados. Procesos index.py:"
pgrep -af "index.py" || echo "(ninguno)"
echo "Puertos:"
ss -tlnp 2>/dev/null | rg "8086|8087" || echo "(nada)"
