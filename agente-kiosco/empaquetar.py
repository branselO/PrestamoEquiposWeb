#!/usr/bin/env python3
"""Arma el zip del agente para instalar en cada kiosco.

No duplica el código fuente: copia desde PaginaRegistro/Usuarios/hardware
solo los módulos del lector. biometria_cache.py se queda en el servidor.

Uso, desde la raíz del repo o desde esta carpeta:

    python agente-kiosco/empaquetar.py
    python empaquetar.py
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent
HARDWARE_ORIGEN = REPO / "PaginaRegistro" / "Usuarios" / "hardware"
DIST = AQUI / "dist"

# Módulos del lector. El índice en RAM de Django no viaja al kiosco.
# __init__.py del kiosco es liviano: no reexporta todo el API de Django.
MODULOS = (
    "agente.py",
    "contrato.py",
    "hardware.py",
    "huella_pc.py",
    "prueba_gabor.py",
    "verificar_as608.py",
)

INIT_HARDWARE_KIOSCO = '''\
"""Lector AS608 empaquetado para el kiosco.

La página web llama a Usuarios.hardware.agente. El índice biométrico en RAM
sigue en el servidor.
"""

from .contrato import VERSION_AGENTE, VERSION_CONTRATO

__all__ = ["VERSION_AGENTE", "VERSION_CONTRATO"]
'''

ARCHIVOS_RAIZ = (
    "requirements.txt",
    "README.md",
    "CONTRATO.md",
    "arrancar.py",
    "arrancar.bat",
    "instalar.bat",
)


def _version_agente() -> str:
    ruta = HARDWARE_ORIGEN / "contrato.py"
    spec = importlib.util.spec_from_file_location("contrato_kiosco", ruta)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No pude leer {ruta}")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return str(modulo.VERSION_AGENTE)


def _limpiar_destino(destino: Path) -> None:
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)


def _copiar_paquete(destino: Path) -> None:
    usuarios = destino / "Usuarios"
    hardware = usuarios / "hardware"
    hardware.mkdir(parents=True)
    (usuarios / "__init__.py").write_text(
        '"""Paquete mínimo para arrancar el agente sin Django."""\n',
        encoding="utf-8",
    )
    (hardware / "__init__.py").write_text(INIT_HARDWARE_KIOSCO, encoding="utf-8")
    faltantes = []
    for nombre in MODULOS:
        origen = HARDWARE_ORIGEN / nombre
        if not origen.is_file():
            faltantes.append(nombre)
            continue
        shutil.copy2(origen, hardware / nombre)
    if faltantes:
        raise FileNotFoundError(
            "Faltan módulos del lector en "
            f"{HARDWARE_ORIGEN}: {', '.join(faltantes)}"
        )


def _copiar_raiz(destino: Path) -> None:
    for nombre in ARCHIVOS_RAIZ:
        origen = AQUI / nombre
        if not origen.is_file():
            raise FileNotFoundError(f"Falta {origen}")
        shutil.copy2(origen, destino / nombre)


def _escribir_version(destino: Path, version: str) -> None:
    (destino / "VERSION").write_text(version + "\n", encoding="utf-8")


def _zip(carpeta: Path, archivo_zip: Path) -> None:
    if archivo_zip.exists():
        archivo_zip.unlink()
    with zipfile.ZipFile(archivo_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for ruta in sorted(carpeta.rglob("*")):
            if ruta.is_file():
                zf.write(ruta, ruta.relative_to(carpeta.parent).as_posix())


def empaquetar(salida: Path | None = None) -> Path:
    if not HARDWARE_ORIGEN.is_dir():
        raise FileNotFoundError(f"No encontré el paquete del lector: {HARDWARE_ORIGEN}")
    version = _version_agente()
    nombre = f"agente-huella-kiosco-{version}"
    DIST.mkdir(parents=True, exist_ok=True)
    destino = DIST / nombre
    _limpiar_destino(destino)
    _copiar_paquete(destino)
    _copiar_raiz(destino)
    _escribir_version(destino, version)
    archivo_zip = salida or (DIST / f"{nombre}.zip")
    archivo_zip = archivo_zip.resolve()
    archivo_zip.parent.mkdir(parents=True, exist_ok=True)
    _zip(destino, archivo_zip)
    return archivo_zip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Empaqueta el agente de huella para kioscos.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Ruta del .zip de salida (por defecto agente-kiosco/dist/).",
    )
    args = parser.parse_args(argv)
    try:
        zip_path = empaquetar(args.output)
    except (OSError, RuntimeError, FileNotFoundError) as error:
        print(f"No pude empaquetar el agente: {error}", file=sys.stderr)
        return 1
    print(f"Listo: {zip_path}")
    print(f"Carpeta: {zip_path.with_suffix('')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
