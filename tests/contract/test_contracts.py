"""Contract tests for the public library surface."""

import inspect

import darwin_collector as dc
from darwin_collector.adapters.base import BaseAdapter


def test_manager_public_methods_are_new_only():
    methods = set(dir(dc.AdapterManager))
    assert {"register", "get_adapter", "collect", "close"} <= methods
    # Old config-loading surface must not exist.
    assert "load_from_sources" not in methods
    assert "get_type_config" not in methods
    assert "render_type_config" not in methods


def test_exports_are_present():
    for name in dc.__all__:
        assert hasattr(dc, name), name


def test_base_adapter_contract():
    assert hasattr(BaseAdapter, "collect_once")
    assert hasattr(BaseAdapter, "ensure_ready")
    assert hasattr(BaseAdapter, "reauth")
    assert hasattr(BaseAdapter, "close")
    assert "fetch" not in dir(BaseAdapter)


def test_no_logger_or_config_dependency_in_source():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "src" / "darwin_collector"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "darwin_config" not in text, path
        assert "darwin_logger" not in text, path
        assert "adapter.json" not in text, path
