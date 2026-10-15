#!/usr/bin/env bash
# Build the build/ folder for deploying to AWS Lambda (python3.13, arm64)
#
# Usage (run from the server folder):
#   ./scripts/build_lambda.sh
#
# - Installs the libraries in requirements-lambda.txt as Linux (manylinux) builds,
#   so building on a Mac produces files that run on Lambda
# - Copies only the code the API needs at runtime. .env, .venv/ and scripts/ are deliberately excluded
set -euo pipefail

cd "$(dirname "$0")/.."            # server/
BUILD_DIR="${BUILD_DIR:-build}"
PYTHON_VERSION="3.13"              # must match Runtime in template.yaml
APP_DIRS=(configs core db routers schemas services)

echo "→ clearing ${BUILD_DIR}/"
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

echo "→ installing libraries (Linux arm64, Python ${PYTHON_VERSION})"
python3 -m pip install \
  --requirement requirements-lambda.txt \
  --target "${BUILD_DIR}" \
  --platform manylinux2014_aarch64 \
  --platform manylinux_2_28_aarch64 \
  --implementation cp \
  --python-version "${PYTHON_VERSION}" \
  --only-binary=:all: \
  --upgrade \
  --quiet

echo "→ copying code"
cp main.py "${BUILD_DIR}/"
for dir in "${APP_DIRS[@]}"; do
  cp -R "${dir}" "${BUILD_DIR}/"
done
find "${BUILD_DIR}" -type d -name "__pycache__" -prune -exec rm -rf {} +

echo "✓ build ready: ${BUILD_DIR}/ ($(du -sh "${BUILD_DIR}" | cut -f1))"
echo "  next step: sam deploy --parameter-overrides SupabaseServiceRoleKey=..."
