"""Download source texts into data/raw/ (gitignored)."""

from pathlib import Path

import httpx

from delphi.config import settings
from delphi.ingest.sources import Source

USER_AGENT = (
    "DelphiOracleBot/0.1 (https://github.com/IdzaYar120/orakul_myth; educational RAG project)"
)


def raw_dir() -> Path:
    path = settings.data_dir / "raw"
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_source(
    source: Source,
    force: bool = False,
    client: httpx.Client | None = None,
    filename: str | None = None,
) -> Path:
    """Download one source file unless it is already present; returns the local path."""
    target = raw_dir() / (filename or source.raw_filename)
    if target.exists() and target.stat().st_size > 0 and not force:
        return target
    if not source.download_url:
        raise ValueError(f"{source.id}: немає download_url у sources.yaml")
    if client is None:
        with httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True
        ) as own:
            resp = own.get(source.download_url)
    else:
        resp = client.get(source.download_url)
    resp.raise_for_status()
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(resp.content)
    tmp.replace(target)
    return target
