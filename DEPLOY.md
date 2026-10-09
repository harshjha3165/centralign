# Deploying the dashboard

What this is: steps to put `dashboard/` on the public internet, behind a password, on a host that
can actually run it (Python + a real Chromium browser + a long-lived process). **Not GitHub
Pages** - that's static-file hosting only and can't run any of this.

Verified locally, before you deploy anywhere:
- The auth gate: unauthenticated requests get `401` once `DASHBOARD_USER`/`DASHBOARD_PASS` are
  set; correct Basic Auth credentials get through. Open (no prompt) if those vars are unset, which
  is intentional for local use and wrong for a public deployment - **always set both before
  deploying**.
- `PORT` env var binding: the app binds `0.0.0.0:$PORT` when `PORT` is set (what a host injects),
  and stays on `127.0.0.1` otherwise (so running it locally never accidentally exposes it to your
  LAN).
- **Not verified: the actual Docker image.** Docker isn't installed in the environment this was
  built in, so the `Dockerfile` itself hasn't been built or run. Build it locally and confirm it
  starts before pushing to a host - don't skip straight to a cloud deploy on an unbuilt image.

```bash
docker build -t centralign-dashboard .
docker run --rm -p 5050:5050 \
  -e PORT=5050 -e GEMINI_API_KEY=... -e DASHBOARD_USER=demo -e DASHBOARD_PASS=... \
  centralign-dashboard
# open http://localhost:5050 - should prompt for the username/password you set
```

## Before you deploy, understand the cost/abuse surface

- There's no per-user rate limit beyond "one run at a time, globally" and whatever your Gemini
  key's own free-tier quota enforces (15 req/min, 500/day on `gemini-3.1-flash-lite` - see
  README §8.2). Anyone with the password can burn through that quota with a few runs.
- Every tool call costs real API usage. The password gate is the only thing standing between
  "a private demo" and "a public one someone could hammer." Use a real password, not `admin`.
- The worker only ever browses `localhost:8000` inside its own container (`policy.py`'s domain
  allowlist enforces this) - it cannot be pointed at other sites, so the *browsing* surface is
  safe regardless of who's using the dashboard. The *API spend* is the actual risk.

## Steps (Render.com, Docker-based host, free tier)

Render was picked for the simplest "connect a repo, it builds your Dockerfile" flow. Fly.io is a
reasonable alternative with more control over VM size if the free tier's RAM is too tight for
Chromium (headless Chromium wants roughly 512MB+ comfortably). **Check current free-tier limits
and pricing yourself at signup** - they change, and this doc may be out of date by the time you
read it.

1. **Push this repo to GitHub.** Render deploys from a GitHub (or GitLab) repo it can read.
   ```bash
   git init -b main                      # if not already a repo
   git add -A
   git commit -m "Initial commit"
   gh repo create <your-repo-name> --private --source=. --push
   # or: create the repo on github.com, then `git remote add origin <url> && git push -u origin main`
   ```
   Double-check `.env` is **not** in what you're about to push (`git status` should never show it;
   it's gitignored, but if you ever renamed it or copied the key elsewhere, check by hand).

2. **Render dashboard → New → Web Service → connect your repo.** Render should auto-detect the
   `Dockerfile` at the repo root and offer "Docker" as the environment. If it doesn't, select
   Docker manually.

3. **Set environment variables** (Render dashboard → your service → Environment):
   - `GEMINI_API_KEY` — your key
   - `DASHBOARD_USER` — a username you choose
   - `DASHBOARD_PASS` — a real password, not reused from anywhere else
   - Leave `PORT` alone; Render injects it automatically and `dashboard/app.py` reads it.

4. **Deploy.** First build will take a few minutes (the Playwright base image is large). Render
   gives you a `https://<your-service>.onrender.com` URL. Open it, log in with the Basic Auth
   prompt, and you should see the same dashboard that ran locally.

5. **If the free tier spins down on inactivity** (common on free web-service tiers), the first
   request after idle time will be slow (cold start, often 20-60s) while it boots back up - that's
   normal, not a bug. If Chromium fails to launch with an out-of-memory-style error, the instance
   is too small; move to a paid tier with more RAM.

## If you'd rather not expose a live key at all

Record the demo locally instead (see the README's demo-video section) and share the video, or
share read-only `examples/*/replay.html` files, which need no server, no key, and no ongoing cost.
That's genuinely a reasonable choice, not a lesser one — it's what "receipts, not promises" already
gives you without taking on hosting risk.
