# Documento consolidado de retorno — contexto_zai v6.19 (con F6)

**Fecha:** 2026-11-16
**Versión:** 6.19
**Proyecto:** contexto_zai
**Agente:** CZAI

---

## Aprendizajes genéricos (viajan a agent-learn/)

### A1 — Propagación de parámetros entre capas
Cuando se añade un parámetro nuevo a la entrada de un pipeline, hay que verificar que se propague por TODAS las capas intermedias hasta el generador final. **Criterio:** cualquier fix que añada un parámetro debe incluir tests de propagación capa por capa.

### A2 — Filtro de comentarios HTML multilínea en markdown
Usar `re.sub(r"<!--.*?-->", "", contenido, flags=re.DOTALL)` para eliminar bloques completos multilínea. **Criterio:** cualquier parser de markdown que filtre comentarios HTML debe usar el patrón `re.DOTALL`.

### A3 — Autonomía del agente frente al daemon
El agente CZAI debe ejecutar pending_tasks de Nivel 3 automáticamente cuando el daemon lo pide (status=waiting_for_agent), sin pedir permiso al Director. **Criterio:** cuando el proceso pide acción, el agente actúa. No esperar confirmación del Director para lo que el proceso ya autorizó.

## Anti-patrones específicos de v6.19

### AP19 — Parser que extrae rutas sin distinguir texto natural de bloques de código
**Fix:** encadenar `_strip_tool_calls` + `_strip_bash_blocks` antes del regex de detección.

### AP19-bis — Estructura del .zip con carpeta envolvente
El .zip debe tener los archivos en raíz, sin carpeta envolvente que duplique el nombre del repo local.

### AP19-ter — Sentencias de prueba con saltos de línea literales en cmd.exe
Las sentencias `python -c "..."` NO deben contener saltos de línea literales. Usar `chr(10)` u otras funciones.

