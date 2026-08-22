import pytest
from pydantic import ValidationError

from app.schemas.llm import (
    AliasJudgeResult,
    BridgeEvidence,
    ExtractionResult,
    MergeJudgeResult,
    MergePair,
    MergePairSide,
    PendingMention,
    RelationshipType,
)


def test_extraction_result_valid():
    result = ExtractionResult.model_validate({
        "characters": [{"name": "贾宝玉"}, {"name": "林黛玉"}],
        "relationships": [
            {"source": "贾宝玉", "target": "林黛玉", "type": "love", "confidence": 0.95},
        ],
    })
    assert result.relationships[0].type == RelationshipType.love


def test_unknown_type_rejected():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({
            "characters": [],
            "relationships": [
                {"source": "贾宝玉", "target": "林黛玉", "type": "romantic", "confidence": 0.9},
            ],
        })


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({
            "characters": [],
            "relationships": [
                {"source": "a", "target": "b", "type": "love", "confidence": 1.5},
            ],
        })


def test_name_length_limits():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({
            "characters": [{"name": ""}],
            "relationships": [],
        })


def test_self_loop_dropped():
    result = ExtractionResult.model_validate({
        "characters": [{"name": "贾宝玉"}],
        "relationships": [
            {"source": "贾宝玉", "target": "贾宝玉", "type": "love", "confidence": 0.9},
        ],
    })
    assert result.relationships == []


import httpx
import pytest

from app.pipeline.chunker import Chunk
from app.pipeline.extractor import FailedBlock, extract_all, extract_one
from app.pipeline.llm_client import LLMClient
from app.schemas.llm import ExtractionResult

VALID_JSON = {
    "characters": [{"name": "贾宝玉"}, {"name": "林黛玉"}],
    "relationships": [
        {"source": "贾宝玉", "target": "林黛玉", "type": "love", "confidence": 0.9},
    ],
}


def make_chunk(chunk_id):
    return Chunk(chunk_id=chunk_id, chapter_id=1, chapter_title="第1章",
                 text="文本", start_offset=0, end_offset=2)


class FakeHttpClient:
    """模拟 httpx.Client：按队列依次返回预置响应。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.last_headers = None

    def post(self, url, json=None, headers=None):
        self.calls += 1
        self.last_headers = headers
        return self.responses.pop(0)


def fake_response(status_code, payload=None):
    class _Resp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    return _Resp(status_code, payload)


def make_client(responses):
    return LLMClient(base_url="http://fake", api_key="k", model="m",
                     http_client=FakeHttpClient(responses))


def test_extract_chunk_parses_valid_json():
    client = make_client([fake_response(200, {
        "choices": [{"message": {"content": '{"characters": [], "relationships": []}'}}],
    })])
    result = client.extract_chunk("任意文本")
    assert isinstance(result, ExtractionResult)


def test_extract_chunk_sends_bearer_auth_header():
    client = make_client([fake_response(200, {
        "choices": [{"message": {"content": '{"characters": [], "relationships": []}'}}],
    })])
    client.extract_chunk("任意文本")
    assert client._client.last_headers == {"Authorization": "Bearer k"}


def test_extract_chunk_malformed_json_is_validation_error():
    client = make_client([fake_response(200, {"choices": [{"message": {"content": "不是JSON"}}]})])
    with pytest.raises(Exception) as exc:
        client.extract_chunk("任意文本")
    assert "validation_error" in str(exc.value)


def test_retryable_error_retried_once_then_succeeds():
    client = make_client([
        fake_response(429),
        fake_response(200, {"choices": [{"message": {"content": '{"characters": [], "relationships": []}'}}]}),
    ])
    chunk = make_chunk(1)
    out = extract_one(client, chunk)
    assert isinstance(out, tuple)
    assert client._client.calls == 2


def test_retryable_error_fails_after_retries_exhausted():
    client = make_client([fake_response(500), fake_response(500)])
    chunk = make_chunk(1)
    out = extract_one(client, chunk)
    assert isinstance(out, FailedBlock)
    assert out.error == "http_500"


def test_validation_error_not_retried():
    client = make_client([fake_response(200, {"choices": [{"message": {"content": '{"bad": 1}'}}]})])
    chunk = make_chunk(1)
    out = extract_one(client, chunk)
    assert isinstance(out, FailedBlock)
    assert out.error == "validation_error"
    assert client._client.calls == 1


def test_extract_all_sorts_and_counts_and_callback():
    chunks = [make_chunk(2), make_chunk(1)]
    client = make_client([
        fake_response(200, {"choices": [{"message": {"content": '{"characters": [], "relationships": []}'}}]}),
        fake_response(200, {"choices": [{"message": {"content": '{"characters": [], "relationships": []}'}}]}),
    ])
    calls = []
    bundle = extract_all(client, chunks, concurrency=2, on_chunk_done=lambda: calls.append(1))
    assert [c.chunk_id for c, _ in bundle.results] == [1, 2]
    assert bundle.failed == []
    assert len(calls) == 2


def test_alias_judge_result_valid():
    r = AliasJudgeResult.model_validate({
        "resolutions": [
            {"mention": "二老", "resolves_to": "傩送"},
            {"mention": "大老", "resolves_to": None},
        ],
    })
    assert r.resolutions[0].resolves_to == "傩送"
    assert r.resolutions[1].resolves_to is None


def test_alias_judge_duplicate_mention_deduped():
    r = AliasJudgeResult.model_validate({
        "resolutions": [
            {"mention": "二老", "resolves_to": "傩送"},
            {"mention": "二老", "resolves_to": "大老"},
        ],
    })
    assert len(r.resolutions) == 1
    assert r.resolutions[0].resolves_to == "傩送"


def test_judge_aliases_parses_result():
    client = make_client([fake_response(200, {"choices": [{"message": {"content": (
        '{"resolutions": [{"mention": "二老", "resolves_to": "傩送"}]}'
    )}}]})])
    pending = [PendingMention.model_validate({
        "mention": "二老",
        "candidates": [{"canonical": "傩送", "matched_names": ["傩送", "二老"]}],
    })]
    result = client.judge_aliases("文本", pending)
    assert isinstance(result, AliasJudgeResult)
    assert result.resolutions[0].resolves_to == "傩送"


def test_judge_aliases_bad_json_is_validation_error():
    client = make_client([fake_response(200, {"choices": [{"message": {"content": "不是JSON"}}]})])
    with pytest.raises(Exception) as exc:
        client.judge_aliases("文本", [])
    assert "validation_error" in str(exc.value)


def test_judge_aliases_retryable_429():
    client = make_client([fake_response(429), fake_response(200, {"choices": [{"message": {"content": '{"resolutions": []}'}}]})])
    client.judge_aliases("文本", [])
    assert client._client.calls == 2


def test_judge_merges_parses_result():
    client = make_client([fake_response(200, {"choices": [{"message": {"content": (
        '{"merges": [{"a": "大儿子", "b": "大老", "merge": true, "confidence": 0.9}]}'
    )}}]})])
    pairs = [MergePair.model_validate({
        "a": {"canonical": "大儿子", "first_seen_chunk": 6, "mention_count": 2},
        "b": {"canonical": "大老", "first_seen_chunk": 9, "mention_count": 1},
    })]
    result = client.judge_merges(pairs)
    assert isinstance(result, MergeJudgeResult)
    assert result.merges[0].merge is True


def test_judge_merges_bad_json_is_validation_error():
    client = make_client([fake_response(200, {"choices": [{"message": {"content": "不是JSON"}}]})])
    with pytest.raises(Exception) as exc:
        client.judge_merges([])
    assert "validation_error" in str(exc.value)


def test_judge_merges_retryable_429():
    client = make_client([fake_response(429), fake_response(200, {"choices": [{"message": {"content": '{"merges": []}'}}]})])
    client.judge_merges([])
    assert client._client.calls == 2
