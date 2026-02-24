import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.abspath("."))

# Ensure environment variable is NOT set
if "LICENSE_SIGNING_SECRET" in os.environ:
    del os.environ["LICENSE_SIGNING_SECRET"]

import license

def test_rs256_validation():
    # Path to the generated test key
    key_path = Path("test_rsa_license.key")
    
    if not key_path.exists():
        print("Error: test_rsa_license.key not found")
        return

    print(f"Testing validation for {key_path}...")
    
    # Load the license using the mocked path
    # This should use the embedded PUBLIC_KEY_DEFAULT and RS156
    info = license.load_license(key_path=key_path)
    
    print(f"Edition: {info.edition}")
    print(f"Org: {info.org_name}")
    print(f"Seats: {info.seats}")
    print(f"Is Team: {info.is_team}")
    print(f"Warning: {info.warning}")
    
    if info.is_team and info.org_name == "RSA Test Org":
        print("\nSUCCESS: RSA license validated without environment variables!")
    else:
        print("\nFAILURE: RSA license validation failed.")

if __name__ == "__main__":
    test_rs256_validation()
