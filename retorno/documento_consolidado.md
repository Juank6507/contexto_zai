# Documento consolidado de retorno — contexto_zai v6.19

**Fecha:** 2026-11-15
**Versión:** 6.19
**Proyecto:** contexto_zai
**Agente:** CZAI

---

## Aprendizajes genéricos (viajan a agent-learn/)

### A1 — Propagación de parámetros entre capas
Cuando se añade un parámetro nuevo a la entrada de un pipeline (ej: `chat_id` en `ampliar_contexto()`), hay que verificar que se propague por TODAS las capas intermedias hasta el generador final. En v6.19, `chat_id` pasó por: `ampliar_contexto()` → `RecoveryCycle` → `RecoveryGenerator` → `EstadoGenerator`. Si una capa intermedia no lo propaga, el parámetro llega vacío al final. **Criterio:** cualquier fix que añada un parámetro debe incluir tests de propagación capa por capa.

### A2 — Filtro de comentarios HTML multilínea en markdown
El filtro de comentarios HTML `<!-- ... -->` en markdown debe usar `re.sub(r"<!--.*?-->", "", contenido, flags=re.DOTALL)` para eliminar bloques completos multilínea. Un filtro que solo elimina líneas que **empiezan** con `<!--` no cubre los comentarios multilínea donde las líneas intermedias no empiezan con `<!--`. **Criterio:** cualquier parser de markdown que filtre comentarios HTML debe usar el patrón `re.DOTALL`.

## Anti-patrones específicos de v6.19

### AP19 — Parser que extrae rutas sin distinguir texto natural de bloques de código
`EstadoGenerator._extraer_entregables()` aplicaba regex de detección de rutas sobre el contenido completo del mensaje del agente, sin distinguir si la ruta estaba en texto natural o dentro de un bloque ` ```bash ... ``` `. Esto generaba falsos entregables. **Fix:** encadenar `_strip_tool_calls` + `_strip_bash_blocks` antes del regex de detección. **Criterio:** cualquier parser que extraiga patrones del contenido del agente debe primero limpiar tool_calls y bloques de código.

### AP19-bis — Estructura del .zip con carpeta envolvente
El .zip de entrega debe contener los archivos DIRECTAMENTE en la raíz, no envueltos en una carpeta `contexto_zai/`. Cuando el Director descomprime el .zip en `C:\Python\Proyectos\contexto_zai` (que ya es el repo local), la estructura con carpeta envolvente crea doble nesting (`contexto_zai/contexto_zai/...`) y rompe todos los imports relativos. **Criterio:** el .zip debe tener los archivos en raíz, sin carpeta envolvente que duplique el nombre del repo local.

### AP19-ter — Sentencias de prueba con saltos de línea literales en cmd.exe
Las sentencias de prueba del `update_czai.ps1` que usan `python -c "..."` NO deben contener saltos de línea literales (`
` reales en el string), porque `cmd.exe /c` los interpreta como fin de comando y corta el código Python. Para incluir saltos de línea en un string Python dentro de `python -c`, usar `chr(10)` en vez de `
` literal. **Criterio:** cualquier sentencia de prueba con `python -c` que necesite strings multi-línea debe construirlos con `chr(10)` u otras funciones, no con literales.

