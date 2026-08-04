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

---

# AI Agent CLI (showdown.py)

`showdown.py` is a conversational AI agent powered by Groq that talks to the connector API.
You describe what you want in plain English and the agent figures out which API calls to make.

## Additional .env keys required

Add these to your `.env` file alongside the existing keys:

```env
GROQ_API_KEY=your_groq_api_key_here
FASTAPI_BASE_URL=http://localhost:8001
```

Get a free Groq API key at https://console.groq.com

## Start the connector API first

The agent calls the connector in the background, so it must be running:

```powershell
uvicorn connector:app --reload --port 8001
```

## Start the agent

```powershell
python showdown.py
```

A `You:` prompt appears. Type your request and press Enter.

```
You: show me all gpus
You: show me gpus on runpod
You: show me my pods on novita
You: create a pod on runpod with an RTX 4090
You: exit
```

## How the agent handles missing information

When the agent needs a value it cannot infer (e.g. which provider, which pod),
it pauses and shows you a numbered list to pick from:

```
[Select provider] — 2 options available:
  1. runpod
  2. novita

Pick a provider (number or exact value): 1
```

Type the number or the exact value and press Enter.

## Destructive or paid operations require confirmation

For create, stop, delete operations the agent shows a summary and asks before executing:

```
[Confirm] About to execute: create_pod
  Params: {
    "provider": "runpod",
    "name": "my-pod",
    ...
  }
Approve? (yes/no): yes
```

Type `yes` to proceed or `no` to cancel.

## Supported commands (natural language examples)

| What you want | Example prompt |
|---|---|
| List all GPUs across providers | `show me all gpus` |
| List GPUs for one provider | `show me runpod gpus` |
| List your pods | `show me my pods on novita` |
| Get pod details | `get details for pod abc123 on runpod` |
| Create a pod | `create a pod on runpod with an RTX 4090 named my-pod` |
| Stop a pod | `stop pod abc123 on novita` |
| Delete a pod | `delete pod abc123 on runpod` |
| List your volumes | `show my volumes on runpod` |
| Create a volume | `create a 20gb volume called my-vol on runpod` |
| Delete a volume | `delete volume xyz on novita` |
| List providers | `what providers are available` |

## Exit

Type `exit`, `quit`, or `q` at the `You:` prompt.