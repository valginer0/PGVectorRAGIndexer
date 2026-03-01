import requests
import json

BASE_URL = "http://localhost:8001"

def test_error_responses():
    print("Testing Error Registry Responses...")
    
    # 1. Test Auth Error: Missing API Key (AUTH_2001)
    print("\n[1] Testing 401 - Unauthorized (Missing API Key)...")
    # /api/v1/search requires an API key and must be POST
    resp = requests.post(f"{BASE_URL}/api/v1/search", json={"query": "test"})
    print(f"Status: {resp.status_code}")
    try:
        data = resp.json()
        print(f"Response: {json.dumps(data, indent=2)}")
        if data.get("error_code") == "AUTH_2001":
            print("SUCCESS: Received AUTH_2001")
        else:
            print(f"FAILED: Expected error_code AUTH_2001, got {data.get('error_code')}")
    except Exception as e:
        print(f"FAILED: Could not parse JSON: {e}")
    
    print("\nVerification Complete.")

if __name__ == "__main__":
    # Ensure server is running before running this
    # uvicorn api:app --port 8000
    try:
        test_error_responses()
    except Exception as e:
        print(f"Search failed (server might be down): {e}")
