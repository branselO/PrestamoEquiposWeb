import threading
import time

try:
    from .hardware import comparar_minucias_fast, deserializar_template
except ImportError:
    from hardware import comparar_minucias_fast, deserializar_template

class IndiceBiometricoRAM:
    """
    Mantiene las matrices NumPy de todos los usuarios en la memoria RAM del worker
    de Django para lograr búsquedas 1:N en milisegundos sin tocar PostgreSQL.
    """
    _lock = threading.Lock()
    _padron = {}  # { usuario_id: np.ndarray(N, 4) }
    _inicializado = False

    @classmethod
    def cargar_desde_postgres(cls, ModeloUsuario):
        """Carga todas las huellas no nulas desde PostgreSQL al arrancar."""
        with cls._lock:
            qs = ModeloUsuario.objects.filter(is_active=True).exclude(
                huella_template__isnull=True
            ).values_list("id", "huella_template")
            nuevo_padron = {}
            for user_id, blob in qs:
                if blob:
                    try:
                        nuevo_padron[user_id] = deserializar_template(bytes(blob))
                    except Exception:
                        # Ignora templates antiguos de 512b del AS608 que aún no se re-enrolan
                        continue
            cls._padron = nuevo_padron
            cls._inicializado = True

    @classmethod
    def actualizar_usuario(cls, usuario_id: int, template_bytes: bytes):
        """Actualiza o inserta en caliente la huella recién enrolada sin reiniciar Django."""
        with cls._lock:
            if template_bytes:
                cls._padron[usuario_id] = deserializar_template(bytes(template_bytes))
            else:
                cls._padron.pop(usuario_id, None)

    @classmethod
    def identificar_1_a_N(cls, m_captura, ModeloUsuario, umbral=0.35):
        """
        Recorre miles de usuarios en RAM usando NumPy vectorizado.
        Retorna (usuario_id, score, tiempo_ms).
        """
        if not cls._inicializado:
            cls.cargar_desde_postgres(ModeloUsuario)

        t0 = time.perf_counter()
        mejor_uid = None
        mejor_score = 0.0

        with cls._lock:
            padron_snapshot = list(cls._padron.items())

        for uid, m_db in padron_snapshot:
            score = comparar_minucias_fast(m_captura, m_db)
            if score >= umbral and score > mejor_score:
                mejor_score = score
                mejor_uid = uid

        latencia_ms = round((time.perf_counter() - t0) * 1000, 2)
        return mejor_uid, round(mejor_score, 4), latencia_ms