"""Unit tests for the management vars module (async_provisioning_service.services.management_vars)."""

import contextlib

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

import async_provisioning_service.services.management_vars as mgmt_module
from async_provisioning_service.services.management_vars import (
    load_management_vars,
    get_golden_image_credentials,
    GoldenImageCredentials,
)

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


@pytest.fixture(autouse=True)
def reset_cache():
    mgmt_module._cached_vars = None
    yield
    mgmt_module._cached_vars = None


@contextlib.contextmanager
def _mock_vars_path(*, content=None, side_effect=None):
    """Patch management_vars_path to return a mock Path with the given content or side_effect."""
    mock_path = MagicMock(spec=Path)
    if side_effect:
        mock_path.read_text.side_effect = side_effect
    else:
        mock_path.read_text.return_value = content
    with patch.object(
        type(mgmt_module.settings),
        "management_vars_path",
        new_callable=lambda: property(lambda self: mock_path),
    ):
        yield mock_path


class TestLoadManagementVars:
    def test_load_management_vars_success(self):
        """Valid YAML file is parsed and returned as a dict."""
        with _mock_vars_path(content=VALID_YAML) as mock_path:
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
        with _mock_vars_path(side_effect=FileNotFoundError("no such file")):
            result = load_management_vars()

        assert result == {}

    def test_load_management_vars_invalid_yaml(self):
        """Malformed YAML returns empty dict without raising."""
        with _mock_vars_path(content=INVALID_YAML):
            result = load_management_vars()

        assert result == {}

    def test_load_management_vars_empty_yaml(self):
        """Empty YAML content returns empty dict (yaml.safe_load returns None)."""
        with _mock_vars_path(content=""):
            result = load_management_vars()

        assert result == {}


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

    @pytest.mark.parametrize(
        "vars_dict",
        [
            pytest.param({"root_ssh_password": "s3cret", "golden_image_name": "ubuntu-golden-v3"}, id="missing_filename"),
            pytest.param({"root_ssh_filename": "id_rsa_golden", "golden_image_name": "ubuntu-golden-v3"}, id="missing_password"),
            pytest.param({}, id="empty_vars"),
        ],
    )
    def test_get_golden_image_credentials_missing_required_field(self, vars_dict):
        """Missing any required field -> returns None."""
        with patch.object(mgmt_module, "load_management_vars", return_value=vars_dict):
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
