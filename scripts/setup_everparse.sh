#!/usr/bin/env bash
set -euo pipefail

# Download and extract EverParse v2025.06.05 into the project root.
# This artifact supports Linux x86_64 only.

EVERPARSE_VERSION="v2025.06.05"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"

# Detect platform
OS="$(uname -s)"
ARCH="$(uname -m)"

if [ "$OS" != "Linux" ]; then
  echo "ERROR: This artifact only supports Linux x86_64."
  echo "Unsupported OS: $OS"
  echo "Download EverParse manually from: https://github.com/project-everest/everparse/releases/tag/$EVERPARSE_VERSION"
  exit 1
fi

case "$ARCH" in
  x86_64|amd64)
    ARCH="x86_64"
    ;;
  *)
    echo "ERROR: This artifact only supports Linux x86_64."
    echo "Unsupported architecture: $ARCH"
    echo "Download EverParse manually from: https://github.com/project-everest/everparse/releases/tag/$EVERPARSE_VERSION"
    exit 1
    ;;
esac

ARCHIVE="everparse_${EVERPARSE_VERSION}_Linux_${ARCH}.tar.gz"
DOWNLOAD_URL="https://github.com/project-everest/everparse/releases/download/${EVERPARSE_VERSION}/${ARCHIVE}"

echo "Platform: Linux ($ARCH)"
echo "Downloading: $ARCHIVE"

# Check if everparse already exists
if [ -d "$PROJECT_DIR/everparse" ]; then
  echo "everparse/ directory already exists. Remove it first if you want to re-download."
  exit 0
fi

# Download
HTTP_CODE=$(curl -L --fail --silent --write-out "%{http_code}" -o "/tmp/$ARCHIVE" "$DOWNLOAD_URL")
if [ "$HTTP_CODE" != "200" ]; then
  echo "ERROR: Download failed (HTTP $HTTP_CODE)."
  echo "The Linux $ARCH build may not be available for $EVERPARSE_VERSION."
  echo "Check https://github.com/project-everest/everparse/releases/tag/$EVERPARSE_VERSION for available assets."
  rm -f "/tmp/$ARCHIVE"
  exit 1
fi

# Extract
tar -xzf "/tmp/$ARCHIVE" -C "$PROJECT_DIR"
rm "/tmp/$ARCHIVE"

# The archive extracts to a directory named like "everparse_v2025.06.05_Linux_x86_64".
# Rename it to everparse.
for d in "$PROJECT_DIR"/everparse*; do
  if [ -d "$d" ] && [ "$d" != "$PROJECT_DIR/everparse" ]; then
    mv "$d" "$PROJECT_DIR/everparse"
    break
  fi
done

if [ ! -d "$PROJECT_DIR/everparse" ]; then
  echo "WARNING: Could not auto-detect the extracted directory name."
  echo "Rename it manually to 'everparse/' in the project root."
  exit 1
fi

echo "EverParse installed to: $PROJECT_DIR/everparse"
echo "Done."
