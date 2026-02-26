#!/bin/bash
cd /home/ksenia/Apps/job-scraper
source .venv/bin/activate
job-scraper scrape
job-scraper filter
