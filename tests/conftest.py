import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import generate_data  # noqa: E402
from semantic_layer import SemanticLayer, User  # noqa: E402


@pytest.fixture(scope="session")
def layer(tmp_path_factory):
    db = str(tmp_path_factory.mktemp("data") / "crm_demo.duckdb")
    generate_data.main(db)
    return SemanticLayer(db_path=db)


@pytest.fixture
def vp():
    return User("Regional VP")


@pytest.fixture
def ohio_tam():
    return User("Jordan Pike", "Ohio Valley")
