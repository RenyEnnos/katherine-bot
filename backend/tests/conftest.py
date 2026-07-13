import os

# Force mock placeholders for tests to prevent real environment keys from being used
os.environ["GROQ_API_KEY"] = "mock_groq_key_placeholder"
os.environ["GROQ_API_KEY_2"] = "mock_groq_key_2_placeholder"
