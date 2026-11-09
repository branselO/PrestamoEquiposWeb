"""Comparación 1:N de huellas en la computadora.

El AS608 solo entrega la foto. Las minucias, el puntaje y el archivo viven aquí.
"""

from __future__ import annotations

import json
import math
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ANCHO = 256
ALTO = 288
UMBRAL = 55
COHERENCIA_MINIMA = 0.4
MINUCIAS_MINIMAS = 8
MINUCIAS_MAXIMAS = 80


@dataclass
class Minucia:
    x: int
    y: int
    angulo: float
    tipo: int


@dataclass
class Analisis:
    pixeles: bytes
    ancho: int
    alto: int
    minucias: list[Minucia]
    coherencia: float
    util: bool
    motivo: str = ""


@dataclass
class Registro:
    identificador: int
    minucias: list[Minucia]
    coherencia: float
    archivo: str


def decodificar_imagen(crudo: bytes, ancho: int = ANCHO, alto: int = ALTO) -> bytes | None:
    cantidad = ancho * alto
    if len(crudo) >= cantidad:
        return bytes(crudo[:cantidad])
    if len(crudo) < cantidad // 2:
        return None
    pixeles = bytearray(cantidad)
    origen = crudo[: cantidad // 2]
    destino = 0
    for valor in origen:
        pixeles[destino] = (valor >> 4) * 17
        pixeles[destino + 1] = (valor & 0x0F) * 17
        destino += 2
    return bytes(pixeles)


def _orientacion(pixeles: bytes, ancho: int, alto: int, bloque: int = 8):
    angulos: list[list[float]] = []
    coherencias: list[list[float]] = []
    suma = 0.0
    bloques = 0
    for y0 in range(0, alto, bloque):
        fila_a: list[float] = []
        fila_c: list[float] = []
        for x0 in range(0, ancho, bloque):
            gxx = 0.0
            gyy = 0.0
            gxy = 0.0
            y1 = min(y0 + bloque, alto - 1)
            x1 = min(x0 + bloque, ancho - 1)
            for y in range(max(y0, 1), y1):
                fila = y * ancho
                for x in range(max(x0, 1), x1):
                    gx = float(pixeles[fila + x + 1]) - float(pixeles[fila + x - 1])
                    gy = float(pixeles[fila + ancho + x]) - float(pixeles[fila - ancho + x])
                    gxx += gx * gx
                    gyy += gy * gy
                    gxy += gx * gy
            energia = gxx + gyy
            if energia < 1.0:
                fila_a.append(0.0)
                fila_c.append(0.0)
                continue
            coherencia = math.hypot(gxx - gyy, 2.0 * gxy) / energia
            angulo = 0.5 * math.atan2(2.0 * gxy, gxx - gyy) + math.pi / 2.0
            fila_a.append(angulo)
            fila_c.append(coherencia)
            suma += coherencia
            bloques += 1
        angulos.append(fila_a)
        coherencias.append(fila_c)
    media = suma / bloques if bloques else 0.0
    return angulos, coherencias, media, bloque


def _muestra(pixeles: bytes, ancho: int, alto: int, x: float, y: float) -> int:
    ix = int(round(x))
    iy = int(round(y))
    if ix < 0 or iy < 0 or ix >= ancho or iy >= alto:
        return 255
    return pixeles[iy * ancho + ix]


def _realzar(pixeles: bytes, ancho: int, alto: int, angulos, bloque: int) -> bytearray:
    salida = bytearray(ancho * alto)
    for y in range(alto):
        by = min(y // bloque, len(angulos) - 1)
        for x in range(ancho):
            bx = min(x // bloque, len(angulos[by]) - 1)
            angulo = angulos[by][bx]
            ca = math.cos(angulo)
            sa = math.sin(angulo)
            total = 0
            for paso in (-3, -2, -1, 0, 1, 2, 3):
                total += _muestra(pixeles, ancho, alto, x + ca * paso, y + sa * paso)
            salida[y * ancho + x] = total // 7
    return salida


def _binarizar(pixeles: bytearray, ancho: int, alto: int, bloque: int = 16) -> bytearray:
    bits = bytearray(ancho * alto)
    for y0 in range(0, alto, bloque):
        for x0 in range(0, ancho, bloque):
            y1 = min(y0 + bloque, alto)
            x1 = min(x0 + bloque, ancho)
            total = 0
            cuenta = 0
            for y in range(y0, y1):
                fila = y * ancho
                for x in range(x0, x1):
                    total += pixeles[fila + x]
                    cuenta += 1
            media = total / cuenta
            for y in range(y0, y1):
                fila = y * ancho
                for x in range(x0, x1):
                    bits[fila + x] = 1 if pixeles[fila + x] < media - 4 else 0
    return bits


def _adelgazar(bits: bytearray, ancho: int, alto: int) -> None:
    def transiciones(vecinos: tuple[int, ...]) -> int:
        secuencia = vecinos + (vecinos[0],)
        return sum(1 for a, b in zip(secuencia, secuencia[1:]) if a == 0 and b == 1)

    for _ in range(30):
        cambio = False
        for paso in (0, 1):
            borrar: list[int] = []
            for y in range(1, alto - 1):
                fila = y * ancho
                for x in range(1, ancho - 1):
                    indice = fila + x
                    if bits[indice] == 0:
                        continue
                    p2 = bits[indice - ancho]
                    p4 = bits[indice + 1]
                    p6 = bits[indice + ancho]
                    p8 = bits[indice - 1]
                    p3 = bits[indice - ancho + 1]
                    p5 = bits[indice + ancho + 1]
                    p7 = bits[indice + ancho - 1]
                    p9 = bits[indice - ancho - 1]
                    vecinos = (p2, p3, p4, p5, p6, p7, p8, p9)
                    cuenta = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
                    if cuenta < 2 or cuenta > 6 or transiciones(vecinos) != 1:
                        continue
                    if paso == 0:
                        if p2 * p4 * p6 or p4 * p6 * p8:
                            continue
                    elif p2 * p4 * p8 or p2 * p6 * p8:
                        continue
                    borrar.append(indice)
            if not borrar:
                continue
            cambio = True
            for indice in borrar:
                bits[indice] = 0
        if not cambio:
            break


def _cruz(bits: bytearray, ancho: int, x: int, y: int) -> int:
    indice = y * ancho + x
    orden = (
        bits[indice - ancho],
        bits[indice - ancho + 1],
        bits[indice + 1],
        bits[indice + ancho + 1],
        bits[indice + ancho],
        bits[indice + ancho - 1],
        bits[indice - 1],
        bits[indice - ancho - 1],
    )
    secuencia = orden + (orden[0],)
    cambios = sum(1 for a, b in zip(secuencia, secuencia[1:]) if a == 0 and b == 1)
    return cambios


def _minucias(bits: bytearray, ancho: int, alto: int, angulos, coherencias, bloque: int) -> list[Minucia]:
    encontradas: list[Minucia] = []
    borde = bloque + 2
    for y in range(borde, alto - borde):
        by = min(y // bloque, len(angulos) - 1)
        fila = y * ancho
        for x in range(borde, ancho - borde):
            if bits[fila + x] == 0:
                continue
            bx = min(x // bloque, len(coherencias[by]) - 1)
            if coherencias[by][bx] < 0.25:
                continue
            cruce = _cruz(bits, ancho, x, y)
            if cruce not in (1, 3):
                continue
            encontradas.append(Minucia(x, y, angulos[by][bx] % math.pi, cruce))
    encontradas.sort(key=lambda item: (item.y, item.x))
    separadas: list[Minucia] = []
    for candidata in encontradas:
        if any(abs(candidata.x - previa.x) <= 6 and abs(candidata.y - previa.y) <= 6 for previa in separadas):
            continue
        separadas.append(candidata)
        if len(separadas) >= MINUCIAS_MAXIMAS:
            break
    return separadas


def _direccion_dominante(angulos, coherencias) -> tuple[float, float]:
    """Concentración circular de la orientación y el ángulo medio de la cresta.

    La cresta no tiene sentido, así que el promedio usa el doble del ángulo.
    """
    seno = 0.0
    coseno = 0.0
    peso = 0.0
    for fila_a, fila_c in zip(angulos, coherencias):
        for angulo, coherencia in zip(fila_a, fila_c):
            if coherencia <= 0.2:
                continue
            seno += coherencia * math.sin(2.0 * angulo)
            coseno += coherencia * math.cos(2.0 * angulo)
            peso += coherencia
    if peso < 1.0:
        return 0.0, 0.0
    return math.hypot(seno, coseno) / peso, 0.5 * math.atan2(seno, coseno)


def _periodo_normal(pixeles: bytes, ancho: int, alto: int, angulo: float) -> int | None:
    """Primer pico de autocorrelación, en píxeles, cruzando las crestas."""
    normal_x = -math.sin(angulo)
    normal_y = math.cos(angulo)
    lateral_x = -normal_y
    lateral_y = normal_x
    largo = max(24, int(min(ancho, alto) * 0.85))
    perfiles = 16
    separacion = min(ancho, alto) / (perfiles + 1)
    acumulado = [0.0] * largo
    cuenta = [0] * largo
    centro_x = (ancho - 1) / 2.0
    centro_y = (alto - 1) / 2.0
    for perfil in range(perfiles):
        desplazamiento = (perfil - (perfiles - 1) / 2.0) * separacion
        origen_x = centro_x + lateral_x * desplazamiento - normal_x * (largo / 2.0)
        origen_y = centro_y + lateral_y * desplazamiento - normal_y * (largo / 2.0)
        for paso in range(largo):
            x = int(round(origen_x + normal_x * paso))
            y = int(round(origen_y + normal_y * paso))
            if x < 0 or y < 0 or x >= ancho or y >= alto:
                continue
            acumulado[paso] += pixeles[y * ancho + x]
            cuenta[paso] += 1
    serie = [acumulado[i] / cuenta[i] for i in range(largo) if cuenta[i]]
    if len(serie) < 24:
        return None
    media = sum(serie) / len(serie)
    centrada = [valor - media for valor in serie]
    autocorrelacion: dict[int, float] = {}
    for retraso in range(2, 24):
        if retraso >= len(centrada) - 4:
            break
        producto = 0.0
        energia_a = 0.0
        energia_b = 0.0
        for indice in range(len(centrada) - retraso):
            a = centrada[indice]
            b = centrada[indice + retraso]
            producto += a * b
            energia_a += a * a
            energia_b += b * b
        denominador = math.sqrt(energia_a * energia_b)
        autocorrelacion[retraso] = producto / denominador if denominador else 0.0
    for retraso in range(3, 23):
        valor = autocorrelacion.get(retraso)
        anterior = autocorrelacion.get(retraso - 1)
        siguiente = autocorrelacion.get(retraso + 1)
        if valor is None or anterior is None or siguiente is None:
            continue
        if valor > 0.2 and valor >= anterior and valor >= siguiente:
            return retraso
    return None


def _quitar_bandas(pixeles: bytes, ancho: int, alto: int) -> bytes:
    """Quita la franja de la lámpara, que cruza toda la fila con el mismo brillo."""
    total = sum(pixeles) / len(pixeles)
    salida = bytearray(len(pixeles))
    for y in range(alto):
        inicio = y * ancho
        media = sum(pixeles[inicio : inicio + ancho]) / ancho
        for x in range(ancho):
            valor = pixeles[inicio + x] - media + total
            if valor < 0:
                valor = 0
            elif valor > 255:
                valor = 255
            salida[inicio + x] = int(round(valor))
    return bytes(salida)


def analizar(pixeles: bytes, ancho: int = ANCHO, alto: int = ALTO) -> Analisis:
    angulos, coherencias, _, _ = _orientacion(pixeles, ancho, alto)
    concentracion, angulo = _direccion_dominante(angulos, coherencias)
    if concentracion >= 0.9:
        periodo = _periodo_normal(pixeles, ancho, alto, angulo)
        if periodo is not None and periodo <= 5:
            return Analisis(pixeles, ancho, alto, [], 0.0, False, "rejilla")
    limpio = _quitar_bandas(pixeles, ancho, alto)
    angulos, coherencias, media, bloque = _orientacion(limpio, ancho, alto)
    if concentracion >= 0.9 and media < COHERENCIA_MINIMA:
        return Analisis(pixeles, ancho, alto, [], media, False, "rejilla")
    realce = _realzar(limpio, ancho, alto, angulos, bloque)
    bits = _binarizar(realce, ancho, alto)
    _adelgazar(bits, ancho, alto)
    minucias = _minucias(bits, ancho, alto, angulos, coherencias, bloque)
    util = media >= COHERENCIA_MINIMA and MINUCIAS_MINIMAS <= len(minucias) <= MINUCIAS_MAXIMAS
    return Analisis(pixeles, ancho, alto, minucias, media, util, "")


def _diferencia_angular(a: float, b: float) -> float:
    delta = abs(a - b) % math.pi
    return min(delta, math.pi - delta)


def comparar_minucias(origen: list[Minucia], destino: list[Minucia]) -> int:
    if len(origen) < MINUCIAS_MINIMAS or len(destino) < MINUCIAS_MINIMAS:
        return 0
    mejor = 0
    referencias_a = origen[:16]
    referencias_b = destino[:16]
    for base_a in referencias_a:
        for base_b in referencias_b:
            if base_a.tipo != base_b.tipo:
                continue
            giro = base_b.angulo - base_a.angulo
            coseno = math.cos(giro)
            seno = math.sin(giro)
            usados: set[int] = set()
            pares = 0
            for punto in origen:
                dx = punto.x - base_a.x
                dy = punto.y - base_a.y
                x = dx * coseno - dy * seno + base_b.x
                y = dx * seno + dy * coseno + base_b.y
                angulo = (punto.angulo + giro) % math.pi
                for indice, candidato in enumerate(destino):
                    if indice in usados or candidato.tipo != punto.tipo:
                        continue
                    if abs(candidato.x - x) > 12 or abs(candidato.y - y) > 12:
                        continue
                    if _diferencia_angular(candidato.angulo, angulo) > 0.45:
                        continue
                    usados.add(indice)
                    pares += 1
                    break
            if pares > mejor:
                mejor = pares
    return int(round(100 * 2 * mejor / (len(origen) + len(destino))))


def guardar_vista(carpeta: Path, pixeles: bytes, ancho: int, alto: int) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / "ultimo.png"
    escribir_png(ruta, pixeles, ancho, alto)
    return ruta


def png_de_pixeles(pixeles: bytes, ancho: int, alto: int) -> bytes:
    """PNG en escala de grises, listo para mostrarse en el navegador."""

    def trozo(etiqueta: bytes, datos: bytes) -> bytes:
        crc = zlib.crc32(etiqueta + datos) & 0xFFFFFFFF
        return struct.pack(">I", len(datos)) + etiqueta + datos + struct.pack(">I", crc)

    filas = bytearray()
    for y in range(alto):
        filas.append(0)
        inicio = y * ancho
        filas.extend(pixeles[inicio : inicio + ancho])
    ihdr = struct.pack(">IIBBBBB", ancho, alto, 8, 0, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", ihdr) + trozo(b"IDAT", zlib.compress(bytes(filas), 6))
    return png + trozo(b"IEND", b"")


def escribir_png(ruta: Path, pixeles: bytes, ancho: int, alto: int) -> None:
    ruta.write_bytes(png_de_pixeles(pixeles, ancho, alto))


def _a_json(minucias: list[Minucia]) -> list[dict]:
    return [
        {"x": item.x, "y": item.y, "angulo": round(item.angulo, 5), "tipo": item.tipo}
        for item in minucias
    ]


def _desde_json(datos: list[dict]) -> list[Minucia]:
    return [Minucia(int(item["x"]), int(item["y"]), float(item["angulo"]), int(item["tipo"])) for item in datos]


def cargar_registros(carpeta: Path) -> list[Registro]:
    if not carpeta.is_dir():
        return []
    registros = []
    for ruta in sorted(carpeta.glob("*.json"), key=lambda item: int(item.stem) if item.stem.isdigit() else 10**9):
        if not ruta.stem.isdigit():
            continue
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        registros.append(
            Registro(
                identificador=int(datos["id"]),
                minucias=_desde_json(datos["minucias"]),
                coherencia=float(datos.get("coherencia", 0)),
                archivo=str(datos.get("png", "")),
            )
        )
    return registros


def buscar_mejor(minucias: list[Minucia], registros: list[Registro]) -> tuple[int, int] | None:
    mejor: tuple[int, int] | None = None
    for registro in registros:
        puntaje = comparar_minucias(minucias, registro.minucias)
        if mejor is None or puntaje > mejor[0]:
            mejor = (puntaje, registro.identificador)
    return mejor


def guardar_analisis(carpeta: Path, analisis: Analisis, identificador: int | None = None) -> int:
    carpeta.mkdir(parents=True, exist_ok=True)
    ocupados = {registro.identificador for registro in cargar_registros(carpeta)}
    if identificador is None:
        identificador = 0
        while identificador in ocupados:
            identificador += 1
    base = carpeta / str(identificador)
    base.with_suffix(".raw").write_bytes(analisis.pixeles)
    escribir_png(base.with_suffix(".png"), analisis.pixeles, analisis.ancho, analisis.alto)
    documento = {
        "id": identificador,
        "ancho": analisis.ancho,
        "alto": analisis.alto,
        "coherencia": round(analisis.coherencia, 4),
        "minucias": _a_json(analisis.minucias),
        "png": f"{identificador}.png",
        "creado": datetime.now(timezone.utc).isoformat(),
    }
    base.with_suffix(".json").write_text(json.dumps(documento), encoding="utf-8")
    return identificador


def borrar_registro(carpeta: Path, identificador: int) -> bool:
    base = carpeta / str(identificador)
    existia = False
    for sufijo in (".json", ".raw", ".png"):
        ruta = base.with_suffix(sufijo)
        if ruta.is_file():
            ruta.unlink()
            existia = True
    return existia
