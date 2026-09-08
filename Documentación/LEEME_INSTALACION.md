# INSTALACIÓN DEL PROYECTO CONTEXTO Z.AI v3.4

## Cómo descomprimir en tu Windows

1. **Descomprime el ZIP** `contexto_zai_completo.zip` en tu carpeta de proyectos:
   ```
   C:\Python\Proyectos\
   ```
   Esto creará:
   ```
   C:\Python\Proyectos\contexto_zai\          ← paquete Python
   C:\Python\Proyectos\tests\                 ← tests actualizados
   C:\Python\Proyectos\download\               ← spec y plan v3.4
   ```

2. **Si ya tenías el proyecto antes**, sustituye las carpetas existentes:
   - Borra `C:\Python\Proyectos\contexto_zai\` viejo (o renómbralo a `contexto_zai_old/`)
   - Copia la carpeta `contexto_zai/` nueva del ZIP
   - Igual con `tests/`

3. **Verifica que todo funciona** ejecutando desde la terminal:
   ```powershell
   cd C:\Python\Proyectos\
   python tests\run_all_tests.py
   ```
   Debes ver:
   ```
   RESULTADO FINAL
     Total tests ejecutados: 37
     Pasaron: 37
     Fallaron: 0
   ```

## Estructura del paquete

```
contexto_zai/                      ← paquete Python completo (v3.4)
├── __init__.py                    ← inicializador del paquete
├── config.py                      ← constantes y configuración
├── models.py                      ← modelos Pydantic
├── pipeline.py                    ← entry point con run(), export_context(), import_context()
├── Documentación/                 ← specs y planes de versiones anteriores
├── client/                        ← cliente Z.ai (auth, browser, chat, web_reader)
│   ├── auth_client.py
│   ├── browser_session.py
│   ├── chat_client.py
│   └── web_reader.py              ← NUEVO v3.4: lee links externos
├── context/                       ← NUEVO v3.4: exportación/importación
│   ├── exporter.py
│   └── importer.py
├── detection/                     ← detección de pérdida de contexto
│   ├── lexic_trigger.py
│   ├── token_counter.py
│   └── self_questions.py
├── generation/                    ← generadores de archivos de recuperación
│   ├── estado_generator.py       ← MODIFICADO v3.4: truncamiento lógico
│   ├── indice_generator.py
│   ├── decisiones_generator.py
│   ├── bloque_generator.py
│   └── recovery_generator.py
├── metadata/                      ← gestión de _metadata.json
│   └── manager.py
├── process/                       ← orquestadores
│   ├── orchestrator.py
│   ├── recovery_cycle.py         ← MODIFICADO v3.4: Capa 3 integrada
│   └── incremental_cycle.py
├── processing/                    ← procesamiento de intercambios
│   ├── exchange_builder.py       ← MODIFICADO v3.4: detecta links externos
│   ├── classifier.py              ← MODIFICADO v3.4: Capa 2 de intención
│   ├── intention_classifier.py   ← NUEVO v3.4: clasifica por intención
│   ├── content_cleaner.py
│   ├── block_packer.py
│   ├── subdivider.py
│   ├── code_detector.py
│   ├── version_graph.py
│   └── decision_extractor.py
├── subagents/                     ← subagentes efímeros
│   ├── launcher.py
│   ├── estado_subagent.py
│   ├── barrido_subagent.py
│   ├── decisiones_subagent.py
│   ├── mantenimiento_subagent.py
│   └── discriminator_subagent.py ← NUEVO v3.4: subdivide temas grandes (Capa 3)
└── verification/                  ← verificación de límites
    └── verifier.py

tests/                             ← tests del proyecto
├── run_all_tests.py               ← MODIFICADO: incluye 5 módulos v3.4
├── test_e2e_pipeline.py           ← MODIFICADO: 4 tests E2E nuevos v3.4
├── test_classifier_packer_subdivider.py
├── test_estado_indice_generation.py
├── test_recovery_cycle.py
├── test_code_detector.py
├── test_subagent_lifecycle.py
└── test_version_graph.py
```

## Qué cambia respecto a v3.3

1. **Fix 1 — Links externos:** Si el Director pasa un link en el chat, el proceso lo detecta, lo descarga y lo mete en un bloque temático como un intercambio más.

2. **Fix 2 — Clasificación por capas:**
   - Capa 1: léxica (keywords) — igual que antes
   - Capa 2: intención (aprobación, rechazo, handoff, etc.) — NUEVO
   - Capa 3: subagente discriminador que subdivide temas grandes en subtemas específicos — NUEVO

3. **Fix 3 — Estado con truncamiento lógico:** En vez de cortar el estado actual con "(truncado por límite de espacio)", resume la parte excluida y la añade al final en una sección "Resumen del contexto excluido".

4. **Fix 4 — Exportación/importación:** Puedes empaquetar el contexto del proyecto en un `.zip` y cargarlo en otro agente CZAI sin perder memoria de lo conversado.

## Cómo usar las nuevas funciones

```python
# Activar recuperación de contexto (igual que antes)
from contexto_zai.pipeline import run
result = run(chat_id="...", jwt="...")

# Exportar contexto a .zip (handoff entre agentes)
from contexto_zai.pipeline import export_context
zip_path = export_context(chat_id="abc-123")

# Importar contexto desde .zip
from contexto_zai.pipeline import import_context, find_context_packages
packages = find_context_packages()  # busca en download/
if packages:
    instrucciones = import_context(zip_path=packages[0])
    print("Contexto cargado. Instrucciones:")
    print(instrucciones)
```

## Requisitos

- Python 3.11 o superior
- Dependencias: `pydantic` (>=2.0), `httpx`, `beautifulsoup4`
  ```
  pip install pydantic httpx beautifulsoup4
  ```

## Si algo falla

Ejecuta cualquier módulo directamente para ver sus auto-tests:
```powershell
cd C:\Python\Proyectos\
python contexto_zai\subagents\discriminator_subagent.py
python contexto_zai\client\web_reader.py
python contexto_zai\processing\intention_classifier.py
python contexto_zai\context\exporter.py
python contexto_zai\context\importer.py
```

Cada uno debe mostrar `[PASS] xxx.py: todos los tests pasaron` sin errores de importación.
