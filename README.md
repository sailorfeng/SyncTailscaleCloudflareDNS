# SyncTailscaleCloudflare

**SyncTailscaleCloudflare** is a Python application that automatically synchronizes your Tailscale device hostnames and their corresponding IP addresses to Cloudflare DNS as 'A' records. This allows you to access your Tailscale devices using custom, memorable domain names.

## Features

*   **Tailscale Integration**: Reads device information (hostnames, IPs) directly from the local Tailscale CLI.
*   **Cloudflare DNS Management**: Creates, updates, and deletes 'A' records in your Cloudflare DNS zone.
*   **Configurable**: Flexible configuration via a `config.json` file and environment variables (environment variables take precedence).
*   **Subdomain Prefixing**: Allows specifying a subdomain prefix (e.g., `ts`) so records are created as `device-name.ts.yourdomain.com`.
*   **Comprehensive Logging**: Detailed logging of operations, errors, and warnings.
*   **Command-Line Interface (CLI)**:
    *   **One-Time Sync**: Perform a single synchronization run.
    *   **Watch Mode**: Periodically sync devices in the background.
    *   **List Devices**: Display current Tailscale devices and their details.
    *   **Cleanup Records**: Remove all DNS records managed by this tool from Cloudflare.
    *   **Validate Configuration**: Check `config.json` and connectivity.
    *   **Dry Run Mode**: Simulate synchronization or cleanup operations without making any actual changes to Cloudflare DNS.

## Prerequisites

*   Python 3.7+
*   A Tailscale account with the Tailscale CLI installed and logged in on the device running this application.
*   A Cloudflare account and an [API token](https://developers.cloudflare.com/api/tokens/create/).
    *   The token needs `Zone:Read` and `DNS:Edit` permissions for the specific zone you want to manage.
*   Your Cloudflare Zone ID.
    *   You can find this on the "Overview" page for your domain in the Cloudflare dashboard (bottom right).
*   Your registered domain name managed by Cloudflare.

## Setup

1.  **Clone the repository (or download the source code):**
    ```bash
    git clone https://github.com/your-username/SyncTailscaleCloudflare.git # Replace with actual repo URL if applicable
    cd SyncTailscaleCloudflare
    ```

2.  **Install dependencies:**
    It's recommended to use a virtual environment.
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    pip install -r requirements.txt
    ```

3.  **Configure the application:**
    Copy the example configuration file:
    ```bash
    cp config.json.example config.json
    ```
    Edit `config.json` with your specific details:

    ```json
    {
      "tailscale": {
        "comment": "No API token is needed when using the Tailscale CLI"
      },
      "cloudflare": {
        "api_token": "YOUR_CLOUDFLARE_API_TOKEN",
        "zone_id": "YOUR_CLOUDFLARE_ZONE_ID",
        "domain": "yourdomain.com",
        "subdomain_prefix": "ts"
      },
      "sync": {
        "interval_seconds": 300,
        "log_level": "INFO"
      }
    }
    ```

    **Notes:**
    - This tool now uses the local Tailscale CLI to get device information, so a Tailscale API token is no longer needed.
    - `subdomain_prefix` is optional and defaults to "ts" if not set. Records will be created as `<device_name>.<subdomain_prefix>.<domain>`.

    **Alternatively, use environment variables:**
    All configuration options can be set via environment variables. They will override values in `config.json`.

    *   `CLOUDFLARE_API_TOKEN`
    *   `CLOUDFLARE_ZONE_ID`
    *   `CLOUDFLARE_DOMAIN`
    *   `CLOUDFLARE_SUBDOMAIN_PREFIX` (optional, defaults to "ts")
    *   `SYNC_INTERVAL_SECONDS` (optional, defaults to 300)
    *   `SYNC_LOG_LEVEL` (optional, defaults to "INFO")

## Usage

The application is run from the command line using `python src/sync.py`.

```bash
python src/sync.py [OPTIONS]
```

**Available Options:**

*   `--config FILE_PATH`: Path to the configuration file (default: `config.json`).
*   `--watch`: Run in watch mode, synchronizing periodically based on `interval_seconds` in the config.
*   `--dry-run`: Perform a dry run. Simulates operations without making any changes to Cloudflare. Useful for testing.
*   `--list-devices`: List current Tailscale devices and their details, then exit.
*   `--cleanup-records`: Remove all DNS 'A' records managed by this tool (matching `*.subdomain_prefix.domain`) from Cloudflare, then exit. Use with `--dry-run` to see what would be deleted.
*   `--validate-config`: Validate the configuration settings and test API token connectivity to Tailscale and Cloudflare, then exit.
*   `-h`, `--help`: Show the help message and exit.

**Examples:**

1.  **Perform a one-time synchronization:**
    ```bash
    python src/sync.py
    ```

2.  **Perform a dry run to see what changes would be made:**
    ```bash
    python src/sync.py --dry-run
    ```

3.  **Run in watch mode to sync every 5 minutes (default interval):**
    ```bash
    python src/sync.py --watch
    ```

4.  **Run in watch mode with a custom interval (e.g., every 10 minutes, configured in `config.json` or env var):**
    First, set `interval_seconds`: 600 in `config.json` or `export SYNC_INTERVAL_SECONDS=600`.
    ```bash
    python src/sync.py --watch
    ```

5.  **List your Tailscale devices:**
    ```bash
    python src/sync.py --list-devices
    ```

6.  **Validate your configuration and API tokens:**
    ```bash
    python src/sync.py --validate-config
    ```

7.  **See which DNS records would be cleaned up (dry run):**
    ```bash
    python src/sync.py --cleanup-records --dry-run
    ```

8.  **Clean up (delete) all managed DNS records from Cloudflare:**
    **Warning**: This will delete DNS records. Be sure this is what you intend.
    ```bash
    python src/sync.py --cleanup-records
    ```

9.  **Use a custom configuration file path:**
    ```bash
    python src/sync.py --config /path/to/your/custom_config.json
    ```

## Logging

The application logs its activities to standard output. The log level can be configured using the `log_level` setting in `config.json` or the `SYNC_LOG_LEVEL` environment variable.

## Development & Testing

To install development dependencies (like `pytest` and `pytest-mock`):
```bash
pip install -r requirements-dev.txt
```

Run unit tests:
```bash
python -m pytest
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
