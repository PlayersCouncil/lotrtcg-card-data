"""The command line against fixtures: the image-tree guard and the schema-version rebuild trigger. No network."""
import argparse
import json
import pathlib

import pytest

from cardbuild import cli, wiki

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SOURCES = {"wiki": {"revid": 1, "timestamp": None}, "gemp": {"repo": "r", "branch": "b", "commits": {}},
           "cdn": {"manifestHash": "x"}, "timeline": {"sha256": None}}


class NoWiki:
    def latest_revision(self, namespaces):
        return {"revid": 1, "timestamp": None}

    def pull(self):
        raise AssertionError("the build went on to pull the wiki")


def test_build_without_the_image_tree_fails_and_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_wiki", lambda config: NoWiki())
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"hash": "x", "root": {"d": {"cards": {"f": [["LOTR01050.jpg", 1, 1]]}}}}))
    out = tmp_path / "out"
    args = argparse.Namespace(gemp=str(FIXTURES / "gemp"), wiki_cache=None, manifest=str(manifest), out=str(out), gemp_sha="abc")
    assert cli.cmd_build(args) != 0
    assert not out.exists()
    assert "wiki/original/" in capsys.readouterr().err


@pytest.mark.parametrize("schema_version, changed", [(cli.SCHEMA_VERSION, False), (cli.SCHEMA_VERSION - 1, True)])
def test_check_rebuilds_when_the_schema_version_changes(tmp_path, monkeypatch, capsys, schema_version, changed):
    (tmp_path / "version.json").write_text(json.dumps({"schemaVersion": schema_version, "sources": SOURCES}))
    monkeypatch.setattr(cli, "DATA", tmp_path)
    monkeypatch.setattr(cli, "make_wiki", lambda config: NoWiki())
    monkeypatch.setattr(cli, "current_sources", lambda *a, **k: (SOURCES, None))
    assert cli.cmd_check(argparse.Namespace(force=False, github_output=None, gemp_sha=None)) == 0
    assert json.loads(capsys.readouterr().out)["changed"] is changed


def test_a_saved_pull_is_reused_only_for_the_same_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DATA", tmp_path)
    monkeypatch.setattr(cli, "make_wiki", lambda config: NoWiki())
    monkeypatch.setattr(cli, "current_sources", lambda *a, **k: (SOURCES, None))
    output = tmp_path / "github-output"
    cli.cmd_check(argparse.Namespace(force=False, github_output=str(output), gemp_sha=None))
    name = wiki.cache_name(1)
    assert f"wiki_cache={name}\n" in output.read_text()
    monkeypatch.setattr(wiki, "CARD_FIELDS", wiki.CARD_FIELDS + ["Another"])
    assert wiki.cache_name(1) != name
