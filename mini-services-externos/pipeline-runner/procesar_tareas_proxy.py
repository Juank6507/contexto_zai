#!/usr/bin/env python3
"""Procesa todas las tareas pendientes via proxy APA con manejo de rate limit."""
import sys, json, os, time, urllib.request

PROXY_URL = "http://localhost:3000/api/zai-proxy/v1/chat/completions"
WS = "/home/z/my-project/contexto_recuperacion"
PENDING = f"{WS}/_pending_tasks.json"
RESPONSES = f"{WS}/_responses"

os.makedirs(RESPONSES, exist_ok=True)

with open(PENDING) as f:
    data = json.load(f)
tasks = data.get('tasks', [])

# Filtrar las que ya están procesadas
pendientes = []
for t in tasks:
    resp_path = f"{RESPONSES}/{t['task_id']}.txt"
    if not os.path.exists(resp_path):
        pendientes.append(t)

print(f"Procesando {len(pendientes)} tareas (delay 5s, retry 3x)...", flush=True)

processed = 0
failed = 0
for i, task in enumerate(pendientes):
    task_id = task['task_id']
    prompt = task['prompt']
    if len(prompt) > 12000:
        prompt = prompt[:6000] + "\n\n...(truncado)...\n\n" + prompt[-6000:]
    body = json.dumps({
        "model": "glm-4-plus",
        "messages": [
            {"role": "system", "content": "Eres un subagente del sistema contexto_zai."},
            {"role": "user", "content": prompt}
        ]
    }).encode('utf-8')

    success = False
    for attempt in range(3):
        try:
            req = urllib.request.Request(PROXY_URL, data=body, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                content = result['choices'][0]['message']['content']
                with open(f"{RESPONSES}/{task_id}.txt", 'w', encoding='utf-8') as f:
                    f.write(content)
                success = True
                processed += 1
                break
        except Exception as e:
            err_msg = str(e)
            if '429' in err_msg:
                print(f"  429 attempt {attempt+1}/3 for {task_id[:60]}", flush=True)
                time.sleep(30)
            else:
                print(f"  ERR attempt {attempt+1}/3 for {task_id[:60]}: {err_msg[:80]}", flush=True)
                time.sleep(5)

    if not success:
        failed += 1
        print(f"  FAILED {task_id}", flush=True)

    if (i+1) % 10 == 0:
        print(f"  [{i+1}/{len(pendientes)}] processed={processed}, failed={failed}", flush=True)
    time.sleep(5)

print(f"\n=== DONE: {processed} processed, {failed} failed ===", flush=True)
