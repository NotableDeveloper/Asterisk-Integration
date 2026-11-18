"""Create local development credentials without replacing an existing .env."""

from pathlib import Path
import os
import secrets


def main():
    path = Path(__file__).resolve().parents[1] / ".env"
    try:
        with open(path, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as file:
            file.write(f"ARI_PASSWORD={secrets.token_hex(24)}\n")
            file.write(f"SIP_PASSWORD={secrets.token_hex(24)}\n")
    except FileExistsError:
        print("Existing .env preserved.")
    else:
        print("Created .env with random local credentials (mode 0600).")


if __name__ == "__main__":
    main()
