# datamays.com

Personal portfolio and data engineering showcase site.

This repository hosts the code for [datamays.com](https://datamays.com), built with Django, Tailwind, and other supporting tools. The project uses **uv** for Python dependency management and a **VS Code Dev Container** for a consistent development environment.

---

## Table of Contents

- [Requirements](#requirements)
- [Getting Started](#getting-started)
- [Running the Project Locally](#running-the-project-locally)
- [Adding Dependencies](#adding-dependencies)
- [Contributing](#contributing)

---

## Requirements

- [Docker](https://www.docker.com/get-started) (for dev container)
- [VS Code](https://code.visualstudio.com/)
- [VS Code Remote - Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

> Optionally, you can run without the dev container, but using the container ensures consistent versions of Python, Node, and dependencies.

---

## Getting Started

1. **Clone the repository**:

```bash
git clone https://github.com/dimays/datamays.git
cd datamays
```

2. **Open the repo in VS Code** and reopen in the dev container:

```
Command Palette → "Dev Containers: Reopen in Container"
```

3. **Post-create setup**:

The dev container automatically runs `.devcontainer/post-create.sh`, which will:

- Install Node.js dependencies (`npm install`)
- Sync Python dependencies using uv (`uv sync` → generates `.venv`)

You should see `.venv/` created and `uv.lock` generated if it doesn’t exist yet.

---

## Running the Project Locally

### Django Server

```bash
uv run python manage.py runserver 0.0.0.0:8000
```

Visit [http://localhost:8000](http://localhost:8000) in your browser.

### Tailwind / Frontend Dev Server

```bash
npm run dev
```

Visit [http://localhost:3000](http://localhost:3000) for Tailwind hot-reload.

---

## Adding / Updating Dependencies

**Python Packages**

- Add a package:

```bash
uv add <package-name>
```

- Remove a package:

```bash
uv remove <package-name>
```

- Sync dependencies and update `.venv`:

```bash
uv sync
```

> All Python dependencies are defined in `pyproject.toml` and locked in `uv.lock`.

**Node Packages**

```bash
npm install <package-name>
npm remove <package-name>
```

---

## Contributing

1. Fork the repository and create a branch for your feature/fix:

```bash
git checkout -b feature/my-new-feature
```

2. Make changes in the dev container to ensure environment consistency.
3. Test your changes locally.
4. Commit changes and push to your fork:

```bash
git add .
git commit -m "Add feature XYZ"
git push origin feature/my-new-feature
```

5. Open a Pull Request against `main`.

> All commits should follow standard formatting and pass any pre-commit checks if configured.

---

## Notes

- The dev container ensures that Python, Node, and other tooling are consistent across developers and CI/CD.  
- `.venv` should **not** be committed. Only `pyproject.toml` and `uv.lock` should be tracked.
- Docker + VS Code Dev Containers are strongly recommended for first-time setup.
