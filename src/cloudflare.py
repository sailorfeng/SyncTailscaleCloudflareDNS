# Cloudflare API interaction module

import requests
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class CloudflareAPI:
    def __init__(self, api_token: str, zone_id: str, domain: str, subdomain_prefix: str = "ts"):
        self.api_token = api_token
        self.zone_id = zone_id
        self.domain = domain
        self.subdomain_prefix = subdomain_prefix
        self.base_url = "https://api.cloudflare.com/client/v4"
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.request(method, url, headers=self.headers, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error occurred with Cloudflare API: {e.response.status_code} - {e.response.text}")
            # Attempt to parse Cloudflare-specific errors
            try:
                error_data = e.response.json()
                if "errors" in error_data and error_data["errors"]:
                    for err in error_data["errors"]:
                        logger.error(f"Cloudflare API Error Code {err.get('code')}: {err.get('message')}")
            except ValueError: # If response is not JSON
                pass
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Error connecting to Cloudflare API: {e}")
            raise

    def _get_record_name(self, device_name: str) -> str:
        """Constructs the FQDN for the DNS record."""
        if not device_name:
            raise ValueError("Device name cannot be empty.")
        return f"{device_name}.{self.subdomain_prefix}.{self.domain}".lower()

    def get_dns_records(self, name: Optional[str] = None, record_type: str = "A") -> List[Dict[str, Any]]:
        """
        Retrieves DNS records for the zone.
        Can be filtered by name and type.
        If name is provided, it should be the FQDN.
        """
        endpoint = f"/zones/{self.zone_id}/dns_records"
        params: Dict[str, Any] = {"type": record_type}
        if name:
            params["name"] = name.lower()

        all_records = []
        page = 1
        while True:
            params["page"] = page
            params["per_page"] = 100 # Max per page
            try:
                data = self._request("GET", endpoint, params=params)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 401 or e.response.status_code == 403:
                     logger.error("Cloudflare API authentication/authorization failed. Check token and zone ID permissions.")
                     raise ValueError("Cloudflare API token/zone ID invalid or insufficient permissions.")
                raise

            records_on_page = data.get("result", [])
            if not records_on_page:
                break
            all_records.extend(records_on_page)

            result_info = data.get("result_info", {})
            total_pages = result_info.get("total_pages", 1)
            if page >= total_pages:
                break
            page += 1

        logger.info(f"Retrieved {len(all_records)} DNS records matching filters (type: {record_type}, name: {name if name else 'any'}).")
        return all_records

    def create_dns_record(self, device_name: str, ip_address: str, record_type: str = "A", ttl: int = 300) -> Dict[str, Any]:
        """
        Creates a new DNS A record.
        device_name: The short hostname of the device (e.g., 'my-laptop').
        """
        record_name = self._get_record_name(device_name)
        endpoint = f"/zones/{self.zone_id}/dns_records"
        payload = {
            "type": record_type,
            "name": record_name,
            "content": ip_address,
            "ttl": ttl,
            "proxied": False # For internal DNS, typically not proxied
        }
        logger.info(f"Creating DNS record: {record_name} -> {ip_address}")
        try:
            result = self._request("POST", endpoint, json=payload)
            if result.get("success"):
                logger.info(f"Successfully created DNS record: {record_name} (ID: {result.get('result',{}).get('id')})")
                return result.get("result", {})
            else:
                logger.error(f"Failed to create DNS record {record_name}. Errors: {result.get('errors')}")
                raise Exception(f"Cloudflare API reported failure on create: {result.get('errors')}")
        except requests.exceptions.HTTPError as e:
            # Check for specific error codes, e.g., record already exists (81057)
            try:
                error_data = e.response.json()
                if any(err.get("code") == 81057 for err in error_data.get("errors", [])):
                    logger.warning(f"DNS record {record_name} already exists. Consider updating instead.")
                    # Optionally, you could try to fetch and return the existing record here.
                    existing = self.get_dns_records(name=record_name, record_type=record_type)
                    if existing:
                        return existing[0] # Return the first match
                    raise # Re-raise if not found after all
            except (ValueError, AttributeError):
                pass # If error response is not as expected, just re-raise original
            raise


    def update_dns_record(self, record_id: str, device_name: str, ip_address: str, record_type: str = "A", ttl: int = 300) -> Dict[str, Any]:
        """
        Updates an existing DNS A record by its ID.
        device_name: The short hostname of the device (e.g., 'my-laptop').
        """
        record_name = self._get_record_name(device_name)
        endpoint = f"/zones/{self.zone_id}/dns_records/{record_id}"
        payload = {
            "type": record_type,
            "name": record_name,
            "content": ip_address,
            "ttl": ttl,
            "proxied": False
        }
        logger.info(f"Updating DNS record ID {record_id}: {record_name} -> {ip_address}")
        result = self._request("PUT", endpoint, json=payload)
        if result.get("success"):
            logger.info(f"Successfully updated DNS record: {record_name} (ID: {result.get('result',{}).get('id')})")
            return result.get("result", {})
        else:
            logger.error(f"Failed to update DNS record {record_name} (ID: {record_id}). Errors: {result.get('errors')}")
            raise Exception(f"Cloudflare API reported failure on update: {result.get('errors')}")


    def delete_dns_record(self, record_id: str) -> bool:
        """Deletes a DNS record by its ID."""
        endpoint = f"/zones/{self.zone_id}/dns_records/{record_id}"
        logger.info(f"Deleting DNS record ID: {record_id}")
        result = self._request("DELETE", endpoint)
        if result.get("success"):
            logger.info(f"Successfully deleted DNS record ID: {record_id}")
            return True
        else:
            logger.error(f"Failed to delete DNS record ID {record_id}. Errors: {result.get('errors')}")
            # Check if the record was already deleted (common scenario)
            # Error code 81044: Record not found
            if result.get("errors") and any(e.get("code") == 81044 for e in result["errors"]):
                logger.warning(f"Record ID {record_id} not found for deletion, likely already deleted.")
                return True # Treat as success if already gone
            return False

    def find_record_id(self, device_name: str, record_type: str = "A") -> Optional[str]:
        """Finds a DNS record ID by device name."""
        record_name_fqdn = self._get_record_name(device_name)
        records = self.get_dns_records(name=record_name_fqdn, record_type=record_type)
        if records:
            # It's possible to have multiple records with the same name but different content (e.g. for round-robin)
            # For this tool, we assume one A record per device name.
            if len(records) > 1:
                logger.warning(f"Multiple records found for {record_name_fqdn}. Using the first one: {records[0]['id']}")
            return records[0]["id"]
        return None

    def get_all_managed_records(self) -> List[Dict[str, Any]]:
        """
        Retrieves all DNS A records managed by this tool
        (i.e., matching *.<subdomain_prefix>.<domain>).
        """
        # Cloudflare API doesn\'t support wildcard in the middle of the name for filtering directly.
        # We fetch all A records and filter locally.
        all_a_records = self.get_dns_records(record_type="A")

        managed_records = []
        # Example: device_name.ts.example.com
        # We need to match *.ts.example.com
        # So, name must end with .<subdomain_prefix>.<domain>
        suffix_to_match = f".{self.subdomain_prefix}.{self.domain}".lower()

        for record in all_a_records:
            if record.get("name", "").lower().endswith(suffix_to_match):
                managed_records.append(record)
        logger.info(f"Found {len(managed_records)} existing records managed by this tool (ending with {suffix_to_match}).")
        return managed_records

# Example usage (for direct script testing)
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    try:
        from config import load_config # Assuming config.py is in the same directory or PYTHONPATH
    except ImportError:
        import sys
        sys.path.append(os.path.dirname(__file__)) # Add current dir to path for sibling import
        from config import load_config


    # Load environment variables from .env file for local testing
    # Path is relative to the project root if this script is in src/
    dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
    load_dotenv(dotenv_path)

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

    # Config file path relative to project root
    config_file_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config.yaml')

    if not os.path.exists(config_file_path):
        logger.warning(f"Main config file {config_file_path} not found. Creating a dummy for test.")
        # Create a dummy config.yaml if it doesn\'t exist for the config loader
        dummy_config_content = '''
tailscale:
  api_token: "dummy_ts_token"
  # tailnet: "your_tailnet"
cloudflare:
  api_token: "YOUR_CLOUDFLARE_API_TOKEN_HERE" # Replace or set CLOUDFLARE_API_TOKEN env var
  zone_id: "YOUR_CLOUDFLARE_ZONE_ID_HERE"   # Replace or set CLOUDFLARE_ZONE_ID env var
  domain: "yourdomain.com"                # Replace or set CLOUDFLARE_DOMAIN env var
  subdomain_prefix: "ts-test"
sync:
  interval_seconds: 300
  log_level: "DEBUG"
'''
        with open(config_file_path, 'w') as f:
            f.write(dummy_config_content)
        logger.info(f"Created dummy config at {config_file_path}. "
                    "IMPORTANT: Populate Cloudflare details in it or set environment variables "
                    "(CLOUDFLARE_API_TOKEN, CLOUDFLARE_ZONE_ID, CLOUDFLARE_DOMAIN) for testing.")

    try:
        app_config = load_config(config_file_path)

        cf_token = app_config.get("cloudflare", {}).get("api_token")
        cf_zone_id = app_config.get("cloudflare", {}).get("zone_id")
        cf_domain = app_config.get("cloudflare", {}).get("domain")
        cf_prefix = app_config.get("cloudflare", {}).get("subdomain_prefix", "ts")

        if not all([cf_token, cf_zone_id, cf_domain]):
            print("Cloudflare API token, Zone ID, or Domain not found. "
                  "Please set CLOUDFLARE_API_TOKEN, CLOUDFLARE_ZONE_ID, CLOUDFLARE_DOMAIN "
                  "in environment variables or config.yaml for testing.")
            exit(1)

        if "YOUR_CLOUDFLARE" in cf_token or "yourdomain.com" == cf_domain :
             print("Dummy Cloudflare credentials detected in config. Please update config.yaml or set environment variables.")
             print("Skipping live API tests to avoid errors with dummy data.")
             exit(0)


        print(f"Using Cloudflare API Token: {cf_token[:5]}...{cf_token[-5:] if len(cf_token) > 10 else ''}")
        print(f"Using Zone ID: {cf_zone_id}")
        print(f"Using Domain: {cf_domain}")
        print(f"Using Subdomain Prefix: {cf_prefix}")

        cloudflare_api = CloudflareAPI(
            api_token=cf_token,
            zone_id=cf_zone_id,
            domain=cf_domain,
            subdomain_prefix=cf_prefix
        )

        test_device_name = "test-sync-device"
        test_ip = "100.101.102.103"
        test_ip_updated = "100.101.102.104"
        record_fqdn = cloudflare_api._get_record_name(test_device_name)

        # 0. Cleanup any pre-existing test record
        print(f"\\\\n--- Pre-test cleanup for {record_fqdn} ---")
        existing_records_before_test = cloudflare_api.get_dns_records(name=record_fqdn)
        for rec in existing_records_before_test:
            print(f"Deleting pre-existing test record: {rec['name']} (ID: {rec['id']})")
            cloudflare_api.delete_dns_record(rec['id'])

        # 1. Get all managed records (to see initial state)
        print(f"\\\\n--- Test 1: Get All Managed Records (Initial) ---")
        managed_records = cloudflare_api.get_all_managed_records()
        print(f"Found {len(managed_records)} initially.")
        # for record in managed_records:
        #     print(f"  - {record[\'name\']} -> {record[\'content\']} (ID: {record[\'id\']})")


        # 2. Create a new DNS record
        print(f"\\\\n--- Test 2: Create DNS Record ---")
        created_record = None
        try:
            created_record = cloudflare_api.create_dns_record(test_device_name, test_ip)
            if created_record:
                print(f"Created record: {created_record['name']} -> {created_record['content']} (ID: {created_record['id']})")
                assert created_record['name'] == record_fqdn
                assert created_record['content'] == test_ip
            else:
                print("Failed to create record or record already existed and was returned.")
        except Exception as e:
            print(f"Error creating record: {e}")
            # If it already exists from a failed previous cleanup, try to get it for update test
            existing = cloudflare_api.get_dns_records(name=record_fqdn)
            if existing:
                created_record = existing[0]
                print(f"Using existing record for subsequent tests: {created_record['name']} (ID: {created_record['id']})")
            else:
                 raise # re-raise if truly failed to create and not found

        if not created_record: # If creation failed and it didn\'t exist
            print("Cannot proceed with update/delete tests as creation failed and record doesn\'t exist.")
            exit(1)

        record_id_to_test = created_record['id']

        # 3. Get specific DNS record
        print(f"\\\\n--- Test 3: Get Specific DNS Record ---")
        records = cloudflare_api.get_dns_records(name=record_fqdn)
        if records:
            print(f"Found record: {records[0]['name']} -> {records[0]['content']}")
            assert records[0]['id'] == record_id_to_test
        else:
            print(f"Record {record_fqdn} not found after creation!")
            assert False, "Record should exist"

        # 4. Update DNS record
        print(f"\\\\n--- Test 4: Update DNS Record ---")
        if record_id_to_test:
            updated_record = cloudflare_api.update_dns_record(record_id_to_test, test_device_name, test_ip_updated)
            print(f"Updated record: {updated_record['name']} -> {updated_record['content']}")
            assert updated_record['content'] == test_ip_updated
        else:
            print("Skipping update test as record_id was not found.")

        # 5. Find record ID by name
        print(f"\\\\n--- Test 5: Find Record ID by Name ---")
        found_id = cloudflare_api.find_record_id(test_device_name)
        print(f"Found ID for {test_device_name}: {found_id}")
        assert found_id == record_id_to_test

        # 6. Get all managed records (to see created record)
        print(f"\\\\n--- Test 6: Get All Managed Records (After Create/Update) ---")
        managed_records_after = cloudflare_api.get_all_managed_records()
        print(f"Found {len(managed_records_after)} managed records now.")
        found_in_all = any(r['id'] == record_id_to_test for r in managed_records_after)
        assert found_in_all, f"Test record {record_fqdn} not found in all managed records."


        # 7. Delete DNS record
        print(f"\\\\n--- Test 7: Delete DNS Record ---")
        if record_id_to_test:
            delete_success = cloudflare_api.delete_dns_record(record_id_to_test)
            print(f"Deletion status for ID {record_id_to_test}: {delete_success}")
            assert delete_success

            # Verify deletion
            records_after_delete = cloudflare_api.get_dns_records(name=record_fqdn)
            assert not records_after_delete, f"Record {record_fqdn} should be deleted but was found."
        else:
            print("Skipping delete test as record_id was not found.")

        print("\\\\nAll Cloudflare API tests seem to have passed if no asserts failed and no live API errors shown (check logs).")

    except ValueError as e:
        print(f"Configuration or API error: {e}")
    except FileNotFoundError:
        print(f"Could not find config file at {config_file_path}. Ensure it exists or env vars are set.")
    except requests.exceptions.RequestException as e:
        print(f"A network or Cloudflare API request error occurred: {e}")
    except Exception as e:
        print(f"An unexpected error occurred during Cloudflare API tests: {e}")
        logger.exception("Details of unexpected error:")
    finally:
        # Optional: clean up the dummy config file if it was created by this test script
        # Be cautious with this in a real environment.
        # if os.path.exists(config_file_path) and "YOUR_CLOUDFLARE_API_TOKEN_HERE" in open(config_file_path).read():
        #     # os.remove(config_file_path)
        #     # logger.info(f"Removed dummy config file: {config_file_path}")
        #     logger.info(f"Test created/used a config at {config_file_path} with placeholder values. Please review or remove it.")
        pass
