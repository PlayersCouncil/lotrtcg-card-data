"""The Gemp side: card blueprints, the alternate-ID mapping and the client's image maps.

Read from a checkout of the Gemp repo (the workflow makes a sparse one). The
image logic follows Gemp's client (Card.getImageUrl), because those maps are what
Gemp actually shows; the `image` paths in the HJSON files aren't used by Gemp.
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


_ENTRY_RE = re.compile(r"""^\s*["'](-?\w+)["']\s*:\s*["']([^"']+)["']""", re.M)


def _js_map(path):
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    # Commented-out entries start with //, which the pattern's ^\s* doesn't allow
    return {key: url for key, url in _ENTRY_RE.findall(text)}


def _remade_erratas(card_js):
    """Card.remadeErratas: Decipher errata Gemp shows from its own images/erratas folder."""
    text = card_js.read_text(encoding="utf-8")
    block = re.search(r"static remadeErratas\s*=\s*\{(.*?)\}", text, re.S)
    result = {}
    if block:
        for set_number, numbers in re.findall(r'"(\d+)"\s*:\s*\[([^\]]*)\]', block.group(1)):
            result[int(set_number)] = {int(n) for n in re.findall(r"\d+", numbers)}
    return result


class ImageMaps:
    """Card.getImageUrl, ported."""

    def __init__(self, js_dir):
        js_dir = pathlib.Path(js_dir)
        self.fixed = _js_map(js_dir / "cards" / "CardImages.js")
        self.set40 = _js_map(js_dir / "set40.js")
        self.hobbit = _js_map(js_dir / "hobbit.js")
        self.pc = _js_map(js_dir / "PC_Cards.js")
        self.remade = _remade_erratas(js_dir / "cards" / "Card.js")

    def explicit(self, blueprint_id):
        for table in (self.fixed, self.set40, self.hobbit, self.pc):
            if blueprint_id in table:
                return table[blueprint_id]
        return None

    @staticmethod
    def _card_no(set_number, number):
        return f"{set_number:02d}{number:03d}"

    @staticmethod
    def _masterworks(set_number, number):
        if set_number in (12, 13):
            return number > 194
        if set_number == 15:
            return 194 < number < 204
        if set_number == 17:
            return number > 148
        if set_number == 18:
            return number > 140
        return False

    def decipher_original(self, blueprint_id):
        """The printed card's image, ignoring any Decipher errata image."""
        set_number, number = split_id(blueprint_id)
        if self._masterworks(set_number, number):
            offset = {17: 148, 18: 140}.get(set_number, 194)
            card = f"{set_number:02d}O0{number - offset}"
        else:
            card = self._card_no(set_number, number)
        return f"https://i.lotrtcgpc.net/decipher/LOTR{card}.jpg"

    def decipher_errata(self, blueprint_id):
        set_number, number = split_id(blueprint_id)
        if number in self.remade.get(set_number, set()):
            return f"/gemp-lotr/images/erratas/LOTR{self._card_no(set_number, number)}.jpg"
        return None

    def current(self, blueprint_id):
        """What Gemp shows for this blueprint today."""
        return self.explicit(blueprint_id) or self.decipher_errata(blueprint_id) or self.decipher_original(blueprint_id)


def latest_commit(repo, branch, path, token=None):
    """SHA of the newest commit on `branch` touching `path` (GitHub API, one request)."""
    url = f"https://api.github.com/repos/{repo}/commits?sha={branch}&path={path}&per_page=1"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "lotrtcg-card-data"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        commits = json.load(response)
    return commits[0]["sha"] if commits else None
