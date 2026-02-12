"""Unit tests for the management vars module (async_provisioning_service.services.management_vars)."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

import async_provisioning_service.services.management_vars as mgmt_module
from async_provisioning_service.services.management_vars import (
    load_management_vars,
    get_golden_image_credentials,
    GoldenImageCredentials,
)


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

VALID_YAML = """\
root_ssh_filename: id_rsa_golden
root_ssh_password: s3cret-passw0rd
golden_image_name: ubuntu-golden-v3
gcs_bucket: my-bucket
gcs_project: my-project
"""

PARTIAL_YAML = """\
golden_image_name: ubuntu-golden-v3
gcs_bucket: my-bucket
"""

INVALID_YAML = """\
root_ssh_filename: id_rsa_golden
  bad_indent: this_is_broken
    - not: valid
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset the module-level _cached_vars before every test."""
    mgmt_module._cached_vars = None
    yield
    mgmt_module._cached_vars = None


# ---------------------------------------------------------------------------
# load_management_vars
# ---------------------------------------------------------------------------


class TestLoadManagementVars:
    def test_load_management_vars_success(self):
        """Valid YAML file is parsed and returned as a dict."""
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.return_value = VALID_YAML

        with patch.object(
            type(mgmt_module.settings),
            "management_vars_path",
            new_callable=lambda: property(lambda self: mock_path),
        ):
            result = load_management_vars()

        assert result == {
            "root_ssh_filename": "id_rsa_golden",
            "root_ssh_password": "s3cret-passw0rd",
            "golden_image_name": "ubuntu-golden-v3",
            "gcs_bucket": "my-bucket",
            "gcs_project": "my-project",
        }
        mock_path.read_text.assert_called_once_with(encoding="utf-8")

    def test_load_management_vars_file_not_found(self):
        """Missing file returns empty dict without raising."""
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.side_effect = FileNotFoundError("no such file")

        with patch.object(
            type(mgmt_module.settings),
            "management_vars_path",
            new_callable=lambda: property(lambda self: mock_path),
        ):
            result = load_management_vars()

        assert result == {}

    def test_load_management_vars_invalid_yaml(self):
        """Malformed YAML returns empty dict without raising."""
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.return_value = INVALID_YAML

        with patch.object(
            type(mgmt_module.settings),
            "management_vars_path",
            new_callable=lambda: property(lambda self: mock_path),
        ):
            result = load_management_vars()

        assert result == {}

    def test_load_management_vars_caching(self):
        """Second call returns cached result -- read_text is only called once."""
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.return_value = VALID_YAML

        with patch.object(
            type(mgmt_module.settings),
            "management_vars_path",
            new_callable=lambda: property(lambda self: mock_path),
        ):
            result1 = load_management_vars()
            result2 = load_management_vars()

        assert result1 == result2
        mock_path.read_text.assert_called_once()

    def test_load_management_vars_force_reload(self):
        """force_reload=True bypasses the cache and reads file again."""
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.return_value = VALID_YAML

        with patch.object(
            type(mgmt_module.settings),
            "management_vars_path",
            new_callable=lambda: property(lambda self: mock_path),
        ):
            result1 = load_management_vars()
            result2 = load_management_vars(force_reload=True)

        assert result1 == result2
        assert mock_path.read_text.call_count == 2

    def test_load_management_vars_empty_yaml(self):
        """Empty YAML content returns empty dict (yaml.safe_load returns None)."""
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.return_value = ""

        with patch.object(
            type(mgmt_module.settings),
            "management_vars_path",
            new_callable=lambda: property(lambda self: mock_path),
        ):
            result = load_management_vars()

        assert result == {}


# ---------------------------------------------------------------------------
# get_golden_image_credentials
# ---------------------------------------------------------------------------


class TestGetGoldenImageCredentials:
    def test_get_golden_image_credentials_success(self):
        """All required fields present -> returns GoldenImageCredentials."""
        with patch.object(mgmt_module, "load_management_vars", return_value={
            "root_ssh_filename": "id_rsa_golden",
            "root_ssh_password": "s3cret",
            "golden_image_name": "ubuntu-golden-v3",
            "gcs_bucket": "my-bucket",
            "gcs_project": "my-project",
        }):
            creds = get_golden_image_credentials()

        assert creds is not None
        assert isinstance(creds, GoldenImageCredentials)
        assert creds.root_ssh_filename == "id_rsa_golden"
        assert creds.root_ssh_password == "s3cret"
        assert creds.golden_image_name == "ubuntu-golden-v3"
        assert creds.gcs_bucket == "my-bucket"
        assert creds.gcs_project == "my-project"

    def test_get_golden_image_credentials_missing_fields(self):
        """Missing root_ssh_filename -> returns None."""
        with patch.object(mgmt_module, "load_management_vars", return_value={
            "root_ssh_password": "s3cret",
            "golden_image_name": "ubuntu-golden-v3",
        }):
            creds = get_golden_image_credentials()

        assert creds is None

    def test_get_golden_image_credentials_missing_password(self):
        """Missing root_ssh_password -> returns None."""
        with patch.object(mgmt_module, "load_management_vars", return_value={
            "root_ssh_filename": "id_rsa_golden",
            "golden_image_name": "ubuntu-golden-v3",
        }):
            creds = get_golden_image_credentials()

        assert creds is None

    def test_get_golden_image_credentials_empty_vars(self):
        """Empty dict from load_management_vars -> returns None."""
        with patch.object(mgmt_module, "load_management_vars", return_value={}):
            creds = get_golden_image_credentials()

        assert creds is None

    def test_get_golden_image_credentials_optional_fields_absent(self):
        """Only required fields present -> optional fields default to None."""
        with patch.object(mgmt_module, "load_management_vars", return_value={
            "root_ssh_filename": "id_rsa_golden",
            "root_ssh_password": "s3cret",
        }):
            creds = get_golden_image_credentials()

        assert creds is not None
        assert creds.root_ssh_filename == "id_rsa_golden"
        assert creds.root_ssh_password == "s3cret"
        assert creds.golden_image_name is None
        assert creds.gcs_bucket is None
        assert creds.gcs_project is None
