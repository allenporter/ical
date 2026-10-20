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

- **Major / Minor releases (`X.Y.0`)** are cut from `main`, which commits `chore(release): X.Y.0` to `main`, pushes `release/X.Y` at that commit, and creates the GitHub release.
- **Patch releases (`X.Y.Z`)** are cut from `release/X.Y` by cherry-picking fixes onto `release/X.Y` and running `create-release.sh X.Y.Z` without touching `main`.

### Major / Minor Release (e.g. `14.4.0` from `main`)

1. Checkout `main` and pull the latest changes:
   ```bash
   git checkout main
   git pull --ff-only origin main
   ```
2. Run the release script with the new `X.Y.0` version:
   ```bash
   .agent/skills/gh-release/scripts/create-release.sh 14.4.0
   ```
   This commits `chore(release): 14.4.0` to `main`, creates and pushes the `release/14.4` branch at that commit, and creates the `14.4.0` GitHub release.

### Patch Release (e.g. `14.3.1` with targeted cherry-picks)

1. Checkout the `release/X.Y` branch:
   ```bash
   git fetch origin
   git checkout release/14.3
   git pull --ff-only origin release/14.3
   ```
   *(Note: If the `release/X.Y` branch was not yet created for an older `X.Y.0` tag, create it from that tag first with `git checkout -b release/14.3 14.3.0`.)*
2. Cherry-pick the target commit(s) from `main`:
   ```bash
   git cherry-pick <commit-sha>
   ```
3. Run the release script with the patch version:
   ```bash
   .agent/skills/gh-release/scripts/create-release.sh 14.3.1
   ```
   This commits `chore(release): 14.3.1` on `release/14.3`, pushes `release/14.3`, and creates the `14.3.1` GitHub release targeting `release/14.3`.

## Requirements

- `gh` CLI tool must be installed and authenticated.
- The script should be run from the root of the project repository.
- The script expects to find `pyproject.toml` in the root.

## Resources

### scripts/

- `create-release.sh`: The main script that performs the release automation.
