import pytest
from fastapi.testclient import TestClient
from api import app


class TestMetadataOpenAPI:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_openapi_has_metadata_values(self, client, db_manager):
        r = client.get("/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        assert "/metadata/values" in paths, "Missing /metadata/values in OpenAPI"
        assert "/metadata/keys" in paths, "Missing /metadata/keys in OpenAPI"
