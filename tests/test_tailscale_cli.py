# Tests for tailscale.py using CLI implementation

import pytest
import subprocess
import json
from unittest.mock import patch, MagicMock

# Ensure src is in path for imports if tests are run from project root
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from src.tailscale import TailscaleAPI
except ImportError:
    from tailscale import TailscaleAPI

# Sample tailscale status --json output
SAMPLE_TAILSCALE_STATUS = {
    "Self": {
        "ID": "local123",
        "HostName": "local-device",
        "DNSName": "local-device.ts.net",
        "OS": "linux",
        "User": "user@example.com",
        "TailscaleIPs": ["100.100.100.100", "fd7a:115c:a1e0::1"]
    },
    "Peer": {
        "remote123": {
            "ID": "remote123",
            "HostName": "remote-device",
            "DNSName": "remote-device.ts.net",
            "OS": "macos",
            "User": "user@example.com",
            "TailscaleIPs": ["100.100.100.101", "fd7a:115c:a1e0::2"],
            "LastSeen": "2023-05-16T12:00:00Z"
        },
        "remote456": {
            "ID": "remote456",
            "HostName": "ipv6-only",
            "DNSName": "ipv6-only.ts.net",
            "OS": "windows",
            "User": "user@example.com",
            "TailscaleIPs": ["fd7a:115c:a1e0::3"],  # Only IPv6
            "LastSeen": "2023-05-16T13:00:00Z"
        },
        "remote789": {
            "ID": "remote789",
            "HostName": "link-local",
            "DNSName": "link-local.ts.net",
            "OS": "android",
            "User": "user@example.com",
            "TailscaleIPs": ["169.254.1.1", "100.100.100.102"],  # Link-local should be skipped
            "LastSeen": "2023-05-16T14:00:00Z"
        }
    }
}

@pytest.fixture
def ts_api_client():
    return TailscaleAPI()

class MockCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

def mock_subprocess_run(returncode=0, stdout="", stderr="", check=True):
    """Helper to create a mock for subprocess.run with configurable output"""
    mock = MagicMock()
    if check and returncode != 0:
        mock.side_effect = subprocess.CalledProcessError(
            returncode, cmd="mock cmd", output=stdout, stderr=stderr
        )
    else:
        mock.return_value = MockCompletedProcess(returncode, stdout, stderr)
    return mock

@patch("subprocess.run")
def test_tailscale_get_devices_success(mock_run, ts_api_client):
    """Test getting devices from a successful tailscale status --json command"""
    # Mock the subprocess.run to return a tailscale status response
    mock_run.return_value = MockCompletedProcess(
        returncode=0,
        stdout=json.dumps(SAMPLE_TAILSCALE_STATUS)
    )

    devices = ts_api_client.get_devices()

    mock_run.assert_called_once_with(
        ["tailscale", "status", "--json"],
        capture_output=True,
        text=True,
        check=True
    )

    # Should include Self and 2 of the 3 peers (skipping the IPv6-only one)
    assert len(devices) == 3

    # Verify local device
    local_device = next((d for d in devices if d["id"] == "local123"), None)
    assert local_device is not None
    assert local_device["name"] == "local-device"
    assert local_device["ip"] == "100.100.100.100"

    # Verify remote device
    remote_device = next((d for d in devices if d["id"] == "remote123"), None)
    assert remote_device is not None
    assert remote_device["name"] == "remote-device"
    assert remote_device["ip"] == "100.100.100.101"

    # Verify link-local device (should use 100.x IP)
    link_local_device = next((d for d in devices if d["id"] == "remote789"), None)
    assert link_local_device is not None
    assert link_local_device["name"] == "link-local"
    assert link_local_device["ip"] == "100.100.100.102"  # Should skip the 169.254.x.x address

@patch("subprocess.run")
def test_tailscale_get_devices_empty(mock_run, ts_api_client):
    """Test getting devices when no peers are found"""
    empty_status = {
        "Self": {
            "ID": "local123",
            "HostName": "local-device",
            "DNSName": "local-device.ts.net",
            "OS": "linux",
            "User": "user@example.com",
            "TailscaleIPs": ["100.100.100.100"]
        },
        "Peer": {}
    }

    mock_run.return_value = MockCompletedProcess(
        returncode=0,
        stdout=json.dumps(empty_status)
    )

    devices = ts_api_client.get_devices()

    # Should only include the local device
    assert len(devices) == 1
    assert devices[0]["name"] == "local-device"
    assert devices[0]["ip"] == "100.100.100.100"

@patch("subprocess.run")
def test_tailscale_get_devices_no_ipv4(mock_run, ts_api_client):
    """Test getting devices when no IPv4 addresses are available"""
    ipv6_only_status = {
        "Self": {
            "ID": "local123",
            "HostName": "local-device",
            "DNSName": "local-device.ts.net",
            "OS": "linux",
            "User": "user@example.com",
            "TailscaleIPs": ["fd7a:115c:a1e0::1"]  # Only IPv6
        },
        "Peer": {}
    }

    mock_run.return_value = MockCompletedProcess(
        returncode=0,
        stdout=json.dumps(ipv6_only_status)
    )

    devices = ts_api_client.get_devices()

    # Should be empty as there are no usable IPv4 addresses
    assert len(devices) == 0

@patch("subprocess.run")
def test_tailscale_get_devices_command_failure(mock_run, ts_api_client):
    """Test handling of tailscale command failure"""
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["tailscale", "status", "--json"],
        output=None,
        stderr="Tailscale not running"
    )

    with pytest.raises(ValueError, match="Tailscale command failed"):
        ts_api_client.get_devices()

@patch("subprocess.run")
def test_tailscale_get_devices_invalid_json(mock_run, ts_api_client):
    """Test handling of invalid JSON output"""
    mock_run.return_value = MockCompletedProcess(
        returncode=0,
        stdout="Not valid JSON"
    )

    with pytest.raises(ValueError, match="Invalid JSON output"):
        ts_api_client.get_devices()

def test_get_tailnet_returns_local():
    """Test that get_tailnet returns 'local' when no tailnet is provided"""
    api = TailscaleAPI()
    assert api.get_tailnet() == "local"

def test_get_tailnet_returns_provided_value():
    """Test that get_tailnet returns the provided tailnet value"""
    api = TailscaleAPI(tailnet="example.com")
    assert api.get_tailnet() == "example.com"
