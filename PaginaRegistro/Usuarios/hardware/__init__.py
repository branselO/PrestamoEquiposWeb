"""Lector AS608 usado por registro, login y préstamos.

Los scripts de la carpeta siguen pudiendo ejecutarse solos. Django importa
este paquete y usa los mismos nombres de antes. El zip del kiosco copia este
paquete sin biometria_cache.py.
"""

from .contrato import VERSION_AGENTE, VERSION_CONTRATO
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
    minucias_desde_texto,
    png_data_url,
    publicar_estado,
    serializar_template,
)

__all__ = [
    "TOMA_TOTAL",
    "VERSION_AGENTE",
    "VERSION_CONTRATO",
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
    "minucias_desde_texto",
    "png_data_url",
    "publicar_estado",
    "serializar_template",
]
