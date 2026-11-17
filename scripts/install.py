#!/usr/bin/env python3
"""Back-compat shim: the flag-only installer now lives in the zoho_skills package (`zoho-skills install`)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from zoho_skills.legacy_install import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
