"""Turns the wiki pull and the Gemp checkout into the dataset.

One record per Gemp blueprint in the configured sets: the Decipher and V-set
cards ("card") and the PC errata blueprints ("errata", errataOf the original).
Card facts and version history come from the wiki; Gemp supplies which IDs
exist, the alternate-ID mapping and the images Gemp shows.
"""
import collections
import difflib
import re
import unicodedata

from .gemp import in_ranges, split_id

ISSUER_PC = "Player's Council"
ISSUER_DECIPHER = "Decipher"

# Wiki CardReleases fields carried into a version, and their dataset names.
# A blank field on a revision row means "unchanged from the previous revision".
VERSION_FIELDS = {
    "Title": "title", "Subtitle": "subtitle", "IsUnique": "unique", "Subtypes": "subtypes",
    "TwilightCost": "twilight", "Strength": "strength", "StrengthMod": "strengthMod",
    "Vitality": "vitality", "VitalityMod": "vitalityMod", "SiteNum": "siteNumber",
    "SiteNumMod": "siteNumberMod", "Resistance": "resistance", "ResistanceMod": "resistanceMod",
    "CanBearRing": "canBearRing", "Signet": "signet", "Block": "block", "ShadowNum": "shadowNumber",
    "ArrowDir": "arrowDirection", "GameText": "gameText", "Lore": "lore", "PromoText": "promoText",
}
INT_FIELDS = {"twilight", "strength", "vitality", "siteNumber", "resistance", "shadowNumber"}
BOOL_FIELDS = {"unique", "canBearRing"}

# Wiki set IDs that differ from Gemp's set numbers
WIKI_SET_TO_GEMP = {"V0": 100, "V1": 101, "V2": 102, "V3": 103}


def fold(text):
    text = str(text or "").replace("•", "").replace("’", "'").replace("“", '"').replace("”", '"')
    text = " ".join(text.split()).lower()
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def letters(text):
    return re.sub(r"[^a-z]", "", fold(text))


def same_title(a, b):
    """Same card name, allowing for typos on one side (Ruinous Hail / Ruinous Hall): those show up
    in the report as title mismatches instead of breaking the link between the two."""
    a, b = letters(a), letters(b)
    if a == b or (a and b and (a in b or b in a)):
        return True
    return bool(a and b) and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def to_value(field, raw):
    if raw is None or raw == "":
        return None
    if field in INT_FIELDS:
        try:
            return int(raw)
        except ValueError:
            return raw
    if field in BOOL_FIELDS:
        return raw in ("1", "true", "True", "yes")
    return raw


def wiki_gemp_ids(card):
    return [g for g in str(card.get("GEMP_ID") or "").replace(" ", "").split(",") if g]


def stem(wiki_id):
    """LOTR-EN01S050.1 -> LOTR-EN01S050 (the card without its revision)."""
    return wiki_id.rsplit(".", 1)[0]


class Build:
    def __init__(self, config, wiki, blueprints, mapping, images, cdn, overrides, batch_names):
        self.config = config
        self.wiki = wiki
        self.blueprints = blueprints
        self.mapping = mapping
        self.images = images
        self.cdn = cdn
        self.overrides = overrides
        self.batch_names = batch_names
        self.report = collections.defaultdict(list)
        self.card_ranges = config["sets"]["cards"]
        self.errata_ranges = config["sets"]["errata"]

    # ---- wiki indexes ----

    def _index_wiki(self):
        self.cards_by_id = {card["ID"]: card for card in self.wiki["cards"]}
        self.releases_by_card = collections.defaultdict(list)
        for release in self.wiki["releases"]:
            self.releases_by_card[release["BaseCardID"]].append(release)
        self.english = [c for c in self.wiki["cards"] if c["ID"].startswith("LOTR-EN")]

    def _apply_overrides(self):
        for rule in self.overrides.get("gempIds", []):
            match = rule["match"]
            hits = [c for c in self.english if all(fold(c.get(_wiki_field(k))) == fold(v) for k, v in match.items())]
            if len(hits) != 1:
                raise RuntimeError(f"override {match} matched {len(hits)} English wiki cards, expected 1")
            card = hits[0]
            self.report["overridesApplied"].append({"wiki": card["ID"], "wikiGempId": card.get("GEMP_ID"), "gempId": rule["gempId"]})
            card["GEMP_ID"] = rule["gempId"]

    def _assign_cards(self):
        """Gemp base ID -> the wiki card for it, plus the wiki's other printings of it."""
        self.wiki_for = {}
        self.printings_for = collections.defaultdict(list)
        candidates = collections.defaultdict(list)
        for card in self.english:
            for gemp_id in wiki_gemp_ids(card):
                if not split_id(gemp_id):
                    self.report["unusableGempId"].append({"wiki": card["ID"], "gempId": gemp_id})
                    continue
                base = self.mapping.get(gemp_id, gemp_id)
                blueprint = self.blueprints.get(base)
                if blueprint is None:
                    if self._wanted(base):
                        self.report["wikiOnly"].append({"wiki": card["ID"], "title": card["Title"], "gempId": gemp_id})
                    continue
                if not same_title(card["Title"], blueprint.get("title")):
                    self.report["wrongGempId"].append({
                        "wiki": card["ID"], "wikiTitle": card["Title"], "gempId": gemp_id, "gempTitle": blueprint.get("title")})
                    continue
                candidates[base].append((gemp_id, card))
        for base, found in candidates.items():
            # The card whose own Gemp ID is the base, standard subset first; the rest are other printings
            found.sort(key=lambda pair: (pair[0] != base, pair[1]["Subset"] != "S", pair[1]["ID"]))
            self.wiki_for[base] = found[0][1]
            for gemp_id, card in found[1:]:
                self.printings_for[base].append({"wikiId": card["ID"], "gempId": gemp_id, "subset": card["Subset"], "collInfo": card["CollInfo"]})
        for card in self.english:
            if not wiki_gemp_ids(card) and card.get("IsPlayable") == "1":
                self.report["wikiWithoutGempId"].append({"wiki": card["ID"], "title": card["Title"]})

    def _wanted(self, blueprint_id):
        parts = split_id(blueprint_id)
        return parts is not None and (in_ranges(parts[0], self.card_ranges) or in_ranges(parts[0], self.errata_ranges))

    # ---- versions ----

    def _revisions(self, card):
        """English rows of this card (same subset as the card), in revision order."""
        rows = [r for r in self.releases_by_card.get(card["ID"], []) if r["LanguageCode"] == "EN" and stem(r["ID"]) == stem(card["ID"])]
        return sorted(rows, key=lambda r: int(r["Revision"] or 0))

    def _batch(self, release):
        issuer, date = release.get("Issuer") or "", release.get("ReleaseDate") or ""
        if not issuer or not date:
            return None
        key = ("pc" if issuer == ISSUER_PC else "decipher" if issuer == ISSUER_DECIPHER else letters(issuer)) + "-" + date
        self.batches.setdefault(key, {"id": key, "issuer": issuer, "releaseDate": date, "name": self.batch_names.get(key), "cards": 0})
        self.batches[key]["cards"] += 1
        return key

    def _versions(self, card, gemp_id):
        versions = []
        for release in self._revisions(card):
            changes = {}
            for wiki_field, field in VERSION_FIELDS.items():
                value = to_value(field, release.get(wiki_field))
                if value is not None:
                    changes[field] = value
            revision = int(release["Revision"] or 0)
            issuer = release.get("Issuer") or None
            if revision > 0 and not issuer:
                self.report["revisionWithoutIssuer"].append({"wiki": release["ID"]})
            versions.append({
                "wikiId": release["ID"],
                "revision": revision,
                "issuer": issuer if revision > 0 else None,
                "releaseDate": release.get("ReleaseDate") or None,
                "batch": self._batch(release) if revision > 0 else None,
                "fields": changes,
                "image": self._version_image(gemp_id, release, revision, issuer),
                "wikiImage": release.get("ImageFilename") or None,
            })
            if revision > 0 and issuer == ISSUER_DECIPHER and not release.get("ReleaseDate"):
                self.report["decipherErrataWithoutDate"].append(release["ID"])
        return versions

    @staticmethod
    def layer(versions, issuers):
        """The card as of the last version from these issuers (revision 0 always applies)."""
        current = {}
        last = None
        for version in versions:
            if version["revision"] > 0 and version["issuer"] not in issuers:
                continue
            current.update(version["fields"])
            last = version
        return current, last

    # ---- images ----

    def _version_image(self, gemp_id, release, revision, issuer):
        set_number, _ = split_id(gemp_id)
        if revision == 0 and set_number <= 19:
            return self.cdn.url(self.images.explicit(gemp_id) or self.images.decipher_original(gemp_id))
        if issuer == ISSUER_DECIPHER:
            return self.cdn.url(self.images.decipher_errata(gemp_id))
        # PC revisions and V-set cards: find the file on the CDN by name. The CDN names errata
        # revisions with subset E where the wiki has S (LOTR-EN01E050.1_card.jpg).
        name = release.get("ImageFilename") or ""
        names = [name]
        match = re.match(r"^(LOTR-EN[0-9V]\w)S(\d+\.\d+_card\.jpg)$", name)
        if match:
            names.append(f"{match.group(1)}E{match.group(2)}")
        return self.cdn.find([n for n in names if n])

    def _current_image(self, blueprint_id):
        url = self.cdn.url(self.images.current(blueprint_id))
        if self.cdn.exists(url) is False:
            self.report["imageMissing"].append({"gempId": blueprint_id, "url": url})
        return url

    # ---- printings in other languages ----

    def _translations(self, card):
        out = []
        for release in self.releases_by_card.get(card["ID"], []):
            if release["LanguageCode"] == "EN":
                continue
            fields = {}
            for wiki_field in ("Title", "Subtitle", "GameText", "Lore", "PromoText"):
                if release.get(wiki_field):
                    fields[VERSION_FIELDS[wiki_field]] = release[wiki_field]
            out.append({
                "wikiId": release["ID"], "language": release["LanguageCode"], "subset": release.get("Subset"),
                "revision": int(release["Revision"] or 0), "fields": fields,
                "wikiImage": release.get("ImageFilename") or None,
                "physical": release.get("IsPhysical") == "1",
            })
        return sorted(out, key=lambda p: (p["language"], p["wikiId"]))

    # ---- records ----

    def _base_fields(self, card):
        return {
            "wikiId": card["ID"],
            "collInfo": card.get("CollInfo") or None,
            "rarity": card.get("Rarity") or None,
            "culture": {"Site": None, "": None}.get(card.get("Culture"), card.get("Culture")),
            "side": {"None": None, "": None}.get(card.get("Side"), card.get("Side")),
            "type": card.get("CardType") or None,
        }

    def _from_gemp(self, blueprint_id):
        """A record for a Gemp blueprint the wiki doesn't have: Gemp's own fields, flagged."""
        blueprint = self.blueprints[blueprint_id]
        return {
            "title": blueprint.get("title"), "subtitle": blueprint.get("subtitle"), "unique": bool(blueprint.get("unique")),
            "culture": blueprint.get("culture"), "side": blueprint.get("side"), "type": blueprint.get("type"),
            "twilight": blueprint.get("twilight"), "strength": blueprint.get("strength"), "vitality": blueprint.get("vitality"),
            "resistance": blueprint.get("resistance"), "siteNumber": blueprint.get("site"), "gameText": blueprint.get("gametext"),
            "lore": blueprint.get("lore"),
        }

    def run(self):
        self._index_wiki()
        self._apply_overrides()
        self._assign_cards()
        self.batches = {}
        alternates = collections.defaultdict(list)
        for alternate, base in self.mapping.items():
            alternates[base].append(alternate)

        records = {}
        for blueprint_id in sorted(self.blueprints, key=lambda b: split_id(b)):
            set_number, number = split_id(blueprint_id)
            if in_ranges(set_number, self.card_ranges):
                if blueprint_id in self.mapping:
                    continue  # an alternate of another blueprint; listed on that one
                records[blueprint_id] = self._card(blueprint_id, set_number, number, alternates)
            elif in_ranges(set_number, self.errata_ranges):
                records[blueprint_id] = self._errata(blueprint_id, set_number, number)

        for blueprint_id, record in records.items():
            original = record.get("errataOf")
            if original and original in records:
                records[original]["errataId"] = blueprint_id
        return records, sorted(self.batches.values(), key=lambda b: (b["releaseDate"], b["id"]))

    def _card(self, blueprint_id, set_number, number, alternates):
        card = self.wiki_for.get(blueprint_id)
        record = {"id": blueprint_id, "set": str(set_number), "number": number, "kind": "card"}
        if card is None:
            self.report["gempOnly"].append({"gempId": blueprint_id, "title": self.blueprints[blueprint_id].get("title")})
            record.update({"source": "gemp", **self._from_gemp(blueprint_id), "versions": [], "translations": []})
        else:
            versions = self._versions(card, blueprint_id)
            # V-set cards are PC cards: their PC revisions are the card. Decipher cards: Decipher's own errata only.
            issuers = {ISSUER_DECIPHER, ISSUER_PC} if set_number >= 100 else {ISSUER_DECIPHER}
            current, _ = self.layer(versions, issuers)
            record.update({"source": "wiki", **self._base_fields(card), **current, "versions": versions, "translations": self._translations(card)})
        record["image"] = self._current_image(blueprint_id)
        record["alternates"] = sorted(alternates.get(blueprint_id, []), key=split_id)
        record["printings"] = self.printings_for.get(blueprint_id, [])
        return record

    def _errata(self, blueprint_id, set_number, number):
        original = f"{set_number - 50}_{number}"
        card = self.wiki_for.get(original)
        record = {"id": blueprint_id, "set": str(set_number), "number": number, "kind": "errata", "errataOf": original}
        if card is None:
            self.report["gempOnly"].append({"gempId": blueprint_id, "title": self.blueprints[blueprint_id].get("title")})
            record.update({"source": "gemp", **self._from_gemp(blueprint_id)})
        else:
            versions = self._versions(card, original)
            current, last = self.layer(versions, {ISSUER_DECIPHER, ISSUER_PC})
            has_pc = any(v["issuer"] == ISSUER_PC for v in versions)
            if not has_pc:
                self.report["pcErrataMissingOnWiki"].append({"gempId": blueprint_id, "wiki": card["ID"]})
            record.update({"source": "wiki" if has_pc else "wiki+gemp", **self._base_fields(card), **current,
                           "wikiVersion": last["wikiId"] if last and has_pc else None})
            if not has_pc:
                # Without the PC revision on the wiki, Gemp is the only record of the erratum's stats
                record.update({k: v for k, v in self._from_gemp(blueprint_id).items() if v is not None and k not in ("gameText", "lore")})
        record["image"] = self._current_image(blueprint_id)
        return record


def _wiki_field(name):
    return {"title": "Title", "subtitle": "Subtitle", "culture": "Culture", "set": "SetNum", "collInfo": "CollInfo"}.get(name, name)


def build_sets(wiki_sets, records):
    """Sets in the dataset, named from the wiki; PC errata sets named after the set they errata."""
    by_number = {}
    for row in wiki_sets:
        number = WIKI_SET_TO_GEMP.get(row["ID"])
        if number is None and row["ID"].isdigit():
            number = int(row["ID"])
        if number is None:
            continue
        by_number[number] = {
            "set": str(number), "wikiSet": row["ID"], "name": row["Name"], "abbreviation": row.get("Abbr") or None,
            "creator": row.get("Creator") or None, "releaseDate": row.get("ReleaseDate") or None,
            "official": row.get("IsOfficial") == "1",
        }
    present = sorted({int(r["set"]) for r in records.values()})
    sets = []
    for number in present:
        if number in by_number:
            entry = dict(by_number[number], kind="pc" if number >= 100 else "decipher")
        elif 50 <= number <= 69 and (number - 50) in by_number:
            source = by_number[number - 50]
            entry = {"set": str(number), "wikiSet": None, "name": source["name"] + " (PC errata)",
                     "abbreviation": None, "creator": ISSUER_PC, "releaseDate": None, "official": False,
                     "kind": "pc-errata", "errataOfSet": source["set"]}
        else:
            entry = {"set": str(number), "wikiSet": None, "name": None, "kind": "unknown"}
        entry["cards"] = sum(1 for r in records.values() if r["set"] == str(number))
        sets.append(entry)
    return sets
