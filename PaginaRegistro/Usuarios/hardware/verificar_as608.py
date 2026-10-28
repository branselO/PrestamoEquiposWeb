#!/usr/bin/env python3
"""Habla con un AS608 conectado por adaptador TTL-USB.

El módulo se usa como escáner: baja la foto y la comparación 1:N se hace
en esta computadora. También puede comprobar solo el enlace UART.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

try:
    from .huella_pc import (
        UMBRAL,
        analizar,
        borrar_registro,
        buscar_mejor,
        cargar_registros,
        decodificar_imagen,
        guardar_analisis,
        guardar_vista,
    )
except ImportError:
    from huella_pc import (
        UMBRAL,
        analizar,
        borrar_registro,
        buscar_mejor,
        cargar_registros,
        decodificar_imagen,
        guardar_analisis,
        guardar_vista,
    )

CABECERA = b"\xEF\x01"
DIRECCION_FABRICA = 0xFFFFFFFF
BAUD_FABRICA = 57600
BAUDS_CONOCIDOS = (57600, 9600, 19200, 38400, 115200, 28800, 48000, 67200, 76800, 86400, 96000, 105600)

COMANDO = 0x01
ACK = 0x07

VERIFICAR_PASSWORD = 0x13
LEER_PARAMETROS = 0x0F
CONTAR_PLANTILLAS = 0x1D
CAPTURAR_IMAGEN = 0x01
IMAGEN_A_CARACTER = 0x02
BUSCAR = 0x04
REGISTRAR_MODELO = 0x05
GUARDAR_MODELO = 0x06
CARGAR_MODELO = 0x07
BORRAR_MODELO = 0x0C
LEER_INDICE = 0x1F
SUBIR_IMAGEN = 0x0A
SUBIR_CARACTER = 0x08
BAJAR_CARACTER = 0x09
COMPARAR = 0x03
PAQUETE_DATOS = 0x02
PAQUETE_FIN = 0x08
MAGIC_VACIO = b"AS608VACIO1"
ARCHIVO_VACIO = Path("cristal-vacio.bin")
PUNTAJE_MINIMO = 100
TIEMPO_DESCARGA = 25.0
CARPETA_HUELLAS = Path("huellas")

CODIGOS = {
    0x00: "correcto",
    0x01: "error al recibir el paquete",
    0x02: "no hay dedo en el sensor",
    0x03: "falló la captura de la imagen",
    0x06: "imagen demasiado desordenada para sacar minucias",
    0x07: "pocos puntos característicos o huella demasiado pequeña",
    0x08: "las muestras no coinciden",
    0x09: "esta huella no está en la memoria",
    0x0A: "no se pudieron combinar las muestras",
    0x0B: "posición fuera de la memoria",
    0x0C: "error al leer la plantilla",
    0x0D: "error al subir una característica",
    0x0E: "el módulo no recibió los paquetes siguientes",
    0x0F: "error al subir la imagen",
    0x10: "no se pudo borrar la plantilla",
    0x11: "no se pudo vaciar la memoria",
    0x13: "contraseña incorrecta",
    0x15: "la imagen no tiene área útil",
    0x18: "error de memoria flash",
    0x1A: "registro inválido",
    0x20: "código de dirección",
    0x21: "la verificación de la huella pasó",
}

TAMANO_PAQUETE = {0: 32, 1: 64, 2: 128, 3: 256}


class SinRespuesta(Exception):
    def __init__(self, recibidos: bytes) -> None:
        super().__init__("el sensor no contestó")
        self.recibidos = recibidos


class RespuestaInvalida(Exception):
    def __init__(self, crudo: bytes) -> None:
        super().__init__("la trama no es un acuse del AS608")
        self.crudo = crudo


@dataclass
class Paquete:
    tipo: int
    datos: bytes
    crudo: bytes


@dataclass
class Informe:
    puerto: str | None = None
    baud: int | None = None
    enlace: str = "sin_respuesta"
    codigo_password: int | None = None
    parametros: dict | None = None
    plantillas: int | None = None
    captura: str = "no_intentada"
    codigo_imagen: int | None = None
    codigo_caracter: int | None = None
    coincidencia: tuple[int, int] | None = None
    identificador: int | None = None
    ocupados: tuple[int, ...] | None = None
    ruido: bytes = b""
    checksums_malos: int = 0
    codigo_salida: int = 1
    notas: list[str] = field(default_factory=list)
    vista: str | None = None


def hex_bytes(datos: bytes) -> str:
    return datos.hex(" ").upper()


def describir_codigo(codigo: int) -> str:
    return CODIGOS.get(codigo, "código no documentado")


def construir_paquete(tipo: int, datos: bytes = b"", direccion: int = DIRECCION_FABRICA) -> bytes:
    longitud = len(datos) + 2
    trama = bytes(
        [
            0xEF,
            0x01,
            (direccion >> 24) & 0xFF,
            (direccion >> 16) & 0xFF,
            (direccion >> 8) & 0xFF,
            direccion & 0xFF,
            tipo & 0xFF,
            (longitud >> 8) & 0xFF,
            longitud & 0xFF,
        ]
    ) + datos
    suma = sum(trama[6:]) & 0xFFFF
    return trama + bytes([(suma >> 8) & 0xFF, suma & 0xFF])


def construir_comando(instruccion: int, datos: bytes = b"", direccion: int = DIRECCION_FABRICA) -> bytes:
    return construir_paquete(COMANDO, bytes([instruccion]) + datos, direccion)


class AS608:
    def __init__(self, serie, direccion: int = DIRECCION_FABRICA, verbose: bool = False) -> None:
        self.serie = serie
        self.direccion = direccion
        self.verbose = verbose
        self.ultimo_ruido = b""
        self.checksums_malos = 0
        self.pendiente = bytearray()

    def vaciar_entrada(self) -> None:
        self.pendiente.clear()
        reset = getattr(self.serie, "reset_input_buffer", None)
        if reset:
            reset()

    def cambiar_baud(self, baud: int) -> None:
        if getattr(self.serie, "baudrate", None) != baud:
            self.serie.baudrate = baud
            time.sleep(0.05)
        self.vaciar_entrada()

    def comando(self, instruccion: int, datos: bytes = b"", timeout: float = 1.0) -> Paquete:
        trama = construir_comando(instruccion, datos, self.direccion)
        self.vaciar_entrada()
        if self.verbose:
            print(f"    TX {hex_bytes(trama)}")
        self.serie.write(trama)
        flush = getattr(self.serie, "flush", None)
        if flush:
            flush()
        respuesta = self.leer_paquete(timeout)
        if respuesta is None:
            raise SinRespuesta(self.ultimo_ruido)
        if self.verbose:
            print(f"    RX {hex_bytes(respuesta.crudo)}")
        if respuesta.tipo != ACK or not respuesta.datos:
            raise RespuestaInvalida(respuesta.crudo)
        return respuesta

    def leer_paquete(self, timeout: float) -> Paquete | None:
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            paquete = self._extraer(self.pendiente)
            if paquete is not None:
                self.ultimo_ruido = bytes(self.pendiente)
                return paquete
            en_espera = getattr(self.serie, "in_waiting", 0) or 0
            chunk = self.serie.read(en_espera or 1)
            if chunk:
                self.pendiente.extend(chunk)
            else:
                time.sleep(0.01)
        self.ultimo_ruido = bytes(self.pendiente)
        return None

    def bajar_imagen(self, timeout: float) -> tuple[int | None, bytes | None]:
        try:
            respuesta = self.comando(SUBIR_IMAGEN, timeout=min(3.0, timeout))
        except (SinRespuesta, RespuestaInvalida):
            return None, None
        if not respuesta.datos:
            return None, None
        codigo = respuesta.datos[0]
        if codigo != 0x00:
            return codigo, None
        partes: list[bytes] = []
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            paquete = self.leer_paquete(min(0.6, max(0.05, limite - time.monotonic())))
            if paquete is None:
                crudo = b"".join(partes)
                if len(crudo) >= (ANCHO_IMAGEN * ALTO_IMAGEN) // 2:
                    return 0x00, crudo
                return 0x00, None
            if paquete.tipo in (PAQUETE_DATOS, PAQUETE_FIN):
                partes.append(paquete.datos)
                if paquete.tipo == PAQUETE_FIN:
                    return 0x00, b"".join(partes)
        crudo = b"".join(partes)
        if len(crudo) >= (ANCHO_IMAGEN * ALTO_IMAGEN) // 2:
            return 0x00, crudo
        return 0x00, None

    def subir_caracteristica(self, ranura: int, timeout: float) -> bytes | None:
        try:
            respuesta = self.comando(SUBIR_CARACTER, bytes([ranura]), timeout=timeout)
        except (SinRespuesta, RespuestaInvalida):
            return None
        if not respuesta.datos or respuesta.datos[0] != 0x00:
            return None
        partes: list[bytes] = []
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            paquete = self.leer_paquete(min(1.5, max(0.05, limite - time.monotonic())))
            if paquete is None:
                return None
            if paquete.tipo in (PAQUETE_DATOS, PAQUETE_FIN):
                partes.append(paquete.datos)
                if paquete.tipo == PAQUETE_FIN:
                    return b"".join(partes)
        return None

    def bajar_caracteristica(self, ranura: int, datos: bytes, tamano: int, timeout: float) -> int | None:
        try:
            respuesta = self.comando(BAJAR_CARACTER, bytes([ranura]), timeout=timeout)
        except (SinRespuesta, RespuestaInvalida):
            return None
        if not respuesta.datos or respuesta.datos[0] != 0x00:
            return respuesta.datos[0] if respuesta.datos else None
        for inicio in range(0, len(datos), tamano):
            bloque = datos[inicio : inicio + tamano]
            tipo = PAQUETE_FIN if inicio + tamano >= len(datos) else PAQUETE_DATOS
            self.serie.write(construir_paquete(tipo, bloque, self.direccion))
            time.sleep(0.002)
        flush = getattr(self.serie, "flush", None)
        if flush:
            flush()
        try:
            acuse = self.leer_paquete(timeout)
        except (SinRespuesta, RespuestaInvalida):
            return None
        if acuse is None or acuse.tipo != ACK or not acuse.datos:
            return None
        return acuse.datos[0]

    def comparar(self, timeout: float) -> tuple[int, int | None]:
        respuesta = self.comando(COMPARAR, timeout=timeout)
        codigo = respuesta.datos[0]
        if codigo == 0x00 and len(respuesta.datos) >= 3:
            return codigo, (respuesta.datos[1] << 8) | respuesta.datos[2]
        return codigo, None

    def _extraer(self, buf: bytearray) -> Paquete | None:
        while True:
            inicio = buf.find(CABECERA)
            if inicio < 0:
                if len(buf) > 1:
                    del buf[:-1]
                return None
            if inicio:
                del buf[:inicio]
            if len(buf) < 9:
                return None
            longitud = (buf[7] << 8) | buf[8]
            if longitud < 2 or longitud > 1024:
                del buf[0]
                continue
            total = 9 + longitud
            if len(buf) < total:
                return None
            trama = bytes(buf[:total])
            calculada = sum(trama[6:-2]) & 0xFFFF
            recibida = (trama[-2] << 8) | trama[-1]
            if calculada != recibida:
                self.checksums_malos += 1
                del buf[:2]
                continue
            del buf[:total]
            return Paquete(tipo=trama[6], datos=trama[9:-2], crudo=trama)


ANCHO_IMAGEN = 256
ALTO_IMAGEN = 288


def estadisticas_imagen(crudo: bytes) -> dict | None:
    pixeles_4bits = ANCHO_IMAGEN * ALTO_IMAGEN // 2
    pixeles_8bits = ANCHO_IMAGEN * ALTO_IMAGEN
    if len(crudo) >= pixeles_8bits:
        muestra = crudo[:pixeles_8bits]
        escala = 255
        total = 0
        cuadrados = 0
        for valor in muestra:
            total += valor
            cuadrados += valor * valor
        cantidad = pixeles_8bits
    elif len(crudo) >= pixeles_4bits:
        escala = 15
        total = 0
        cuadrados = 0
        for valor in crudo[:pixeles_4bits]:
            alto = valor >> 4
            bajo = valor & 0x0F
            total += alto + bajo
            cuadrados += alto * alto + bajo * bajo
        cantidad = pixeles_4bits * 2
    else:
        return None
    media = total / cantidad
    varianza = cuadrados / cantidad - media * media
    if varianza < 0:
        varianza = 0
    return {"media": media, "desviacion": varianza ** 0.5, "escala": escala}


def guardar_vacio(ruta: Path, datos: bytes) -> None:
    ruta.write_bytes(MAGIC_VACIO + datos)


def leer_vacio(ruta: Path) -> bytes | None:
    if not ruta.is_file():
        return None
    datos = ruta.read_bytes()
    if not datos.startswith(MAGIC_VACIO) or len(datos) <= len(MAGIC_VACIO):
        return None
    return datos[len(MAGIC_VACIO) :]


def tamano_de_paquete(parametros: dict | None) -> int:
    tamano = 128
    if parametros and parametros.get("tamano_paquete") in (32, 64, 128, 256):
        tamano = parametros["tamano_paquete"]
    return tamano


def parece_dedo(stats: dict) -> bool:
    escala = stats["escala"]
    if escala <= 0:
        return False
    media = stats["media"] / escala
    desviacion = stats["desviacion"] / escala
    if media < 0.05 or media > 0.95:
        return False
    if desviacion < 0.045:
        return False
    return True


def interpretar_parametros(datos: bytes) -> dict | None:
    if not datos or datos[0] != 0x00 or len(datos) < 17:
        return None
    codigo_tamano = (datos[13] << 8) | datos[14]
    factor_baud = (datos[15] << 8) | datos[16]
    return {
        "estado": (datos[1] << 8) | datos[2],
        "sistema": (datos[3] << 8) | datos[4],
        "capacidad": (datos[5] << 8) | datos[6],
        "seguridad": (datos[7] << 8) | datos[8],
        "direccion": (datos[9] << 24) | (datos[10] << 16) | (datos[11] << 8) | datos[12],
        "tamano_paquete": TAMANO_PAQUETE.get(codigo_tamano, codigo_tamano),
        "baud": factor_baud * 9600,
    }


def _marcar_enlace(informe: Informe, sensor: AS608) -> None:
    informe.checksums_malos = sensor.checksums_malos
    informe.ruido = sensor.ultimo_ruido
    if informe.codigo_password == 0x00:
        informe.enlace = "ok"
    elif informe.codigo_password is not None:
        informe.enlace = "password"
    elif sensor.checksums_malos:
        informe.enlace = "checksum"
    elif sensor.ultimo_ruido:
        informe.enlace = "ruido"
    else:
        informe.enlace = "sin_respuesta"


def buscar_baud(
    sensor: AS608,
    bauds: list[int],
    password: int,
    timeout: float,
    *,
    anunciar: bool,
) -> tuple[int, Paquete] | None:
    clave = password.to_bytes(4, "big")
    ruido = b""
    checksums = 0
    for baud in bauds:
        if anunciar:
            print(f"  Probando {baud} baud...")
        sensor.checksums_malos = 0
        sensor.ultimo_ruido = b""
        try:
            sensor.cambiar_baud(baud)
        except (OSError, ValueError) as exc:
            if anunciar:
                print(f"  {baud} baud no está disponible en este adaptador ({exc}).")
            continue
        try:
            respuesta = sensor.comando(VERIFICAR_PASSWORD, clave, timeout=timeout)
        except (SinRespuesta, RespuestaInvalida):
            checksums += sensor.checksums_malos
            if sensor.ultimo_ruido and not ruido:
                ruido = sensor.ultimo_ruido
            continue
        return baud, respuesta
    sensor.checksums_malos = checksums
    sensor.ultimo_ruido = ruido
    return None


def calibrar_cristal(
    sensor: AS608,
    informe: Informe,
    ruta: Path,
    timeout_comando: float,
    timeout_imagen: float,
) -> Informe:
    print("[4] Calibración del cristal vacío")
    print("  No pongas el dedo. El vidrio tiene que estar limpio y seco.")
    try:
        imagen = sensor.comando(CAPTURAR_IMAGEN, timeout=timeout_imagen)
    except (SinRespuesta, RespuestaInvalida):
        informe.captura = "timeout"
        informe.codigo_salida = 2
        return informe
    if imagen.datos[0] != 0x00:
        print(f"  GenImg 0x{imagen.datos[0]:02X}: {describir_codigo(imagen.datos[0])}")
        informe.captura = "falla_imagen"
        informe.codigo_salida = 2
        informe.notas.append("Con el cristal vacío el módulo no armó una imagen. No hay patrón que restar.")
        return informe
    try:
        caracter = sensor.comando(IMAGEN_A_CARACTER, bytes([0x01]), timeout=timeout_comando)
    except (SinRespuesta, RespuestaInvalida):
        informe.captura = "timeout"
        informe.codigo_salida = 2
        return informe
    print(f"  Img2Tz 0x{caracter.datos[0]:02X}: {describir_codigo(caracter.datos[0])}")
    if caracter.datos[0] != 0x00:
        informe.captura = "calibrado"
        informe.codigo_salida = 0
        informe.notas.append(
            "El cristal vacío no produjo minucias. Así es como debe verse cuando no hay dedo."
        )
        return informe
    patron = sensor.subir_caracteristica(1, timeout_comando)
    if not patron:
        informe.captura = "falla_imagen"
        informe.codigo_salida = 2
        informe.notas.append("No pude leer las minucias del cristal vacío.")
        return informe
    try:
        sensor.comando(CAPTURAR_IMAGEN, timeout=timeout_imagen)
        sensor.comando(IMAGEN_A_CARACTER, bytes([0x02]), timeout=timeout_comando)
        codigo, puntaje = sensor.comparar(timeout_comando)
        if codigo == 0x00:
            texto = f"puntaje {puntaje}" if puntaje is not None else "coinciden"
            print(f"  Las dos fotos del cristal vacío coinciden ({texto}).")
        else:
            print(f"  La segunda foto no coincidió (0x{codigo:02X}). El patrón no es del todo estable.")
    except (SinRespuesta, RespuestaInvalida):
        print("  No pude sacar una segunda foto para confirmar.")
    guardar_vacio(ruta, patron)
    print(f"  Guardé {len(patron)} bytes en {ruta}.")
    informe.captura = "calibrado"
    informe.codigo_salida = 0
    informe.notas.append(
        "Ese patrón ya no cuenta como dedo. Vuelve a correr el script sin --calibrar-vacio."
    )
    return informe


def ids_en_tabla(pagina: int, tabla: bytes, capacidad: int) -> list[int]:
    identificadores = []
    for indice, valor in enumerate(tabla[:32]):
        for bit in range(8):
            if valor & (1 << bit):
                identificador = pagina * 256 + indice * 8 + bit
                if identificador < capacidad:
                    identificadores.append(identificador)
    return identificadores


def capacidad_de(informe: Informe) -> int:
    if informe.parametros and informe.parametros["capacidad"] > 0:
        return min(int(informe.parametros["capacidad"]), 1000)
    return 300


def posiciones_ocupadas(sensor: AS608, capacidad: int, timeout: float) -> set[int] | None:
    ocupados: set[int] = set()
    paginas = max(1, (capacidad + 255) // 256)
    for pagina in range(paginas):
        try:
            respuesta = sensor.comando(LEER_INDICE, bytes([pagina]), timeout=timeout)
        except (SinRespuesta, RespuestaInvalida):
            return None
        if not respuesta.datos or respuesta.datos[0] != 0x00 or len(respuesta.datos) < 33:
            return None
        ocupados.update(ids_en_tabla(pagina, respuesta.datos[1:33], capacidad))
    return ocupados


def buscar_coincidencia(
    sensor: AS608, capacidad: int, timeout: float
) -> tuple[int, int | None, int | None]:
    respuesta = sensor.comando(
        BUSCAR,
        bytes([0x01, 0x00, 0x00, (capacidad >> 8) & 0xFF, capacidad & 0xFF]),
        timeout=timeout,
    )
    codigo = respuesta.datos[0]
    if codigo == 0x00 and len(respuesta.datos) >= 5:
        identificador = (respuesta.datos[1] << 8) | respuesta.datos[2]
        confianza = (respuesta.datos[3] << 8) | respuesta.datos[4]
        return codigo, identificador, confianza
    return codigo, None, None


@dataclass
class Hallazgo:
    estado: str
    codigo: int | None = None
    identificador: int | None = None
    puntaje: int | None = None
    buffer2_contaminado: bool = False


def confirmar_plantilla(
    sensor: AS608, identificador: int, timeout: float
) -> tuple[int, int | None]:
    pagina = bytes([0x02, (identificador >> 8) & 0xFF, identificador & 0xFF])
    respuesta = sensor.comando(CARGAR_MODELO, pagina, timeout=timeout)
    if not respuesta.datos or respuesta.datos[0] != 0x00:
        codigo = respuesta.datos[0] if respuesta.datos else 0x01
        return codigo, None
    return sensor.comparar(timeout)


def resolver_coincidencia(sensor: AS608, informe: Informe, timeout: float) -> Hallazgo:
    if informe.plantillas == 0:
        print("  El conteo dice que la memoria está vacía.")
    try:
        codigo, identificador, confianza = buscar_coincidencia(
            sensor, capacidad_de(informe), timeout
        )
    except (SinRespuesta, RespuestaInvalida):
        print("  La búsqueda en memoria no contestó.")
        return Hallazgo("error")
    if codigo != 0x00 or identificador is None:
        print(f"  Búsqueda 0x{codigo:02X}: {describir_codigo(codigo)}")
        return Hallazgo("ninguna", codigo=codigo)
    if informe.plantillas == 0:
        print(
            f"  El módulo señaló el ID {identificador} con la memoria vacía. "
            "No lo cuento."
        )
        return Hallazgo("debil", codigo=codigo, identificador=identificador, puntaje=confianza)
    if confianza is None or confianza < PUNTAJE_MINIMO:
        print(
            f"  El módulo señaló el ID {identificador} con puntaje {confianza}, "
            f"bajo {PUNTAJE_MINIMO}. No lo acepto."
        )
        informe.notas.append(
            f"El ID {identificador} apareció con puntaje {confianza}. "
            f"Si todos los dedos caen ahí, bórralo con --borrar {identificador}."
        )
        return Hallazgo("debil", codigo=codigo, identificador=identificador, puntaje=confianza)
    try:
        codigo_carga, puntaje = confirmar_plantilla(sensor, identificador, timeout)
    except (SinRespuesta, RespuestaInvalida):
        print(f"  No pude releer el ID {identificador} para confirmarlo.")
        return Hallazgo("error", codigo=codigo, identificador=identificador, puntaje=confianza)
    if codigo_carga != 0x00 or puntaje is None or puntaje < PUNTAJE_MINIMO:
        texto = f", puntaje {puntaje}" if puntaje is not None else ""
        print(
            f"  Releí el ID {identificador} y no coincide con este dedo "
            f"(0x{codigo_carga:02X}{texto})."
        )
        informe.notas.append(
            f"La plantilla del ID {identificador} no confirma este dedo. "
            f"Si siempre sale ese ID, bórralo con --borrar {identificador}."
        )
        return Hallazgo(
            "debil",
            codigo=codigo_carga,
            identificador=identificador,
            puntaje=puntaje if puntaje is not None else confianza,
            buffer2_contaminado=True,
        )
    print(f"  Coincide con el ID {identificador}, puntaje {puntaje}.")
    informe.coincidencia = (identificador, puntaje)
    informe.identificador = identificador
    return Hallazgo(
        "firme",
        codigo=0x00,
        identificador=identificador,
        puntaje=puntaje,
        buffer2_contaminado=True,
    )


def aplicar_resultado_captura(informe: Informe, resultado: str) -> Informe:
    informe.captura = resultado
    informe.codigo_salida = 0 if resultado == "calidad" else 2
    return informe


def capturar_dedo_estable(
    sensor: AS608,
    informe: Informe,
    *,
    espera: float,
    timeout_comando: float,
    timeout_imagen: float,
    pausa: float,
    titulo: str,
    instrucciones: tuple[str, ...],
    segunda: bool = False,
) -> str:
    print(titulo)
    for linea in instrucciones:
        print(f"  {linea}")
    limite = time.monotonic() + espera
    timeouts = 0
    codigos_imagen: list[int] = []
    ultimo_aviso = 0.0
    vio_vacio = False
    while time.monotonic() < limite:
        try:
            imagen = sensor.comando(CAPTURAR_IMAGEN, timeout=timeout_imagen)
        except (SinRespuesta, RespuestaInvalida):
            timeouts += 1
            print("  GenImg no contestó.")
            if timeouts >= 2:
                break
            continue
        codigo = imagen.datos[0]
        informe.codigo_imagen = codigo
        if not codigos_imagen or codigos_imagen[-1] != codigo:
            print(f"  GenImg 0x{codigo:02X}: {describir_codigo(codigo)}")
        codigos_imagen.append(codigo)
        if codigo != 0x00:
            if codigo != 0x02 and codigos_imagen.count(codigo) >= 3:
                break
            if codigo == 0x02:
                if ultimo_aviso == 0.0:
                    ultimo_aviso = time.monotonic()
                elif time.monotonic() - ultimo_aviso > 2:
                    print("  Sigo sin ver el dedo. Mantenlo cubriendo el cristal.")
                    ultimo_aviso = time.monotonic()
            time.sleep(pausa)
            continue

        ranura = 0x02 if segunda else 0x01
        try:
            caracter = sensor.comando(IMAGEN_A_CARACTER, bytes([ranura]), timeout=timeout_comando)
        except (SinRespuesta, RespuestaInvalida):
            print("  La imagen se pidió, pero Img2Tz no contestó.")
            timeouts += 1
            if timeouts >= 2:
                break
            continue
        informe.codigo_caracter = caracter.datos[0]
        print(f"  Img2Tz 0x{caracter.datos[0]:02X}: {describir_codigo(caracter.datos[0])}")
        if caracter.datos[0] in (0x06, 0x07, 0x15):
            print("  No hay una huella clara. Cubre el cristal con el dedo.")
            time.sleep(pausa)
            continue
        if caracter.datos[0] != 0x00:
            break

        if not segunda:
            try:
                segunda_foto = sensor.comando(CAPTURAR_IMAGEN, timeout=timeout_imagen)
                if segunda_foto.datos[0] != 0x00:
                    print(
                        f"  Segunda foto 0x{segunda_foto.datos[0]:02X}: "
                        f"{describir_codigo(segunda_foto.datos[0])}"
                    )
                    time.sleep(pausa)
                    continue
                caracter2 = sensor.comando(IMAGEN_A_CARACTER, bytes([0x02]), timeout=timeout_comando)
            except (SinRespuesta, RespuestaInvalida):
                print("  La segunda foto no contestó.")
                time.sleep(pausa)
                continue
            if caracter2.datos[0] != 0x00:
                print(
                    f"  Segunda Img2Tz 0x{caracter2.datos[0]:02X}: "
                    f"{describir_codigo(caracter2.datos[0])}"
                )
                time.sleep(pausa)
                continue

        try:
            codigo_cmp, puntaje = sensor.comparar(timeout_comando)
        except (SinRespuesta, RespuestaInvalida):
            print("  No pude comparar las dos fotos.")
            time.sleep(pausa)
            continue
        texto = f", puntaje {puntaje}" if puntaje is not None else ""
        print(f"  Comparación 0x{codigo_cmp:02X}{texto}")
        puntaje_bajo = puntaje is not None and puntaje < PUNTAJE_MINIMO
        if codigo_cmp != 0x00 or puntaje_bajo:
            vio_vacio = True
            if ultimo_aviso == 0.0 or time.monotonic() - ultimo_aviso > 2:
                if puntaje_bajo and segunda:
                    print(
                        f"  Puntaje {puntaje} bajo {PUNTAJE_MINIMO}. "
                        "Tiene que ser el mismo dedo, quieto."
                    )
                elif puntaje_bajo:
                    print(f"  Puntaje {puntaje} bajo {PUNTAJE_MINIMO}. El cristal vacío a veces llega aquí.")
                elif segunda:
                    print("  Esta toma no coincide con la primera. Apoya el mismo dedo, quieto.")
                else:
                    print("  Las dos fotos no coinciden. Sin un dedo quieto no lo acepto.")
                ultimo_aviso = time.monotonic()
            time.sleep(pausa)
            continue
        return "ok"

    if vio_vacio and segunda:
        return "distinta"
    if vio_vacio:
        return "vacio"
    if informe.codigo_caracter in (0x06, 0x07, 0x15):
        return "calidad"
    if not codigos_imagen:
        return "timeout"
    if informe.codigo_imagen == 0x02:
        return "sin_dedo"
    if informe.codigo_caracter is None and timeouts:
        return "timeout"
    return "falla_imagen"


def tomar_segunda_puesta(
    sensor: AS608,
    *,
    espera: float,
    timeout_comando: float,
    timeout_imagen: float,
    pausa: float,
) -> str:
    print("[6] Segunda toma")
    print("  Levanta el dedo y apóyalo otra vez, sin moverlo.")
    print("  Este módulo no avisa cuando el cristal queda vacío. Espero a que las fotos dejen de coincidir.")
    limite = time.monotonic() + espera
    vio_pausa = False
    ultimo_bueno = False
    ultimo_aviso = 0.0
    timeouts = 0

    def avisar(texto: str) -> None:
        nonlocal ultimo_aviso
        if ultimo_aviso == 0.0 or time.monotonic() - ultimo_aviso > 2:
            print(texto)
            ultimo_aviso = time.monotonic()

    while time.monotonic() < limite:
        try:
            imagen = sensor.comando(CAPTURAR_IMAGEN, timeout=timeout_imagen)
        except (SinRespuesta, RespuestaInvalida):
            timeouts += 1
            print("  GenImg no contestó.")
            if timeouts >= 2:
                return "timeout"
            continue
        if imagen.datos[0] == 0x02:
            vio_pausa = True
            ultimo_bueno = False
            avisar("  Dedo fuera. Apóyalo otra vez, sin moverlo.")
            time.sleep(pausa)
            continue
        if imagen.datos[0] != 0x00:
            time.sleep(pausa)
            continue
        try:
            caracter = sensor.comando(IMAGEN_A_CARACTER, bytes([0x02]), timeout=timeout_comando)
        except (SinRespuesta, RespuestaInvalida):
            print("  La segunda toma no contestó.")
            time.sleep(pausa)
            continue
        if caracter.datos[0] != 0x00:
            print(f"  Img2Tz 0x{caracter.datos[0]:02X}: {describir_codigo(caracter.datos[0])}")
            time.sleep(pausa)
            continue
        try:
            codigo, puntaje = sensor.comparar(timeout_comando)
        except (SinRespuesta, RespuestaInvalida):
            print("  No pude comparar con la primera toma.")
            time.sleep(pausa)
            continue
        texto = f", puntaje {puntaje}" if puntaje is not None else ""
        print(f"  Comparación 0x{codigo:02X}{texto}")
        aceptable = codigo == 0x00 and (puntaje is None or puntaje >= PUNTAJE_MINIMO)
        if aceptable and vio_pausa:
            print("  La segunda puesta coincide.")
            return "ok"
        if aceptable:
            ultimo_bueno = True
            avisar("  Sigue siendo la misma toma. Levanta el dedo del cristal.")
            time.sleep(pausa)
            continue
        vio_pausa = True
        ultimo_bueno = False
        if puntaje is not None and puntaje < PUNTAJE_MINIMO:
            avisar(f"  Puntaje {puntaje} bajo {PUNTAJE_MINIMO}. Apoya el mismo dedo, quieto.")
        else:
            avisar("  El dedo ya no coincide. Apóyalo otra vez, sin moverlo.")
        time.sleep(pausa)
    if ultimo_bueno:
        print("  No separaste el dedo. Guardo las fotos de esta misma toma.")
        return "misma"
    return "distinta"


def listar_huellas(sensor: AS608, informe: Informe, timeout_comando: float) -> Informe:
    print("[4] Huellas en memoria")
    capacidad = capacidad_de(informe)
    ocupados = posiciones_ocupadas(sensor, capacidad, timeout_comando)
    if ocupados is None:
        informe.captura = "sin_indice"
        informe.codigo_salida = 2
        if informe.plantillas is not None:
            informe.notas.append(
                f"El conteo dice {informe.plantillas} huella(s), pero el mapa de ID no contestó."
            )
        return informe
    informe.ocupados = tuple(sorted(ocupados))
    if informe.ocupados:
        texto = ", ".join(str(identificador) for identificador in informe.ocupados)
        print(f"  ID ocupados: {texto}")
    else:
        print("  No hay huellas guardadas.")
    informe.captura = "listada"
    informe.codigo_salida = 0
    informe.notas.append(f"{len(informe.ocupados)} posición(es) ocupada(s).")
    return informe


def reconocer_huella(sensor: AS608, informe: Informe, timeout_comando: float) -> Informe:
    print("[5] Reconocer")
    hallazgo = resolver_coincidencia(sensor, informe, timeout_comando)
    if hallazgo.estado == "firme":
        informe.captura = "reconocida"
        informe.codigo_salida = 0
        return informe
    if hallazgo.estado == "error":
        informe.captura = "sin_busqueda"
        informe.codigo_salida = 2
        return informe
    if hallazgo.estado == "debil":
        informe.identificador = hallazgo.identificador
        informe.captura = "debil"
        informe.codigo_salida = 0
        return informe
    if hallazgo.codigo == 0x09 or hallazgo.estado == "ninguna":
        informe.captura = "desconocida"
        informe.codigo_salida = 0
        return informe
    informe.captura = "falla_imagen"
    informe.codigo_salida = 2
    return informe


def borrar_huella(
    sensor: AS608, informe: Informe, identificador: int, timeout_comando: float
) -> Informe:
    print(f"[4] Borrar ID {identificador}")
    capacidad = capacidad_de(informe)
    if identificador < 0 or identificador >= capacidad:
        informe.captura = "falla_imagen"
        informe.codigo_salida = 2
        informe.notas.append(
            f"El ID {identificador} no cabe. Este módulo guarda de 0 a {capacidad - 1}."
        )
        return informe
    datos = bytes([(identificador >> 8) & 0xFF, identificador & 0xFF, 0x00, 0x01])
    try:
        respuesta = sensor.comando(BORRAR_MODELO, datos, timeout=max(timeout_comando, 2.0))
    except (SinRespuesta, RespuestaInvalida):
        informe.captura = "falla_imagen"
        informe.codigo_salida = 2
        informe.notas.append(f"El módulo no confirmó el borrado del ID {identificador}.")
        return informe
    print(f"  Borrar 0x{respuesta.datos[0]:02X}: {describir_codigo(respuesta.datos[0])}")
    if respuesta.datos[0] != 0x00:
        informe.captura = "falla_imagen"
        informe.codigo_salida = 2
        informe.notas.append(
            f"No se pudo borrar el ID {identificador} "
            f"(0x{respuesta.datos[0]:02X}, {describir_codigo(respuesta.datos[0])})."
        )
        return informe
    informe.identificador = identificador
    informe.captura = "borrada"
    informe.codigo_salida = 0
    informe.notas.append(f"Borré el ID {identificador}.")
    return informe


def guardar_huella(
    sensor: AS608,
    informe: Informe,
    *,
    identificador: int | None,
    reemplazar: bool,
    espera: float,
    timeout_comando: float,
    timeout_imagen: float,
    pausa: float,
) -> Informe:
    capacidad = capacidad_de(informe)
    print("[5] Memoria")
    hallazgo = resolver_coincidencia(sensor, informe, timeout_comando)
    if hallazgo.estado == "firme":
        informe.captura = "ya_guardada"
        informe.codigo_salida = 0
        return informe

    ocupados = posiciones_ocupadas(sensor, capacidad, timeout_comando)
    if ocupados is not None:
        informe.ocupados = tuple(sorted(ocupados))
    if identificador is None:
        if ocupados is None:
            informe.captura = "sin_indice"
            informe.codigo_salida = 2
            informe.notas.append("No pude leer qué posiciones están libres. Repite con --id.")
            return informe
        identificador = next((candidato for candidato in range(capacidad) if candidato not in ocupados), None)
        if identificador is None:
            informe.captura = "llena"
            informe.codigo_salida = 2
            return informe
    elif identificador >= capacidad:
        informe.captura = "falla_imagen"
        informe.codigo_salida = 2
        informe.notas.append(
            f"El ID {identificador} no cabe. Este módulo guarda de 0 a {capacidad - 1}."
        )
        return informe
    elif ocupados is not None and identificador in ocupados and not reemplazar:
        informe.identificador = identificador
        informe.captura = "ocupado"
        informe.codigo_salida = 2
        print(f"  El ID {identificador} ya tiene una huella.")
        return informe

    resultado = tomar_segunda_puesta(
        sensor,
        espera=espera,
        timeout_comando=timeout_comando,
        timeout_imagen=timeout_imagen,
        pausa=pausa,
    )
    if resultado == "timeout":
        informe.captura = "timeout"
        informe.codigo_salida = 2
        return informe
    if resultado not in ("ok", "misma"):
        return aplicar_resultado_captura(informe, resultado)

    print(f"[7] Guardar en el ID {identificador}")
    try:
        modelo = sensor.comando(REGISTRAR_MODELO, timeout=timeout_comando)
    except (SinRespuesta, RespuestaInvalida):
        informe.captura = "falla_imagen"
        informe.codigo_salida = 2
        informe.notas.append("No pude combinar las dos tomas.")
        return informe
    print(f"  RegModel 0x{modelo.datos[0]:02X}: {describir_codigo(modelo.datos[0])}")
    if modelo.datos[0] != 0x00:
        informe.captura = "falla_imagen"
        informe.codigo_salida = 2
        informe.notas.append("Las dos tomas no se pudieron combinar en una plantilla.")
        return informe
    pagina = bytes([0x01, (identificador >> 8) & 0xFF, identificador & 0xFF])
    try:
        guardado = sensor.comando(GUARDAR_MODELO, pagina, timeout=max(timeout_comando, 2.0))
    except (SinRespuesta, RespuestaInvalida):
        informe.captura = "falla_imagen"
        informe.codigo_salida = 2
        informe.notas.append("La plantilla se armó, pero el módulo no confirmó el guardado.")
        return informe
    print(f"  Store 0x{guardado.datos[0]:02X}: {describir_codigo(guardado.datos[0])}")
    if guardado.datos[0] != 0x00:
        informe.captura = "falla_imagen"
        informe.codigo_salida = 2
        informe.notas.append(
            f"No se pudo escribir el ID {identificador} "
            f"(0x{guardado.datos[0]:02X}, {describir_codigo(guardado.datos[0])})."
        )
        return informe
    print(f"  Quedó guardada en el ID {identificador}.")
    informe.identificador = identificador
    informe.captura = "guardada"
    informe.codigo_salida = 0
    informe.notas.append(f"Huella guardada en el ID {identificador}.")
    return informe


def listar_en_pc(informe: Informe, carpeta: Path) -> Informe:
    informe.enlace = "ok"
    print("[4] Huellas en esta computadora")
    registros = cargar_registros(carpeta)
    informe.ocupados = tuple(registro.identificador for registro in registros)
    if registros:
        for registro in registros:
            print(f"  ID {registro.identificador}: {len(registro.minucias)} minucias")
    else:
        print(f"  No hay huellas en {carpeta}.")
    informe.captura = "listada"
    informe.codigo_salida = 0
    informe.notas.append(f"{len(registros)} huella(s) en {carpeta}.")
    return informe


def borrar_en_pc(informe: Informe, carpeta: Path, identificador: int | None) -> Informe:
    if identificador is None:
        informe.captura = "falla_imagen"
        informe.codigo_salida = 2
        informe.notas.append("Falta el ID. Úsalo así: --borrar 0.")
        return informe
    print(f"[4] Borrar ID {identificador} de esta computadora")
    informe.enlace = "ok"
    if not borrar_registro(carpeta, identificador):
        informe.identificador = identificador
        informe.captura = "ausente"
        informe.codigo_salida = 2
        return informe
    informe.identificador = identificador
    informe.captura = "borrada"
    informe.codigo_salida = 0
    return informe


def escanear_dedo(
    sensor: AS608,
    informe: Informe,
    *,
    espera: float,
    timeout_imagen: float,
    pausa: float,
    carpeta: Path,
):
    print("[4] Escanear")
    print("  Una sola foto. Apoya el dedo y no lo muevas.")
    print(f"  La imagen queda en {carpeta / 'ultimo.png'}.")
    print("  Si el LED azul quedó encendido desde que conectaste el 5 V, es la lámpara del módulo.")
    if espera >= 5:
        print("  Esperando 3 segundos para que lo apoyes.")
        time.sleep(3)
    limite = time.monotonic() + espera
    vio_mala = False
    vio_rejilla = False
    fallo_descarga = False
    while time.monotonic() < limite:
        try:
            imagen = sensor.comando(CAPTURAR_IMAGEN, timeout=timeout_imagen)
        except (SinRespuesta, RespuestaInvalida):
            print("  GenImg no contestó.")
            time.sleep(pausa)
            continue
        codigo = imagen.datos[0]
        informe.codigo_imagen = codigo
        print(f"  GenImg 0x{codigo:02X}: {describir_codigo(codigo)}")
        if codigo != 0x00:
            time.sleep(pausa)
            continue
        print("  Descargando la foto...")
        codigo_bajada, crudo = sensor.bajar_imagen(TIEMPO_DESCARGA)
        if not crudo:
            fallo_descarga = True
            if codigo_bajada in (None, 0x00):
                print("  No llegó la foto completa.")
            else:
                print(f"  Descarga 0x{codigo_bajada:02X}: {describir_codigo(codigo_bajada)}")
            time.sleep(pausa)
            continue
        pixeles = decodificar_imagen(crudo, ANCHO_IMAGEN, ALTO_IMAGEN)
        if pixeles is None:
            fallo_descarga = True
            print(
                f"  Llegaron {len(crudo)} bytes. "
                f"No forman una foto de {ANCHO_IMAGEN}×{ALTO_IMAGEN}."
            )
            time.sleep(pausa)
            continue
        print(f"  Foto de {len(crudo)} bytes.")
        ruta = guardar_vista(carpeta, pixeles, ANCHO_IMAGEN, ALTO_IMAGEN)
        informe.vista = str(ruta)
        print(f"  Foto guardada en {ruta}.")
        analisis = analizar(pixeles, ANCHO_IMAGEN, ALTO_IMAGEN)
        print(f"  Minucias: {len(analisis.minucias)}, coherencia: {analisis.coherencia:.2f}")
        if not analisis.util:
            vio_mala = True
            if analisis.motivo == "rejilla":
                vio_rejilla = True
                print("  Son las líneas del cristal. Abre esa imagen: tiene que verse la yema, no solo rayas.")
            else:
                print("  No hay crestas claras. Seca el dedo y cubre el cristal.")
            print("  Para otra foto, vuelve a correr el comando con el dedo ya apoyado.")
            break
        return analisis
    if vio_rejilla:
        informe.captura = "rejilla"
    elif fallo_descarga and not vio_mala:
        informe.captura = "falla_imagen"
    elif vio_mala or informe.codigo_imagen == 0x00:
        informe.captura = "vacio"
    elif informe.codigo_imagen == 0x02:
        informe.captura = "sin_dedo"
    else:
        informe.captura = "timeout"
    informe.codigo_salida = 2
    return None


def concluir_imagen(
    informe: Informe,
    analisis,
    modo: str,
    carpeta: Path,
    identificador: int | None,
    reemplazar: bool,
) -> Informe:
    registros = cargar_registros(carpeta)
    mejor = buscar_mejor(analisis.minucias, registros)
    if mejor is None:
        print(f"  No hay huellas en {carpeta}.")
        puntaje, ident = 0, None
    else:
        puntaje, ident = mejor
        print(f"  Mejor coincidencia: ID {ident}, puntaje {puntaje}.")
    if modo == "guardar":
        if mejor is not None and puntaje >= UMBRAL and not reemplazar:
            informe.coincidencia = (ident, puntaje)
            informe.identificador = ident
            informe.captura = "ya_guardada"
            informe.codigo_salida = 0
            return informe
        if (
            identificador is not None
            and any(registro.identificador == identificador for registro in registros)
            and not reemplazar
        ):
            informe.identificador = identificador
            informe.captura = "ocupado"
            informe.codigo_salida = 2
            return informe
        nuevo = guardar_analisis(carpeta, analisis, identificador)
        informe.identificador = nuevo
        informe.captura = "guardada"
        informe.codigo_salida = 0
        informe.notas.append(f"Foto en {carpeta / f'{nuevo}.png'}.")
        return informe
    if mejor is not None and puntaje >= UMBRAL:
        informe.coincidencia = (ident, puntaje)
        informe.identificador = ident
        informe.captura = "reconocida"
        informe.codigo_salida = 0
        return informe
    if mejor is not None:
        informe.notas.append(
            f"La más cercana es el ID {ident} con puntaje {puntaje}. Hace falta {UMBRAL}."
        )
    elif modo == "reconocer":
        informe.notas.append(f"No hay huellas en {carpeta}.")
    informe.captura = "desconocida"
    informe.codigo_salida = 0
    return informe


def verificar(
    sensor: AS608,
    *,
    baud_inicial: int,
    password: int = 0,
    probar_dedo: bool = True,
    espera: float = 20.0,
    bauds: list[int] | None = None,
    timeout_comando: float = 1.0,
    timeout_imagen: float = 2.0,
    pausa: float = 0.2,
    calibrar_vacio: bool = False,
    ruta_vacio: Path = ARCHIVO_VACIO,
    modo: str = "verificar",
    identificador: int | None = None,
    reemplazar: bool = False,
    carpeta: Path = CARPETA_HUELLAS,
) -> Informe:
    informe = Informe(baud=baud_inicial)
    candidatos = [baud_inicial]
    for baud in bauds or BAUDS_CONOCIDOS:
        if baud not in candidatos:
            candidatos.append(baud)

    print("[1] Contraseña de enlace")
    encontrado = buscar_baud(
        sensor, candidatos[:1], password, timeout_comando, anunciar=False
    )
    if encontrado is None and len(candidatos) > 1:
        ruido_inicial = sensor.ultimo_ruido
        checksums_iniciales = sensor.checksums_malos
        print("  Sin respuesta en el baud indicado. Barro los baud habituales del AS608.")
        encontrado = buscar_baud(
            sensor,
            candidatos[1:],
            password,
            min(timeout_comando, 0.45),
            anunciar=True,
        )
        if encontrado is None:
            sensor.checksums_malos += checksums_iniciales
            if not sensor.ultimo_ruido:
                sensor.ultimo_ruido = ruido_inicial

    if encontrado is None:
        _marcar_enlace(informe, sensor)
        informe.captura = "no_intentada"
        informe.codigo_salida = 1
        return informe

    baud, respuesta = encontrado
    informe.baud = baud
    informe.codigo_password = respuesta.datos[0]
    sensor.cambiar_baud(baud)
    print(f"  Código 0x{respuesta.datos[0]:02X}: {describir_codigo(respuesta.datos[0])}")
    _marcar_enlace(informe, sensor)

    print("[2] Parámetros del módulo")
    try:
        parametros_crudos = sensor.comando(LEER_PARAMETROS, timeout=timeout_comando)
    except (SinRespuesta, RespuestaInvalida):
        print("  No contestó a la lectura de parámetros.")
    else:
        codigo = parametros_crudos.datos[0]
        print(f"  Código 0x{codigo:02X}: {describir_codigo(codigo)}")
        informe.parametros = interpretar_parametros(parametros_crudos.datos)
        if informe.parametros:
            datos = informe.parametros
            print(f"  Capacidad: {datos['capacidad']} huellas")
            print(f"  Nivel de seguridad: {datos['seguridad']}")
            print(f"  Baud guardado en el módulo: {datos['baud']}")
            print(f"  Tamaño de paquete: {datos['tamano_paquete']} bytes")
            print(f"  Dirección: {datos['direccion']:08X}")
            if datos["baud"] and datos["baud"] != baud:
                informe.notas.append(
                    f"Abre el puerto a {baud} baud. El módulo tiene guardado {datos['baud']}, "
                    "pero su reloj corre a otro ritmo y los bits salen a la velocidad en la que contestó. "
                    "Deja ese registro como está: si lo reescribes, la velocidad real se vuelve a correr."
                )
            elif baud != baud_inicial:
                informe.notas.append(
                    f"Usa --baud {baud}. A {baud_inicial} no contestó."
                )
        elif baud != baud_inicial:
            informe.notas.append(f"Usa --baud {baud}. A {baud_inicial} no contestó.")

    print("[3] Plantillas guardadas")
    try:
        conteo = sensor.comando(CONTAR_PLANTILLAS, timeout=timeout_comando)
    except (SinRespuesta, RespuestaInvalida):
        print("  No contestó al conteo de plantillas.")
    else:
        if conteo.datos[0] == 0x00 and len(conteo.datos) >= 3:
            informe.plantillas = (conteo.datos[1] << 8) | conteo.datos[2]
            print(f"  {informe.plantillas} huella(s) en la memoria.")
        else:
            print(f"  Código 0x{conteo.datos[0]:02X}: {describir_codigo(conteo.datos[0])}")

    if informe.enlace == "password" and informe.parametros is None and informe.plantillas is None:
        informe.codigo_salida = 4 if informe.codigo_password == 0x13 else 1
        return informe

    if informe.codigo_password not in (None, 0x00):
        informe.notas.append(
            "El módulo contestó aunque rechazó la contraseña "
            f"(0x{informe.codigo_password:02X}, {describir_codigo(informe.codigo_password)})."
        )
    informe.enlace = "ok"

    if calibrar_vacio:
        return calibrar_cristal(sensor, informe, ruta_vacio, timeout_comando, timeout_imagen)

    if modo == "listar":
        return listar_en_pc(informe, carpeta)

    if modo == "borrar":
        return borrar_en_pc(informe, carpeta, identificador)

    if modo in ("guardar", "reconocer"):
        analisis = escanear_dedo(
            sensor,
            informe,
            espera=espera,
            timeout_imagen=timeout_imagen,
            pausa=pausa,
            carpeta=carpeta,
        )
        if analisis is None:
            return informe
        return concluir_imagen(informe, analisis, modo, carpeta, identificador, reemplazar)

    if not probar_dedo:
        informe.captura = "omitida"
        informe.codigo_salida = 0
        return informe

    if modo == "guardar":
        instrucciones = (
            "Primera toma. Apoya el dedo y no lo muevas.",
            f"Solo sigo si las dos fotos coinciden con puntaje de {PUNTAJE_MINIMO} o más.",
            "Después levántalo y apóyalo otra vez. Este módulo no avisa cuando lo quitas.",
        )
    else:
        instrucciones = (
            "Apoya el dedo y no lo muevas. Hago dos fotos; solo acepto si coinciden "
            f"con puntaje de {PUNTAJE_MINIMO} o más.",
            "Si el LED azul quedó encendido desde que conectaste el 5 V, es la lámpara del módulo.",
        )
    resultado = capturar_dedo_estable(
        sensor,
        informe,
        espera=espera,
        timeout_comando=timeout_comando,
        timeout_imagen=timeout_imagen,
        pausa=pausa,
        titulo="[4] Captura de huella",
        instrucciones=instrucciones,
    )
    if resultado != "ok":
        return aplicar_resultado_captura(informe, resultado)

    if modo == "guardar":
        return guardar_huella(
            sensor,
            informe,
            identificador=identificador,
            reemplazar=reemplazar,
            espera=espera,
            timeout_comando=timeout_comando,
            timeout_imagen=timeout_imagen,
            pausa=pausa,
        )
    if modo == "reconocer":
        return reconocer_huella(sensor, informe, timeout_comando)

    if informe.plantillas:
        hallazgo = resolver_coincidencia(sensor, informe, timeout_comando)
        if hallazgo.estado == "ninguna" and hallazgo.codigo == 0x09:
            informe.notas.append("La imagen sirvió. Este dedo no es la huella que ya está guardada.")
        elif hallazgo.estado == "error":
            informe.notas.append("La captura fue válida. La búsqueda en memoria no contestó.")

    informe.captura = "ok"
    informe.codigo_salida = 0
    return informe


def texto_diagnostico(informe: Informe) -> str:
    if informe.enlace == "sin_respuesta":
        return (
            "No llegó ninguna respuesta del AS608. El puerto abre, pero el módulo no contesta. "
            "Deja el jumper en 3.3 V y alimenta el rojo desde el pin de 5 V, con GND común. "
            "El TX del adaptador va directo al RX del sensor. "
            "Si el TX del sensor en reposo mide cerca de 5 V, no lo conectes directo al RX del adaptador: "
            "ese pin está en 3.3 V. Intercala un divisor, 1 kΩ desde el TX del sensor hasta el RX del "
            "adaptador y 2 kΩ de ese RX a GND. En el RX del adaptador deben quedar unos 3.2 V."
        )
    if informe.enlace == "ruido":
        muestra = hex_bytes(informe.ruido[:24])
        return (
            "Llegaron bytes que no forman un paquete EF 01 "
            f"({muestra or 'vacío'}). Revisa que el baud sea 57600, que TX y RX estén cruzados "
            "y que la tierra sea común. Si el TX del sensor está cerca de 5 V y el adaptador en 3.3 V, "
            "esos bytes también salen de meter 5 V directo en el RX: hace falta el divisor de 1 kΩ y 2 kΩ."
        )
    if informe.enlace == "checksum":
        return (
            "Llegó la cabecera EF 01, pero el checksum no cuadra. El baud es el indicado y la señal "
            "está corrupta: nivel lógico al límite, o el 5 V se cae cuando el sensor intenta trabajar."
        )
    if informe.enlace == "password":
        if informe.codigo_password == 0x13:
            return (
                "El módulo contestó, así que el UART funciona, pero rechazó la contraseña. "
                "La de fábrica es 0x00000000. Si se cambió en el sensor, pásala con --password."
            )
        return (
            f"El módulo contestó con 0x{informe.codigo_password:02X} "
            f"({describir_codigo(informe.codigo_password or 0)}), así que el UART funciona, "
            "pero no entregó parámetros. Repite la prueba con --verbose."
        )
    if informe.captura == "omitida":
        return "El enlace UART está confirmado. La captura no se pidió por --solo-enlace."
    if informe.captura == "rejilla":
        donde = informe.vista or "huellas/ultimo.png"
        return (
            f"La foto quedó en {donde}. Son las líneas del cristal: el dedo no salió en la imagen. "
            "Limpia el vidrio, apoya la yema en el centro y aprieta hasta que la piel se aclare. "
            "Vuelve a correr el comando con el dedo ya apoyado. Es una sola foto cada vez."
        )
    if informe.captura == "vacio":
        return (
            "El cristal vacío a veces fabrica minucias. Si las dos fotos no coinciden, "
            f"o coinciden con un puntaje menor de {PUNTAJE_MINIMO}, no es un dedo. "
            f"Un dedo quieto suele pasar de {PUNTAJE_MINIMO}. "
            "Si el LED azul está encendido desde que conectas el 5 V, es la lámpara del módulo."
        )
    if informe.captura == "distinta":
        return (
            "La segunda toma no alcanzó el puntaje contra la primera. "
            "Tiene que ser el mismo dedo, seco y quieto, cubriendo el cristal."
        )
    if informe.captura == "guardada":
        return (
            f"La foto quedó en esta computadora como ID {informe.identificador}. "
            "El módulo no la guardó. Para probarla, corre --reconocer con el mismo dedo."
        )
    if informe.captura == "ya_guardada":
        ident, conf = informe.coincidencia or (informe.identificador, None)
        extra = f", puntaje {conf}" if conf is not None else ""
        return (
            f"Esa huella ya está en el ID {ident} de esta computadora{extra}. "
            "No guardé otra copia."
        )
    if informe.captura == "debil":
        return (
            f"El módulo señaló el ID {informe.identificador}, pero el puntaje no llega "
            f"a {PUNTAJE_MINIMO}. No lo cuento como ese dedo. "
            f"Si todos los dedos caen en el ID {informe.identificador}, "
            f"esa plantilla no sirve: --borrar {informe.identificador}."
        )
    if informe.captura == "ausente":
        return f"No hay una huella con el ID {informe.identificador} en esta computadora."
    if informe.captura == "borrada":
        return (
            f"Borré el ID {informe.identificador} de esta computadora. "
            "Puedes volver a guardarlo con --guardar."
        )
    if informe.captura == "reconocida":
        ident, conf = informe.coincidencia or (informe.identificador, None)
        extra = f", puntaje {conf}" if conf is not None else ""
        return f"El dedo coincide con el ID {ident} de esta computadora{extra}."
    if informe.captura == "desconocida":
        return (
            "La foto sirvió y no coincide con las huellas de esta computadora. "
            "Guárdala con --guardar."
        )
    if informe.captura == "ocupado":
        return (
            f"El ID {informe.identificador} ya tiene una foto en esta computadora. "
            "Elige otro número o vuelve a correr con --reemplazar."
        )
    if informe.captura == "llena":
        return "La memoria del módulo no tiene posiciones libres."
    if informe.captura == "listada":
        return "Esas son las huellas guardadas en esta computadora."
    if informe.captura == "sin_indice":
        return "El módulo no entregó el mapa de posiciones. Indica dónde guardar con --id."
    if informe.captura == "sin_busqueda":
        return "La captura fue válida, pero la búsqueda en memoria no contestó."
    if informe.captura == "calibrado":
        return "Quedó guardado el patrón del cristal vacío. La próxima lectura lo va a ignorar."
    if informe.captura == "sin_dedo":
        return (
            "El enlace está bien y GenImg responde 0x02, que significa que no ve un dedo. "
            "Si el dedo estaba puesto y el LED azul no encendió, al sensor le falta alimentación: "
            "necesita entre 3.6 V y 6 V, y cerca de 150 mA al tomar la imagen. "
            "El pin de 3.3 V del adaptador no alcanza. Deja TX y RX en 3.3 V y alimenta el rojo con 5 V."
        )
    if informe.captura == "timeout":
        return (
            "Los primeros comandos contestaron, pero al pedir la imagen el módulo dejó de responder. "
            "El LED azul pide un pico de corriente y la alimentación se está cayendo. "
            "Usa el pin de 5 V, no el de 3.3 V, con una fuente que sostenga al menos 150 mA, y GND común."
        )
    if informe.captura == "falla_imagen":
        return (
            "El UART funciona, pero la captura no sirvió. Limpia el cristal y cubre toda la ventana. "
            "Si el LED azul no enciende durante GenImg, el módulo sigue corto de alimentación."
        )
    if informe.captura == "calidad":
        return (
            "La imagen se tomó, pero no salieron minucias fiables. El adaptador y el óptico sí respondieron. "
            "Seca el dedo y apóyalo plano, cubriendo el cristal."
        )
    if informe.captura == "ok":
        return "El adaptador y el AS608 se comunican, y la captura de la huella funcionó."
    return "La prueba no pudo clasificar el resultado. Vuelve a correrla con --verbose."


def imprimir_informe(informe: Informe) -> None:
    print()
    print("Resultado")
    for nota in informe.notas:
        print(f"  {nota}")
    print(f"  {texto_diagnostico(informe)}")


def abortar(codigo: int, mensaje: str) -> NoReturn:
    print(mensaje)
    raise SystemExit(codigo)


def cargar_serial():
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        abortar(3, "Falta pyserial. En el entorno del proyecto ejecuta: pip install -r requirements.txt")
    return serial, list_ports


def describir_puerto(puerto) -> str:
    detalles = [puerto.description or "", puerto.manufacturer or "", puerto.hwid or ""]
    extra = " ".join(parte for parte in detalles if parte).strip()
    if extra:
        return f"{puerto.device}  {extra}"
    return puerto.device


def puntaje_puerto(puerto) -> int:
    texto = f"{puerto.device} {puerto.description or ''} {puerto.hwid or ''} {puerto.manufacturer or ''}".upper()
    if puerto.device.startswith("/dev/ttyS"):
        return -5
    puntaje = 0
    for clave in ("CH340", "CH341", "CP210", "FTDI", "FT232", "PL2303", "UART", "USB SERIAL", "USB-SERIAL"):
        if clave in texto:
            puntaje += 2
    dispositivo = puerto.device.upper()
    if "TTYUSB" in dispositivo or "TTYACM" in dispositivo or dispositivo.startswith("COM"):
        puntaje += 1
    return puntaje


def elegir_puerto(puertos) -> str | None:
    if len(puertos) == 1 and puntaje_puerto(puertos[0]) >= 0:
        return puertos[0].device
    destacados = [puerto for puerto in puertos if puntaje_puerto(puerto) >= 2]
    if len(destacados) == 1:
        return destacados[0].device
    return None


def imprimir_puertos(puertos) -> None:
    if not puertos:
        print("No hay puertos serie.")
        print(
            "Si el adaptador no aparece, el problema es el USB o el driver, "
            "no el jumper de 3.3 V / 5 V. Con el jumper en 5 V el puerto sigue existiendo "
            "y lo que falla es la respuesta del sensor."
        )
        return
    print("Puertos serie:")
    for puerto in puertos:
        print(f"  {describir_puerto(puerto)}")


def abrir_puerto(serial, nombre: str, baud: int):
    serie = serial.Serial()
    serie.port = nombre
    serie.baudrate = baud
    serie.bytesize = serial.EIGHTBITS
    serie.parity = serial.PARITY_NONE
    serie.stopbits = serial.STOPBITS_ONE
    serie.timeout = 0.05
    serie.write_timeout = 1
    serie.xonxoff = False
    serie.rtscts = False
    serie.dsrdtr = False
    try:
        serie.open()
    except serial.SerialException as exc:
        texto = str(exc)
        if "permission" in texto.lower() or "acceso" in texto.lower() or "denied" in texto.lower():
            abortar(
                3,
                f"Permiso denegado sobre {nombre}. En Linux agrega tu usuario al grupo dialout "
                "y vuelve a iniciar sesión: sudo usermod -aG dialout $USER",
            )
        abortar(3, f"No se pudo abrir {nombre}: {texto}")
    serie.dtr = False
    serie.rts = False
    time.sleep(0.3)
    serie.reset_input_buffer()
    return serie


def parser_argumentos() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verifica, guarda o reconoce huellas en un AS608 con adaptador TTL-USB.",
        epilog=(
            "Códigos de salida: 0 el sensor respondió y la operación funcionó, "
            "1 no hay comunicación, 2 hay comunicación pero la captura o el guardado falló, "
            "3 no se pudo abrir el puerto o falta pyserial, 4 el módulo rechazó la contraseña."
        ),
    )
    parser.add_argument("--puerto", help="Puerto serie, por ejemplo COM5 o /dev/ttyUSB0.")
    parser.add_argument("--baud", type=int, default=BAUD_FABRICA, help="Baud inicial. De fábrica es 57600.")
    parser.add_argument(
        "--password",
        type=lambda valor: int(valor, 0),
        default=0,
        help="Contraseña del módulo en decimal o hexadecimal. De fábrica es 0.",
    )
    parser.add_argument("--listar", action="store_true", help="Muestra los puertos serie y termina.")
    parser.add_argument(
        "--solo-enlace",
        action="store_true",
        help="Solo comprueba comunicación y parámetros, sin pedir una huella.",
    )
    parser.add_argument(
        "--espera",
        type=float,
        default=20.0,
        help="Segundos esperando un dedo en el cristal. Por defecto 20.",
    )
    parser.add_argument("--verbose", action="store_true", help="Imprime cada trama enviada y recibida.")
    parser.add_argument(
        "--calibrar-vacio",
        action="store_true",
        help="Guarda la foto del cristal sin dedo para que después no cuente como huella.",
    )
    parser.add_argument(
        "--guardar",
        action="store_true",
        help="Escanea el dedo y guarda la foto y sus minucias en esta computadora.",
    )
    parser.add_argument(
        "--reconocer",
        action="store_true",
        help="Escanea el dedo y lo busca entre las huellas de esta computadora.",
    )
    parser.add_argument(
        "--listar-huellas",
        action="store_true",
        help="Muestra los ID guardados en esta computadora. No usa el sensor.",
    )
    parser.add_argument(
        "--id",
        type=int,
        default=None,
        help="ID con el que se guarda la foto. Si se omite, usa el primer número libre.",
    )
    parser.add_argument(
        "--reemplazar",
        action="store_true",
        help="Con --guardar, escribe aunque el dedo o el ID ya existan.",
    )
    parser.add_argument(
        "--borrar",
        type=int,
        default=None,
        metavar="ID",
        help="Borra esa huella de esta computadora. No pide el dedo ni el sensor.",
    )
    parser.add_argument(
        "--carpeta",
        type=Path,
        default=CARPETA_HUELLAS,
        help="Carpeta de las fotos y minucias. Por defecto, huellas.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parser_argumentos().parse_args(argv)
    serial, list_ports = cargar_serial()
    puertos = list(list_ports.comports())

    if args.listar:
        imprimir_puertos(puertos)
        return 0

    if not 0 <= args.password <= 0xFFFFFFFF:
        print("La contraseña tiene que caber en 4 bytes (0 a 4294967295).")
        return 3
    if args.baud <= 0:
        print("El baud tiene que ser un entero positivo.")
        return 3
    modos = {
        "--guardar": args.guardar,
        "--reconocer": args.reconocer,
        "--listar-huellas": args.listar_huellas,
        "--solo-enlace": args.solo_enlace,
        "--calibrar-vacio": args.calibrar_vacio,
        "--borrar": args.borrar is not None,
    }
    activos = [opcion for opcion, activo in modos.items() if activo]
    if len(activos) > 1:
        print("Usa solo una de estas opciones: " + ", ".join(activos) + ".")
        return 3
    if args.id is not None and not args.guardar:
        print("--id solo se usa junto con --guardar.")
        return 3
    if args.reemplazar and not args.guardar:
        print("--reemplazar solo se usa junto con --guardar.")
        return 3
    if args.id is not None and args.id < 0:
        print("El ID empieza en 0.")
        return 3
    if args.borrar is not None and args.borrar < 0:
        print("El ID empieza en 0.")
        return 3
    if args.listar_huellas:
        informe = listar_en_pc(Informe(), args.carpeta)
        imprimir_informe(informe)
        return informe.codigo_salida
    if args.borrar is not None:
        informe = borrar_en_pc(Informe(), args.carpeta, args.borrar)
        imprimir_informe(informe)
        return informe.codigo_salida

    if args.guardar:
        modo = "guardar"
    elif args.reconocer:
        modo = "reconocer"
    elif args.listar_huellas:
        modo = "listar"
    elif args.borrar is not None:
        modo = "borrar"
    else:
        modo = "verificar"
    titulos = {
        "guardar": "AS608 — escanear y guardar en la computadora",
        "reconocer": "AS608 — reconocer en la computadora",
        "listar": "AS608 — huellas en la computadora",
        "borrar": "AS608 — borrar huella de la computadora",
    }

    nombre = args.puerto or elegir_puerto(puertos)

    if not nombre:
        imprimir_puertos(puertos)
        print("Indica el adaptador con --puerto.")
        return 3

    print(titulos.get(modo, "AS608 — verificación con adaptador TTL-USB"))
    print(f"Puerto: {nombre}")
    print(f"Baud inicial: {args.baud}  8N1  sin control de flujo")
    print()

    serie = abrir_puerto(serial, nombre, args.baud)
    sensor = AS608(serie, verbose=args.verbose)
    try:
        informe = verificar(
            sensor,
            baud_inicial=args.baud,
            password=args.password,
            probar_dedo=not args.solo_enlace,
            espera=args.espera,
            calibrar_vacio=args.calibrar_vacio,
            modo=modo,
            identificador=args.borrar if args.borrar is not None else args.id,
            reemplazar=args.reemplazar,
            carpeta=args.carpeta,
        )
    except KeyboardInterrupt:
        print("\nPrueba interrumpida.")
        return 3
    finally:
        serie.close()

    informe.puerto = nombre
    imprimir_informe(informe)
    return informe.codigo_salida


if __name__ == "__main__":
    sys.exit(main())
