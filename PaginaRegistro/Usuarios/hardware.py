import serial
import serial.tools.list_ports
import time
import zlib
import json
import numpy as np
import cv2
import adafruit_fingerprint
import fingerprint_enhancer
import fingerprint_feature_extractor

BAUDRATE = 57600
ESTADO_SENSOR = "Iniciando..."

def encontrar_puerto_arduino():
    """Escanea y devuelve el puerto del sensor en macOS, Linux o Windows."""
    puertos = serial.tools.list_ports.comports()
    for puerto in puertos:
        # 1. Búsqueda para macOS (Arduino usbmodem o FT232/CH340 usbserial)
        if "usbmodem" in puerto.device or "usbserial" in puerto.device:
            return puerto.device
        # 2. Búsqueda para Windows y Linux (ttyUSB / ttyACM)
        elif any(k in (puerto.description or "") for k in ("USB", "CH340", "CP210", "FT232")) or "ttyUSB" in puerto.device:
            return puerto.device
    return None

def get_sensor():
    """Inicializa la conexión y devuelve el sensor y el puerto (para cerrarlo después)."""
    puerto = encontrar_puerto_arduino()
    if not puerto:
        raise RuntimeError("Sensor/Adaptador USB no detectado. Revisa la conexión USB.")
    
    uart = serial.Serial(puerto, baudrate=BAUDRATE, timeout=2)
    try:
        sensor = adafruit_fingerprint.Adafruit_Fingerprint(uart)
        return sensor, uart
    except Exception as e:
        uart.close()
        raise RuntimeError(f"Error al comunicar con el sensor AS608/R503: {e}")

def _descargar_imagen_numpy(sensor):
    """
    Descarga el ImageBuffer crudo del AS608 (36864 bytes) o R503 (18432 bytes)
    usando UpImage (0x0A) y reconstruye la matriz de 8 bits en escala de grises.
    """
    raw_bytes = sensor.get_fpdata(sensorbuffer="image")
    
    # Cada byte contiene 2 píxeles de 4 bits (nibble alto y nibble bajo)
    arr = np.frombuffer(bytes(raw_bytes), dtype=np.uint8)
    high_nibbles = (arr >> 4) * 17
    low_nibbles = (arr & 0x0F) * 17
    
    pixels = np.empty(arr.size * 2, dtype=np.uint8)
    pixels[0::2] = high_nibbles
    pixels[1::2] = low_nibbles

    # Detectar automáticamente si la trama proviene de un R503 (192x192) o AS608 (256x288)
    if pixels.size == 192 * 192:
        return pixels.reshape((192, 192))
    elif pixels.size >= 256 * 288:
        return pixels[:256 * 288].reshape((288, 256))
    else:
        lado = int(np.sqrt(pixels.size))
        return pixels[:lado * lado].reshape((lado, lado))

def _extraer_minucias_matriz(img_gris):
    """
    Ejecuta Filtro de Gabor Orientado -> Esqueletización -> Cruce de Rutovitz (CN)
    en la PC. Devuelve un ndarray de forma (N, 4) con columnas: [x, y, angulo_rad, tipo].
    """
    # 1. Realce de crestas con filtros de Gabor
    img_gabor = fingerprint_enhancer.enhance_fingerprint(img_gris)
    
    # 2. Extracción de Terminaciones (tipo=1) y Bifurcaciones (tipo=3)
    terms, bifs = fingerprint_feature_extractor.extract_minutiae_features(
        img_gabor,
        spuriousMinutiaeThresh=10,
        invertImage=False,
        showResult=False,
        saveResult=False
    )

    puntos = []
    for m in terms:
        ang = np.deg2rad(float(m.Orientation[0])) if m.Orientation else 0.0
        puntos.append([float(m.locX), float(m.locY), ang, 1.0])
    for m in bifs:
        ang = np.deg2rad(float(m.Orientation[0])) if m.Orientation else 0.0
        puntos.append([float(m.locX), float(m.locY), ang, 3.0])

    if not puntos:
        raise RuntimeError("Huella con poca presión o borrosa. No se extrajeron minucias suficientes.")

    mat = np.array(puntos, dtype=np.float32)
    # Centrar coordenadas respecto al centroide (invarianza a traslación al apoyar el dedo)
    mat[:, 0] -= np.mean(mat[:, 0])
    mat[:, 1] -= np.mean(mat[:, 1])
    return mat

def serializar_template(matriz_minucias: np.ndarray) -> bytes:
    """Empaqueta el ndarray (N, 4) en bytes comprimidos para models.BinaryField."""
    payload = np.round(matriz_minucias, 3).tolist()
    return zlib.compress(json.dumps(payload).encode("utf-8"), level=9)

def deserializar_template(template_bytes: bytes) -> np.ndarray:
    """Reconstruye el ndarray (N, 4) desde el BinaryField de PostgreSQL."""
    raw = zlib.decompress(bytes(template_bytes))
    return np.array(json.loads(raw.decode("utf-8")), dtype=np.float32)

def comparar_minucias_fast(m_captura: np.ndarray, m_db: np.ndarray, dist_tol=14.0, ang_tol_rad=0.35) -> float:
    """
    Comparación matricial vectorizada en C/NumPy con tolerancia a rotación (-15° a +15°).
    Toma ~0.04 ms por comparación en un MacBook Apple Silicon.
    """
    if len(m_captura) < 8 or len(m_db) < 8:
        return 0.0

    mejor_score = 0.0
    # Evaluar 5 micro-rotaciones (-12°, -6°, 0°, +6°, +12°) de forma vectorizada
    for delta_deg in (-12.0, -6.0, 0.0, 6.0, 12.0):
        theta = np.deg2rad(delta_deg)
        c, s = np.cos(theta), np.sin(theta)
        
        # Rotar coordenadas (x, y) de la huella capturada
        x_rot = m_captura[:, 0] * c - m_captura[:, 1] * s
        y_rot = m_captura[:, 0] * s + m_captura[:, 1] * c
        ang_rot = m_captura[:, 2] + theta

        # Matriz de distancias euclidianas (N x M) mediante broadcasting de NumPy
        dx = x_rot[:, None] - m_db[None, :, 0]
        dy = y_rot[:, None] - m_db[None, :, 1]
        dist_sq = dx * dx + dy * dy

        # Diferencia angular circular y coincidencia de tipo (Terminación vs Bifurcación)
        d_ang = np.abs(np.arctan2(np.sin(ang_rot[:, None] - m_db[None, :, 2]),
                                  np.cos(ang_rot[:, None] - m_db[None, :, 2])))
        mismo_tipo = (m_captura[:, 3][:, None] == m_db[None, :, 3])

        # Máscara booleana de pares válidos
        coincidencias_matriz = (dist_sq <= (dist_tol ** 2)) & (d_ang <= ang_tol_rad) & mismo_tipo
        num_matches = np.sum( np.any(coincidencias_matriz, axis=1) )

        score = (2.0 * num_matches) / (len(m_captura) + len(m_db))
        if score > mejor_score:
            mejor_score = score

    return float(mejor_score)

def enroll_fingerprint_to_db(sensor):
    """
    Doble escaneo en el sensor para validar calidad y extracción del template
    matemático en la PC listo para guardarse en models.BinaryField.
    """
    global ESTADO_SENSOR

    # 1. Primera lectura
    ESTADO_SENSOR = "Pon el dedo en el sensor..."
    while sensor.get_image() != adafruit_fingerprint.OK:
        pass
    ESTADO_SENSOR = "Descargando primera lectura..."
    img1 = _descargar_imagen_numpy(sensor)
    m1 = _extraer_minucias_matriz(img1)

    ESTADO_SENSOR = "Primera lectura exitosa. Quita el dedo."
    time.sleep(0.4)
    while sensor.get_image() != adafruit_fingerprint.NOFINGER:
        pass

    # 2. Segunda lectura para confirmar consistencia
    ESTADO_SENSOR = "Pon el MISMO dedo otra vez..."
    while sensor.get_image() != adafruit_fingerprint.OK:
        pass
    ESTADO_SENSOR = "Procesando y verificando huella en PC..."
    img2 = _descargar_imagen_numpy(sensor)
    m2 = _extraer_minucias_matriz(img2)

    # 3. Verificar en la PC que ambas lecturas correspondan al mismo dedo
    if comparar_minucias_fast(m1, m2) < 0.25:
        ESTADO_SENSOR = "Error: Las huellas no coinciden."
        raise RuntimeError("Las dos capturas no coinciden. Apoya el centro del dedo con firmeza.")

    # Guardamos el template con mayor riqueza de minucias en BinaryField
    template_final = m1 if len(m1) >= len(m2) else m2
    template_bytes = serializar_template(template_final)
    ESTADO_SENSOR = "¡Completado!"
    return template_bytes

def capturar_minucias_en_vivo(sensor):
    """
    Lee el dedo una sola vez y devuelve el ndarray (N, 4) de minucias
    para pasarlo al motor de búsqueda 1:N en RAM.
    """
    global ESTADO_SENSOR
    ESTADO_SENSOR = "Coloca tu dedo para identificarte..."
    while sensor.get_image() != adafruit_fingerprint.OK:
        pass
    ESTADO_SENSOR = "Analizando huella..."
    img = _descargar_imagen_numpy(sensor)
    return _extraer_minucias_matriz(img)

def apagar_led_sensor(sensor):
    """Intenta apagar la luz azul del sensor AS608 / R503."""
    if not sensor:
        return
    try:
        sensor.set_led(color=1, mode=4, speed=0, cycles=0)
    except Exception:
        pass