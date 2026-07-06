#!/usr/bin/env bash
# download_ecoregions.sh — Download One Earth Bioregions Framework 2017
#
# Downloads Ecoregions2017.zip from Google Cloud Storage and extracts
# the shapefile into the target directory for use by maxent_pipeline.R
# and niche_pipeline.R as the M mask (accessible area).
#
# Usage:
#   bash download_ecoregions.sh [target_dir]
#
# Default target: /media/reumanlab/TOSHIBA_EXT/ecoregions

set -euo pipefail

TARGET_DIR="${1:-/media/reumanlab/TOSHIBA_EXT/ecoregions}"
URL="https://storage.googleapis.com/teow2016/Ecoregions2017.zip"
ZIP_FILE="${TARGET_DIR}/Ecoregions2017.zip"

echo "=== One Earth Ecoregions 2017 Download ==="
echo "Source: ${URL}"
echo "Target: ${TARGET_DIR}"

# Create target directory
mkdir -p "${TARGET_DIR}"

# Check if shapefile already exists
if [ -f "${TARGET_DIR}/Ecoregions2017.shp" ]; then
    echo "Ecoregions2017.shp already exists in ${TARGET_DIR}"
    echo "Skipping download. Delete the .shp to force re-download."
    ls -lh "${TARGET_DIR}"/Ecoregions2017.*
    exit 0
fi

# Download
echo "Downloading Ecoregions2017.zip..."
if command -v wget &>/dev/null; then
    wget -q --show-progress -O "${ZIP_FILE}" "${URL}"
elif command -v curl &>/dev/null; then
    curl -L -o "${ZIP_FILE}" "${URL}"
else
    echo "ERROR: Neither wget nor curl found. Install one and retry."
    exit 1
fi

# Verify download
if [ ! -f "${ZIP_FILE}" ]; then
    echo "ERROR: Download failed — ${ZIP_FILE} not found"
    exit 1
fi
echo "Downloaded: $(du -h "${ZIP_FILE}" | cut -f1)"

# Extract
echo "Extracting..."
unzip -o "${ZIP_FILE}" -d "${TARGET_DIR}"

# Verify shapefile components
REQUIRED_EXTS=("shp" "shx" "dbf" "prj")
MISSING=0
for ext in "${REQUIRED_EXTS[@]}"; do
    if ! ls "${TARGET_DIR}"/*.${ext} &>/dev/null; then
        echo "WARNING: No .${ext} file found after extraction"
        MISSING=$((MISSING + 1))
    fi
done

if [ "${MISSING}" -gt 0 ]; then
    echo "WARNING: ${MISSING} shapefile component(s) missing"
    echo "Contents of ${TARGET_DIR}:"
    ls -la "${TARGET_DIR}/"
else
    echo "All shapefile components present"
fi

# Cleanup zip
rm -f "${ZIP_FILE}"

# Report
echo ""
echo "=== Ecoregions ready ==="
ls -lh "${TARGET_DIR}"/Ecoregions2017.* 2>/dev/null || ls -lh "${TARGET_DIR}"/*.shp 2>/dev/null
echo ""
echo "Path for R pipelines: --ecoregions ${TARGET_DIR}"
