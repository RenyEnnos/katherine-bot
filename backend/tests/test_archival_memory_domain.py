import pytest
import math
from backend.archival_memory import (
    parse_archival_extraction,
    ArchivalValidationError,
    compute_idempotency_key,
    ArchivalFact,
    ArchivalExtractionEnvelope
)

def test_valid_envelope():
    payload = {
        "facts": [
            {"content": "Likes hot coffee", "importance": 0.8, "tags": ["Coffee", "coffee", "likes_coffee"]}
        ],
        "schema_version": 1,
        "extractor_version": 1
    }
    env = parse_archival_extraction(payload)
    assert len(env.facts) == 1
    assert env.facts[0].content == "Likes hot coffee"
    assert env.facts[0].importance == 0.8
    # Normalized, unique, order-preserved tags: ["coffee", "likes_coffee"]
    assert env.facts[0].tags == ["coffee", "likes_coffee"]

def test_empty_facts_valid():
    payload = {
        "facts": [],
        "schema_version": 1,
        "extractor_version": 1
    }
    env = parse_archival_extraction(payload)
    assert len(env.facts) == 0

def test_reject_unknown_keys():
    payload = {
        "facts": [{"content": "x", "importance": 0.5, "tags": [], "extra_key": "bad"}],
        "schema_version": 1,
        "extractor_version": 1
    }
    with pytest.raises(ArchivalValidationError):
        parse_archival_extraction(payload)

def test_reject_bool_importance():
    payload = {
        "facts": [{"content": "x", "importance": True, "tags": []}],
        "schema_version": 1,
        "extractor_version": 1
    }
    with pytest.raises(ArchivalValidationError):
        parse_archival_extraction(payload)

def test_reject_invalid_importance_bounds():
    for imp in [-0.1, 1.1, math.nan, math.inf, None, "0.5"]:
        payload = {
            "facts": [{"content": "x", "importance": imp, "tags": []}],
            "schema_version": 1,
            "extractor_version": 1
        }
        with pytest.raises(ArchivalValidationError):
            parse_archival_extraction(payload)

def test_reject_invalid_tag_chars():
    payload = {
        "facts": [{"content": "x", "importance": 0.5, "tags": ["-tag", "tag!", ""]}],
        "schema_version": 1,
        "extractor_version": 1
    }
    with pytest.raises(ArchivalValidationError):
        parse_archival_extraction(payload)

def test_reject_fact_length_exceeded():
    payload = {
        "facts": [{"content": "a" * 501, "importance": 0.5, "tags": []}],
        "schema_version": 1,
        "extractor_version": 1
    }
    with pytest.raises(ArchivalValidationError):
        parse_archival_extraction(payload)

def test_reject_too_many_facts():
    payload = {
        "facts": [{"content": f"f{i}", "importance": 0.5, "tags": []} for i in range(6)],
        "schema_version": 1,
        "extractor_version": 1
    }
    with pytest.raises(ArchivalValidationError):
        parse_archival_extraction(payload)

def test_reject_too_many_tags():
    payload = {
        "facts": [{"content": "x", "importance": 0.5, "tags": [f"t{i}" for i in range(9)]}],
        "schema_version": 1,
        "extractor_version": 1
    }
    with pytest.raises(ArchivalValidationError):
        parse_archival_extraction(payload)

def test_reject_tag_too_long():
    payload = {
        "facts": [{"content": "x", "importance": 0.5, "tags": ["a" * 33]}],
        "schema_version": 1,
        "extractor_version": 1
    }
    with pytest.raises(ArchivalValidationError):
        parse_archival_extraction(payload)

def test_reject_wrong_versions():
    for v in [0, 2, "1"]:
        payload = {
            "facts": [],
            "schema_version": v,
            "extractor_version": 1
        }
        with pytest.raises(ArchivalValidationError):
            parse_archival_extraction(payload)

def test_compute_idempotency_key():
    key1 = compute_idempotency_key("user1", 123, 1)
    key2 = compute_idempotency_key("user1", 123, 1)
    key3 = compute_idempotency_key("user2", 123, 1)
    assert key1 == key2
    assert key1 != key3
    assert len(key1) == 64
