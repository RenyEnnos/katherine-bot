import pytest
from unittest.mock import patch
from backend.emotional_core import AffectiveEngine

def test_save_state_error_handling(capsys):
    engine = AffectiveEngine()

    with patch("builtins.open", side_effect=IOError("Mocked IO Error")):
        engine.save_state("dummy.json")

    captured = capsys.readouterr()
    assert "Error saving emotional state: Mocked IO Error" in captured.out
