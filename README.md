# Intelligent Job Scraper

A modern, AI-powered job scraping tool for public job boards (for now, theprotocol.it, more boards are coming) with intelligent LLM-based filtering.

## Features

- **AI-Powered Filtering**: Uses OPENAI to match jobs to your requirements
- **Rate Limiting**: Configurable daily limits and polite scraping behavior
- **Persistent Storage**: Saves matched and rejected jobs to separate files
- **Mock Mode**: Test the system with fake data before going live

## Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) - Fast Python package manager

## Installation (WSL)


1. **Install uv**: https://docs.astral.sh/uv/getting-started/installation/
2. **Navigate to project directory and install dependencies with**:
   ```bash
   uv sync
   ```
3. **activate virtual environment**
    ```bash
    source .venv/bin/activate
    ```
4. **Verify installation**
   ```bash
   job-scraper --help
   ```
5. **copy config example to config.yaml and customize it to your preferences**
    ```bash
    cp config-example.yaml config.yaml
    ```
6. **copy env example to .env and customize**

   ```bash
   cp .env.example .env
   ```
7. **run scraper**
   ```bash
   job-scraper scrape
   ```


## Usage

The scraper has three subcommands that run independently:

```
uv run job-scraper <command> [options]
```

| Command | What it does |
|---------|-------------|
| `scrape` | Opens a browser, paginates through job listings, saves raw job data to `data/scraped_jobs.db` |
| `filter` | Reads the SQLite queue, sends each job to the LLM, writes results to `matched_jobs.txt` / `rejected_jobs.txt` |
| `optimize` | Reads the matched jobs, sends each job to the LLM, optimizes your cv sections |
| `review` | opens ui to review matched jobs with optimized cv sections |
| `run` | Runs `scrape` then `filter` sequentially (browser closes before LLM starts) |

### Common invocations

```bash
# Scrape up to 200 jobs, browser visible
uv run  python -m job-scraper scrape --limit 200

# Scrape and show browser window, headless by default
uv run python -m job-scraper scrape --headless false --limit 500

# Filter whatever is in the SQLite queue (no browser needed)
uv run python -m job-scraper filter

# Filter only 10 jobs this session
uv run python -m job-scraper filter --limit 10

# Full pipeline in one go
uv run python -m job-scraper run --limit 100
```

### View results

```bash
cat data/matched_jobs.txt
cat data/rejected_jobs.txt
```


## Ethical Scraping

This project follows ethical web scraping practices:
- Respects `robots.txt`
- Uses rate limiting and human-like delays
- Only scrapes public data (no authentication bypass)
- Runs locally (no data collection or reselling)
- For personal job search use only

## License

This project is for educational and personal use only. Always respect the target platform's Terms of Service and robots.txt.

## Contributing

This is a personal project designed for portfolio purposes. Feel free to fork and adapt for your own use!
