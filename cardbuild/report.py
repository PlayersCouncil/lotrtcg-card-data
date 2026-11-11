"""The mismatch report: where the wiki, Gemp and the CDN disagree.

Published with every build so the wiki (and Gemp) can be fixed; nothing here
blocks a build.
"""
import collections
import re

from .assemble import fold, letters

CULTURE_ALIASES = {"ringwraith": "wraith"}
CHARACTERS = {"companion", "minion", "ally"}
# Card types whose Gemp strength/vitality/resistance/site are printed bonuses (the wiki's ...Mod fields)
BONUS_HOLDERS = {"possession", "artifact", "condition", "follower"}
SKIPPED_TYPES = {"the one ring", "metasite"}
# Two paragraphs run together in the wiki's plain game text ("Ring-bound.Frodo"), or markup left in it
RUN_TOGETHER = re.compile(r"[a-z\)\]][.!:][A-Z\[]")
MARKUP = re.compile(r"\\|<br\s*/?>|</?[bi]>|''")


def _num(value):
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip().replace("+", ""))
    except (TypeError, ValueError):
        return None


def _list(value):
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]


def _empty(value):
    return value in (None, "", 0, []) or (isinstance(value, str) and letters(value) in ("", "none"))


def _same(ours, theirs):
    return ours == theirs or (_empty(ours) and _empty(theirs))


def _text(value):
    return fold(re.sub(r"<[^>]+>", " ", str(value or "")))


def _subtypes(record):
    return {letters(s) for s in re.split(r"[,•]", str(record.get("subtypes") or "")) if s.strip()}


def _homes(values):
    """Home sites as printed: "3" on a Fellowship-block ally is Gemp's "3F"."""
    out = []
    for value in values or []:
        match = re.match(r"\s*(\d+)\s*([A-Za-z]?)", str(value))
        if match:
            out.append(match.group(1) + ("" if match.group(2).upper() == "F" else match.group(2).upper()))
    return out


def _keyword_on_card(keyword, text):
    """Gemp's keyword ("Damage+1", "Ambush 3", "Hunter+2") as it reads in the wiki's game text."""
    word = fold(keyword).replace("_", " ")
    match = re.match(r"^([a-z -]+?)\s*\+?\s*(\d+)$", word)
    if match:
        return re.search(re.escape(match.group(1)) + r"\s*\(?\+?\s*" + match.group(2), text) is not None
    return word in text


def field_checks(record, blueprint):
    """(field, wiki value, Gemp value) for every value the two sources both describe."""
    kind = fold(blueprint.get("type"))
    checks = [
        ("title", letters(record.get("title")), letters(blueprint.get("title"))),  # letters only: Gemp's "Orc Pursuer(2)"
        ("subtitle", letters(record.get("subtitle")), letters(blueprint.get("subtitle"))),
        ("unique", bool(record.get("unique")), bool(blueprint.get("unique"))),
        ("type", letters(record.get("type")), letters(blueprint.get("type"))),
        ("canBearRing", bool(record.get("canBearRing")), bool(blueprint.get("canStartWithRing"))),
        ("signet", letters(record.get("signet")), letters(blueprint.get("signet"))),
    ]
    if record["kind"] == "card":
        culture = letters(record.get("culture"))
        checks += [("culture", CULTURE_ALIASES.get(culture, culture), letters(blueprint.get("culture"))),
                   ("side", letters(record.get("side")), letters(blueprint.get("side")))]
    if kind == "site":
        checks += [("shadowNumber", _num(record.get("shadowNumber")), _num(blueprint.get("twilight"))),
                   ("siteNumber", _num(record.get("siteNumber")), _num(blueprint.get("site"))),
                   ("arrowDirection", letters(record.get("arrowDirection")), letters(blueprint.get("direction")))]
        if blueprint.get("block"):
            checks.append(("block", letters(record.get("block")), letters(blueprint.get("block"))))
    else:
        checks.append(("twilight", _num(record.get("twilight")), _num(blueprint.get("twilight"))))
    if kind in CHARACTERS:
        checks += [(f, _num(record.get(f)), _num(blueprint.get(f))) for f in ("strength", "vitality", "resistance")]
        if kind == "minion":
            checks.append(("siteNumber", _num(record.get("siteNumber")), _num(blueprint.get("site"))))
        if kind == "ally" and blueprint.get("allyHome"):
            homes = [h for value in _list(blueprint["allyHome"]) for h in value.split(",")]
            checks.append(("homeSites", _homes(record.get("homeSites")), _homes(homes)))
    elif kind in BONUS_HOLDERS:
        for field, gemp_field in (("strengthMod", "strength"), ("vitalityMod", "vitality"),
                                  ("resistanceMod", "resistance"), ("siteNumberMod", "site")):
            checks.append((field, _num(record.get(field)), _num(blueprint.get(gemp_field))))
    return checks


def keyword_checks(record, blueprint):
    """Gemp's race, item class, keywords and event phase that the wiki shows nowhere (Subtypes or game text)."""
    subtypes, text = _subtypes(record), _text(record.get("gameText"))
    missing = []
    for field in ("race", "itemclass"):
        missing += [(field, v) for v in _list(blueprint.get(field)) if letters(v) not in subtypes]
    for keyword in _list(blueprint.get("keywords")) + _list(blueprint.get("keyword")):
        if letters(keyword) == "supportarea":
            if "supportarea" not in subtypes and "support area" not in text:
                missing.append(("keywords", keyword))
        elif not _keyword_on_card(keyword, text):
            missing.append(("keywords", keyword))
    for phase in _list(blueprint.get("timewords")) + _list(blueprint.get("timeword")):
        if fold(phase) not in text and letters(phase) not in subtypes:
            missing.append(("phase", phase))
    return missing


def _entry(record, field, ours, theirs):
    title = record.get("title") or ""
    if record.get("subtitle"):
        title += ", " + record["subtitle"]
    return {"gempId": record["id"], "wiki": record.get("wikiVersion") or record.get("wikiId"), "title": title,
            "field": field, "gemp": theirs, "wiki_value": ours}


def compare(records, blueprints, acknowledged=()):
    """Every value both sources describe. Returns {section: entries} for valueMismatch, erratumNotRecordedOnWiki,
    keywordNotOnWiki, gameTextNumbers, textHygiene and acknowledged (differences overrides.json says are known)."""
    known = {(a["gempId"], a["field"]) for a in acknowledged}
    out = collections.defaultdict(list)
    for blueprint_id, record in records.items():
        blueprint = blueprints.get(blueprint_id)
        if record.get("source") == "gemp" or blueprint is None or fold(blueprint.get("type")) in SKIPPED_TYPES:
            continue
        found = [("valueMismatch", _entry(record, field, ours, theirs))
                 for field, ours, theirs in field_checks(record, blueprint) if not _same(ours, theirs)]
        found += [("keywordNotOnWiki", _entry(record, field, record.get("subtypes"), value))
                  for field, value in keyword_checks(record, blueprint)]
        ours_text, theirs_text = _text(record.get("gameText")), _text(blueprint.get("gametext"))
        if ours_text and theirs_text and sorted(re.findall(r"\d+", ours_text)) != sorted(re.findall(r"\d+", theirs_text)):
            found.append(("gameTextNumbers", _entry(record, "gameText", record.get("gameText"), blueprint.get("gametext"))))
        for section, entry in found:
            if (blueprint_id, entry["field"]) in known:
                out["acknowledged"].append(entry)
            elif section == "valueMismatch" and record["kind"] == "errata" and entry["field"] != "title" and record.get("wikiVersion"):
                out["erratumNotRecordedOnWiki"].append(entry)
            else:
                out[section].append(entry)
    for record in records.values():
        for version in record.get("versions", []):
            text = version["fields"].get("gameText") or ""
            if RUN_TOGETHER.search(text) or MARKUP.search(text):
                out["textHygiene"].append({"wiki": version["wikiId"], "gameText": text})
    return out


SECTIONS = [
    ("overridesApplied", "One-off Gemp ID exceptions applied (overrides.json)"),
    ("wrongGempId", "Wiki cards whose Gemp ID points at a different card"),
    ("wikiOnly", "Wiki Gemp IDs with no Gemp blueprint"),
    ("gempOnly", "Gemp blueprints with no wiki card (included from Gemp's data)"),
    ("wikiWithoutGempId", "Playable wiki cards without a Gemp ID"),
    ("pcErrataMissingOnWiki", "PC errata in Gemp with no PC revision on the wiki"),
    ("erratumNotRecordedOnWiki", "PC errata whose wiki revision doesn't record a value Gemp has"),
    ("valueMismatch", "Values that differ between the wiki and Gemp"),
    ("keywordNotOnWiki", "Gemp race, item class, keywords or event phase the wiki shows nowhere"),
    ("gameTextNumbers", "Game text whose numbers differ between the wiki and Gemp (often only wording)"),
    ("textHygiene", "Wiki game text with paragraphs run together or markup left in"),
    ("decipherErrataWithoutDate", "Decipher errata revisions without a release date"),
    ("revisionWithoutIssuer", "Revisions without an issuer"),
    ("imageMissing", "Images Gemp references that aren't on the CDN"),
    ("unusableGempId", "Wiki Gemp IDs that aren't in set_number form"),
    ("acknowledged", "Known differences, acknowledged in overrides.json (not errors)"),
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
