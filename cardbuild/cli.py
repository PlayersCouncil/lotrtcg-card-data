"""Command line: `check` (have the sources changed?) and `build` (rebuild the dataset).

    python -m cardbuild check [--force] [--github-output FILE]
    python -m cardbuild build --gemp PATH [--wiki-cache DIR] [--manifest FILE]
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import sys

from . import assemble, cdn, gemp, report, wiki

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SCHEMA_VERSION = 1


def load_json(path, default=None):
    path = pathlib.Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def current_sources(config, wiki_client, manifest=None, gemp_sha=None):
    token = os.environ.get("GITHUB_TOKEN")
    if gemp_sha:
        # Offline: the caller knows which Gemp commit it checked out
        commits = {path: gemp_sha for path in config["gemp"]["watchPaths"]}
    else:
        commits = {path: gemp.latest_commit(config["gemp"]["repo"], config["gemp"]["branch"], path, token)
                   for path in config["gemp"]["watchPaths"]}
    if manifest is None:
        manifest = cdn.fetch_manifest(config["cdn"]["manifest"], config["wiki"]["userAgent"])
    return {
        "wiki": wiki_client.latest_revision(config["wiki"]["watchNamespaces"]),
        "gemp": {"repo": config["gemp"]["repo"], "branch": config["gemp"]["branch"], "commits": commits},
        "cdn": {"manifestHash": manifest.get("hash")},
    }, manifest


def sources_key(sources):
    return {
        "wiki": sources["wiki"]["revid"],
        "gemp": [sources["gemp"]["repo"], sources["gemp"]["branch"], sorted(sources["gemp"]["commits"].items())],
        "cdn": sources["cdn"]["manifestHash"],
    }


def make_wiki(config):
    return wiki.Wiki(config["wiki"]["api"], config["wiki"]["delaySeconds"], config["wiki"]["userAgent"])


def cmd_check(args):
    config = load_json(ROOT / "config.json")
    sources, _ = current_sources(config, make_wiki(config), gemp_sha=args.gemp_sha)
    previous = load_json(DATA / "version.json", {})
    changed = args.force or "sources" not in previous or sources_key(previous["sources"]) != sources_key(sources)
    print(json.dumps({"changed": changed, "sources": sources}, indent=1))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"changed={'true' if changed else 'false'}\n")
            handle.write(f"wiki_revid={sources['wiki']['revid']}\n")
    return 0


def cmd_build(args):
    config = load_json(ROOT / "config.json")
    wiki_client = make_wiki(config)
    manifest = load_json(args.manifest) if args.manifest else None
    sources, manifest = current_sources(config, wiki_client, manifest, gemp_sha=args.gemp_sha)

    # The wiki pull is the slow part; reuse it when the wiki hasn't changed (the workflow caches this folder)
    cache_file = pathlib.Path(args.wiki_cache) / f"wiki-{sources['wiki']['revid']}.json" if args.wiki_cache else None
    pulled = load_json(cache_file) if cache_file else None
    if pulled is None:
        print("pulling the wiki (paced, a few minutes)...", file=sys.stderr)
        pulled = wiki_client.pull()
        if cache_file:
            dump(cache_file, pulled)

    gemp_root = pathlib.Path(args.gemp)
    blueprints = gemp.load_blueprints(gemp_root / config["gemp"]["cardsDir"])
    mapping = gemp.load_mapping(gemp_root / config["gemp"]["mappingFile"])
    images = gemp.ImageMaps(gemp_root / config["gemp"]["jsDir"])
    cdn_index = cdn.Cdn(manifest, config["cdn"]["base"], config["cdn"]["oldImageHost"], config["cdn"]["cardsPrefix"], config["gemp"]["publicBase"])

    build = assemble.Build(config, pulled, blueprints, mapping, images, cdn_index,
                           load_json(ROOT / "overrides.json", {}), load_json(ROOT / "errata-batches.json", {}).get("names", {}))
    records, batches = build.run()
    overrides = load_json(ROOT / "overrides.json", {})
    build.report.update(report.compare(records, blueprints, overrides.get("acknowledged", [])))
    final_report = report.finish(build.report)

    # Write the data, then work out whether it changed
    out = pathlib.Path(args.out) if args.out else DATA
    texts = []
    by_set = {}
    for record in records.values():
        by_set.setdefault(record["set"], []).append(record)
    existing = {p.name for p in (out / "cards").glob("*.json")} if (out / "cards").exists() else set()
    written = set()
    for set_number in sorted(by_set, key=int):
        name = f"{set_number}.json"
        texts.append(dump(out / "cards" / name, {"set": set_number, "cards": sorted(by_set[set_number], key=lambda r: r["number"])}))
        written.add(name)
    for stale in existing - written:
        (out / "cards" / stale).unlink()
    texts.append(dump(out / "sets.json", assemble.build_sets(pulled["sets"], records)))
    texts.append(dump(out / "errata-batches.json", batches))
    texts.append(dump(out / "report.json", final_report))
    content_hash = hashlib.sha256("".join(texts).encode("utf-8")).hexdigest()

    previous = load_json(out / "version.json", {})
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    version = {
        "schemaVersion": SCHEMA_VERSION,
        "contentHash": content_hash,
        "builtAt": previous.get("builtAt") if previous.get("contentHash") == content_hash else now,
        "sources": sources,
        "counts": {"cards": sum(1 for r in records.values() if r["kind"] == "card"),
                   "errata": sum(1 for r in records.values() if r["kind"] == "errata"),
                   "sets": len(by_set), "errataBatches": len(batches)},
    }
    dump(out / "version.json", version)
    (out / "report.md").write_text(report.markdown(final_report, version), encoding="utf-8")
    print(json.dumps({"contentChanged": previous.get("contentHash") != content_hash, **version["counts"],
                      "report": final_report["counts"]}, indent=1))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cardbuild")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="compare the sources with data/version.json")
    check.add_argument("--force", action="store_true")
    check.add_argument("--github-output")
    check.add_argument("--gemp-sha", help="use this Gemp commit instead of asking GitHub")
    build = sub.add_parser("build", help="rebuild data/")
    build.add_argument("--gemp", required=True, help="path to a Gemp checkout")
    build.add_argument("--wiki-cache", help="folder to keep the raw wiki pull in, keyed by wiki revision")
    build.add_argument("--manifest", help="use this CDN manifest file instead of fetching it")
    build.add_argument("--out", help="output folder (default: data/)")
    build.add_argument("--gemp-sha", help="the Gemp commit checked out at --gemp, instead of asking GitHub")
    args = parser.parse_args(argv)
    return {"check": cmd_check, "build": cmd_build}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
