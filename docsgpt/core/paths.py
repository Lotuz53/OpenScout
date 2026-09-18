"""Where DocsGPT keeps its files.

Three locations matter. The package directory holds code and the data that
ships with it (prompts, model catalogs, migrations). A checkout, when the
package is imported from one, is the directory holding ``pyproject.toml``.
The data home is where runtime data lives: ``.env``, ``inputs``, ``indexes``.

The home is ``DOCSGPT_HOME`` when set, else the checkout, else the current
directory. That keeps a source checkout and the Docker image (which runs from
``/app`` with the package beside it) behaving as before, and gives a
``pip install docsgpt`` user a home that is not ``site-packages``.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path

HOME_ENV = "DOCSGPT_HOME"
ENV_FILE_ENV = "DOCSGPT_ENV_FILE"


def warn_on_insecure_env_file(path: Path) -> None:
    """Warn when an environment file can be accessed by group or other users."""
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return
    if mode & 0o077:
        logging.getLogger(__name__).warning(
            "Environment file %s is not private (mode %o); run chmod 600 %s",
            path,
            mode,
            path,
        )


def package_dir() -> Path:
    """The installed ``docsgpt`` package directory."""
    return Path(__file__).resolve().parent.parent


def checkout_root() -> Path | None:
    """The source checkout the package is imported from, or None when installed."""
    root = package_dir().parent
    return root if (root / "pyproject.toml").is_file() else None


def home_dir() -> Path:
    """Directory for runtime data: ``DOCSGPT_HOME``, else the checkout, else cwd."""
    configured = os.environ.get(HOME_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return checkout_root() or Path.cwd()


def env_file() -> Path:
    """The ``.env`` file settings load: ``DOCSGPT_ENV_FILE``, else ``<home>/.env``."""
    configured = os.environ.get(ENV_FILE_ENV)
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"{ENV_FILE_ENV} is set to {path}, which is not a file")
        warn_on_insecure_env_file(path)
        return path
    path = home_dir() / ".env"
    warn_on_insecure_env_file(path)
    return path
