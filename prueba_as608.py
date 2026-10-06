import serial
import time
import adafruit_fingerprint

# Asegúrate de que este puerto sea el correcto
UART_PORT = '/dev/cu.usbmodem11201' 
BAUDRATE = 57600 # La velocidad real oculta del sensor

def probar_sensor():
    print(f"Abriendo puerto {UART_PORT} a {BAUDRATE} baudios en modo Zombie...")
    
    try:
        uart = serial.Serial(UART_PORT, baudrate=BAUDRATE, timeout=1)
    except Exception as e:
        print("\n❌ ERROR: No se pudo abrir el puerto USB.")
        return

    try:
        print("Puerto abierto. Buscando comunicación con el AS608...")
        sensor = adafruit_fingerprint.Adafruit_Fingerprint(uart)
        
        print("\n✅ ¡COMUNICACIÓN EXITOSA!")
        print("Parámetros internos del sensor:")
        print(f"  - Capacidad máxima: {sensor.library_size} huellas")
        
        print("\nPrueba óptica: Por favor, pon tu dedo en el sensor...")
        
        while sensor.get_image() != adafruit_fingerprint.OK:
            pass
            
        print("✅ ¡Dedo detectado correctamente!")
        
    except RuntimeError as e:
        print("\n❌ ERROR: Sin respuesta. Revisa que TX esté en Pin 1 y RX en Pin 0.")
    finally:
        if 'uart' in locals() and uart.is_open:
            uart.close()

if __name__ == '__main__':
    probar_sensor()