"""The published data matches the schema (skipped until data/ has been built with this code's schema version)."""
import json
import pathlib

import pytest

from cardbuild.cli import SCHEMA_VERSION

ROOT = pathlib.Path(__file__).resolve().parent.parent
jsonschema = pytest.importorskip("jsonschema")


def set_files():
    return sorted((ROOT / "data" / "cards").glob("*.json"))


def data_schema_version():
    path = ROOT / "data" / "version.json"
    return json.loads(path.read_text(encoding="utf-8")).get("schemaVersion") if path.exists() else None


@pytest.mark.skipif(not set_files(), reason="data/ not built")
@pytest.mark.skipif(data_schema_version() != SCHEMA_VERSION,
                    reason=f"data/ was built with schema version {data_schema_version()}, the code is at {SCHEMA_VERSION}: "
                           "the next build regenerates it")
def test_every_set_file_matches_the_schema():
    schema = json.loads((ROOT / "schema" / "card-set.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for path in set_files():
        errors = list(validator.iter_errors(json.loads(path.read_text(encoding="utf-8"))))
        assert not errors, f"{path.name}: {errors[0].message} at {list(errors[0].absolute_path)}"
