# Despliegue y pruebas

El repositorio cubre el entorno local (Django en el host, PostgreSQL en Docker) y el zip del agente de kiosco. No hay Dockerfile de la aplicación, ni Gunicorn o uWSGI en `requirements.txt`, ni Nginx, ni unidad de servicio, ni workflow de CI (no existe `.github/workflows`). Tampoco hay configuración de linter o formateador: no hay `ruff`, `flake8`, `black`, `pylint`, `eslint`, `pytest.ini` ni `pre-commit`.

## Pruebas

Las de Django están en:

| Módulo | Qué ejercita el archivo |
|--------|-------------------------|
| `PaginaRegistro/Usuarios/tests.py` | Formularios de alta, tomas de huella en sesión, entidades por programa, perfil y su correo, login por contraseña y por minucias, elección de puerto, candado del agente, filtro de franjas de la imagen |
| `PaginaRegistro/Inventario/tests.py` | Edición de dispositivo sin poder dejar el estado `prestado` desde el formulario, y el enlace de seguimiento cuando el equipo ya está prestado |
| `PaginaRegistro/Prestamos/tests.py` | Asistente de tres pasos, sanción que bloquea, correos, filtros, atrasos, devolución con usuario y sin usuario |
| `agente-kiosco/test_empaquetar.py` | El zip incluye el agente, omite `biometria_cache.py` y el proceso empaquetado responde `GET /estado` |

No hay pruebas de extremo a extremo con navegador ni con el AS608 conectado. Las de huella construyen minucias en memoria o levantan el HTTP del agente en un puerto efímero (`servir(0)`). `GET /estado` no abre el USB.

Desde `PaginaRegistro/`, con el venv de la raíz activo y PostgreSQL en marcha:

```bash
python manage.py test
python manage.py test Usuarios
python manage.py test Inventario
python manage.py test Prestamos
```

`settings.py` apunta a PostgreSQL. `TestCase` pide a ese servidor una base aparte (`test_` delante del nombre configurado, `pcpuma_db`). Si el contenedor no está arriba, o el usuario `admin_pcpuma` no puede crear bases, esa parte de la suite no arranca. `SimpleTestCase` (puerto, agente, franjas) no usa la base.

El usuario de Compose es dueño de `pcpuma_db`. Crear `test_pcpuma_db` exige el privilegio `CREATEDB`. La imagen oficial de Postgres se lo da al usuario declarado en `POSTGRES_USER`. El archivo no añade otro rol.

Desde la raíz del repositorio:

```bash
python agente-kiosco/test_empaquetar.py
```

El nombre del directorio lleva un guion, así que no es un módulo importable con `python -m unittest`. El archivo sí llama a `unittest.main()`. Inserta `agente-kiosco/` en `sys.path` e importa `empaquetar`.

Empaquetar importa `contrato.py` y copia archivos. La segunda prueba arranca el agente empaquetado, que importa NumPy, el puerto serie y el resto de `agente-kiosco/requirements.txt`. No hace falta el lector para `/estado`.

`prueba_as608.py` no es una prueba automática. Abre `COM4` y espera un dedo.

## Linters

No hay un comando de lint en el proyecto. Nada en el código invoca un analizador. Revisar estilo queda fuera de lo que el repositorio define.

## Docker

`PaginaRegistro/docker-compose.yml` define dos servicios. La aplicación no es uno de ellos.

| Servicio | Imagen | Contenedor | Publicación | Notas |
|----------|--------|------------|-------------|--------|
| `db_pcpuma` | `postgres:15-alpine` | `postgres_pcpuma` | `5433:5432` | `restart: always`. Volumen `pcpuma_postgres_data` |
| `pgadmin` | `dpage/pgadmin4` | `pgadmin4_pcpuma` | `5050:80` | `depends_on: db_pcpuma` |

Variables que el compose escribe dentro de los contenedores (no las lee Django por sí mismo; Django tiene los mismos datos de Postgres copiados en `settings.py`):

| Variable | Valor en el archivo |
|----------|---------------------|
| `POSTGRES_DB` | `pcpuma_db` |
| `POSTGRES_USER` | `admin_pcpuma` |
| `POSTGRES_PASSWORD` | `password_seguro_123` |
| `PGADMIN_DEFAULT_EMAIL` | `admin@pcpuma.com` |
| `PGADMIN_DEFAULT_PASSWORD` | `admin` |

Desde `PaginaRegistro/`:

```bash
docker compose up -d
docker compose ps
docker compose logs db_pcpuma
docker compose down
```

`down` no borra el volumen. `docker compose down -v` sí lo borra: se pierde `pcpuma_postgres_data`.

No hay `healthcheck`. `depends_on` solo espera a que el contenedor de Postgres arranque, no a que acepte conexiones. Si `migrate` corre en el mismo instante que el primer `up`, puede fallar hasta que Postgres termine de inicializar.

pgAdmin no es necesario para `runserver`. Sirve para mirar las tablas en `http://localhost:5050`. El host interno del servidor Postgres, visto desde pgAdmin, es el nombre del servicio `db_pcpuma` y el puerto `5432`.

## Agente en el kiosco

El kiosco no clona el repositorio. En una máquina de desarrollo, desde la raíz:

```bash
python agente-kiosco/empaquetar.py
```

Salida por defecto: `agente-kiosco/dist/agente-huella-kiosco-<VERSION_AGENTE>.zip` y la carpeta del mismo nombre. `-o` / `--output` cambia la ruta del zip. El directorio `dist/` está en `.gitignore`.

El zip lleva `requirements.txt`, `README.md`, `CONTRATO.md`, `arrancar.py`, `arrancar.bat`, `instalar.bat`, un `VERSION` y el paquete mínimo `Usuarios/hardware/` (`agente.py`, `contrato.py`, `hardware.py`, `huella_pc.py`, `prueba_gabor.py`, `verificar_as608.py`). No lleva Django, Postgres ni `biometria_cache.py`.

En Windows, dentro de la carpeta descomprimida, `instalar.bat` crea `.venv` e instala `requirements.txt`. `arrancar.bat` ejecuta `arrancar.py` con ese intérprete. En Linux o macOS el equivalente que sí está en el repo es:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python arrancar.py
```

Esos tres comandos valen dentro del zip. En el repo, sin empaquetar, `python agente-kiosco/arrancar.py` usa `PaginaRegistro/Usuarios/hardware` directamente.

El proceso se queda en primer plano e imprime `Agente de huella en http://127.0.0.1:<puerto>`. Un `HUELLA_AGENTE_PUERTO` que no sea entero termina con código 1. Si el puerto está ocupado, también. No hay servicio de Windows ni de systemd en el repositorio: la terminal tiene que seguir abierta, que es lo que describen `arrancar.py` y el README del agente.

`HUELLA_AGENTE_URL` del servidor Django tiene que ser la URL que el navegador de ese kiosco puede abrir. El default `http://127.0.0.1:8766` asume que el navegador y el agente están en la misma máquina. El agente no escucha en otra interfaz.

Si cambian las rutas, el JSON o el empaquetado de minucias, `contrato.py` pide subir `VERSION_CONTRATO` y actualizar `agente-kiosco/CONTRATO.md` antes de volver a empaquetar. `VERSION_AGENTE` es la que sale en el nombre del zip y en `GET /estado`.

## Producción de la aplicación web

No hay un procedimiento de producción en el repositorio. Lo que sí existe, y un servidor WSGI usaría, es el callable `application` de `PaginaRegistro/PaginaRegistro/wsgi.py` (`DJANGO_SETTINGS_MODULE=PaginaRegistro.settings`). `asgi.py` expone el mismo tipo de callable; no hay consumidores ASGI ni Django Channels en `INSTALLED_APPS`.

Con el `settings.py` actual, un despliegue público queda así de limitado:

| Ajuste | Valor en el código | Consecuencia |
|--------|--------------------|--------------|
| `DEBUG` | `True` | Páginas de error con traza. `/media/` se monta solo en este modo |
| `ALLOWED_HOSTS` | `[]` | Un host que no sea el del runserver de desarrollo recibe 400 |
| `SECRET_KEY` | literal `django-insecure-...` en el archivo | Firmas de sesión predecibles si ese archivo se publica |
| Base de datos | literales, host `localhost`, puerto `5433` | El proceso tiene que ver Postgres en ese host y puerto. No hay variable para moverlo |
| `STATIC_ROOT` | no definido | `collectstatic` no tiene destino |
| Estáticos de UI | CDN de Tailwind y Google Fonts | El navegador del kiosco necesita salir a esos dominios |
| Correo | consola, salvo `EMAIL_HOST` | En producción hay que exportar el SMTP. Si no, el acierto del préstamo igual se guarda y el mensaje avisa que el correo no salió |
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` | no salen de entorno | Cambiarlos implica editar `settings.py`. El código no lee `DJANGO_SECRET_KEY` ni un equivalente |

Medios subidos (`Dispositivo.foto`) quedan en `PaginaRegistro/media/dispositivos_fotos/`. Sin `DEBUG`, `urls.py` no los sirve. No hay otro servidor de medios configurado.

Sesiones y el padrón de huellas están en memoria de cada proceso en lo que toca al índice biométrico. La sesión de Django usa la tabla de `django.contrib.sessions` (el backend por defecto, porque `SESSION_ENGINE` no está definido). El índice `IndiceBiometricoRAM` no se comparte entre procesos: cada worker lo llena en su primera búsqueda 1:N.

Antes de orientarlo a una red real hay que sustituir la clave, apagar `DEBUG`, llenar `ALLOWED_HOSTS` y sacar de los archivos la contraseña de Postgres y la de pgAdmin. Esas piezas no están hechas en este repositorio.

## Orden mínimo que sí está soportado

En una máquina de desarrollo, desde un clon de este repo:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd PaginaRegistro
docker compose up -d
python manage.py migrate
python manage.py runserver
```

En otra terminal, si hace falta el lector de esta misma máquina:

```bash
python agente-kiosco/arrancar.py
```

La comprobación automática correspondiente es `python manage.py test` dentro de `PaginaRegistro/` y `python agente-kiosco/test_empaquetar.py` en la raíz.
