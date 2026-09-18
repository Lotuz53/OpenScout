"""Regression checks for the Python dependency security baseline."""

import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dependency_lock_removes_unfixed_python_jose_ecdsa_chain() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependencies = [dependency.lower() for dependency in project["project"]["dependencies"]]
    lock_text = (ROOT / "uv.lock").read_text()

    assert not any(dependency.startswith("python-jose") for dependency in dependencies)
    assert '[package]\nname = "python-jose"' not in lock_text
    assert '[package]\nname = "ecdsa"' not in lock_text


def test_dependency_lock_uses_fixed_click_version() -> None:
    lock_text = (ROOT / "uv.lock").read_text()
    match = re.search(r'\[\[package\]\]\nname = "click"\nversion = "([^"]+)"', lock_text)

    assert match is not None
    assert tuple(int(part) for part in match.group(1).split(".")) >= (8, 3, 3)

    for requirements_path in (ROOT / "docsgpt").glob("requirements*.txt"):
        requirements = requirements_path.read_text()
        assert "python-jose==" not in requirements
        assert "ecdsa==" not in requirements
        exported_click = re.search(r"^click==([^\n]+)$", requirements, re.MULTILINE)
        assert exported_click is not None
        assert tuple(int(part) for part in exported_click.group(1).split(".")) >= (8, 3, 3)
