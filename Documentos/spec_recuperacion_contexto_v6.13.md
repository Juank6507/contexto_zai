# contexto_zai/Documentos/spec_recuperacion_contexto_v6.13.md
# Spec v6.13 — Corrección de 21 problemas detectados tras v6.12

**Versión:** 6.13
**Fecha:** 2026-11-06
**Estado:** Pendiente de implementación.
**Especifica continuación de:** spec v6.12.

---

## 1. Propósito

Corregir 21 problemas detectados en v6.12, siguiendo las decisiones conciliadas en C y aclaradas en E.

---

## 2. Orden del proceso (18 pasos, corregido tras revisión de estrategia)

1. Cargar JWT del CredentialManager
2. **Auditoría integral** al arrancar (AuditorWorkspace: buscar contexto_recuperacion, auditar bloques + enriquecimiento + metadata)
3. Decidir recovery vs incremental según auditoría
4. Extraer mensajes (árbol + batch paginado)
5. Construir intercambios (ExchangeBuilder)
6. **Clasificar por tema** (MessageClassifier — necesario para indexación: tema_a_archivo, query_context, índice, estado_actual)
7. Empaquetar bloques cronológicos descendentes (BlockPacker: ordena por timestamp descendente, cada intercambio conserva su tema)
8. Escribir bloques físicos (BloqueGenerator: cabecera `# Bloque cronológico N`, lista temas del bloque)
9. Generar 00_estado_actual.md (EstadoGenerator)
10. Generar 01_indice_recuperacion.md (IndiceGenerator)
11. Generar 02_decisiones_clave.md (DecisionesGenerator)
12. Generar 03_objetivo_proyecto.md
13. Escribir _metadata.json (con tema_a_archivo)
14. Enriquecimiento (cascada W1+W2+W3: ProgressMonitor — Worker Bun → proxy Z.ai → subagentes, nunca se detiene)
15. Sincronizar _processed_blocks.json (AuditorWorkspace)
16. **Auditoría final** (AuditorWorkspace — reutiliza la misma clase del paso 2)
17. Consolidar decisiones LLM
18. Regenerar índice tras enriquecimiento

---

## 3. Decisiones conciliadas por categoría

### Categoría 1 — Diseño del proceso (6 problemas)

| # | Problema | Decisión |
|---|---|---|
| 1+1 | Bloques ordenados alfabéticamente | BlockPacker: bloques cronológicos descendentes (bloque_01 = más nuevo). Cabecera `# Bloque cronológico N`. Sin agrupación temática (pero clasificación por tema se mantiene para indexación) |
| 2 | PROGRESS_GROWTH=1.5 inventado | 20s + exponencial (factor 2.0: 2+4+8+16+32+64). Ligado a P5 |
| 3 | _processed_blocks.json inconsistente | AuditorWorkspace.sincronizar_registro(): revisar físico vs registro, carencias a pending_tasks |
| 4 | IncrementalCycle no preserva contexto | Auditoría integral al arrancar (paso 2): buscar contexto_recuperacion, auditar bloques + enriquecimiento + metadata. No confiar solo en metadata |
| 5 | Nivel 2 frágil + falta clase orquestadora | ProgressMonitor orquesta toda la cascada. Nunca se detiene. Si Worker Bun falla → proxy inmediatamente. Si proxy falla → subagentes. Renombrado proxy APA → proxy Z.ai. W1+W2+W3 en 1 llamada. Lotes de 5. MAX_ITER=5 |

### Categoría 2 — Calidad del contexto (5 problemas)

| # | Problema | Decisión |
|---|---|---|
| 6 | 85 bloques sin RESUMEN | Efecto cascada de P5 (la cascada nunca se detiene) |
| 7+8 | RESUMENES que no cumplen + bloque_20 | W3 valida rango (600-900, 4 oraciones, sin etiquetas). Si no cumple: >2000 chars contenido = mejorable → pending_task. ≤2000 = aceptado con observaciones. MAX_ITER=5. Procedimiento ajeno al ejecutor |
| 9 | 4 bloques pisados | Opción A: no hacer nada (contenido legítimo del chat) |
| 10 | 2 bloques sin 3 archivos | Fusión W1+W2+W3: los 4 artefactos se escriben juntos en 1 llamada |

### Categoría 3 — Entrega (5 problemas)

| # | Problema | Decisión |
|---|---|---|
| 11+12 | .zip sin Documentos, sandbox-src, scripts, mini-services | .zip siempre incluye todo el contenido del proyecto |
| 13 | update_czai.ps1 no respeta plantilla | Instanciar desde plantilla v1.5.4 + 12 pasos del Director |
| 14+15 | Specs/planes inexistentes o borrados | Ya corregidos (restaurados en sesión 13) |

### Categoría 4 — Verificación (3 problemas)

| # | Problema | Decisión |
|---|---|---|
| 16 | Gauntlet con mocks | Gauntlet 7 pasos con datos reales: (1) inicio, (2) auditoría existentes, (3) 1er bloque, (4) 5 próximos, (5) 5 últimos, (6) auditoría cierre, (7) ficheros 00-03 |
| 17+18 | Baremo táctico no derivado | A+C: ampliar dcepi.md §8 + sección obligatoria en cada spec |

### Categoría 5 — Memoria (2 problemas)

| # | Problema | Decisión |
|---|---|---|
| 19 | Contexto perdido | Resuelto por P4 (auditoría integral al arrancar) |
| 20 | Workspace no restaurado | Tras Gauntlet: crear contexto desde exchanges_czai_consolidados.md + actualizar del chat |

---

## 4. Baremo táctico derivado del estratégico

### Gauntlet (7 pasos con datos reales)

| Paso | Verificación | Umbral |
|---|---|---|
| 1 | Inicio: proceso arranca sobre workspace | workspace con bloques + metadata |
| 2 | Auditoría de bloques existentes | AuditorWorkspace.auditar_completitud() |
| 3 | 1er bloque (más actual) | bloque_01 = max(timestamp) |
| 4 | 5 próximos bloques | orden descendente verificado |
| 5 | 5 últimos bloques | bloques más viejos verificados |
| 6 | Auditoría de cierre | _processed_blocks.json sincronizado |
| 7 | Ficheros 00-03 | 4 archivos generados por el proceso |

### Criterios de aceptación (16)

1. BlockPacker genera bloques cronológicos descendentes. Cabecera `# Bloque cronológico N`.
2. PROGRESS_GROWTH=2.0.
3. _processed_blocks.json coincide con estado físico.
4. Auditoría integral al arrancar (AuditorWorkspace integrado en Orchestrator.activate()).
5. ProgressMonitor orquesta cascada. Nunca se detiene.
6. Proxy Z.ai pasa headers X-Ratelimit-*.
7. Cascada nunca se detiene (no hay pausa de 10 min).
8. W1+W2+W3 fusionados en 1 llamada.
9. Lotes de 5 en paralelo.
10. Validación ajena al ejecutor (W3). MAX_ITER=5.
11. 0 menciones "proxy APA".
12. .zip incluye todo el contenido.
13. update_czai.ps1 respeta plantilla v1.5.4.
14. Gauntlet 7 pasos pasa 100% con datos reales.
15. Ficheros 00-03 generados por el proceso.
16. Contexto reconstruido desde exchanges_czai_consolidados.md.

---

**Fin de la spec v6.13.**
