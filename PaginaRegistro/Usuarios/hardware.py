import serial
import serial.tools.list_ports
import time
import adafruit_fingerprint

BAUDRATE = 57600
ESTADO_SENSOR = "Iniciando..."

def encontrar_puerto_arduino():
    """Escanea y devuelve el puerto del puente Zombie automáticamente."""
    puertos = serial.tools.list_ports.comports()
    for puerto in puertos:
        if "usbmodem" in puerto.device:
            return puerto.device
    return None

def get_sensor():
    """Inicializa la conexión y devuelve el sensor y el puerto (para cerrarlo después)."""
    puerto = encontrar_puerto_arduino()
    if not puerto:
        raise RuntimeError("Arduino no detectado. Revisa la conexión USB.")
    
    # timeout=1 es crucial para que Django no se quede congelado si el sensor falla
    uart = serial.Serial(puerto, baudrate=BAUDRATE, timeout=1)
    try:
        sensor = adafruit_fingerprint.Adafruit_Fingerprint(uart)
        return sensor, uart
    except Exception as e:
        uart.close()
        raise RuntimeError(f"Error al comunicar con el AS608: {e}")

def enroll_fingerprint_to_db(sensor):
    """Guía el proceso de doble escaneo y extrae el template biométrico puro."""

    global ESTADO_SENSOR

    # 1. Primera lectura
    ESTADO_SENSOR = "Pon el dedo en el sensor..."
    while sensor.get_image() != adafruit_fingerprint.OK:
        pass
    sensor.image_2_tz(1) # Guarda características en el buffer 1
    
    ESTADO_SENSOR = "Primera lectura exitosa. Quita el dedo."
    
    # 2. Esperar a que el usuario quite el dedo
    time.sleep(0.5)
    while sensor.get_image() != adafruit_fingerprint.NOFINGER:
        pass
        
    # 3. Segunda lectura para confirmación
    ESTADO_SENSOR = "Pon el MISMO dedo otra vez..."
    while sensor.get_image() != adafruit_fingerprint.OK:
        pass
    sensor.image_2_tz(2) # Guarda características en el buffer 2

    ESTADO_SENSOR = "Procesando huella..."

    
    # 4. Mezclar ambos buffers y crear el modelo final
    if sensor.create_model() != adafruit_fingerprint.OK:
        ESTADO_SENSOR = "Error: Las huellas no coinciden."
        raise RuntimeError("Las huellas no coinciden. Intenta de nuevo.")
    
    # 5. Descargar el modelo del sensor a la memoria de la Mac (Python)
    # Atrapamos la lista que retorna la función en la variable 'datos_huella'
    datos_huella = sensor.get_fpdata(sensorbuffer="char", slot=1)
    
    # Convertimos esa lista de enteros en bytes puros para la Base de Datos
    template_bytes = bytes(datos_huella)
    ESTADO_SENSOR = "¡Completado!"
    return template_bytes

def verify_fingerprint_from_db(sensor, db_template_bytes):
    """Escanea un dedo vivo y lo compara con los bytes guardados en tu base de datos."""

    # 1. Leer dedo actual
    while sensor.get_image() != adafruit_fingerprint.OK:
        pass
    sensor.image_2_tz(1) 
    
    sensor.send_fpdata(list(db_template_bytes), slot=2, sensorbuffer="char")
    
    # 3. Que el chip óptico haga la comparación matemática entre ambos buffers
    if sensor.compare_templates() == adafruit_fingerprint.OK:
        return True
    return False

def apagar_led_sensor(sensor):
    """Intenta apagar la luz azul del sensor AS608."""
    if not sensor:
        return
    try:
        # El mode=4 es el comando interno para apagar el anillo/LED
        sensor.set_led(color=1, mode=4, speed=0, cycles=0)
    except Exception:
        pass # Ignorar si el modelo no soporta el comando