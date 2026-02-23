# Intelligent Job Scraper

A modern, AI-powered job scraping tool for public job boards (for now, theprotocol.it, more boards are coming) with intelligent LLM-based filtering.

## Features

- **AI-Powered Filtering**: Uses OPENAI to match jobs to your requirements
- **Rate Limiting**: Configurable daily limits and polite scraping behavior
- **Persistent Storage**: Saves matched and rejected jobs to separate files


## Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) - Fast Python package manager

## Installation (Unix systems)

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

**macOS / iCloud warning**: avoid cloning this project to an iCloud-synced directory. macOS applies the UF_HIDDEN flag to files in .venv, and on iCloud locations this happens aggressively and repeatedly. In my experience, cloning to a local directory fixes this — the flag hasn't been reapplied there for at least a week.  If you get "no module found" errors after a successful build, try removing the flag recursively:
```zsh
chflags -R nohidden .venv
```

## Usage

The scraper has subcommands that run independently:

```
uv run job-scraper <command> [options]
```

| Command | What it does |
|---------|-------------|
| `scrape` | Opens a browser, paginates through job listings, saves raw job data to `data/scraped_jobs.db` |
| `filter` | Reads the SQLite queue, sends each job to the LLM, writes results to `matched_jobs.txt` / `rejected_jobs.txt` |
| `optimize` | Reads the matched jobs, sends each job to the LLM, optimizes your cv sections |
| `review` | opens ui to review matched jobs with optimized cv sections. To learn and adjust the prompt to your needs, you can review rejected job posts  with `--rejected` flag and save your review as text. the data will be persisted in `learn` table of `results.db`, which you can access later. same with matched jobs, which do not fit. you can specify the reason and save to `learn` table by clicking "reject"|

*see --help for all options*


### Scraping sources
There are trhee online scraping sources: theprotocol.it, justjoin.it and nofluffjobs.com preconfigured for you.
You are welcome to extend the scraper module and adjust to your own preferences. 
There is also a `local` scraping source which allows you to ingest data saved locally in json format (see `job-example.json`). to ure this feature, you might want to use a js script or custom broswer extentsion to extract data from visited pages. This will allow you to minimize manual work even for sources that are restrictive against scraping. I personally have created an `apple shortcut` but you can use whatever feels right for you. 

### Common invocations

```bash
# Scrape up to 200 jobs
job-scraper scrape --limit 200

# Filter whatever is in the SQLite queue (no browser needed)
job-scraper filter

# Filter only 10 jobs this session
job-scraper filter --limit 10

# Review what's in the mqtched queue:
job-scraper review

#Review rejected jobs ()
job-scraper review --rejeted
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
