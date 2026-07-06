#!/bin/bash
# ============================================================
# STRAVA WEEKLY MILEAGE COMPILER
# ============================================================
# Double-click this file every Monday to update the Google Sheet.
#
# What happens:
#   1. Chrome opens to Strava login page
#   2. You log in (enter email + verification code from your email)
#   3. Script scrapes the data and updates Google Sheet
#   4. Done!
# ============================================================

cd "$(dirname "$0")"

echo ""
echo "=========================================="
echo "  STRAVA WEEKLY MILEAGE COMPILER"
echo "=========================================="
echo ""

# Pull latest code from GitHub (in case of updates)
git pull origin main 2>/dev/null

# Install/update dependencies quietly
pip3 install -r requirements.txt -q 2>/dev/null

echo ""
echo "  Chrome will open now."
echo "  Log in to Strava, then wait here."
echo ""
echo "=========================================="
echo ""

python3 main.py

echo ""
echo "=========================================="
if [ $? -eq 0 ]; then
    echo "  ✓ DONE! Google Sheet has been updated."
    echo "  You can close this window."
else
    echo "  ✗ Something went wrong."
    echo "  Take a screenshot and send to Megan."
fi
echo "=========================================="
echo ""
read -p "Press Enter to close..."
