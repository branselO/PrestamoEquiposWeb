"""Lector AS608 usado por registro, login y préstamos.

Los scripts de la carpeta siguen pudiendo ejecutarse solos. Django importa
este paquete y usa los mismos nombres de antes.
"""

from .hardware import (
    TOMA_TOTAL,
    apagar_led_sensor,
    capturar_minucias_en_vivo,
    capturar_toma_para_pantalla,
    comparar_minucias_fast,
    deserializar_template,
    enroll_fingerprint_to_db,
    encontrar_puerto_arduino,
    estado_sensor,
    fusionar_plantilla,
    get_sensor,
    png_data_url,
    publicar_estado,
    serializar_template,
)

__all__ = [
    "TOMA_TOTAL",
    "apagar_led_sensor",
    "capturar_minucias_en_vivo",
    "capturar_toma_para_pantalla",
    "comparar_minucias_fast",
    "deserializar_template",
    "enroll_fingerprint_to_db",
    "encontrar_puerto_arduino",
    "estado_sensor",
    "fusionar_plantilla",
    "get_sensor",
    "png_data_url",
    "publicar_estado",
    "serializar_template",
]
