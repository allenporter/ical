#!/bin/bash
set -e

VERSION=$1
if [ -z "$VERSION" ]; then
  echo "Usage: $0 <version>"
  exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$VERSION" == *.0 ]]; then
  if [[ "$BRANCH" != "main" ]]; then
    echo "Error: Major/minor releases ($VERSION) must be run from 'main'."
    exit 1
  fi
else
  EXPECTED_BRANCH="release/${VERSION%.*}"
  if [[ "$BRANCH" != "$EXPECTED_BRANCH" ]]; then
    echo "Error: Patch release ($VERSION) must be run from '$EXPECTED_BRANCH' (currently on '$BRANCH')."
    exit 1
  fi
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
git push -u origin "$BRANCH"

if [[ "$VERSION" == *.0 ]]; then
  RELEASE_BRANCH="release/${VERSION%.*}"
  git branch -f "$RELEASE_BRANCH" HEAD
  git push -u origin "$RELEASE_BRANCH"
fi

gh release create "$VERSION" --target "$BRANCH" --generate-notes
