# tests/verify_delivery_completeness.py
# Ubicacion: contexto_zai/tests/verify_delivery_completeness.py
# E6 fix: verifica completitud de entrega por inventario recursivo de carpetas (L021 v1.8)
# NO asume diff cero — hace diff real entre repo y zip descomprimido.

"""Verifica que un zip de entrega contiene TODAS las carpetas y archivos del repo.

Uso:
    python3 verify_delivery_completeness.py <repo_dir> <zip_file>

Exit 0 si el zip es completo (todas las carpetas del repo presentes en el zip).
Exit 1 si faltan carpetas o archivos.

Criterio L021 (estrategia v1.8): la completitud de una entrega se comprueba
por inventario recursivo de carpetas, no por asunción de diff cero.
"""
import sys
import zipfile
from pathlib import Path


def verify_completeness(repo_dir: str, zip_file: str) -> tuple[bool, list[str]]:
    repo = Path(repo_dir)
    zf = zipfile.ZipFile(zip_file)
    zip_names = set(zf.namelist())
    missing = []

    for path in sorted(repo.rglob("*")):
        if path.is_dir():
            continue
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.suffix == ".pyc":
            continue
        rel = str(path.relative_to(repo))
        if rel not in zip_names:
            missing.append(rel)

    return (len(missing) == 0, missing)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: python3 verify_delivery_completeness.py <repo_dir> <zip_file>")
        sys.exit(2)
    ok, missing = verify_completeness(sys.argv[1], sys.argv[2])
    if ok:
        print(f"OK: zip completo — todas las carpetas y archivos del repo presentes")
        sys.exit(0)
    else:
        print(f"FALLO: {len(missing)} archivos/carpetas faltantes en el zip:")
        for m in missing[:20]:
            print(f"  - {m}")
        if len(missing) > 20:
            print(f"  ... y {len(missing)-20} más")
        sys.exit(1)
