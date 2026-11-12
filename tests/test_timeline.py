"""The format timeline check (cardbuild.timeline): every card and revision it names must be in the build."""
from cardbuild import timeline

RECORDS = {
    "1_40": {"kind": "card", "versions": [{"revision": 0}, {"revision": 1}], "alternates": ["0_99"]},
    "1_55": {"kind": "card", "versions": [{"revision": 0}, {"revision": 1}, {"revision": 2}]},
}


def test_a_timeline_matching_the_build_has_no_problems():
    tl = {"events": [{"id": "pc-errata-2021-03-28", "kind": "pc-errata", "cards": [{"card": "1_40", "revision": 1}]},
                     {"id": "list-x", "kind": "list", "cards": ["1_55", "0_99"], "changes": [{"card": "1_55"}]}],
          "microformats": [{"key": "pc_movie@2021-03-28", "errata": {"decipher": [{"card": "1_55", "revision": 2}],
                                                                     "pc": [{"card": "1_40", "revision": 1}]},
                            "extraCards": [], "lists": {"pc xlist": {"cards": ["1_40"]}},
                            "delta": [{"card": "1_55", "micro": {"revision": 1}, "base": {"revision": 2}}]}]}
    assert timeline.check(tl, RECORDS) == []


def test_unknown_cards_and_revisions_are_reported_once():
    tl = {"events": [{"id": "errata-2002-09-03", "kind": "errata", "cards": [{"card": "1_40", "revision": 3},
                                                                             {"card": "9_999", "revision": 1}]}],
          "microformats": [{"key": "open@2002-11-13", "errata": {"decipher": [{"card": "1_40", "revision": 3}], "pc": []},
                            "extraCards": [{"card": "9_999"}], "lists": {}, "delta": []}]}
    problems = timeline.check(tl, RECORDS)
    assert {(p["gempId"], p["problem"]) for p in problems} == {("1_40", "no revision 3"), ("9_999", "no such card")}
    assert len(problems) == 2
