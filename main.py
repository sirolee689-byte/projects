from __future__ import annotations

from pathlib import Path

from app.settings import load_app_settings
from app.ui.main_window import run_main_window


def main() -> None:
    root = Path(__file__).resolve().parent
    settings = load_app_settings(root / "config.json")
    run_main_window(Path(settings.share_root), settings.download_dir)


if __name__ == "__main__":
    main()

