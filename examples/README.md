# Examples

[English](README.md) · [简体中文](README.cn.md)

All examples are runnable from the repository root with no SDK, API key or network access:

```bash
uv run --extra test python examples/01_custom_adapter.py
```

Set `PYTHONPATH=src` when running with a plain `python` and without installing the package. `tests/integration/test_examples.py` executes every script and asserts a zero exit code.

| Example | What it shows |
| --- | --- |
| `01_custom_adapter.py` | Implement `BaseAdapter` and collect from an in-memory source |
| `02_fake_mode.py` | `fake=True` skips `collect_once()`, but `ensure_ready()` still runs |
| `03_policies.py` | Inject `RetryPolicy` and `RateLimitPolicy` for a flaky source |
| `04_key_rotation.py` | Split comma-separated keys and rotate on a simulated 429 |
| `05_framework_pagination.py` | Forward page-number pagination driven by `options` |
| `06_multi_source.py` | Register several sources and reuse cached adapter instances |

Notes:

- Built-in adapters initialize their SDK in `ensure_ready()`. With `fake=True`, that step still happens; use a small custom adapter (as in `02_fake_mode.py`) for a fully offline dry run.
- The key pool in `04_key_rotation.py` is inspected through a private attribute for demonstration only; treat it as an implementation detail.
- See the [development guide](../docs/development-guide.md) for the adapter contract and policy internals.
