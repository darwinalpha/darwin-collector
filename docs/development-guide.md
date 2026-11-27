# darwin-collector 开发指南

## 定位

`darwin-collector` 只做采集：注册适配器 → 初始化/登录 → 调用 SDK → 施加策略 → 返回 `CollectResult`。它不读配置、不写文件、不清洗数据、不做跨源路由。

## 一次采集的执行链

```
AdapterManager.collect(request)
  → resolve_backend(source)          # 当前恒为 direct，worker 分支预埋
  → get_adapter(source)              # 注册表查表，实例可复用
  → Executor.execute(adapter, request)
      → adapter.ensure_ready(credentials)
      → 选 Paginator（按 pagination_mode）
      → call_once = retry(RateLimit(adapter.collect_once))
      → paginate(...) 或单次调用
      → CollectResult
```

## 新增一个数据源

1. 在 `src/darwin_collector/adapters/<source>/` 建 `adapter.py` 和 `__init__.py`；
2. 继承 `BaseAdapter`，实现 `get_source_name()` 和 `collect_once(method, **kwargs)`；
3. 在 `ensure_ready(credentials)` 里用**传入的**凭证初始化 SDK，禁止读环境变量或配置；
4. 声明 `pagination_mode`：
   - `NONE`：单次调用；
   - `FRAMEWORK`：`collect_once` 只拿一页，由 Paginator 翻页（tushare 属于此类）；
   - `ADAPTER`：SDK 已返回完整结果，框架不翻页；
   - 若数据源需要 API key，声明 `key_fields = ("token",)` 之类的字段名（按优先级排列）；
5. 把 SDK 异常映射成 `AdapterAuthError` / `AdapterRateLimitError` / `AdapterNetworkError` / `AdapterDataError`；
6. 写行为锁定测试（fake 模式），放 `tests/unit/adapters/test_<source>.py`；
7. 调用方通过 `manager.register("source", SourceAdapter)` 注册。

## 策略注入

调用方在 `CollectRequest.policies` 传入 `Policies(retry=..., rate_limit=..., paginator=..., pagination_mode=...)`。不传则用 `defaults.py` 的库默认常量。库不读取任何全局配置。

- `RetryPolicy`：只对限流/网络异常重试；认证失败先 `reauth()` 一次，仍失败抛 `AdapterAuthError`。
- `RateLimitPolicy`：`before_call()` 控制调用间隔，`on_rate_limit()` 控制冷却；当前 Executor 使用 `before_call`，冷却由重试等待承担。
- `KeyRotationPolicy`：控制多 key 轮换——`cooldown_seconds` / `auth_cooldown_seconds` 分别设定限流与认证失败的冷却时长，`max_rotations` 限制单次调用的轮换次数，`rotate_on_auth` / `rotate_on_rate_limit` 控制两类错误是否触发轮换。
- `Paginator`：`framework` 模式按 options 触发键选择策略，按检查顺序：
  - `max_lines`：反向日期分页（tushare）；
  - `chunk_months`：按自然月切片，替换 `since_ts_millis` / `until_ts_millis`（ftshare 可选）；
  - `chunk_ms`：按天切毫秒时间戳，替换 `start_time` / `end_time`（tickflow）；
  - `paginate`：正向翻页，替换 `page`；
  - `chunk_days`：按天切片，替换 `start_date` / `end_date`。

  所有切片策略都有 `max_iterations` / `max_pages` 上限，并在连续 `max_empty_chunks` 个空片后停止。间隔由 `RateLimitPolicy` 负责，Paginator 自身不 sleep。

## 多 API key 轮换

轮换是库级能力，不在任何适配器内单独实现。需要 key 的适配器只需：

1. 声明 `key_fields`（凭证字典中存放 key 的字段，按优先级）；
2. 在 `ensure_ready()` 中调用 `self._init_key_pool(credentials)`，空池时抛 `AdapterAuthError`，非空时 `self._warm_client(factory)` 预热第一个 client；
3. 把单次 SDK 调用写成 `def invoke(key): ...` 闭包，用 `self._cached_client(key, factory)` 取该 key 对应的 client，最后 `return self._run_with_keys(invoke)`；
4. `reauth()` / `close()` 调用 `self._reset_key_state()` 清空 client 缓存与冷却状态。

库的行为：

- 凭证值含逗号（字符串或列表元素）时自动拆成多个 key；
- 限流与认证失败都轮换到下一个 key，失败的 key 进入冷却，到期自动恢复；
- 单 key 时不内部轮换，保持旧行为交给框架重试层；
- 轮换状态保存在适配器实例上，常驻 worker 跨 `collect()` 复用时冷却状态延续，无需共享存储；
- 通过 `Policies(key_rotation=...)` 注入自定义策略；`Executor.execute()` 在 `ensure_ready()` 前调用 `adapter.configure(policies)` 完成注入。

## 会话与 worker

adapter 实例由 `AdapterManager` 缓存，可跨多次 `collect` 复用，`close()` 由宿主在退出时调用。`resolve_backend(source)` 是唯一的后端选择点，当前恒为 `direct`；worker 实现时只需在这里切换，调用方与适配器无需改动。

有会话的源按以下约定实现，保证 worker 复用时不会每次登录：

- `ensure_ready()`：幂等初始化；baostock 在此 `login()`，ohlcvault 在此 `connect()`；
- `close()`：宿主退出时 `logout()` / 释放连接；
- `reauth()`：认证失败后重建会话（baostock 重新 login，ftshare/tickflow/finzdata/yfinance 重建 SDK 引用或 client，tushare 重设 token）；带 key 的适配器同时清空 client 缓存与冷却状态。

## FinzData 方法映射

FinzData 只需 API key，没有 login 往返；`ensure_ready()` 用传入的 `api_key`（或 `token`）构造 `finzdata.Client`，不读 `FINZDATA_API_KEY`。

支持的方法分三类：

- `Client` 数据集方法：直接按原名调用，例如 `prices` / `minutes` / `cot` / `futures` / `macro` / `gex` / `fundamentals` / `valuation` / `datasets` / `me`。完整白名单见 `adapters/finzdata/adapter.py`；
- yfinance 风格别名：`history` / `ticker_history` → `Ticker(symbol).history()`，`download` → `finzdata.download()`；
- `Ticker` 辅助属性：`ticker.info` / `ticker.actions` / `ticker.facts` / `ticker.dividends` / `ticker.splits`。

两个约定：

1. `start_date` / `end_date` 和 `since_ts_millis` / `until_ts_millis` 会转换成 SDK 的 `start` / `end`，所以可选的 `FRAMEWORK` 分块策略可以直接复用现有 Paginator；
2. `FinzError.status` 按语义分类：`401` → 认证（标记不可用），`403` → 套餐无权访问（数据错误，不重试），`429` → 限流，`5xx` → 网络错误。`403` 不当作认证失败，因为同一 key 仍可能访问其他数据集。

## yfinance 方法映射

yfinance 没有 API key 或 login 往返；`ensure_ready()` 只导入 SDK，并保留调用方可选传入的 `session`（通过 `credentials={"session": ...}`）。库不读任何环境变量。

支持的方法分三类：

- `download` → `yf.download()`，`tickers` / `symbols` / `symbol` 都可作为代码参数；
- `history` / `ticker_history` → `Ticker(symbol).history()`；
- Ticker 方法与属性白名单：`info` / `fast_info` / `financials` / `income_stmt` / `balance_sheet` / `cash_flow` / `earnings` / `earnings_dates` / `actions` / `dividends` / `splits` / `recommendations` / `institutional_holders` / `option_chain` / `news` 等；`ticker.<name>`、`<name>` 和 `get_<name>` 三种写法都接受。

两个约定：

1. `start_date` / `end_date` 和 `since_ts_millis` / `until_ts_millis` 会转换成 `start` / `end`，所以可选的 `FRAMEWORK` 分块策略可以复用现有 Paginator；反向日期分页如按索引列判断，需要调用方传入 `options={"date_field": "Date"}`。
2. `YFRateLimitError` → 限流；`YFPricesMissingError` / `YFTickerMissingError` / `YFInvalidPeriodError` / `YFDataException` → 数据错误；`ConnectionError` / timeout / DNS 类错误 → 网络错误。**空 DataFrame 是正常结果**，不抛异常。

## 禁止事项

- 不要 import `darwin_config` / `darwin_logger` / writer / cleaner / loader；
- 不要读取 `adapter.json` / `adapter_clean.json` / `mapping.json`；
- 不要在库内实现去重、落盘或跨源故障切换。
