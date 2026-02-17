# Intelligent Job Scraper

A modern, AI-powered job scraping tool for public job boards (for now, theprotocol.it, more boards are coming) with intelligent LLM-based filtering.

## Features

- **AI-Powered Filtering**: Uses local LLM (Ollama) to match jobs to your requirements
- **Rate Limiting**: Configurable daily limits and polite scraping behavior
- **Persistent Storage**: Saves matched and rejected jobs to separate files
- **Privacy First**: Runs completely locally - no data leaves your machine
- **Mock Mode**: Test the system with fake data before going live

## Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) - Fast Python package manager
- [Ollama](https://ollama.ai) - Local LLM runtime

## Installation

1. **Install Ollama** (if not already installed):
   ```bash
   # macOS/Linux
   curl -fsSL https://ollama.ai/install.sh | sh
   
   # Or visit https://ollama.ai for other platforms
   ```

2. **Pull an LLM model**:
   ```bash
   ollama pull llama3.2:latest
   # or: ollama pull llama3, ollama pull phi3, etc.
   ```

3. **Install project dependencies**:
   ```bash
   uv sync
   ```

4. **Install Playwright browsers**:
   ```bash
   uv run playwright install chromium
   ```

## Configuration

1. **Create `.env` file** from the template:
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env`** with machine-level settings:
   ```env
   OLLAMA_HOST=http://localhost:11434
   OLLAMA_MODEL=llama3.2:latest
   HEADLESS=false   # set true to run browser invisibly
   MOCK_MODE=false
   ```

3. **Copy and customize `config.yaml`** with your job search criteria:
   ```bash
   cp config-example.yaml config.yaml
   ```
   ```yaml
   search:
     technology: "python"        # theprotocol.it technology filter
     category: "backend"         # backend, frontend, devops, etc. (leave empty for all)
     contract: "kontrakt-b2b"    # contract type filter (leave empty for all)

   scraper:
     daily_limit: 100            # max jobs to scrape per day
     view_duration_seconds: 3    # seconds to spend on each job page

   requirements:
     skillset:
       - "Python"
       - "FastAPI"
     years_of_experience: 2
     min_skillset_match: 60      # reject if LLM match % is below this
     excluded_companies:
       - "some company"          # skipped before LLM, case-insensitive substring match
     conditions:
       - "Location must be remote or hybrid in Warsaw"
       - "Contract type should be B2B"
   ```

## Usage

The scraper has three subcommands that run independently:

```
uv run job-scraper <command> [options]
```

| Command | What it does |
|---------|-------------|
| `scrape` | Opens a browser, paginates through job listings, saves raw job data to `data/scraped_jobs.yaml` |
| `filter` | Reads the YAML queue, sends each job to the local LLM, writes results to `matched_jobs.txt` / `rejected_jobs.txt` |
| `run` | Runs `scrape` then `filter` sequentially (browser closes before LLM starts) |

### Common invocations

```bash
# Scrape up to 200 jobs, browser visible
uv run  python -m job-scraper scrape --limit 200

# Scrape headlessly (no browser window)
uv run python -m job-scraper scrape --headless --limit 500

# Filter whatever is in the YAML queue (no browser needed)
uv run python -m job-scraper filter

# Filter only 10 jobs this session
uv run python -m job-scraper filter --limit 10

# Full pipeline in one go
uv run python -m job-scraper run --limit 100
```

Or use the Makefile shortcuts:
```bash
make scrape          # scrape with visible browser
make scrape-headless # scrape headlessly
make filter          # filter the queue
make run             # full pipeline
make mock-scrape     # test with fake data (no browser, no Ollama needed for scrape)
```

### View results

```bash
make matched         # show matched jobs
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
