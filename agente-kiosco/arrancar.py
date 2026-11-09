#!/usr/bin/env python3
"""Arranca el agente del lector en esta computadora.

Funciona:
- dentro del zip instalado en el kiosco (Usuarios/ al lado de este archivo)
- desde el repo, usando PaginaRegistro sin instalar Django
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def _raiz_python() -> Path:
    aqui = Path(__file__).resolve().parent
    if (aqui / "Usuarios" / "hardware" / "agente.py").is_file():
        return aqui
    pagina = aqui.parent / "PaginaRegistro"
    if (pagina / "Usuarios" / "hardware" / "agente.py").is_file():
        return pagina
    raise SystemExit(
        "No encontré Usuarios.hardware.agente. "
        "Corre empaquetar.py o ejecuta esto desde agente-kiosco/ del repo."
    )


def main() -> int:
    raiz = _raiz_python()
    texto = str(raiz)
    if texto not in sys.path:
        sys.path.insert(0, texto)
    runpy.run_module("Usuarios.hardware.agente", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
