"""The build against small fixtures (tests/fixtures): no network."""
import copy
import json
import pathlib

import pytest

from cardbuild import assemble, cdn, gemp, report

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CONFIG = {"sets": {"cards": [[0, 19], [100, 149]], "errata": [[50, 69]]}}
OVERRIDES = {"gempIds": [{"match": {"title": "Soldier's Cache"}, "gempId": "17_35"}]}


def run(overrides=OVERRIDES):
    wiki = json.loads((FIXTURES / "wiki.json").read_text(encoding="utf-8"))
    blueprints = gemp.load_blueprints(FIXTURES / "gemp" / "cards")
    mapping = gemp.load_mapping(FIXTURES / "gemp" / "blueprintMapping.txt")
    images = gemp.ImageMaps(FIXTURES / "gemp" / "js")
    index = cdn.Cdn(json.loads((FIXTURES / "manifest.json").read_text()), "https://cdn.lotrtcgpc.net/",
                    "https://i.lotrtcgpc.net/", "cards/", "https://play.lotrtcgpc.net")
    build = assemble.Build(CONFIG, wiki, blueprints, mapping, images, index, overrides, {"pc-2024-12-06": "2024 Yuletide"})
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


def test_images(built):
    _, records, _, _ = built
    assert records["1_50"]["image"] == "https://cdn.lotrtcgpc.net/cards/decipher/LOTR01050.jpg"
    assert records["51_50"]["image"] == "https://cdn.lotrtcgpc.net/cards/errata/LOTR-EN01E050.1_card.jpg"
    # Decipher errata in Card.remadeErratas come from Gemp's own images folder
    assert records["1_3"]["image"] == "https://play.lotrtcgpc.net/gemp-lotr/images/erratas/LOTR01003.jpg"
    # An older PC revision's image is found on the CDN under its E-subset name, not the huge/ copy
    assert records["1_50"]["versions"][1]["image"] == "https://cdn.lotrtcgpc.net/cards/errata/LOTR-EN01E050.1_card.jpg"


def test_alternates_and_printings(built):
    _, records, _, _ = built
    assert records["1_50"]["alternates"] == ["0_13"]
    assert records["1_50"]["printings"][0]["wikiId"] == "LOTR-EN00S013.0"
    assert "0_13" not in records  # an alternate is listed on its base, not as its own record
    assert records["1_50"]["translations"][0]["language"] == "DE"


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


def test_masterworks_image_name():
    images = gemp.ImageMaps(FIXTURES / "gemp" / "js")
    assert images.decipher_original("12_195") == "https://i.lotrtcgpc.net/decipher/LOTR12O01.jpg"
    assert images.decipher_original("17_149") == "https://i.lotrtcgpc.net/decipher/LOTR17O01.jpg"
    assert images.decipher_original("4_7") == "https://i.lotrtcgpc.net/decipher/LOTR04007.jpg"


def test_commented_out_js_entries_are_ignored():
    images = gemp.ImageMaps(FIXTURES / "gemp" / "js")
    assert "51_1" not in images.pc and "51_50" in images.pc
