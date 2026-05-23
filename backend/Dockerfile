# EcoSeek API gateway — lightweight FastAPI backend.
# Builds independently from this repo; no agenticSeek dependency.
#
#   docker build -t ecoseek-api backend/
#   docker compose up --build ecoseek-api
#
# Target: <200 MB image, <60 s cold build on a typical laptop.

FROM python:3.11-slim

# Non-root user for defence-in-depth.
RUN groupadd --gid 1000 ecoseek \
    && useradd --uid 1000 --gid ecoseek --no-create-home ecoseek

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code.
COPY config.py api.py ./

RUN chown -R ecoseek:ecoseek /app

USER ecoseek

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 3000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "3000"]
