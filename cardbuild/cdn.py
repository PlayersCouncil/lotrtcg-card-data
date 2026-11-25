"""The CDN's file list (files.lotrtcgpc.net/_dirindex/manifest.json), for finding card images.

Card images live in one tree on the CDN, one folder per size under the tree's prefix (config.json → cdn.tree):
wiki/original/ (standard size: card images and portraits), wiki/double/ (2x) and wiki/huge/ (4x). Within each
size folder a file name is unique, so an image is found by its wiki file name alone; where in the folder it sits
(language, set) is taken from the file list.
"""
import json
import re
import urllib.request

# A card image's file name around its subset letter: LOTR-EN12 | O | 079.0_card.jpg
CARD_FILE = re.compile(r"^(.+-[A-Z]{2}[0-9A-Z]{2})([A-Z])(\d{3}\.\d+_card\..+)$")


def fetch_manifest(url, user_agent="lotrtcg-card-data"):
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


class Cdn:
    def __init__(self, manifest, base, tree):
        self.base = base
        self.hash = manifest.get("hash")
        self.folders = {size: tree["prefix"] + folder + "/" for size, folder in tree["sizes"].items()}
        self.by_size = {size: {} for size in self.folders}
        # Subset letter of a clean image -> subset letter of the foil scan of the same card
        self.foil_of = tree.get("foilOf", {})
        self._walk(manifest["root"], "")

    def _walk(self, node, prefix):
        for entry in node.get("f", []):
            path = prefix + entry[0]
            for size, folder in self.folders.items():
                if path.startswith(folder):
                    names = self.by_size[size]
                    if entry[0] in names:
                        raise RuntimeError(f"{entry[0]} is in {folder} twice: {names[entry[0]]} and {path}")
                    names[entry[0]] = path
        for name, child in node.get("d", {}).items():
            self._walk(child, prefix + name + "/")

    def clean_and_foil(self, name):
        """(file to show, foil scan or None) for the image file a wiki row names.

        A foil scan carries the clean image's name with only the subset letter changed (cdn.tree.foilOf:
        LOTR-EN12O079.0_card.jpg and LOTR-EN12G079.0_card.jpg). A row that names the scan itself is shown by
        the clean image when the tree has one; a clean image gets its scan when the tree has one. A file the
        tree does not hold stands alone: nothing is shown in its place, and it has no foil."""
        match = CARD_FILE.match(name or "")
        if not match or name not in self.by_size["1x"]:
            return name, None
        before, letter, after = match.groups()
        for clean, foil in self.foil_of.items():
            if letter == foil and before + clean + after in self.by_size["1x"]:
                return before + clean + after, name
        scan = before + self.foil_of[letter] + after if letter in self.foil_of else None
        return name, scan if scan in self.by_size["1x"] else None

    def url(self, size, name):
        """The URL of the file with this name in this size's folder, or None if it isn't there."""
        path = self.by_size[size].get(name) if name else None
        return self.base + path if path else None
