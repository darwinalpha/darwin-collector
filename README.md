# darwin-collector

一个只做**数据采集**的库：注册数据源适配器，把一次采集任务跑完，返回统一的结果对象。

它不读配置文件、不写文件、不清洗数据、不做路由和故障切换。调度、配置解析、写入落盘由上层负责。

## 设计边界

| 负责 | 不负责 |
| --- | --- |
| 适配器注册与查找 | 读取 `adapter.json` 或任何配置文件 |
| 初始化 / 登录 | Writer 写入 |
| 单次 SDK 调用 `collect_once()` | 清洗 / 去重 |
| 重试、限流、分页策略 | 跨源路由 / 故障切换 |
| 多 API key 拆分与轮换 | Worker 进程管理（仅预埋扩展点） |
| 统一异常与 `CollectResult` | |

唯一硬依赖是 `pandas`；各数据源 SDK 按需安装。库内自带的默认设置是代码常量，其余参数由调用方解析后传入。

## 安装

```bash
pip install -e .
pip install -e '.[tushare]'       # 按需安装单个 SDK
pip install -e '.[ftshare,tickflow,baostock,ohlcvault,finzdata,yfinance]'
pip install -e '.[finzdata]'      # FinzData（官方 finzdata SDK）
pip install -e '.[yfinance]'      # yfinance（Yahoo Finance 数据）
pip install -e '.[all]'           # 一次安装全部
```

## 最小用法

```python
from darwin_collector import AdapterManager, CollectRequest
from darwin_collector.adapters.tushare import TushareAdapter

manager = AdapterManager()
manager.register("tushare", TushareAdapter)

request = CollectRequest(
    source="tushare",
    method="daily",
    params={"ts_code": "000001.SZ", "start_date": "20240101", "end_date": "20240131"},
    credentials={"token": "..."},   # 上层解析后传入，库不读环境变量
)
result = manager.collect(request)
df = result.to_dataframe()
```

`fake=True` 时适配器不调用真实 SDK，返回空 DataFrame，可用于验证配置与调用链。

## 分层位置

```
shell 调度 → fetch.py（门面）→ fetcher.py（唤起/采集/调用 Writer）→ darwin-collector → SDK
```

worker 是 collector 的一种可选执行后端，通过 `resolve_backend(source)` 选择。当前恒为 `direct`（本进程直连），分支已预埋但未实现 worker。

## 当前支持的数据源

| 数据源 | 导入路径 | 凭证（由调用方传入） | 分页模式 |
| --- | --- | --- | --- |
| tushare | `adapters.tushare.TushareAdapter` | `{"token": ...}` | framework（反向日期） |
| ftshare | `adapters.ftshare.FtshareAdapter` | `{"api_keys": [...]}` 或 `{"api_key": ...}` | adapter（SDK 内部翻页）；可切 framework 做 chunk |
| tickflow | `adapters.tickflow.TickflowAdapter` | `{"token": ...}` | framework（毫秒切片） |
| baostock | `adapters.baostock.BaostockAdapter` | 无需凭证 | none |
| ohlcvault | `adapters.ohlcvault.OhlcvaultAdapter` | 可选 `{"mirrors": [...], "snapshot": ...}` | none |
| finzdata | `adapters.finzdata.FinzdataAdapter` | `{"api_key": ...}`（也接受 `token`） | none；可切 framework 做 chunk |
| yfinance | `adapters.yfinance.YfinanceAdapter` | 无需凭证；可选 `{"session": ...}` | none；可切 framework 做 chunk |

注册与用法一致：

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

FinzData 直接映射官方 `finzdata.Client` 的方法名，也支持 yfinance 风格别名：

```python
from darwin_collector.adapters.finzdata import FinzdataAdapter
manager.register("finzdata", FinzdataAdapter)

result = manager.collect(CollectRequest(
    source="finzdata",
    method="prices",  # 或 "history" / "download" / "cot" / "minutes" / "gex" 等
    params={"symbol": "MSFT", "start": "2025-01-01", "end": "2025-01-31"},
    credentials={"api_key": "fz_..."},  # 库不读 FINZDATA_API_KEY
))
```

yfinance 无需 API key；`history` 与 `download` 直接映射官方 SDK：

```python
from darwin_collector.adapters.yfinance import YfinanceAdapter
manager.register("yfinance", YfinanceAdapter)

result = manager.collect(CollectRequest(
    source="yfinance",
    method="history",  # 或 "download" / "financials" / "info" / "dividends" 等
    params={"symbol": "MSFT", "start": "2025-01-01", "end": "2025-01-31"},
))
```

## 多 API key 与轮换

所有需要凭证的数据源（tushare / ftshare / tickflow / finzdata）共享库级的多 key 能力。凭证值中的逗号会自动拆分为多个 key，列表形式也支持：

```python
credentials={"token": "key1, key2, key3"}       # 自动拆成 3 个 key
credentials={"api_keys": ["k1", "k2"]}          # 等价
```

- 遇到**限流**或**认证失败**时自动轮换到下一个 key；失败的 key 进入冷却期，到期后重新可用（不会永久拉黑）。
- 轮换状态保存在适配器实例上，因此常驻 worker 跨多次 `collect()` 复用同一个池，冷却计时基于单调时钟，无需外部协调。
- 单 key 时保持原有行为（不内部轮换，交给框架重试层）。
- 可用 `KeyRotationPolicy` 定制，与其他策略一样通过 `Policies` 注入：

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

- `fake=True` 不会实例化 SDK，executor 直接返回空 DataFrame。
- 适配器的 `close()` 由宿主在退出时统一调用，实例可跨多次 `collect()` 复用；Baostock 的登录会话因此只建立一次。
- FinzData 的 `401` 映射认证错误、`429` 映射限流、`5xx` 映射网络错误；`403` 表示套餐不含该数据集，映射为数据错误且不触发重试。
- yfinance 无登录步骤；`YFRateLimitError` 映射限流，价格/数据缺失与无效参数映射数据错误，`ConnectionError` / timeout 映射网络错误；空 DataFrame 是正常结果而非异常。

## 文档

- [开发指南](docs/development-guide.md)
