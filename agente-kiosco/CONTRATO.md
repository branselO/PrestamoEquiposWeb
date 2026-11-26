# Contrato agente ↔ página web

Fuente de verdad de los números: `PaginaRegistro/Usuarios/hardware/contrato.py`.

## Versión actual

- `VERSION_AGENTE`: versión del proceso instalado en el kiosco.
- `VERSION_CONTRATO`: compatibilidad del intercambio HTTP/JSON. Súbela solo si un kiosco viejo dejaría de funcionar con la página nueva.

`GET /estado` responde `version_agente` y `version_contrato`.

## Red

- Solo escucha en `127.0.0.1` (por defecto puerto `8766`).
- Variable `HUELLA_AGENTE_PUERTO` cambia el puerto.
- La página usa `HUELLA_AGENTE_URL` (por defecto `http://127.0.0.1:8766`).
- CORS: `Access-Control-Allow-Origin: *`, métodos `GET`, `POST` y `OPTIONS`, cabecera `Content-Type`.

## Rutas

| Método | Ruta | Cuerpo | Respuesta útil |
|--------|------|--------|----------------|
| `GET` | `/estado` | — | `ok`, `mensaje`, `version_agente`, `version_contrato` |
| `POST` | `/capturar` | vacío | `ok`, `minucias` (base64), `mensaje` |
| `POST` | `/toma` | `{"numero": 1..4, "primera": "<base64 opcional>"}` | `ok`, `numero`, `minucias`, `imagen` (PNG data URL), `mensaje` |
| `POST` | `/cancelar` | vacío | `ok`, `mensaje`, `cancelado: true` |
| `OPTIONS` | cualquiera | — | preflight CORS |

Si el lector está ocupado: HTTP `409` con `ok: false`.

Si la página cancela con `/cancelar` mientras hay una lectura: esa lectura responde HTTP `499` con `ok: false` y `cancelado: true`, y suelta el candado.

## Minucias

Blob zlib+JSON del ndarray `(N, 4)`, enviado en base64. Misma serialización que `serializar_template` / `deserializar_template` en el servidor.
