# Agente de huella para kioscos

Artefacto chico: solo el proceso local que lee el AS608 por USB. **No** lleva Django, Postgres ni el resto del repo.

La página web sigue saliendo del servidor. El navegador del kiosco llama a `http://127.0.0.1:8766`.

## Qué instalar en cada kiosco

1. En una máquina de desarrollo, desde la raíz del repo:

   ```bash
   python agente-kiosco/empaquetar.py
   ```

2. Copia `agente-kiosco/dist/agente-huella-kiosco-<version>.zip` al kiosco y descomprímelo.

3. En el kiosco (Windows):

   ```bat
   instalar.bat
   arrancar.bat
   ```

4. Deja el lector USB conectado y abre la página del sistema en el navegador.

## Variables opcionales

| Variable | Efecto |
|----------|--------|
| `HUELLA_AGENTE_PUERTO` | Puerto local (default `8766`) |
| `HUELLA_PUERTO` | Fuerza el COM/TTY del adaptador |
| `HUELLA_BAUD` | Fuerza la velocidad serie |

## Desarrollo en el repo

Sin empaquetar:

```bash
cd agente-kiosco
python arrancar.py
```

Eso usa `PaginaRegistro/Usuarios/hardware` directamente.

## Contrato

Ver [CONTRATO.md](CONTRATO.md). Si cambias rutas o el formato de minucias, sube `VERSION_CONTRATO` en `contrato.py` y vuelve a empaquetar.
