.PHONY: help setup install scrape filter run dev test-small mock-scrape mock-filter logs errors stats matched clean ollama-start ollama-pull

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup: ## Run full setup (install deps, browsers, create .env)
	@bash setup.sh

install: ## Install dependencies only
	uv sync
	uv run playwright install chromium

scrape: ## Scrape jobs to YAML (no LLM needed)
	uv run python -m job_scraper scrape

scrape-headless: ## Scrape jobs in headless mode (usage: make scrape-headless LIMIT=700)
	uv run python -m job_scraper scrape --headless

filter: ## Filter scraped jobs with LLM (no browser needed)
	uv run python -m job_scraper filter

run: ## Run full pipeline (scrape then filter, sequential)
	uv run python -m job_scraper run

dev: ## Scrape in visible browser mode
	HEADLESS=false uv run python -m job_scraper scrape

mock-scrape: ## Mock scrape (fake data, no real browser)
	MOCK_MODE=true DAILY_JOB_LIMIT=10 uv run python -m job_scraper scrape

mock-filter: ## Filter mock-scraped data with LLM
	MOCK_MODE=true uv run python -m job_scraper filter

logs: ## Show recent logs
	@tail -n 50 logs/scraper_$$(date +%Y-%m-%d).log

errors: ## Show recent errors
	@tail -n 50 logs/errors_$$(date +%Y-%m-%d).log 2>/dev/null || echo "No errors today!"

stats: ## Show job statistics from YAML
	@python3 -c "import yaml; d=yaml.safe_load(open('data/scraped_jobs.yaml')); jobs=d.get('jobs',[]); print('=== Job Statistics ==='); print(f'Total scraped: {len(jobs)}'); print(f'Pending:  {sum(1 for j in jobs if j.get(\"status\")==\"pending\")}'); print(f'Matched:  {sum(1 for j in jobs if j.get(\"status\")==\"matched\")}'); print(f'Rejected: {sum(1 for j in jobs if j.get(\"status\")==\"rejected\")}')" 2>/dev/null || echo "No data yet. Run 'make scrape' first."

matched: ## Show matched jobs
	@cat data/matched_jobs.txt 2>/dev/null || echo "No matched jobs yet"

clean: ## Clean logs and cached files
	rm -rf logs/*.log
	rm -rf __pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

clean-data: ## Delete scraped queue and URL cache to start fresh (keeps matched/rejected results)
	rm -f data/scraped_jobs.yaml data/.url_cache

ollama-start: ## Start Ollama service
	ollama serve

ollama-pull: ## Pull Ollama model (default: llama3.2:latest)
	ollama pull llama3.2:latest
