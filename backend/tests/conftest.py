import os

# Set default mock environment variables for the test suite before imports happen
os.environ.setdefault("GROQ_API_KEY", "mock_groq_key")
