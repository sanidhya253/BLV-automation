#!/bin/bash
# ============================================================
# BLV Hook Installer
# Installs the pre-push hook into your git repository
# ============================================================

echo "Installing BLV pre-push hook..."

# Check if we're in a git repo
if [ ! -d ".git" ]; then
    echo "[ERROR] Not a git repository. Run 'git init' first."
    exit 1
fi

# Copy hook
cp git-hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push

echo ""
echo "BLV pre-push hook installed successfully!"
echo ""
echo "How it works:"
echo "  - Every time you run 'git push', the BLV scan runs automatically"
echo "  - If quality gate FAILS → push is BLOCKED"
echo "  - If quality gate PASSES → push goes through"
echo ""
echo "To remove the hook later: rm .git/hooks/pre-push"
echo ""
