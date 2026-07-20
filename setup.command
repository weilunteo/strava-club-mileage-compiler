#!/bin/bash
# ============================================================
# STRAVA MILEAGE COMPILER - DIVISION SETUP (ONE-TIME)
# ============================================================
# Run this ONCE when everyone has joined the Strava club.
# Re-run only if new members join or roster.json changes.
#
# What happens:
#   1. Chrome opens to Strava login page
#   2. You log in
#   3. Script scrapes members and matches roster names
#   4. Writes division mapping to config.ini
# ============================================================

cd "$(dirname "$0")"

echo ""
echo "=========================================="
echo "  DIVISION SETUP (One-Time)"
echo "=========================================="
echo ""

python3 setup_divisions.py

echo ""
echo "=========================================="
echo "  Setup complete. From now on, run:"
echo "    ./run.command  (or double-click it)"
echo "=========================================="
echo ""
read -p "Press Enter to close..."
