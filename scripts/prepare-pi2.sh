#!/bin/sh
# Build the status page on a machine that has Node (laptop or Pi 5).
# The 32-bit Pi 2 image copies web/dist and does not run Node.
set -eu
cd "$(dirname "$0")/.."

if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm is required here. The Pi 2 cannot build the status page itself." >&2
  exit 1
fi

pnpm --dir web install --frozen-lockfile
pnpm --dir web build
test -f web/dist/index.html

echo "web/dist is ready. Copy this repo to the Pi 2, including web/dist, then on the Pi run:"
echo "  sudo python3 scripts/setup.py"
echo "  sudo ./scripts/install-pi2.sh"
