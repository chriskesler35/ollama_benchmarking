ROLE: Coder

I'll push the project to GitHub for you. Let me initialize the repo, add files, commit, and push.

CMD: git init
CMD: git add .
CMD: git commit -m "Initial commit: Ollama Benchmark Tool

Features:
- CLI tool for benchmarking Ollama models
- Web UI with real-time progress via WebSocket
- Multi-category test prompts (reasoning, coding, creative, factual)
- JSON export of results
- Ranked results table with performance metrics
- Support for custom Ollama server URLs"
CMD: git remote add origin https://github.com/chriskesler35/ollama_benchmarking.git
CMD: git branch -M main
CMD: git push -u origin main