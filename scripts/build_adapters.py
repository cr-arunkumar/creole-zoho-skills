#!/usr/bin/env python3
"""Regenerate (or --check) the committed in-repo adapters from skills/ and packs/. See zoho_skills.build_adapters."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from zoho_skills.build_adapters import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
