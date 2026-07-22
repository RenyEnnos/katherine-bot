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
        os.environ['SUPABASE_SERVICE_ROLE_KEY'] = 'mock'

        # Attempt to import main
        import backend.main

        assert backend.main.app is not None
    finally:
        # Restore environment and modules directionally
        if 'backend.main' in sys.modules:
            del sys.modules['backend.main']
        if 'sentence_transformers' in sys.modules:
            del sys.modules['sentence_transformers']
        if 'supabase' in sys.modules:
            del sys.modules['supabase']

        # Restore what was actually added during the test
        for k in list(sys.modules.keys()):
            if k.startswith('backend.'):
                del sys.modules[k]

        os.environ.clear()
        os.environ.update(_original_env)
