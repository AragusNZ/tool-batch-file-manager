"""Ask GitHub for the newest release. Stdlib only; nothing about the user's files is sent."""

import json
import re
from urllib.request import Request, urlopen

from batch_file_manager import __version__

RELEASES_API = "https://api.github.com/repos/AragusNZ/tool-batch-file-manager/releases/latest"
RELEASES_URL = "https://github.com/AragusNZ/tool-batch-file-manager/releases/latest"


def latest_version(timeout: float = 5.0) -> str:
    """Tag of the latest release, without the leading ``v``. Raises on any network or API error."""
    # GitHub rejects requests without a User-Agent.
    req = Request(
        RELEASES_API,
        headers={"User-Agent": f"batch-file-manager/{__version__}", "Accept": "application/vnd.github+json"},
    )
    with urlopen(req, timeout=timeout) as response:
        return json.load(response)["tag_name"].lstrip("v")


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version)[:3])


def is_newer(latest: str, current: str) -> bool:
    return _key(latest) > _key(current)
