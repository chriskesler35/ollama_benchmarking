#!/bin/bash
# Script to initialize git and push to GitHub

# Initialize git if not already done
git init

# Add all files
git add .

# Create initial commit
git commit -m "Initial commit: Ollama Benchmark Tool

Features:
- CLI tool for benchmarking Ollama models
- Web UI with real-time progress via WebSocket
- Multi-category test prompts (reasoning, coding, creative, factual)
- JSON export of results
- Ranked results table with performance metrics
- Support for custom Ollama server URLs"

# Add remote
git remote add origin https://github.com/chriskesler35/ollama_benchmarking.git

# Push to main branch
git branch -M main
git push -u origin main
