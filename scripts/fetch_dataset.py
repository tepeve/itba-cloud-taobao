import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "data" / "raw" / "UserBehavior.csv"
DATASET = "marwa80/userbehavior"
KAGGLE_ENV_DOC = """\
Este dataset requiere una cuenta Kaggle gratuita y un API token.

 1. Entrar en https://www.kaggle.com/settings (cuenta > Settings > API).
 2. Clic en 'Create New Token' (descarga kaggle.json).
 3. Opciones para pasar las credenciales:
      a) Env: exportar KAGGLE_USERNAME=<usuario> KAGGLE_KEY=<token>
      b) Archivo: colocar kaggle.json en ~/.kaggle/kaggle.json (chmod 600)
"""


def _check_creds():
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        return
    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    if kaggle_json.exists() and kaggle_json.stat().st_size > 0:
        return
    print("Faltan credenciales de Kaggle.\n" + KAGGLE_ENV_DOC, file=sys.stderr)
    sys.exit(1)


def fetch(force=False):
    if not force and TARGET.exists():
        print(f"{TARGET} ya existe. Usar --force para re-descargar.")
        return
    _check_creds()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    zip_path = TARGET.parent / "userbehavior.zip"
    print(f"Descargando {DATASET} de Kaggle...")
    result = subprocess.run(
        [
            "uvx", "kaggle", "datasets", "download",
            "-d", DATASET, "-p", str(TARGET.parent), "--unzip",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if zip_path.exists():
            zip_path.unlink()
        err = result.stderr.strip() or result.stdout.strip()
        if "401" in err or "Unauthorized" in err:
            print(
                "Credenciales invalidas. Verificar KAGGLE_USERNAME / KAGGLE_KEY "
                "o ~/.kaggle/kaggle.json.",
                file=sys.stderr,
            )
        else:
            print(f"Error al descargar: {err}", file=sys.stderr)
        sys.exit(result.returncode)
    if zip_path.exists():
        zip_path.unlink()
    if not TARGET.exists():
        print(
            f"No se encontro {TARGET.name} tras la descarga. "
            f"Verificar que el dataset {DATASET} contenga el archivo esperado.",
            file=sys.stderr,
        )
        sys.exit(1)
    size_mb = TARGET.stat().st_size / (1024 * 1024)
    print(f"{TARGET.name} descargado ({size_mb:.0f} MB).")


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--force", action="store_true")
    args, _ = parser.parse_known_args()
    fetch(force=args.force)


if __name__ == "__main__":
    main()
