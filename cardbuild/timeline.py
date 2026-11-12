"""The format timeline: copied into data/ with the cards, after checking every card and revision it names.

timeline/format-timeline.json is the input. decipher-map's ru_formats.py writes it (the official formats, their
micro-formats, the errata in force in each, and each micro-format's nearest Gemp hall format); it is committed here
by hand. The build copies it to data/format-timeline.json and lists in the report any card it names that this build
doesn't have, or any revision a card doesn't have, so a published timeline always matches the card data beside it.
Its hash counts as a source: committing a new timeline makes the next scheduled check rebuild.
"""
import hashlib
import pathlib

SOURCE = pathlib.Path("timeline") / "format-timeline.json"


def file_hash(path):
    """sha256 of the file with CRLF read as LF, so a Windows checkout (core.autocrlf) hashes as CI does."""
    path = pathlib.Path(path)
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() if path.exists() else None


def check(timeline, records):
    """Report entries for the cards and revisions the timeline names that aren't in the records."""
    alternates = {alt: rid for rid, r in records.items() for alt in r.get("alternates") or []}
    problems, seen = [], set()

    def card(cid, where, revision=None):
        rid = cid if cid in records else alternates.get(cid)
        if rid is None:
            problem = "no such card"
        elif revision is not None and revision not in {v["revision"] for v in records[rid].get("versions") or []}:
            problem = f"no revision {revision}"
        else:
            return
        key = (cid, problem)
        if key not in seen:
            seen.add(key)
            problems.append({"gempId": cid, "problem": problem, "where": where})

    for e in timeline.get("events", []):
        for c in e.get("cards") or []:
            if isinstance(c, str):
                card(c, e["id"])
            else:
                card(c["card"], e["id"], c.get("revision") if e["kind"] in ("errata", "pc-errata") else None)
        for c in e.get("changes") or []:
            card(c["card"], e["id"])
    for m in timeline.get("microformats", []):
        where = m.get("key") or m.get("id")
        for side in ("decipher", "pc"):
            for x in (m.get("errata") or {}).get(side, []):
                card(x["card"], where, x["revision"])
        for x in m.get("extraCards") or []:
            card(x["card"], where)
        for lst in (m.get("lists") or {}).values():
            for cid in lst.get("cards") or []:
                card(cid, where)
        for d in m.get("delta") or []:
            card(d["card"], where, d["micro"]["revision"])
            card(d["card"], where, d["base"]["revision"])
    return problems
