"""arcet — effective Azure permissions, with the chain that explains them."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("arcet")
except PackageNotFoundError:  # pragma: no cover - only when running from source
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
