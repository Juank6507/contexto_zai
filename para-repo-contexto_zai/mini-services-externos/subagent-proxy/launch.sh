#!/bin/bash
# Lanzador que desvincula completamente el proceso
cd /home/z/my-project/mini-services/subagent-proxy
export CZAI_WORKSPACE_DIR=/home/z/my-project/contexto_recuperacion_v5
nohup setsid bun run start </dev/null >/tmp/proxy_v5.log 2>&1 &
disown $! 2>/dev/null || true
echo "Proxy lanzado, PID inicial: $!"
