"""Contract tests for the public library surface and bilingual docs."""

import re
from pathlib import Path

import darwin_collector as dc
from darwin_collector.adapters.base import BaseAdapter

ROOT = Path(__file__).resolve().parents[2]


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


def test_english_docs_have_no_chinese_except_language_switch() -> None:
    han = re.compile(r"[\u4e00-\u9fff]")
    targets = [
        ROOT / "README.md",
        ROOT / "docs" / "development-guide.md",
        ROOT / "examples" / "README.md",
    ]
    for path in targets:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "简体中文" in line:
                continue
            assert not han.search(line), f"Chinese text in {path.name}:{number}"


def test_chinese_docs_exist() -> None:
    for path in (
        ROOT / "README.cn.md",
        ROOT / "docs" / "development-guide.cn.md",
        ROOT / "examples" / "README.cn.md",
    ):
        assert path.exists(), path
        assert re.search(r"[\u4e00-\u9fff]", path.read_text(encoding="utf-8"))


def test_root_readme_uses_absolute_language_links() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "](README.cn.md)" not in text
    assert "https://github.com/darwinalpha/darwin-collector/blob/main/README.cn.md" in text

    chinese = (ROOT / "README.cn.md").read_text(encoding="utf-8")
    assert "](README.md)" not in chinese
    assert "https://github.com/darwinalpha/darwin-collector/blob/main/README.md" in chinese

