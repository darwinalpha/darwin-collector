# darwin-collector

[English](https://github.com/darwinalpha/darwin-collector/blob/main/README.md) · 简体中文

一个只做**数据采集**的库：注册数据源适配器，把一次采集任务跑完，返回统一的结果对象。

它不读配置文件、不写文件、不清洗数据、不做跨源路由和故障切换。调度、配置解析、写入落盘由上层负责。

- **小而稳定的接口**：一个 `collect()` 入口，一套请求与结果契约
- **无配置**：凭证与参数由调用方传入，库不读环境变量或 `adapter.json`
- **策略可注入**：重试、限流、分页与 API key 轮换都是显式的 `Policies`
- **统一异常**：类型化错误携带数据源、方法和尝试次数上下文
- **SDK 按需安装**：硬依赖只有 `pandas`，每个数据源是一个 extra

Python >= 3.10。

```bash
pip install darwin-collector                       # 核心（仅 pandas）
pip install 'darwin-collector[tushare]'            # 单个 SDK
pip install 'darwin-collector[finzdata,yfinance]'  # 多个 SDK
pip install 'darwin-collector[all]'                # 全部 SDK
pip install 'darwin-collector[test]'               # 含 pytest
```

---

## 1. 设计边界

| 负责 | 不负责 |
| --- | --- |
| 适配器注册与查找 | 读取 `adapter.json` 或任何配置文件 |
| 初始化 / 登录 | Writer 写入 |
| 单次 SDK 调用 `collect_once()` | 清洗 / 去重 |
| 重试、限流、分页策略 | 跨源路由 / 故障切换 |
| 多 API key 拆分与轮换 | Worker 进程管理（仅预埋扩展点） |
| 类型化异常与 `CollectResult` | 环境变量加载 |

内置默认值是 `defaults.py` 中的代码常量，其余参数由调用方传入。执行链与适配器契约见[开发指南](docs/development-guide.cn.md)。

---

## 2. 最小用法

```python
from darwin_collector import AdapterManager, CollectRequest
from darwin_collector.adapters.tushare import TushareAdapter

manager = AdapterManager()
manager.register("tushare", TushareAdapter)

request = CollectRequest(
    source="tushare",
    method="daily",
    params={"ts_code": "000001.SZ", "start_date": "20240101", "end_date": "20240131"},
    credentials={"token": "<your token>"},  # 由调用方解析后传入
)
result = manager.collect(request)
df = result.to_dataframe()
print(result.row_count, result.chunk_count, result.elapsed_ms)
manager.close()
```

`fake=True` 会跳过 `collect_once()` 并返回空 DataFrame，但 `ensure_ready()` 仍会执行。要完全离线演练，请用轻量自定义适配器：

```python
from darwin_collector import AdapterManager, CollectRequest
from darwin_collector.adapters.base import BaseAdapter

class DemoAdapter(BaseAdapter):
    def get_source_name(self):
        return "demo"

    def collect_once(self, method, **kwargs):
        raise AssertionError("not called in fake mode")

manager = AdapterManager()
manager.register("demo", DemoAdapter)
result = manager.collect(CollectRequest(source="demo", method="daily", fake=True))
assert result.fake and result.row_count == 0
```

未注册的数据源抛 `AdapterNotRegisteredError`；不支持的 SDK 方法抛 `MethodNotSupportedError`。

---

## 3. 核心契约

| 对象 | 职责 |
| --- | --- |
| `AdapterManager` | 注册工厂、缓存适配器实例，提供 `collect()` 与 `close()` |
| `CollectRequest` | `source`、`method`、`params`、`options`、`credentials`、`policies`、`fake` |
| `CollectResult` | `frames`、`attempts`、`elapsed_ms`、`fake`，以及 `to_dataframe()`、`to_records()`、`row_count`、`chunk_count` |
| `Policies` | 可选的 `RetryPolicy`、`RateLimitPolicy`、`Paginator`、`pagination_mode`、`KeyRotationPolicy` |
| `BaseAdapter` | 实现 `get_source_name()` 与 `collect_once(method, **kwargs)`；可选 `ensure_ready()`、`reauth()`、`close()` |

`CollectResult` 不含文件路径、写入状态或清洗配置：拿到 DataFrame 后如何处理由调用方决定。

执行链：

```text
AdapterManager.collect(request)
  -> resolve_backend(source)             # 当前恒为 direct
  -> get_adapter(source)                 # 复用缓存实例
  -> Executor.execute(adapter, request)
       -> configure(policies)
       -> ensure_ready(credentials)
       -> 按 pagination_mode 选择分页器
       -> rate_limit.before_call() + retry.run(collect_once)
       -> framework 模式下分页
       -> CollectResult
```

适配器实例按 manager 缓存，可跨多次 `collect()` 复用；`close()` 由宿主调用，用于释放会话。`resolve_backend()` 是唯一的后端选择点，当前恒为 `direct`（本进程直连），worker 分支已预埋但未实现。

---

## 4. 支持的数据源

| 数据源 | 导入路径 | 凭证（由调用方传入） | 分页模式 |
| --- | --- | --- | --- |
| tushare | `darwin_collector.adapters.tushare.TushareAdapter` | `{"token": ...}` | framework（反向日期） |
| ftshare | `darwin_collector.adapters.ftshare.FtshareAdapter` | `{"api_keys": [...]}` 或 `{"api_key": ...}` | adapter（SDK 内部翻页）；可选 framework 分块 |
| tickflow | `darwin_collector.adapters.tickflow.TickflowAdapter` | `{"token": ...}` | framework（毫秒切片） |
| baostock | `darwin_collector.adapters.baostock.BaostockAdapter` | 无需凭证 | none |
| ohlcvault | `darwin_collector.adapters.ohlcvault.OhlcvaultAdapter` | 可选 `{"mirrors": [...], "snapshot": ...}` | none |
| finzdata | `darwin_collector.adapters.finzdata.FinzdataAdapter` | `{"api_key": ...}`（也接受 `token`） | none；可选 framework 分块 |
| yfinance | `darwin_collector.adapters.yfinance.YfinanceAdapter` | 无需凭证；可选 `{"session": ...}` | none；可选 framework 分块 |

注册方式一致：

```python
from darwin_collector.adapters.baostock import BaostockAdapter

manager.register("baostock", BaostockAdapter)
result = manager.collect(CollectRequest(
    source="baostock",
    method="query_history_k_data_plus",
    params={"code": "sh.000001", "start_date": "20240101", "end_date": "20240131",
            "fields": "date,code,close", "frequency": "d"},
))
```

FinzData 直接映射官方 `finzdata.Client` 的方法名（`prices`、`minutes`、`cot`、`futures`、`macro`、`gex`、`fundamentals`、`valuation`、`datasets`、`me` 等），也支持 yfinance 风格别名（`history`、`download`）：

```python
from darwin_collector.adapters.finzdata import FinzdataAdapter

manager.register("finzdata", FinzdataAdapter)
result = manager.collect(CollectRequest(
    source="finzdata",
    method="prices",
    params={"symbol": "MSFT", "start": "2025-01-01", "end": "2025-01-31"},
    credentials={"api_key": "<your key>"},  # 库不读 FINZDATA_API_KEY
))
```

yfinance 无需 API key。`download`、`history`、`info`、`financials`、`dividends` 等 Ticker 成员直接映射官方 SDK；空 DataFrame 是正常结果而非异常。

---

## 5. 策略与默认值

在 `CollectRequest` 中传入 `Policies`；为 `None` 的字段使用 `defaults.py` 中的常量。

| 策略 | 默认值 |
| --- | --- |
| `RetryPolicy` | 3 次尝试，基础延迟 500 ms，退避系数 2.0，认证失败重新登录一次 |
| `RateLimitPolicy` | 每次调用间隔 500 ms，冷却 5000 ms（分页器自身不 sleep） |
| 分页 | 最多 100 次迭代 / 页，页大小 500，日期字段 `trade_date`，连续 3 个空片后停止 |
| `KeyRotationPolicy` | 限流冷却 30 s，认证冷却 300 s，最多轮换 3 次，两类错误都触发轮换 |

只有限流和网络错误会重试；认证错误先 `reauth()` 一次，随后直接抛出；数据错误不重试。

```python
from darwin_collector import CollectRequest, Policies
from darwin_collector.policies import RateLimitPolicy, RetryPolicy

request = CollectRequest(
    source="tushare", method="daily",
    params={"ts_code": "000001.SZ"},
    policies=Policies(
        retry=RetryPolicy(max_attempts=5, base_delay_ms=200, backoff=1.5),
        rate_limit=RateLimitPolicy(interval_ms=100, cooldown_ms=2000),
    ),
)
```

`pagination_mode` 决定由谁翻页：

| 模式 | 行为 |
| --- | --- |
| `none` | 单次 `collect_once()` 调用，不分页 |
| `adapter` | SDK 已返回完整结果，executor 只调用一次 |
| `framework` | `collect_once()` 只返回一页 / 一片，分页器循环调用 |

`framework` 模式下，`CollectRequest.options` 的触发键决定策略（按检查顺序）：

| 选项 | 策略 |
| --- | --- |
| `max_lines` | 反向日期分页，替换 `start_date` / `end_date` |
| `chunk_months` | 自然月切片，替换 `since_ts_millis` / `until_ts_millis` |
| `chunk_ms` | 按天切毫秒时间戳，替换 `start_time` / `end_time` |
| `paginate` | 正向页码翻页，替换 `page` |
| `chunk_days` | 按天切片，替换 `start_date` / `end_date` |

所有切片策略都有 `max_iterations` / `max_pages` 上限，并在连续 `max_empty_chunks` 个空结果后停止。

---

## 6. 多 API key 与轮换

需要 key 的数据源（tushare / ftshare / tickflow / finzdata）共享库级 key 池。凭证值中的逗号会自动拆分，列表也支持：

```python
credentials={"token": "key1, key2, key3"}     # 拆成 3 个 key
credentials={"api_keys": ["k1", "k2"]}        # 等价
```

- 遇到限流或认证失败时轮换到下一个 key；失败的 key 进入冷却，到期自动恢复，不会永久拉黑。
- 轮换状态保存在适配器实例上，常驻进程跨 `collect()` 复用同一个池；冷却基于单调时钟，无需外部协调。
- 单 key 时保持原有行为：不做内部轮换，交由框架重试层处理。
- 可通过 `Policies` 注入自定义的 `KeyRotationPolicy`：

```python
from darwin_collector import KeyRotationPolicy, Policies

request = CollectRequest(
    source="tushare", method="daily",
    credentials={"token": "key1, key2"},
    policies=Policies(key_rotation=KeyRotationPolicy(
        cooldown_seconds=30,
        auth_cooldown_seconds=300,
        max_rotations=3,
    )),
)
```

错误映射属于适配器契约：FinzData 的 `401` 映射认证错误、`429` 映射限流、`5xx` 映射网络错误，`403` 映射为不重试的数据错误；yfinance 的 `YFRateLimitError` 映射限流，数据缺失或参数无效映射数据错误，连接 / 超时映射网络错误。

---

## 7. 文档与示例

- [开发指南](docs/development-guide.cn.md)：执行链、新增数据源、策略与 key 池细节
- [示例](examples/README.cn.md)：六个无需真实 SDK 与网络即可运行的脚本

| 示例 | 说明 |
| --- | --- |
| `01_custom_adapter.py` | 实现 `BaseAdapter`，从内存数据源采集 |
| `02_fake_mode.py` | 用 `fake=True` 在未安装 SDK 时校验请求 |
| `03_policies.py` | 为不稳定数据源注入重试与限流策略 |
| `04_key_rotation.py` | 拆分多个 key，并在模拟 429 时轮换 |
| `05_framework_pagination.py` | 由 `options` 驱动的正向页码分页 |
| `06_multi_source.py` | 注册多个数据源并复用适配器实例 |

---

## 8. 测试

```bash
uv run --extra test python -m pytest tests -q
# 或：python -m pytest tests -q
```

测试覆盖单元行为、端到端采集、适配器行为、示例脚本执行、公开导出与双语文档契约。

---

## 9. 许可

MIT，见 [LICENSE](LICENSE)。
