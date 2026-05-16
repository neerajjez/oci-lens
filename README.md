# oci-lens

A CLI tool that connects to OCI tenancies, collects compute, storage, and cost data across compartments, runs an analytics pipeline to identify over-provisioned or idle resources, and delivers per-compartment PDF reports via email on a configurable schedule.

## What you get

*   **PDF per compartment**: Clean summaries of your cloud spend and infrastructure health.
*   **Per-instance cost breakdown**: Exact mapping of your compute, block, and boot volumes to actual costs.
*   **Utilisation recommendations**: Actionable insights to downsize, upsize, or investigate resources based on real thresholds.
*   **Scheduled email delivery**: Automated drops straight to your inbox, so you don't have to log in.

## Why I built this

I manage Oracle Cloud for several tenancies. Every month, finance asks the same question: "where did the budget go, and which resources can we trim?"

The existing options were either log into the console and click around for an hour, or pay for a third-party observability platform we didn't need 90% of. I just wanted a simple, automated answer.

So I built this. It collects the data, runs the numbers, and drops a PDF in your inbox — one per compartment, on a schedule.

If you're in a similar position, it should save you the same time it saves me.

## Requirements

| Requirement | Version |
|---|---|
| Python | 3.9+ |
| OCI SDK | Authenticated via config file or instance principal |
| SMTP server | For email delivery (optional) |

## Quickstart

The shortest path from clone to first report. For detailed manual steps or Windows instructions, see [docs/INSTALL_LINUX.md](docs/INSTALL_LINUX.md) or [docs/INSTALL_WINDOWS.md](docs/INSTALL_WINDOWS.md).

```bash
git clone <repo-url> /opt/oci-lens
cd /opt/oci-lens

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Configure
cp config/config.example.yaml config/config.yaml
# Edit config/config.yaml to add your tenancy details

# Run
python main.py run
```

## Configuration

Settings live in `config/config.yaml`. Sensitive values go in `config/.env`. Here's why the key settings matter:

```yaml
# Days of metrics and cost history to collect. More days mean better averages but longer API fetch times.
collection_period_days: 30

# OCI Monitoring aggregation resolution (minutes). 60 is usually a good balance of granularity and speed.
metrics_interval_minutes: 60

# Utilisation thresholds that drive recommendations. Tweak these based on your risk appetite.
thresholds:
  cpu_underutilized_pct: 20    # p95 CPU below this → DOWNSIZE recommendation
  memory_underutilized_pct: 30
  cpu_overcommit_pct: 85       # p95 CPU above this → UPSIZE_OR_INVESTIGATE

# Output and retention for the generated PDFs.
report:
  output_dir: ./reports
  retention_days: 90

# Email delivery settings.
email:
  enabled: true
  smtp_host: smtp.example.com
  smtp_port: 587
  from_address: oci-reports@example.com
  to_addresses:
    - recipient@example.com
  encryption: tls          # none | tls | starttls
  auth_method: login       # none | login
  use_tls: true
  attach_pdf: true         # attach the PDF to each email

# How often setup_schedule.py runs the pipeline.
schedule:
  interval_days: 15

# Currency conversion rates (USD base). Useful if you bill internally in another currency.
fx_rates:
  INR: 0.012

# Save disk space by cleaning up old raw JSON files.
cleanup:
  keep_raw_days: 7

# Map credentials to environments. One entry per OCI tenancy.
tenancies:
  - name: "TenancyA"
    oci_config_path: /path/to/oci/config_a
    oci_profile: DEFAULT
    home_region: us-ashburn-1
    compartments:
      - id: ocid1.compartment.oc1..REPLACE
        name: "Production"
        region: us-ashburn-1
      - id: ocid1.compartment.oc1..REPLACE2
        name: "Development"
        region: eu-frankfurt-1   # each compartment can be in a different region
```

## CLI Reference

Run all commands from the project root with the venv activated.

```bash
python main.py <command> [options]
```

### Core Pipeline

`run` — Full orchestrated pipeline
Runs the complete workflow: collect → analyze → report → notify. Supports resuming interrupted runs.

```bash
python main.py run [--dry-run] [--skip-notify] [--resume RUN_ID]
```

| Flag | Description |
|---|---|
| `--dry-run` | Skip all API calls and email; write `.eml` draft instead |
| `--skip-notify` | Run pipeline but skip email/notification dispatch |
| `--resume RUN_ID` | Resume a previously interrupted run from where it stopped |

### Individual Stages

`collect` — Fetch data from OCI APIs
Collects compute instances, block volumes, boot volumes, object storage buckets, and cost records. Writes one raw JSON file per compartment to `reports/raw/<tenancy>/`.

```bash
python main.py collect [--dry-run] [--tenancy NAME] [--compartment NAME]
```

| Flag | Description |
|---|---|
| `--dry-run` | Validate config and auth without making any API calls |
| `--tenancy NAME` | Collect only for this tenancy (case-insensitive name match) |
| `--compartment NAME` | Collect only for this compartment (case-insensitive name match) |

**Examples:**

```bash
# Collect all tenancies and compartments
python main.py collect

# Collect only one compartment
python main.py collect --tenancy "TenancyA" --compartment "Production"

# Validate config and auth only (no API calls)
python main.py collect --dry-run
```

`resource-report` — Generate PDF reports
Reads the latest raw JSON files and generates one PDF per compartment. Sends each PDF by email unless `--skip-email` is passed. Automatically replaces older PDFs for the same compartment.

```bash
python main.py resource-report [--tenancy NAME] [--compartment NAME] [--input FILE] [--output FILE] [--skip-email]
```

| Flag | Description |
|---|---|
| `--tenancy NAME` | Generate reports only for this tenancy |
| `--compartment NAME` | Generate report only for this compartment |
| `--input FILE` | Use a specific `*_raw.json` file instead of auto-detecting latest |
| `--output FILE` | Write PDF to this path (only valid with `--input`) |
| `--skip-email` | Generate PDFs only, do not send emails |

**Examples:**

```bash
# Generate and email all compartment reports
python main.py resource-report

# Generate PDF only (no email) for one compartment
python main.py resource-report --tenancy "TenancyA" --compartment "Production" --skip-email

# Process a specific raw file
python main.py resource-report --input reports/raw/tenancy_a/production_20260513_120000_raw.json --skip-email
```

`analyze` — Run analytics engine
Runs the 6-stage analytics pipeline on raw JSON data and produces cost optimisation recommendations with confidence scoring.

```bash
python main.py analyze [--input FILE] [--validate-only] [--explain OCID] [--previous FILE]
```

| Flag | Description |
|---|---|
| `--input FILE` | Specific raw JSON file (default: latest in `reports/raw/`) |
| `--validate-only` | Check data quality only, skip recommendations |
| `--explain OCID` | Print detailed explanation for one instance |
| `--previous FILE` | Compare against a previous analytics run |

`report` — Generate analytics PDF
Generates a full cost-analytics PDF from an analytics JSON output file.

```bash
python main.py report [--input FILE] [--output FILE]
```

### Utilities

`health` — System health check
Checks Python version, filesystem writability, disk space, OCI credentials, SMTP connectivity, and last run status.

```bash
python main.py health [--verbose] [--json]
```

| Flag | Description |
|---|---|
| `--verbose` | Show latency and detail for each check |
| `--json` | Output results as JSON (for monitoring integrations) |

Exit codes: `0` = all OK · `1` = warnings · `2` = critical failure

```bash
# Human-readable
python main.py health --verbose

# JSON output
python main.py health --json
```

`validate-config` — Validate configuration file
Validates `config/config.yaml` structure and values without making any API calls.

```bash
python main.py validate-config
```

`status` — Show recent pipeline runs
Displays the last N runs (default: 5) with status, duration, and any errors.

```bash
python main.py status [--last N]
```

`logs` — View log output

```bash
python main.py logs [--tail N] [--follow]
```

| Flag | Description |
|---|---|
| `--tail N` | Show last N lines (default: 50) |
| `--follow` | Stream log output live (Ctrl+C to stop) |

## Deployment

### Running Manually

Activate your venv, then execute the full workflow:

```bash
source venv/bin/activate
python main.py run
```

### Scheduling (cron)

Install the scheduled task to automate runs:

```bash
python scripts/setup_schedule.py install
```

This installs a cron entry that runs `python main.py run` at 08:00 on the schedule defined by `schedule.interval_days` in `config.yaml` (default: every 15 days).

```bash
# Check status
python scripts/setup_schedule.py status

# Remove
python scripts/setup_schedule.py uninstall

# Preview without installing
python scripts/setup_schedule.py install --dry-run
```

### Docker

Docker Compose is preferred. It uses host bind mounts — no named volumes. Config is mounted read-only; `reports/` and `logs/` are read-write on the host.

Ensure the required host directories exist before starting:

```bash
mkdir -p reports logs
```

Build and start the main service (runs `python main.py run`):

```bash
docker compose up --build -d
```

Check health:

```bash
docker compose exec oci-resource-report python main.py health --verbose
```

View logs:

```bash
docker compose logs -f oci-resource-report
```

Stop:

```bash
docker compose down
```

The `collect` and `report` services use the `tools` profile so they never start automatically with `docker compose up`. Use `docker compose run --rm` to invoke them on demand:

```bash
# One-shot collect (without starting the persistent service)
docker compose run --rm collect

# One-shot report generation + email
docker compose run --rm report
```

If you must use bare `docker run`:

```bash
# Collect
docker run --rm \
  -v ./config:/app/config:ro \
  -v ./reports:/app/reports \
  -v ./logs:/app/logs \
  oci-resource-report:latest collect
```

## Multi-Tenancy Setup

oci-lens supports multiple tenancies out of the box. Authentication is tried in this order:

1.  **Instance Principal**: Used automatically when running on an OCI compute instance. No config file needed.
2.  **Config file**: Used when not on OCI compute.

Each tenancy requires its own OCI credentials file and a block under `tenancies:` in `config/config.yaml`. Each compartment can be in a different OCI region.

```yaml
tenancies:
  - name: "europe"
    oci_config_path: /opt/oci-lens/config/oci_europe
    oci_profile: DEFAULT
    home_region: eu-paris-1
    compartments:
      - id: ocid1.compartment.oc1..aaaa...
        name: "EU-Production"
        region: eu-paris-1
      - id: ocid1.compartment.oc1..bbbb...
        name: "UK-Production"
        region: uk-london-1
```

> `home_region` must be the tenancy's subscription region — this is where the OCI Cost/Usage API is available. Cost data is fetched once per tenancy from the `home_region` and automatically filtered per compartment.

## Email Setup

Configure SMTP in `config/config.yaml`:

```yaml
email:
  enabled: true
  smtp_host: smtp.example.com
  smtp_port: 587
  from_address: oci-reports@example.com
  to_addresses:
    - analyst@example.com
  encryption: tls
  auth_method: login
  use_tls: true
  attach_pdf: true
```

Add your SMTP password to `config/.env`:

```ini
SMTP_PASSWORD=your_password_here
```

Emails arrive with the following subject format:

```text
OCI Resource Reports | <Tenancy> | <Compartment> | 13 Apr 2026 – 13 May 2026
```

> Each per-compartment PDF is typically 300–500 KB. If your mail server enforces a strict size limit, set `attach_pdf: false` to send the report summary in the email body only.

## Logging

Set format and level in `config/.env`:

```ini
LOG_FORMAT=json    # json (production) | human (development)
LOG_LEVEL=INFO     # DEBUG | INFO | WARNING | ERROR
```

Tail live logs or view recent run history:

```bash
python main.py logs --follow
python main.py status --last 10
```

## Project Structure

```text
.
├── config/                  # Configuration YAMLs and .env files
├── docs/                    # Extended documentation and runbooks
├── scripts/                 # OS-specific installation and scheduling scripts
├── src/
│   ├── analytics/           # 6-stage analytics pipeline
│   ├── collector/           # OCI API collectors (compute, storage, cost)
│   ├── models/              # Typed dataclasses and schemas
│   ├── notifier/            # Email dispatch logic
│   ├── orchestrator/        # Pipeline runner and step management
│   ├── reporter/            # PDF report builder using ReportLab
│   └── utils/               # Logging, health checks, date helpers
├── tests/                   # Pytest test suite
├── main.py                  # CLI entry point
├── requirements.txt         # Python dependencies
├── pyproject.toml           # Project metadata
└── Dockerfile               # Container build instructions
```

## Contributing

This is my personal tool, open-sourced because someone else probably has the same problem. PRs are welcome, but don't expect a roadmap or issue triage SLA. Fork it and make it yours.
