from __future__ import annotations
 
 # Expose package version from installed metadata as the single source of truth
try:
    from importlib.metadata import PackageNotFoundError, version
except Exception:  # pragma: no cover - fallback for older Python
    # For very old environments; not expected with requires-python>=3.11
    from importlib_metadata import PackageNotFoundError, version  # type: ignore
 
try:
    __version__ = version("halal-image-downloader")
except PackageNotFoundError:
    # When running from source without installation, fall back to a dev marker
    __version__ = "0.0.0.dev"
 
 
def main() -> None:
    print("Hello from halal-image-downloader!")
