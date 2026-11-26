"""Contrato estable entre el agente del kiosco y la página web.

El navegador del kiosco habla con 127.0.0.1. Django identifica o guarda.
Si cambias rutas, campos JSON o el empaquetado de minucias, sube
VERSION_CONTRATO y actualiza CONTRATO.md en agente-kiosco.
"""

from __future__ import annotations

# Versión del proceso instalado en cada kiosco (aparece en /estado y en el zip).
# 1.3.0 acepta POST /cancelar para soltar el lector si la página aborta.
VERSION_AGENTE = "1.3.0"

# Compatibilidad agente ↔ página. Sube solo cuando el intercambio deja de ser
# compatible con un kiosco antiguo.
VERSION_CONTRATO = 2

RUTAS = ("/estado", "/capturar", "/toma", "/cancelar")
HOST_LOCAL = "127.0.0.1"
PUERTO_DEFAULT = 8766
