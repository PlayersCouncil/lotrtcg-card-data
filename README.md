# LOTR TCG card data (lotrtcg-card-data)

Every card of the Lord of the Rings Trading Card Game as JSON, built from the [Players Council wiki](https://wiki.lotrtcgpc.net) and [Gemp](https://github.com/PlayersCouncil/gemp-lotr). Used by Red Book (the PC deck site) and anything else that needs card data.

**Nobody edits `data/` by hand.** It's rebuilt from its sources:

| Source | Provides |
|---|---|
| The wiki (Cargo tables `Cards`, `CardReleases`, `CardSets`) | Card facts, game text, lore, every revision with issuer and release date, every language |
| Gemp (`config.json` → `gemp.branch`) | Which blueprint IDs exist, and the alternate-ID mapping (`blueprintMapping.txt`) |
| The CDN file list (`files.lotrtcgpc.net/_dirindex/manifest.json`) | Where each image the wiki names is in the CDN's image tree (`config.json` → `cdn.tree`), if it's there at all |
| `timeline/format-timeline.json` (committed; written by decipher-map's `ru_formats.py`) | The format timeline: the official formats, their micro-formats, the errata in force in each, and each one's nearest Gemp hall format |

To fix a card, fix the wiki (or Gemp); the next build picks it up. `data/report.md` lists where the sources disagree.

## Data

| File | Contents |
|---|---|
| `data/cards/*.json` | One file per Gemp set: `01.json` for Decipher sets, `E01.json` for the PC errata of set 1 (Gemp set 51), `V01.json` for V-set 1 (Gemp set 101). `sets.json` gives each set's file. Schema: `schema/card-set.schema.json` |
| `data/sets.json` | Set names, wiki set IDs, release dates and data file; PC errata sets (50–69) named after the set they errata |
| `data/errata-batches.json` | Errata batches (issuer + release date), with names from `errata-batches.json` where given |
| `data/version.json` | What the data was built from (wiki revision, Gemp commits, CDN manifest hash), a content hash, counts |
| `data/report.json`, `data/report.md` | Where the wiki, Gemp and the CDN disagree |
| `data/format-timeline.json` | The format timeline, copied from `timeline/` by the build after checking every card and revision it names against this build (problems are in the report's timeline section). Its schema: decipher-map's `notes/format-timeline-data.md` |

A card record is keyed by its **Gemp base blueprint ID**:

- `kind: "card"` is a Decipher or V-set card. Its fields are the card as Decipher left it: revision 0 plus Decipher's own errata. V-set cards include their PC revisions (they're PC cards).
- `kind: "errata"` is a PC errata blueprint (`51_50`), `errataOf` the original (`1_50`), with the PC revisions applied. The original carries `errataId`.
- `versions` lists the English revisions in order. A revision's `fields` are what the wiki records on that revision row; anything not listed is unchanged from the revision before.
  - A revision that changes the card type carries `type`; allies and sites carry `homeSites` (`["2T", "8T"]`).
  - A revision that **removes** a printed value gives it explicitly as "none": `"0"` for a stat modifier (`strengthMod: "0"`), `"None"` for `signet`, `block` or `arrowDirection`. The card's own fields show that as `null`.
- Companions with no printed resistance have resistance 6 (how they're ruled in post-Shadows play); the wiki stores that 6.
- `translations` are printings in other languages, with only the fields that differ from English.
- `reprints` are the Gemp IDs mapped to this card (promos, alternate images, reprints); `alts` are the wiki's other English printings of it.
- `images` are the card's image URLs on `cdn.lotrtcgpc.net`: `1x` (standard size), `2x` and `4x` (larger renders), `foil` (a scan of the foil printing) and `portrait`. Each is there only if the file is in the CDN's image tree (`wiki/original/`, `wiki/double/`, `wiki/huge/`), found by the file name the wiki gives; with none, `images` is left out.
  - A record's `images` are those of the version its fields describe, with the portrait in effect for that version.
  - Every version, translation and alt carries its own `images`. Revision 0 carries the card's portrait; the others carry a `portrait` only where theirs differs from it.
  - `foil` is found by file name: a foil scan has the clean image's name with only the subset letter changed (`S` to `F`, `O` to `G`; `config.json` → `cdn.tree.foilOf`). Where the wiki's row names the scan itself, as for Masterworks, `1x` is the clean image and the scan is `foil`.
- `wikiUrl` is the card's page on the wiki, taken from where the wiki stores the card's data (`Data:<page>/Data`), so it is the wiki's own page name. An erratum carries the page of the card it errata; an alt carries its own. Left out when there is no wiki card.
- `source` is `wiki`, `wiki+gemp` (a PC erratum the wiki has no revision for yet: stats from Gemp) or `gemp` (no wiki card at all).

Pin a commit or tag rather than reading `main` if a consumer needs stable data.

## Building

The scheduled workflow (`.github/workflows/build.yml`) runs daily:

1. **Check** (three small requests): the wiki's newest revision in the Data, Template and Module namespaces, Gemp's latest commits on the card paths, and the CDN manifest's hash. If they match `data/version.json`, it stops there.
2. **Build** only when something changed: a sparse checkout of Gemp's card files and blueprint mapping, the wiki pull (paced at one request every 2 seconds, since the wiki rate-limits; cached by wiki revision and by the fields the build asks for), then the data and the report.
3. **Commit** `data/` if the output changed.

Run it from the Actions tab (with "force" to rebuild regardless).

Locally:

```bash
pip install -r requirements-dev.txt
python -m cardbuild check
python -m cardbuild build --gemp /path/to/gemp-lotr --wiki-cache .cache/wiki
python -m pytest
```

`--gemp-sha` skips the GitHub API lookups when they aren't reachable; `--manifest` uses a saved CDN manifest.

## The format timeline

`timeline/format-timeline.json` is the one input committed by hand: decipher-map builds it from the Decipher archive,
the rules documents and this card data, and it is copied in when it changes. The build copies it to
`data/format-timeline.json` unchanged, and lists in the report any card it names that the build doesn't have, or any
revision a card doesn't have. Its hash is one of the sources in `data/version.json`, so committing a new timeline makes
the next scheduled check rebuild. Remove the file and the build removes the copy.

## Exceptions

`overrides.json` holds one-off Gemp ID fixes the wiki can't express. Each rule must match exactly one English wiki card or the build fails, so a rule never silently stops applying. Today there's one: Soldier's Cache, which the wiki records as 18_59 and Gemp keeps as 17_35.

`overrides.json` → `acknowledged` lists known differences between the wiki and Gemp that aren't errors (Gemp's own version labels, for instance). Each is `{gempId, field, note}`; the report moves matching entries to its "acknowledged" section instead of listing them as mismatches.

## The report

`data/report.md` compares every value the wiki and Gemp both describe: title, subtitle, uniqueness, card type, culture, side, twilight or shadow number, strength, vitality and resistance, ring-bearer, signet, site number and home sites, block, arrow direction, and the printed bonuses on possessions, artifacts, conditions and followers. It also lists Gemp keywords, races, item classes and event phases the wiki shows nowhere, game text whose numbers differ, wiki game text with paragraphs run together or markup left in it, the English cards, versions and alternate printings with no image in the tree, and wiki cards whose data isn't stored on `Data:<card page>/Data`. An erratum's values are compared with Gemp's errata blueprint; a difference there means the wiki's revision doesn't record what the erratum changed.
