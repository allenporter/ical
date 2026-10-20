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

To use this skill, execute the `create-release.sh` script from the root of your project with the desired new version number as an argument.

### Standard Release (from `main`)

```bash
.agent/skills/gh-release/scripts/create-release.sh 0.9.1
```

This will perform the following actions:

1. Ensure the working directory is clean and in the `main` (or `release/*`) branch.
2. Update the `version` field in `pyproject.toml` to `0.9.1`.
3. Stage the `pyproject.toml` file.
4. Commit the change with the message `chore(release): 0.9.1`.
5. Push the changes to the remote branch.
6. Create a GitHub release named `0.9.1` targeting that branch with auto-generated release notes using `gh release create "0.9.1" --target "$BRANCH" --generate-notes`.

### Targeted Patch Release (Cherry-Pick onto `release/X.Y`)

When `main` has accumulated additional changes that should not be included in a targeted patch release (for example, releasing `14.3.1` with a single bug fix on top of `14.3.0`):

1. Create and checkout a `release/X.Y` branch from the base release tag:
   ```bash
   git checkout -b release/14.3 14.3.0
   ```
2. Cherry-pick the specific commit(s) from `main`:
   ```bash
   git cherry-pick <commit-sha>
   ```
3. Run the release script on the `release/X.Y` branch:
   ```bash
   .agent/skills/gh-release/scripts/create-release.sh 14.3.1
   ```
   When run from a `release/*` branch, `create-release.sh` will publish the release from `release/X.Y` and automatically port the `pyproject.toml` version bump commit back to `main`.

## Requirements

- `gh` CLI tool must be installed and authenticated.
- The script should be run from the root of the project repository.
- The script expects to find `pyproject.toml` in the root.

## Resources

### scripts/

- `create-release.sh`: The main script that performs the release automation.
