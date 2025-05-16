# Configuration file parsing module

import json
import os
import logging
from typing import Dict, Any, Optional

DEFAULT_CONFIG_PATH = "config.json"
logger = logging.getLogger(__name__)

def load_config(path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """
    Loads configuration from a JSON file and environment variables.
    Environment variables override JSON settings.
    """
    config = {}
    if os.path.exists(path):
        with open(path, 'r') as f:
            try:
                config = json.load(f)
                if config is None:  # Handle empty JSON file
                    config = {}
                logger.info(f"Configuration loaded from {path}")
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing JSON file {path}: {e}")
                raise ValueError(f"Error parsing JSON file {path}: {e}")
    else:
        logger.warning(f"Config file {path} not found. Relying on environment variables.")

    # Ensure all main sections exist
    config.setdefault("tailscale", {})
    config.setdefault("cloudflare", {})
    config.setdefault("sync", {})

    # Override with environment variables
    # Tailscale settings (optional now, kept for backward compatibility)
    config["tailscale"]["tailnet"] = os.getenv("TAILSCALE_TAILNET", config["tailscale"].get("tailnet"))

    # Cloudflare settings
    config["cloudflare"]["api_token"] = os.getenv("CLOUDFLARE_API_TOKEN", config["cloudflare"].get("api_token"))
    config["cloudflare"]["zone_id"] = os.getenv("CLOUDFLARE_ZONE_ID", config["cloudflare"].get("zone_id"))
    config["cloudflare"]["domain"] = os.getenv("CLOUDFLARE_DOMAIN", config["cloudflare"].get("domain"))
    config["cloudflare"]["subdomain_prefix"] = os.getenv(
        "CLOUDFLARE_SUBDOMAIN_PREFIX", config["cloudflare"].get("subdomain_prefix", "ts")
    )

    # Sync settings
    interval_seconds = config["sync"].get("interval_seconds", 300)
    try:
        interval_seconds = int(os.getenv("SYNC_INTERVAL_SECONDS", interval_seconds))
    except (ValueError, TypeError):
        interval_seconds = 300
    config["sync"]["interval_seconds"] = interval_seconds

    config["sync"]["log_level"] = os.getenv(
        "SYNC_LOG_LEVEL", config["sync"].get("log_level", "INFO")
    ).upper()

    validate_config(config)
    return config

def validate_config(config: Dict[str, Any]) -> None:
    """
    Validates the presence of required configuration parameters.
    """
    required_cloudflare = ["api_token", "zone_id", "domain"]

    # Validate Cloudflare settings
    for key in required_cloudflare:
        if not config["cloudflare"].get(key):
            raise ValueError(
                f"Missing required Cloudflare configuration: {key}. "
                f"Set it in config.json or as CLOUDFLARE_{key.upper()} env var."
            )

    # Validate subdomain prefix
    if not config["cloudflare"].get("subdomain_prefix"):
        logger.warning("Cloudflare subdomain_prefix is not set, defaulting to 'ts'.")
        config["cloudflare"]["subdomain_prefix"] = "ts"

    # Validate sync settings
    if not isinstance(config["sync"]["interval_seconds"], int) or config["sync"]["interval_seconds"] <= 0:
        raise ValueError("sync.interval_seconds must be a positive integer.")

    valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if config["sync"]["log_level"] not in valid_log_levels:
        raise ValueError(f"sync.log_level must be one of {valid_log_levels}.")

    logger.info("Configuration validated successfully.")

# Example usage (optional, for direct script testing)
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Create a dummy config.json for testing
    dummy_config_content = """
{
  "tailscale": {
    "comment": "No API token needed when using Tailscale CLI",
    "tailnet": "example.com"
  },
  "cloudflare": {
    "api_token": "json_cloudflare_token",
    "zone_id": "json_zone_id",
    "domain": "json_domain.com",
    "subdomain_prefix": "json_ts"
  },
  "sync": {
    "interval_seconds": 600,
    "log_level": "DEBUG"
  }
}
"""
    with open(DEFAULT_CONFIG_PATH, 'w') as f:
        f.write(dummy_config_content)

    # Test case 1: Load from JSON
    print("--- Test Case 1: Load from JSON ---")
    cfg = load_config()
    print(f"Loaded config: {cfg}")
    assert cfg["cloudflare"]["zone_id"] == "json_zone_id"
    assert cfg["sync"]["interval_seconds"] == 600

    # Test case 2: Override with environment variables
    print("\n--- Test Case 2: Override with environment variables ---")
    os.environ["CLOUDFLARE_DOMAIN"] = "env_domain.com"
    os.environ["SYNC_LOG_LEVEL"] = "INFO"
    cfg_env = load_config()
    print(f"Loaded config with env overrides: {cfg_env}")
    assert cfg_env["cloudflare"]["domain"] == "env_domain.com"
    assert cfg_env["sync"]["log_level"] == "INFO"

    # Test case 3: Missing required fields (should raise ValueError)
    print("\n--- Test Case 3: Missing required fields ---")
    faulty_config_content = """
{
  "tailscale": {},
  "sync": {
    "interval_seconds": 300,
    "log_level": "INFO"
  }
}
"""
    with open("faulty_config.json", 'w') as f:
        f.write(faulty_config_content)
    try:
        load_config("faulty_config.json")
    except ValueError as e:
        print(f"Caught expected error: {e}")
        assert "Missing required Cloudflare configuration" in str(e)

    # Test case 4: Config file not found (should use env vars or defaults, or raise error if required are missing)
    print("\n--- Test Case 4: Config file not found ---")
    os.environ["CLOUDFLARE_API_TOKEN"] = "env_only_cf_token"
    os.environ["CLOUDFLARE_ZONE_ID"] = "env_only_cf_zone"
    os.environ["CLOUDFLARE_DOMAIN"] = "env_only_cf_domain"
    if os.path.exists("non_existent_config.json"):
        os.remove("non_existent_config.json")
    cfg_no_file = load_config("non_existent_config.json")
    print(f"Loaded config with no file: {cfg_no_file}")
    assert cfg_no_file["cloudflare"]["api_token"] == "env_only_cf_token"
    assert cfg_no_file["cloudflare"]["subdomain_prefix"] == "ts"  # Default
    assert cfg_no_file["sync"]["interval_seconds"] == 300  # Default

    # Cleanup dummy files
    if os.path.exists(DEFAULT_CONFIG_PATH):
        os.remove(DEFAULT_CONFIG_PATH)
    if os.path.exists("faulty_config.json"):
        os.remove("faulty_config.json")

    # Clear env vars used for testing
    del os.environ["CLOUDFLARE_DOMAIN"]
    del os.environ["SYNC_LOG_LEVEL"]
    del os.environ["CLOUDFLARE_API_TOKEN"]
    del os.environ["CLOUDFLARE_ZONE_ID"]

    print("\nAll config tests passed (if no asserts failed).")
