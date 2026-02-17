# Intelligent Job Scraper

A modern, AI-powered job scraping tool for **theprotocol.it** (Polish IT job board) with intelligent LLM-based filtering.

## Features

- 🇵🇱 **theprotocol.it Integration**: Scrapes Poland's premier IT job board (no authentication required!)
- 🤖 **AI-Powered Filtering**: Uses local LLM (Ollama) to match jobs to your exact requirements
- 🎭 **Human-like Behavior**: Mimics natural browsing with random delays and scrolling
- ⚡ **Modern Tech Stack**: Built with Playwright, Pydantic, and async Python
- 📊 **Rate Limiting**: Configurable daily limits and polite scraping behavior
- 💾 **Persistent Storage**: Saves matched and rejected jobs to separate files
- 🔒 **Privacy First**: Runs completely locally - no data leaves your machine
- 🧪 **Mock Mode**: Test the system with fake data before going live

## Prerequisites

- Python 3.14+
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

2. **Edit `.env`** (credentials not needed for theprotocol.it!):
   ```env
   # No authentication needed! theprotocol.it is public
   OLLAMA_HOST=http://localhost:11434
   OLLAMA_MODEL=llama3.2:latest
   DAILY_JOB_LIMIT=100
   VIEW_DURATION_SECONDS=20
   HEADLESS=false
   ```

3. **Customize `config.yaml`** with your job search criteria:
   ```yaml
   search:
     query: "python"  # Optional search term
     category: "backend"  # backend, frontend, qa-testing, devops, etc.
     location: "warszawa"  # Warsaw (use Polish city names)
     remote: false  # Set true for remote-only jobs

   requirements:
     skillset:
       - "Python"
       - "Backend development"
       - "AWS"
     years_of_experience: 3
     min_skillset_match: 65  # Minimum % match
     conditions:
       - "Location should be remote or hybrid in Warsaw"
       - "Contract type should be B2B"
       - "Spoken languages: English required"
   ```

## Quick Start (Testing with Mock Mode)

**Test the system without hitting real servers:**

```bash
# Run with mock data (no real scraping)
make test-mock

# Or manually:
MOCK_MODE=true DAILY_JOB_LIMIT=5 uv run job-scraper
```

This will:
- Generate fake job postings
- Test the LLM filtering logic
- Save results to `data/` folder
- No browser automation or external requests

**Perfect for:**
- Testing your Ollama setup
- Tweaking job requirements in `config.yaml`
- Verifying the system works before going live

## Usage

### Run the scraper:
```bash
uv run python -m job_scraper.main
```

### Or using the package entry point:
```bash
uv run job-scraper
```

### View results:
```bash
# Matched jobs
cat data/matched_jobs.txt

# Rejected jobs
cat data/rejected_jobs.txt
```

## Project Structure

```
job_scraper/
├── src/job_scraper/
│   ├── config/          # Settings and configuration
│   │   └── settings.py
│   ├── scraper/         # Web automation
│   │   ├── browser.py   # Browser wrapper with human-like behavior
│   │   └── job_board.py # Job platform scraper
│   ├── llm/             # AI filtering
│   │   └── filter.py    # LLM-based job filtering
│   ├── storage/         # Data persistence
│   │   └── file_storage.py
│   ├── utils/           # Utilities
│   │   ├── logger.py    # Logging setup
│   │   └── rate_limiter.py
│   └── main.py          # Main orchestration
├── config.yaml          # Job search configuration
├── .env                 # Environment variables (not in git)
└── data/               # Output directory
    ├── matched_jobs.txt
    └── rejected_jobs.txt
```

## How It Works

1. **Navigate**: Goes to theprotocol.it with your specified filters (category, location, etc.)
2. **Handle Modals**: Automatically accepts cookies and selects Polish language
3. **Collect**: Scrolls through results and collects job posting URLs
4. **View**: Opens each job for specified duration (default 20s) with human-like scrolling
5. **Extract**: Scrapes title, company, location, description, and technologies
6. **AI Filter**: Uses local LLM to match jobs against your requirements
7. **Save**: Stores matched and rejected jobs to separate text files
8. **Rate Limit**: Respects daily limits and adds random delays between requests

## Best Practices

- **Start with small limits**: Test with `DAILY_JOB_LIMIT=10` first
- **Run in visible mode**: Set `HEADLESS=false` to monitor the scraper
- **Customize requirements**: Edit `config.yaml` to match your actual job preferences
- **Check Ollama**: Ensure Ollama is running before starting the scraper
- **Review logs**: Check `logs/` directory for detailed execution logs

## Development

### Add new dependencies:
```bash
uv add package-name
```

### Run with different models:
```bash
# Use a different LLM model
OLLAMA_MODEL=llama3 uv run job-scraper
```

### Why theprotocol.it?
- **No authentication required** - public job board, ethical scraping
- **Excellent structure** - uses `data-test` attributes (scraper-friendly)
- **Poor native filters** - gives you competitive advantage with AI filtering
- **Poland-focused** - great for targeting Polish/European IT market
- **Respects robots.txt** - only blocks Next.js assets directory

### Customize for other platforms:
The scraper is modular. To adapt for other job boards:
1. Create new scraper in `scraper/` (use `protocol_scraper.py` as template)
2. Update `main.py` to use new scraper
3. Adjust `config.yaml` for platform-specific filters

## Troubleshooting

**Ollama connection error:**
```bash
# Start Ollama service
ollama serve
```

**Modals not handled:**
- Cookie consent or language selection might block scraping
- Run in non-headless mode (`HEADLESS=false`) to see what's happening
- Check browser console for errors

**Browser not found:**
```bash
uv run playwright install chromium
```

**Too many requests:**
- Reduce `DAILY_JOB_LIMIT`
- Increase delays in `config.yaml` under `scraper.random_delay_range`

## Ethical Scraping

This project follows ethical web scraping practices:
- ✅ Respects theprotocol.it's `robots.txt`
- ✅ Uses rate limiting and human-like delays
- ✅ Only scrapes public data (no authentication bypass)
- ✅ Runs locally (no data collection or reselling)
- ✅ For personal job search use only

## License

This project is for educational and personal use only. Always respect the target platform's Terms of Service and robots.txt.

## Contributing

This is a personal project designed for portfolio purposes. Feel free to fork and adapt for your own use!
