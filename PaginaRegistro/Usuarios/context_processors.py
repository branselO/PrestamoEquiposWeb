from django.conf import settings


def huella_agente(request):
    """Dirección del agente que lee el sensor USB de este kiosco."""
    return {'huella_agente_url': settings.HUELLA_AGENTE_URL}
