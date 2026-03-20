"""Pytest configuration for domain/compute tests.

Ensures local package roots are importable without relying on editable
installs from a parent project environment.
"""
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[3])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_SERVICE_SRC = str(Path(__file__).resolve().parents[3] / "service" / "src")
if _SERVICE_SRC not in sys.path:
    sys.path.insert(0, _SERVICE_SRC)
