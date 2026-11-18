from pathlib import Path

import yaml

from delphi.config import settings


def download_sources(sources_yaml: Path | None = None) -> None:
    """Завантажує тексти античних авторів у data/raw/ згідно із sources.yaml."""
    src_file = sources_yaml or (settings.data_dir / "sources.yaml")
    if not src_file.exists():
        raise FileNotFoundError(f"Файл конфігурації джерел не знайдено: {src_file}")

    with open(src_file, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    raw_dir = settings.data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print(f"Завантаження {len(data.get('sources', []))} джерел у {raw_dir}...")
