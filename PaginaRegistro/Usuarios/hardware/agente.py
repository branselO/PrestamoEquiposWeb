"""Agente del lector, uno por kiosco.

Lee el AS608 de esta computadora y devuelve las minucias. Django, en el
servidor, identifica o guarda. No abre el puerto serie.

Desde la carpeta PaginaRegistro:

    python -m Usuarios.hardware.agente

Escucha solo en 127.0.0.1. El puerto sale de HUELLA_AGENTE_PUERTO (8766).
HUELLA_PUERTO y HUELLA_BAUD siguen forzando el adaptador, igual que antes.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

try:
    from .hardware import (
        apagar_led_sensor,
        capturar_minucias_en_vivo,
        capturar_toma_para_pantalla,
        estado_sensor,
        get_sensor,
        minucias_desde_texto,
        png_data_url,
        publicar_estado,
        serializar_template,
    )
except ImportError:
    from hardware import (
        apagar_led_sensor,
        capturar_minucias_en_vivo,
        capturar_toma_para_pantalla,
        estado_sensor,
        get_sensor,
        minucias_desde_texto,
        png_data_url,
        publicar_estado,
        serializar_template,
    )

import base64

_candado = threading.Lock()
_OCUPADO = "El lector está ocupado. Espera a que termine la lectura en curso."


def _minucias_b64(matriz) -> str:
    return base64.b64encode(serializar_template(matriz)).decode("ascii")


def _con_lector(operacion):
    if not _candado.acquire(blocking=False):
        return 409, {"ok": False, "mensaje": _OCUPADO}
    sensor = uart = None
    try:
        publicar_estado("Buscando el lector USB. En cuanto esté listo, apoya el centro del dedo.")
        sensor, uart = get_sensor()
        return operacion(sensor)
    except (OSError, RuntimeError) as error:
        publicar_estado("No se pudo usar el lector. Revisa el USB y vuelve a intentar.")
        return 400, {"ok": False, "mensaje": str(error)}
    finally:
        if sensor:
            apagar_led_sensor(sensor)
        if uart is not None and getattr(uart, "is_open", False):
            uart.close()
        _candado.release()


def capturar_identificacion():
    def operacion(sensor):
        publicar_estado("Lector listo. Apoya el centro del dedo y no lo muevas.")
        minucias = capturar_minucias_en_vivo(sensor)
        return 200, {
            "ok": True,
            "minucias": _minucias_b64(minucias),
            "mensaje": estado_sensor(),
        }

    return _con_lector(operacion)


def capturar_una_toma(datos):
    if not isinstance(datos, dict):
        return 400, {"ok": False, "mensaje": "La petición de la toma no tiene datos válidos."}
    try:
        numero = int(datos.get("numero") or 1)
    except (TypeError, ValueError):
        return 400, {"ok": False, "mensaje": "El número de toma no es válido."}
    primera = None
    texto = (datos.get("primera") or "").strip()
    if texto:
        try:
            primera = minucias_desde_texto(texto)
        except ValueError as error:
            return 400, {"ok": False, "mensaje": str(error)}

    def operacion(sensor):
        pixeles, minucias = capturar_toma_para_pantalla(sensor, numero, primera)
        return 200, {
            "ok": True,
            "numero": numero,
            "minucias": _minucias_b64(minucias),
            "imagen": png_data_url(pixeles),
            "mensaje": estado_sensor(),
        }

    return _con_lector(operacion)


class Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, formato, *args):
        sys.stderr.write("agente huella: " + (formato % args) + "\n")

    def _json(self, codigo, cuerpo):
        datos = json.dumps(cuerpo).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        ruta = urlparse(self.path).path
        if ruta != "/estado":
            self._json(404, {"ok": False, "mensaje": "Ruta desconocida."})
            return
        self._json(200, {"ok": True, "mensaje": estado_sensor()})

    def _datos(self):
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if largo < 0 or largo > 1_000_000:
            return None
        if largo == 0:
            return {}
        crudo = self.rfile.read(largo)
        try:
            datos = json.loads(crudo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return datos if isinstance(datos, dict) else None

    def do_POST(self):
        ruta = urlparse(self.path).path
        datos = self._datos()
        if ruta == "/capturar":
            codigo, cuerpo = capturar_identificacion()
        elif ruta == "/toma":
            if datos is None:
                codigo, cuerpo = 400, {"ok": False, "mensaje": "La petición de la toma no tiene datos válidos."}
            else:
                codigo, cuerpo = capturar_una_toma(datos)
        else:
            codigo, cuerpo = 404, {"ok": False, "mensaje": "Ruta desconocida."}
        self._json(codigo, cuerpo)


def servir(puerto: int = 0):
    """Abre el agente en 127.0.0.1. Puerto 0 elige uno libre, para las pruebas."""
    return ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)


def main() -> int:
    try:
        puerto = int(os.environ.get("HUELLA_AGENTE_PUERTO", "8766"))
    except ValueError:
        print("HUELLA_AGENTE_PUERTO tiene que ser un número.", file=sys.stderr)
        return 1
    try:
        servidor = servir(puerto)
    except OSError as error:
        print(f"No pude abrir 127.0.0.1:{puerto}: {error}", file=sys.stderr)
        return 1
    print(f"Agente de huella en http://127.0.0.1:{puerto} (solo esta computadora)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
