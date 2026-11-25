"""The build against small fixtures (tests/fixtures): no network."""
import copy
import json
import pathlib

import pytest

from cardbuild import assemble, cdn, gemp, report

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CONFIG = {"sets": {"cards": [[0, 19], [100, 149]], "errata": [[50, 69]]}}
TREE = {"prefix": "wiki/", "sizes": {"1x": "original", "2x": "double", "4x": "huge"}}
CDN = "https://cdn.lotrtcgpc.net/"
OVERRIDES = {"gempIds": [{"match": {"title": "Soldier's Cache"}, "gempId": "17_35"}]}


def run(overrides=OVERRIDES):
    wiki = json.loads((FIXTURES / "wiki.json").read_text(encoding="utf-8"))
    blueprints = gemp.load_blueprints(FIXTURES / "gemp" / "cards")
    mapping = gemp.load_mapping(FIXTURES / "gemp" / "blueprintMapping.txt")
    index = cdn.Cdn(json.loads((FIXTURES / "manifest.json").read_text()), CDN, TREE)
    build = assemble.Build(CONFIG, wiki, blueprints, mapping, index, overrides, {"pc-2024-12-06": "2024 Yuletide"})
    records, batches = build.run()
    return build, records, batches, blueprints


@pytest.fixture(scope="module")
def built():
    return run()


def test_decipher_card_is_the_original_with_decipher_errata_only(built):
    _, records, _, _ = built
    legolas = records["1_50"]
    assert legolas["kind"] == "card"
    assert legolas["gameText"] == "Archer."  # the PC revision belongs to 51_50, not here
    assert legolas["errataId"] == "51_50"
    axe = records["1_3"]
    assert axe["gameText"] == "Decipher errata text."  # Decipher's own errata does apply


def test_errata_blueprint_layers_the_pc_revision(built):
    _, records, _, _ = built
    errata = records["51_50"]
    assert errata["kind"] == "errata" and errata["errataOf"] == "1_50"
    assert errata["gameText"] == "Archer. Errata."
    assert errata["twilight"] == 2  # blank on the revision row: inherited from revision 0
    assert errata["wikiVersion"] == "LOTR-EN01S050.1"


def test_versions_and_batches(built):
    _, records, batches, _ = built
    versions = records["1_50"]["versions"]
    assert [v["revision"] for v in versions] == [0, 1]
    assert versions[1]["issuer"] == "Player's Council" and versions[1]["batch"] == "pc-2024-12-06"
    assert {b["id"]: b["name"] for b in batches} == {"decipher-2001-11-20": None, "pc-2024-12-06": "2024 Yuletide"}


EN01 = CDN + "wiki/{}/EN/01/LOTR-EN01S050.{}"


def test_images_in_every_size_the_tree_has(built):
    _, records, _, _ = built
    base, revision = records["1_50"]["versions"]
    assert base["images"] == {"1x": EN01.format("original", "0_card.jpg"), "2x": EN01.format("double", "0_card.jpg"),
                              "4x": EN01.format("huge", "0_card.jpg"), "portrait": EN01.format("original", "0_portrait.jpg")}
    # 1x and 4x only; the portrait the revision repeats is the base's, so it isn't repeated here
    assert revision["images"] == {"1x": EN01.format("original", "1_card.jpg"), "4x": EN01.format("huge", "1_card.jpg")}
    # 1x only; the portrait the wiki names isn't in the tree
    assert records["17_35"]["images"] == {"1x": CDN + "wiki/original/EN/18/LOTR-EN18S058.0_card.jpg"}


def test_a_record_shows_the_images_of_the_version_it_describes(built):
    _, records, _, _ = built
    # The card as Decipher left it: revision 0
    assert records["1_50"]["images"] == records["1_50"]["versions"][0]["images"]
    # The PC erratum: revision 1, with the base version's portrait in effect
    assert records["51_50"]["images"] == {"1x": EN01.format("original", "1_card.jpg"), "4x": EN01.format("huge", "1_card.jpg"),
                                          "portrait": EN01.format("original", "0_portrait.jpg")}


def test_images_left_out_when_the_tree_has_no_file(built):
    _, records, _, _ = built
    assert "images" not in records["1_3"]
    assert all("images" not in v for v in records["1_3"]["versions"])
    assert "images" not in records["1_99"]  # from Gemp only
    de, fr = records["1_50"]["translations"]
    assert de["images"] == {"1x": CDN + "wiki/original/DE/01/LOTR-DE01S050.0_card.jpg"}
    assert fr["language"] == "FR" and "images" not in fr


def test_alt_has_its_own_images_and_portrait_override(built):
    _, records, _, _ = built
    alt = records["1_50"]["alts"][0]
    assert alt["images"] == {"1x": CDN + "wiki/original/EN/00/LOTR-EN00S013.0_card.jpg",
                             "portrait": CDN + "wiki/original/EN/00/LOTR-EN00S013.0_portrait.jpg"}


def test_only_an_overriding_portrait_gives_a_variant_images():
    build = assemble.Build(CONFIG, {}, {}, {}, cdn.Cdn(json.loads((FIXTURES / "manifest.json").read_text()), CDN, TREE), {}, {})
    row = {"ImageFilename": "", "PortraitFilename": "LOTR-EN00S013.0_portrait.jpg"}
    assert build._images(row, "LOTR-EN01S050.0_portrait.jpg") == {"portrait": CDN + "wiki/original/EN/00/LOTR-EN00S013.0_portrait.jpg"}
    assert build._images(row, "LOTR-EN00S013.0_portrait.jpg") is None


def test_no_image_report(built):
    build, _, _, _ = built
    entries = build.report["noImage"]
    assert {"gempId": "1_3", "wikiId": "LOTR-EN01S003.1", "file": "LOTR-EN01S003.1_card.jpg", "what": "card"} in entries
    assert {"gempId": "1_3", "wikiId": "LOTR-EN01S003.0", "file": None, "what": "version"} in entries
    assert {"gempId": "1_3", "wikiId": "LOTR-EN01S003.1", "file": "LOTR-EN01S003.1_card.jpg", "what": "version"} in entries
    assert {"gempId": "1_99", "wikiId": None, "file": None, "what": "card"} in entries
    # English only: the French printing has no file in the tree but isn't listed
    assert not any(e["wikiId"].startswith("LOTR-FR") for e in entries if e["wikiId"])
    assert not any(e["gempId"] in ("1_50", "51_50", "17_35") for e in entries)
    assert "noImage" in dict(report.SECTIONS)


def tree(*paths):
    """A manifest holding these file paths."""
    root = {}
    for path in paths:
        node = root
        *folders, name = path.split("/")
        for folder in folders:
            node = node.setdefault("d", {}).setdefault(folder, {})
        node.setdefault("f", []).append([name, 1, 1])
    return {"hash": "x", "root": root}


def test_images_are_found_by_name_in_their_size_folder_only():
    index = cdn.Cdn(tree("wiki/huge/EN/01/a.jpg", "wiki/other/b.jpg", "cards/c.jpg", "wiki/original/EN/01/d.jpg"), CDN, TREE)
    assert index.url("4x", "a.jpg") == CDN + "wiki/huge/EN/01/a.jpg"
    assert index.url("1x", "a.jpg") is None
    assert index.url("1x", "b.jpg") is None and index.url("1x", "c.jpg") is None
    assert index.url("1x", "d.jpg") == CDN + "wiki/original/EN/01/d.jpg"
    assert index.url("1x", None) is None


def test_a_name_twice_in_one_size_folder_fails():
    cdn.Cdn(tree("wiki/original/EN/01/a.jpg", "wiki/huge/EN/01/a.jpg"), CDN, TREE)  # different sizes: fine
    with pytest.raises(RuntimeError, match="a.jpg is in wiki/original/ twice"):
        cdn.Cdn(tree("wiki/original/EN/01/a.jpg", "wiki/original/DE/01/a.jpg"), CDN, TREE)


def test_reprints_and_alts(built):
    _, records, _, _ = built
    assert records["1_50"]["reprints"] == ["0_13"]
    assert records["1_50"]["alts"][0]["wikiId"] == "LOTR-EN00S013.0"
    assert records["1_50"]["alts"][0]["gempId"] == "0_13"
    assert "0_13" not in records  # an alternate is listed on its base, not as its own record
    assert records["1_50"]["translations"][0]["language"] == "DE"
    for record in records.values():
        assert not {"image", "wikiImage", "alternates", "printings"} & set(record)
        assert not any({"image", "wikiImage"} & set(v) for v in record.get("versions", []) + record.get("translations", []))


def test_built_records_match_the_schema(built):
    jsonschema = pytest.importorskip("jsonschema")
    _, records, _, _ = built
    schema = json.loads((FIXTURES.parent.parent / "schema" / "card-set.schema.json").read_text(encoding="utf-8"))
    for set_number in {r["set"] for r in records.values()}:
        jsonschema.validate({"set": set_number, "cards": [r for r in records.values() if r["set"] == set_number]}, schema)


def test_wrong_gemp_id_is_reported_not_used(built):
    build, records, _, _ = built
    assert records["1_3"]["wikiId"] == "LOTR-EN01S003.0"
    assert any(e["wiki"] == "LOTR-EN01A003.0" for e in build.report["wrongGempId"])


def test_gemp_only_card_comes_from_gemp(built):
    build, records, _, _ = built
    assert records["1_99"]["source"] == "gemp"
    assert records["1_99"]["title"] == "Gemp Only Card"
    assert {"gempId": "1_99", "title": "Gemp Only Card"} in build.report["gempOnly"]


def test_override_maps_soldiers_cache(built):
    build, records, _, _ = built
    assert records["17_35"]["wikiId"] == "LOTR-EN18S058.0"
    assert "18_58" not in records  # Gemp maps it to 17_35
    assert build.report["overridesApplied"] == [{"wiki": "LOTR-EN18S058.0", "wikiGempId": "18_59", "gempId": "17_35"}]


def test_override_that_matches_nothing_fails_the_build():
    with pytest.raises(RuntimeError, match="matched 0"):
        run({"gempIds": [{"match": {"title": "No Such Card"}, "gempId": "1_1"}]})


def test_wiki_card_without_gemp_id_is_reported(built):
    build, _, _, _ = built
    assert {"wiki": "LOTR-EN01S900.0", "title": "No Gemp Id"} in build.report["wikiWithoutGempId"]


def test_report_compares_values(built):
    _, records, _, blueprints = built
    records = copy.deepcopy(records)
    assert dict(report.compare(records, blueprints)) == {}
    records["1_50"]["strength"] = 7
    found = report.compare(records, blueprints)
    assert found["valueMismatch"] == [{"gempId": "1_50", "wiki": "LOTR-EN01S050.0", "title": "Legolas, Greenleaf",
                                       "field": "strength", "gemp": 6, "wiki_value": 7}]


def test_report_compares_every_field_both_sources_have(built):
    _, records, _, blueprints = built
    records, blueprints = copy.deepcopy(records), copy.deepcopy(blueprints)
    records["1_50"].update(unique=False, canBearRing=False, signet="None")
    blueprints["1_50"].update(canStartWithRing=True, resistance=7, signet="Aragorn", keywords=["Archer", "Ambush 2"])
    records["1_50"]["gameText"] = "Archer. Ambush (2)."
    fields = {e["field"] for e in report.compare(records, blueprints)["valueMismatch"]}
    assert fields == {"unique", "canBearRing", "resistance", "signet"}
    # "None" and blank are the same; keywords match however the wiki spells their number
    records["1_50"].update(unique=True, canBearRing=True, resistance=7, signet="Aragorn")
    assert dict(report.compare(records, blueprints)) == {}
    blueprints["1_50"]["keywords"] = ["Fierce"]
    assert [e["gemp"] for e in report.compare(records, blueprints)["keywordNotOnWiki"]] == ["Fierce"]


def test_report_errata_card_type_is_compared(built):
    _, records, _, blueprints = built
    records, blueprints = copy.deepcopy(records), copy.deepcopy(blueprints)
    blueprints["51_50"]["type"] = "Ally"
    assert [e["field"] for e in report.compare(records, blueprints)["erratumNotRecordedOnWiki"]] == ["type"]


def test_report_acknowledged_differences_are_set_aside(built):
    _, records, _, blueprints = built
    records = copy.deepcopy(records)
    records["1_50"]["strength"] = 7
    found = report.compare(records, blueprints, [{"gempId": "1_50", "field": "strength", "note": "test"}])
    assert "valueMismatch" not in found and found["acknowledged"][0]["field"] == "strength"


def test_report_text_hygiene(built):
    _, records, _, blueprints = built
    records = copy.deepcopy(records)
    records["1_50"]["versions"][0]["fields"]["gameText"] = "Ring-bound.Frodo is strength +1."
    records["1_3"]["versions"][0]["fields"]["gameText"] = "Spell.\\Exert Gandalf."
    assert {e["wiki"] for e in report.compare(records, blueprints)["textHygiene"]} == {"LOTR-EN01S050.0", "LOTR-EN01S003.0"}


def test_set_file_names():
    assert [assemble.set_file(n) for n in (0, 1, 19, 51, 69, 100, 101, "103")] == [
        "00.json", "01.json", "19.json", "E01.json", "E19.json", "V00.json", "V01.json", "V03.json"]


def test_report_home_sites():
    assert report._homes(["3"]) == report._homes(["3F"]) == ["3"]
    assert report._homes(["2T", "8T"]) == ["2T", "8T"]


def test_revision_changes_card_type_and_removes_values():
    versions = [
        {"revision": 0, "issuer": None, "fields": {"type": "Event", "strengthMod": "+2", "signet": "None", "homeSites": ["2T", "8T"]}},
        {"revision": 1, "issuer": "Player's Council", "fields": {"type": "Condition", "strengthMod": "0"}},
    ]
    current, last = assemble.Build.layer(versions, {"Decipher", "Player's Council"})
    assert current == {"type": "Condition", "strengthMod": None, "signet": None, "homeSites": ["2T", "8T"]}
    assert last["revision"] == 1
    decipher_only, _ = assemble.Build.layer(versions, {"Decipher"})
    assert decipher_only["type"] == "Event" and decipher_only["strengthMod"] == "+2"
    assert assemble.to_value("homeSites", "2T,8T") == ["2T", "8T"]


def test_typo_in_title_still_links_the_card():
    assert assemble.same_title("Ruinous Hail", "Ruinous Hall")
    assert not assemble.same_title("Celeborn", "Arod")
