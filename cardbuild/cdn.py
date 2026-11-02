"""The CDN's file list (files.lotrtcgpc.net/_dirindex/manifest.json), for checking and finding images."""
import json
import urllib.request


def fetch_manifest(url, user_agent="lotrtcg-card-data"):
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


class Cdn:
    def __init__(self, manifest, base, old_host, cards_prefix="cards/", gemp_base=None):
        self.base = base
        self.old_host = old_host
        self.cards_prefix = cards_prefix
        self.gemp_base = gemp_base
        self.hash = manifest.get("hash")
        self.paths = set()
        self.by_name = {}
        self._walk(manifest["root"], "")

    def _walk(self, node, prefix):
        for entry in node.get("f", []):
            path = prefix + entry[0]
            self.paths.add(path)
            folder = prefix.rstrip("/").split("/")[-1] if prefix else ""
            # The double/ and huge/ folders hold upscaled copies; a card's image is the plain one
            if folder not in ("double", "huge"):
                self.by_name.setdefault(entry[0], []).append(path)
        for name, child in node.get("d", {}).items():
            self._walk(child, prefix + name + "/")

    def url(self, image):
        """A Gemp image reference as a public URL: i.lotrtcgpc.net becomes the CDN, Gemp-relative paths Gemp's host."""
        if image is None:
            return None
        if image.startswith(self.old_host):
            return self.base + self.cards_prefix + image[len(self.old_host):]
        if image.startswith("/") and self.gemp_base:
            return self.gemp_base + image
        return image

    def exists(self, url):
        """True/False for CDN URLs, None for URLs elsewhere (not checkable from the manifest)."""
        if url is None:
            return False
        if not url.startswith(self.base):
            return None
        return url[len(self.base):] in self.paths

    def find(self, names):
        """The first of these file names that's on the CDN, as a URL (prefers the shortest path)."""
        for name in names:
            paths = self.by_name.get(name)
            if paths:
                return self.base + sorted(paths, key=len)[0]
        return None
