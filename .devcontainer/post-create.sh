#!/usr/bin/env bash
set -e

echo "🔧 Ensuring uv environment..."
uv --version

# Create or sync venv if project already has config
if [ -f "pyproject.toml" ]; then
  echo "📦 Syncing Python dependencies with uv..."
  uv sync
fi

if [ -f "package.json" ]; then
  echo "📦 Installing Node dependencies..."
  npm install
fi

echo "✅ Dev container setup complete."
