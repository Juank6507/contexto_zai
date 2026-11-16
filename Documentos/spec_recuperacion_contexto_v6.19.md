# contexto_zai/Documentos/spec_recuperacion_contexto_v6.19.md
# Spec v6.19 — Fixes de los 8 problemas de v6.18 detectados en la F6 sobre exchanges_czai_consolidados.md

**Versión:** 6.19
**Fecha:** 2026-11-15
**Estado:** Implementada (Gauntlet NH27 verde).
**Especifica continuación de:** spec v6.18.
**Sesión origen:** CZAI 6a00fcb8, elemento C del método DCEPI conciliado.

---

## 1. Propósito

Corregir los 8 problemas detectados tras la F6 de v6.18 sobre `exchanges_czai_consolidados.md`. Los 8 problemas se agrupan en 4 categorías:

1. **Identidad del workspace (P1, P5, P4):** `00_estado_actual.md`, `_metadata.json` y `03_objetivo_proyecto.md` no reflejan correctamente el chat_id del chat actual ni el objetivo del proyecto desde el worklog canónico.
2. **Parser de A2 (P2):** la sección A2 de `00_estado_actual.md` extrae rutas dentro de bloques de código bash como si fueran entregables.
3. **Marcar errores históricos (P3, P8):** la sección A3 y los RESUMENES que mencionan «proxy APA» deben marcarse como contenido histórico, no actual.
4. **Bloques residuales (P6, P7):** el `bloque_23` con cabecera «Bloque externo» no proviene del documento fuente actual. RecoveryCycle no limpia bloques de ejecuciones anteriores antes de generar los nuevos.

## 2. Orden del proceso (19 pasos, sin cambios)

v6.19 no cambia el orden de los 19 pasos del pipeline. Solo corrige la implementación de los pasos P14 (enriquecimiento, generación del `03_objetivo_proyecto.md`) y P16 (auditoría final).

## 3. Decisiones conciliadas

### 1. chat_id siempre del chat actual (P1, P5)

`RecoveryCycle` y `ampliar_contexto` usan siempre el `chat_id` del chat actual donde corre el agente, sin importar si la fuente es un chat vivo de Z.ai o un archivo externo. La cabecera de `00_estado_actual.md` y los campos `chat_id` y `share_id` de `_metadata.json` muestran ese `chat_id`.

**Implementación:**
- `ampliar_contexto()` recibe `chat_id` como parámetro.
- El daemon `pipeline-daemon/index.py` lo pasa desde los metadatos del gateway IM.
- `RecoveryCycle` propaga el `chat_id` a `RecoveryGenerator` y `EstadoGenerator`.
- `EstadoGenerator.generate()` usa `chat_id` en la cabecera si está disponible, sino `chat_label`.
- `_metadata.json` se escribe con `chat_id` del chat actual en ambos flujos (cronológico y arbitrario).

### 2. Parser A2/A3 omite bloques bash (P2)

`EstadoGenerator._build_a2()` y `_build_a3()` no parsean rutas dentro de bloques de código bash. El contenido entre ` ```bash ` y ` ``` ` se omite completamente para la extracción de entregables y errores. Las rutas mencionadas en texto natural del agente (fuera de bloques de código) sí se extraen.

**Implementación:** nuevo método `_strip_bash_blocks(content)` en `EstadoGenerator`. Aplicado en `_build_a2` y `_build_a3` antes del regex de detección de rutas/errores, encadenado con `_strip_tool_calls` existente.

### 3. Marcar errores como históricos (P3, P8)

`EstadoGenerator._build_a3()` marca cada error detectado con la fecha del exchange donde aparece, indicando si es histórico (más de 7 días previos a la fecha actual del workspace) o actual. Los RESUMENES generados por la cascada W1-W4 preservan el contenido histórico del bloque tal cual.

**Implementación:** nuevo método `_obtener_timestamp_workspace()` en `EstadoGenerator`. Lee `_metadata.json["ultimo_timestamp"]`. Cada error se anota con `[histórico YYYY-MM-DD]` si su antigüedad > 7 días.

### 4. `_asegurar_objetivo_proyecto()` lee el worklog canónico (P4)

`_asegurar_objetivo_proyecto()` cambia su fuente: en vez de leer `estrategia/agent-context/proyecto.md`, lee el worklog canónico del proyecto (`/home/z/my-project/worklog.md`). La estructura del `03_objetivo_proyecto.md` se mantiene en 4 secciones: G0.A (quién eres), G0.B (norte del proyecto), G0.C (qué te pasó y cómo recuperarte, con acta de nacimiento como placeholder que el agente rellena desde el contexto), título.

**Implementación:** nuevo método `_extraer_objetivo_de_worklog(project_root)` en `EstadoGenerator`. Parsea la cabecera del worklog para obtener agente y proyecto. Genera las 4 secciones con placeholders `__MODELO_AGENTE__`, `__ACTA_NACIMIENTO__`, `__DIRECTOR__`, `__EMAIL__`. Métodos auxiliares `_extraer_sesiones_worklog` y `_extraer_evolucion_worklog` extraen las primeras N sesiones del worklog. El archivo se genera **una sola vez**.

### 5. Hash SHA256 para detectar fuente cambiada (P6, P7)

Antes de generar bloques nuevos, `ampliar_contexto` compara el hash SHA256 del documento fuente actual con el hash almacenado en `_metadata.json["source_sha256"]`. Si difieren (o si no hay hash, primera corrida), se eliminan todos los bloques existentes (`bloque_*.md`) antes de regenerar. Si coinciden, no se eliminan (es una re-corrida del mismo documento, preserva el trabajo ya hecho y permite al bucle D7 re-procesar lo incompleto).

**Implementación:** en `ampliar_contexto`, antes de llamar a `RecoveryCycle`, se calcula `sha256(content_bytes)`. Se lee `source_sha256` de `_metadata.json`. Si difieren, se eliminan los `bloque_*.md`. Tras generar los bloques nuevos, se escribe el hash actual en `_metadata.json["source_sha256"]`.

## 4. Baremo táctico — Criterios de aceptación (5)

1. La cabecera de `00_estado_actual.md` muestra el `chat_id` del chat actual, no el nombre del archivo fuente.
2. `_metadata.json` tiene `chat_id` poblado con el chat_id del chat actual.
3. La sección A2 de `00_estado_actual.md` no contiene rutas extraídas de bloques bash (verificable: el contenido entre ` ```bash ` y ` ``` ` no aparece en A2 como entregables).
4. El `03_objetivo_proyecto.md` generado tiene las 4 secciones (G0.A, G0.B, G0.C, título) y NO contiene comentarios HTML. El modelo del agente y el acta de nacimiento son placeholders que el agente rellena.
5. Al cambiar el documento fuente (hash SHA256 distinto), todos los `bloque_*.md` existentes se eliminan antes de regenerar. Al re-correr el mismo documento (hash igual), los bloques existentes se preservan.

## 5. Estado

Implementado en elemento I (Implementación) el 15 nov 2026. Gauntlet determinista + Gauntlet de terminación NH27 verificados VERDE. Lista para empaquetado I.3.a.

---

**Fin de la spec v6.19.**
