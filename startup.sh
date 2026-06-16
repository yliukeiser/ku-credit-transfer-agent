#!/bin/bash
# Azure App Service startup command.
# Set this as the "Startup Command" in App Service → Configuration → General settings.
gunicorn app:app --timeout 120 --workers 1 --bind 0.0.0.0:${PORT:-8000}
