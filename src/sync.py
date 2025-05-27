# Device synchronization logic and CLI

import argparse
import logging
import os
import sys
from typing import Any, Dict, List, Tuple

# Ensure src directory is in path for direct execution and for imports if not installed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from src.cloudflare import CloudflareAPI
    from src.config import DEFAULT_CONFIG_PATH, load_config
    from src.tailscale import TailscaleAPI
except ImportError: # Fallback for when the package is installed
    from cloudflare import CloudflareAPI
    from config import DEFAULT_CONFIG_PATH, load_config
    from tailscale import TailscaleAPI


logger = logging.getLogger(__name__)

def setup_logging(log_level_str: str):
    """Configures basic logging."""
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)] # Ensure logs go to stdout
    )
    # Suppress overly verbose logs from libraries like requests
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_desired_dns_records(ts_devices: List[Dict[str, Any]], cf_api: CloudflareAPI) -> Dict[str, Dict[str, Any]]:
    """
    Transforms Tailscale devices into a dictionary of desired DNS records.
    Keyed by FQDN, value is a dict with 'ip' and 'device_name'.
    """
    desired_records = {}
    for device in ts_devices:
        # Use real_hostname if available, otherwise fallback to name
        device_name = device.get("real_hostname") or device.get("name")
        ip = device.get("ip")
        if device_name and ip:
            fqdn = cf_api._get_record_name(device_name) # Use internal method to ensure consistent naming
            desired_records[fqdn] = {"ip": ip, "device_name": device_name, "tailscale_id": device.get("id")}
        else:
            logger.warning(f"Skipping Tailscale device due to missing name or IP: {device}")
    return desired_records

def get_current_dns_records(cf_api: CloudflareAPI) -> Dict[str, Dict[str, Any]]:
    """
    Fetches current DNS A records from Cloudflare managed by this tool.
    Keyed by FQDN, value is a dict with 'id', 'ip', and 'name'.
    """
    current_records_raw = cf_api.get_all_managed_records() # Fetches A records matching *.subdomain_prefix.domain
    current_records_map = {}
    for record in current_records_raw:
        # Ensure we only process A records, though get_all_managed_records should already filter
        if record.get("type") == "A":
            current_records_map[record["name"].lower()] = {
                "id": record["id"],
                "ip": record["content"],
                "name": record["name"] # FQDN
            }
    return current_records_map

def synchronize_dns(ts_api: TailscaleAPI, cf_api: CloudflareAPI, dry_run: bool = False):
    """
    Core synchronization logic.
    Fetches devices from Tailscale and DNS records from Cloudflare, then syncs.
    """
    logger.info("Starting DNS synchronization...")
    if dry_run:
        logger.info("DRY RUN mode enabled. No changes will be made to Cloudflare.")

    try:
        ts_devices = ts_api.get_devices()
        if not ts_devices:
            logger.info("No active devices found in Tailscale. Nothing to sync.")
            # Check if there are any managed records in Cloudflare that need to be deleted
    except ValueError as e: # Handles auth errors or config issues from TailscaleAPI
        logger.error(f"Failed to get devices from Tailscale: {e}")
        return
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching Tailscale devices: {e}", exc_info=True)
        return

    desired_records_map = get_desired_dns_records(ts_devices, cf_api)

    try:
        current_records_map = get_current_dns_records(cf_api)
    except ValueError as e: # Handles auth errors or config issues from CloudflareAPI
        logger.error(f"Failed to get current DNS records from Cloudflare: {e}")
        return
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching Cloudflare DNS records: {e}", exc_info=True)
        return

    actions = {"created": 0, "updated": 0, "deleted": 0, "no_change": 0, "errors": 0}

    # Records to create or update
    for fqdn, desired_state in desired_records_map.items():
        current_state = current_records_map.get(fqdn)
        device_name_for_cf = desired_state["device_name"] # Short hostname

        if current_state is None:
            logger.info(f"Record for {fqdn} (device: {device_name_for_cf}) does not exist. Will create.")
            if not dry_run:
                try:
                    cf_api.create_dns_record(device_name_for_cf, desired_state["ip"])
                    actions["created"] += 1
                except Exception as e:
                    logger.error(f"Failed to create DNS record for {fqdn}: {e}")
                    actions["errors"] += 1
            else:
                actions["created"] += 1 # Count as if created in dry run
        elif current_state["ip"] != desired_state["ip"]:
            logger.info(f"Record for {fqdn} (device: {device_name_for_cf}) IP has changed. Current: {current_state['ip']}, Desired: {desired_state['ip']}. Will update.")
            if not dry_run:
                try:
                    cf_api.update_dns_record(current_state["id"], device_name_for_cf, desired_state["ip"])
                    actions["updated"] += 1
                except Exception as e:
                    logger.error(f"Failed to update DNS record for {fqdn} (ID: {current_state['id']}): {e}")
                    actions["errors"] += 1
            else:
                actions["updated"] += 1 # Count as if updated in dry run
        else:
            logger.debug(f"Record for {fqdn} (device: {device_name_for_cf}) is up to date.")
            actions["no_change"] += 1

    # Records to delete
    # These are records in Cloudflare (managed by this tool) but not in Tailscale's current device list
    desired_fqdns = set(desired_records_map.keys())
    for fqdn, current_state in current_records_map.items():
        if fqdn not in desired_fqdns:
            logger.info(f"Record for {fqdn} (ID: {current_state['id']}) exists in Cloudflare but not in Tailscale. Will delete.")
            if not dry_run:
                try:
                    cf_api.delete_dns_record(current_state["id"])
                    actions["deleted"] += 1
                except Exception as e:
                    logger.error(f"Failed to delete DNS record for {fqdn} (ID: {current_state['id']}): {e}")
                    actions["errors"] += 1
            else:
                actions["deleted"] += 1 # Count as if deleted in dry run

    summary_verb = "Planned" if dry_run else "Performed"
    logger.info(
        f"Synchronization {summary_verb}: "
        f"{actions['created']} created, {actions['updated']} updated, "
        f"{actions['deleted']} deleted, {actions['no_change']} no change, "
        f"{actions['errors']} errors."
    )

def list_tailscale_devices(ts_api: TailscaleAPI):
    logger.info("Fetching Tailscale devices...")
    try:
        devices = ts_api.get_devices()
        if not devices:
            print("No active devices found in Tailscale.")
            return
        print("Current Tailscale Devices:")
        for dev in devices:
            print(f"  - Name: {dev.get('name', 'N/A')}, IP: {dev.get('ip', 'N/A')}, OS: {dev.get('os', 'N/A')}, FQDN (Tailscale): {dev.get('fqdn', 'N/A')}")
    except Exception as e:
        logger.error(f"Failed to list Tailscale devices: {e}")

def cleanup_cloudflare_records(cf_api: CloudflareAPI, dry_run: bool = False):
    logger.info("Starting cleanup of all managed Cloudflare DNS records...")
    if dry_run:
        logger.info("DRY RUN mode enabled. No records will actually be deleted.")

    try:
        managed_records = cf_api.get_all_managed_records()
        if not managed_records:
            logger.info("No managed DNS records found in Cloudflare. Nothing to clean up.")
            return

        deleted_count = 0
        error_count = 0
        logger.info(f"Found {len(managed_records)} records to potentially delete:")
        for record in managed_records:
            logger.info(f"  - Will delete: {record['name']} (ID: {record['id']}) -> {record['content']}")
            if not dry_run:
                try:
                    cf_api.delete_dns_record(record['id'])
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Failed to delete DNS record {record['name']} (ID: {record['id']}): {e}")
                    error_count += 1
            else:
                deleted_count+=1 # Count as if deleted

        summary_verb = "Planned to delete" if dry_run else "Deleted"
        logger.info(f"Cleanup {summary_verb}: {deleted_count} records. Errors: {error_count}.")

    except Exception as e:
        logger.error(f"An error occurred during cleanup: {e}")

def validate_api_tokens(config: Dict[str, Any]):
    logger.info("Validating API tokens and connectivity...")
    valid_ts = False
    valid_cf = False

    # Validate Tailscale CLI access
    try:
        logger.info("Attempting to use Tailscale CLI...")
        ts_api = TailscaleAPI()
        ts_api.get_devices()  # A simple call to check if tailscale CLI is available
        logger.info("Tailscale CLI connectivity: OK")
        valid_ts = True
    except ValueError as e:
        logger.error(f"Tailscale CLI validation failed: {e}")
    except Exception as e:
        logger.error(f"Tailscale CLI validation failed with an unexpected error: {e}")

    # Validate Cloudflare API token
    try:
        logger.info("Attempting to connect to Cloudflare API...")
        cf_api = CloudflareAPI(
            api_token=config["cloudflare"]["api_token"],
            zone_id=config["cloudflare"]["zone_id"],
            domain=config["cloudflare"]["domain"],
            subdomain_prefix=config["cloudflare"]["subdomain_prefix"]
        )
        cf_api.get_dns_records(name="example-validation-record.nonexistent", record_type="TXT") # Test call
        logger.info("Cloudflare API token and connectivity: OK")
        valid_cf = True
    except ValueError as e: # Specific error from CloudflareAPI for auth/config issues
        logger.error(f"Cloudflare API validation failed: {e}")
    except Exception as e:
        logger.error(f"Cloudflare API validation failed with an unexpected error: {e}")

    if valid_ts and valid_cf:
        logger.info("All API validations passed.")
    else:
        logger.warning("One or more API validations failed. Check logs and configuration.")


def main():
    parser = argparse.ArgumentParser(description="Synchronize Tailscale devices to Cloudflare DNS.")
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG_PATH, help=f"Path to configuration file (default: {DEFAULT_CONFIG_PATH})"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Perform a dry run without making any changes to Cloudflare."
    )
    parser.add_argument(
        "--list-devices", action="store_true", help="List current Tailscale devices and exit."
    )
    parser.add_argument(
        "--cleanup-records", action="store_true", help="Remove all managed DNS records from Cloudflare and exit."
    )
    parser.add_argument(
        "--validate-config", action="store_true", help="Validate configuration and API token connectivity, then exit."
    )

    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except ValueError as e:
        logging.error(f"Configuration error: {e}") # Use basic logging if setup_logging fails
        sys.exit(1)
    except FileNotFoundError:
        logging.error(f"Configuration file not found at {args.config}. Please create one or specify the path.")
        sys.exit(1)


    setup_logging(config.get("sync", {}).get("log_level", "INFO"))
    logger.debug(f"Loaded configuration: {config}") # Log loaded config at debug level

    if args.validate_config:
        validate_api_tokens(config)
        sys.exit(0)

    # Initialize APIs after config validation (if not doing --validate-config which does its own init)
    try:
        ts_api = TailscaleAPI()  # No API token needed when using CLI
        cf_api = CloudflareAPI(
            api_token=config["cloudflare"]["api_token"],
            zone_id=config["cloudflare"]["zone_id"],
            domain=config["cloudflare"]["domain"],
            subdomain_prefix=config["cloudflare"]["subdomain_prefix"]
        )
    except KeyError as e:
        logger.error(f"Missing critical configuration for API initialization: {e}. Ensure your config file or environment variables are complete.")
        sys.exit(1)


    if args.list_devices:
        list_tailscale_devices(ts_api)
        sys.exit(0)

    if args.cleanup_records:
        cleanup_cloudflare_records(cf_api, dry_run=args.dry_run)
        sys.exit(0)

    # Single run
    try:
        synchronize_dns(ts_api, cf_api, dry_run=args.dry_run)
    except Exception as e:
        logger.error(f"Unhandled error during synchronization: {e}", exc_info=True)
        sys.exit(1)
    logger.info("Synchronization complete.")

if __name__ == "__main__":
    main()
