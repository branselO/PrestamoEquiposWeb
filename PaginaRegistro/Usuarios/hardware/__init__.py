"""Lector AS608 usado por registro, login y préstamos.

Los scripts de la carpeta siguen pudiendo ejecutarse solos. Django importa
este paquete y usa los mismos nombres de antes.
"""

from .hardware import (
    ESTADO_SENSOR,
    apagar_led_sensor,
    capturar_minucias_en_vivo,
    comparar_minucias_fast,
    deserializar_template,
    enroll_fingerprint_to_db,
    encontrar_puerto_arduino,
    get_sensor,
    serializar_template,
)

__all__ = [
    "ESTADO_SENSOR",
    "apagar_led_sensor",
    "capturar_minucias_en_vivo",
    "comparar_minucias_fast",
    "deserializar_template",
    "enroll_fingerprint_to_db",
    "encontrar_puerto_arduino",
    "get_sensor",
    "serializar_template",
]
