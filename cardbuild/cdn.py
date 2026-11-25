"""The CDN's file list (files.lotrtcgpc.net/_dirindex/manifest.json), for finding card images.

Card images live in one tree on the CDN, one folder per size under the tree's prefix (config.json → cdn.tree):
wiki/original/ (standard size: card images and portraits), wiki/double/ (2x) and wiki/huge/ (4x). Within each
size folder a file name is unique, so an image is found by its wiki file name alone; where in the folder it sits
(language, set) is taken from the file list.
"""
import json
import urllib.request


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

    def url(self, size, name):
        """The URL of the file with this name in this size's folder, or None if it isn't there."""
        path = self.by_size[size].get(name) if name else None
        return self.base + path if path else None
