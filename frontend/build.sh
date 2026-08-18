#!/bin/bash
cd /root/.hermes/workspace/xianyu-ops/frontend
echo "=== CLEAN ==="
rm -rf node_modules package-lock.json
echo "=== INSTALL (NODE_ENV=development) ==="
NODE_ENV=development npm install --include=dev --no-audit --no-fund 2>&1 | tail -8
echo "=== CHECK VITE ==="
ls node_modules/vite/package.json 2>&1 && echo "VITE_FOUND" || echo "VITE_MISSING"
echo "=== BUILD ==="
node_modules/.bin/vite build 2>&1 | tail -30
echo "=== BUILD_FINISHED ==="
