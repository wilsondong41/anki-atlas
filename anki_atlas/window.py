"""Anki Qt window, background QueryOp loader, cache, and pycmd bridge for Anki Atlas."""

from __future__ import annotations

import collections
import html
import json
import os
import re
import time
from typing import Any

from .graph import build_graph
from .taxonomy import (
    OVERLAY_RESOURCES,
    clean_label,
    escape_anki_deck,
    escape_anki_tag,
    extract_deck_path,
    extract_generic_tag_paths,
    extract_step_paths,
    is_utility_tag,
    locate_primary_node_id,
)

_ADDON_PKG = __package__ or "anki_atlas"
_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
_BODY_RE = re.compile(r"<body[^>]*>(.*)</body>", re.DOTALL | re.IGNORECASE)
_SCRIPT_SRC_RE = re.compile(r'<script[^>]+src=["\'][^"\']+["\'][^>]*>\s*</script>', re.IGNORECASE)
_SNIP_SOUND_RE = re.compile(r"\[sound:[^\]]*\]", re.IGNORECASE)
_SNIP_CLOZE_RE = re.compile(r"\{\{c\d+::(.*?)(?:::[^{}]*)?\}\}", re.DOTALL)
_SNIP_HTML_RE = re.compile(r"<[^>]+>")

# Cache keyed by (profile_name, col_mod, suspended_count, lens_id)
_GRAPH_CACHE: dict[tuple[str, int, int, str], dict[str, Any]] = {}


def clear_cache() -> None:
    """Drop all cached graph payloads."""
    _GRAPH_CACHE.clear()


def build_page_parts(web_dir: str | None = None) -> tuple[str, str]:
    """Read atlas.html, atlas.css, and atlas.js and return (head_html, body_html)."""
    base = web_dir or _WEB_DIR
    with open(os.path.join(base, "atlas.html"), "r", encoding="utf-8") as fh:
        raw_html = fh.read()
    with open(os.path.join(base, "atlas.css"), "r", encoding="utf-8") as fh:
        raw_css = fh.read()
    with open(os.path.join(base, "atlas.js"), "r", encoding="utf-8") as fh:
        raw_js = fh.read()

    match = _BODY_RE.search(raw_html)
    body = match.group(1) if match else raw_html
    body = _SCRIPT_SRC_RE.sub("", body).strip()

    head_html = f"<style>\n{raw_css}\n</style>"
    safe_js = raw_js.replace("</script>", "<\\/script>")
    body_html = f"{body}\n<script>\n{safe_js}\n</script>"
    return head_html, body_html


def build_atlas_from_col(
    col: Any,
    deck_filter: str = "auto",
    exam_scope: str = "all",
) -> dict[str, Any]:
    """Read notes, cards, decks, and 30d revlog read-only from an open Anki collection."""
    notes_rows = col.db.all("SELECT id, tags, flds FROM notes")
    cards_rows = col.db.all("SELECT id, nid, did, queue, ivl, lapses, factor FROM cards")
    decks_map = {d.id: d.name for d in col.decks.all_names_and_ids()}
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - 30 * 86400 * 1000
    try:
        rev_rows = col.db.all("SELECT cid, MAX(id) FROM revlog WHERE id >= ? GROUP BY cid", cutoff_ms)
        revlog_recent = {int(cid): int(ts) for cid, ts in rev_rows}
    except Exception:
        revlog_recent = {}
    return build_graph(
        notes_rows,
        cards_rows,
        decks_map,
        deck_filter=deck_filter,
        exam_scope=exam_scope,
        revlog_recent=revlog_recent,
        now_ms=now_ms,
    )


def create_or_rebuild_cram_deck(
    col: Any,
    title: str,
    query: str,
    limit: int = 50,
) -> tuple[str, int, int]:
    """Create or rebuild a non-rescheduling Filtered Deck for a topic/pathway/overlay.

    Returns ``(deck_name, did, card_count)``.
    """
    clean_title = re.sub(r"[\r\n\t]+", " ", (title or "Study")).strip()[:42] or "Study"
    deck_name = f"Atlas Study — {clean_title}"
    existing = col.decks.by_name(deck_name)
    created_new = False
    if existing and existing.get("dyn", 0) == 1:
        did = existing["id"]
    else:
        if existing:
            deck_name = f"{deck_name} (Cram)"
            existing2 = col.decks.by_name(deck_name)
            if existing2 and existing2.get("dyn", 0) == 1:
                did = existing2["id"]
            else:
                did = col.decks.new_filtered(deck_name)
                created_new = True
        else:
            did = col.decks.new_filtered(deck_name)
            created_new = True

    deck = col.decks.get(did)
    capped_limit = max(1, min(200, int(limit)))
    deck["terms"] = [[query.strip(), capped_limit, 0]]
    deck["resched"] = False
    col.decks.save(deck)
    col.sched.rebuild_filtered_deck(did)
    count = len(col.find_cards(escape_anki_deck(deck_name)))
    if count == 0 and created_new:
        col.decks.remove([did])
        return (deck_name, 0, 0)
    return (deck_name, did, count)


def _clean_card_snippet(flds: str, max_len: int = 120) -> str:
    """Turn Anki note fields into a clean single-line text preview."""
    if not flds:
        return ""
    parts = flds.split("\x1f")
    for raw in (parts[0], parts[1] if len(parts) > 1 else ""):
        txt = _SNIP_SOUND_RE.sub(" ", raw or "")
        txt = _SNIP_CLOZE_RE.sub(r"\1", txt)
        txt = _SNIP_HTML_RE.sub(" ", txt)
        txt = html.unescape(txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        if txt:
            return (txt[: max_len - 1] + "…") if len(txt) > max_len else txt
    return ""


def _card_state_label(queue: int, ivl: int) -> str:
    if queue == -1:
        return "suspended"
    if queue >= 1:
        return "mature" if ivl >= 21 else "young"
    return "new"


def _extract_raw_prefixes_from_query(query: str, raw_tag: str = "") -> list[str]:
    prefixes: list[str] = []
    if raw_tag:
        prefixes.append(raw_tag)
    for m in re.finditer(r'tag:"((?:\\.|[^"])+)"|tag:([^\s)]+)', query or ""):
        raw = m.group(1) if m.group(1) is not None else m.group(2)
        unesc = (
            raw.replace('\\"', '"')
            .replace("\\\\", "\\")
            .replace("\\*", "*")
            .replace("\\_", "_")
        )
        if unesc and unesc not in prefixes:
            prefixes.append(unesc)
    return prefixes


def inspect_node_in_col(
    col: Any,
    node_id: str,
    query: str,
    raw_tag: str = "",
    query_kind: str = "tag",
    taxonomy_mode: str = "step_subjects",
    deck_filter: str = "ALL",
) -> dict[str, Any]:
    """Read-only deep inspection of a topic: Level 4+ subtags, gap subdecks/tags, and sample cards."""
    empty = {
        "id": node_id,
        "subtags": [],
        "gap_mode": "suspended",
        "gap_sources": [],
        "cards": [],
        "total_notes": 0,
    }
    if not query or col is None:
        return empty

    try:
        nids = list(col.find_notes(query))
    except Exception:
        return empty
    if not nids:
        return empty

    total_notes = len(nids)
    sample_nids = nids[:1500]
    notes_map: dict[int, tuple[str, str]] = {}
    cards_rows: list[tuple[int, int, int, int, int, int]] = []
    for i in range(0, len(sample_nids), 400):
        chunk = sample_nids[i : i + 400]
        ph = ",".join("?" for _ in chunk)
        for nid, tags_str, flds in col.db.all(f"SELECT id, tags, flds FROM notes WHERE id IN ({ph})", *chunk):
            notes_map[int(nid)] = (tags_str or "", flds or "")
        for cid, nid, did, queue, ivl, lapses in col.db.all(
            f"SELECT id, nid, did, queue, ivl, lapses FROM cards WHERE nid IN ({ph})", *chunk
        ):
            cards_rows.append((int(cid), int(nid), int(did), int(queue), int(ivl), int(lapses)))

    decks_map = {d.id: d.name.replace("\x1f", "::").strip() for d in col.decks.all_names_and_ids()}
    deck_clause = (
        f" {escape_anki_deck(deck_filter)}"
        if (query_kind == "tag" and deck_filter and deck_filter not in ("ALL", "auto"))
        else ""
    )

    # Aggregate card counts per note & sample representative card per note
    note_counts: dict[int, list[int]] = {}  # nid -> [tot, mat, yng, nw, susp, max_lapses]
    note_dids: dict[int, set[int]] = collections.defaultdict(set)
    card_samples: list[tuple[int, int, str, int, int]] = []  # (prio, cid, snippet, state, lapses)
    susp_cards: list[tuple[int, int, int]] = []  # (cid, nid, did)
    weak_cards: list[tuple[int, int, int]] = []

    for cid, nid, did, queue, ivl, lapses in cards_rows:
        st = note_counts.get(nid)
        if st is None:
            st = [0, 0, 0, 0, 0, 0]
            note_counts[nid] = st
        note_dids[nid].add(did)
        st[0] += 1
        st_name = _card_state_label(queue, ivl)
        if st_name == "suspended":
            st[4] += 1
            susp_cards.append((cid, nid, did))
        elif st_name == "mature":
            st[1] += 1
        elif st_name == "young":
            st[2] += 1
        else:
            st[3] += 1
        if lapses > st[5]:
            st[5] = lapses
        if queue >= 1 and lapses >= 2:
            weak_cards.append((cid, nid, did))

    # Build top 15 representative card previews (1 card per note, prioritizing suspended then weak)
    seen_preview_nids: set[int] = set()
    for cid, nid, _did, queue, ivl, lapses in cards_rows:
        if nid in seen_preview_nids or nid not in notes_map:
            continue
        seen_preview_nids.add(nid)
        st_name = _card_state_label(queue, ivl)
        snip = _clean_card_snippet(notes_map[nid][1])
        if not snip:
            continue
        prio = 0 if st_name == "suspended" else (1 if lapses >= 2 else (2 if st_name != "mature" else 3))
        card_samples.append((prio, cid, snip, st_name, lapses))
    card_samples.sort(key=lambda x: (x[0], -x[4], x[1]))
    cards_out = [
        {"cid": cid, "text": snip, "state": st_name, "lapses": lapses, "query": f"cid:{cid}"}
        for _prio, cid, snip, st_name, lapses in card_samples[:15]
    ]

    # 1. Deeper child subtags (1 level below node's raw tag prefixes, e.g. Level 4-5)
    raw_prefixes = _extract_raw_prefixes_from_query(query, raw_tag)
    subtag_stats: dict[str, list[int]] = {}
    subtag_labels: dict[str, str] = {}
    if raw_prefixes and query_kind == "tag":
        pref_colons = [(p, p + "::") for p in raw_prefixes]
        for nid, (tags_str, _flds) in notes_map.items():
            nc = note_counts.get(nid)
            if not nc:
                continue
            seen_for_note: set[str] = set()
            for t in tags_str.split():
                for _p, p_col in pref_colons:
                    if not t.startswith(p_col):
                        continue
                    rem = t[len(p_col) :]
                    child_seg = rem.split("::", 1)[0].strip()
                    if not child_seg or is_utility_tag(child_seg):
                        continue
                    child_full = f"{p_col}{child_seg}"
                    if child_full in seen_for_note:
                        continue
                    seen_for_note.add(child_full)
                    st = subtag_stats.get(child_full)
                    if st is None:
                        st = [0, 0, 0, 0, 0]
                        subtag_stats[child_full] = st
                        subtag_labels[child_full] = clean_label(child_seg)
                    st[0] += nc[0]
                    st[1] += nc[1]
                    st[2] += nc[2]
                    st[3] += nc[3]
                    st[4] += nc[4]

    subtags_out = []
    for full_tag, st in sorted(subtag_stats.items(), key=lambda kv: (-kv[1][4], -kv[1][0], subtag_labels[kv[0]])):
        tot, mat, yng, nw, susp = st
        act = mat + yng
        subtags_out.append({
            "label": subtag_labels[full_tag],
            "tag": full_tag,
            "total": tot,
            "mature": mat,
            "young": yng,
            "new": nw,
            "suspended": susp,
            "learned_pct": round(act / tot, 4) if tot else 0.0,
            "query": f"{escape_anki_tag(full_tag)}{deck_clause}",
        })
        if len(subtags_out) >= 24:
            break

    # 2. Simple universal "Where missing cards live" (subdecks + resource/user tags on gap cards)
    gap_mode = "suspended" if susp_cards else ("weak" if weak_cards else "none")
    target_cards = susp_cards if gap_mode == "suspended" else weak_cards
    gap_sources: list[dict[str, Any]] = []
    if target_cards:
        gap_suffix = "is:suspended" if gap_mode == "suspended" else "prop:lapses>=2"
        gap_base = f"({query}) {gap_suffix}"

        subdeck_counts: collections.Counter[str] = collections.Counter()
        for _cid, _nid, did in target_cards:
            dname = decks_map.get(did, "")
            if not dname or "Filtered Deck" in dname:
                continue
            if deck_filter and deck_filter not in ("ALL", "auto"):
                if dname == deck_filter or not dname.startswith(deck_filter + "::"):
                    continue
            elif "::" not in dname:
                continue
            short = dname.rsplit("::", 1)[-1]
            if short.lower() == "past":
                continue
            subdeck_counts[dname] += 1

        for dname, cnt in subdeck_counts.most_common(4):
            short = dname.rsplit("::", 1)[-1]
            gap_sources.append({
                "label": clean_label(short),
                "kind": "subdeck",
                "count": cnt,
                "query": f"{gap_base} {escape_anki_deck(dname)}",
            })

        # Tally tags across gap cards
        gap_card_tags_count: collections.Counter[str] = collections.Counter()
        gap_tag_labels: dict[str, str] = {}
        res_checks = [(pref, pref + "::", lbl) for pref, lbl in OVERLAY_RESOURCES]
        found_known_res = False
        for _cid, nid, _did in target_cards:
            tags_str = notes_map.get(nid, ("", ""))[0]
            if not tags_str:
                continue
            matched_res_for_card: set[str] = set()
            for t in tags_str.split():
                for pref, pref_col, lbl in res_checks:
                    if t == pref or t.startswith(pref_col):
                        matched_res_for_card.add(pref)
                        gap_tag_labels[pref] = lbl
            for pref in matched_res_for_card:
                found_known_res = True
                gap_card_tags_count[pref] += 1

        if not found_known_res:
            # Generic / non-AnKing tags on gap cards (skip utility tags and node's own taxonomy prefixes)
            raw_low = tuple(p.lower() for p in raw_prefixes)
            for _cid, nid, _did in target_cards:
                tags_str = notes_map.get(nid, ("", ""))[0]
                if not tags_str:
                    continue
                seen_card_tags: set[str] = set()
                for t in tags_str.split():
                    if is_utility_tag(t):
                        continue
                    tl = t.lower()
                    if any(tl.startswith(rp) or rp.startswith(tl + "::") for rp in raw_low):
                        continue
                    root = t if "::" not in t else t.split("::", 1)[0]
                    if root and root not in seen_card_tags:
                        seen_card_tags.add(root)
                        gap_tag_labels[root] = f"#{clean_label(root)}"
                        gap_card_tags_count[root] += 1

        for tag_key, cnt in gap_card_tags_count.most_common(6):
            gap_sources.append({
                "label": gap_tag_labels.get(tag_key, tag_key),
                "kind": "tag",
                "count": cnt,
                "query": f"{gap_base} {escape_anki_tag(tag_key)}",
            })

    return {
        "id": node_id,
        "subtags": subtags_out,
        "gap_mode": gap_mode,
        "gap_sources": gap_sources[:8],
        "cards": cards_out,
        "total_notes": total_notes,
    }


def _tag_search_stem(word: str) -> str:
    w = word.lower()
    if len(w) >= 6 and w.endswith("e"):
        return w[:-1]
    if len(w) >= 5 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def search_collection_for_atlas(
    col: Any,
    query_text: str,
    deck_filter: str = "ALL",
    exam_scope: str = "all",
    taxonomy_mode: str = "step_subjects",
    tag_strip_root: str = "",
    loaded_node_ids: set[str] | None = None,
    token: int = 0,
) -> dict[str, Any]:
    """Search Anki card text AND deep tags (Level 4-5) fast using col.find_notes."""
    q = re.sub(r'["()\\]+', " ", (query_text or "").strip())
    q = re.sub(r"\s+", " ", q).strip()
    if len(q) < 2 or col is None:
        return {"token": token, "query": q, "total_notes": 0, "browser_query": "", "topics": [], "subtags": [], "cards": []}

    words = [w for w in q.split(" ") if w]
    tag_clause = " ".join(f"tag:*{_tag_search_stem(w)}*" for w in words)
    deck_clause = (
        f" {escape_anki_deck(deck_filter)}"
        if (deck_filter and deck_filter not in ("ALL", "auto"))
        else ""
    )
    browser_query = f"({q} OR ({tag_clause})){deck_clause}"

    try:
        nids = list(col.find_notes(browser_query))
    except Exception:
        nids = []

    if not nids:
        return {
            "token": token,
            "query": query_text.strip(),
            "total_notes": 0,
            "browser_query": browser_query,
            "topics": [],
            "subtags": [],
            "cards": [],
        }

    total_notes = len(nids)
    sample_nids = nids[:200]
    ph = ",".join("?" for _ in sample_nids)
    notes_rows = col.db.all(f"SELECT id, tags, flds FROM notes WHERE id IN ({ph})", *sample_nids)
    cards_rows = col.db.all(f"SELECT id, nid, did, queue, ivl, lapses FROM cards WHERE nid IN ({ph})", *sample_nids)
    decks_map = {d.id: d.name.replace("\x1f", "::").strip() for d in col.decks.all_names_and_ids()}

    cards_by_nid: dict[int, list[tuple[int, int, int, int, int]]] = collections.defaultdict(list)
    for cid, nid, did, queue, ivl, lapses in cards_rows:
        cards_by_nid[int(nid)].append((int(cid), int(did), int(queue), int(ivl), int(lapses)))

    node_hits: collections.Counter[str] = collections.Counter()
    node_susp: collections.Counter[str] = collections.Counter()
    subtag_hits: dict[str, list[int]] = {}
    subtag_meta: dict[str, tuple[str, str, str | None]] = {}
    card_hits: list[dict[str, Any]] = []
    q_words_low = [w.lower() for w in words]
    loaded = loaded_node_ids

    for nid, tags_str, flds in notes_rows:
        nid = int(nid)
        tags = [t for t in (tags_str or "").split() if t]
        ncards = cards_by_nid.get(nid, [])
        if not ncards:
            continue
        first_cid, first_did, first_q, first_ivl, _lapses = ncards[0]
        dname = decks_map.get(first_did, "")
        has_susp = any(c[2] == -1 for c in ncards)
        any_susp_cnt = sum(1 for c in ncards if c[2] == -1)

        node_id = locate_primary_node_id(
            tags,
            dname,
            exam_scope=exam_scope,
            use_step_subjects=(taxonomy_mode == "step_subjects"),
            base_deck=deck_filter if deck_filter != "auto" else "ALL",
            taxonomy_mode=taxonomy_mode,
            tag_strip_root=tag_strip_root,
        )
        if node_id and (loaded is None or node_id in loaded):
            node_hits[node_id] += 1
            node_susp[node_id] += any_susp_cnt

        # Check tags whose segment(s) match the searched words or stems (surfaces Gangrenous Necrosis for "gangrene")
        q_stems = [_tag_search_stem(w) for w in q_words_low]
        seen_subtags: set[str] = set()
        for t in tags:
            if is_utility_tag(t):
                continue
            tl = t.lower()
            if all(st in tl for st in q_stems):
                parts = [p for p in t.split("::") if p]
                if not parts:
                    continue
                leaf = clean_label(parts[-1])
                if leaf.lower() in ("extra", "notes", "misc") and len(parts) >= 2:
                    leaf = f"{clean_label(parts[-2])} ({leaf})"
                    trail = " › ".join(clean_label(p) for p in parts[max(0, len(parts) - 4) : -2])
                else:
                    trail = " › ".join(clean_label(p) for p in parts[max(0, len(parts) - 3) : -1])
                if t not in seen_subtags:
                    seen_subtags.add(t)
                    st = subtag_hits.get(t)
                    if st is None:
                        st = [0, 0]
                        subtag_hits[t] = st
                        subtag_meta[t] = (leaf, trail, node_id if (loaded is None or node_id in loaded) else None)
                    st[0] += 1
                    st[1] += any_susp_cnt

        if len(card_hits) < 12:
            snip = _clean_card_snippet(flds)
            if snip:
                state_name = "suspended" if has_susp and all(c[2] == -1 for c in ncards) else _card_state_label(first_q, first_ivl)
                card_hits.append({
                    "cid": first_cid,
                    "text": snip,
                    "state": state_name,
                    "node_id": node_id if (loaded is None or node_id in loaded) else None,
                    "query": f"cid:{first_cid}",
                })

    topics_out = [
        {"id": nid_key, "hits": cnt, "suspended": node_susp[nid_key]}
        for nid_key, cnt in node_hits.most_common(14)
    ]

    subtags_out = []
    for full_t, (hits, susp_c) in sorted(subtag_hits.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0])):
        leaf, trail, parent_node_id = subtag_meta[full_t]
        subtags_out.append({
            "label": leaf,
            "trail": trail,
            "hits": hits,
            "suspended": susp_c,
            "node_id": parent_node_id,
            "query": f"{escape_anki_tag(full_t)}{deck_clause}",
        })
        if len(subtags_out) >= 10:
            break

    return {
        "token": token,
        "query": query_text.strip(),
        "total_notes": total_notes,
        "browser_query": browser_query,
        "topics": topics_out,
        "subtags": subtags_out,
        "cards": card_hits,
    }


def _col_cache_key(mw: Any, col: Any, deck_filter: str, exam_scope: str) -> tuple[str, int, int, str, str]:
    profile = ""
    try:
        profile = mw.pm.name or ""
    except Exception:
        profile = ""
    try:
        mod = int(col.mod or 0)
    except Exception:
        mod = 0
    try:
        susp = int(col.db.scalar("SELECT COUNT(*) FROM cards WHERE queue = -1") or 0)
    except Exception:
        susp = 0
    return (profile, mod, susp, deck_filter, exam_scope)


def _load_config(mw: Any) -> dict[str, Any]:
    defaults = {
        "deck_filter": "auto",
        "exam_scope": "all",
        "view_mode": "grid",
        "colorblind_mode": False,
        "show_concept_links": True,
        "high_yield_only": False,
        "window_width": 1340,
        "window_height": 860,
    }
    try:
        cfg = mw.addonManager.getConfig(_ADDON_PKG) or {}
    except Exception:
        cfg = {}
    merged = dict(defaults)
    for k in defaults:
        if k in cfg:
            merged[k] = cfg[k]
    return merged


def _save_config(mw: Any, updates: dict[str, Any]) -> None:
    try:
        cfg = _load_config(mw)
        cfg.update(updates)
        mw.addonManager.writeConfig(_ADDON_PKG, cfg)
    except Exception:
        pass


def create_atlas_window(mw: Any) -> Any:
    """Create and return an AtlasWindow bound to Anki's main window."""
    import aqt
    from aqt.operations import QueryOp
    from aqt.qt import QDialog, Qt, QVBoxLayout
    from aqt.theme import theme_manager
    from aqt.webview import AnkiWebView

    class AtlasWindow(QDialog):
        """Standalone, non-modal knowledge map window."""

        def __init__(self, main_win: Any) -> None:
            super().__init__(main_win, Qt.WindowType.Window)
            self._mw = main_win
            self._cfg = _load_config(main_win)
            self._deck_filter = str(self._cfg.get("deck_filter") or "auto")
            self._exam_scope = str(self._cfg.get("exam_scope") or "all")
            self._loading_token = 0
            self._initial_load_started = False
            self._pending_locate_id: str | None = None
            self._loaded_node_ids: set[str] = set()
            self._use_step_subjects: bool = True
            self._taxonomy_mode: str = "step_subjects"
            self._tag_strip_root: str = ""

            self.setWindowTitle("Anki Atlas")
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            w = max(880, int(self._cfg.get("window_width", 1340)))
            h = max(580, int(self._cfg.get("window_height", 860)))
            self.resize(w, h)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self.web = AnkiWebView(parent=self, title="Anki Atlas")
            self.web.set_bridge_command(self._on_bridge_cmd, self)
            layout.addWidget(self.web)

            head_html, body_html = build_page_parts()
            self.web.stdHtml(
                body=body_html,
                js=[],
                head=head_html,
                context=self,
                default_css=False,
            )
            self._start_initial_load()

        def _start_initial_load(self) -> None:
            self._initial_load_started = True
            self._push_prefs()
            self._load_graph(self._deck_filter, self._exam_scope)

        def reload_current(self) -> None:
            """Refresh graph when re-focused if collection changed."""
            self._load_graph(self._deck_filter, self._exam_scope)

        def _push_prefs(self) -> None:
            prefs = {
                "night_mode": bool(theme_manager.night_mode),
                "view_mode": str(self._cfg.get("view_mode") or "grid"),
                "colorblind_mode": bool(self._cfg.get("colorblind_mode", False)),
                "show_concept_links": bool(self._cfg.get("show_concept_links", True)),
                "high_yield_only": bool(self._cfg.get("high_yield_only", False)),
                "deck_filter": self._deck_filter,
                "exam_scope": self._exam_scope,
            }
            self.web.eval(f"window.atlasInitPrefs({json.dumps(prefs)});")

        def locate_card(self, card: Any) -> None:
            """Locate a card's topic in Atlas, widening filters if needed."""
            col = getattr(self._mw, "col", None)
            if col is None or card is None:
                return
            try:
                note = card.note()
                tags = list(note.tags)
                dname = col.decks.name(card.did)
            except Exception:
                return

            node_id = locate_primary_node_id(
                tags,
                dname,
                exam_scope=self._exam_scope,
                use_step_subjects=self._use_step_subjects,
                base_deck=self._deck_filter,
                taxonomy_mode=self._taxonomy_mode,
                tag_strip_root=self._tag_strip_root,
            )
            if node_id and node_id in self._loaded_node_ids:
                self._pending_locate_id = None
                self.web.eval(f"window.atlasLocateNode({json.dumps(node_id)});")
                return

            # Try matching under All Decks / All Exams if card wasn't in current filter
            is_step_card = any(
                t.startswith("#AK_Step1_v12::#FirstAid::") or t.startswith("#AK_Step2_v12::#Subjects::")
                for t in tags
            )
            fallback_mode = (
                "step_subjects"
                if is_step_card
                else (self._taxonomy_mode if self._taxonomy_mode == "generic_tags" else "decks")
            )
            fallback_id = locate_primary_node_id(
                tags,
                dname,
                exam_scope="all",
                use_step_subjects=is_step_card,
                base_deck="ALL",
                taxonomy_mode=fallback_mode,
                tag_strip_root=self._tag_strip_root,
            )
            if not fallback_id:
                self.web.eval('window.atlasToast("This card has no matching topic in Atlas.");')
                return
            self._pending_locate_id = fallback_id
            if self._loaded_node_ids and fallback_id in self._loaded_node_ids:
                self.web.eval(f"window.atlasLocateNode({json.dumps(fallback_id)});")
                self._pending_locate_id = None
            else:
                self._load_graph("ALL" if not fallback_id.startswith("L") or self._deck_filter not in ("auto", "ALL") else self._deck_filter, "all")

        def _deliver_payload(self, payload: dict[str, Any]) -> None:
            summary = payload.get("summary") or {}
            self._loaded_node_ids = {n["id"] for n in payload.get("nodes", ())}
            self._use_step_subjects = bool(summary.get("use_step_subjects", True))
            self._taxonomy_mode = str(summary.get("taxonomy_mode") or ("step_subjects" if self._use_step_subjects else "decks"))
            self._tag_strip_root = str(summary.get("tag_strip_root") or "")
            encoded = json.dumps(payload, separators=(",", ":"))
            self.web.eval(f"window.atlasReceiveGraph({encoded});")
            if self._pending_locate_id:
                loc = self._pending_locate_id
                self._pending_locate_id = None
                self.web.eval(f"window.atlasLocateNode({json.dumps(loc)});")

        def _load_graph(self, deck_filter: str, exam_scope: str, force: bool = False) -> None:
            col = getattr(self._mw, "col", None)
            if col is None:
                self.web.eval('window.atlasShowError("Open an Anki profile to load the Atlas.");')
                return

            self._deck_filter = deck_filter or "auto"
            self._exam_scope = exam_scope if exam_scope in ("all", "step1", "step2") else "all"
            key = _col_cache_key(self._mw, col, self._deck_filter, self._exam_scope)
            if not force and key in _GRAPH_CACHE:
                payload = _GRAPH_CACHE[key]
                self._deliver_payload(payload)
                return

            self._loading_token += 1
            token = self._loading_token
            self.web.eval("window.atlasSetLoading(true);")

            req_deck = self._deck_filter
            req_exam = self._exam_scope

            def _op(c: Any) -> dict[str, Any]:
                return build_atlas_from_col(c, deck_filter=req_deck, exam_scope=req_exam)

            def _on_success(payload: dict[str, Any]) -> None:
                if token != self._loading_token:
                    return
                self._deck_filter = payload.get("deck_filter", self._deck_filter)
                self._exam_scope = payload.get("exam_scope", self._exam_scope)
                _GRAPH_CACHE[_col_cache_key(self._mw, col, self._deck_filter, self._exam_scope)] = payload
                _GRAPH_CACHE[key] = payload
                self._deliver_payload(payload)

            def _on_failure(err: Exception) -> None:
                if token != self._loading_token:
                    return
                self.web.eval(f"window.atlasShowError({json.dumps(str(err))});")

            QueryOp(parent=self, op=_op, success=_on_success).failure(_on_failure).run_in_background()

        def _on_bridge_cmd(self, cmd: str) -> Any:
            if cmd == "atlas:ready":
                if not self._initial_load_started:
                    self._start_initial_load()
                else:
                    self._push_prefs()
            elif cmd.startswith("atlas:filter:"):
                raw = cmd.split(":", 2)[2]
                try:
                    data = json.loads(raw)
                except Exception:
                    return
                df = str(data.get("deck_filter") or self._deck_filter)
                ex = str(data.get("exam_scope") or self._exam_scope)
                self._cfg["deck_filter"] = df
                self._cfg["exam_scope"] = ex
                _save_config(self._mw, {"deck_filter": df, "exam_scope": ex})
                self._load_graph(df, ex)
            elif cmd == "atlas:refresh":
                clear_cache()
                self._load_graph(self._deck_filter, self._exam_scope, force=True)
            elif cmd.startswith("atlas:browser:"):
                query = cmd.split(":", 2)[2].strip()
                if query:
                    aqt.dialogs.open("Browser", self._mw, search=(query,))
            elif cmd.startswith("atlas:cram:"):
                raw = cmd.split(":", 2)[2]
                try:
                    data = json.loads(raw)
                except Exception:
                    return
                col = getattr(self._mw, "col", None)
                query = str(data.get("query") or "").strip()
                title = str(data.get("title") or "Study").strip()
                limit = int(data.get("limit") or 50)
                if col is None or not query:
                    return
                try:
                    dname, did, count = create_or_rebuild_cram_deck(col, title, query, limit=limit)
                    if count > 0 and did:
                        col.decks.select(did)
                        self._mw.moveToState("overview")
                        try:
                            if self._mw.isMinimized():
                                self._mw.showNormal()
                            self._mw.raise_()
                            self._mw.activateWindow()
                        except Exception:
                            pass
                        msg = f"Built '{dname}' ({count} cards, non-rescheduling)"
                    else:
                        msg = "No matching cards found for that study deck."
                except Exception as exc:
                    msg = f"Could not create study deck: {exc}"
                self.web.eval(f"window.atlasToast({json.dumps(msg)});")
            elif cmd.startswith("atlas:inspect_node:"):
                raw = cmd.split(":", 2)[2]
                try:
                    data = json.loads(raw)
                except Exception:
                    return
                col = getattr(self._mw, "col", None)
                if col is None:
                    return
                details = inspect_node_in_col(
                    col,
                    node_id=str(data.get("id") or ""),
                    query=str(data.get("query") or ""),
                    raw_tag=str(data.get("raw") or ""),
                    query_kind=str(data.get("query_kind") or "tag"),
                    taxonomy_mode=self._taxonomy_mode,
                    deck_filter=self._deck_filter,
                )
                self.web.eval(f"window.atlasReceiveNodeDetails({json.dumps(details)});")
            elif cmd.startswith("atlas:search:"):
                raw = cmd.split(":", 2)[2]
                try:
                    data = json.loads(raw)
                except Exception:
                    return
                col = getattr(self._mw, "col", None)
                if col is None:
                    return
                res = search_collection_for_atlas(
                    col,
                    query_text=str(data.get("query") or ""),
                    deck_filter=self._deck_filter,
                    exam_scope=self._exam_scope,
                    taxonomy_mode=self._taxonomy_mode,
                    tag_strip_root=self._tag_strip_root,
                    loaded_node_ids=self._loaded_node_ids,
                    token=int(data.get("token") or 0),
                )
                self.web.eval(f"window.atlasReceiveSearchResults({json.dumps(res)});")
            elif cmd.startswith("atlas:prefs:"):
                raw = cmd.split(":", 2)[2]
                try:
                    data = json.loads(raw)
                except Exception:
                    return
                allowed: dict[str, Any] = {}
                if "show_concept_links" in data:
                    allowed["show_concept_links"] = bool(data["show_concept_links"])
                if "high_yield_only" in data:
                    allowed["high_yield_only"] = bool(data["high_yield_only"])
                if "colorblind_mode" in data:
                    allowed["colorblind_mode"] = bool(data["colorblind_mode"])
                if "view_mode" in data and data["view_mode"] in ("grid", "2d", "3d"):
                    allowed["view_mode"] = data["view_mode"]
                if "deck_filter" in data and isinstance(data["deck_filter"], str):
                    allowed["deck_filter"] = data["deck_filter"]
                if "exam_scope" in data and data["exam_scope"] in ("all", "step1", "step2"):
                    allowed["exam_scope"] = data["exam_scope"]
                if allowed:
                    self._cfg.update(allowed)
                    _save_config(self._mw, allowed)

        def closeEvent(self, event: Any) -> None:
            _save_config(
                self._mw,
                {
                    "window_width": int(self.width()),
                    "window_height": int(self.height()),
                },
            )
            super().closeEvent(event)

    return AtlasWindow(mw)
