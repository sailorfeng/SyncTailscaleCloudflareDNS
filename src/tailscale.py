# Tailscale CLI interaction module

import json
import subprocess
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class TailscaleAPI:
    def __init__(self, api_token: Optional[str] = None, tailnet: Optional[str] = None):
        """
        Initialize the Tailscale interface.
        Note: api_token parameter is kept for backward compatibility but is no longer used.
        """
        self._tailnet = tailnet
        # We don't use these anymore, but keep them for backward compatibility
        self.api_token = api_token
        self.base_url = None

    def get_tailnet(self) -> str:
        """
        Returns the tailnet name if explicitly provided during initialization.
        This method is kept for backward compatibility but is no longer necessary
        when using the CLI tool.
        """
        if self._tailnet:
            return self._tailnet
        logger.info("Tailnet not explicitly configured. Using local tailscale client.")
        return "local"

    def _run_tailscale_command(self, args: List[str]) -> Dict[str, Any]:
        """
        Runs a tailscale command with the given arguments and returns the parsed JSON output.
        
        Args:
            args: List of command arguments to pass to tailscale
            
        Returns:
            Parsed JSON data from the command output
            
        Raises:
            ValueError: If the command fails or returns invalid JSON
            Exception: For other unexpected errors
        """
        cmd = ["tailscale"] + args
        try:
            logger.debug(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON output from tailscale command: {e}")
                logger.debug(f"Command output: {result.stdout}")
                raise ValueError(f"Invalid JSON output from tailscale command: {e}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Tailscale command failed with exit code {e.returncode}: {e.stderr}")
            raise ValueError(f"Tailscale command failed: {e.stderr}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while running tailscale command: {e}")
            raise

    def get_devices(self) -> List[Dict[str, Any]]:
        """
        Retrieves all devices in the tailnet using the 'tailscale status --json' command.
        Filters for devices that are connected and have an IP address.
        
        Returns:
            List of device dictionaries with standardized keys
        """
        try:
            status_data = self._run_tailscale_command(["status", "--json"])
            peer_data = status_data.get("Peer", {})
            self_data = status_data.get("Self", {})

            active_devices = []

            # Add all peers (other devices in the tailnet)
            for device_id, device in peer_data.items():
                if not device.get("TailscaleIPs"):
                    logger.debug(f"Device {device.get('HostName', 'UnknownDevice')} has no IP addresses. Skipping.")
                    continue

                # Find the first suitable IPv4 address
                ipv4_address = None
                for ip in device.get("TailscaleIPs", []):
                    if "." in ip and (ip.startswith("100.") or not ip.startswith("169.254")):
                        ipv4_address = ip
                        break

                if ipv4_address:
                    # Extract real hostname from FQDN if available
                    fqdn = device.get("DNSName", "")
                    real_hostname = fqdn.split(".")[0] if fqdn else device.get("HostName", "unknown")
                    active_devices.append({
                        "id": device_id,
                        "name": device.get("HostName", "unknown"),  # Short hostname
                        "fqdn": fqdn,  # FQDN from Tailscale
                        "ip": ipv4_address,
                        "os": device.get("OS", "unknown"),
                        "lastSeen": device.get("LastSeen", ""),
                        "real_hostname": real_hostname
                    })
                else:
                    logger.debug(f"Device {device.get('HostName', 'UnknownDevice')} has no suitable IPv4 address. Addresses: {device.get('TailscaleIPs')}. Skipping.")

            # Add the local device (Self)
            if self_data:
                # Find the first suitable IPv4 address for the local device
                local_ipv4 = None
                for ip in self_data.get("TailscaleIPs", []):
                    if "." in ip and (ip.startswith("100.") or not ip.startswith("169.254")):
                        local_ipv4 = ip
                        break

                if local_ipv4:
                    fqdn = self_data.get("DNSName", "")
                    real_hostname = fqdn.split(".")[0] if fqdn else self_data.get("HostName", "unknown")
                    active_devices.append({
                        "id": self_data.get("ID", ""),
                        "name": self_data.get("HostName", "unknown"),
                        "fqdn": fqdn,
                        "ip": local_ipv4,
                        "os": self_data.get("OS", "unknown"),
                        "lastSeen": "current",  # Local device is always "current"
                        "real_hostname": real_hostname
                    })
                else:
                    logger.debug(f"Local device has no suitable IPv4 address. Addresses: {self_data.get('TailscaleIPs')}. Skipping.")

            logger.info(f"Retrieved {len(active_devices)} active devices from Tailscale.")
            return active_devices
        except ValueError as e:
            logger.error(f"Failed to get devices from Tailscale: {e}")
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred while fetching Tailscale devices: {e}")
            raise

# Example usage (for direct script testing)
if __name__ == "__main__":
    import os
    import sys

    # Corrected relative import for testing when run as a script
    try:
        from config import load_config
    except ImportError:
        # Fallback for running directly from src or if PYTHONPATH is not set up for ..
        sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
        from config import load_config

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

    # Config file path for configuration settings (not required for basic functionality)
    config_file_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')

    try:
        print("\nAttempting to fetch devices using Tailscale CLI...")
        tailscale_api = TailscaleAPI()

        # The tailnet info is no longer needed but we'll keep the message for backward compatibility
        print(f"Using local Tailscale client")

        devices = tailscale_api.get_devices()
        if devices:
            print(f"\nSuccessfully retrieved {len(devices)} devices:")
            for device in devices:
                print(f"  - Name: {device['name']}, IP: {device['ip']}, OS: {device['os']}")
        else:
            print("No active devices found.")

    except ValueError as e:
        print(f"Error: {e}")
    except FileNotFoundError:
        print(f"Could not find Tailscale CLI. Make sure it's installed and in your PATH.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
