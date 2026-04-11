FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies needed by pycairo/weasyprint/xhtml2pdf in Linux containers.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libcairo2-dev \
    libpango1.0-dev \
    libgdk-pixbuf-2.0-dev \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency list first for better layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy project files
COPY projttgs /app/projttgs
COPY entrypointscript.sh /app/entrypointscript.sh
RUN chmod +x /app/entrypointscript.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypointscript.sh"]
