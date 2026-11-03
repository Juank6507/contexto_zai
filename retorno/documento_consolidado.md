# Documento consolidado de retorno — contexto_zai v6.12

## Lecciones aprendidas (propuesta para agent-learn/)

### L017 — El timeout fijo mató al Worker Bun; el monitoreo de progreso es la solución
- **Contexto:** v6.10 introdujo `timeout=5` sin autorización del Director; el Worker Bun no procesaba ni un bloque. v6.12 lo reemplazó con `ProgressMonitor` (monitoreo de progreso en intervalos progresivos).
- **Lección:** Un timeout fijo mata procesos legítimos que necesitan más tiempo. El monitoreo de progreso (contar resultados físicos en intervalos) es superior: adapta el tiempo al trabajo real.
- **Aplica cuando:** Diseño de cualquier mecanismo de espera sobre procesos externos.

### AP18 — Introducir cambios sin autorización del Director
- **Contexto:** El `timeout=5` fue introducido por el agente en v6.10 sin que el Director lo pidiera. Causó 2 versiones de bugs (v6.10 y v6.11) antes de ser detectado.
- **Lección:** NH8 (actuar sin autorización) no es solo "empezar a codear sin permiso". También es "añadir parámetros o comportamientos que el Director no pidió" dentro de una implementación autorizada. Cada parámetro que cambia el comportamiento del proceso debe ser conciliado en C.
- **Aplica cuando:** Implementación de cualquier cambio en parámetros de comportamiento.

## Antipatrones detectados

### AP19 — Leer la plantilla no es seguirla
- **Contexto:** El agente leyó la plantilla `plantilla_script_entrega_proyecto.ps1` pero al instanciarla cambió la interfaz de uso, omitió parámetros y no generó el manifiesto ni el documento consolidado de retorno.
- **Lección:** Una plantilla es un guardrail: se instancia sustituyendo marcadores, sin cambiar estructura, parámetros ni forma de uso. Leer la plantilla y no seguirla es lo mismo que no haberla leído.
- **Aplica cuando:** Instanciación de cualquier plantilla de la estrategia.

### AP20 — Empaquetar sin verificar importabilidad
- **Contexto:** v6.12 se empaquetó sin incluir `processing/message_extractor.py` en el `.zip`. El archivo existía en el clon y en v6.11, pero se omitió al construir el paquete. Las 3 sentencias de prueba (`ProgressMonitor`, `_enriquecer_con_proxy_apa`, `_bloque_esta_completo`) fallaron con `ModuleNotFoundError` porque `incremental_cycle.py` importa `MessageExtractor` de ese módulo.
- **Lección:** Antes de entregar un `.zip`, ejecutar las sentencias de prueba contra el contenido del paquete (no contra el clon). El clon tiene todos los archivos; el `.zip` puede omitirlos por error de empaquetado. La verificación debe ser contra el artefacto entregado, no contra la fuente.
- **Aplica cuando:** Cierre de cualquier entrega empaquetada (`.zip`).

### AP21 — La sentencia de entrega debe respetar el shell del Director
- **Contexto:** La sentencia PowerShell del `1-LEER-PRIMERO.txt` usaba `$z`, `$env:USERPROFILE` y `$env:TEMP` sin escapar dentro de un bloque `& { }` pasado a `powershell -Command`. Cuando el Director la pega en su consola PowerShell (no `cmd`), el shell exterior expande las variables antes de pasarlas al `powershell.exe` interior, produciendo `=Join-Path` (variable `$z` vacía).
- **Lección:** Toda sentencia diseñada para ser pegada en PowerShell debe escapar `$` con backtick (`` `$ ``) cuando la variable debe ser resuelta por el proceso interior, no por el shell que la pega.
- **Aplica cuando:** Redacción de cualquier sentencia de entrega para PowerShell.

### AP22 — El manifiesto debe listar rutas relativas a la raíz del .zip, no a la subcarpeta
- **Contexto:** v6.12 falló la verificación SHA256 del `update_czai.ps1` porque el manifiesto listaba rutas relativas a `para-repo-contexto_zai/` (ej: `generation/resumenes_generator.py`), pero el script busca los archivos con `Join-Path $zipRoot $rel`. Cuando el .zip tiene múltiples ítems raíz (1-LEER-PRIMERO.txt, update_czai.ps1, para-repo-contexto_zai/), `$zipRoot` queda como `$tempDir`, no como `para-repo-contexto_zai/`. El script buscaba `$tempDir\generation\...` y no encontraba nada — reportaba "FALTA" para todos los archivos (aunque solo mostraba los primeros 10).
- **Lección:** Las rutas del manifiesto deben ser relativas a la raíz del .zip (ej: `para-repo-contexto_zai/generation/resumenes_generator.py`), no relativas a la subcarpeta de contenido. El script hace `Join-Path $zipRoot $rel`, y `$zipRoot` puede ser `$tempDir` o `para-repo-contexto_zai/` según la cantidad de ítems raíz. Con el prefijo completo, ambos casos funcionan.
- **Aplica cuando:** Generación del manifiesto de cualquier entrega empaquetada que tenga archivos de soporte (script, README) junto a la subcarpeta de contenido.

### AP23 — Los tests que mockean parcialmente dejan dependencias ocultas
- **Contexto:** v6.12 falló la verificación del script de entrega porque `test_v62_worker_falla_parcialmente` y `test_v62_worker_timeout` mockeaban el Worker Bun (Nivel 1) pero no el proxy APA directo (Nivel 2). Los bloques de test eran < 100 chars, así que `_enriquecer_con_proxy_apa` emitía un `logger.warning(...)` a stderr sin realmente llamar al proxy. El test pasaba (30/30 assertions OK), pero el script de entrega hace `& cmd.exe /c $cmd 2>&1` en PowerShell, que captura stderr como excepción → "Test E2E 1 lanzo error".
- **Lección:** Cuando un test mockea una capa (Nivel 1) pero deja que la siguiente capa (Nivel 2) se ejecute realmente, el test depende implícitamente de que esa capa falle o tenga efectos secundarios controlables. El mock debe ser explícito para cada capa que el test no quiere ejercer. Además, los tests E2E que serán ejecutados por un script que captura stderr deben producir 0 líneas de stderr — cualquier `logger.warning` o `print` a stderr rompe el script.
- **Aplica cuando:** Diseño de tests que mockean parcialmente un pipeline multicapa, especialmente si serán ejecutados por scripts de verificación que capturan stderr.
