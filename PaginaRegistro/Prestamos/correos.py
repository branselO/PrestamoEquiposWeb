"""Confirmaciones por correo de préstamos, sanciones y devoluciones."""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger(__name__)


def _cuando(momento):
    if momento is None:
        return '—'
    return timezone.localtime(momento).strftime('%d/%m/%Y %H:%M')


def _nombre(usuario):
    if usuario is None:
        return '—'
    visible = ' '.join(
        parte for parte in (usuario.nombre, usuario.apellidos) if parte
    ).strip()
    return visible or usuario.email


def _enviar(destinatario, asunto, cuerpo):
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


def confirmar_prestamo(prestamo):
    usuario = prestamo.usuario_solicita
    equipos = [
        f'- {detalle.dispositivo.codigo_inventario} {detalle.dispositivo.nombre}'
        for detalle in prestamo.detalles.all()
    ]
    autoriza = prestamo.staff_autoriza
    cuerpo = '\n'.join([
        f'Hola {_nombre(usuario)},',
        '',
        f'Tu préstamo #{prestamo.pk} quedó registrado.',
        f'Salida: {_cuando(prestamo.fecha_salida)}',
        f'Devolución esperada: {_cuando(prestamo.fecha_devolucion_esperada)}',
        f'Autorizó: {_nombre(autoriza)}' + (
            f' ({autoriza.email})' if autoriza is not None and autoriza.email else ''
        ),
        '',
        'Equipos:',
        *(equipos or ['- Ninguno']),
        '',
        'Devuélvelos a más tardar en la fecha indicada.',
    ])
    return _enviar(
        usuario.email,
        f'Confirmación de préstamo #{prestamo.pk}',
        cuerpo,
    )


def confirmar_sancion(sancion):
    usuario = sancion.usuario
    cuerpo = '\n'.join([
        f'Hola {_nombre(usuario)},',
        '',
        f'Se registró la sanción #{sancion.pk} en tu cuenta.',
        f'Préstamo: #{sancion.prestamo_id}',
        f'Tipo: {sancion.get_tipo_sancion_display()}',
        f'Estado: {sancion.get_estado_display()}',
        f'Fecha: {_cuando(sancion.fecha_reporte)}',
        f'Registrada por: {_nombre(sancion.registrado_por)}',
        '',
        'Observaciones:',
        sancion.observaciones,
        '',
        'Mientras la sanción esté activa no puedes solicitar préstamos.',
    ])
    return _enviar(
        usuario.email,
        f'Confirmación de sanción #{sancion.pk}',
        cuerpo,
    )


def confirmar_devolucion(prestamo, detalles):
    usuario = prestamo.usuario_solicita
    lineas = []
    for detalle in detalles:
        if detalle.usuario_devuelve_id:
            quien = _nombre(detalle.usuario_devuelve)
        else:
            quien = detalle.nombre_externo_devuelve or 'No indicado'
        lineas.append(
            f'- {detalle.dispositivo.codigo_inventario} {detalle.dispositivo.nombre}'
            f' — {_cuando(detalle.fecha_devuelto)}, entregó {quien}'
        )
    comentarios = next(
        (
            detalle.comentarios_devolucion
            for detalle in detalles
            if detalle.comentarios_devolucion
        ),
        '',
    )
    cuerpo = '\n'.join([
        f'Hola {_nombre(usuario)},',
        '',
        f'Se registró la devolución de {len(detalles)} equipo(s) del préstamo #{prestamo.pk}.',
        '',
        'Equipos:',
        *(lineas or ['- Ninguno']),
        '',
        'Comentarios:',
        comentarios or 'Sin comentarios.',
    ])
    return _enviar(
        usuario.email,
        f'Confirmación de devolución del préstamo #{prestamo.pk}',
        cuerpo,
    )
