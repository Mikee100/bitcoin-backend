#!/usr/bin/env bash

# Simple dev runner for the FastAPI backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

