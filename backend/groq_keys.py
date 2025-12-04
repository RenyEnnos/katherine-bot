import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEYS = [
    os.getenv("GROQ_API_KEY")
]
