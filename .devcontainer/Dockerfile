# Use official Python 3.12 slim image
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

# -----------------------------
# Core tools
# -----------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    git \
    build-essential \
    ca-certificates \
    pkg-config \
    python3-distutils \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------
# Node.js LTS for Tailwind / frontend builds
# -----------------------------
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------
# Install uv system-wide
# -----------------------------
ENV UV_INSTALL_DIR=/usr/local/bin
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# -----------------------------
# Create non-root dev user
# -----------------------------
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME

USER $USERNAME
WORKDIR /workspace
