# LOTR TCG card data (lotrtcg-card-data)

Every card of the Lord of the Rings Trading Card Game as JSON, built from the [Players Council wiki](https://wiki.lotrtcgpc.net) and [Gemp](https://github.com/PlayersCouncil/gemp-lotr). Used by Red Book (the PC deck site) and anything else that needs card data.

**Nobody edits `data/` by hand.** It's rebuilt from its sources:

| Source | Provides |
|---|---|
| The wiki (Cargo tables `Cards`, `CardReleases`, `CardSets`) | Card facts, game text, lore, every revision with issuer and release date, every language |
| Gemp (`config.json` → `gemp.branch`) | Which blueprint IDs exist, the alternate-ID mapping (`blueprintMapping.txt`), and the images Gemp shows (its client's image maps) |
| The CDN file list (`files.lotrtcgpc.net/_dirindex/manifest.json`) | Which images exist, and the files for older revisions |

To fix a card, fix the wiki (or Gemp); the next build picks it up. `data/report.md` lists where the sources disagree.

## Data

| File | Contents |
|---|---|
| `data/cards/*.json` | One file per Gemp set: `01.json` for Decipher sets, `E01.json` for the PC errata of set 1 (Gemp set 51), `V01.json` for V-set 1 (Gemp set 101). `sets.json` gives each set's file. Schema: `schema/card-set.schema.json` |
| `data/sets.json` | Set names, wiki set IDs, release dates and data file; PC errata sets (50–69) named after the set they errata |
| `data/errata-batches.json` | Errata batches (issuer + release date), with names from `errata-batches.json` where given |
| `data/version.json` | What the data was built from (wiki revision, Gemp commits, CDN manifest hash), a content hash, counts |
| `data/report.json`, `data/report.md` | Where the wiki, Gemp and the CDN disagree |

A card record is keyed by its **Gemp base blueprint ID**:

- `kind: "card"` is a Decipher or V-set card. Its fields are the card as Decipher left it: revision 0 plus Decipher's own errata. V-set cards include their PC revisions (they're PC cards).
- `kind: "errata"` is a PC errata blueprint (`51_50`), `errataOf` the original (`1_50`), with the PC revisions applied. The original carries `errataId`.
- `versions` lists the English revisions in order. A revision's `fields` are what the wiki records on that revision row; anything not listed is unchanged from the revision before.
  - A revision that changes the card type carries `type`; allies and sites carry `homeSites` (`["2T", "8T"]`).
  - A revision that **removes** a printed value gives it explicitly as "none": `"0"` for a stat modifier (`strengthMod: "0"`), `"None"` for `signet`, `block` or `arrowDirection`. The card's own fields show that as `null`.
- Companions with no printed resistance have resistance 6 (how they're ruled in post-Shadows play); the wiki stores that 6.
- `translations` are printings in other languages, with only the fields that differ from English.
- `alternates` are the Gemp IDs mapped to this card (promos, alternate images, reprints); `printings` are the wiki's other English printings of it.
- `image` is what Gemp shows today, on `cdn.lotrtcgpc.net` (Decipher errata images Gemp keeps itself are on `play.lotrtcgpc.net`).
- `source` is `wiki`, `wiki+gemp` (a PC erratum the wiki has no revision for yet: stats from Gemp) or `gemp` (no wiki card at all).

Pin a commit or tag rather than reading `main` if a consumer needs stable data.

## Building

The scheduled workflow (`.github/workflows/build.yml`) runs daily:

1. **Check** (three small requests): the wiki's newest revision in the Data, Template and Module namespaces, Gemp's latest commits on the card paths, and the CDN manifest's hash. If they match `data/version.json`, it stops there.
2. **Build** only when something changed: a sparse checkout of Gemp's card files and image maps, the wiki pull (paced at one request every 2 seconds, since the wiki rate-limits; cached by wiki revision), then the data and the report.
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

## Exceptions

`overrides.json` holds one-off Gemp ID fixes the wiki can't express. Each rule must match exactly one English wiki card or the build fails, so a rule never silently stops applying. Today there's one: Soldier's Cache, which the wiki records as 18_59 and Gemp keeps as 17_35.

`overrides.json` → `acknowledged` lists known differences between the wiki and Gemp that aren't errors (Gemp's own version labels, for instance). Each is `{gempId, field, note}`; the report moves matching entries to its "acknowledged" section instead of listing them as mismatches.

## The report

`data/report.md` compares every value the wiki and Gemp both describe: title, subtitle, uniqueness, card type, culture, side, twilight or shadow number, strength, vitality and resistance, ring-bearer, signet, site number and home sites, block, arrow direction, and the printed bonuses on possessions, artifacts, conditions and followers. It also lists Gemp keywords, races, item classes and event phases the wiki shows nowhere, game text whose numbers differ, and wiki game text with paragraphs run together or markup left in it. An erratum's values are compared with Gemp's errata blueprint; a difference there means the wiki's revision doesn't record what the erratum changed.
