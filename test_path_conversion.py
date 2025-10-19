#!/usr/bin/env python3
"""
Quick test for Windows to WSL path conversion logic.
"""

def convert_windows_to_wsl_path(path_str: str) -> str:
    """Convert Windows path to WSL format."""
    if path_str.startswith("\\\\wsl"):
        # Already a WSL path: \\wsl.localhost\Ubuntu\home\user\...
        # Convert to /home/user/...
        if "\\wsl.localhost\\Ubuntu\\" in path_str:
            # Remove the \\wsl.localhost\Ubuntu\ prefix completely
            wsl_part = path_str.replace("\\wsl.localhost\\Ubuntu\\", "")
            # Convert backslashes and ensure single leading slash
            return "/" + wsl_part.replace("\\", "/").lstrip("/")
        else:
            return path_str.replace("\\", "/")
    else:
        # Windows path: C:\Users\... → /mnt/c/Users/...
        # Convert drive letter and backslashes
        if len(path_str) >= 2 and path_str[1] == ':':
            drive = path_str[0].lower()
            rest = path_str[2:].replace("\\", "/")
            return f"/mnt/{drive}{rest}"
        else:
            return path_str.replace("\\", "/")


# Test cases
test_cases = [
    ("C:\\Users\\v_ale\\PGVectorRAGIndexer", "/mnt/c/Users/v_ale/PGVectorRAGIndexer"),
    ("D:\\Projects\\MyApp", "/mnt/d/Projects/MyApp"),
    ("\\\\wsl.localhost\\Ubuntu\\home\\valginer0\\projects\\PGVectorRAGIndexer", 
     "/home/valginer0/projects/PGVectorRAGIndexer"),
]

print("Testing Windows to WSL path conversion:")
print("=" * 70)

all_passed = True
for windows_path, expected_wsl in test_cases:
    result = convert_windows_to_wsl_path(windows_path)
    passed = result == expected_wsl
    all_passed = all_passed and passed
    
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"\n{status}")
    print(f"  Input:    {windows_path}")
    print(f"  Expected: {expected_wsl}")
    print(f"  Got:      {result}")

print("\n" + "=" * 70)
if all_passed:
    print("✓ All tests passed!")
else:
    print("✗ Some tests failed!")

exit(0 if all_passed else 1)
