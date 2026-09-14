#!/bin/bash
# /home/z/my-project/mini-services/pipeline-runner/launch.sh -- Lanzador del pipeline-runner con doble setsid.
#
# Lanza el pipeline.run() en background con el patrón doble setsid para que
# sobreviva entre llamadas del Bash tool. El pipeline puede encolar tareas de
# subagentes en TaskBridgeServer (8087); el agente principal debe hacer polling
# activo de /pending-tasks y ejecutarlas con el Task tool.
#
# USO:
#   nohup setsid bash /home/z/my-project/mini-services/pipeline-runner/launch.sh \
#     </dev/null >/home/z/my-project/mini-services/pipeline-runner/launch.log 2>&1 &
#   disown
#
# El proceso sobrevive entre llamadas del Bash tool. Para detenerlo:
#   pkill -f "pipeline-runner/runner.py"

set -e
cd /home/z/my-project

nohup setsid python3 /home/z/my-project/mini-services/pipeline-runner/runner.py \
  </dev/null >/home/z/my-project/mini-services/pipeline-runner/serve.log 2>&1 &
disown $! 2>/dev/null || true

sleep 2
echo "Pipeline runner lanzado."
pgrep -af "runner.py" || echo "(no encontrado)"
