import os
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

def __getattr__(name: str):
    if name == "GROQ_API_KEYS":
        return [
            os.getenv("GROQ_API_KEY"),
            os.getenv("GROQ_API_KEY_2")
        ]
    raise AttributeError(f"module {__name__} has no attribute {name}")
