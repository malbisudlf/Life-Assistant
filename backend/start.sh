#!/bin/sh
set -e

# Arrancar el backend
exec uvicorn main:app --host 0.0.0.0 --port 8080
