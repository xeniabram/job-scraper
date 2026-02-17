# Claude Context: Intelligent Job Scraper

## Project Overview

AI-powered job scraper built with modern Python tools. Scrapes **theprotocol.it** (Polish IT job board) using Playwright and filters jobs with Ollama (local LLM) based on user requirements.

**Key Goal**: Portfolio-ready project demonstrating modern Python patterns, ethical web scraping, and AI integration.

## Architecture Principles

1. **Modular Design**: Each component is independent and testable
2. **Async-First**: Uses asyncio throughout for efficient I/O operations
3. **Type Safety**: Full type hints with Pydantic for validation
4. **Abstraction**: Platform-agnostic naming (e.g., `JobBoard` instead of hardcoded platform names)
5. **Configuration**: Settings via environment variables + YAML config files

## Project Structure

```
job_scraper/
├── config/               # Pydantic settings, config loading
├── scraper/              # Browser automation (Playwright)
│   ├── browser.py        # Human-like browser behavior
│   ├── protocol_scraper.py  # theprotocol.it scraper
│   └── mock_job_board.py    # Mock data for testing
├── llm/                  # Ollama-based filtering
├── storage/              # Async file operations
├── utils/                # Logging (Loguru) & rate limiting
└── main.py               # Orchestration layer
```

## Tech Stack

- **Web Automation**: Playwright (modern, async, better than Selenium)
- **LLM**: Ollama with local models (llama3.2:latest, Llama3, etc.)
- **Config**: Pydantic + pydantic-settings + YAML
- **Logging**: Loguru (structured, rotated logs)
- **Package Manager**: uv (fast, modern)
- **Async**: asyncio + aiofiles

## Code Conventions

- **Imports**: Use absolute imports from `job_scraper` package
  ```python
  from job_scraper.config import _settings
  from job_scraper.scraper import Browser
  ```
- **Type Hints**: All functions have return types and parameter types
- **Async**: Prefix async functions with `async`, use `await` for I/O
- **Logging**: Use `loguru.logger` for all logging
- **Errors**: Let exceptions bubble up; log at appropriate levels

## Configuration Files

- **`.env`**: Credentials and runtime settings (gitignored)
- **`config.yaml`**: Job search criteria and requirements
- **`pyproject.toml`**: Dependencies and project metadata

## Important Implementation Details

### Target Platform: theprotocol.it
- **No authentication required** (public job board)
- Polish IT job board with excellent filter options
- Uses `data-test` attributes extensively (scraper-friendly)
- Categories: backend, frontend, qa-testing, devops, security, etc.
- Filter by: technology, location, seniority, remote work
- Job URL pattern: `/praca/{slug},oferta,{guid}`

### Browser Automation
- Uses stealth techniques to avoid detection
- Handles cookie consent and language selection modals
- Random delays between actions (1-3 seconds configurable)
- Human-like scrolling and mouse movements
- Viewport and user-agent spoofing (Polish locale)

### Rate Limiting
- Daily request limits (default 100)
- Automatic reset at midnight
- Random delays between requests
- Tracks requests across sessions

### LLM Filtering
- Sends job data to local Ollama instance
- Expects JSON response: `{match: bool, reason: string, score: 0-100}`
- Low temperature (0.1) for consistent filtering
- Graceful fallback if LLM fails

### Storage
- Two output files: `matched_jobs.txt` and `rejected_jobs.txt`
- Format: `URL | Title/Reason`
- Loads previous URLs to avoid re-processing
- Async file operations for performance

## Running the Project

```bash
# Development
uv run python -m job_scraper.main

# Production (after install)
uv run job-scraper
```

## Future Enhancements (Ideas)

- Add database storage (SQLite/PostgreSQL)
- Web UI for configuration and results
- Email notifications for matched jobs
- Support for multiple job platforms
- Advanced filters (salary, remote only, etc.)
- Resume matching score
- Job analytics dashboard

## Gotchas

1. **Playwright browsers**: Must run `uv run playwright install chromium` before first use
2. **Ollama must be running**: Start with `ollama serve` if not running as service
3. **theprotocol.it specifics**:
   - Site uses Next.js with dynamic rendering
   - Requires proper Chrome user-agent (older browsers get blocked)
   - Modals (cookie consent, language selection) appear on first visit
   - Uses Polish locale by default
4. **Rate limiting**: Too aggressive scraping may trigger platform protections
5. **Headless mode**: Site may detect headless browsers - test with `HEADLESS=false` first

## Environment Variables

All optional (no credentials needed!):
- `PLATFORM_EMAIL` (optional, unused - kept for compatibility)
- `PLATFORM_PASSWORD` (optional, unused - kept for compatibility)
- `OLLAMA_MODEL` (default: llama3.2:latest)
- `DAILY_JOB_LIMIT` (default: 100)
- `VIEW_DURATION_SECONDS` (default: 20)
- `HEADLESS` (default: false)

## Testing Strategy

Currently no automated tests. For manual testing:
1. Start with small limits (10 jobs)
2. Run in visible mode (`HEADLESS=false`)
3. Check logs in `logs/` directory
4. Verify output files in `data/`

## Portfolio Presentation

When sharing this project:
- Emphasize modern Python patterns (async, type hints, Pydantic)
- Highlight AI integration (local LLM for filtering)
- Mention "polite scraping" with rate limiting
- Showcase modular architecture
- Note: Can be adapted for multiple platforms (not hardcoded)
