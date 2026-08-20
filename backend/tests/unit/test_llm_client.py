import pytest
from pydantic import ValidationError

from app.schemas.llm import ExtractionResult, RelationshipType


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
