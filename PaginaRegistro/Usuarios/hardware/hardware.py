"""Lectura de huellas para el proyecto web.

La interfaz es la de prestamoequiposweb: `get_sensor`, `enroll_fingerprint_to_db`,
`capturar_minucias_en_vivo` y el padrón en RAM. Por dentro usa el enlace que sí
contesta en este módulo.

El registro del AS608 dice 57600. El reloj va a 14/12, así que el puerto se abre
a 67200. No hay que reescribir ese registro: si el módulo creyera que habla a
67200, el cable quedaría en 78400.

Adafruit no sirve con este adaptador: parte los paquetes USB y `get_image`
contesta bien aunque el cristal esté vacío. La foto se baja con el lector de
`verificar_as608.py`. Este clon a veces responde GenImg 0x00 sin dedo; una foto
así es la rejilla del prisma y se descarta.

Registrar pide cuatro veces el centro del mismo dedo. La foto se toma en cuanto
dos lecturas seguidas se parecen; ya no hay una pausa fija de 3 segundos. Cada toma tiene que parecerse a la
primera (0.35) y la plantilla se queda con las minucias que se repiten,
promediadas. Identificar es una sola foto. La comparación también prueba un
corrimiento de hasta 24 píxeles.

`locX` del extractor es la fila y `locY` es la columna. El realce de Gabor sale
en bool y hay que pasarlo a 0/255. Las rayas de la lámpara se quitan antes de
medir. El PNG guarda los píxeles originales.

En Django, `prueba_gabor.py`, `verificar_as608.py` y `huella_pc.py` tienen que
estar en el mismo paquete o en el PYTHONPATH. El puerto se detecta solo y
prefiere el puente Silicon Labs CP210x, con el número COM que Windows le
asigne. La velocidad también: prueba la última que contestó y, si no responde,
barre 67200, 57600, 9600 y el resto. `HUELLA_PUERTO` y `HUELLA_BAUD` la fuerzan.
"""

from __future__ import annotations

import base64
import json
import os
import time
import warnings
import zlib
from pathlib import Path

import numpy as np
import serial
import serial.tools.list_ports

try:
    from .huella_pc import _quitar_bandas, analizar, decodificar_imagen, escribir_png, png_de_pixeles
    from .prueba_gabor import (
        MIN_COMUNES,
        UMBRAL,
        acordar_baud,
        comparar_rapido,
        extraer_minucias,
        fusionar_plantilla,
    )
    from .verificar_as608 import (
        ALTO_IMAGEN,
        ANCHO_IMAGEN,
        AS608,
        CAPTURAR_IMAGEN,
        TIEMPO_DESCARGA,
        SinRespuesta,
        elegir_puerto,
    )
except ImportError:
    from huella_pc import _quitar_bandas, analizar, decodificar_imagen, escribir_png, png_de_pixeles
    from prueba_gabor import (
        MIN_COMUNES,
        UMBRAL,
        acordar_baud,
        comparar_rapido,
        extraer_minucias,
        fusionar_plantilla,
    )
    from verificar_as608 import (
        ALTO_IMAGEN,
        ANCHO_IMAGEN,
        AS608,
        CAPTURAR_IMAGEN,
        TIEMPO_DESCARGA,
        SinRespuesta,
        elegir_puerto,
    )

BAUDRATE = 67200
_baud_detectado: int | None = None
TOMA_TOTAL = 4
ESPERA_QUIETO = 1.0
QUIETO_DIFERENCIA = 12.0
ESPERA_DEDO = 60.0
ESPERA_LEVANTAR = 20.0
INTENTOS_POR_TOMA = 3
CARPETA = Path("huellas-gabor")
ESTADO_SENSOR = "Iniciando..."

AVISOS = (
    "Toma {n} de {total}. Apoya el centro del dedo, con presión media.",
    "Toma {n} de {total}. Levanta el dedo y vuelve a apoyar el centro, igual que la primera.",
    "Toma {n} de {total}. Otra vez el centro, con la misma presión.",
    "Toma {n} de {total}. Última vez: el centro del mismo dedo.",
)


def _estado(texto: str) -> None:
    global ESTADO_SENSOR
    ESTADO_SENSOR = texto


def estado_sensor() -> str:
    """Texto vivo del lector. Hay que llamarlo: el nombre importado no se actualiza."""
    return ESTADO_SENSOR


def publicar_estado(texto: str) -> None:
    _estado(texto)


def encontrar_puerto_arduino():
    """Devuelve el CP210x (Silicon Labs) o, si no hay otro, el único puerto serie."""
    forzado = os.environ.get("HUELLA_PUERTO")
    if forzado:
        return forzado
    puertos = list(serial.tools.list_ports.comports())
    elegido = elegir_puerto(puertos)
    if elegido:
        _estado(f"Puerto detectado: {elegido}")
    return elegido


def _baud_pedido() -> int:
    """Última velocidad que contestó, o la forzada con HUELLA_BAUD."""
    texto = os.environ.get("HUELLA_BAUD")
    if texto:
        try:
            return int(texto)
        except ValueError:
            pass
    if _baud_detectado:
        return _baud_detectado
    return BAUDRATE


def _abrir_serie(puerto: str, baud: int):
    serie = serial.Serial()
    serie.port = puerto
    serie.baudrate = baud
    serie.bytesize = serial.EIGHTBITS
    serie.parity = serial.PARITY_NONE
    serie.stopbits = serial.STOPBITS_ONE
    serie.timeout = 0.05
    serie.write_timeout = 1
    serie.xonxoff = False
    serie.rtscts = False
    serie.dsrdtr = False
    serie.open()
    serie.dtr = False
    serie.rts = False
    time.sleep(0.3)
    serie.reset_input_buffer()
    return serie


def get_sensor(puerto: str | None = None):
    """Abre el AS608 en el puerto y la velocidad que contesten, y devuelve lector y serie."""
    puerto = puerto or encontrar_puerto_arduino()
    if not puerto:
        _estado("Sensor no detectado.")
        raise RuntimeError(
            "No encontré el adaptador Silicon Labs CP210x. "
            "Conéctalo (aparece como USB to UART Bridge) o define HUELLA_PUERTO."
        )
    baud = _baud_pedido()
    _estado(f"Abriendo {puerto} a {baud}...")
    try:
        serie = _abrir_serie(puerto, baud)
    except serial.SerialException as exc:
        _estado("No se pudo abrir el puerto.")
        raise RuntimeError(f"No se pudo abrir {puerto}: {exc}") from exc
    sensor = AS608(serie)
    try:
        baud_ok, respuesta = acordar_baud(sensor, baud, avisar=_estado)
    except SinRespuesta:
        ruido = sensor.ultimo_ruido
        serie.close()
        _estado("El sensor no contestó.")
        if ruido:
            raise RuntimeError(
                f"Llegaron bytes en {puerto} y ninguno formó una trama del AS608. "
                "Revisa el cable del TX del sensor: dos resistencias de 1 kΩ de ese nodo a GND. "
                "En el RX del adaptador tienen que quedar unos 3.2 V."
            )
        raise RuntimeError(
            f"{puerto} abrió y el sensor no envió nada, ni a {baud} ni en el resto de velocidades. "
            f"Cierra lo que tenga {puerto} abierto, desconecta el USB y vuelve a conectarlo. "
            "Jumper en 3.3 V, rojo del sensor en el pin de 5 V, tierras unidas."
        )
    if not respuesta.datos or respuesta.datos[0] != 0x00:
        serie.close()
        _estado("Contraseña rechazada.")
        codigo = respuesta.datos[0] if respuesta.datos else 0xFF
        raise RuntimeError(f"Contraseña rechazada, código 0x{codigo:02X}.")
    global _baud_detectado
    _baud_detectado = baud_ok
    _estado(f"Sensor listo en {puerto} a {baud_ok}.")
    return sensor, serie


def _leer_foto(sensor: AS608) -> tuple[bytes | None, int | None]:
    try:
        ack = sensor.comando(CAPTURAR_IMAGEN, timeout=3)
    except Exception:
        return None, None
    if not ack.datos:
        return None, None
    codigo = ack.datos[0]
    if codigo != 0x00:
        return None, codigo
    try:
        _codigo_bajada, crudo = sensor.bajar_imagen(TIEMPO_DESCARGA)
    except Exception:
        return None, codigo
    if not crudo:
        return None, codigo
    pixeles = decodificar_imagen(crudo, ANCHO_IMAGEN, ALTO_IMAGEN)
    return pixeles, codigo


def _minucias_de_foto(pixeles: bytes) -> np.ndarray | None:
    limpio = _quitar_bandas(pixeles, ANCHO_IMAGEN, ALTO_IMAGEN)
    imagen = np.frombuffer(limpio, dtype=np.uint8).reshape((ALTO_IMAGEN, ANCHO_IMAGEN)).copy()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=FutureWarning, module=r"fingerprint_feature_extractor")
        warnings.filterwarnings("ignore", category=FutureWarning, module=r"skimage")
        minucias = extraer_minucias(imagen, verbose=False)
    if minucias is None or len(minucias) < MIN_COMUNES:
        return None
    return minucias


def _guardar_toma(carpeta: Path, pixeles: bytes, numero: int) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    escribir_png(carpeta / "ultimo.png", pixeles, ANCHO_IMAGEN, ALTO_IMAGEN)
    ruta = carpeta / f"toma-{numero}.png"
    escribir_png(ruta, pixeles, ANCHO_IMAGEN, ALTO_IMAGEN)
    return ruta


def _diferencia(primera: bytes, segunda: bytes) -> float:
    if len(primera) != len(segunda) or not primera:
        return 255.0
    a = np.frombuffer(primera, dtype=np.uint8).astype(np.int16)
    b = np.frombuffer(segunda, dtype=np.uint8).astype(np.int16)
    return float(np.mean(np.abs(a - b)))


def _esperar_apoyo(sensor: AS608, mensaje: str, limite: float) -> bytes | None:
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        _estado(mensaje)
        pixeles, codigo = _leer_foto(sensor)
        if pixeles is None:
            if codigo == 0x02:
                _estado("No hay dedo en el sensor. Apoya el centro.")
            time.sleep(0.2)
            continue
        if analizar(pixeles, ANCHO_IMAGEN, ALTO_IMAGEN).motivo == "rejilla":
            _estado("Sigo viendo el cristal. Apoya el centro del dedo, con presión media.")
            time.sleep(0.2)
            continue
        return pixeles
    return None


def _esperar_levantar(sensor: AS608, anterior: bytes, limite: float) -> None:
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        _estado("Levanta el dedo.")
        pixeles, _codigo = _leer_foto(sensor)
        if pixeles is None:
            return
        if analizar(pixeles, ANCHO_IMAGEN, ALTO_IMAGEN).motivo == "rejilla":
            return
        if _diferencia(pixeles, anterior) >= 30:
            return
        time.sleep(0.2)
    _estado("Sigo viendo el dedo.")
    raise RuntimeError("Sigo viendo el dedo. Levántalo por completo antes de la siguiente toma.")


def _confirmar_quieto(sensor: AS608, apoyo: bytes, espera: float) -> tuple[bytes | None, int | None]:
    """Segunda foto apenas el dedo deja de moverse. `espera` es el máximo, no una pausa fija."""
    if espera <= 0:
        return apoyo, 0
    _estado("Dedo detectado. Manténlo quieto.")
    pausa = min(0.2, espera)
    time.sleep(pausa)
    fin = time.monotonic() + max(0.0, espera - pausa)
    anterior = apoyo
    while True:
        pixeles, codigo = _leer_foto(sensor)
        if pixeles is None:
            if time.monotonic() >= fin:
                return None, codigo
            _estado("Se levantó el dedo. Apóyalo otra vez en el centro.")
            time.sleep(0.12)
            continue
        if analizar(pixeles, ANCHO_IMAGEN, ALTO_IMAGEN).motivo == "rejilla":
            if time.monotonic() >= fin:
                return pixeles, codigo
            _estado("Apoya el centro del dedo, con un poco más de presión.")
            anterior = None
            time.sleep(0.12)
            continue
        if anterior is not None and _diferencia(pixeles, anterior) <= QUIETO_DIFERENCIA:
            _estado("Dedo quieto. Guardando la foto...")
            return pixeles, codigo
        if time.monotonic() >= fin:
            _estado("Guardando la foto...")
            return pixeles, codigo
        anterior = pixeles
        _estado("Dedo detectado. Manténlo quieto.")
        time.sleep(0.1)


def _capturar_toma(
    sensor: AS608,
    numero: int,
    primera: np.ndarray | None,
    espera: float,
    carpeta: Path,
    limite_dedo: float,
    aviso: str | None = None,
    numerar: bool = True,
) -> tuple[bytes, np.ndarray]:
    aviso = aviso or AVISOS[numero - 1].format(n=numero, total=TOMA_TOTAL)
    for _intento in range(INTENTOS_POR_TOMA):
        apoyo = _esperar_apoyo(sensor, aviso, limite_dedo)
        if apoyo is None:
            _estado("No llegó el dedo.")
            raise RuntimeError("No llegó el dedo a tiempo. Apoya el centro del lector.")
        pixeles, codigo = _confirmar_quieto(sensor, apoyo, espera)
        if pixeles is None:
            if codigo == 0x02:
                _estado("GenImg 0x02: no hay dedo en el sensor.")
            else:
                _estado("No llegó la foto. Apoya otra vez el centro.")
            continue
        if analizar(pixeles, ANCHO_IMAGEN, ALTO_IMAGEN).motivo == "rejilla":
            _estado("La foto salió del cristal. Apoya el centro y no lo muevas.")
            continue
        _estado("Procesando la foto...")
        minucias = _minucias_de_foto(pixeles)
        if minucias is None:
            _estado("Pocas minucias. Limpia el dedo y el lector, y apoya otra vez el centro.")
            continue
        if primera is not None:
            parecido = comparar_minucias_fast(minucias, primera)
            if parecido < UMBRAL:
                _estado(
                    f"Esta toma se parece en {parecido:.3f}. Hace falta {UMBRAL:.2f}. "
                    "Mismo centro, misma presión."
                )
                continue
            _estado(f"Toma {numero} lista, {len(minucias)} minucias. Parecido con la primera: {parecido:.3f}.")
        elif numerar:
            _estado(f"Toma {numero} lista, {len(minucias)} minucias.")
        else:
            _estado("Foto lista. Buscando a quién pertenece...")
        if numerar:
            _guardar_toma(carpeta, pixeles, numero)
        else:
            carpeta.mkdir(parents=True, exist_ok=True)
            ruta = carpeta / "ultimo.png"
            escribir_png(ruta, pixeles, ANCHO_IMAGEN, ALTO_IMAGEN)
        return pixeles, minucias
    _estado(f"No pude aceptar la toma {numero}.")
    raise RuntimeError(
        f"No pude aceptar la toma {numero}. Limpia el lector y el dedo, y apoya otra vez el centro."
    )


def capturar_toma_para_pantalla(
    sensor: AS608,
    numero: int,
    primera: np.ndarray | None,
    espera: float = ESPERA_QUIETO,
    limite_dedo: float = ESPERA_DEDO,
) -> tuple[bytes, np.ndarray]:
    """Una sola toma. La página muestra el PNG y espera a que la persona continúe."""
    if numero < 1 or numero > TOMA_TOTAL:
        raise RuntimeError(f"La toma {numero} no forma parte del registro de {TOMA_TOTAL}.")
    return _capturar_toma(
        sensor,
        numero,
        primera,
        espera,
        CARPETA,
        limite_dedo,
        aviso=AVISOS[numero - 1].format(n=numero, total=TOMA_TOTAL),
    )


def png_data_url(pixeles: bytes) -> str:
    png = png_de_pixeles(pixeles, ANCHO_IMAGEN, ALTO_IMAGEN)
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def serializar_template(matriz_minucias: np.ndarray) -> bytes:
    """Empaqueta el ndarray (N, 4) en bytes comprimidos para models.BinaryField."""
    payload = np.round(matriz_minucias, 3).tolist()
    return zlib.compress(json.dumps(payload).encode("utf-8"), level=9)


def deserializar_template(template_bytes: bytes) -> np.ndarray:
    """Reconstruye el ndarray (N, 4) desde el BinaryField de PostgreSQL."""
    raw = zlib.decompress(bytes(template_bytes))
    return np.array(json.loads(raw.decode("utf-8")), dtype=np.float32)


def comparar_minucias_fast(
    m_captura: np.ndarray,
    m_db: np.ndarray,
    dist_tol: float = 14.0,
    ang_tol_rad: float = 0.35,
) -> float:
    """Puntaje 0–1 con giro de ±12° y corrimiento de hasta 24 px.

    Hace falta el mismo tipo de minucia (terminación o bifurcación). Con menos
    de 8 puntos de cada lado el puntaje es 0.
    """
    if len(m_captura) < MIN_COMUNES or len(m_db) < MIN_COMUNES:
        return 0.0
    if m_captura.shape[1] < 4 or m_db.shape[1] < 4:
        return 0.0
    return float(comparar_rapido(m_captura, m_db, dist_tol, ang_tol_rad))


def _enrolar(
    sensor: AS608,
    espera: float = ESPERA_QUIETO,
    carpeta: Path | None = None,
    limite_dedo: float = ESPERA_DEDO,
    limite_levantar: float = ESPERA_LEVANTAR,
) -> np.ndarray:
    carpeta = carpeta or CARPETA
    tomas: list[np.ndarray] = []
    anterior: bytes | None = None
    for numero in range(1, TOMA_TOTAL + 1):
        if anterior is not None:
            _esperar_levantar(sensor, anterior, limite_levantar)
        pixeles, minucias = _capturar_toma(sensor, numero, tomas[0] if tomas else None, espera, carpeta, limite_dedo)
        anterior = pixeles
        tomas.append(minucias)
    plantilla = fusionar_plantilla(tomas)
    if plantilla is None:
        _estado("Las cuatro tomas no alcanzaron para una plantilla.")
        raise RuntimeError(
            "Las cuatro tomas no alcanzaron para una plantilla. Vuelve a registrar el centro del dedo."
        )
    return plantilla


def enroll_fingerprint_to_db(sensor, espera: float = ESPERA_QUIETO, carpeta: Path | None = None) -> bytes:
    """Cuatro tomas del centro. Devuelve la plantilla lista para BinaryField."""
    plantilla = _enrolar(sensor, espera=espera, carpeta=carpeta)
    blob = serializar_template(plantilla)
    _estado(f"¡Completado! {len(plantilla)} minucias.")
    return blob


def capturar_minucias_en_vivo(sensor, espera: float = ESPERA_QUIETO, carpeta: Path | None = None) -> np.ndarray:
    """Una foto del centro. Devuelve el ndarray (N, 4) para la búsqueda 1:N."""
    destino = carpeta or CARPETA
    _pixeles, minucias = _capturar_toma(
        sensor,
        1,
        None,
        espera,
        destino,
        ESPERA_DEDO,
        aviso="Apoya el centro del dedo en el lector y no lo muevas.",
        numerar=False,
    )
    _estado(f"Huella lista para identificar. Foto en {destino / 'ultimo.png'}.")
    return minucias


def apagar_led_sensor(sensor):
    """La lámpara azul del AS608 va con los 5 V. No hay comando para apagarla."""
    return
