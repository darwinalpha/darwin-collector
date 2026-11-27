from darwin_collector import CollectRequest, CollectResult
import pandas as pd


def test_result_dataframe_and_records_views():
    frame = pd.DataFrame({"a": [1, 2]})
    result = CollectResult(source="x", method="m", frames=[frame], attempts=2)

    assert result.to_dataframe().equals(frame)
    assert result.to_records() == [{"a": 1}, {"a": 2}]
    assert result.row_count == 2
    assert result.chunk_count == 1


def test_result_merges_chunks():
    r = CollectResult(
        source="x",
        method="m",
        frames=[pd.DataFrame({"a": [1]}), pd.DataFrame({"a": [2]})],
    )
    assert r.to_dataframe()["a"].tolist() == [1, 2]
    assert r.chunk_count == 2


def test_empty_result():
    r = CollectResult(source="x", method="m")
    assert r.to_dataframe().empty
    assert r.to_records() == []


def test_request_defaults():
    req = CollectRequest(source="x", method="m")
    assert req.params == {}
    assert req.options == {}
    assert req.fake is False
    assert req.credentials is None
