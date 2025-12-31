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
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Create vscode user with passwordless sudo
RUN useradd -m vscode \
    && echo "vscode ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/vscode \
    && chmod 0440 /etc/sudoers.d/vscode

# Switch to vscode user for remainder of build where appropriate
USER vscode
WORKDIR /workspace

# Copy dependency files
COPY --chown=vscode:vscode pyproject.toml uv.lock ./

# Install uv globally into user environment
RUN python -m ensurepip --upgrade \
    && python -m pip install --upgrade pip setuptools wheel \
    && pip install --user uv

# Copy the rest of the repo
COPY --chown=vscode:vscode . .

# Install Node LTS for Tailwind
USER root
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y nodejs \
    && npm install --global npm
USER vscode

# Default shell to bash
SHELL ["/bin/bash", "-c"]

# Expose Django and Tailwind dev ports
EXPOSE 8000 3000

# Default entrypoint
CMD ["bash"]
