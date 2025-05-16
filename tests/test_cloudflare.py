# Tests for cloudflare.py

import pytest
import requests
from unittest.mock import patch, MagicMock, call

# Ensure src is in path for imports if tests are run from project root
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from src.cloudflare import CloudflareAPI
except ImportError:
    from cloudflare import CloudflareAPI

MOCK_CF_API_TOKEN = "test_cf_token"
MOCK_CF_ZONE_ID = "test_zone_id_12345"
MOCK_CF_DOMAIN = "example.com"
MOCK_CF_SUBDOMAIN_PREFIX = "ts-test"

@pytest.fixture
def cf_api_client():
    return CloudflareAPI(
        api_token=MOCK_CF_API_TOKEN,
        zone_id=MOCK_CF_ZONE_ID,
        domain=MOCK_CF_DOMAIN,
        subdomain_prefix=MOCK_CF_SUBDOMAIN_PREFIX
    )

def mock_cf_response(status_code=200, json_data=None, text_data=None, raise_for_status=None):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data if json_data is not None else {}
    mock_resp.text = text_data if text_data is not None else str(json_data)
    if raise_for_status:
        mock_resp.raise_for_status.side_effect = raise_for_status
    return mock_resp

# --- Test _get_record_name ---
def test_get_record_name(cf_api_client):
    assert cf_api_client._get_record_name("my-device") == f"my-device.{MOCK_CF_SUBDOMAIN_PREFIX}.{MOCK_CF_DOMAIN}"
    assert cf_api_client._get_record_name("MY-DEVICE") == f"my-device.{MOCK_CF_SUBDOMAIN_PREFIX}.{MOCK_CF_DOMAIN}" # Lowercase
    with pytest.raises(ValueError):
        cf_api_client._get_record_name("")


# --- Test get_dns_records ---
@patch("requests.request")
def test_get_dns_records_success_no_filter(mock_requests_request, cf_api_client):
    mock_records = [{"id": "1", "type": "A", "name": f"dev1.{MOCK_CF_SUBDOMAIN_PREFIX}.{MOCK_CF_DOMAIN}", "content": "1.1.1.1"}]
    mock_requests_request.return_value = mock_cf_response(json_data={"result": mock_records, "success": True, "result_info": {"page": 1, "total_pages": 1}})
    
    records = cf_api_client.get_dns_records()
    
    mock_requests_request.assert_called_once_with(
        "GET", f"https://api.cloudflare.com/client/v4/zones/{MOCK_CF_ZONE_ID}/dns_records",
        headers=cf_api_client.headers,
        params={"type": "A", "page": 1, "per_page": 100}
    )
    assert records == mock_records

@patch("requests.request")
def test_get_dns_records_with_name_filter(mock_requests_request, cf_api_client):
    record_name = f"mydev.{MOCK_CF_SUBDOMAIN_PREFIX}.{MOCK_CF_DOMAIN}"
    mock_requests_request.return_value = mock_cf_response(json_data={"result": [], "success": True, "result_info": {"page": 1, "total_pages": 1}})

    cf_api_client.get_dns_records(name=record_name, record_type="TXT")
    
    mock_requests_request.assert_called_once_with(
        "GET", f"https://api.cloudflare.com/client/v4/zones/{MOCK_CF_ZONE_ID}/dns_records",
        headers=cf_api_client.headers,
        params={"type": "TXT", "name": record_name, "page": 1, "per_page": 100}
    )

@patch("requests.request")
def test_get_dns_records_pagination(mock_requests_request, cf_api_client):
    page1_records = [{"id": str(i), "type": "A", "name": f"dev{i}.{MOCK_CF_SUBDOMAIN_PREFIX}.{MOCK_CF_DOMAIN}", "content": f"1.1.1.{i}"} for i in range(100)]
    page2_records = [{"id": str(i), "type": "A", "name": f"dev{i}.{MOCK_CF_SUBDOMAIN_PREFIX}.{MOCK_CF_DOMAIN}", "content": f"1.1.1.{i}"} for i in range(100, 150)]
    
    mock_requests_request.side_effect = [
        mock_cf_response(json_data={"result": page1_records, "success": True, "result_info": {"page": 1, "per_page": 100, "total_pages": 2}}),
        mock_cf_response(json_data={"result": page2_records, "success": True, "result_info": {"page": 2, "per_page": 100, "total_pages": 2}})
    ]
    
    records = cf_api_client.get_dns_records()
    assert len(records) == 150
    assert mock_requests_request.call_count == 2
    
    # Check params for page 2 call
    calls = mock_requests_request.call_args_list
    assert calls[1] == call(
        "GET", f"https://api.cloudflare.com/client/v4/zones/{MOCK_CF_ZONE_ID}/dns_records",
        headers=cf_api_client.headers,
        params={"type": "A", "page": 2, "per_page": 100}
    )


@patch("requests.request")
def test_get_dns_records_http_401_error(mock_requests_request, cf_api_client):
    mock_requests_request.return_value = mock_cf_response(
        status_code=401,
        raise_for_status=requests.exceptions.HTTPError(response=MagicMock(status_code=401, text="Unauthorized"))
    )
    with pytest.raises(ValueError, match="Cloudflare API token/zone ID invalid or insufficient permissions"):
        cf_api_client.get_dns_records()

# --- Test create_dns_record ---
@patch("requests.request")
def test_create_dns_record_success(mock_requests_request, cf_api_client):
    device_name = "new-device"
    ip = "100.1.1.1"
    expected_fqdn = f"{device_name}.{MOCK_CF_SUBDOMAIN_PREFIX}.{MOCK_CF_DOMAIN}"
    mock_response_data = {"result": {"id": "new_id_123", "name": expected_fqdn, "content": ip}, "success": True}
    mock_requests_request.return_value = mock_cf_response(json_data=mock_response_data)

    result = cf_api_client.create_dns_record(device_name, ip)

    expected_payload = {"type": "A", "name": expected_fqdn, "content": ip, "ttl": 300, "proxied": False}
    mock_requests_request.assert_called_once_with(
        "POST", f"https://api.cloudflare.com/client/v4/zones/{MOCK_CF_ZONE_ID}/dns_records",
        headers=cf_api_client.headers, json=expected_payload
    )
    assert result == mock_response_data["result"]

@patch("requests.request")
def test_create_dns_record_failure_api_error(mock_requests_request, cf_api_client):
    mock_requests_request.return_value = mock_cf_response(json_data={"success": False, "errors": [{"code": 9000, "message": "Some API error"}]})
    with pytest.raises(Exception, match="Cloudflare API reported failure on create"):
        cf_api_client.create_dns_record("fail-device", "1.2.3.4")

@patch("requests.request")
def test_create_dns_record_already_exists_81057(mock_requests_request, cf_api_client):
    device_name = "existing-device"
    ip = "1.1.1.1"
    expected_fqdn = f"{device_name}.{MOCK_CF_SUBDOMAIN_PREFIX}.{MOCK_CF_DOMAIN}"
    
    # Mock the POST request failing due to existing record
    http_error_response = MagicMock(status_code=400) # Typically 400 for "record already exists"
    http_error_response.json.return_value = {"success": False, "errors": [{"code": 81057, "message": "Record already exists."}]}
    
    # Mock the subsequent GET request for get_dns_records
    existing_record_data = {"id": "existing_id", "type": "A", "name": expected_fqdn, "content": ip}

    mock_requests_request.side_effect = [
        mock_cf_response(status_code=400, json_data=http_error_response.json(), 
                         raise_for_status=requests.exceptions.HTTPError(response=http_error_response)),
        mock_cf_response(json_data={"result": [existing_record_data], "success": True, "result_info": {"page": 1, "total_pages": 1}})
    ]

    result = cf_api_client.create_dns_record(device_name, ip)
    assert result == existing_record_data
    assert mock_requests_request.call_count == 2 # POST (fails), then GET

# --- Test update_dns_record ---
@patch("requests.request")
def test_update_dns_record_success(mock_requests_request, cf_api_client):
    record_id = "record_to_update_id"
    device_name = "updated-device"
    ip = "100.2.2.2"
    expected_fqdn = f"{device_name}.{MOCK_CF_SUBDOMAIN_PREFIX}.{MOCK_CF_DOMAIN}"
    mock_response_data = {"result": {"id": record_id, "name": expected_fqdn, "content": ip}, "success": True}
    mock_requests_request.return_value = mock_cf_response(json_data=mock_response_data)

    result = cf_api_client.update_dns_record(record_id, device_name, ip)
    
    expected_payload = {"type": "A", "name": expected_fqdn, "content": ip, "ttl": 300, "proxied": False}
    mock_requests_request.assert_called_once_with(
        "PUT", f"https://api.cloudflare.com/client/v4/zones/{MOCK_CF_ZONE_ID}/dns_records/{record_id}",
        headers=cf_api_client.headers, json=expected_payload
    )
    assert result == mock_response_data["result"]

# --- Test delete_dns_record ---
@patch("requests.request")
def test_delete_dns_record_success(mock_requests_request, cf_api_client):
    record_id = "record_to_delete_id"
    mock_requests_request.return_value = mock_cf_response(json_data={"result": {"id": record_id}, "success": True})
    
    success = cf_api_client.delete_dns_record(record_id)
    
    mock_requests_request.assert_called_once_with(
        "DELETE", f"https://api.cloudflare.com/client/v4/zones/{MOCK_CF_ZONE_ID}/dns_records/{record_id}",
        headers=cf_api_client.headers
    )
    assert success is True

@patch("requests.request")
def test_delete_dns_record_already_deleted_81044(mock_requests_request, cf_api_client):
    record_id = "already_deleted_id"
    mock_requests_request.return_value = mock_cf_response(
        json_data={"success": False, "errors": [{"code": 81044, "message": "Record not found."}]}
    )
    success = cf_api_client.delete_dns_record(record_id)
    assert success is True # Should treat as success

@patch("requests.request")
def test_delete_dns_record_failure_other_error(mock_requests_request, cf_api_client):
    record_id = "fail_delete_id"
    mock_requests_request.return_value = mock_cf_response(
        json_data={"success": False, "errors": [{"code": 9999, "message": "Another error."}]}
    )
    success = cf_api_client.delete_dns_record(record_id)
    assert success is False

# --- Test find_record_id ---
@patch.object(CloudflareAPI, "get_dns_records")
def test_find_record_id_found(mock_get_dns_records, cf_api_client):
    device_name = "find-me"
    expected_fqdn = f"{device_name}.{MOCK_CF_SUBDOMAIN_PREFIX}.{MOCK_CF_DOMAIN}"
    mock_get_dns_records.return_value = [{"id": "found_id_789", "name": expected_fqdn, "type": "A"}]
    
    record_id = cf_api_client.find_record_id(device_name)
    
    mock_get_dns_records.assert_called_once_with(name=expected_fqdn, record_type="A")
    assert record_id == "found_id_789"

@patch.object(CloudflareAPI, "get_dns_records")
def test_find_record_id_not_found(mock_get_dns_records, cf_api_client):
    mock_get_dns_records.return_value = []
    record_id = cf_api_client.find_record_id("not-found-device")
    assert record_id is None

@patch.object(CloudflareAPI, "get_dns_records")
def test_find_record_id_multiple_found_returns_first(mock_get_dns_records, cf_api_client):
    device_name = "multi-device"
    expected_fqdn = f"{device_name}.{MOCK_CF_SUBDOMAIN_PREFIX}.{MOCK_CF_DOMAIN}"
    mock_get_dns_records.return_value = [
        {"id": "id_1", "name": expected_fqdn, "type": "A"},
        {"id": "id_2", "name": expected_fqdn, "type": "A"}
    ]
    record_id = cf_api_client.find_record_id(device_name)
    assert record_id == "id_1" # Returns the first one

# --- Test get_all_managed_records ---
@patch.object(CloudflareAPI, "get_dns_records")
def test_get_all_managed_records(mock_get_dns_records, cf_api_client):
    suffix_to_match = f".{MOCK_CF_SUBDOMAIN_PREFIX}.{MOCK_CF_DOMAIN}"
    all_records_from_api = [
        {"id": "1", "type": "A", "name": f"dev1{suffix_to_match}", "content": "1.1.1.1"},
        {"id": "2", "type": "A", "name": f"another{suffix_to_match}", "content": "2.2.2.2"},
        {"id": "3", "type": "A", "name": f"unmanaged.other.{MOCK_CF_DOMAIN}", "content": "3.3.3.3"}, # Different prefix
        {"id": "4", "type": "TXT", "name": f"textrecord{suffix_to_match}", "content": "text"}, # Different type (get_dns_records filters by A)
        {"id": "5", "type": "A", "name": f"dev5.anotherprefix.{MOCK_CF_DOMAIN}", "content": "5.5.5.5"}, # Different prefix
    ]
    # get_all_managed_records calls get_dns_records(record_type="A")
    # So, mock what that call would return (only A records)
    mock_get_dns_records.return_value = [r for r in all_records_from_api if r["type"] == "A"]

    managed_records = cf_api_client.get_all_managed_records()
    
    mock_get_dns_records.assert_called_once_with(record_type="A")
    assert len(managed_records) == 2
    assert all(r["name"].endswith(suffix_to_match) for r in managed_records)
    assert managed_records[0]["id"] == "1"
    assert managed_records[1]["id"] == "2"

@patch("requests.request")
def test_request_error_logging_cloudflare_format(mock_requests_request, cf_api_client):
    # Test that Cloudflare's specific error format is logged from _request
    error_json = {
        "success": False,
        "errors": [{"code": 1003, "message": "Invalid or missing zone ID."}],
        "messages": [], "result": None
    }
    http_error = requests.exceptions.HTTPError(response=mock_cf_response(status_code=400, json_data=error_json))
    mock_requests_request.side_effect = http_error
    
    with patch.object(cf_api_client.logger, "error") as mock_logger_error:
        with pytest.raises(requests.exceptions.HTTPError):
            cf_api_client._request("GET", "/some_endpoint")
        
        # Check for the generic HTTP error log
        assert any(f"HTTP error occurred with Cloudflare API: 400" in str(arg) for arg_list in mock_logger_error.call_args_list for arg in arg_list[0])
        # Check for the specific Cloudflare error log
        assert any(f"Cloudflare API Error Code 1003: Invalid or missing zone ID." in str(arg) for arg_list in mock_logger_error.call_args_list for arg in arg_list[0])
