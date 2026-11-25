"""Create a GeoSpectrum activation file on an offline signing workstation."""
from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.modules.activation import ActivationClaims, encode_signed_activation  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--prompt-key-password", action="store_true", help="read an encrypted PEM password interactively")
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--expires-at", required=True, help="ISO 8601 with time zone, e.g. 2027-01-01T00:00:00+08:00")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        expires_at = datetime.fromisoformat(args.expires_at)
        claims = ActivationClaims(installation_id=args.installation_id, expires_at=expires_at)
        if expires_at <= datetime.now(timezone.utc):
            raise ValueError("expiry must be in the future")
        password = getpass.getpass("PEM password: ").encode("utf-8") if args.prompt_key_password else None
        key = serialization.load_pem_private_key(args.private_key.read_bytes(), password=password)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("expected an Ed25519 private key")
        content = encode_signed_activation(claims, key.sign)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(content)
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
