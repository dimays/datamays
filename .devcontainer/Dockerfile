# Use official Python 3.11 slim image
FROM python:3.11-slim-bookworm

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/.venv/bin:$PATH" \
    SHELL=/bin/bash

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    git \
    build-essential \
    ca-certificates \
    pkg-config \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# Copy dependency files to leverage Docker cache
COPY pyproject.toml uv.lock ./

# Install uv globally and create venv for the project
RUN python -m ensurepip --upgrade \
    && python -m pip install --upgrade pip setuptools wheel \
    && pip install uv

# Copy the rest of the repo
COPY . .

# Install Node LTS for Tailwind
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y nodejs \
    && npm install --global npm

# Default shell to bash
SHELL ["/bin/bash", "-c"]

# Expose Django and Tailwind dev ports
EXPOSE 8000 3000

# Default entrypoint (optional)
CMD ["bash"]
