---
name: gh-release
description: Automates version bumping in pyproject.toml and creating GitHub releases. Use when releasing a new version of the project.
---

# GitHub Release Skill

## Overview

This skill automates the process of creating a new release for this Python project. It updates the `version` in `pyproject.toml`, commits the change, and then creates a GitHub release using the `gh` CLI tool.

## Semantic Versioning (SemVer)

This project follows [Semantic Versioning](https://semver.org/) (SemVer) for releasing versions. SemVer uses a `MAJOR.MINOR.PATCH` format:

- **MAJOR** version when you make incompatible API changes.
- **MINOR** version when you add functionality in a backward compatible manner.
- **PATCH** version when you make backward compatible bug fixes.

Example: `1.0.0` -> `1.1.0` (new feature), `1.1.0` -> `1.1.1` (bug fix), `1.1.1` -> `2.0.0` (breaking change).

## Usage

All releases are cut from a `release/X.Y` branch.

### Major / Minor Release (e.g. `14.4.0` from `main`)

1. Create and checkout a new `release/X.Y` branch from `main`:
   ```bash
   git fetch origin
   git checkout -b release/14.4 origin/main
   ```
2. Run the release script with the new version:
   ```bash
   .agent/skills/gh-release/scripts/create-release.sh 14.4.0
   ```

### Patch Release (e.g. `14.3.1` with targeted cherry-picks)

1. Checkout the existing `release/X.Y` branch (or create it from the `X.Y.0` tag if it does not exist yet):
   ```bash
   git fetch origin
   git checkout release/14.3 || git checkout -b release/14.3 14.3.0
   ```
2. Cherry-pick the target commit(s) from `main`:
   ```bash
   git cherry-pick <commit-sha>
   ```
3. Run the release script with the patch version:
   ```bash
   .agent/skills/gh-release/scripts/create-release.sh 14.3.1
   ```

### What `create-release.sh` does

1. Ensures the working directory is clean and on a `release/*` branch.
2. Updates the `version` field in `pyproject.toml` to `<version>`.
3. Commits `pyproject.toml` with the message `chore(release): <version>`.
4. Pushes the `release/*` branch to `origin`.
5. Creates a GitHub release named `<version>` targeting that `release/*` branch with auto-generated release notes (`gh release create "<version>" --target "$BRANCH" --generate-notes`).

## Requirements

- `gh` CLI tool must be installed and authenticated.
- The script should be run from the root of the project repository.
- The script expects to find `pyproject.toml` in the root.

## Resources

### scripts/

- `create-release.sh`: The main script that performs the release automation.
