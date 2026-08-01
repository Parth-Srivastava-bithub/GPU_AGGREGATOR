# GPU Aggregate Backend

## Prerequisites

- Python 3.11+
- Google Chrome
- RunPod Account
- RunPod API Key
- Novita API Key

---

# 1. Clone Project

```bash
git clone <repo-url>
cd GPU_AGGREGATE/backend
```

---

# 2. Create Virtual Environment

```powershell
python -m venv .venv

.venv\Scripts\activate
```

---

# 3. Install Dependencies

```powershell
pip install -r requirements.txt
```

---

# 4. Configure Environment

Create a `.env` file.

```env
RUNPOD_API_KEY=xxxxxxxxxxxxxxxx
NOVITA_API_KEY=xxxxxxxxxxxxxxxx
```

---

# 5. Start Chrome in Remote Debugging Mode

Run the following command in **PowerShell**.

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
   --remote-debugging-port=9222 `
   --user-data-dir="C:\Users\user\Documents\GPU_AGGREGATE\chrome_cdp_profile"
```

A new Chrome profile will open.

---

# 6. Login to RunPod

Open

```
https://console.runpod.io/deploy
```

Login using GitHub (or your preferred login method).

After login:

- Stay on the Deploy page.
- Do **not** close this Chrome window.
- The scraper connects to this browser through the Chrome DevTools Protocol (CDP).

---

# 7. Initialize Database

```powershell
python database/db.py
```

This creates:

```
database/gpu_catalog.db
```

---

# 8. Start Scheduler

```powershell
python scheduler.py
```

The scheduler will:

### Initial Run

- Scrape RunPod Deploy page
- Fetch RunPod GraphQL data
- Merge both datasets
- Store into SQLite
- Fetch Novita GPUs
- Store into SQLite

### Background Jobs

Every **1 hour**

- Full RunPod scrape
- RunPod GraphQL refresh
- Merge
- Upsert database
- Novita full refresh

Every **10 minutes**

- Refresh RunPod live fields
- Refresh Novita live fields

Updated fields:

- Availability
- Deployable
- Hourly Price
- Community Price
- Secure Price

---

# Notes

The browser must remain open while the scheduler is running.

If the browser is closed:

- Run the Chrome command again.
- Login again.
- Restart the scheduler.

---

# Database

SQLite database location:

```
database/gpu_catalog.db
```

Contains GPU information from all supported providers using a common schema.

---

# Current Providers

- RunPod
- Novita

More providers can be added by implementing the common provider schema.