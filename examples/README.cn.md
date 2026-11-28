# 示例

[English](README.md) · 简体中文

所有示例均可在仓库根目录直接运行，不需要 SDK、API key 或网络：

```bash
uv run --extra test python examples/01_custom_adapter.py
```

如果未安装包、直接用 `python` 运行，请设置 `PYTHONPATH=src`。`tests/integration/test_examples.py` 会执行每个脚本并断言退出码为 0。

| 示例 | 说明 |
| --- | --- |
| `01_custom_adapter.py` | 实现 `BaseAdapter`，从内存数据源采集 |
| `02_fake_mode.py` | `fake=True` 会跳过 `collect_once()`，但 `ensure_ready()` 仍执行 |
| `03_policies.py` | 为不稳定数据源注入 `RetryPolicy` 与 `RateLimitPolicy` |
| `04_key_rotation.py` | 拆分逗号分隔的多个 key，并在模拟 429 时轮换 |
| `05_framework_pagination.py` | 由 `options` 驱动的正向页码分页 |
| `06_multi_source.py` | 注册多个数据源并复用缓存的适配器实例 |

注意：

- 内置适配器在 `ensure_ready()` 中初始化 SDK；`fake=True` 时该步骤仍会发生。要完全离线演练，请用 `02_fake_mode.py` 那样的轻量自定义适配器。
- `04_key_rotation.py` 中通过私有属性查看 key 池仅用于演示，属于实现细节。
- 适配器契约与策略细节见[开发指南](../docs/development-guide.cn.md)。
