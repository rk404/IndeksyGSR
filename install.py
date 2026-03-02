"""
Skrypt instalacyjny projektu – działa na Windows, macOS i Linux.
Uruchomienie: python install.py
"""

import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


ROOT_DIR = Path(__file__).parent
BACKEND_DIR = ROOT_DIR / "backend"


def run(cmd: list[str], **kwargs) -> None:
    print(f"  > {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def install_uv() -> None:
    system = platform.system()
    print(f"--- Instalacja uv (wykryto: {system}) ---")

    if system in ("Darwin", "Linux"):
        installer_url = "https://astral.sh/uv/install.sh"
        with urllib.request.urlopen(installer_url) as resp:
            script = resp.read()
        run(["sh"], input=script)
        # Dodaj ~/.local/bin do PATH dla reszty procesu
        local_bin = str(Path.home() / ".local" / "bin")
        os.environ["PATH"] = local_bin + os.pathsep + os.environ.get("PATH", "")

    elif system == "Windows":
        installer_url = "https://astral.sh/uv/install.ps1"
        run([
            "powershell",
            "-ExecutionPolicy", "ByPass",
            "-c", f"irm {installer_url} | iex",
        ])
        # uv >= 0.5 instaluje do %USERPROFILE%\.local\bin
        # starsze wersje instalowały do %APPDATA%\uv\bin
        # dodajemy obie lokalizacje do PATH na wszelki wypadek
        candidates = [
            Path.home() / ".local" / "bin",
            Path(os.environ.get("APPDATA", "")) / "uv" / "bin",
        ]
        extra = os.pathsep.join(str(p) for p in candidates)
        os.environ["PATH"] = extra + os.pathsep + os.environ.get("PATH", "")

    else:
        sys.exit(
            f"Nieznany system: {system}. "
            "Zainstaluj uv ręcznie: https://docs.astral.sh/uv/getting-started/installation/"
        )


def main() -> None:
    print("=== Instalacja zależności projektu ===")

    # 1. uv
    if shutil.which("uv"):
        result = subprocess.run(["uv", "--version"], capture_output=True, text=True)
        print(f"--- uv już zainstalowany: {result.stdout.strip()} ---")
    else:
        install_uv()

    # 2. Pakiety Python (backend)
    print("\n--- Instalacja pakietów Python (uv sync) ---")
    run(["uv", "sync"], cwd=ROOT_DIR)

    # 2a. macOS: Python 3.13 pomija .pth pliki z flagą UF_HIDDEN (uv ustawia ją na .venv)
    if platform.system() == "Darwin":
        print("\n--- macOS: usuwanie flagi UF_HIDDEN z site-packages ---")
        venv_site = ROOT_DIR / ".venv" / "lib"
        if venv_site.exists():
            run(["chflags", "-R", "nohidden", str(venv_site)])

    # 3. Playwright – przeglądarka Chromium
    print("\n--- Instalacja przeglądarki Playwright: Chromium ---")
    # playwright nie jest dostępny jako komenda CLI w uv – używamy modułu Pythona
    run(["uv", "run", "python", "-m", "playwright", "install", "chromium"], cwd=BACKEND_DIR)

    # 5. Modele HuggingFace BGE
    print("\n--- Pobieranie modeli HuggingFace (może potrwać kilka minut) ---")
    hf_script = """
print("Pobieranie BAAI/bge-m3 (~570 MB)...")
from FlagEmbedding import BGEM3FlagModel
BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)

print("Pobieranie BAAI/bge-reranker-v2-m3 (~1.1 GB)...")
from FlagEmbedding import FlagReranker
FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=True, normalize=True)
"""
    run(["uv", "run", "python", "-c", hf_script], cwd=BACKEND_DIR)

    print("\n=== Setup zakończony pomyślnie ===")


if __name__ == "__main__":
    main()
