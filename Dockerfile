# MarketLens — full image with the Playwright browser layer baked in.
# The Playwright base image ships Chromium + all OS deps, so `docker compose up`
# gives a colleague the complete app (including e-commerce scraping) in one command.
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

WORKDIR /app

# Install Python deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium

# App source.
COPY . .

# Persistent data lives here; docker-compose mounts a named volume onto it.
ENV MARKETLENS_DATA_DIR=/data
ENV PORT=8000
RUN mkdir -p /data

EXPOSE 8000

# Bind is controlled by MODE (solo=127.0.0.1, team=0.0.0.0). In Docker you almost
# always want it reachable from the host, so default the container to team-friendly
# binding via HOST; override MODE=team + ADMIN_PASSWORD for real auth.
ENV HOST=0.0.0.0

CMD ["python", "app.py"]
