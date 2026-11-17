"""User config at ~/.zoho-skills/config.json (chmod 600). The Zoho MCP URL embeds a credential, so it lives only here —
never in harness configs or repos — and is redacted from every message we print."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from . import mcp_config


def config_dir() -> Path:
    return Path(os.environ.get("ZOHO_SKILLS_HOME") or Path.home() / ".zoho-skills")


def config_path() -> Path:
    return config_dir() / "config.json"


def load() -> dict:
    p = config_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict) -> Path:
    """Atomic write with owner-only permissions (the file holds a credential)."""
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    fd, tmp = tempfile.mkstemp(dir=str(d), prefix=".config-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, config_path())
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return config_path()


def update(**changes) -> dict:
    data = load()
    data.update({k: v for k, v in changes.items() if v is not None})
    save(data)
    return data


def get_url() -> Optional[str]:
    return os.environ.get("ZOHO_SKILLS_URL") or load().get("url") or None


def region() -> str:
    return load().get("region") or mcp_config.DEFAULT_REGION


def readonly() -> bool:
    if os.environ.get("ZOHO_SKILLS_READONLY") in ("1", "true", "yes"):
        return True
    return bool(load().get("readonly"))


def host_matches_region(url: str, region_key: str) -> bool:
    """Warn-level check: a *.zoho.in console should pair with an .in endpoint (hosts embed the data centre)."""
    host = (urlparse(url).hostname or "").lower()
    if "zoho" not in host:
        return True  # custom/proxy host: can't tell
    suffix = "zoho." + region_key
    return host.endswith(suffix) or host.endswith("zohomcp." + region_key)


def redact(text: str) -> str:
    """Remove the configured URL and any key-looking query values from text destined for output."""
    url = get_url()
    if url:
        text = text.replace(url, mcp_config.mask_url(url))
    text = re.sub(r"/[0-9a-fA-F]{24,}(?=[/?\s\"']|$)", "/***", text)  # key embedded in the URL path
    return re.sub(r"([?&](?:key|token|apikey|api_key|access_token)=)[^&\s\"']+", r"\1***", text, flags=re.I)
