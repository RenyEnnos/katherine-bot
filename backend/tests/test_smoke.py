import sys
import os
from unittest.mock import MagicMock

def test_imports():
    _original_modules = dict(sys.modules)
    _original_env = dict(os.environ)

    try:
        # Mock network-dependent/heavy modules
        sys.modules['sentence_transformers'] = MagicMock()
        sys.modules['supabase'] = MagicMock()

        # Mock environment variables
        os.environ['GROQ_API_KEY'] = 'mock'
        os.environ['SUPABASE_URL'] = 'mock'
        os.environ['SUPABASE_KEY'] = 'mock'

        # Attempt to import main
        import backend.main

        assert backend.main.app is not None
    finally:
        modules_to_remove = [k for k in sys.modules if k not in _original_modules]
        for k in modules_to_remove:
            del sys.modules[k]

        os.environ.clear()
        os.environ.update(_original_env)
