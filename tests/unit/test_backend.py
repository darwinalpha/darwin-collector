from darwin_collector import Backend, resolve_backend


def test_resolve_backend_is_direct_for_every_source():
    for source in ["tushare", "ftshare", "anything"]:
        assert resolve_backend(source) == Backend.DIRECT


def test_worker_backend_is_not_implemented():
    from darwin_collector import AdapterManager, CollectRequest

    m = AdapterManager()
    # No source registered -> direct path raises typed error before worker.
    with __import__("pytest").raises(Exception):
        m.collect(CollectRequest(source="nope", method="m"))
