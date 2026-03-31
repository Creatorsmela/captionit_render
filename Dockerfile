FROM node:20-slim

RUN apt-get update && apt-get install -y \
    chromium ffmpeg python3 python3-pip python3-venv \
    fonts-noto fonts-noto-cjk \
    --no-install-recommends && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Node deps (Remotion)
COPY remotion/package*.json ./remotion/
RUN cd remotion && npm ci

COPY remotion/ ./remotion/

# Python deps
COPY requirements.txt .
RUN python3 -m venv venv && venv/bin/pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV REMOTION_DIR=/app/remotion
ENV PYTHONUNBUFFERED=1
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

EXPOSE 8001

CMD ["venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
