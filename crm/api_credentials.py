"""Create per-channel credentials locally without printing secrets."""

import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path

from crm.service import CHANNELS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".secrets/crm-api-credentials.json"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    integrations = []
    for channel in CHANNELS:
        if channel == "Unassigned":
            continue
        token = secrets.token_urlsafe(48)
        integrations.append(
            {
                "name": channel,
                "channel": channel,
                "token": token,
                "sha256": hashlib.sha256(token.encode()).hexdigest(),
            }
        )
    output = {
        "integrations": integrations,
        "server_config": [{k: row[k] for k in ("name", "channel", "sha256")} for row in integrations],
    }
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(output, handle, indent=2)
    print(f"Credentials saved to {args.output}. Store privately; do not commit or share in chat.")


if __name__ == "__main__":
    main()
