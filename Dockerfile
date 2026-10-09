# Playwright's official image ships Chromium plus every system library it
# needs to actually launch headless - avoids hand-maintaining an apt-get list
# that silently goes stale. Tag must match the playwright pip version below.
FROM mcr.microsoft.com/playwright/python:v1.63.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Dashboard binds PORT if set (see dashboard/app.py); hosts like Render/Fly
# inject it. Ledger (sandbox/ledger_app) is spawned internally by the
# dashboard on :8000 - never exposed outside the container.
ENV PORT=5050
EXPOSE 5050

# GEMINI_API_KEY, DASHBOARD_USER, DASHBOARD_PASS are read from the real
# environment at runtime - set them as platform secrets, never bake them
# into the image or this file.
CMD ["python3", "-m", "dashboard.app"]
