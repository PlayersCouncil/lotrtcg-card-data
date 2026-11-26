"""Turns the wiki pull and the Gemp checkout into the dataset.

One record per Gemp blueprint in the configured sets: the Decipher and V-set
cards ("card") and the PC errata blueprints ("errata", errataOf the original).
Card facts, version history and each card's wiki page come from the wiki; Gemp
supplies which IDs exist and the alternate-ID mapping. Images are the CDN's
files of the names the wiki gives (cardbuild.cdn).
"""
import collections
import difflib
import re
import unicodedata
import urllib.parse

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
    # Set on a revision only when an erratum changes it (CardType), or on allies and sites (HomeSites)
    "CardType": "type", "HomeSites": "homeSites",
}
INT_FIELDS = {"twilight", "strength", "vitality", "siteNumber", "resistance", "shadowNumber"}
BOOL_FIELDS = {"unique", "canBearRing"}
LIST_FIELDS = {"homeSites"}

# A revision removes a printed value by giving it explicitly as "none": 0 for a stat modifier, None for
# Signet, Block or ArrowDir (Template:Errata). A blank field means "unchanged". After layering, those
# explicit "none" values become null.
NONE_VALUES = {"strengthMod": {"0", "+0", "-0"}, "vitalityMod": {"0", "+0", "-0"}, "resistanceMod": {"0", "+0", "-0"},
               "siteNumberMod": {"0", "+0", "-0"}, "signet": {"None"}, "block": {"None"}, "arrowDirection": {"None"}}


def without_none_values(fields):
    return {k: (None if v is not None and str(v) in NONE_VALUES.get(k, ()) else v) for k, v in fields.items()}

# Wiki set IDs that differ from Gemp's set numbers
WIKI_SET_TO_GEMP = {"V0": 100, "V1": 101, "V2": 102, "V3": 103}


def fold(text):
    text = str(text or "").replace("•", "").replace("’", "'").replace("“", '"').replace("”", '"')
    text = " ".join(text.split()).lower()
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def letters(text):
    return re.sub(r"[^a-z]", "", fold(text))


# Wiki subsets that are printings only, never Gemp blueprints: foil and rare foil
IGNORED_SUBSETS = {"F", "RF"}

# A card's Cargo row is stored on the Data subpage of the card's own page, in the Data namespace:
# "Data:<card page>/Data". A few rows still sit on the subpage in the main namespace, "<card page>/Data".
DATA_PAGE = re.compile(r"^(Data:)?(.+)/Data$")
# The punctuation MediaWiki leaves as it is in a page address (wfUrlencode); everything else is percent-encoded
PAGE_ADDRESS_SAFE = ";@$!*(),/~:"


def page_url(pages, title):
    """A wiki page's address as the wiki writes it: Slopes of Amon Hen (1U361) -> .../Slopes_of_Amon_Hen_(1U361)."""
    return pages + urllib.parse.quote(title.replace(" ", "_"), safe=PAGE_ADDRESS_SAFE)



def same_title(a, b):
    """Same card name, allowing for typos on one side (Ruinous Hail / Ruinous Hall): those show up
    in the report as title mismatches instead of breaking the link between the two."""
    a, b = letters(a), letters(b)
    if a == b or (a and b and (a in b or b in a)):
        return True
    return bool(a and b) and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def to_value(field, raw):
    # "None" (and a 0 modifier) is kept here so a revision can remove a printed value; layer() turns it into null
    if raw is None or raw == "":
        return None
    if field in INT_FIELDS:
        try:
            return int(raw)
        except ValueError:
            return raw
    if field in BOOL_FIELDS:
        return raw in ("1", "true", "True", "yes")
    if field in LIST_FIELDS:
        return [part.strip() for part in str(raw).split(",") if part.strip()]
    return raw


def wiki_gemp_ids(card):
    return [g for g in str(card.get("GEMP_ID") or "").replace(" ", "").split(",") if g]


def stem(wiki_id):
    """LOTR-EN01S050.1 -> LOTR-EN01S050 (the card without its revision)."""
    return wiki_id.rsplit(".", 1)[0]


class Build:
    def __init__(self, config, wiki, blueprints, mapping, cdn, overrides, batch_names):
        self.config = config
        self.wiki = wiki
        self.blueprints = blueprints
        self.mapping = mapping
        self.cdn = cdn
        self.overrides = overrides
        self.batch_names = batch_names
        self.report = collections.defaultdict(list)
        self.card_ranges = config["sets"]["cards"]
        self.errata_ranges = config["sets"]["errata"]
        self.wiki_pages = config["wiki"]["pages"]
        self._wiki_urls = {}

    # ---- wiki indexes ----

    def _index_wiki(self):
        self.cards_by_id = {card["ID"]: card for card in self.wiki["cards"]}
        self.releases_by_card = collections.defaultdict(list)
        self.releases_by_id = {release["ID"]: release for release in self.wiki["releases"]}
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
        """Gemp base ID -> the wiki card for it, plus the wiki's other printings of it (alts)."""
        self.wiki_for = {}
        self.alts_for = collections.defaultdict(list)
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
            base_portrait = self._base_portrait(found[0][1])
            for gemp_id, card in found[1:]:
                alt = {"wikiId": card["ID"], **self._wiki_url(card), "gempId": gemp_id, "subset": card["Subset"],
                       "collInfo": card["CollInfo"]}
                release = self._base_release(card) or {}
                images = self._images(release, base_portrait)
                if images:
                    alt["images"] = images
                # Kept beside the alt for the report: the card image file the wiki gives for it
                self.alts_for[base].append((alt, release.get("ImageFilename") or None))
        for card in self.english:
            # Foil (F) and rare foil (RF) printings never get Gemp blueprints of their own (Ketura, 2026-11-01)
            if card.get("Subset") in IGNORED_SUBSETS:
                continue
            if not wiki_gemp_ids(card) and card.get("IsPlayable") == "1":
                self.report["wikiWithoutGempId"].append({"wiki": card["ID"], "title": card["Title"]})

    def _wiki_url(self, card):
        """{"wikiUrl": the card's wiki page}, from the page its row is stored on; {} when that isn't a Data
        subpage. A row stored anywhere but Data:<card page>/Data is listed in the report."""
        if card["ID"] not in self._wiki_urls:
            match = DATA_PAGE.match(card.get("Page") or "")
            url = page_url(self.wiki_pages, match.group(2)) if match else None
            if not match or not match.group(1):
                self.report["oddDataPage"].append({"wiki": card["ID"], "storedOn": card.get("Page") or None, "wikiUrl": url})
            self._wiki_urls[card["ID"]] = {"wikiUrl": url} if url else {}
        return self._wiki_urls[card["ID"]]

    def _wanted(self, blueprint_id):
        parts = split_id(blueprint_id)
        return parts is not None and (in_ranges(parts[0], self.card_ranges) or in_ranges(parts[0], self.errata_ranges))

    # ---- versions ----

    def _revisions(self, card):
        """English rows of this card (same subset as the card), in revision order."""
        rows = [r for r in self.releases_by_card.get(card["ID"], []) if r["LanguageCode"] == "EN" and stem(r["ID"]) == stem(card["ID"])]
        return sorted(rows, key=lambda r: int(r["Revision"] or 0))

    def _base_release(self, card):
        """The card's English revision-0 row, if the wiki has one."""
        rows = self._revisions(card)
        return rows[0] if rows and int(rows[0]["Revision"] or 0) == 0 else None

    def _base_portrait(self, card):
        """The portrait file name of the card's base version (English revision 0)."""
        release = self._base_release(card)
        return (release.get("PortraitFilename") or None) if release else None

    def _batch(self, release):
        issuer, date = release.get("Issuer") or "", release.get("ReleaseDate") or ""
        if not issuer or not date:
            return None
        key = ("pc" if issuer == ISSUER_PC else "decipher" if issuer == ISSUER_DECIPHER else letters(issuer)) + "-" + date
        self.batches.setdefault(key, {"id": key, "issuer": issuer, "releaseDate": date, "name": self.batch_names.get(key), "cards": 0})
        self.batches[key]["cards"] += 1
        return key

    def _versions(self, card):
        versions = []
        base_portrait = self._base_portrait(card)
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
            version = {
                "wikiId": release["ID"],
                "revision": revision,
                "issuer": issuer if revision > 0 else None,
                "releaseDate": release.get("ReleaseDate") or None,
                "batch": self._batch(release) if revision > 0 else None,
                "fields": changes,
            }
            # The base version has no portrait to inherit; a later one shows only a portrait of its own
            images = self._images(release, base_portrait if revision > 0 else None)
            if images:
                version["images"] = images
            versions.append(version)
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
        return without_none_values(current), last

    # ---- images ----

    def _images(self, release, inherited_portrait):
        """A release row's images in the CDN tree: its card image in each size, the foil scan of it, and its
        portrait when the row names one other than inherited_portrait (the base version's). The card image is
        the clean one even when the row names the foil scan. None when the tree has none of them."""
        images = {}
        shown, foil = self.cdn.clean_and_foil(release.get("ImageFilename"))
        for size in ("1x", "2x", "4x"):
            url = self.cdn.url(size, shown)
            if url:
                images[size] = url
        if foil:
            images["foil"] = self.cdn.url("1x", foil)
        portrait = release.get("PortraitFilename") or None
        if portrait and portrait != inherited_portrait:
            url = self.cdn.url("1x", portrait)
            if url:
                images["portrait"] = url
        return images or None

    @staticmethod
    def _record_images(versions, last):
        """The images of the version a record describes, with the portrait in effect for it: the version's
        own portrait if it has one, otherwise the base version's."""
        if last is None:
            return None
        images = {k: v for k, v in (last.get("images") or {}).items() if k != "portrait"}
        own = (last.get("images") or {}).get("portrait")
        base = (versions[0].get("images") or {}).get("portrait") if versions[0]["revision"] == 0 else None
        if own or base:
            images["portrait"] = own or base
        return images or None

    def _no_image(self, what, gemp_id, wiki_id, file, images):
        """Report a card, version or alt without a standard-size image; file is the name the wiki gives."""
        if not (images or {}).get("1x"):
            self.report["noImage"].append({"gempId": gemp_id, "wikiId": wiki_id, "file": file, "what": what})

    # ---- printings in other languages ----

    def _translations(self, card):
        out = []
        base_portrait = self._base_portrait(card)
        for release in self.releases_by_card.get(card["ID"], []):
            if release["LanguageCode"] == "EN":
                continue
            fields = {}
            for wiki_field in ("Title", "Subtitle", "GameText", "Lore", "PromoText"):
                if release.get(wiki_field):
                    fields[VERSION_FIELDS[wiki_field]] = release[wiki_field]
            translation = {
                "wikiId": release["ID"], "language": release["LanguageCode"], "subset": release.get("Subset"),
                "revision": int(release["Revision"] or 0), "fields": fields,
                "physical": release.get("IsPhysical") == "1",
            }
            images = self._images(release, base_portrait)
            if images:
                translation["images"] = images
            out.append(translation)
        return sorted(out, key=lambda p: (p["language"], p["wikiId"]))

    # ---- records ----

    def _base_fields(self, card):
        return {
            "wikiId": card["ID"],
            **self._wiki_url(card),
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
        reprints = collections.defaultdict(list)
        for alternate, base in self.mapping.items():
            reprints[base].append(alternate)

        records = {}
        for blueprint_id in sorted(self.blueprints, key=lambda b: split_id(b)):
            set_number, number = split_id(blueprint_id)
            if in_ranges(set_number, self.card_ranges):
                if blueprint_id in self.mapping:
                    continue  # an alternate of another blueprint; listed on that one
                records[blueprint_id] = self._card(blueprint_id, set_number, number, reprints)
            elif in_ranges(set_number, self.errata_ranges):
                records[blueprint_id] = self._errata(blueprint_id, set_number, number)

        for blueprint_id, record in records.items():
            original = record.get("errataOf")
            if original and original in records:
                records[original]["errataId"] = blueprint_id
        return records, sorted(self.batches.values(), key=lambda b: (b["releaseDate"], b["id"]))

    def _card(self, blueprint_id, set_number, number, reprints):
        card = self.wiki_for.get(blueprint_id)
        record = {"id": blueprint_id, "set": str(set_number), "number": number, "kind": "card"}
        if card is None:
            self.report["gempOnly"].append({"gempId": blueprint_id, "title": self.blueprints[blueprint_id].get("title")})
            record.update({"source": "gemp", **self._from_gemp(blueprint_id), "versions": [], "translations": []})
            self._no_image("card", blueprint_id, None, None, None)
        else:
            versions = self._versions(card)
            # V-set cards are PC cards: their PC revisions are the card. Decipher cards: Decipher's own errata only.
            issuers = {ISSUER_DECIPHER, ISSUER_PC} if set_number >= 100 else {ISSUER_DECIPHER}
            current, last = self.layer(versions, issuers)
            record.update({"source": "wiki", **self._base_fields(card), **current, "versions": versions, "translations": self._translations(card)})
            self._set_record_images(record, versions, last)
            for version in versions:
                self._no_image("version", blueprint_id, version["wikiId"], self._file(version), version.get("images"))
        record["reprints"] = sorted(reprints.get(blueprint_id, []), key=split_id)
        record["alts"] = []
        for alt, file in self.alts_for.get(blueprint_id, []):
            record["alts"].append(alt)
            self._no_image("alt", alt["gempId"], alt["wikiId"], file, alt.get("images"))
        return record

    def _set_record_images(self, record, versions, last):
        """The record's images: those of `last`, the version its fields describe."""
        images = self._record_images(versions, last)
        if images:
            record["images"] = images
        self._no_image("card", record["id"], last["wikiId"] if last else record.get("wikiId"), self._file(last) if last else None, images)

    def _file(self, version):
        """The card image file name the wiki gives for a version."""
        return self.releases_by_id[version["wikiId"]].get("ImageFilename") or None

    def _errata(self, blueprint_id, set_number, number):
        original = f"{set_number - 50}_{number}"
        card = self.wiki_for.get(original)
        record = {"id": blueprint_id, "set": str(set_number), "number": number, "kind": "errata", "errataOf": original}
        if card is None:
            self.report["gempOnly"].append({"gempId": blueprint_id, "title": self.blueprints[blueprint_id].get("title")})
            record.update({"source": "gemp", **self._from_gemp(blueprint_id)})
            self._no_image("card", blueprint_id, None, None, None)
        else:
            versions = self._versions(card)
            current, last = self.layer(versions, {ISSUER_DECIPHER, ISSUER_PC})
            has_pc = any(v["issuer"] == ISSUER_PC for v in versions)
            if not has_pc:
                self.report["pcErrataMissingOnWiki"].append({"gempId": blueprint_id, "wiki": card["ID"]})
            record.update({"source": "wiki" if has_pc else "wiki+gemp", **self._base_fields(card), **current,
                           "wikiVersion": last["wikiId"] if last and has_pc else None})
            if not has_pc:
                # Without the PC revision on the wiki, Gemp is the only record of the erratum's stats
                record.update({k: v for k, v in self._from_gemp(blueprint_id).items() if v is not None and k not in ("gameText", "lore")})
            self._set_record_images(record, versions, last)
        return record


def _wiki_field(name):
    return {"title": "Title", "subtitle": "Subtitle", "culture": "Culture", "set": "SetNum", "collInfo": "CollInfo"}.get(name, name)


def set_file(set_number):
    """The data file for a Gemp set: 01.json for Decipher sets, E01.json for PC errata of set 1 (Gemp set 51),
    V01.json for V-set 1 (Gemp set 101)."""
    number = int(set_number)
    if number >= 100:
        return f"V{number - 100:02d}.json"
    if 50 <= number <= 69:
        return f"E{number - 50:02d}.json"
    return f"{number:02d}.json"


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
        entry["file"] = "cards/" + set_file(number)
        sets.append(entry)
    return sets
