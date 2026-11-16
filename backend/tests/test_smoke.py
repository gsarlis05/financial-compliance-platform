"""Smoke tests for the project skeleton."""

import importlib
import pkgutil

from django.test import Client

import fcp.modules


def test_healthz_returns_ok() -> None:
    response = Client().get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_every_module_exposes_a_public_api() -> None:
    names = [m.name for m in pkgutil.iter_modules(fcp.modules.__path__)]
    assert names, "no modules found"
    for name in names:
        api = importlib.import_module(f"fcp.modules.{name}.api")
        assert isinstance(api.__all__, list)
