# Anki Atlas — agent entry file

What it is: offline, strictly read-only Anki add-on that renders an interactive Mastery Grid + 2D/3D Knowledge Map of learned progress, deep subtags, cross-topic connections, and suspended/weak gaps across any hierarchical `::` tag tree, flat tag set, or subdeck structure (with built-in Step 1 / Step 2 subject mapping and overlays for AnKing).

Status (2026-11-25): **1.0.0** packaged in `dist/`, installed on Mac at `~/Library/Application Support/Anki2/addons21/anki_atlas`, and published to public GitHub + release `v1.0.0` at `wilsondong41/anki-atlas`. Pending AnkiWeb upload by user.

## Layout
- `anki_atlas/` add-on source (only this folder is packaged via `python3 build.py` → `dist/`):
  - `manifest.json`: `"package": "anki_atlas"`, `"human_version": "1.0.0"`, `"min_point_version": 240400`.
  - `taxonomy.py`: pure-Python label cleanup, lens/taxonomy auto-detection (`step_subjects`, `generic_tags`, `decks`), secondary-tag exclusion when stripping dominant tag roots, and Browser query helpers.
  - `graph.py`: pure-Python card-state aggregation (deduplicated per note ID), Layer 2 shared-card bridges, Layer 3 offline sparse TF-IDF concept links, Connected Gaps (`is_frontier`), multi-overlay tallying (`_compute_overlays`), deterministic layout.
  - `window.py`: singleton `AtlasWindow` (`QDialog` + `AnkiWebView`), background `QueryOp` collection reads, profile+`col.mod` cache, deep level 4+ inspect (`inspect_node_in_col`), live collection search (`search_collection_for_atlas`), non-rescheduling filtered cram deck builder (`create_or_rebuild_cram_deck` with main-window raise/focus), `pycmd` bridge.
  - `__init__.py`: `Atlas` top-toolbar link + `Tools → Anki Atlas` (`Ctrl+Shift+M`).
  - `web/atlas.html`, `web/atlas.css`, `web/atlas.js`: self-contained offline Grid + 2D/3D Canvas UI, official Anki colors + Okabe-Ito colorblind toggle (`CB`, synced to `<html>`, `<body>`, and bottom legend dots), multi-select `Highlight Tags` checkbox popover, calm 2-button Inspector with inline `.ins-quick-links` and collapsed `<details class="ins-fold">` sections.
- `listing/description.txt`: AnkiWeb store listing (`**COMPLETELY VIBED CODED WITH CLAUDE AI, THE GOAT.**` + GitHub Issues link).
- `tests/`:
  - `python3 -m unittest discover -s tests -v`
  - `QT_QPA_PLATFORM=offscreen ~/Library/Application\ Support/AnkiProgramFiles/.venv/bin/python -m unittest discover -s tests -v`

## Rules
- Strictly read-only on the user's Anki collection — never modify notes, cards, tags, or review history; Cram Deck creates a separate `resched=False` filtered deck.
- 100% offline — zero external scripts, CDNs, or API calls.
- Sensible defaults, calm uncluttered UI; avoid adding manual depth/knob toggles or foregrounding "High Yield" pills outside the Inspector.
- Keep `taxonomy.py` and `graph.py` free of `aqt` imports so unit tests run under plain `python3`.
- Never commit `backups/`, `dist/`, `meta.json`, `user_files/`, or collection data to git.
