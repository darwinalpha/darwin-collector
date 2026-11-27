"""Minimal collection example (no config file, no writer)."""

from darwin_collector import AdapterManager, CollectRequest


def main() -> None:
    manager = AdapterManager()

    # In a real app the source/method/credentials come from your own config.
    # from darwin_collector.adapters.tushare import TushareAdapter
    # manager.register("tushare", TushareAdapter)

    # request = CollectRequest(
    #     source="tushare",
    #     method="daily",
    #     params={"ts_code": "000001.SZ", "start_date": "20240101", "end_date": "20240131"},
    #     credentials={"token": "<your token>"},
    # )
    # df = manager.collect(request).to_dataframe()
    # print(df.head())

    # FinzData example: key comes from the caller, not from the environment.
    # from darwin_collector.adapters.finzdata import FinzdataAdapter
    # manager.register("finzdata", FinzdataAdapter)
    # result = manager.collect(CollectRequest(
    #     source="finzdata",
    #     method="prices",
    #     params={"symbol": "MSFT", "start": "2025-01-01", "end": "2025-01-31"},
    #     credentials={"api_key": "<your key>"},
    # ))
    # print(result.to_dataframe().head())

    # yfinance example: no credentials required.
    # from darwin_collector.adapters.yfinance import YfinanceAdapter
    # manager.register("yfinance", YfinanceAdapter)
    # result = manager.collect(CollectRequest(
    #     source="yfinance",
    #     method="history",
    #     params={"symbol": "MSFT", "start": "2025-01-01", "end": "2025-01-31"},
    # ))
    # print(result.to_dataframe().head())

    print("Register a source and build a CollectRequest to start collecting.")
    manager.close()


if __name__ == "__main__":
    main()
