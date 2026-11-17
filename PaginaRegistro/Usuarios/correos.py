"""Correos enviados desde el panel de usuarios."""

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

ASUNTO_PERFIL_DEFAULT = 'PCPUMA - SISTEMA DE PRESTAMOS'


def enviar_correo_perfil(destinatario, asunto, cuerpo):
    """Envía un mensaje al correo del perfil con django.core.mail.send_mail."""
    destinatario = (destinatario or '').strip()
    asunto = (asunto or '').strip() or ASUNTO_PERFIL_DEFAULT
    cuerpo = (cuerpo or '').strip()
    if not destinatario:
        return False
    try:
        enviados = send_mail(
            asunto,
            cuerpo,
            settings.DEFAULT_FROM_EMAIL,
            [destinatario],
            fail_silently=False,
        )
    except Exception:
        logger.exception('No se pudo enviar «%s» a %s', asunto, destinatario)
        return False
    return enviados > 0
