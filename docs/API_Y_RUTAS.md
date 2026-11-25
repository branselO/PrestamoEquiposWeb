# API y rutas

No hay un API REST con versionado ni esquema OpenAPI. Las pantallas son vistas Django y algunos `POST`/`GET` responden JSON para el navegador del kiosco. El prefijo sale de `PaginaRegistro/urls.py`.

| Prefijo | App |
|---------|-----|
| `/admin/` | Django admin |
| `/` | `Usuarios.urls` |
| `/Inventario/` | `Inventario.urls` |
| `/Prestamos/` | `Prestamos.urls` |

Con `DEBUG=True`, `/media/<ruta>` sirve `MEDIA_ROOT`.

## Permisos

Salvo que la fila diga otra cosa:

- **Público**: la vista no comprueba sesión.
- **Staff**: `UserPassesTestMixin` con `is_authenticated` e `is_staff`. El anónimo va a `/` (`LOGIN_URL = 'login'`). Quien ya entró y no es staff recibe 403.
- **Login + staff**: `@login_required` y, en el cuerpo, `is_staff`. Si falta la sesión, Django redirige al login. Si la sesión no es staff, la vista responde JSON 403.
- **Superusuario**: solo el admin de `CustomUser`, `StaffUser` y `NormalUser`.

CSRF aplica a los POST hacia Django. El agente en `127.0.0.1` no usa CSRF ni sesión.

Las respuestas JSON de las vistas propias usan `status` / `message` o `error`. El agente usa `ok` / `mensaje`.

## Usuarios

### `GET/POST /` — `login`

Público. Plantilla `Usuarios/login.html`. Formulario `EmailLoginForm`: un solo campo `email`.

Si existe un usuario activo, staff, con ese correo, guarda `pre_login_user_id` y redirige a `/login/huella/`. Si no, el formulario muestra «No se pudo iniciar sesión con ese correo.». Esta vista no comprueba la contraseña.

### `POST /logout/` — `logout`

`LogoutView` con `next_page='login'`. La barra lo envía como POST con token CSRF.

### `GET/POST /register/` — `register_Staff`

Público. Alta de staff (`StaffSignUpForm`). Campos: `email`, `nombre`, `apellidos`, `numero_cuenta`, `numero_trabajador`, `rfc`, `curp`, `genero`, `direccion`, `telefono_celular`, `programa`, `entidad_academica`, más las dos contraseñas de `UserCreationForm`.

El POST válido no inserta el usuario. Redirige a `/api/registrar_huella/`.

### `GET/POST /crear_usuario/` — `register_Normal`

Staff. Igual que el alta de staff, con `is_staff=False` en la sesión. Plantilla `register_Normal.html`.

### `GET /api/entidades-por-programa/` — `entidades_por_programa`

Público. Otro método responde 405.

| Query | Regla |
|-------|--------|
| `programa_id` | Entero decimal. Si falta o no es decimal, 400 `{"error": "Selecciona un programa válido."}`. Si el programa no existe, 404 `{"error": "El programa seleccionado no existe."}`. |

Respuesta 200:

```json
{
  "entidades": [
    {"id": 1, "clave": "FI", "nombre": "Facultad de Ingeniería"}
  ]
}
```

La lista va ordenada por `nombre`. Puede ir vacía.

### `GET/POST /api/registrar_huella/` — `registrar_huella`

Público a nivel de vista. El POST `guardar` exige `temp_user_data` en la sesión (si no, 400 `{"status": "error", "message": "Sesión caducada."}`).

GET: borra las tomas de la sesión y pinta `registro_huella_Staff.html` o `registro_huella_Normal.html`. Sin la clave `is_staff` en la sesión pinta la de staff.

POST JSON:

| `accion` | Efecto |
|----------|--------|
| `reiniciar` | Vacía `huella_tomas`. No exige `temp_user_data`. |
| `guardar` | Añade una toma. Exige `minucias` (base64) e `imagen` (`data:image/png;base64,` que decodifique a PNG). |
| otra o ausente | 400. El mensaje dice que la captura se hace en el lector del kiosco. |

`reiniciar` responde:

```json
{
  "status": "reiniciado",
  "message": "Empezamos de nuevo. Captura la toma 1.",
  "toma": 0,
  "total": 4,
  "completo": false
}
```

Toma intermedia (`status` 200):

```json
{
  "status": "captura",
  "message": "Toma 1 lista. Revisa la foto y pulsa Continuar.",
  "imagen": "data:image/png;base64,...",
  "toma": 1,
  "total": 4,
  "completo": false
}
```

Cuarta toma correcta: `status` vale `"success"`, `completo` es `true`, `message` es «Huella y usuario guardados. Ya puedes entrar.». Ahí se inserta el `CustomUser` y se borra `temp_user_data`.

Errores 400 habituales: minucias ilegibles, PNG ausente o falso, tomas previas corruptas (`reiniciar: true`), fusión imposible (`reiniciar: true` y toma 0).

### `GET /api/estado_sensor/` — `estado_sensor`

Público. Respuesta: `{"mensaje": "<texto>"}`. El texto es el del proceso Django (`ESTADO_SENSOR`), no el del agente del kiosco. Al arrancar Django vale `"Iniciando..."`.

### `GET/POST /login/huella/` — `verificar_huella`

Exige `pre_login_user_id` de un staff activo. Si falta, el GET redirige a `/` y el POST responde 400 `{"status": "error", "message": "Sesión caducada."}`.

GET: plantilla `login_huella.html` con el usuario en el contexto.

POST `application/x-www-form-urlencoded`:

| Cuerpo | Resultado |
|--------|-----------|
| `auth_method=password` y `password` correcta | 200, `status=success`, `redirect_url` hacia `/inicio/`, y `login()` |
| `auth_method=password` incorrecta o vacía | 401 «La contraseña no es correcta.» |
| `minucias` cuyo puntaje contra la plantilla es `>= 0.30` | 200, mensaje «Identidad confirmada, <nombre>. Entrando...», `redirect_url` `/inicio/` |
| sin plantilla guardada | 401 «Esta cuenta no tiene huella...» |
| minucias ilegibles | 400 con el texto de `minucias_desde_texto` |
| plantilla de la base ilegible | 500 «La huella guardada de esta cuenta no se pudo leer.» |
| puntaje menor a 0.30 | 401 «La huella no coincide...» |

Ejemplo de acierto:

```json
{
  "status": "success",
  "message": "Identidad confirmada, Ada. Entrando...",
  "redirect_url": "/inicio/"
}
```

### `GET /inicio/` — `inicio`

Staff. Plantilla `inicio.html`. Enlaces a usuarios, alta, inventario, préstamos y sanciones.

### `GET /inicio/admin_usuarios/` — `admin_usuarios`

Staff. Plantilla `admin_usuarios.html`.

Query opcionales, ambos con `icontains`, combinados con AND:

| Query | Filtro |
|-------|--------|
| `nombre` | `nombre__icontains` |
| `email` | `email__icontains` |

Si ambos vienen vacíos, lista a todos. El contexto separa `usuarios_normales` (`is_staff=False`) y `usuarios_staff` (`is_staff=True` y `is_superuser=False`). Los superusuarios no entran en ninguno de los dos grupos.

### `GET /perfil/<usuario_id>/` — `perfil_usuario`

Público. 404 si el id no existe. Plantilla `ver_perfil.html`. El contexto incluye `asunto_correo_default` = `PCPUMA - SISTEMA DE PRESTAMOS`.

### `POST /perfil/<usuario_id>/enviar_correo/` — `enviar_correo_perfil`

Login + staff. Cuerpo de formulario: `asunto` (opcional; si va vacío se usa el asunto por defecto) y `cuerpo` (obligatorio).

| Caso | Respuesta |
|------|-----------|
| sin staff | 403 `{"status":"error","message":"Solo el personal puede enviar este correo."}` |
| usuario sin correo | 400 |
| cuerpo vacío | 400 «Escribe el contenido del correo.» |
| `send_mail` falla o envía 0 | 502 «No se pudo enviar el correo...» |
| envío correcto | 200 `{"status":"success","message":"Correo enviado a <email>."}` |

## Inventario

Todas las vistas son staff. El alta y la edición redirigen a `/Inventario/Administrar_Inventario/`.

### `GET /Inventario/Administrar_Inventario/` — `inventario`

Plantilla `inventario.html`. Filtros query, todos opcionales:

| Query | Efecto |
|-------|--------|
| `q` | `nombre__icontains` |
| `codigo_inventario` | `codigo_inventario__icontains` |
| `categoria` | id numérico de `Categoria` |
| `estado` | una clave de `disponible`, `prestado`, `mantenimiento`, `extraviado` |

Orden: `codigo_inventario`.

### `GET/POST /Inventario/Dispositivos/Nuevo/` — `dispositivo_nuevo`

Campos: `codigo_inventario`, `nombre`, `categoria`, `especificaciones`, `foto`, `comentarios`. No incluye `estado`. Título de contexto: «Añadir dispositivo».

### `GET/POST /Inventario/Dispositivos/<pk>/Editar/` — `dispositivo_editar`

Los mismos campos más `estado`, sin la opción `prestado`. Título: «Editar dispositivo». Un POST que igual mande `prestado` no pasa la validación del formulario, porque esa opción se quitó de `choices`.

### `GET/POST /Inventario/Categorias/Nueva/` — `categoria_nueva`

Campos `nombre` y `descripcion`. Título: «Añadir categoría».

## Préstamos y sanciones

El prefijo es `/Prestamos/`. Salvo la fila JSON, las pantallas son staff y devuelven HTML. Los POST de error de formulario re-renderizan la misma plantilla con `registro_error` en el contexto, o redirigen con `django.contrib.messages`.

Cuando el navegador manda la cabecera `X-Requested-With: fetch` (la huella lo hace), el paso 1 del préstamo y el login de devolución responden JSON.

### Listado y comentario

`GET /Prestamos/Administrar_Prestamos/` — `prestamos`. Plantilla `prestamos.html`.

| Query | Efecto |
|-------|--------|
| `id` | si es dígitos, filtra ese ticket; si trae otro texto, el queryset queda vacío |
| `usuario` | id de usuario. Además exige un detalle sin devolver. 404 si el id no existe |
| `codigo_inventario` | igualdad exacta y detalle sin devolver. Si el código no existe, `dispositivo_filtrado` es nulo y el filtro de préstamos tampoco encuentra filas |
| `estado` | `completado`, `pendiente` (todo lo que no está completado, atrasados incluidos) o `atrasado`. Se aplica en Python |

`POST /Prestamos/Agregar_Comentario/<pk>/` — `agregar_comentario`. Campo `comentarios`. `origen=pendientes` vuelve a la bandeja de devolución; si no, al listado. Comentario vacío: mensaje de error y no escribe.

### Asistente de préstamo

| Método y ruta | Nombre | Paso |
|---------------|--------|------|
| `GET/POST /Prestamos/Registrar_Prestamo/` | `registrar_prestamo` | 1. Autenticar solicitante |
| `GET/POST /Prestamos/Registrar_Prestamo/Dispositivos/` | `registrar_prestamo_paso2` | 2. Elegir dispositivos disponibles |
| `GET/POST /Prestamos/Registrar_Prestamo/Confirmar/` | `registrar_prestamo_paso3` | 3. Fecha y alta transaccional |
| `GET /Prestamos/Registrar_Prestamo/Exito/<pk>/` | `registrar_prestamo_exito` | Comprobante. 404 si el préstamo no existe |

Paso 1, POST de formulario: `correo`, `metodo` (`contrasena` o `huella`), `contrasena`, `minucias`.

Con `X-Requested-With: fetch`, el acierto es:

```json
{
  "status": "success",
  "message": "Huella reconocida: Ada Lovelace. Continuando con el préstamo.",
  "redirect_url": "/Prestamos/Registrar_Prestamo/Dispositivos/"
}
```

El fallo es 400 `{"status":"error","message":"..."}`. Mensajes que el código emite: correo vacío, usuario inexistente o inactivo, contraseña incorrecta, método distinto de `contrasena` o `huella`, minucias vacías o ilegibles, huella sin coincidencia sobre 0.30, sanción activa.

Sin esa cabecera, el fallo re-renderiza el paso y el acierto redirige al paso 2. La sesión queda `{"usuario_id": <pk>}`. Se borra cualquier selección anterior.

El paso 2 exige el paso 1. Query `q`, `codigo` (icontains del código) y `categoria`. POST: `dispositivos` con uno o más ids. Todos tienen que seguir en `disponible`. Respuesta de éxito: redirect al paso 3.

El paso 3 exige dispositivos en la sesión. POST: `fecha_devolucion` (`YYYY-MM-DDTHH:MM` o un datetime que `parse_datetime` entienda). Vacío significa «dentro de dos horas», al minuto. Éxito: redirect al comprobante y mensaje de correo enviado o no enviado. Si un equipo dejó de estar disponible, vuelve al paso 2. Si el solicitante ya no pasa la regla de sanción, vuelve al paso 1 y limpia la sesión.

### Devolución

| Método y ruta | Nombre | Comportamiento |
|---------------|--------|----------------|
| `GET/POST /Prestamos/Registrar_Devolucion/` | `devolucion_login` | Mismos campos y el mismo JSON de huella que el paso 1. Guarda `devolucion_usuario_id`. |
| `GET /Prestamos/Registrar_Devolucion/Pendientes/` | `devolucion_pendientes` | Préstamos de esa persona con algo sin devolver. Sin sesión válida, redirect al login de devolución. |
| `POST /Prestamos/Registrar_Devolucion/Salir/` | `devolucion_salir` | Borra la sesión de devolución y vuelve al login. |
| `POST /Prestamos/Registrar_Devolucion/<pk>/como-usuario/` | `devolucion_como_usuario` | Autentica a quien entrega (`correo`, `metodo`, `contrasena` o `minucias`). |
| `POST /Prestamos/Registrar_Devolucion/<pk>/sin-usuario/` | `devolucion_sin_usuario` | `nombre_completo` con al menos dos palabras. |
| `POST /Prestamos/Registrar_Devolucion/<pk>/` | `registrar_devolucion` | Devolución desde el listado. `detalles` (ids), `comentarios`, `entrega_<detalle_id>`. No llena `usuario_devuelve`. |

En `como-usuario` y `sin-usuario` el POST también lleva `detalles`, `comentarios` y `origen`. Con `origen=pendientes` el préstamo tiene que ser de la persona en sesión; si no hay sesión, el destino es el login de devolución. Sin ese origen, el destino es el listado de préstamos y el ticket se busca solo por pk.

Si `metodo=huella` y la cabecera es `X-Requested-With: fetch`, la respuesta es JSON (`status` `success` o `error`, `message`, `redirect_url`) en lugar de redirect. El error HTTP es 400.

Efecto común de una devolución aceptada: `fecha_devuelto` ahora, dispositivo `prestado` pasa a `disponible`, comentario opcional en el ticket, correo al solicitante. Cero detalles pendientes seleccionados: mensaje de error y no escribe.

### Sanciones

`GET /Prestamos/Administrar_Sanciones/` — `sanciones`. Plantilla `sansiones.html` (el archivo se llama así, sin la segunda c).

| Query | Efecto |
|-------|--------|
| `estado` | `activa` o `resuelta`. Otro valor se ignora |
| `prestamo` | id numérico del ticket; texto no numérico deja la lista vacía |
| `correo` | `usuario__email__icontains` |
| `usuario` | id. 404 si no existe |

`GET/POST /Prestamos/Registrar_Sancion/` — `registrar_sancion`.

GET acepta `?prestamo=<id>` y muestra el préstamo si existe. POST: `prestamo`, `tipo_sancion` (una de las cuatro claves del modelo), `observaciones`. Errores posibles, como mensaje de Django: id inexistente, tipo inválido, observaciones vacías. El acierto redirige al listado.

`GET /Prestamos/Prestamo_Usuario/<pk>/` — `prestamo_usuario_json`. Staff.

404:

```json
{"encontrado": false}
```

200:

```json
{
  "encontrado": true,
  "nombre": "Ada Lovelace",
  "email": "ada@ejemplo.unam.mx"
}
```

`POST /Prestamos/Modificar_Estado_Sancion/<pk>/` — `modificar_estado_sancion`. Campo `estado`: `activa` o `resuelta`. Cualquier otro valor no guarda y deja un mensaje de error. Siempre redirige al listado.

## Agente de huella

Proceso distinto a Django. Escucha en `127.0.0.1` y el puerto `HUELLA_AGENTE_PUERTO` (8766). Contrato numérico: `VERSION_AGENTE` `1.3.0`, `VERSION_CONTRATO` `2`. El detalle corto también está en `agente-kiosco/CONTRATO.md`.

CORS: `Access-Control-Allow-Origin: *`, métodos `GET`, `POST`, `OPTIONS`, cabecera `Content-Type`. `OPTIONS` responde 204.

| Método | Ruta | Cuerpo | Respuesta |
|--------|------|--------|-----------|
| `GET` | `/estado` | — | 200 `ok`, `mensaje`, `version_agente`, `version_contrato` |
| `POST` | `/capturar` | vacío o JSON ignorado | 200 `ok`, `minucias` (base64), `mensaje` |
| `POST` | `/toma` | `{"numero": 1..4, "primera": "<base64 o vacío>"}` | 200 `ok`, `numero`, `minucias`, `imagen` (PNG data URL), `mensaje` |
| `POST` | `/cancelar` | vacío | 200 `ok`, `mensaje`, `cancelado: true` |
| cualquiera | otra ruta | — | 404 `{"ok": false, "mensaje": "Ruta desconocida."}` |

```json
{
  "ok": true,
  "mensaje": "Lector listo. Apoya el centro del dedo y no lo muevas.",
  "version_agente": "1.3.0",
  "version_contrato": 2
}
```

Lectura ocupada: 409 `{"ok": false, "mensaje": "El lector está ocupado. Espera a que termine la lectura en curso."}`. Una captura nueva espera hasta 1.5 s a que la anterior suelte el candado; antes de esperar pone la bandera de cancelación.

Cancelación a media lectura: esa lectura responde 499 `{"ok": false, "mensaje": "Lectura cancelada.", "cancelado": true}`.

Fallo de puerto, dedo o toma: 400 `{"ok": false, "mensaje": "<RuntimeError o OSError>"}`. Cuerpo de `/toma` que no es un objeto JSON, número inválido o `primera` ilegible: 400. El cuerpo mayor de 1 000 000 bytes se rechaza igual que un JSON inválido.

`/capturar` es una sola foto. `/toma` exige que el número esté entre 1 y 4. Si viene `primera`, la toma nueva tiene que alcanzar el umbral 0.35 contra esa matriz.

## Admin de Django

`/admin/` usa el admin de Django con los `ModelAdmin` registrados.

| Modelo | Qué muestra el admin del código |
|--------|----------------------------------|
| `CustomUser`, `StaffUser`, `NormalUser` | listado por correo, nombre, apellidos, número de cuenta e `is_staff`. Busca correo, número de cuenta y nombre. Solo superusuario |
| `Programa` | clave y nombre. `filter_horizontal` de entidades |
| `EntidadAcademica` | clave y nombre |
| `Dispositivo` | código, nombre, categoría, estado. Filtro por estado y categoría |
| `Categoria` | nombre |
| `Prestamo` | id, solicitante, staff, fechas y `estado_ticket`. Inline de detalles con `autocomplete_fields` en dispositivo |
| `Sancion` | id, préstamo, usuario, tipo, estado, fecha |

El inline de detalles declara `autocomplete_fields = ['dispositivo']`. `DispositivoAdmin.search_fields` es `codigo_inventario` y `nombre`.
