#!/usr/bin/env python3
"""Prueba de minucias con Gabor, aparte del comparador de verificar_as608.py.

Este módulo no contesta a 57600. El registro dice 57600, pero el reloj va
a 14/12 y los bits salen a 67200. Adafruit lee cada paquete de un tirón;
este adaptador parte los bytes, así que la foto se baja con el mismo lector
que verificar_as608.py.

Hace falta, además de requirements.txt:

    pip install fingerprint-enhancer fingerprint-feature-extractor
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

try:
    from .huella_pc import _quitar_bandas, decodificar_imagen, escribir_png
    from .verificar_as608 import (
        ALTO_IMAGEN,
        ANCHO_IMAGEN,
        AS608,
        BAUDS_CONOCIDOS,
        CAPTURAR_IMAGEN,
        Paquete,
        TIEMPO_DESCARGA,
        SinRespuesta,
        abrir_puerto,
        buscar_baud,
        cargar_serial,
        hex_bytes,
    )
except ImportError:
    from huella_pc import _quitar_bandas, decodificar_imagen, escribir_png
    from verificar_as608 import (
        ALTO_IMAGEN,
        ANCHO_IMAGEN,
        AS608,
        BAUDS_CONOCIDOS,
        CAPTURAR_IMAGEN,
        Paquete,
        TIEMPO_DESCARGA,
        SinRespuesta,
        abrir_puerto,
        buscar_baud,
        cargar_serial,
        hex_bytes,
    )

BAUD = 67200
UMBRAL = 0.35
MIN_COMUNES = 8
TOMA_TOTAL = 4
GIROS = (-12.0, -6.0, 0.0, 6.0, 12.0)
DESPLAZAMIENTOS = (-24.0, -16.0, -8.0, 0.0, 8.0, 16.0, 24.0)
CARPETA = Path("huellas-gabor")
AVISOS_REGISTRO = (
    "Toma {n} de {total}. Apoya el centro del dedo, con presión media, y pulsa Enter.",
    "Toma {n} de {total}. Levanta el dedo y vuelve a apoyar el centro, igual que la primera.",
    "Toma {n} de {total}. Otra vez el centro, con la misma presión.",
    "Toma {n} de {total}. Última vez: el centro del mismo dedo.",
)


def a_uint8(imagen: np.ndarray) -> np.ndarray:
    if imagen.dtype == bool:
        return np.where(imagen, np.uint8(255), np.uint8(0))
    return np.asarray(imagen, dtype=np.uint8)


def nombre_util(nombre: str) -> bool:
    if not nombre or nombre in (".", "..") or nombre.endswith((" ", ".")):
        return False
    return not any(caracter in nombre for caracter in '/\\:*?"<>|')


def guardar_png(carpeta: Path, pixeles: bytes, nombre: str) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / nombre
    escribir_png(ruta, pixeles, ANCHO_IMAGEN, ALTO_IMAGEN)
    return ruta


def borrar_todas(carpeta: Path) -> int:
    if not carpeta.is_dir():
        return 0
    borrados = 0
    for ruta in list(carpeta.iterdir()):
        if ruta.is_file() and ruta.suffix.lower() in {".npz", ".png"}:
            ruta.unlink()
            borrados += 1
    return borrados


def tomar_foto(
    sensor: AS608,
    aviso: str = "Apoya el dedo y pulsa Enter.",
    carpeta: Path | None = None,
    copia: str | None = None,
) -> tuple[np.ndarray, bytes] | None:
    print(aviso)
    input()
    print("Esperando 3 segundos. Apoya el dedo y no lo muevas.")
    time.sleep(3)
    try:
        imagen = sensor.comando(CAPTURAR_IMAGEN, timeout=3)
    except Exception as exc:
        print(f"GenImg no contestó: {exc}")
        return None
    codigo = imagen.datos[0]
    if codigo != 0x00:
        print(f"GenImg 0x{codigo:02X}.")
        return None
    print("Descargando la foto...")
    codigo_bajada, crudo = sensor.bajar_imagen(TIEMPO_DESCARGA)
    if not crudo:
        print("No llegó la foto completa.")
        return None
    pixeles = decodificar_imagen(crudo, ANCHO_IMAGEN, ALTO_IMAGEN)
    if pixeles is None:
        print(f"Llegaron {len(crudo)} bytes. No forman una foto de {ANCHO_IMAGEN}×{ALTO_IMAGEN}.")
        return None
    print(f"Foto de {len(crudo)} bytes.")
    if carpeta is not None:
        ruta = guardar_png(carpeta, pixeles, "ultimo.png")
        print(f"Foto guardada en {ruta.resolve()}.")
        if copia:
            copia_ruta = guardar_png(carpeta, pixeles, copia)
            print(f"Copia en {copia_ruta.resolve()}.")
    limpio = _quitar_bandas(pixeles, ANCHO_IMAGEN, ALTO_IMAGEN)
    imagen = np.frombuffer(limpio, dtype=np.uint8).reshape((ALTO_IMAGEN, ANCHO_IMAGEN)).copy()
    return imagen, pixeles


def extraer_minucias(img_gris: np.ndarray, verbose: bool = True) -> np.ndarray | None:
    import fingerprint_enhancer
    import fingerprint_feature_extractor

    if verbose:
        print("Procesando la foto...")
    realce = a_uint8(fingerprint_enhancer.enhance_fingerprint(img_gris, resize=False))
    terminaciones, bifurcaciones = fingerprint_feature_extractor.extract_minutiae_features(
        realce,
        spuriousMinutiaeThresh=10,
        invertImage=False,
        showResult=False,
        saveResult=False,
    )
    puntos = []
    for minutia, tipo in ((m, 1.0) for m in terminaciones):
        if not minutia.Orientation:
            continue
        angulo = float(minutia.Orientation[0])
        if angulo != angulo:
            continue
        puntos.append([float(minutia.locY), float(minutia.locX), np.deg2rad(angulo), tipo])
    for minutia in bifurcaciones:
        if not minutia.Orientation:
            continue
        angulo = float(minutia.Orientation[0])
        if angulo != angulo:
            continue
        puntos.append([float(minutia.locY), float(minutia.locX), np.deg2rad(angulo), 3.0])
    if not puntos:
        return None
    matriz = np.array(puntos, dtype=np.float32)
    matriz[:, 0] -= np.mean(matriz[:, 0])
    matriz[:, 1] -= np.mean(matriz[:, 1])
    return matriz


def _rotar(captura: np.ndarray, theta: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    coseno, seno = np.cos(theta), np.sin(theta)
    x_rot = captura[:, 0] * coseno - captura[:, 1] * seno
    y_rot = captura[:, 0] * seno + captura[:, 1] * coseno
    return x_rot, y_rot, captura[:, 2] + theta


def _coincidencias(
    captura: np.ndarray,
    guardada: np.ndarray,
    theta: float,
    dist_tol: float,
    ang_tol: float,
    tx: float = 0.0,
    ty: float = 0.0,
) -> tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x_rot, y_rot, angulo = _rotar(captura, theta)
    x_rot = x_rot + tx
    y_rot = y_rot + ty
    dx = x_rot[:, None] - guardada[None, :, 0]
    dy = y_rot[:, None] - guardada[None, :, 1]
    dist_sq = dx * dx + dy * dy
    diferencia = np.abs(
        np.arctan2(
            np.sin(angulo[:, None] - guardada[None, :, 2]),
            np.cos(angulo[:, None] - guardada[None, :, 2]),
        )
    )
    mismo_tipo = captura[:, 3][:, None] == guardada[None, :, 3]
    coincidencias = (dist_sq <= dist_tol ** 2) & (diferencia <= ang_tol) & mismo_tipo
    pares = int(np.sum(np.any(coincidencias, axis=1)))
    puntaje = (2.0 * pares) / (len(captura) + len(guardada))
    return puntaje, x_rot, y_rot, angulo, dist_sq, coincidencias


def _pose_mas_quieta(delta: float, tx: float, ty: float, otra_delta: float, otra_tx: float, otra_ty: float) -> bool:
    costo = abs(delta) + (tx * tx + ty * ty) ** 0.5
    otro = abs(otra_delta) + (otra_tx * otra_tx + otra_ty * otra_ty) ** 0.5
    return costo < otro


def _mejor_vista(
    captura: np.ndarray,
    guardada: np.ndarray,
    dist_tol: float = 14.0,
    ang_tol: float = 0.35,
) -> tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    mejor = None
    pose = (0.0, 0.0, 0.0)
    for delta in GIROS:
        theta = np.deg2rad(delta)
        for tx in DESPLAZAMIENTOS:
            for ty in DESPLAZAMIENTOS:
                vista = _coincidencias(captura, guardada, theta, dist_tol, ang_tol, tx, ty)
                if mejor is None or vista[0] > mejor[0] + 1e-9 or (
                    abs(vista[0] - mejor[0]) <= 1e-9 and _pose_mas_quieta(delta, tx, ty, *pose)
                ):
                    mejor = vista
                    pose = (delta, tx, ty)
    assert mejor is not None
    return mejor


def comparar_rapido(captura: np.ndarray, guardada: np.ndarray, dist_tol: float = 14.0, ang_tol: float = 0.35) -> float:
    return float(_mejor_vista(captura, guardada, dist_tol, ang_tol)[0])


def combinar_tomas(
    primera: np.ndarray,
    segunda: np.ndarray,
    dist_tol: float = 14.0,
    ang_tol: float = 0.35,
    umbral: float = UMBRAL,
) -> tuple[float, np.ndarray | None]:
    """Promedia las minucias que aparecen en las dos tomas, ya alineadas."""
    puntaje, x_rot, y_rot, angulo, dist_sq, coincidencias = _mejor_vista(segunda, primera, dist_tol, ang_tol)
    if puntaje < umbral:
        return float(puntaje), None
    candidatos = np.argwhere(coincidencias)
    if len(candidatos) == 0:
        return float(puntaje), None
    orden = np.argsort(dist_sq[candidatos[:, 0], candidatos[:, 1]])
    usados_segunda: set[int] = set()
    usados_primera: set[int] = set()
    puntos = []
    for indice in orden:
        i = int(candidatos[indice, 0])
        j = int(candidatos[indice, 1])
        if i in usados_segunda or j in usados_primera:
            continue
        usados_segunda.add(i)
        usados_primera.add(j)
        angulo_a = float(primera[j, 2])
        angulo_b = float(angulo[i])
        puntos.append(
            [
                (float(primera[j, 0]) + float(x_rot[i])) / 2.0,
                (float(primera[j, 1]) + float(y_rot[i])) / 2.0,
                float(np.arctan2(np.sin(angulo_a) + np.sin(angulo_b), np.cos(angulo_a) + np.cos(angulo_b))),
                float(primera[j, 3]),
            ]
        )
    if len(puntos) < MIN_COMUNES:
        return float(puntaje), None
    matriz = np.array(puntos, dtype=np.float32)
    matriz[:, 0] -= np.mean(matriz[:, 0])
    matriz[:, 1] -= np.mean(matriz[:, 1])
    return float(puntaje), matriz


def fusionar_plantilla(
    tomas: list[np.ndarray],
    dist_tol: float = 14.0,
    ang_tol: float = 0.35,
) -> np.ndarray | None:
    """Deja una sola plantilla con las minucias que se repiten en las tomas."""
    if len(tomas) < 2:
        return None
    referencia_i = max(range(len(tomas)), key=lambda indice: len(tomas[indice]))
    referencia = tomas[referencia_i]
    observaciones: list[list[tuple[float, float, float]]] = [
        [(float(punto[0]), float(punto[1]), float(punto[2]))] for punto in referencia
    ]
    for indice, toma in enumerate(tomas):
        if indice == referencia_i:
            continue
        _puntaje, x_rot, y_rot, angulo, dist_sq, coincidencias = _mejor_vista(toma, referencia, dist_tol, ang_tol)
        candidatos = np.argwhere(coincidencias)
        if len(candidatos) == 0:
            continue
        orden = np.argsort(dist_sq[candidatos[:, 0], candidatos[:, 1]])
        usados_toma: set[int] = set()
        usados_ref: set[int] = set()
        for fila in orden:
            i = int(candidatos[fila, 0])
            j = int(candidatos[fila, 1])
            if i in usados_toma or j in usados_ref:
                continue
            usados_toma.add(i)
            usados_ref.add(j)
            observaciones[j].append((float(x_rot[i]), float(y_rot[i]), float(angulo[i])))
    puntos = []
    for j, grupo in enumerate(observaciones):
        if len(grupo) < 2:
            continue
        senos = sum(np.sin(punto[2]) for punto in grupo)
        cosenos = sum(np.cos(punto[2]) for punto in grupo)
        puntos.append(
            [
                float(np.mean([punto[0] for punto in grupo])),
                float(np.mean([punto[1] for punto in grupo])),
                float(np.arctan2(senos, cosenos)),
                float(referencia[j, 3]),
            ]
        )
    if len(puntos) < MIN_COMUNES:
        return None
    matriz = np.array(puntos, dtype=np.float32)
    matriz[:, 0] -= np.mean(matriz[:, 0])
    matriz[:, 1] -= np.mean(matriz[:, 1])
    return matriz


def cargar_padron(carpeta: Path) -> dict[str, list[np.ndarray]]:
    padron = {}
    if not carpeta.is_dir():
        return padron
    for ruta in sorted(carpeta.glob("*.npz")):
        datos = np.load(ruta)
        claves = sorted(
            (clave for clave in datos.files if clave.startswith("toma_")),
            key=lambda clave: int(clave.split("_", 1)[1]),
        )
        if claves:
            padron[ruta.stem] = [np.asarray(datos[clave], dtype=np.float32) for clave in claves]
        elif "minucias" in datos.files:
            padron[ruta.stem] = [np.asarray(datos["minucias"], dtype=np.float32)]
    return padron


def guardar_usuario(carpeta: Path, nombre: str, minucias: np.ndarray) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    np.savez(carpeta / f"{nombre}.npz", minucias=minucias)


def mejor_puntaje(viva: np.ndarray, tomas: list[np.ndarray]) -> float:
    return max(comparar_rapido(viva, toma) for toma in tomas)


def registrar(sensor: AS608, carpeta: Path, nombre: str) -> np.ndarray | None:
    """Cuatro apoyos del centro. Las minucias que se repiten forman una plantilla."""
    tomas: list[np.ndarray] = []
    for numero, plantilla in enumerate(AVISOS_REGISTRO, start=1):
        aviso = plantilla.format(n=numero, total=TOMA_TOTAL)
        aceptada = None
        for _intento in range(3):
            tomada = tomar_foto(sensor, aviso, carpeta, f"{nombre}-{numero}.png")
            if tomada is None:
                print("Esa foto no llegó. Repite el centro del mismo dedo.")
                continue
            foto, _png = tomada
            minucias = extraer_minucias(foto)
            if minucias is None or len(minucias) < MIN_COMUNES:
                print("Esa toma no tiene suficientes minucias. Apoya otra vez el centro.")
                continue
            if tomas:
                parecido = comparar_rapido(minucias, tomas[0])
                if parecido < UMBRAL:
                    print(
                        f"Esta toma se parece en {parecido:.3f} a la primera. "
                        f"Hace falta {UMBRAL:.2f}. Apoya otra vez el centro, igual que antes."
                    )
                    continue
                print(f"Toma {numero} lista, {len(minucias)} minucias. Parecido con la primera: {parecido:.3f}.")
            else:
                print(f"Toma {numero} lista, {len(minucias)} minucias.")
            aceptada = minucias
            break
        if aceptada is None:
            print(f"No pude aceptar la toma {numero}.")
            return None
        print(f"Foto: {(carpeta / f'{nombre}-{numero}.png').resolve()}")
        tomas.append(aceptada)
    return fusionar_plantilla(tomas)


def afirmar_baud(sensor: AS608, baud: int) -> None:
    """Vuelve a programar la velocidad después de abrir el puerto.

    En Windows, bajar DTR al abrir puede dejar el adaptador en 9600 aunque
    Python siga creyendo que está en 67200. Pasar por 9600 obliga a
    reescribir el registro del chip.
    """
    if getattr(sensor.serie, "baudrate", None) == baud:
        try:
            sensor.serie.baudrate = 9600
        except (OSError, ValueError):
            pass
    sensor.cambiar_baud(baud)


def acordar_baud(
    sensor: AS608,
    baud: int,
    pausa: float = 0.15,
    timeout: float = 1.0,
    timeout_barrido: float = 0.45,
) -> tuple[int, Paquete]:
    afirmar_baud(sensor, baud)
    for intento in range(3):
        encontrado = buscar_baud(sensor, [baud], 0, timeout, anunciar=False)
        if encontrado:
            return encontrado
        if intento < 2:
            time.sleep(pausa)
    otros = [otro for otro in BAUDS_CONOCIDOS if otro != baud]
    print(f"Sin respuesta a {baud}. Probando las otras velocidades del AS608.")
    encontrado = buscar_baud(sensor, otros, 0, timeout_barrido, anunciar=True)
    if encontrado is None:
        raise SinRespuesta(sensor.ultimo_ruido)
    return encontrado


def enlazar(puerto: str, baud: int) -> AS608:
    serial, _ = cargar_serial()
    serie = abrir_puerto(serial, puerto, baud)
    sensor = AS608(serie)
    try:
        baud_ok, respuesta = acordar_baud(sensor, baud)
    except SinRespuesta:
        ruido = sensor.ultimo_ruido
        serie.close()
        if ruido:
            raise SystemExit(
                f"Llegaron bytes en {puerto} ({hex_bytes(ruido[:24])}) y ninguno formó una trama del AS608. "
                "Revisa el cable del TX del sensor: dos resistencias de 1 kΩ de ese nodo a GND. "
                "En el RX del adaptador tienen que quedar unos 3.2 V."
            )
        raise SystemExit(
            f"{puerto} abrió y el sensor no envió nada, ni a {baud} ni en el resto de velocidades. "
            f"Cierra lo que tenga {puerto} abierto, desconecta el USB y vuelve a conectarlo. "
            "Jumper en 3.3 V, rojo del sensor en el pin de 5 V, tierras unidas."
        )
    if respuesta.datos[0] != 0x00:
        serie.close()
        raise SystemExit(f"Contraseña rechazada, código 0x{respuesta.datos[0]:02X}.")
    if baud_ok != baud:
        print(f"El módulo contestó a {baud_ok}. Sigo en {baud_ok}.")
    return sensor


def menu(sensor: AS608, carpeta: Path) -> None:
    padron = cargar_padron(carpeta)
    while True:
        print(f"\n--- Prueba Gabor ({len(padron)} usuarios en {carpeta}) ---")
        print("1. Registrar")
        print("2. Identificar")
        print("3. Borrar todas")
        print("4. Salir")
        opcion = input("Elige una opción: ").strip()
        if opcion == "1":
            nombre = input("Nombre: ").strip()
            if not nombre_util(nombre):
                print("Ese nombre no sirve.")
                continue
            print("Cuatro tomas del centro del mismo dedo. Con las que coincidan se arma una sola plantilla.")
            plantilla = registrar(sensor, carpeta, nombre)
            if plantilla is None:
                print(f"No guardé a {nombre}.")
                continue
            padron[nombre] = [plantilla]
            guardar_usuario(carpeta, nombre, plantilla)
            print(f"{nombre} quedó con {len(plantilla)} minucias en la plantilla.")
        elif opcion == "2":
            if not padron:
                print("No hay usuarios. Registra uno primero.")
                continue
            tomada = tomar_foto(sensor, carpeta=carpeta)
            if tomada is None:
                continue
            foto, _png = tomada
            inicio = time.perf_counter()
            vivas = extraer_minucias(foto)
            if vivas is None:
                print("No salieron minucias.")
                continue
            mejor_nombre = None
            mejor = 0.0
            marca = time.perf_counter()
            for nombre, tomas in padron.items():
                puntaje = mejor_puntaje(vivas, tomas)
                print(f"  {nombre}: {puntaje:.3f}")
                if puntaje >= UMBRAL and puntaje > mejor:
                    mejor = puntaje
                    mejor_nombre = nombre
            latencia = (time.perf_counter() - marca) * 1000
            if mejor_nombre:
                print(f"Identificado: {mejor_nombre} (puntaje {mejor:.3f})")
            else:
                print(f"No coincide con nadie. Hace falta {UMBRAL:.2f}.")
            print(f"Comparación: {latencia:.0f} ms. Procesado total: {(time.perf_counter() - inicio):.1f} s.")
        elif opcion == "3":
            if not padron and not (carpeta.is_dir() and any(carpeta.glob("*.png"))):
                print("No hay huellas guardadas.")
                continue
            print(f"Hay {len(padron)} usuarios en {carpeta}.")
            confirma = input("Escribe si para borrarlas todas: ").strip().lower()
            if confirma not in ("si", "sí"):
                print("No borré nada.")
                continue
            borrados = borrar_todas(carpeta)
            padron.clear()
            print(f"Borré {borrados} archivos de {carpeta.resolve()}.")
        elif opcion == "4":
            sensor.serie.close()
            return
        else:
            print("Elige 1, 2, 3 o 4.")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Prueba de minucias con Gabor sobre el AS608.")
    parser.add_argument("--puerto", required=True, help="Por ejemplo COM4 o /dev/cu.usbserial-A5069RR4.")
    parser.add_argument("--baud", type=int, default=BAUD, help="Velocidad real del cable. En este módulo, 67200.")
    parser.add_argument("--carpeta", type=Path, default=CARPETA)
    args = parser.parse_args()
    try:
        import fingerprint_enhancer  # noqa: F401
        import fingerprint_feature_extractor  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Faltan las librerías de Gabor. Instala: "
            "pip install fingerprint-enhancer fingerprint-feature-extractor"
        )
    sensor = enlazar(args.puerto, args.baud)
    print(f"Enlace listo en {args.puerto} a {args.baud}.")
    menu(sensor, args.carpeta)


if __name__ == "__main__":
    main()
