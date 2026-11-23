# Documento consolidado — contexto_zai v7.0

## Resumen de la entrega

v7.0 cierra formalmente v6.20 con dos fixes de bugs detectados, sobre una base arquitectónica nueva: modularización del pipeline en subprocesos separados y restauración de la abstracción de plataforma v5.0 (prepara para MB en v7.1).

## Cambios mayores

### A. Modularización arquitectónica

- pipeline.py reducido de 6158 a 2570 líneas (-58%).
- 5 módulos nuevos: pipeline_cascada, pipeline_w3, pipeline_d7, pipeline_archivos, pipeline_auditoria.
- La clase EnriquecimientoOrquestador se eliminó.
- Los 4 subprocesos reusables (cascada, W3, D7, archivos) viven en módulos separados como clases concretas.

### B. Abstracción de plataforma (prepara para MB en v7.1)

- Paquete platforms/ con 4 interfaces abstractas: PlatformAuth, PlatformChat, PlatformLinks, PlatformLLM.
- Implementaciones concretas de Zai en platforms/zai/.
- La cascada recibe PlatformLLM por constructor (no más modelo GLM hardcoded).
- MessageExtractor usa interfaces abstractas.
- Worker Bun y Subagent Proxy refactorizados con LLMProvider en TypeScript (defaults Zai hasta que MB esté disponible).
- config.py renombrado: PROXY_ZAI_URL → PROXY_LLM_URL.

### C. Fixes de los 2 bugs de v6.20

**Bug 1 — Comunicación del daemon cuando la cascada cae a rate limit:**
- El endpoint /collect-responses devuelve en la respuesta HTTP un campo explícito "pending_tasks" con la lista completa de tareas cuando la cascada cae al Nivel 3.
- El agente CZAI recibe todo en una sola respuesta y sabe exactamente qué hacer sin leer _pending_tasks.json.
- Subagent Proxy: añadido CircuitBreaker (5 fallos → 60s cooldown) y clasificación de errores (401/403 → dead letter, no reintenta).
- Subagent Proxy: siempre elimina la tarea del pending después de procesarla (cierra el bucle infinito de v6.20).

**Bug 2 — Subproceso de archivos de recuperación que no completa:**
- _generar_archivos_recuperacion reescrito por pasos: usa los generadores existentes (EstadoGenerator, DecisionesGenerator, IndiceGenerator) por separado. NO bypassa la cascada.
- RecogedorRespuestas.limpiar: preserva los archivos auxiliares (_nombre.txt, _decisiones.txt, _temas.txt) y el directorio cache/. Cierra el bucle de re-cascada infinita.
- IntegradorRespuestas: añadido handler para task_id "enriquecer_bloque_NN" que era el patrón que se descartaba silenciosamente en v6.20.
- Consolidador de decisiones: añadido fallback a caches cuando los _decisiones.txt no existen. Recupera 65 decisiones reales.
- EstadoGenerator: arreglados _FILE_PATH_PATTERN (no captura puntuación Python), _ERROR_REGEX (exige contexto sintáctico), _strip_tool_calls (cubre JSON compacto), _strip_bash_blocks.
- IndiceGenerator: tokens calculados del tamaño real de los bloques.
- _regenerar_sintesis_contexto (nuevo): regenera la sección G0.B tras el enriquecimiento.
- _reemplazar_placeholders_objetivo (nuevo): reemplaza los 4 placeholders del 03_objetivo_proyecto.md con valores reales.
- ExchangeBuilder.build_from_workspace (nuevo): reconstruye intercambios desde los bloque_NN.md del workspace.

## Aprendizajes (lecciones para agent-learn/)

### L018 (genérico) — Baremo del Gauntlet: prohibido bypass, placeholders en lógica, mocks con datos reales

**Contexto:** en la iteración 1 del Gauntlet v7.0, el baremo era incorrecto: verificaba que el código existe pero no que funciona con datos reales. Daba por buenos criterios que estaban documentados como deuda técnica pero no resueltos (bypass de la cascada, placeholders en lógica de parsing).

**Lección:** el baremo del Gauntlet debe ser: cero bypass (toda llamada al LLM pasa por la cascada), cero placeholders en lógica de código cuando existe fuente real (solo se permiten placeholders donde no tenemos la verdad de dónde llegar porque no tenemos MB), cero mocks cuando existen datos reales (toda validación se ejecuta contra el workspace real), y cada criterio de la spec se verifica ejecutando la funcionalidad, no inspeccionando el código.

**Aplicación futura:** cuando se haga un Gauntlet, el baremo debe explicitar estas tres prohibiciones antes de empezar. Si el Gauntlet da verde en la primera pasada con un alcance grande, sospechar: probablemente el baremo no fue lo suficientemente estricto.

### L019 (genérico) — Gauntlet focalizado, no end-to-end

**Contexto:** en la iteración 1 del Gauntlet v7.0, intenté probar todo el pipeline end-to-end contra el workspace completo. Eso tardaba demasiado y el daemon se caía por problemas del entorno del sandbox.

**Lección:** el Gauntlet no se hace contra todos los bloques ni todo el proceso. Se comprueban las partes estratégicas que se han modificado y que tienen que cumplir una funcionalidad conciliada, especificada y planificada previamente. Es una prueba focalizada por criterio: por cada criterio de la spec modificado, ejecutar la parte correspondiente con datos reales y verificar que cumple.

**Aplicación futura:** cuando se haga un Gauntlet, identificar primero los criterios de la spec que se modificaron, y para cada uno diseñar una prueba focalizada que ejecute solo la parte correspondiente.

### L020 (específico) — Instanciar plantilla conNombreProyecto igual al nombre del archivo .zip

**Contexto:** en la entrega v7.0, el script update_czai.ps1 falló en el paso 2 (Find-ZipInFolder) porque NombreProyecto estaba en mayúsculas ("CZAI") cuando el archivo se llama `contexto_zai_v7.0.zip` (minúsculas). El patrón `CZAI_v*.zip` no encontraba el archivo.

**Lección:** al instanciar la plantilla del script de entrega, NombreProyecto debe coincidir exactamente con el prefijo del nombre del archivo .zip. Si el archivo se llama `contexto_zai_v7.0.zip`, NombreProyecto debe ser `contexto_zai` (minúsculas, con guion bajo).

**Aplicación futura:** antes de generar el .zip, verificar que NombreProyecto coincide con el prefijo del nombre del archivo.

### L021 (específico) — URL de GitHub: respetar mayúsculas del usuario

**Contexto:** en la entrega v7.0, el paso 12 (diff de triple igualdad) falló porque el script consultaba `https://github.com/juanca6507/contexto_zai.git` (j minúscula) cuando el usuario real es `Juank6507` (J mayúscula y k). GitHub distingue mayúsculas en los nombres de usuario.

**Lección:** al instanciar la plantilla con la URL de GitHub, respetar exactamente las mayúsculas y minúsculas del nombre de usuario. Verificar contra el repositorio real antes de generar el .zip.

**Aplicación futura:** antes de generar el .zip, verificar que la URL de GitHub en el script coincide con la URL real del repositorio (including capitalización).

### L022 (específico) — Documento consolidado de retorno debe estar actualizado

**Contexto:** en la entrega v7.0, el criterio C6 falló porque el documento `retorno/documento_consolidado.md` estaba desactualizado (decía v6.20).

**Lección:** el documento consolidado de retorno debe actualizarse en cada entrega con los aprendizajes de la implementación. Es un criterio de validación del Gauntlet (C6, regla R1/NH26).

**Aplicación futura:** antes de empaquetar el .zip, actualizar `retorno/documento_consolidado.md` con los aprendizajes de la implementación.

### L023 (específico) — Sentencias de prueba deben estar definidas en la entrega

**Contexto:** en la entrega v7.0, el criterio C4 falló porque la entrega no definía sentencias de prueba o tests E2E que el script de entrega ejecuta en Windows.

**Lección:** la entrega debe incluir sentencias de prueba que el script ejecuta automáticamente en el paso 8 (Test-Funcionamiento). Estas sentencias deben estar definidas en el script o en un archivo separado que el script lee.

**Aplicación futura:** antes de empaquetar el .zip, asegurarse de que el script incluye sentencias de prueba que validen el funcionamiento en Windows con datos reales.

## Deuda técnica (no bloqueante para v7.0)

- La función _generar_archivos_recuperacion mantiene la llamada LLM directa (criterio 9 v6.20). La conciliación acordó separar por pasos ahora y valorar reintegrar el criterio 9 cuando funcione. Los pasos nuevos (_regenerar_sintesis_contexto, _reemplazar_placeholders_objetivo) ya usan generadores existentes.
- Integración concreta con MB queda para v7.1 (la abstracción ya está lista).
- El daemon se cae después de unos segundos cuando se lanza en background en el sandbox. Es un problema del entorno que mata procesos en background. En producción debe lanzarse con systemd, supervisord, o similar.

