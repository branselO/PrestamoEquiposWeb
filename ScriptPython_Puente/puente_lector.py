from flask import Flask, jsonify, request
from flask_cors import CORS
import serial
import adafruit_fingerprint
import base64
import time

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": ["http://localhost:8000"]}})

API_KEY_SECRETA = "contrasena_secreta   "

# ==========================================
# CONEXIÓN CON EL SENSOR (UART)
# ==========================================
try:
    # CAMBIA "COM3" POR EL PUERTO QUE TE ASIGNE WINDOWS
    uart = serial.Serial("COM3", baudrate=57600, timeout=1)
    sensor = adafruit_fingerprint.Adafruit_Fingerprint(uart)
    print("Sensor AS608 detectado exitosamente.")
except Exception as e:
    print(f"Error al conectar con el sensor: {e}")


def esperar_dedo():
    """Función auxiliar que detiene el código hasta que el cristal detecta un dedo"""
    while sensor.get_image() != adafruit_fingerprint.OK:
        time.sleep(0.1)
    return True


@app.before_request
def verificar_seguridad():
    if request.method == 'OPTIONS': return
    if request.headers.get('X-Kiosco-Token') != API_KEY_SECRETA:
        return jsonify({"status": "error", "mensaje": "Token inválido"}), 403


# ==========================================
# RUTA 1: REGISTRAR (Extraer Template hacia Django)
# ==========================================
@app.route('/api/escanear', methods=['GET'])
def escanear_huella():
    try:
        print("Esperando dedo para REGISTRAR...")
        esperar_dedo()
        
        # 1. Convierte la imagen a minucias y la guarda en el Buffer 1 del sensor
        if sensor.image_2_tz(1) != adafruit_fingerprint.OK:
            return jsonify({"status": "error", "mensaje": "Error al procesar la huella"}), 400
        
        # 2. Descargamos el Template (Buffer 1) desde el sensor hacia Python
        sensor.get_fpdata(sensor='char', slot=1)
        
        # El sensor entrega una lista de enteros (bytes). Los convertimos a texto Base64
        template_bytes = bytes(sensor.fpdata)
        template_base64 = base64.b64encode(template_bytes).decode('utf-8')
        
        print("¡Huella extraída y convertida a Base64!")
        return jsonify({
            "status": "success", 
            "template": template_base64
        })

    except Exception as e:
        return jsonify({"status": "error", "mensaje": str(e)}), 500


# ==========================================
# RUTA 2: PRÉSTAMO (Comparar 1:1 cargando desde Django)
# ==========================================
@app.route('/api/comparar', methods=['POST'])
def comparar_huella():
    datos = request.json
    template_bd_base64 = datos.get('template_bd')
    
    try:
        # 1. Recibimos el texto de Django y lo regresamos a bytes puros
        template_bytes = base64.b64decode(template_bd_base64)
        
        # 2. Subimos el Template de la Base de Datos al Buffer 2 del sensor
        # (El sensor de hardware es quien hará la comparación matemática)
        sensor.send_fpdata(list(template_bytes), sensor='char', slot=2)
        
        print("Plantilla cargada. Esperando dedo en vivo...")
        
        # 3. Pedimos al estudiante que ponga el dedo
        esperar_dedo()
        
        # 4. Procesamos el dedo en vivo y lo guardamos en el Buffer 1
        if sensor.image_2_tz(1) != adafruit_fingerprint.OK:
            return jsonify({"status": "error", "mensaje": "Huella ilegible"}), 400
            
        # 5. Le ordenamos al sensor que compare el Buffer 1 (dedo vivo) vs Buffer 2 (Django)
        if sensor.compare_templates() == adafruit_fingerprint.OK:
            # ¡Las matemáticas del sensor dicen que es la misma persona!
            # finger.confidence nos dice el "score" de similitud
            return jsonify({
                "status": "success", 
                "match": True, 
                "score": sensor.confidence
            })
        else:
            return jsonify({
                "status": "success", 
                "match": False
            })

    except Exception as e:
        return jsonify({"status": "error", "mensaje": str(e)}), 500

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000)