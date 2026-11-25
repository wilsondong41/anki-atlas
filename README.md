# Anki Atlas

An **offline, read-only** knowledge map and mastery explorer for Anki. Works out of the box with any hierarchical `::` tag tree, flat tag set, or subdeck hierarchy—and includes automatic USMLE Step 1 / Step 2 subject mapping and resource tag overlays for AnKing decks.

## Key Features

- **Mastery Grid, 2D Map & 3D Constellation:** Browse everything in a crisp proportional Grid view (click any block to drill down) or switch to interactive 2D/3D topic networks.
- **Works with Any Deck Structure:** Automatically builds a clean 3-level hierarchy from your nested `::` tags (including multi-root decks), flat tags, or subdecks—no manual configuration required.
- **Deep Tag & Live Collection Search (`/`):** Top-level map stays uncluttered at 3 levels, while clicking any leaf topic expands **Specific Tags Inside** (Level 4–5+) and search matches card text and deep tags across your deck.
- **Multi-Select Highlight Tags:** Combine multiple subdecks or cross-cutting tags at once via checkboxes to highlight matching topics and open combined `OR` Browser queries.
- **Calm Topic Inspector & Non-Rescheduling Cram Deck:** Inspect progress at a glance with **Open Gaps**, a non-rescheduling **Cram Deck** (`resched=False`) that brings Anki forward to study, quiet secondary links (Weak, High-Yield, All cards), and expandable **Where missing cards live** / **Sample Cards** sections.
- **Cross-Topic Bridges & Pathway Tracing:** See cards tagged across multiple topics (solid links) and offline local TF-IDF concept similarity (dashed links), or isolate neighborhoods (`F`) and trace shortest paths between topics.
- **Official Anki Colors & Colorblind Mode (`CB`):** Dark green mature, light green young, blue new, and yellow suspended states—plus an Okabe-Ito colorblind-safe toggle that updates tiles, graph nodes, inspector indicators, and the bottom legend together.
- **100% Offline & Collection-Safe:** Zero external requests, CDNs, or telemetry; never modifies your notes, tags, or card scheduling.

## Opening Anki Atlas

- Click **Atlas** in Anki's top toolbar, open **Tools → Anki Atlas**, or press `Ctrl+Shift+M` (`Cmd+Shift+M` on Mac).

## Development & Packaging

```bash
# Run pure-Python unit tests
python3 -m unittest discover -s tests -v

# Run full Qt WebEngine + Anki backend tests (macOS Anki venv)
QT_QPA_PLATFORM=offscreen ~/Library/Application\ Support/AnkiProgramFiles/.venv/bin/python -m unittest discover -s tests -v

# Package local and AnkiWeb .ankiaddon zips into dist/
python3 build.py
```

`dist/anki-atlas.ankiaddon` is for installing directly from a local file; `dist/anki-atlas-ankiweb.ankiaddon` omits `manifest.json` for AnkiWeb uploads.

## License

MIT — see [LICENSE](LICENSE).
