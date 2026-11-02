from cardbuild.assemble import to_value
from cardbuild.report import _gemp_value


def test_gemp_title_suffix_for_same_named_cards_is_ignored():
    # Gemp names the second of two same-named cards "Orc Pursuer(2)" (Ketura, 2026-11-01)
    assert _gemp_value("title", {"title": "Orc Pursuer(2)"}) == _gemp_value("title", {"title": "Orc Pursuer"})
    assert _gemp_value("title", {"title": "White Hand Attacker (2)"}) == _gemp_value("title", {"title": "White Hand Attacker"})


def test_wiki_none_strings_are_empty():
    assert to_value("signet", "None") is None
    assert to_value("block", "None") is None
    assert to_value("signet", "Frodo") == "Frodo"
    assert to_value("gameText", "None") == "None"
