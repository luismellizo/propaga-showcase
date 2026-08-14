"""
Corre la suite independiente completa y devuelve un código de salida real.

Cada script corre en su propio proceso: comparten el mismo `setup_django()` y
tocan la misma base de datos, así que aislarlos evita que el estado de uno
contamine al siguiente.

Los tests de red están fuera de la lista por defecto — se habilitan con
PROPAGA_NETWORK_TESTS=1 y se corren aparte. Ver test_04_downloads.py.
"""
import os
import subprocess
import sys

SCRIPTS = [
    "test_01_auth.py",
    "test_02_video_processing.py",
    "test_03_social_propagation.py",
    "test_04_downloads.py",
    "test_05_infrastructure.py",
]


def run_script(script_name):
    print(f"\n{'=' * 60}")
    print(f"🎬 EXECUTING: {script_name}")
    print(f"{'=' * 60}\n")

    result = subprocess.run(
        [sys.executable, script_name],
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )

    if result.returncode == 0:
        print(f"\n✅ {script_name} COMPLETED SUCCESSFULLY.")
        return True

    print(f"\n❌ {script_name} FAILED (exit {result.returncode}).")
    return False


def main():
    print("🚀 STARTING PROPAGA INDEPENDENT TEST SUITE")

    results = {script: run_script(script) for script in SCRIPTS}

    print(f"\n{'#' * 60}")
    print("🏁 FINAL SUMMARY")
    print(f"{'#' * 60}")

    for script, passed in results.items():
        print(f"{'✅ PASS' if passed else '❌ FAIL'} : {script}")

    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
