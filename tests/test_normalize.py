from cardbuild import assemble, report


def test_gemp_title_suffix_for_same_named_cards_is_ignored():
    # Gemp names the second of two same-named cards "Orc Pursuer(2)" (Ketura, 2026-11-01)
    record = {"kind": "card", "title": "Orc Pursuer"}
    for gemp_title in ("Orc Pursuer(2)", "Orc Pursuer (2)"):
        title = [c for c in report.field_checks(record, {"title": gemp_title}) if c[0] == "title"][0]
        assert title[1] == title[2]


def test_wiki_none_strings_are_empty():
    # The wiki writes "None" for an empty signet, site block or arrow; the card's fields show null.
    # On a revision row it means the erratum removed the value, so it has to survive until layering.
    assert assemble.to_value("signet", "None") == "None"
    versions = [{"revision": 0, "issuer": None, "fields": {"signet": "Frodo", "block": "None"}},
                {"revision": 1, "issuer": "Decipher", "fields": {"signet": "None"}}]
    current, _ = assemble.Build.layer(versions, {"Decipher"})
    assert current == {"signet": None, "block": None}
    assert assemble.to_value("gameText", "None") == "None"
