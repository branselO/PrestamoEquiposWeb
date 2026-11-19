#!/usr/bin/env python3
"""Prueba el zip del kiosco sin instalar Django ni el lector."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent


class EmpaquetarKioscoTests(unittest.TestCase):
    def test_zip_incluye_agente_y_omite_cache_del_servidor(self):
        sys.path.insert(0, str(AQUI))
        import empaquetar

        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "kiosco.zip"
            generado = empaquetar.empaquetar(zip_path)
            self.assertTrue(generado.is_file())
            with zipfile.ZipFile(generado) as zf:
                nombres = set(zf.namelist())
            prefijo = f"agente-huella-kiosco-{empaquetar._version_agente()}/"
            self.assertIn(prefijo + "arrancar.py", nombres)
            self.assertIn(prefijo + "Usuarios/hardware/agente.py", nombres)
            self.assertIn(prefijo + "Usuarios/hardware/contrato.py", nombres)
            self.assertIn(prefijo + "VERSION", nombres)
            self.assertNotIn(prefijo + "Usuarios/hardware/biometria_cache.py", nombres)

    def test_agente_empaquetado_reporta_contrato_en_estado(self):
        sys.path.insert(0, str(AQUI))
        import empaquetar

        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "kiosco.zip"
            empaquetar.empaquetar(zip_path)
            destino = Path(tmp) / "extraido"
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(destino)
            version = empaquetar._version_agente()
            raiz = destino / f"agente-huella-kiosco-{version}"
            sys.path.insert(0, str(raiz))
            from Usuarios.hardware import agente

            servidor = agente.servir(0)
            hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
            hilo.start()
            try:
                host, puerto = servidor.server_address
                with urllib.request.urlopen(f"http://{host}:{puerto}/estado", timeout=3) as resp:
                    cuerpo = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(cuerpo["ok"])
                self.assertEqual(cuerpo["version_agente"], agente.VERSION_AGENTE)
                self.assertEqual(cuerpo["version_contrato"], agente.VERSION_CONTRATO)
            finally:
                servidor.shutdown()
                servidor.server_close()


if __name__ == "__main__":
    unittest.main()
