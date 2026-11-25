"""The Gemp side: card blueprints and the alternate-ID mapping.

Read from a checkout of the Gemp repo (the workflow makes a sparse one).
"""
import json
import pathlib
import re
import urllib.request

import hjson

ID_RE = re.compile(r"^(\d+)_(\d+)$")


def split_id(blueprint_id):
    match = ID_RE.match(blueprint_id)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def in_ranges(set_number, ranges):
    return any(low <= set_number <= high for low, high in ranges)


def load_blueprints(cards_dir):
    """Every blueprint in the HJSON card files: {id: definition}."""
    blueprints = {}
    for path in sorted(pathlib.Path(cards_dir).rglob("*.hjson")):
        with open(path, encoding="utf-8") as handle:
            data = hjson.load(handle)
        for key, value in data.items():
            if isinstance(value, dict) and split_id(key):
                blueprints[key] = value
    return blueprints


def load_mapping(path):
    """blueprintMapping.txt: alternate ID -> base ID (promos, alternate images, reprints)."""
    mapping = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 2 and split_id(parts[0]) and split_id(parts[1]):
            mapping[parts[0]] = parts[1]
    return mapping


def latest_commit(repo, branch, path, token=None):
    """SHA of the newest commit on `branch` touching `path` (GitHub API, one request)."""
    url = f"https://api.github.com/repos/{repo}/commits?sha={branch}&path={path}&per_page=1"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "lotrtcg-card-data"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        commits = json.load(response)
    return commits[0]["sha"] if commits else None
