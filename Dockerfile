# Lightweight Python — NO Playwright, NO Chromium
FROM python:3.11-slim

WORKDIR /app

# Copy and install requirements
COPY po_sniper/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot files
COPY po_sniper/ /app/

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
