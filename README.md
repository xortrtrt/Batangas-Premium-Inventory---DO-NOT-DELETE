# MeatTrack — Standalone Inventory Management System

A lightweight, standalone web application for meat processing facilities. Handles raw materials, recipes, batch production (with automated ingredient deductions), shelf-life expiry tracking (FEFO), inventory audit ledgers, and alerts.

Completely decoupled from sales, resellers, chatbots, and orders. Designed for zero-cost, zero-maintenance cloud hosting or local offline use.

---

## 🚀 Features

- **Inventory Workspace:** Create product recipes with multiple ingredient proportions, declared pack sizes, and batch codes.
- **Production Engine:** Produce finished product batches with automatic raw material stock deduction and validation triggers.
- **Shelf-Life & Batch Tracking:** First-Expired, First-Out (FEFO) ledger with automated near-expiry and critical-expiry warning indicators.
- **Stock Movements & Audit Ledger:** Immutable transaction log tracking balance before and after every movement.
- **Mobile PWA Ready:** Clients can open the site in Google Chrome on Android and tap **"Install App"** to get a full-screen home screen app icon.
- **Self-Contained Security:** No external SMS or email gateways required. Secure session management and password controls.

---

## 🛠️ Tech Stack

- **Backend:** FastAPI (Python 3.11+) + Uvicorn
- **Database:** PostgreSQL (supports Neon.tech serverless or local Postgres)
- **Frontend:** Jinja2 server-rendered templates, Vanilla CSS, Vanilla JS, Lucide icons, Chart.js
- **Mobile:** Progressive Web App (PWA) manifest & meta tags

---

## 🌐 5-Minute Free Deployment (Render + Neon.tech)

To host this **100% free forever** with zero cold-start delay and no data loss:

### 1. Database on Neon (Free Serverless PostgreSQL)
1. Go to [Neon.tech](https://neon.tech) and create a free account (using the client's email).
2. Create a new project named `meattrack-inventory`.
3. Copy the connection string (it looks like `postgresql://user:pass@ep-xyz.us-east-2.aws.neon.tech/neondb?sslmode=require`).

### 2. Web App on Render (Free Web Service)
1. Push this folder to a GitHub repository.
2. Go to [Render.com](https://render.com) and create a **New Web Service** connected to your repo.
3. Configure settings:
   - **Environment:** `Python`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT`
4. In **Environment Variables**, add:
   - `DATABASE_URL` = *(paste your Neon connection string)*
   - `SESSION_SECRET_KEY` = *(click Generate or enter a random string)*
   - `BUSINESS_TIMEZONE` = `Asia/Manila`
   - `CSRF_PROTECTION_ENABLED` = `true`
5. Click **Create Web Service**.

### 3. Initialize Database & Seed Admin
Once deployed, open the Render **Shell** tab (or run locally with `DATABASE_URL` pointing to Neon):
```bash
python tools/init_db.py
```
This automatically applies `database/schema.sql` and creates the default admin user:
- **Email:** `admin@batangaspremium.test`
- **Password:** `Admin123!@#`

### 4. Keep Awake 24/7 (Prevent Render Sleep)
1. Go to [cron-job.org](https://cron-job.org) or [UptimeRobot.com](https://uptimerobot.com) (both 100% free).
2. Create a monitor to ping:
   `https://your-service-name.onrender.com/health`
3. Set interval to **every 10 minutes**.
4. The site will now stay awake 24/7 with instant load times for your client!

---

## 💻 Running Locally (Offline Mode)

If the client prefers running it completely offline on a store computer:

1. Install Python 3.11+.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set your local PostgreSQL credentials in `.env` (or copy `.env.example`).
4. Initialize the database:
   ```bash
   python tools/init_db.py
   ```
5. Start the server:
   ```bash
   uvicorn app.main:create_app --factory --reload --port 8000
   ```
6. Open browser to `http://localhost:8000`.
