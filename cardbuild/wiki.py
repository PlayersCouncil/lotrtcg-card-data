"""The wiki side: Cargo tables over the MediaWiki API, pulled slowly.

The wiki rate-limits its API (HTTP 429 after a few quick requests), so every
request waits `delaySeconds` and backs off on 429.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

CARD_FIELDS = [
    "ID", "ReprintBaseID", "Title", "Subtitle", "SetNum", "Subset", "SetOrder", "Rarity", "CardNum",
    "Revision", "CollInfo", "GEMP_ID", "Culture", "Side", "CardType", "IsPhysical", "IsPlayable",
]

RELEASE_FIELDS = [
    "ID", "BaseCardID", "Subset", "Revision", "Issuer", "ReleaseDate", "ReleaseNotes", "ImageFilename",
    "LanguageCode", "IsPhysical", "IsPlayable", "CollInfo", "IsUnique", "Title", "Subtitle", "Subtypes",
    "TwilightCost", "Strength", "StrengthMod", "Vitality", "VitalityMod", "SiteNum", "SiteNumMod",
    "Resistance", "ResistanceMod", "CanBearRing", "Signet", "Block", "ShadowNum", "ArrowDir",
    "GameText", "Lore", "PromoText",
]

SET_FIELDS = ["ID", "Name", "Abbr", "Creator", "ReleaseDate", "IsOfficial"]


class Wiki:
    def __init__(self, api, delay=2.0, user_agent="lotrtcg-card-data", opener=None):
        self.api = api
        self.delay = delay
        self.user_agent = user_agent
        self._open = opener or urllib.request.urlopen
        self._last = 0.0

    def _get(self, params):
        url = self.api + "?" + urllib.parse.urlencode({**params, "format": "json"})
        for attempt in range(8):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
                with self._open(request, timeout=60) as response:
                    data = json.load(response)
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    raise
                time.sleep(int(e.headers.get("Retry-After") or 10 * (attempt + 1)))
                continue
            if "error" in data:
                raise RuntimeError(f"wiki API error: {data['error']}")
            return data
        raise RuntimeError("wiki API kept answering 429")

    def latest_revision(self, namespaces):
        """The newest revision in the given namespaces: the wiki's data version."""
        data = self._get({
            "action": "query", "list": "allrevisions", "arvnamespace": "|".join(str(n) for n in namespaces),
            "arvlimit": 1, "arvprop": "ids|timestamp",
        })
        pages = data["query"]["allrevisions"]
        if not pages:
            return {"revid": 0, "timestamp": None}
        revision = pages[0]["revisions"][0]
        return {"revid": revision["revid"], "timestamp": revision["timestamp"]}

    def cargo(self, table, fields, where=None, page=500):
        """Every row of a Cargo table, as dicts keyed by field name (spaces in Cargo's names become _)."""
        rows = []
        offset = 0
        while True:
            params = {
                "action": "cargoquery", "tables": table, "fields": ",".join(fields),
                "limit": page, "offset": offset, "order_by": f"{table}._pageID,{table}._ID",
            }
            if where:
                params["where"] = where
            batch = [row["title"] for row in self._get(params).get("cargoquery", [])]
            for row in batch:
                rows.append({key.replace(" ", "_"): value for key, value in row.items() if not key.endswith("__precision")})
            offset += page
            if len(batch) < page:
                return rows

    def pull(self):
        """Everything the build needs from the wiki."""
        return {
            "cards": self.cargo("Cards", CARD_FIELDS),
            "releases": self.cargo("CardReleases", RELEASE_FIELDS),
            "sets": self.cargo("CardSets", SET_FIELDS),
        }
