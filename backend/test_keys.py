import os
from groq import Groq, APIError
from backend.groq_keys import GROQ_API_KEYS

def test_keys():
    print("Testing Groq API Keys...\n")
    valid_keys = []
    
    for key in GROQ_API_KEYS:
        client = Groq(api_key=key)
        try:
            client.chat.completions.create(
                messages=[{"role": "user", "content": "hi"}],
                model="llama-3.1-8b-instant",
                max_tokens=1
            )
            print(f"[VALID] {key[:10]}...")
            valid_keys.append(key)
        except APIError as e:
            print(f"[INVALID] {key[:10]}... -> {e.message}")
        except Exception as e:
            print(f"[ERROR] {key[:10]}... -> {str(e)}")
            
    print(f"\nSummary: {len(valid_keys)}/{len(GROQ_API_KEYS)} keys are valid.")
    
    if valid_keys:
        print("\nValid Keys:")
        for k in valid_keys:
            print(k)

if __name__ == "__main__":
    test_keys()
