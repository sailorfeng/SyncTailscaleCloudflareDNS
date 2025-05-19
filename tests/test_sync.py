# Tests for sync.py

import logging
import os
# Ensure src is in path for imports if tests are run from project root
import sys
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from src import sync
    from src.cloudflare import CloudflareAPI
    from src.config import load_config  # For main args parsing
    from src.tailscale import TailscaleAPI
except ImportError:
    # Fallback for when package might be installed or structure is different
    import sync
    from cloudflare import CloudflareAPI
    from config import load_config
    from tailscale import TailscaleAPI


# --- Fixtures ---
@pytest.fixture
def mock_ts_api():
    api = MagicMock(spec=TailscaleAPI)
    api.get_devices.return_value = [] # Default to no devices
    return api

@pytest.fixture
def mock_cf_api():
    api = MagicMock(spec=CloudflareAPI)
    api.get_all_managed_records.return_value = [] # Default to no existing records
    api._get_record_name = lambda device_name: f"{device_name}.{api.subdomain_prefix}.{api.domain}"
    api.subdomain_prefix = "ts-test" # Match default in tests
    api.domain = "example.com"    # Match default in tests
    return api

@pytest.fixture(autouse=True)
def setup_test_logging(caplog):
    # Ensure logs are captured and set a reasonable level for tests
    caplog.set_level(logging.INFO)
    # sync.setup_logging("DEBUG") # Optionally set sync module's logging level for more verbose test output

# --- Test get_desired_dns_records ---
def test_get_desired_dns_records_empty(mock_cf_api):
    ts_devices = []
    desired = sync.get_desired_dns_records(ts_devices, mock_cf_api)
    assert desired == {}

def test_get_desired_dns_records_single_device(mock_cf_api):
    ts_devices = [{"name": "dev1", "ip": "100.1.1.1", "id": "tsid1"}]
    # mock_cf_api._get_record_name.return_value = "dev1.ts-test.example.com" # Already mocked by fixture setup

    desired = sync.get_desired_dns_records(ts_devices, mock_cf_api)

    expected_fqdn = "dev1.ts-test.example.com"
    assert expected_fqdn in desired
    assert desired[expected_fqdn]["ip"] == "100.1.1.1"
    assert desired[expected_fqdn]["device_name"] == "dev1"
    assert desired[expected_fqdn]["tailscale_id"] == "tsid1"

def test_get_desired_dns_records_filters_missing_ip_or_name(mock_cf_api, caplog):
    ts_devices = [
        {"name": "dev-ok", "ip": "100.1.1.2", "id": "tsid2"},
        {"name": "dev-no-ip", "id": "tsid3"}, # Missing IP
        {"ip": "100.1.1.3", "id": "tsid4"}    # Missing name
    ]
    desired = sync.get_desired_dns_records(ts_devices, mock_cf_api)

    assert len(desired) == 1
    assert "dev-ok.ts-test.example.com" in desired
    assert "Skipping Tailscale device due to missing name or IP" in caplog.text
    # Check that it logged twice for the two problematic devices
    assert caplog.text.count("Skipping Tailscale device due to missing name or IP") == 2


# --- Test get_current_dns_records ---
def test_get_current_dns_records_empty(mock_cf_api):
    mock_cf_api.get_all_managed_records.return_value = []
    current = sync.get_current_dns_records(mock_cf_api)
    assert current == {}

def test_get_current_dns_records_multiple(mock_cf_api):
    raw_records = [
        {"id": "cfid1", "name": "rec1.ts-test.example.com", "content": "1.2.3.4", "type": "A"},
        {"id": "cfid2", "name": "rec2.ts-test.example.com", "content": "5.6.7.8", "type": "A"},
        {"id": "cfid3", "name": "ignored.ts-test.example.com", "content": "9.9.9.9", "type": "TXT"}, # Ignored type
    ]
    mock_cf_api.get_all_managed_records.return_value = raw_records

    current = sync.get_current_dns_records(mock_cf_api)

    assert len(current) == 2
    assert "rec1.ts-test.example.com" in current
    assert current["rec1.ts-test.example.com"]["id"] == "cfid1"
    assert current["rec1.ts-test.example.com"]["ip"] == "1.2.3.4"
    assert "rec2.ts-test.example.com" in current


# --- Test synchronize_dns ---
# Scenario: Create new record
def test_synchronize_dns_create_new(mock_ts_api, mock_cf_api, caplog):
    mock_ts_api.get_devices.return_value = [{"name": "newdev", "ip": "100.10.1.1", "id": "ts_new"}]
    mock_cf_api.get_all_managed_records.return_value = [] # No existing records

    sync.synchronize_dns(mock_ts_api, mock_cf_api)

    fqdn = "newdev.ts-test.example.com"
    mock_cf_api.create_dns_record.assert_called_once_with("newdev", "100.10.1.1")
    assert f"Record for {fqdn} (device: newdev) does not exist. Will create." in caplog.text
    assert "1 created, 0 updated, 0 deleted" in caplog.text

# Scenario: Update existing record
def test_synchronize_dns_update_existing(mock_ts_api, mock_cf_api, caplog):
    fqdn = "existingdev.ts-test.example.com"
    mock_ts_api.get_devices.return_value = [{"name": "existingdev", "ip": "100.10.1.2", "id": "ts_exist"}] # New IP
    mock_cf_api.get_all_managed_records.return_value = [
        {"id": "cf_id_exist", "name": fqdn, "content": "100.10.1.1", "type": "A"} # Old IP
    ]

    sync.synchronize_dns(mock_ts_api, mock_cf_api)

    mock_cf_api.update_dns_record.assert_called_once_with("cf_id_exist", "existingdev", "100.10.1.2")
    assert f"Record for {fqdn} (device: existingdev) IP has changed. Current: 100.10.1.1, Desired: 100.10.1.2. Will update." in caplog.text
    assert "0 created, 1 updated, 0 deleted" in caplog.text

# Scenario: Delete stale record
def test_synchronize_dns_delete_stale(mock_ts_api, mock_cf_api, caplog):
    fqdn_stale = "staledev.ts-test.example.com"
    mock_ts_api.get_devices.return_value = [] # No Tailscale devices
    mock_cf_api.get_all_managed_records.return_value = [
        {"id": "cf_id_stale", "name": fqdn_stale, "content": "100.10.1.3", "type": "A"}
    ]

    sync.synchronize_dns(mock_ts_api, mock_cf_api)

    mock_cf_api.delete_dns_record.assert_called_once_with("cf_id_stale")
    assert f"Record for {fqdn_stale} (ID: cf_id_stale) exists in Cloudflare but not in Tailscale. Will delete." in caplog.text
    assert "0 created, 0 updated, 1 deleted" in caplog.text

# Scenario: No changes needed
def test_synchronize_dns_no_changes(mock_ts_api, mock_cf_api, caplog):
    caplog.set_level(logging.DEBUG)  # Set debug level for this test to capture debug logs
    fqdn = "samedev.ts-test.example.com"
    ip = "100.10.1.4"
    mock_ts_api.get_devices.return_value = [{"name": "samedev", "ip": ip, "id": "ts_same"}]
    mock_cf_api.get_all_managed_records.return_value = [
        {"id": "cf_id_same", "name": fqdn, "content": ip, "type": "A"}
    ]

    sync.synchronize_dns(mock_ts_api, mock_cf_api)

    mock_cf_api.create_dns_record.assert_not_called()
    mock_cf_api.update_dns_record.assert_not_called()
    mock_cf_api.delete_dns_record.assert_not_called()
    assert f"Record for {fqdn} (device: samedev) is up to date." in caplog.text # Debug log
    assert "0 created, 0 updated, 0 deleted, 1 no change" in caplog.text


# Scenario: Dry run
def test_synchronize_dns_dry_run(mock_ts_api, mock_cf_api, caplog):
    mock_ts_api.get_devices.return_value = [{"name": "drydev", "ip": "100.10.1.5", "id": "ts_dry"}]
    mock_cf_api.get_all_managed_records.return_value = []

    sync.synchronize_dns(mock_ts_api, mock_cf_api, dry_run=True)

    mock_cf_api.create_dns_record.assert_not_called()
    assert "DRY RUN mode enabled" in caplog.text
    assert "Planned: 1 created, 0 updated, 0 deleted" in caplog.text


# Scenario: Error in Tailscale API
def test_synchronize_dns_tailscale_api_error(mock_ts_api, mock_cf_api, caplog):
    mock_ts_api.get_devices.side_effect = ValueError("Tailscale auth failed")

    sync.synchronize_dns(mock_ts_api, mock_cf_api)

    assert "Failed to get devices from Tailscale: Tailscale auth failed" in caplog.text
    mock_cf_api.get_all_managed_records.assert_not_called() # Should not proceed

# Scenario: Error in Cloudflare API (get_all_managed_records)
def test_synchronize_dns_cloudflare_get_error(mock_ts_api, mock_cf_api, caplog):
    mock_ts_api.get_devices.return_value = [{"name": "dev", "ip": "1.1.1.1", "id": "ts1"}]
    mock_cf_api.get_all_managed_records.side_effect = ValueError("Cloudflare auth failed")

    sync.synchronize_dns(mock_ts_api, mock_cf_api)

    assert "Failed to get current DNS records from Cloudflare: Cloudflare auth failed" in caplog.text
    mock_cf_api.create_dns_record.assert_not_called() # Should not proceed to actions

# Scenario: Error during Cloudflare action (e.g., create)
def test_synchronize_dns_cloudflare_action_error(mock_ts_api, mock_cf_api, caplog):
    mock_ts_api.get_devices.return_value = [{"name": "actionerrdev", "ip": "100.10.1.6", "id": "ts_act_err"}]
    mock_cf_api.get_all_managed_records.return_value = []
    mock_cf_api.create_dns_record.side_effect = Exception("CF API create error")

    sync.synchronize_dns(mock_ts_api, mock_cf_api)

    fqdn = "actionerrdev.ts-test.example.com"
    assert f"Failed to create DNS record for {fqdn}: CF API create error" in caplog.text
    assert "0 created, 0 updated, 0 deleted, 0 no change, 1 errors." in caplog.text


# --- Test list_tailscale_devices ---
def test_list_tailscale_devices_success(mock_ts_api, capsys):
    mock_ts_api.get_devices.return_value = [
        {"name": "dev1", "ip": "1.1.1.1", "os": "linux", "fqdn": "dev1.ts.net"},
        {"name": "dev2", "ip": "2.2.2.2", "os": "macos", "fqdn": "dev2.ts.net"},
    ]
    sync.list_tailscale_devices(mock_ts_api)
    captured = capsys.readouterr()
    assert "Current Tailscale Devices:" in captured.out
    assert "Name: dev1, IP: 1.1.1.1, OS: linux, FQDN (Tailscale): dev1.ts.net" in captured.out
    assert "Name: dev2, IP: 2.2.2.2, OS: macos, FQDN (Tailscale): dev2.ts.net" in captured.out

def test_list_tailscale_devices_empty(mock_ts_api, capsys):
    mock_ts_api.get_devices.return_value = []
    sync.list_tailscale_devices(mock_ts_api)
    captured = capsys.readouterr()
    assert "No active devices found in Tailscale." in captured.out

def test_list_tailscale_devices_api_error(mock_ts_api, caplog):
    mock_ts_api.get_devices.side_effect = Exception("TS API List Error")
    sync.list_tailscale_devices(mock_ts_api)
    assert "Failed to list Tailscale devices: TS API List Error" in caplog.text


# --- Test cleanup_cloudflare_records ---
def test_cleanup_cloudflare_records_success(mock_cf_api, caplog):
    records_to_delete = [
        {"id": "cfid1", "name": "rec1.ts-test.example.com", "content": "1.2.3.4", "type": "A"},
        {"id": "cfid2", "name": "rec2.ts-test.example.com", "content": "5.6.7.8", "type": "A"},
    ]
    mock_cf_api.get_all_managed_records.return_value = records_to_delete

    sync.cleanup_cloudflare_records(mock_cf_api, dry_run=False)

    assert mock_cf_api.delete_dns_record.call_count == 2
    mock_cf_api.delete_dns_record.assert_any_call("cfid1")
    mock_cf_api.delete_dns_record.assert_any_call("cfid2")
    assert "Deleted: 2 records. Errors: 0." in caplog.text

def test_cleanup_cloudflare_records_dry_run(mock_cf_api, caplog):
    records_to_delete = [{"id": "cfid1", "name": "rec1.ts-test.example.com", "content": "1.2.3.4", "type": "A"}]
    mock_cf_api.get_all_managed_records.return_value = records_to_delete

    sync.cleanup_cloudflare_records(mock_cf_api, dry_run=True)

    mock_cf_api.delete_dns_record.assert_not_called()
    assert "DRY RUN mode enabled" in caplog.text
    assert "Planned to delete: 1 records. Errors: 0." in caplog.text

def test_cleanup_cloudflare_records_no_records(mock_cf_api, caplog):
    mock_cf_api.get_all_managed_records.return_value = []
    sync.cleanup_cloudflare_records(mock_cf_api)
    assert "No managed DNS records found in Cloudflare. Nothing to clean up." in caplog.text

def test_cleanup_cloudflare_records_delete_error(mock_cf_api, caplog):
    records_to_delete = [{"id": "cfid1", "name": "rec1.ts-test.example.com", "content": "1.2.3.4", "type": "A"}]
    mock_cf_api.get_all_managed_records.return_value = records_to_delete
    mock_cf_api.delete_dns_record.side_effect = Exception("CF Delete Error")

    sync.cleanup_cloudflare_records(mock_cf_api, dry_run=False)
    assert "Failed to delete DNS record rec1.ts-test.example.com (ID: cfid1): CF Delete Error" in caplog.text
    assert "Deleted: 0 records. Errors: 1." in caplog.text


# --- Test validate_api_tokens ---
@patch('src.sync.TailscaleAPI') # Patch within the sync module's scope
@patch('src.sync.CloudflareAPI')
def test_validate_api_tokens_all_ok(MockCfApiCons, MockTsApiCons, caplog):
    mock_ts_instance = MockTsApiCons.return_value
    mock_ts_instance.get_devices.return_value = [{"name": "test", "ip": "1.1.1.1"}] # Simulate successful call

    mock_cf_instance = MockCfApiCons.return_value
    mock_cf_instance.get_dns_records.return_value = [] # Simulate successful call

    config = {
        "tailscale": {"comment": "No API token needed"},
        "cloudflare": {"api_token": "cf_ok", "zone_id": "zone_ok", "domain": "ok.com", "subdomain_prefix": "ts"}
    }
    sync.validate_api_tokens(config)

    assert "Tailscale CLI connectivity: OK" in caplog.text
    assert "Cloudflare API token and connectivity: OK" in caplog.text
    assert "All API validations passed." in caplog.text
    # No parameters passed to TailscaleAPI constructor anymore
    MockTsApiCons.assert_called_once_with()
    MockCfApiCons.assert_called_once_with(api_token="cf_ok", zone_id="zone_ok", domain="ok.com", subdomain_prefix="ts")

@patch('src.sync.TailscaleAPI')
@patch('src.sync.CloudflareAPI')
def test_validate_api_tokens_ts_fails(MockCfApiCons, MockTsApiCons, caplog):
    MockTsApiCons.return_value.get_devices.side_effect = ValueError("TS Auth Error")
    MockCfApiCons.return_value.get_dns_records.return_value = []

    config = {
        "tailscale": {"comment": "No API token needed"},
        "cloudflare": {"api_token": "cf_ok", "zone_id": "zone_ok", "domain": "ok.com", "subdomain_prefix": "ts"}
    }
    sync.validate_api_tokens(config)

    assert "Tailscale CLI validation failed: TS Auth Error" in caplog.text
    assert "Cloudflare API token and connectivity: OK" in caplog.text # CF should still be checked
    assert "One or more API validations failed." in caplog.text

@patch('src.sync.TailscaleAPI')
@patch('src.sync.CloudflareAPI')
def test_validate_api_tokens_cf_fails(MockCfApiCons, MockTsApiCons, caplog):
    MockTsApiCons.return_value.get_devices.return_value = []
    MockCfApiCons.return_value.get_dns_records.side_effect = ValueError("CF Auth Error")

    config = {
        "tailscale": {"comment": "No API token needed"},
        "cloudflare": {"api_token": "cf_fail", "zone_id": "zone_fail", "domain": "fail.com", "subdomain_prefix": "ts"}
    }
    sync.validate_api_tokens(config)

    assert "Tailscale CLI connectivity: OK" in caplog.text
    assert "Cloudflare API validation failed: CF Auth Error" in caplog.text
    assert "One or more API validations failed." in caplog.text


# --- Test main() argument parsing and flow ---
# These are more complex integration tests for the CLI part.
# We'll mock the core functions called by main.

@patch('src.sync.load_config')
@patch('src.sync.setup_logging')
@patch('src.sync.TailscaleAPI')
@patch('src.sync.CloudflareAPI')
@patch('src.sync.synchronize_dns')
def test_main_single_run(mock_sync_dns, MockCfApi, MockTsApi, mock_setup_logging, mock_load_config, monkeypatch):
    mock_load_config.return_value = {
        "tailscale": {"api_token": "t", "tailnet": "tn"},
        "cloudflare": {"api_token": "c", "zone_id": "z", "domain": "d", "subdomain_prefix": "p"},
        "sync": {"log_level": "INFO", "interval_seconds": 300}
    }
    monkeypatch.setattr(sys, 'argv', ['sync.py']) # Basic run, no extra args

    sync.main()

    mock_load_config.assert_called_once()
    mock_setup_logging.assert_called_once_with("INFO")
    MockTsApi.assert_called_once()
    MockCfApi.assert_called_once()
    mock_sync_dns.assert_called_once_with(MockTsApi.return_value, MockCfApi.return_value, dry_run=False)

@patch('src.sync.load_config')
@patch('src.sync.setup_logging')
@patch('src.sync.TailscaleAPI')
@patch('src.sync.CloudflareAPI')
@patch('src.sync.list_tailscale_devices')
def test_main_list_devices(mock_list_dev, MockCfApi, MockTsApi, mock_setup_logging, mock_load_config, monkeypatch):
    mock_load_config.return_value = { # Same config as above
        "tailscale": {"api_token": "t", "tailnet": "tn"},
        "cloudflare": {"api_token": "c", "zone_id": "z", "domain": "d", "subdomain_prefix": "p"},
        "sync": {"log_level": "INFO"}
    }
    monkeypatch.setattr(sys, 'argv', ['sync.py', '--list-devices'])

    with pytest.raises(SystemExit) as e: # Should exit after listing
        sync.main()
    assert e.value.code == 0

    mock_list_dev.assert_called_once_with(MockTsApi.return_value)

@patch('src.sync.load_config')
@patch('src.sync.setup_logging')
@patch('src.sync.validate_api_tokens')
def test_main_validate_config(mock_validate, mock_setup_logging, mock_load_config, monkeypatch):
    mock_load_config.return_value = {"sync": {"log_level": "DEBUG"}} # Minimal for this path
    monkeypatch.setattr(sys, 'argv', ['sync.py', '--validate-config'])

    with pytest.raises(SystemExit) as e:
        sync.main()
    assert e.value.code == 0
    mock_validate.assert_called_once_with(mock_load_config.return_value)


def test_main_config_load_failure(monkeypatch, caplog):
    # Test what happens if load_config itself fails (e.g., file not found and no env vars for required fields)
    with patch('src.sync.load_config', side_effect=ValueError("Mocked config load error")):
        monkeypatch.setattr(sys, 'argv', ['sync.py'])
        with pytest.raises(SystemExit) as e:
            sync.main()
        assert e.value.code == 1
        # Check basic logging because setup_logging might not have been called
        assert "Configuration error: Mocked config load error" in caplog.text
