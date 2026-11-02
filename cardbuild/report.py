"""The mismatch report: where the wiki, Gemp and the CDN disagree.

Published with every build so the wiki (and Gemp) can be fixed; nothing here
blocks a build.
"""
import collections
import re

from .assemble import ISSUER_PC, fold, letters

# Gemp field -> dataset field, compared after normalizing
COMPARED = ["title", "twilight", "strength", "vitality", "siteNumber", "culture", "side", "type"]
# Bonuses on these types live in different places in Gemp and on the wiki; not compared
BONUS_TYPES = {"possession", "artifact", "follower", "condition"}
CULTURE_ALIASES = {"ringwraith": "wraith"}


def _num(value):
    try:
        return int(str(value).strip().replace("+", ""))
    except (TypeError, ValueError):
        return None


def _gemp_value(field, blueprint):
    kind = fold(blueprint.get("type"))
    if field == "twilight":
        return _num(blueprint.get("twilight"))
    if field == "siteNumber":
        if kind == "ally":
            # e.g. "3F", or "2T,8T" for an ally with two home sites: compare the first
            match = re.match(r"\s*(\d+)", str(blueprint.get("allyHome") or ""))
            return int(match.group(1)) if match else None
        return _num(blueprint.get("site"))
    if field in ("strength", "vitality"):
        return _num(blueprint.get(field))
    if field == "title":
        # Gemp gives cards that share a name with another card a "(2)" suffix to tell them apart
        # internally (Ketura, 2026-11-01); the card's real name is without it
        return re.sub(r"\s*\(\d\)\s*$", "", fold(blueprint.get("title")))
    return letters(blueprint.get(field))


def _record_value(field, record):
    kind = fold(record.get("type"))
    if field == "twilight":
        return _num(record.get("shadowNumber") if kind == "site" else record.get("twilight"))
    if field in ("strength", "vitality", "siteNumber"):
        return _num(record.get(field))
    if field == "title":
        return fold(record.get("title"))
    value = letters(record.get(field))
    return CULTURE_ALIASES.get(value, value) if field == "culture" else value


def compare(records, blueprints):
    mismatches = []
    unrecorded = []
    for blueprint_id, record in records.items():
        if record.get("source") == "gemp":
            continue
        blueprint = blueprints.get(blueprint_id)
        if blueprint is None or fold(blueprint.get("type")) == "the one ring":
            continue
        kind = fold(blueprint.get("type"))
        for field in COMPARED:
            if field in ("culture", "side", "type") and record["kind"] == "errata":
                continue
            ours, theirs = _record_value(field, record), _gemp_value(field, blueprint)
            if ours == theirs or (ours in (0, None, "") and theirs in (0, None, "")):
                continue
            if field in ("strength", "vitality") and kind in BONUS_TYPES:
                continue
            entry = {"gempId": blueprint_id, "wiki": record.get("wikiVersion") or record.get("wikiId"),
                     "field": field, "gemp": theirs, "wiki_value": ours}
            if record["kind"] == "errata" and field != "title" and record.get("wikiVersion"):
                unrecorded.append(entry)
            else:
                mismatches.append(entry)
    return mismatches, unrecorded


SECTIONS = [
    ("overridesApplied", "One-off Gemp ID exceptions applied (overrides.json)"),
    ("wrongGempId", "Wiki cards whose Gemp ID points at a different card"),
    ("wikiOnly", "Wiki Gemp IDs with no Gemp blueprint"),
    ("gempOnly", "Gemp blueprints with no wiki card (included from Gemp's data)"),
    ("wikiWithoutGempId", "Playable wiki cards without a Gemp ID"),
    ("pcErrataMissingOnWiki", "PC errata in Gemp with no PC revision on the wiki"),
    ("erratumNotRecordedOnWiki", "PC errata whose wiki revision doesn't record a value Gemp has"),
    ("valueMismatch", "Values that differ between the wiki and Gemp"),
    ("decipherErrataWithoutDate", "Decipher errata revisions without a release date"),
    ("revisionWithoutIssuer", "Revisions without an issuer"),
    ("imageMissing", "Images Gemp references that aren't on the CDN"),
    ("unusableGempId", "Wiki Gemp IDs that aren't in set_number form"),
]


def finish(report):
    """Sort entries for stable output and add counts."""
    out = {}
    for key, _ in SECTIONS:
        entries = report.get(key, [])
        out[key] = sorted(entries, key=lambda e: str(e) if not isinstance(e, dict) else (e.get("gempId") or e.get("wiki") or "", e.get("field", "")))
    out["counts"] = {key: len(out[key]) for key, _ in SECTIONS}
    return out


def markdown(report, version):
    lines = ["# Card data report", "",
             f"Wiki revision {version['sources']['wiki']['revid']}, Gemp `{version['sources']['gemp']['branch']}`, "
             f"CDN manifest `{(version['sources']['cdn']['manifestHash'] or '')[:12]}`.", "",
             "Where the wiki, Gemp and the CDN disagree. Fix the source (usually the wiki) and the next build picks it up.", ""]
    for key, title in SECTIONS:
        entries = report[key]
        lines.append(f"## {title} ({len(entries)})")
        lines.append("")
        if not entries:
            lines.append("None.")
        for entry in entries[:500]:
            if isinstance(entry, dict):
                lines.append("- " + ", ".join(f"{k}: `{v}`" for k, v in entry.items()))
            else:
                lines.append(f"- `{entry}`")
        if len(entries) > 500:
            lines.append(f"- … and {len(entries) - 500} more (see report.json)")
        lines.append("")
    return "\n".join(lines)
