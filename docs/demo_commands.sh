#!/usr/bin/env bash
# Scripted demo for the terminal recording -- run from the repo root with the
# venv already active. The conference-list cache should be warm before
# recording (run `esmo-scraper list-conferences --search x` once, off camera,
# first -- a cold scan takes 1-3 minutes and would blow the time budget; a
# warm one is sub-second and that's the real, documented, steady-state
# behavior this is meant to show).
set -e

clear
sleep 1
echo '$ esmo-scraper list-conferences --search "ESMO Congress"'
sleep 0.5
esmo-scraper list-conferences --search "ESMO Congress"
sleep 3.5

echo
echo '$ esmo-scraper formats --congress-search "ESMO Congress 2026"'
sleep 0.5
esmo-scraper formats --congress-search "ESMO Congress 2026"
sleep 3.5

echo
echo '$ esmo-scraper run --congress-search "ESMO Congress 2026" --congress-slug esmo-congress-2026 \'
echo '    --formats abstract eposter --limit 10 --render-pdfs --local-root demo_data'
sleep 0.5
esmo-scraper run --congress-search "ESMO Congress 2026" --congress-slug esmo-congress-2026 \
  --formats abstract eposter --limit 10 --render-pdfs --local-root demo_data
sleep 3.5

echo
echo '$ find demo_data -type f | sort'
sleep 0.5
find demo_data -type f | sort
sleep 3.5

echo
echo '$ grep -o "\"content_status\": *\"[a-z_]*\"" demo_data/esmo-congress-2026/master_metadata.jsonl | sort | uniq -c'
sleep 0.5
grep -o '"content_status": *"[a-z_]*"' demo_data/esmo-congress-2026/master_metadata.jsonl | sort | uniq -c
sleep 3
