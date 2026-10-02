#!/bin/sh
# Build the Windows exe from WSL using the Windows Python. Output lands in dist/ as usual.
cd "$(dirname "$0")" && exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File build.ps1
