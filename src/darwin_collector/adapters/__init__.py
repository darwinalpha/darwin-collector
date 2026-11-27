"""Data-source adapters.

All seven sources are implemented. Import a class directly from its subpackage:

    from darwin_collector.adapters.tushare import TushareAdapter
    from darwin_collector.adapters.ftshare import FtshareAdapter
    from darwin_collector.adapters.tickflow import TickflowAdapter
    from darwin_collector.adapters.baostock import BaostockAdapter
    from darwin_collector.adapters.ohlcvault import OhlcvaultAdapter
    from darwin_collector.adapters.finzdata import FinzdataAdapter
    from darwin_collector.adapters.yfinance import YfinanceAdapter
"""

from .base import BaseAdapter

__all__ = ["BaseAdapter"]
