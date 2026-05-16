# Linux / macOS Installation

## Option A — Automated installer

The quickest way to get started is using the automated installer script, which creates the virtual environment and installs dependencies for you.

```bash
git clone <repo-url> /opt/oci-lens
cd /opt/oci-lens
bash scripts/install.sh
```

The script detects Python 3.9+, creates a virtual environment, installs dependencies, scaffolds config files, validates the config, and optionally installs the scheduler.

## Option B — Manual steps

**1. Clone or copy the project**

```bash
git clone <repo-url> /opt/oci-lens
cd /opt/oci-lens
```

**2. Create and activate a virtual environment**

```bash
python3 -m venv venv
source venv/bin/activate
```

Your prompt will change to show `(venv)`. All subsequent commands must be run inside the activated venv.

**3. Install dependencies**

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**4. Create config files**

```bash
cp config/config.example.yaml config/config.yaml
cp config/.env.example config/.env
```

**5. Edit `config/config.yaml`** — add your tenancies, compartments, and email settings.

**6. Edit `config/.env`** — add your SMTP password if required:

```
SMTP_PASSWORD=your_smtp_password
LOG_FORMAT=human
```

**7. Validate configuration**

```bash
python main.py validate-config
```

**8. Test connectivity (no API calls made)**

```bash
python main.py collect --dry-run
```

## Scheduling (cron)

**Install the scheduled task:**

```bash
python scripts/setup_schedule.py install
```

Installs a cron entry that runs `python main.py run` at 08:00 on the schedule defined by `schedule.interval_days` in `config.yaml` (default: every 15 days).

**Check status:**

```bash
python scripts/setup_schedule.py status
```

**Remove:**

```bash
python scripts/setup_schedule.py uninstall
```

**Preview without installing:**

```bash
python scripts/setup_schedule.py install --dry-run
```

Scheduled run output is logged to `logs/scheduled_run.log`.
