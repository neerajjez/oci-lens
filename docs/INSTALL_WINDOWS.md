# Windows Installation

## Option A — Automated installer (PowerShell)

Open PowerShell as Administrator:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\install.ps1
```

## Option B — Manual steps

**1. Open PowerShell and navigate to the project folder**

```powershell
cd C:\opt\oci-lens
```

**2. Create and activate a virtual environment**

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If you see an execution policy error, run this first:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Your prompt will show `(venv)` when active. To deactivate later: `deactivate`.

**3. Install dependencies**

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

**4. Create config files**

```powershell
Copy-Item config\config.example.yaml config\config.yaml
Copy-Item config\.env.example config\.env
```

**5. Edit `config\config.yaml`** in Notepad or your preferred editor.

**6. Edit `config\.env`** — add your SMTP password if required.

**7. Validate**

```powershell
python main.py validate-config
```

**8. Test connectivity (no API calls made)**

```powershell
python main.py collect --dry-run
```

## Scheduling (Task Scheduler)

Open PowerShell as Administrator, then:

**Install the scheduled task:**

```powershell
python scripts\setup_schedule.py install
```

Creates a Windows Task Scheduler entry named `OCI-Cost-Optimizer` that runs every 15 days at 08:00.

**Check status:**

```powershell
python scripts\setup_schedule.py status
```

**Remove:**

```powershell
python scripts\setup_schedule.py uninstall
```

**Preview the Task Scheduler XML without installing:**

```powershell
python scripts\setup_schedule.py install --dry-run
```

You can also view and manage the task in the Windows Task Scheduler GUI under **Task Scheduler Library**.
