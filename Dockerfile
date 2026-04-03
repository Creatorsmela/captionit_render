FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg python3 python3-pip python3-venv \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN python3 -m venv venv && venv/bin/pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY remotion/ ./remotion/

# Install Node.js dependencies for Remotion wrapper
RUN cd /app/remotion && npm install --production

ENV PYTHONUNBUFFERED=1

EXPOSE 8001

CMD ["venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
