#!/usr/bin/env python3
"""
License key generator for PGVectorRAGIndexer.

Generates signed JWT license keys for Team edition.
Used for manual sales and Stripe webhook integration.

Usage:
    python generate_license_key.py \\
        --secret "your-hmac-secret" \\
        --edition team \\
        --org "Acme Corp" \\
        --seats 10 \\
        --days 90

    # Or use environment variable for secret
    export LICENSE_SIGNING_SECRET="your-hmac-secret"
    python generate_license_key.py --org "Acme Corp" --seats 10 --days 90
"""

import argparse
import json
import os
import sys
import time
import uuid

try:
    import jwt  # PyJWT
except ImportError:
    print("ERROR: PyJWT is required. Install with: pip install PyJWT", file=sys.stderr)
    sys.exit(1)


def generate_license_key(
    signing_secret: str,
    edition: str = "team",
    org_name: str = "",
    seats: int = 1,
    days: int = 90,
    algorithm: str = "HS256",
) -> str:
    """Generate a signed JWT license key.

    Args:
        signing_secret: HMAC-SHA256 signing secret (for HS256) or private key (for RS256).
        edition: Edition string ("team" or "community").
        org_name: Organization name.
        seats: Number of licensed seats.
        days: Days until expiry.
        algorithm: JWT signing algorithm ("HS256" or "RS256").

    Returns:
        Encoded JWT string.
    """
    now = time.time()
    payload = {
        "edition": edition,
        "org": org_name,
        "seats": seats,
        "iat": int(now),
        "exp": int(now + (days * 86400)),
        "jti": str(uuid.uuid4()),
    }

    return jwt.encode(payload, signing_secret, algorithm=algorithm)


def main():
    parser = argparse.ArgumentParser(
        description="Generate PGVectorRAGIndexer license keys",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate a 90-day Team license for 10 seats
  python generate_license_key.py --secret "mysecret" --org "Acme Corp" --seats 10

  # Generate a 1-year license
  python generate_license_key.py --secret "mysecret" --org "Acme Corp" --days 365

  # Use environment variable for secret
  export LICENSE_SIGNING_SECRET="mysecret"
  python generate_license_key.py --org "Acme Corp" --seats 5

  # Output as JSON (includes metadata)
  python generate_license_key.py --secret "mysecret" --org "Acme Corp" --json
        """,
    )

    parser.add_argument(
        "--secret",
        default=os.environ.get("LICENSE_SIGNING_SECRET", ""),
        help="HMAC-SHA256 signing secret or private key for RS256 (or set LICENSE_SIGNING_SECRET env var)",
    )
    parser.add_argument(
        "--edition",
        default="team",
        choices=["team", "community"],
        help="License edition (default: team)",
    )
    parser.add_argument(
        "--org",
        required=True,
        help="Organization name",
    )
    parser.add_argument(
        "--seats",
        type=int,
        default=1,
        help="Number of licensed seats (default: 1)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Days until expiry (default: 90)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output as JSON with metadata",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Write key to file instead of stdout",
    )
    parser.add_argument(
        "--algorithm",
        default="HS256",
        choices=["HS256", "RS256"],
        help="JWT signing algorithm (default: HS256)",
    )

    args = parser.parse_args()

    secret = args.secret
    if args.algorithm == "RS256" and not secret:
        # Try to read from private_key.pem if it exists and secret is not set
        if os.path.exists("private_key.pem"):
            with open("private_key.pem", "r") as f:
                secret = f.read()
            print("Using private_key.pem for RS256 signing", file=sys.stderr)

    if not secret:
        print(
            "ERROR: No signing secret provided. Use --secret or set "
            "LICENSE_SIGNING_SECRET environment variable. "
            "For RS256, you can also place 'private_key.pem' in the current directory.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Generate the key
    token = generate_license_key(
        signing_secret=secret,
        edition=args.edition,
        org_name=args.org,
        seats=args.seats,
        days=args.days,
        algorithm=args.algorithm,
    )

    if args.output_json:
        # Decode to show metadata
        # For RS256, decoding requires the public key. If secret is a private key,
        # we can't decode with it directly. For simplicity, we'll assume the secret
        # provided is sufficient for decoding if it's HS256, or if it's a public key
        # for RS256 (which is not how we generate it).
        # A more robust solution would require a separate public key argument for decoding.
        # For now, we'll just use the provided secret for decoding, which works for HS256
        # and if the secret happens to be the public key for RS256.
        # If the secret is a private key for RS256, this decode will fail unless
        # the public key is also provided or inferred.
        try:
            payload = jwt.decode(token, secret, algorithms=[args.algorithm])
        except Exception as e:
            print(f"Warning: Could not decode token for JSON output: {e}", file=sys.stderr)
            payload = {"error": "Could not decode token with provided secret/key for display."}

        output = {
            "token": token,
            "payload": payload,
            "instructions": {
                "linux_macos": f"mkdir -p ~/.pgvector-license && echo '{token}' > ~/.pgvector-license/license.key && chmod 600 ~/.pgvector-license/license.key",
                "windows": f"Save the token to %APPDATA%\\PGVectorRAGIndexer\\license.key",
            },
        }
        result = json.dumps(output, indent=2, default=str)
    else:
        result = token

    if args.output:
        with open(args.output, "w") as f:
            f.write(result + "\n")
        print(f"License key written to {args.output}", file=sys.stderr)
    else:
        print(result)


if __name__ == "__main__":
    main()
