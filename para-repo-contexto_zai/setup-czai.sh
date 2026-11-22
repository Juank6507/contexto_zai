#!/bin/bash
# setup-czai.sh — Provisiona el código CZAI en un sandbox nuevo de Z.ai
#
# Uso:
#   cd /home/z/my-project/contexto_zai && bash setup-czai.sh
#
# Qué hace:
#   1. Copia los endpoints CZAI a src/app/api/czai/
#   2. Copia las librerías CZAI a src/lib/czai/
#   3. Copia el componente CZAI a src/components/czai/
#   4. Reemplaza src/app/page.tsx con la página del bridge
#   5. Verifica que los endpoints responden
#
# Este script es idempotente: se puede ejecutar múltiples veces sin problema.
# No sobrescribe ~/.czai/credentials.json (el JWT se gestiona por separado).

set -euo pipefail

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Rutas
SANDBOX_ROOT="${SANDBOX_ROOT:-/home/z/my-project}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/sandbox-src"

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN} CZAI Setup — Provisionando sandbox${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# Verificar que el sandbox existe
if [ ! -d "$SANDBOX_ROOT/src" ]; then
    echo -e "${RED}ERROR: No se encontró $SANDBOX_ROOT/src${NC}"
    echo -e "${YELLOW}¿Estás ejecutando esto en un sandbox de Z.ai?${NC}"
    exit 1
fi

# Verificar que sandbox-src existe
if [ ! -d "$SRC_DIR" ]; then
    echo -e "${RED}ERROR: No se encontró $SRC_DIR${NC}"
    echo -e "${YELLOW}¿Clonaste el repo contexto_zai correctamente?${NC}"
    exit 1
fi

echo -e "${YELLOW}[1/6] Verificando estructura de origen...${NC}"
echo "  Origen: $SRC_DIR"
find "$SRC_DIR" -type f | while read -r f; do
    echo "  - ${f#$SRC_DIR/}"
done
echo ""

echo -e "${YELLOW}[2/6] Creando directorios en el sandbox...${NC}"
mkdir -p "$SANDBOX_ROOT/src/lib/czai"
mkdir -p "$SANDBOX_ROOT/src/components/czai"
mkdir -p "$SANDBOX_ROOT/src/app/api/czai/jwt-status"
mkdir -p "$SANDBOX_ROOT/src/app/api/czai/recibir-jwt"
mkdir -p "$SANDBOX_ROOT/src/app/api/czai/installer-bat"
mkdir -p "$SANDBOX_ROOT/src/app/api/czai/installer-ps1"
echo -e "  ${GREEN}Directorios creados.${NC}"
echo ""

echo -e "${YELLOW}[3/6] Copiando archivos fuente...${NC}"

# Librerías
cp "$SRC_DIR/lib/czai/bookmarklet.ts" "$SANDBOX_ROOT/src/lib/czai/"
cp "$SRC_DIR/lib/czai/installer.ts" "$SANDBOX_ROOT/src/lib/czai/"
echo -e "  ${GREEN}✓ lib/czai/bookmarklet.ts${NC}"
echo -e "  ${GREEN}✓ lib/czai/installer.ts${NC}"

# Componente
cp "$SRC_DIR/components/czai/czai-bridge.tsx" "$SANDBOX_ROOT/src/components/czai/"
echo -e "  ${GREEN}✓ components/czai/czai-bridge.tsx${NC}"

# Endpoints
cp "$SRC_DIR/api/czai/jwt-status/route.ts" "$SANDBOX_ROOT/src/app/api/czai/jwt-status/"
echo -e "  ${GREEN}✓ app/api/czai/jwt-status/route.ts${NC}"

cp "$SRC_DIR/api/czai/recibir-jwt/route.ts" "$SANDBOX_ROOT/src/app/api/czai/recibir-jwt/"
echo -e "  ${GREEN}✓ app/api/czai/recibir-jwt/route.ts${NC}"

cp "$SRC_DIR/api/czai/installer-bat/route.ts" "$SANDBOX_ROOT/src/app/api/czai/installer-bat/"
echo -e "  ${GREEN}✓ app/api/czai/installer-bat/route.ts${NC}"

cp "$SRC_DIR/api/czai/installer-ps1/route.ts" "$SANDBOX_ROOT/src/app/api/czai/installer-ps1/"
echo -e "  ${GREEN}✓ app/api/czai/installer-ps1/route.ts${NC}"

# Página principal
cp "$SRC_DIR/app-page.tsx" "$SANDBOX_ROOT/src/app/page.tsx"
echo -e "  ${GREEN}✓ app/page.tsx${NC}"

echo ""

# -- Copiar mini-servicios al workspace del sandbox --
# Los mini-servicios (jwt-bridge, task-bridge, pipeline-runner) son procesos
# Python que corren en background en el sandbox. Se copian del repo al
# workspace para que estén disponibles sin necesidad de clonar el repo.
# El patrón doble setsid (en _launch.sh) asegura que sobrevivan entre
# llamadas del Bash tool.
echo ""
echo -e "${YELLOW}[4/6] Copiando mini-servicios al workspace...${NC}"
mkdir -p "$SANDBOX_ROOT/mini-services/jwt-bridge"
mkdir -p "$SANDBOX_ROOT/mini-services/task-bridge"
mkdir -p "$SANDBOX_ROOT/mini-services/pipeline-runner"
cp "$SCRIPT_DIR/mini-services/_launch.sh" "$SANDBOX_ROOT/mini-services/"
cp "$SCRIPT_DIR/mini-services/jwt-bridge/index.py" "$SANDBOX_ROOT/mini-services/jwt-bridge/"
cp "$SCRIPT_DIR/mini-services/task-bridge/index.py" "$SANDBOX_ROOT/mini-services/task-bridge/"
cp "$SCRIPT_DIR/mini-services/pipeline-runner/runner.py" "$SANDBOX_ROOT/mini-services/pipeline-runner/"
cp "$SCRIPT_DIR/mini-services/pipeline-runner/launch.sh" "$SANDBOX_ROOT/mini-services/pipeline-runner/"
chmod +x "$SANDBOX_ROOT/mini-services/_launch.sh"
chmod +x "$SANDBOX_ROOT/mini-services/pipeline-runner/launch.sh"
echo -e "  ${GREEN}✓ mini-services/_launch.sh${NC}"
echo -e "  ${GREEN}✓ mini-services/jwt-bridge/index.py${NC}"
echo -e "  ${GREEN}✓ mini-services/task-bridge/index.py${NC}"
echo -e "  ${GREEN}✓ mini-services/pipeline-runner/runner.py${NC}"
echo -e "  ${GREEN}✓ mini-services/pipeline-runner/launch.sh${NC}"
echo ""

echo -e "${YELLOW}[5/6] Verificando que el dev server responde...${NC}"

# Esperar un momento a que Next.js recompile
sleep 3

# Verificar endpoints
MAX_WAIT=30
WAITED=0

check_endpoint() {
    local url="$1"
    local expected="$2"
    local desc="$3"

    WAITED=0
    while [ $WAITED -lt $MAX_WAIT ]; do
        CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:3000$url" 2>/dev/null || echo "000")
        if [ "$CODE" = "$expected" ]; then
            echo -e "  ${GREEN}✓ $desc → HTTP $CODE${NC}"
            return 0
        fi
        sleep 2
        WAITED=$((WAITED + 2))
    done
    echo -e "  ${RED}✗ $desc → HTTP $CODE (esperaba $expected)${NC}"
    return 1
}

check_endpoint "/" "200" "Página principal (GET /)"
check_endpoint "/api/czai/jwt-status" "200" "Endpoint JWT status"
echo ""

echo -e "${YELLOW}[6/6] Verificando estado del JWT...${NC}"
JWT_STATUS=$(curl -s http://localhost:3000/api/czai/jwt-status 2>/dev/null || echo '{"needs_jwt": true}')

if echo "$JWT_STATUS" | grep -q '"needs_jwt":false'; then
    EMAIL=$(echo "$JWT_STATUS" | grep -o '"email":"[^"]*"' | cut -d'"' -f4)
    echo -e "  ${GREEN}✓ JWT configurado${NC}"
    echo -e "  ${GREEN}  Email: $EMAIL${NC}"
    echo -e "  ${GREEN}  CZAI está listo para usar.${NC}"
else
    echo -e "  ${YELLOW}⚠ JWT no configurado en este sandbox${NC}"
    echo -e "  ${YELLOW}  El Director debe hacer clic en el favorito 'Conectar CZAI'${NC}"
    echo -e "  ${YELLOW}  desde chat.z.ai para enviar su JWT.${NC}"
fi

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN} CZAI Setup completado${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""
echo "Endpoints disponibles:"
echo "  GET  /                          — Página del bridge"
echo "  GET  /api/czai/jwt-status       — Estado del JWT"
echo "  POST /api/czai/recibir-jwt      — Recibir JWT (form POST o JSON)"
echo "  GET  /api/czai/installer-bat    — Descargar instalador .bat"
echo "  GET  /api/czai/installer-ps1    — Descargar instalador .ps1"
echo ""
echo "Mini-servicios disponibles:"
echo "  mini-services/_launch.sh        — Lanzar jwt-bridge + task-bridge"
echo "  mini-services/jwt-bridge/       — JwtBridgeServer (puerto 8086)"
echo "  mini-services/task-bridge/      — TaskBridgeServer (puerto 8087)"
echo "  mini-services/pipeline-runner/  — Lanzadera del pipeline"
echo ""
