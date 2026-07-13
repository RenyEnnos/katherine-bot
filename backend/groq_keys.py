import os
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

def get_groq_api_keys():
    return [os.getenv("GROQ_API_KEY"), os.getenv("GROQ_API_KEY_2")]
