"""Offline unit tests for MemoryManager configuration/sanitization.

These tests run in the regular backend CI (no Supabase, no Docker, no network).
They monkeypatch create_client and SentenceTransformer so no real embeddings
are initialized.
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixture: patch heavy modules before any import of backend.memory
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_heavy_modules():
    """Patch sentence_transformers and supabase.create_client before each test."""
    with patch.dict(sys.modules):
        sys.modules["sentence_transformers"] = MagicMock()
        sys.modules["supabase"] = MagicMock()
        yield


def _import_memory_manager():
    """Import and return MemoryManager after patching dependencies."""
    from backend.memory import MemoryManager, StateLoadError, StatePersistenceError
    return MemoryManager, StateLoadError, StatePersistenceError


# ---------------------------------------------------------------------------
# Case 1: Only legacy key (SUPABASE_KEY), no SERVICE_ROLE_KEY
# ---------------------------------------------------------------------------

def test_legacy_key_only(monkeypatch, caplog):
    """With only SUPABASE_URL + SUPABASE_KEY (legacy), MemoryManager must
    fail closed: supabase is None, persistence raises domain exception,
    and the legacy key does not appear in logs."""
    monkeypatch.setenv("SUPABASE_URL", "http://test-legacy.example.com")
    monkeypatch.setenv("SUPABASE_KEY", "legacy_key_eyJ_test_value")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    MemoryManager, StateLoadError, _ = _import_memory_manager()

    mm = MemoryManager()
    assert mm.supabase is None, "supabase should be None without SERVICE_ROLE_KEY"

    with pytest.raises(StateLoadError) as exc:
        mm.load_user_state("test_user")
    assert "indisponível" in str(exc.value).lower() or "Falha" in str(exc.value)

    # Legacy key must NOT appear in logs or exception
    assert "legacy_key_eyJ_test_value" not in caplog.text
    assert "eyJ" not in caplog.text
    assert "legacy_key" not in str(exc.value)


# ---------------------------------------------------------------------------
# Case 2: Valid service role key
# ---------------------------------------------------------------------------

def test_service_role_key_valid(monkeypatch, caplog):
    """With SERVICE_ROLE_KEY set, create_client must be called once with
    the correct URL and key. SUPABASE_KEY must NOT be used as fallback."""
    monkeypatch.setenv("SUPABASE_URL", "http://test-sr.example.com")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sr_key_valid_test_value")
    monkeypatch.delenv("SUPABASE_KEY", raising=False)

    sentinel = MagicMock()
    sentinel.table.return_value = sentinel
    sentinel.select.return_value = sentinel
    sentinel.eq.return_value = sentinel
    sentinel.execute.return_value = MagicMock(data=[])

    import backend.memory as mem_mod
    original_create = mem_mod.create_client

    try:
        mem_mod.create_client = MagicMock(return_value=sentinel)

        MemoryManager, _, _ = _import_memory_manager()
        mm = MemoryManager()

        assert mm.supabase is not None
        mem_mod.create_client.assert_called_once()
        call_args = mem_mod.create_client.call_args
        assert call_args[0][0] == "http://test-sr.example.com"
        assert call_args[0][1] == "sr_key_valid_test_value"

        # Key must NOT appear in logs
        assert "sr_key_valid_test_value" not in caplog.text
        assert "SUPABASE_KEY" not in caplog.text or "not used" in caplog.text
    finally:
        mem_mod.create_client = original_create


# ---------------------------------------------------------------------------
# Case 3: Upstream exception containing sensitive markers
# ---------------------------------------------------------------------------

SENSITIVE_MARKERS = [
    "SENSITIVE_JWT_eyJ_test",
    "SENSITIVE_PAYLOAD",
    "SELECT secret_value FROM users",
    "INSERT private_data INTO logs",
    "SENSITIVE_SERVICE_KEY",
]


def _create_exception_with_markers():
    """Create an exception whose string representation contains all markers."""
    msg = " | ".join(SENSITIVE_MARKERS)
    return RuntimeError(msg)


def test_sensitive_exception_sanitized(monkeypatch, caplog):
    """When create_client raises an exception with sensitive content,
    the markers must NOT leak into caplog or into public exception messages
    produced by MemoryManager methods."""
    monkeypatch.setenv("SUPABASE_URL", "http://test-sensitive.example.com")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sr_key_sensitive")

    import backend.memory as mem_mod
    original_create = mem_mod.create_client

    try:
        mem_mod.create_client = MagicMock(
            side_effect=_create_exception_with_markers()
        )

        MemoryManager, StateLoadError, StatePersistenceError = _import_memory_manager()
        mm = MemoryManager()

        # Supabase should be None after construction failure
        assert mm.supabase is None, "supabase should be None on create_client failure"

        # No markers in logs
        for marker in SENSITIVE_MARKERS:
            assert marker not in caplog.text, (
                f"Sensitive marker leaked into logs: {marker}"
            )

        # Public exceptions must not contain markers
        with pytest.raises(StateLoadError) as exc:
            mm.load_user_state("test_user")
        msg = str(exc.value)
        for marker in SENSITIVE_MARKERS:
            assert marker not in msg, (
                f"Sensitive marker leaked into public exception: {marker}"
            )

        # The public message should be constant
        assert "indisponível" in msg.lower() or "Falha" in msg

        # Also test sync_state for sanitization
        from backend.emotion_presentation import EmotionStateResponse
        from backend.relationship import RelationshipStateV1
        with pytest.raises(StatePersistenceError) as exc2:
            from backend.emotional_domain import EmotionalStateV1
            mm.sync_state(
                "test_user",
                EmotionalStateV1.neutral(timestamp=1000.0),
                RelationshipStateV1.neutral(timestamp=1000.0),
            )
        msg2 = str(exc2.value)
        for marker in SENSITIVE_MARKERS:
            assert marker not in msg2, (
                f"Sensitive marker leaked into sync_state exception: {marker}"
            )
        assert "não configurado" in msg2.lower() or "indisponível" in msg2.lower()

    finally:
        mem_mod.create_client = original_create
