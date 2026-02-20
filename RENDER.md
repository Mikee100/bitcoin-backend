# Deploying the backend to Render

## Option A: One-click with Blueprint (recommended)

1. **Push your code** to a Git repo (GitHub, GitLab, or Bitbucket).

2. **In Render:** [Dashboard](https://dashboard.render.com) → **New** → **Blueprint**.

3. **Connect the repo** and select it. Render will detect `render.yaml` in the repo root.

4. **Apply the Blueprint.** Render creates a Web Service with:
   - **Root directory:** `backend`
   - **Build:** `pip install -r requirements.txt`
   - **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

5. **Set environment variables** in the service’s **Environment** tab:
   - **CORS_ORIGINS** – Your frontend origin(s), comma-separated, **no trailing slash**. Example: `https://bitcoin-frontend-livid.vercel.app`  
     Required so the browser can call the API. If missing or wrong, you’ll see “blocked by CORS policy” in the browser console.

6. After deploy, your API will be at `https://<service-name>.onrender.com`. Test:  
   `https://<service-name>.onrender.com/health`

---

## Option B: Manual Web Service

1. **New** → **Web Service** and connect your repo.

2. Configure:
   - **Root Directory:** `backend`
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

3. Add **CORS_ORIGINS** (and any other env vars) in the **Environment** tab.

---

## Database (SQLite vs PostgreSQL / Neon)

- **Default:** The app uses SQLite (`signals.db`). On Render’s free tier the filesystem is **ephemeral**, so the database is reset on each deploy or restart.
- **Persistent data:** Set **DATABASE_URL** in the Web Service’s **Environment** to a PostgreSQL connection string. For example:
  - **Neon:** Use the connection string from your Neon project (e.g. `postgresql://user:password@host/dbname?sslmode=require`). Copy it from Neon Dashboard → your project → Connection string.
  - **Render Postgres:** Add a PostgreSQL database in the Render dashboard and set **DATABASE_URL** to its **Internal Database URL**.
- **Important:** Never commit your real `DATABASE_URL` (or any password) to git. Set it only in Render’s Environment (or in a local `.env` file that is in `.gitignore`).

---

## Frontend

Point your Next.js app at the Render API URL, e.g.:

- **Env:** `NEXT_PUBLIC_API_URL=https://btc-signals-api.onrender.com`
- Use that for all API requests so they hit the deployed backend.

---

## Optional: Email alerts

To enable trade alerts, set in the Web Service’s environment:

- `EMAIL_ENABLED=true`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_EMAIL`  
(see `backend/.env.example`).
