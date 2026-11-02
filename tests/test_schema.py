"""The published data matches the schema (skipped until data/ has been built)."""
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
jsonschema = pytest.importorskip("jsonschema")


def set_files():
    return sorted((ROOT / "data" / "cards").glob("*.json"))


@pytest.mark.skipif(not set_files(), reason="data/ not built")
def test_every_set_file_matches_the_schema():
    schema = json.loads((ROOT / "schema" / "card-set.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for path in set_files():
        errors = list(validator.iter_errors(json.loads(path.read_text(encoding="utf-8"))))
        assert not errors, f"{path.name}: {errors[0].message} at {list(errors[0].absolute_path)}"
