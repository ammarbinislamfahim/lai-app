#!/usr/bin/env bash
# ==============================================================================
# One-Command GitHub Publisher for Leaf Area & LAI Analyzer (v1.5.6)
# Usage:
#   ./publish_to_github.sh
#   (or: ./publish_to_github.sh ammarbinislamfahim lai-app)
# ==============================================================================
set -euo pipefail

RAW_USER="${1:-ammarbinislamfahim}"
RAW_REPO="${2:-lai-app}"

# Strip accidental angle brackets if passed in quotes
GH_USER="${RAW_USER//</}"
GH_USER="${GH_USER//>/}"
REPO_NAME="${RAW_REPO//</}"
REPO_NAME="${REPO_NAME//>/}"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

VERSION="$(python3 -c "import app.config as c; print(c.SOFTWARE_VERSION)")"
TAG="v${VERSION}"
REPO_URL="https://github.com/${GH_USER}/${REPO_NAME}.git"

echo "==> [1/4] Ensuring GitHub repository URL (${GH_USER}/${REPO_NAME}) in README.md..."
sed -i "s|<YOUR_GITHUB_USERNAME>/<YOUR_REPO_NAME>|${GH_USER}/${REPO_NAME}|g" README.md
sed -i "s|<YOUR_REPO_NAME>|${REPO_NAME}|g" README.md
sed -i "s|<YOUR_GITHUB_USERNAME>|${GH_USER}|g" README.md

echo "==> [2/4] Initializing Git repository and committing v${VERSION}..."
if [ ! -d ".git" ]; then
    git init -b main || (git init && git branch -M main)
fi

if ! git config user.name >/dev/null 2>&1; then
    git config user.name "${GH_USER}"
fi
if ! git config user.email >/dev/null 2>&1; then
    git config user.email "${GH_USER}@users.noreply.github.com"
fi

git add -A
if git diff --cached --quiet; then
    echo "    Working tree already committed."
else
    git commit -m "Release ${TAG}: Leaf Area & LAI Analyzer"
fi

git tag -f "${TAG}"

echo "==> [3/4] Configuring remote origin (${REPO_URL}) and pushing..."
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    echo "    GitHub CLI (gh) is authenticated — creating/pushing ${GH_USER}/${REPO_NAME}..."
    if ! gh repo view "${GH_USER}/${REPO_NAME}" >/dev/null 2>&1; then
        gh repo create "${GH_USER}/${REPO_NAME}" --public --source=. --remote=origin --push
    else
        if git remote get-url origin >/dev/null 2>&1; then
            git remote set-url origin "${REPO_URL}"
        else
            git remote add origin "${REPO_URL}"
        fi
        git push -u origin main
    fi
    git push -f origin "${TAG}"
else
    if git remote get-url origin >/dev/null 2>&1; then
        git remote set-url origin "${REPO_URL}"
    else
        git remote add origin "${REPO_URL}"
    fi
    echo "    Pushing main branch and tag ${TAG} to ${REPO_URL}..."
    echo "    ( Note: Make sure https://github.com/new has an empty repository named '${REPO_NAME}', )"
    echo "    ( and sign in with your GitHub username '${GH_USER}' + Personal Access Token when prompted. )"
    git push -u origin main
    git push -f origin "${TAG}"
fi

echo "==> [4/4] Done!"
echo "    Repository URL : https://github.com/${GH_USER}/${REPO_NAME}"
echo "    Actions Release: https://github.com/${GH_USER}/${REPO_NAME}/actions"
