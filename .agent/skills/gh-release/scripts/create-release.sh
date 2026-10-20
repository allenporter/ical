#!/bin/bash
set -e

VERSION=$1
if [ -z "$VERSION" ]; then
  echo "Usage: $0 <version>"
  exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$BRANCH" != release/* ]]; then
  echo "Error: You must be on a 'release/*' branch to create a release (e.g. 'release/14.3')."
  exit 1
fi

if [[ -n $(git status -s) ]]; then
  echo "Error: Working directory is not clean. Please commit or stash your changes."
  exit 1
fi

if ! command -v gh &> /dev/null; then
    echo "gh command could not be found, please install it first"
    exit 1
fi

FILE_PATH="pyproject.toml"

if [ ! -f "$FILE_PATH" ]; then
    echo "Error: $FILE_PATH not found."
    exit 1
fi

# Update version in pyproject.toml using sed
# This assumes the format: version = "X.Y.Z"
update_version() {
  if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS requires an empty string argument for -i
    sed -i '' "s/^version = \".*\"/version = \"$VERSION\"/" "$FILE_PATH"
  else
    sed -i "s/^version = \".*\"/version = \"$VERSION\"/" "$FILE_PATH"
  fi

  if [ -f "uv.lock" ]; then
    git add "$FILE_PATH" uv.lock
  else
    git add "$FILE_PATH"
  fi
  git commit -m "chore(release): $VERSION"
}

update_version
git push -u origin "$BRANCH"
gh release create "$VERSION" --target "$BRANCH" --generate-notes

echo "Porting version bump ($VERSION) back to main..."
git fetch origin main
git checkout main
git pull --ff-only origin main
update_version
git push origin main
git checkout "$BRANCH"
