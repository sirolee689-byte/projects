from __future__ import annotations

from pathlib import Path

from app.config import load_software_list
from app.settings import load_app_settings
from app.ui.main_window import run_main_window


def main() -> None:
    root = Path(__file__).resolve().parent
    settings = load_app_settings(root / "config.json")
    items = load_software_list(root / "software_list.json")
    run_main_window(items, settings.download_dir)


if __name__ == "__main__":
    main()

