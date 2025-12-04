import requests
import json

try:
    response = requests.post(
        "http://localhost:8000/chat",
        json={"user_id": "debug_user_3", "message": "Ola"},
        headers={"Content-Type": "application/json"}
    )
    print(f"Status Code: {response.status_code}")
    print("Response Body:")
    print(response.text)
except Exception as e:
    print(f"Error: {e}")
