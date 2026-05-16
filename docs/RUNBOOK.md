# Operations Runbook — OCI Resource Report

## Health Check

```bash
python3 main.py health --verbose
```
Exit 0 = all OK, 1 = warning, 2 = critical failure.

---

## Manual One-Off Report

```bash
# Collect for a single compartment
python3 main.py collect --tenancy knovosglobal --compartment "Devlin-OCI"

# Generate PDF (no email)
python3 main.py resource-report --tenancy knovosglobal --compartment "Devlin-OCI" --skip-email

# Generate PDF + send email
python3 main.py resource-report --tenancy knovosglobal --compartment "Devlin-OCI"
```

---

## Scheduled Run Not Firing

1. Check scheduler status:
   ```bash
   python3 scripts/setup_schedule.py status
   ```
2. If not installed, reinstall:
   ```bash
   python3 scripts/setup_schedule.py install
   ```
3. Check scheduled run log:
   ```bash
   tail -50 logs/scheduled_run.log
   ```
4. Test dry-run manually:
   ```bash
   python3 main.py collect --dry-run
   ```

---

## Email Not Arriving

1. Run health check — SMTP section shows connection status:
   ```bash
   python3 main.py health --verbose
   ```
2. Test SMTP port manually:
   ```bash
   nc -zv cmail.knovos.com 25
   ```
3. Check report was generated (PDF exists in `reports/resource/`):
   ```bash
   ls -lh reports/resource/*/*
   ```
4. Re-send without re-collecting:
   ```bash
   python3 main.py resource-report --tenancy <name> --compartment "<name>"
   ```

---

## OCI Authentication Failure

Error: `ProfileNotFound` or `ConfigFileNotFound`

1. Verify config file paths in `config/config.yaml` under `tenancies[*].oci_config_path`
2. Check the profile name matches what's in the OCI config file:
   ```bash
   grep '^\[' /opt/oci_resource_report/config/config
   ```
3. Validate OCI connectivity:
   ```bash
   python3 main.py collect --dry-run
   ```
4. If running on OCI compute, instance principal auth is attempted first — ensure the dynamic group policy grants the required permissions.

---

## Disk Full / Low Disk Space

1. Check current usage:
   ```bash
   df -h /opt/oci_resource_report
   du -sh reports/*/
   ```
2. Manual cleanup (remove reports older than 7 days):
   ```bash
   find reports/raw reports/analytics reports/resource -mtime +7 -type f -delete
   ```
3. Trim run log to last 200 entries:
   ```bash
   tail -200 reports/run_log.jsonl > /tmp/run_log_trim.jsonl && mv /tmp/run_log_trim.jsonl reports/run_log.jsonl
   ```
4. Reduce retention in `config/config.yaml`:
   ```yaml
   cleanup:
     keep_raw_days: 3
   ```

---

## Recent Run History

```bash
python3 main.py status --last 10
```

Or view raw log:
```bash
tail -20 reports/run_log.jsonl | python3 -m json.tool
```

---

## Onboarding a New Compartment

1. Add the compartment to `config/config.yaml` under the appropriate tenancy:
   ```yaml
   compartments:
     - id: ocid1.compartment.oc1..REPLACE
       name: "New-Compartment"
       region: us-ashburn-1
   ```
2. Validate config:
   ```bash
   python3 main.py validate-config
   ```
3. Run collection for the new compartment only:
   ```bash
   python3 main.py collect --tenancy <tenancy-name> --compartment "New-Compartment"
   ```
4. Generate and review the report:
   ```bash
   python3 main.py resource-report --tenancy <tenancy-name> --compartment "New-Compartment" --skip-email
   ```
