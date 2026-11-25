"""Pure-Python graph builder, mastery/gap metrics, bridges, and TF-IDF similarity.

Zero ``aqt`` imports so the full engine runs and tests under plain ``python3``.
"""

from __future__ import annotations

import collections
import html
import math
import re
import time
from typing import Any

from .taxonomy import (
    OVERLAY_RESOURCES,
    clean_label,
    detect_deck_options,
    detect_generic_tag_config,
    escape_anki_deck,
    escape_anki_tag,
    extract_deck_path,
    extract_generic_tag_paths,
    extract_step_paths,
    is_high_yield_note,
    is_leech_note,
    is_utility_tag,
)

# Regexes for cleaning AnKing / Anki note text before TF-IDF
_SOUND_RE = re.compile(r"\[sound:[^\]]*\]", re.IGNORECASE)
_CLOZE_RE = re.compile(r"\{\{c\d+::(.*?)(?:::[^{}]*)?\}\}", re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_TOKEN_RE = re.compile(r"[a-z][a-z0-9-]{2,}")

# Stopwords: common English + generic medical/AnKing card boilerplate
STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "have", "has", "had", "not", "but", "can", "will", "into", "than", "then",
    "which", "when", "where", "who", "what", "why", "how", "all", "any", "both",
    "each", "few", "more", "most", "other", "some", "such", "only", "own",
    "same", "too", "very", "also", "may", "might", "must", "should", "would",
    "could", "its", "their", "there", "these", "those", "they", "them", "been",
    "being", "one", "two", "three", "four", "five", "six", "between", "under",
    "over", "above", "below", "after", "before", "during", "through", "while",
    "about", "against", "without", "within", "via", "due", "per", "out", "off",
    "up", "down", "does", "did", "doing", "done", "use", "used", "using",
    # Generic clinical / flashcard phrasing
    "patient", "patients", "presents", "presenting", "presentation", "history",
    "caused", "causes", "cause", "causing", "associated", "association",
    "treatment", "treat", "treated", "treating", "therapy", "therapies",
    "increased", "increase", "increases", "increasing", "decreased", "decrease",
    "decreases", "decreasing", "elevated", "reduced", "high", "low", "normal",
    "abnormal", "common", "commonly", "most", "usually", "often", "rare",
    "rarely", "typically", "seen", "found", "shows", "show", "shown", "occurs",
    "occur", "occurring", "result", "results", "resulting", "leads", "lead",
    "leading", "characteristic", "characterized", "classic", "classically",
    "cell", "cells", "blood", "serum", "plasma", "level", "levels", "tissue",
    "tissues", "organ", "body", "fluid", "disease", "diseases", "syndrome",
    "syndromes", "disorder", "disorders", "condition", "drug", "drugs",
    "medication", "medications", "agent", "agents", "class", "classes",
    "first", "second", "third", "line", "risk", "factor", "factors", "test",
    "tests", "testing", "diagnosis", "diagnostic", "diagnosed", "symptom",
    "symptoms", "sign", "signs", "finding", "findings", "feature", "features",
    "effect", "effects", "side", "adverse", "toxicity", "mechanism", "action",
    "include", "includes", "including", "especially", "primarily", "mainly",
    "major", "minor", "severe", "mild", "acute", "chronic", "early", "late",
    "primary", "secondary", "type", "types", "form", "forms", "stage", "phase",
    "group", "groups", "system", "systems", "pathway", "pathways", "protein",
    "proteins", "enzyme", "enzymes", "receptor", "receptors", "gene", "genes",
    "mutation", "mutations", "deficiency", "excess", "loss", "gain", "failure",
    "function", "functions", "production", "synthesis", "release", "uptake",
    "inhibition", "inhibit", "inhibits", "inhibitor", "inhibitors", "block",
    "blocks", "blocker", "blockers", "activate", "activates", "activation",
    "bind", "binds", "binding", "response", "activity", "rate", "volume",
    "pressure", "count", "positive", "negative", "present", "absent",
    "male", "female", "men", "women", "child", "children", "infant", "infants",
    "adult", "adults", "age", "years", "old", "young", "day", "days", "week",
    "weeks", "month", "months", "time", "hours", "onset", "course",
    # HTML / AnKing boilerplate leftovers
    "note", "notes", "extra", "image", "images", "figure", "fig", "table",
    "chart", "diagram", "video", "sketchy", "firstaid", "first", "aid",
    "pathoma", "uworld", "amboss", "boards", "beyond", "physeo", "bootcamp",
    "pixorize", "nbme", "anki", "anking", "nbsp", "amp", "quot", "resizer",
    "width", "height", "style", "class", "src", "jpg", "png", "gif", "svg",
    "div", "span", "strong", "href", "http", "https", "com", "www",
})


def extract_clean_tokens(flds_str: str, max_chars: int = 750) -> list[str]:
    """Extract clean medical/concept tokens from a note's Text + Extra fields."""
    if not flds_str:
        return []
    parts = flds_str.split("\x1f")
    raw = parts[0]
    if len(parts) > 1 and parts[1]:
        raw = f"{raw} {parts[1]}"
    raw = raw[:max_chars]
    raw = _SOUND_RE.sub(" ", raw)
    # Unwrap nested cloze if any (1-2 passes)
    raw = _CLOZE_RE.sub(r" \1 ", raw)
    raw = _CLOZE_RE.sub(r" \1 ", raw)
    raw = _HTML_TAG_RE.sub(" ", raw)
    raw = html.unescape(raw).lower()
    tokens = []
    for tok in _TOKEN_RE.findall(raw):
        tok = tok.strip("-")
        if len(tok) < 3 or tok in STOPWORDS or tok.isdigit():
            continue
        tokens.append(tok)
    return tokens


def _format_raw_term(raw: str | list[str], query_kind: str) -> str:
    if isinstance(raw, (list, tuple, set)):
        terms = [escape_anki_deck(r) if query_kind == "deck" else escape_anki_tag(r) for r in sorted(set(raw)) if r]
        if not terms:
            return ""
        if len(terms) == 1:
            return terms[0]
        return f"({' OR '.join(terms)})"
    return escape_anki_deck(raw) if query_kind == "deck" else escape_anki_tag(raw)


def build_browser_query(raw: str | list[str], query_kind: str, mode: str, deck_prefix: str = "") -> str:
    """Build an exact Anki Browser search query for a node and action mode."""
    base = _format_raw_term(raw, query_kind)
    if deck_prefix and deck_prefix != "ALL" and query_kind != "deck":
        base = f"{escape_anki_deck(deck_prefix)} {base}" if base else escape_anki_deck(deck_prefix)
    if mode == "all":
        return base
    if mode == "suspended":
        return f"{base} is:suspended"
    if mode == "hy_suspended":
        hy1 = escape_anki_tag("#AK_Step1_v12::#Low/HighYield::1-HighYield")
        hy2 = escape_anki_tag("#AK_Step1_v12::#Low/HighYield::2-RelativelyHighYield")
        return f"{base} is:suspended ({hy1} OR {hy2})"
    if mode == "weak":
        return f"{base} is:review prop:lapses>=2"
    return base


def build_edge_query(
    raw_a: str | list[str],
    raw_b: str | list[str],
    query_kind: str,
    shared_tag: str = "",
    deck_prefix: str = "",
) -> str:
    """Build an Anki Browser search query for the cards bridging two topics."""
    if query_kind == "deck":
        da = _format_raw_term(raw_a, "deck")
        db = _format_raw_term(raw_b, "deck")
        if shared_tag:
            return f"({da} OR {db}) {escape_anki_tag(shared_tag)}"
        return f"{da} OR {db}"
    ta = _format_raw_term(raw_a, "tag")
    tb = _format_raw_term(raw_b, "tag")
    base = f"{ta} {tb}"
    if deck_prefix and deck_prefix != "ALL":
        return f"{escape_anki_deck(deck_prefix)} {base}"
    return base


def _aggregate_notes(
    notes_rows: list[tuple[int, str, str]],
    cards_rows: list[tuple[int, int, int, int, int, int, int]],
    revlog_recent: dict[int, int] | None = None,
    now_ms: int | None = None,
) -> tuple[dict[int, list[int]], dict[int, list[str]], dict[int, int], dict[int, set[int]]]:
    """Aggregate card states and recent momentum per note ID without double-counting.

    Returns:
      note_stats: nid -> [0:total, 1:mature, 2:young, 3:new, 4:suspended,
                          5:hy_total, 6:hy_suspended, 7:lapses_sum, 8:active,
                          9:leeches, 10:weak_cards, 11:rev_7d, 12:rev_30d]
      note_tags:  nid -> list[str]
      note_did:   nid -> primary did (first card's deck id)
      note_dids:  nid -> set of all dids among filtered cards
    """
    note_stats: dict[int, list[int]] = {}
    note_did: dict[int, int] = {}
    note_dids: dict[int, set[int]] = collections.defaultdict(set)

    cur_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    cut_7d = cur_ms - 7 * 86400 * 1000
    cut_30d = cur_ms - 30 * 86400 * 1000
    rev_map = revlog_recent or {}

    for cid, nid, did, queue, ivl, lapses, _factor in cards_rows:
        st = note_stats.get(nid)
        if st is None:
            st = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
            note_stats[nid] = st
            note_did[nid] = did
        note_dids[nid].add(did)
        st[0] += 1  # total
        if queue == -1:
            st[4] += 1  # suspended
        elif queue == 2:
            if ivl >= 21:
                st[1] += 1  # mature
            else:
                st[2] += 1  # young
            st[8] += 1  # active
            st[7] += lapses
            if lapses >= 4:
                st[9] += 1
            if lapses >= 2:
                st[10] += 1
        elif queue in (1, 3):
            st[2] += 1  # young
            st[8] += 1  # active
            st[7] += lapses
            if lapses >= 4:
                st[9] += 1
            if lapses >= 2:
                st[10] += 1
        elif queue == 0:
            st[3] += 1  # new
        else:
            # Buried (-2, -3): classify by interval so totals reconcile cleanly
            if ivl >= 21:
                st[1] += 1
                st[8] += 1
            elif ivl > 0:
                st[2] += 1
                st[8] += 1
            else:
                st[3] += 1

        ts = rev_map.get(cid)
        if ts is not None:
            if ts >= cut_30d:
                st[12] += 1
                if ts >= cut_7d:
                    st[11] += 1

    note_tags: dict[int, list[str]] = {}
    for nid, tags_str, _flds in notes_rows:
        tags = [t for t in tags_str.strip().split() if t] if tags_str else []
        note_tags[nid] = tags
        st = note_stats.get(nid)
        if st is None:
            continue
        if is_high_yield_note(tags):
            st[5] = st[0]  # hy_total
            st[6] = st[4]  # hy_suspended
        if is_leech_note(tags) and st[8] > 0:
            if st[9] == 0:
                st[9] = 1
            if st[10] == 0:
                st[10] = 1

    return note_stats, note_tags, note_did, note_dids


def _compute_shared_edges(
    level: int,
    node_nids: dict[str, set[int]],
    node_meta: dict[str, dict[str, Any]],
    min_shared: int,
    max_per_node: int,
    max_total: int,
    deck_prefix: str = "",
) -> list[dict[str, Any]]:
    """Compute Layer 2 shared-note bridge edges at a given hierarchy level."""
    nids_to_nodes: dict[int, list[str]] = collections.defaultdict(list)
    for nid_set_id, nids in node_nids.items():
        for nid in nids:
            nids_to_nodes[nid].append(nid_set_id)

    pair_counts: collections.Counter[tuple[str, str]] = collections.Counter()
    for nids_nodes in nids_to_nodes.values():
        if len(nids_nodes) < 2:
            continue
        # Deduplicate & sort once
        uniq = sorted(set(nids_nodes))
        k = len(uniq)
        for i in range(k):
            u = uniq[i]
            for j in range(i + 1, k):
                pair_counts[(u, uniq[j])] += 1

    candidates = []
    for (u, v), shared in pair_counts.items():
        if shared < min_shared:
            continue
        len_u = len(node_nids[u])
        len_v = len(node_nids[v])
        if len_u == 0 or len_v == 0:
            continue
        strength = shared / math.sqrt(len_u * len_v)
        cross_parent = node_meta[u].get("parent_id") != node_meta[v].get("parent_id")
        # Slightly prioritize cross-parent bridges at L2/L3 so cross-system links stay visible
        rank_score = strength * (1.25 if cross_parent else 1.0)
        candidates.append((rank_score, strength, shared, u, v))

    candidates.sort(key=lambda x: -x[0])

    deg: collections.Counter[str] = collections.Counter()
    edges: list[dict[str, Any]] = []
    for _rank, strength, shared, u, v in candidates:
        if deg[u] >= max_per_node or deg[v] >= max_per_node:
            continue
        meta_u = node_meta[u]
        meta_v = node_meta[v]
        edges.append({
            "id": f"E2:{level}:{u}|{v}",
            "level": level,
            "source": u,
            "target": v,
            "kind": "shared",
            "shared": shared,
            "strength": round(min(1.0, strength), 4),
            "terms": [],
            "query": build_edge_query(meta_u["raw_list"], meta_v["raw_list"], meta_u["query_kind"], deck_prefix=deck_prefix),
        })
        deg[u] += 1
        deg[v] += 1
        if len(edges) >= max_total:
            break

    return edges


def _compute_deck_tag_bridges(
    level: int,
    node_nids: dict[str, set[int]],
    node_meta: dict[str, dict[str, Any]],
    note_tags: dict[int, list[str]],
    min_shared: int = 2,
    max_per_node: int = 6,
    max_total: int = 120,
) -> list[dict[str, Any]]:
    """Fallback Layer 2 bridges for deck lens using shared tags across decks."""
    # Map tag -> {node_id: count_of_notes}
    tag_nodes: dict[str, dict[str, int]] = collections.defaultdict(lambda: collections.Counter())
    for node_id, nids in node_nids.items():
        for nid in nids:
            for t in note_tags.get(nid, ()):
                low = t.lower()
                if low in ("leech", "marked") or low.startswith("ankihub_"):
                    continue
                tag_nodes[t][node_id] += 1

    total_nodes = max(1, len(node_nids))
    pair_best_tag: dict[tuple[str, str], tuple[int, str]] = {}
    pair_score: collections.Counter[tuple[str, str]] = collections.Counter()

    for tag, counts_by_node in tag_nodes.items():
        if len(counts_by_node) < 2 or len(counts_by_node) > max(6, int(0.6 * total_nodes)):
            continue
        nodes = sorted(counts_by_node.keys())
        for i in range(len(nodes)):
            u = nodes[i]
            for j in range(i + 1, len(nodes)):
                v = nodes[j]
                overlap = min(counts_by_node[u], counts_by_node[v])
                if overlap >= 1:
                    pair_score[(u, v)] += overlap
                    prev = pair_best_tag.get((u, v))
                    if prev is None or overlap > prev[0]:
                        pair_best_tag[(u, v)] = (overlap, tag)

    candidates = []
    for (u, v), score in pair_score.items():
        if score < min_shared:
            continue
        len_u = len(node_nids[u])
        len_v = len(node_nids[v])
        strength = min(1.0, score / math.sqrt(max(1, len_u * len_v)))
        candidates.append((strength, score, u, v))

    candidates.sort(key=lambda x: -x[0])
    deg: collections.Counter[str] = collections.Counter()
    edges: list[dict[str, Any]] = []
    for strength, score, u, v in candidates:
        if deg[u] >= max_per_node or deg[v] >= max_per_node:
            continue
        best_tag = pair_best_tag[(u, v)][1]
        meta_u = node_meta[u]
        meta_v = node_meta[v]
        edges.append({
            "id": f"E2:{level}:{u}|{v}",
            "level": level,
            "source": u,
            "target": v,
            "kind": "shared",
            "shared": score,
            "strength": round(strength, 4),
            "terms": [best_tag],
            "query": build_edge_query(meta_u["raw"], meta_v["raw"], "deck", shared_tag=best_tag),
        })
        deg[u] += 1
        deg[v] += 1
        if len(edges) >= max_total:
            break
    return edges


def _compute_concept_edges(
    notes_rows: list[tuple[int, str, str]],
    target_nodes: list[str],
    node_nids: dict[str, set[int]],
    node_meta: dict[str, dict[str, Any]],
    existing_shared_pairs_by_level: dict[int, set[tuple[str, str]]],
    target_level: int,
) -> dict[int, list[dict[str, Any]]]:
    """Compute Layer 3 offline sparse TF-IDF concept links and roll up to L2/L1."""
    if len(target_nodes) < 2:
        return {1: [], 2: [], 3: []}

    # Invert target nodes by nid so we only tokenize notes inside target nodes
    nid_to_topics: dict[int, list[int]] = collections.defaultdict(list)
    for idx, node_id in enumerate(target_nodes):
        for nid in node_nids[node_id]:
            nid_to_topics[nid].append(idx)

    n_topics = len(target_nodes)
    topic_tf: list[collections.Counter[str]] = [collections.Counter() for _ in range(n_topics)]

    for nid, _tags_str, flds_str in notes_rows:
        t_idxs = nid_to_topics.get(nid)
        if not t_idxs:
            continue
        toks = extract_clean_tokens(flds_str)
        if not toks:
            continue
        # Unique tokens per note prevent single repeated word from distorting topic TF
        uniq_toks = set(toks)
        for tidx in t_idxs:
            c = topic_tf[tidx]
            for tok in uniq_toks:
                c[tok] += 1

    # Document frequency across topics
    df: collections.Counter[str] = collections.Counter()
    for c in topic_tf:
        for tok in c:
            df[tok] += 1

    max_df = max(2, int(0.25 * n_topics)) if n_topics >= 12 else max(2, n_topics - 1)
    min_df = 2

    # Build normalized sparse TF-IDF vectors (top 28 terms per topic)
    topic_vecs: list[dict[str, float]] = []
    inverted: dict[str, list[tuple[int, float]]] = collections.defaultdict(list)

    for tidx, c in enumerate(topic_tf):
        if not c:
            topic_vecs.append({})
            continue
        scored = []
        for tok, tf in c.items():
            d = df[tok]
            if d < min_df or d > max_df:
                continue
            idf = math.log((n_topics + 1) / (d + 0.5))
            w = (1.0 + math.log(tf)) * idf
            scored.append((w, tok))
        scored.sort(reverse=True)
        top_terms = scored[:28]
        norm = math.sqrt(sum(w * w for w, _ in top_terms))
        if norm <= 0:
            topic_vecs.append({})
            continue
        vec: dict[str, float] = {}
        for w, tok in top_terms:
            nw = w / norm
            vec[tok] = nw
            inverted[tok].append((tidx, nw))
        topic_vecs.append(vec)

    # Accumulate pairwise cosine dot-products and per-term contributions
    max_posting = 80 if n_topics > 80 else n_topics + 1
    pair_dot: dict[tuple[int, int], float] = collections.defaultdict(float)
    pair_shared_cnt: collections.Counter[tuple[int, int]] = collections.Counter()
    pair_terms: dict[tuple[int, int], list[tuple[float, str]]] = collections.defaultdict(list)

    for tok, postings in inverted.items():
        if len(postings) < 2 or len(postings) > max_posting:
            continue
        m = len(postings)
        for a in range(m):
            i, wi = postings[a]
            for b in range(a + 1, m):
                j, wj = postings[b]
                key = (i, j) if i < j else (j, i)
                contrib = wi * wj
                pair_dot[key] += contrib
                pair_shared_cnt[key] += 1
                pair_terms[key].append((contrib, tok))

    min_sim = 0.16 if n_topics >= 12 else 0.12
    shared_pairs_target = existing_shared_pairs_by_level.get(target_level, set())

    raw_links = []
    for (i, j), sim in pair_dot.items():
        if pair_shared_cnt[(i, j)] < 2 or sim < min_sim:
            continue
        u = target_nodes[i]
        v = target_nodes[j]
        canon = (u, v) if u < v else (v, u)
        if canon in shared_pairs_target:
            continue
        terms_ranked = sorted(pair_terms[(i, j)], reverse=True)
        top_words = [t for _c, t in terms_ranked[:3]]
        cross_parent = node_meta[u].get("parent_id") != node_meta[v].get("parent_id")
        rank = sim * (1.2 if cross_parent else 1.0)
        raw_links.append((rank, sim, canon[0], canon[1], top_words))

    raw_links.sort(key=lambda x: -x[0])

    deg: collections.Counter[str] = collections.Counter()
    max_total_target = 600 if target_level == 3 else 180
    target_edges: list[dict[str, Any]] = []
    for _rank, sim, u, v, words in raw_links:
        if deg[u] >= 4 or deg[v] >= 4:
            continue
        target_edges.append({
            "id": f"E3:{target_level}:{u}|{v}",
            "level": target_level,
            "source": u,
            "target": v,
            "kind": "concept",
            "shared": 0,
            "strength": round(min(1.0, sim), 4),
            "terms": words,
            "query": "",
        })
        deg[u] += 1
        deg[v] += 1
        if len(target_edges) >= max_total_target:
            break

    result: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: []}
    result[target_level] = target_edges

    # Roll up concept links to ancestor levels (e.g. L3 -> L2 -> L1)
    def _ancestor_at(node_id: str, desired_level: int) -> str | None:
        cur = node_id
        while cur and cur in node_meta:
            lvl = node_meta[cur]["level"]
            if lvl == desired_level:
                return cur
            if lvl < desired_level:
                return None
            cur = node_meta[cur].get("parent_id")
        return None

    for anc_level in (2, 1):
        if anc_level >= target_level:
            continue
        shared_pairs_anc = existing_shared_pairs_by_level.get(anc_level, set())
        agg_scores: dict[tuple[str, str], float] = collections.defaultdict(float)
        agg_hits: collections.Counter[tuple[str, str]] = collections.Counter()
        agg_terms: dict[tuple[str, str], collections.Counter[str]] = collections.defaultdict(collections.Counter)

        # Use top raw_links (capped for speed & relevance)
        for _rank, sim, u, v, words in raw_links[:2500]:
            au = _ancestor_at(u, anc_level)
            av = _ancestor_at(v, anc_level)
            if not au or not av or au == av:
                continue
            canon = (au, av) if au < av else (av, au)
            if canon in shared_pairs_anc:
                continue
            agg_scores[canon] += sim
            agg_hits[canon] += 1
            for idx_w, w in enumerate(words):
                agg_terms[canon][w] += (3 - idx_w) * sim

        min_hits = 2 if (anc_level == 1 and n_topics >= 25) else 1
        anc_cands = []
        for (au, av), total_sim in agg_scores.items():
            hits = agg_hits[(au, av)]
            if hits < min_hits:
                continue
            avg_sim = min(1.0, (total_sim / hits) * min(1.6, 0.8 + 0.15 * hits))
            anc_cands.append((total_sim, avg_sim, au, av))

        anc_cands.sort(reverse=True)
        anc_deg: collections.Counter[str] = collections.Counter()
        anc_edges: list[dict[str, Any]] = []
        max_anc = 36 if anc_level == 1 else 140
        max_deg = 4 if anc_level == 1 else 4
        for _score, strength, au, av in anc_cands:
            if anc_deg[au] >= max_deg or anc_deg[av] >= max_deg:
                continue
            top_w = [w for w, _ in agg_terms[(au, av)].most_common(3)]
            anc_edges.append({
                "id": f"E3:{anc_level}:{au}|{av}",
                "level": anc_level,
                "source": au,
                "target": av,
                "kind": "concept",
                "shared": 0,
                "strength": round(strength, 4),
                "terms": top_w,
                "query": "",
            })
            anc_deg[au] += 1
            anc_deg[av] += 1
            if len(anc_edges) >= max_anc:
                break
        result[anc_level] = anc_edges

    return result


def _classify_node_state(mat: int, yng: int, nw: int, susp: int, tot: int) -> str:
    """Classify dominant Anki card state for node color encoding."""
    if tot <= 0:
        return "new"
    if mat / tot >= 0.70:
        return "mature"
    if susp / tot >= 0.70:
        return "suspended"
    if yng / tot >= 0.35 or (yng > mat and yng >= susp and yng > nw):
        return "young"
    if nw / tot >= 0.50:
        return "new"
    return "mixed"


def _fib_sphere_point(idx: int, total: int, radius: float) -> tuple[float, float, float]:
    """Deterministic evenly-spaced 3D point on a sphere of given radius."""
    if total <= 1:
        return (0.0, 0.0, 0.0)
    golden = math.pi * (3.0 - math.sqrt(5.0))
    y = 1.0 - (2.0 * (idx + 0.5) / total)
    r_xy = math.sqrt(max(0.0, 1.0 - y * y))
    theta = idx * golden
    return (radius * r_xy * math.cos(theta), radius * y, radius * r_xy * math.sin(theta))


def _layout_3d_organic(
    nodes_by_id: dict[str, dict[str, Any]],
    edges_by_level: dict[int, list[dict[str, Any]]],
    node_sizes: dict[str, int],
) -> None:
    """Assign organic 3D (x, y, z) coordinates across L1/L2/L3 topics."""
    l1_ids = sorted(nid for nid, n in nodes_by_id.items() if n["level"] == 1)
    if not l1_ids:
        return

    # 1. Estimate cluster radii for L2 subtopics and L1 organ-system lobes
    sub_r: dict[str, float] = {}
    for nid, n in nodes_by_id.items():
        if n["level"] == 2:
            c_cnt = sum(1 for cid in n["children"] if cid in nodes_by_id)
            sub_r[nid] = max(28.0, 14.0 * math.sqrt(max(2, c_cnt)))

    lobe_r: dict[str, float] = {}
    for l1_id in l1_ids:
        l2_children = [cid for cid in nodes_by_id[l1_id]["children"] if cid in nodes_by_id]
        if not l2_children:
            lobe_r[l1_id] = 110.0
        else:
            vol = sum((sub_r.get(cid, 32.0) + 14.0) ** 2 for cid in l2_children)
            lobe_r[l1_id] = max(120.0, 1.25 * math.sqrt(vol) + 26.0)

    # 2. Place L1 lobes in 3D via bridge-ordered Fibonacci sphere + force relaxation
    l1_adj: dict[str, dict[str, float]] = collections.defaultdict(dict)
    l1_tot_w: collections.Counter[str] = collections.Counter()
    for e in edges_by_level[1]:
        u, v, s = e["source"], e["target"], e["strength"]
        w = s * (1.0 if e["kind"] == "shared" else 0.45)
        l1_adj[u][v] = max(l1_adj[u].get(v, 0.0), w)
        l1_adj[v][u] = max(l1_adj[v].get(u, 0.0), w)
        l1_tot_w[u] += w
        l1_tot_w[v] += w

    remaining = set(l1_ids)
    ordered_l1: list[str] = []
    cur = max(l1_ids, key=lambda nid: (l1_tot_w[nid], node_sizes.get(nid, 0), nid))
    while remaining:
        ordered_l1.append(cur)
        remaining.remove(cur)
        if not remaining:
            break
        cur = max(
            remaining,
            key=lambda cand: (l1_adj[cur].get(cand, 0.0), l1_tot_w[cand], -len(cand)),
        )

    n1 = len(ordered_l1)
    l1_pos: dict[str, list[float]] = {}
    if n1 == 1:
        l1_pos[ordered_l1[0]] = [0.0, 0.0, 0.0]
    else:
        r0 = max(390.0, 145.0 * math.sqrt(n1))
        for i, nid in enumerate(ordered_l1):
            px, py, pz = _fib_sphere_point(i, n1, r0)
            l1_pos[nid] = [px * 1.28, py * 1.05, pz * 0.62]

        for _ in range(95):
            forces = {nid: [0.0, 0.0, 0.0] for nid in ordered_l1}
            for nid in ordered_l1:
                x, y, z = l1_pos[nid]
                forces[nid][0] -= x * 0.024
                forces[nid][1] -= y * 0.024
                forces[nid][2] -= z * 0.024
            for i in range(n1):
                u = ordered_l1[i]
                ux, uy, uz = l1_pos[u]
                for j in range(i + 1, n1):
                    v = ordered_l1[j]
                    vx, vy, vz = l1_pos[v]
                    dx = ux - vx
                    dy = uy - vy
                    dz = uz - vz
                    d = math.sqrt(dx * dx + dy * dy + dz * dz) or 0.01
                    min_sep = (lobe_r[u] + lobe_r[v]) * 1.12 + 75.0
                    if d < min_sep:
                        push = (min_sep - d) * 0.24
                        fx = (dx / d) * push
                        fy = (dy / d) * push
                        fz = (dz / d) * push
                        forces[u][0] += fx
                        forces[u][1] += fy
                        forces[u][2] += fz
                        forces[v][0] -= fx
                        forces[v][1] -= fy
                        forces[v][2] -= fz
            for e in edges_by_level[1]:
                u, v = e["source"], e["target"]
                if u not in l1_pos or v not in l1_pos:
                    continue
                dx = l1_pos[v][0] - l1_pos[u][0]
                dy = l1_pos[v][1] - l1_pos[u][1]
                dz = l1_pos[v][2] - l1_pos[u][2]
                pull = 0.028 * e["strength"] * (1.0 if e["kind"] == "shared" else 0.45)
                forces[u][0] += dx * pull
                forces[u][1] += dy * pull
                forces[u][2] += dz * pull
                forces[v][0] -= dx * pull
                forces[v][1] -= dy * pull
                forces[v][2] -= dz * pull
            for nid in ordered_l1:
                for k in range(3):
                    l1_pos[nid][k] += max(-24.0, min(24.0, forces[nid][k]))

        cx = sum(p[0] for p in l1_pos.values()) / n1
        cy = sum(p[1] for p in l1_pos.values()) / n1
        cz = sum(p[2] for p in l1_pos.values()) / n1
        for nid in ordered_l1:
            l1_pos[nid][0] -= cx
            l1_pos[nid][1] -= cy
            l1_pos[nid][2] -= cz

    for nid, (x, y, z) in l1_pos.items():
        nodes_by_id[nid]["x"] = round(x, 1)
        nodes_by_id[nid]["y"] = round(y, 1)
        nodes_by_id[nid]["z"] = round(z, 1)

    # 3. Place L2 subtopics in 3D shells around their L1 center, pulled toward bridged external systems
    l2_ext_pull: dict[str, list[tuple[str, float]]] = collections.defaultdict(list)
    for e in edges_by_level[2]:
        u, v = e["source"], e["target"]
        if u in nodes_by_id and v in nodes_by_id:
            pu = nodes_by_id[u]["parent_id"]
            pv = nodes_by_id[v]["parent_id"]
            if pu and pv and pu != pv:
                w = e["strength"] * (1.0 if e["kind"] == "shared" else 0.45)
                l2_ext_pull[u].append((pv, w))
                l2_ext_pull[v].append((pu, w))

    l2_pos: dict[str, list[float]] = {}
    for l1_id in l1_ids:
        lx, ly, lz = l1_pos[l1_id]
        children = sorted(
            [cid for cid in nodes_by_id[l1_id]["children"] if cid in nodes_by_id],
            key=lambda cid: (-node_sizes.get(cid, 0), cid),
        )
        m = len(children)
        if m == 0:
            continue
        pos_local: dict[str, list[float]] = {}
        for idx, cid in enumerate(children):
            rad = 45.0 + (lobe_r[l1_id] * 0.48) * math.sqrt((idx + 0.6) / max(1, m))
            dx, dy, dz = _fib_sphere_point(idx, max(2, m), rad)
            pos_local[cid] = [lx + dx, ly + dy, lz + dz]

        for _ in range(50):
            forces = {cid: [0.0, 0.0, 0.0] for cid in children}
            for cid in children:
                dx = lx - pos_local[cid][0]
                dy = ly - pos_local[cid][1]
                dz = lz - pos_local[cid][2]
                d = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
                if d > lobe_r[l1_id] * 0.85:
                    forces[cid][0] += dx * 0.08
                    forces[cid][1] += dy * 0.08
                    forces[cid][2] += dz * 0.08
                elif d < 36.0:
                    forces[cid][0] -= (dx / d) * 3.5
                    forces[cid][1] -= (dy / d) * 3.5
                    forces[cid][2] -= (dz / d) * 3.5
                for ext_l1, w in l2_ext_pull.get(cid, ())[:3]:
                    if ext_l1 in l1_pos:
                        ex, ey, ez = l1_pos[ext_l1]
                        edx = ex - pos_local[cid][0]
                        edy = ey - pos_local[cid][1]
                        edz = ez - pos_local[cid][2]
                        ed = math.sqrt(edx * edx + edy * edy + edz * edz) or 1.0
                        forces[cid][0] += (edx / ed) * (2.6 * w)
                        forces[cid][1] += (edy / ed) * (2.6 * w)
                        forces[cid][2] += (edz / ed) * (2.6 * w)

            for i in range(m):
                u = children[i]
                ux, uy, uz = pos_local[u]
                for j in range(i + 1, m):
                    v = children[j]
                    dx = ux - pos_local[v][0]
                    dy = uy - pos_local[v][1]
                    dz = uz - pos_local[v][2]
                    d = math.sqrt(dx * dx + dy * dy + dz * dz) or 0.01
                    min_sep = (sub_r[u] + sub_r[v]) * 1.05 + 18.0
                    if d < min_sep:
                        push = (min_sep - d) * 0.24
                        fx = (dx / d) * push
                        fy = (dy / d) * push
                        fz = (dz / d) * push
                        forces[u][0] += fx
                        forces[u][1] += fy
                        forces[u][2] += fz
                        forces[v][0] -= fx
                        forces[v][1] -= fy
                        forces[v][2] -= fz

            for cid in children:
                for k in range(3):
                    pos_local[cid][k] += max(-14.0, min(14.0, forces[cid][k]))

        for cid, (x, y, z) in pos_local.items():
            l2_pos[cid] = [x, y, z]
            nodes_by_id[cid]["x"] = round(x, 1)
            nodes_by_id[cid]["y"] = round(y, 1)
            nodes_by_id[cid]["z"] = round(z, 1)

    # 4. Place L3 leaf topics organically in 3D via tree springs + cross-bridge springs + repulsion
    l3_ids = sorted(nid for nid, n in nodes_by_id.items() if n["level"] == 3)
    l3_links: dict[str, list[tuple[str, float]]] = collections.defaultdict(list)
    for e in edges_by_level[3]:
        u, v, s = e["source"], e["target"], e["strength"]
        w = s * (1.0 if e["kind"] == "shared" else 0.4)
        l3_links[u].append((v, w))
        l3_links[v].append((u, w))

    l2_ids = sorted(nid for nid, n in nodes_by_id.items() if n["level"] == 2)
    l3_pos: dict[str, list[float]] = {}
    for l2_id in l2_ids:
        sx, sy, sz = l2_pos.get(l2_id, [0.0, 0.0, 0.0])
        children = sorted(
            [cid for cid in nodes_by_id[l2_id]["children"] if cid in nodes_by_id],
            key=lambda cid: (-len(l3_links[cid]), -node_sizes.get(cid, 0), cid),
        )
        k = len(children)
        if k == 0:
            continue
        pos_l3: dict[str, list[float]] = {}
        for idx, cid in enumerate(children):
            # Organic 3D spherical scatter (not a stiff flat 2D spiral)
            rad = 22.0 + 11.5 * math.sqrt(idx + 0.7)
            dx, dy, dz = _fib_sphere_point(idx, max(3, k), rad)
            # Subtle deterministic asymmetry from id hash so clusters look organically biological
            h = sum(ord(ch) * (i + 1) for i, ch in enumerate(cid))
            jScale = 0.8 + ((h % 45) / 100.0)
            pos_l3[cid] = [sx + dx * jScale, sy + dy * jScale, sz + dz * jScale]

        for _ in range(30):
            forces = {cid: [0.0, 0.0, 0.0] for cid in children}
            for i in range(k):
                u = children[i]
                ux, uy, uz = pos_l3[u]
                # Keep off parent L2 center while staying tethered
                pdx = ux - sx
                pdy = uy - sy
                pdz = uz - sz
                pd = math.sqrt(pdx * pdx + pdy * pdy + pdz * pdz) or 0.01
                ideal_pd = 24.0 + 7.5 * math.sqrt(k)
                if pd < 16.0:
                    forces[u][0] += (pdx / pd) * 2.8
                    forces[u][1] += (pdy / pd) * 2.8
                    forces[u][2] += (pdz / pd) * 2.8
                elif pd > ideal_pd:
                    pull = (pd - ideal_pd) * 0.045
                    forces[u][0] -= (pdx / pd) * pull
                    forces[u][1] -= (pdy / pd) * pull
                    forces[u][2] -= (pdz / pd) * pull

                for j in range(i + 1, k):
                    v = children[j]
                    dx = ux - pos_l3[v][0]
                    dy = uy - pos_l3[v][1]
                    dz = uz - pos_l3[v][2]
                    d = math.sqrt(dx * dx + dy * dy + dz * dz) or 0.01
                    if d < 20.0:
                        push = (20.0 - d) * 0.28
                        fx = (dx / d) * push
                        fy = (dy / d) * push
                        fz = (dz / d) * push
                        forces[u][0] += fx
                        forces[u][1] += fy
                        forces[u][2] += fz
                        forces[v][0] -= fx
                        forces[v][1] -= fy
                        forces[v][2] -= fz

            for cid in children:
                for dim in range(3):
                    pos_l3[cid][dim] += max(-9.0, min(9.0, forces[cid][dim]))

        for cid, pos in pos_l3.items():
            l3_pos[cid] = pos

    # Apply 6 global bridge-spring iterations across L3 so cross-system bridges visibly reach toward each other
    for _ in range(6):
        l3_forces: dict[str, list[float]] = {cid: [0.0, 0.0, 0.0] for cid in l3_pos}
        for e in edges_by_level[3]:
            u, v = e["source"], e["target"]
            if u not in l3_pos or v not in l3_pos:
                continue
            dx = l3_pos[v][0] - l3_pos[u][0]
            dy = l3_pos[v][1] - l3_pos[u][1]
            dz = l3_pos[v][2] - l3_pos[u][2]
            d = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
            step = min(14.0, 0.045 * d * e["strength"] * (1.0 if e["kind"] == "shared" else 0.45))
            fx, fy, fz = (dx / d) * step, (dy / d) * step, (dz / d) * step
            l3_forces[u][0] += fx
            l3_forces[u][1] += fy
            l3_forces[u][2] += fz
            l3_forces[v][0] -= fx
            l3_forces[v][1] -= fy
            l3_forces[v][2] -= fz
        for cid, pos in l3_pos.items():
            # Tether back toward parent L2 so organic stretch never detaches cluster
            p_id = nodes_by_id[cid].get("parent_id")
            if p_id and p_id in l2_pos:
                sx, sy, sz = l2_pos[p_id]
                pos[0] += l3_forces[cid][0] + (sx - pos[0]) * 0.08
                pos[1] += l3_forces[cid][1] + (sy - pos[1]) * 0.08
                pos[2] += l3_forces[cid][2] + (sz - pos[2]) * 0.08

    for cid, (x, y, z) in l3_pos.items():
        nodes_by_id[cid]["x"] = round(x, 1)
        nodes_by_id[cid]["y"] = round(y, 1)
        nodes_by_id[cid]["z"] = round(z, 1)

    # 5. Compute actual visual 3D lobe radius per L1 node
    for l1_id in l1_ids:
        lx, ly, lz = nodes_by_id[l1_id]["x"], nodes_by_id[l1_id]["y"], nodes_by_id[l1_id]["z"]
        max_d = 85.0
        for l2_id in nodes_by_id[l1_id]["children"]:
            n2 = nodes_by_id.get(l2_id)
            if not n2:
                continue
            max_d = max(max_d, math.sqrt((n2["x"] - lx) ** 2 + (n2["y"] - ly) ** 2 + (n2["z"] - lz) ** 2) + 26.0)
            for l3_id in n2["children"]:
                n3 = nodes_by_id.get(l3_id)
                if not n3:
                    continue
                max_d = max(max_d, math.sqrt((n3["x"] - lx) ** 2 + (n3["y"] - ly) ** 2 + (n3["z"] - lz) ** 2) + 18.0)
        nodes_by_id[l1_id]["lobe_r"] = round(max_d, 1)


def _attach_frontier_metrics(
    nodes_by_id: dict[str, dict[str, Any]],
    edges_by_level: dict[int, list[dict[str, Any]]],
) -> None:
    """Populate `mastered_neighbors` and `is_frontier` (Connected Gaps) per node."""
    adj: dict[str, list[tuple[str, dict[str, Any]]]] = collections.defaultdict(list)
    for edges in edges_by_level.values():
        for e in edges:
            if e["kind"] == "tree":
                continue
            adj[e["source"]].append((e["target"], e))
            adj[e["target"]].append((e["source"], e))

    for nid, node in nodes_by_id.items():
        mastered = []
        seen_nb: set[str] = set()
        for other_id, edge in adj.get(nid, ()):
            if other_id in seen_nb:
                continue
            other = nodes_by_id.get(other_id)
            if not other:
                continue
            if other["learned_pct"] >= 0.70 and other["total"] >= 5:
                seen_nb.add(other_id)
                kind_mult = 1.0 if edge["kind"] == "shared" else 0.7
                mastered.append((
                    kind_mult * edge["strength"],
                    {
                        "id": other_id,
                        "label": other["label"],
                        "learned_pct": other["learned_pct"],
                        "kind": edge["kind"],
                        "shared": edge["shared"],
                        "terms": edge["terms"],
                    },
                ))
        mastered.sort(key=lambda x: -x[0])
        top_mastered = [item for _score, item in mastered[:3]]
        node["mastered_neighbors"] = top_mastered
        node["is_frontier"] = bool(
            top_mastered
            and (node["suspended"] >= 3 or node["hy_suspended"] >= 1)
            and node["learned_pct"] < 0.85
        )


def _compute_overlays(
    chosen_deck: str,
    norm_decks: dict[int, str],
    note_stats: dict[int, list[int]],
    note_tags: dict[int, list[str]],
    note_dids: dict[int, set[int]],
    node_nids: dict[int, dict[str, set[int]]],
    nodes_list: list[dict[str, Any]],
    taxonomy_mode: str = "step_subjects",
    tag_strip_root: str = "",
) -> list[dict[str, Any]]:
    """Build subdeck and resource tag overlays (e.g. UWorld Wrong, Pathoma, or custom user tags)."""
    min_notes = 5 if len(note_stats) >= 100 else 1
    overlays: list[dict[str, Any]] = []

    # Invert nid -> list of node indices for O(notes) overlay counting
    nid_to_node_idxs: dict[int, list[int]] = collections.defaultdict(list)
    node_id_to_idx = {n["id"]: i for i, n in enumerate(nodes_list)}
    for lvl in (1, 2, 3):
        for node_id, nids in node_nids[lvl].items():
            idx = node_id_to_idx.get(node_id)
            if idx is None:
                continue
            for nid in nids:
                nid_to_node_idxs[nid].append(idx)

    def _tally_overlay(nids: set[int]) -> list[int]:
        counts: collections.Counter[int] = collections.Counter()
        for nid in nids:
            tot = note_stats[nid][0]
            for idx in nid_to_node_idxs.get(nid, ()):
                counts[idx] += tot
        pairs: list[int] = []
        for idx, cnt in counts.items():
            pairs.append(idx)
            pairs.append(cnt)
        return pairs

    # 1. Subdeck overlays inside the filtered deck (skipping root deck itself)
    did_to_subdecks: dict[int, str] = {}
    for did, dname in norm_decks.items():
        if not dname or "Filtered Deck" in dname:
            continue
        if chosen_deck == "ALL":
            if "::" in dname:
                did_to_subdecks[did] = dname
        elif dname.startswith(chosen_deck + "::"):
            did_to_subdecks[did] = dname

    subdeck_nids: dict[str, set[int]] = collections.defaultdict(set)
    for nid, dids in note_dids.items():
        for did in dids:
            sd = did_to_subdecks.get(did)
            if sd:
                subdeck_nids[sd].add(nid)

    for sd, nids in subdeck_nids.items():
        if len(nids) < min_notes:
            continue
        short = sd.rsplit("::", 1)[-1]
        if short.lower() == "past":
            continue
        pairs = _tally_overlay(nids)
        if not pairs:
            continue
        tot_cards = sum(note_stats[x][0] for x in nids)
        overlays.append({
            "id": f"subdeck:{sd}",
            "label": clean_label(short),
            "group": "subdeck",
            "query_term": escape_anki_deck(sd),
            "total_cards": tot_cards,
            "pairs": pairs,
        })

    # 2. Resource tag overlays (#Pathoma, #SketchyPharm, #B&B, #UWorld, #NBME, etc.)
    res_nids: dict[str, set[int]] = collections.defaultdict(set)
    prefix_checks = [(pref, pref + "::", lbl) for pref, lbl in OVERLAY_RESOURCES]
    for nid in note_stats:
        for t in note_tags.get(nid, ()):
            for pref, pref_colon, _lbl in prefix_checks:
                if t == pref or t.startswith(pref_colon):
                    res_nids[pref].add(nid)

    res_matched = False
    for pref, lbl in OVERLAY_RESOURCES:
        nids = res_nids.get(pref)
        if not nids or len(nids) < min_notes:
            continue
        pairs = _tally_overlay(nids)
        if not pairs:
            continue
        res_matched = True
        tot_cards = sum(note_stats[x][0] for x in nids)
        overlays.append({
            "id": f"res:{pref}",
            "label": lbl,
            "group": "resource",
            "query_term": escape_anki_tag(pref),
            "total_cards": tot_cards,
            "pairs": pairs,
        })

    # 3. For non-AnKing decks without built-in resource tags, auto-detect user cross-cutting tags
    if not res_matched and taxonomy_mode != "step_subjects":
        total_notes = len(note_stats)
        max_notes = max(min_notes, int(total_notes * 0.85))
        l1_labels = {n["label"].lower() for n in nodes_list if n["level"] == 1}
        has_hier = any(
            "::" in t and not is_utility_tag(t)
            for nid in note_stats
            for t in note_tags.get(nid, ())
        )
        # Skip flat-only auto-overlays if L1 nodes are already flat tags themselves
        if taxonomy_mode == "decks" or has_hier:
            custom_nids: dict[str, set[int]] = collections.defaultdict(set)
            for nid in note_stats:
                for t in note_tags.get(nid, ()):
                    if is_utility_tag(t):
                        continue
                    if taxonomy_mode == "generic_tags":
                        if "::" not in t:
                            custom_nids[t].add(nid)
                        else:
                            root = t.split("::", 1)[0]
                            if (
                                root
                                and root != tag_strip_root
                                and clean_label(root).lower() not in l1_labels
                            ):
                                custom_nids[root].add(nid)
                    else:
                        root = t.split("::", 1)[0]
                        if root:
                            custom_nids[root].add(nid)
            ranked = [
                (tag, nids)
                for tag, nids in custom_nids.items()
                if min_notes <= len(nids) <= max_notes
            ]
            ranked.sort(key=lambda kv: (-len(kv[1]), kv[0]))
            for tag, nids in ranked[:16]:
                pairs = _tally_overlay(nids)
                if not pairs:
                    continue
                tot_cards = sum(note_stats[x][0] for x in nids)
                overlays.append({
                    "id": f"tag:{tag}",
                    "label": f"#{clean_label(tag)}",
                    "group": "resource",
                    "query_term": escape_anki_tag(tag),
                    "total_cards": tot_cards,
                    "pairs": pairs,
                })

    def _sort_key(ov: dict[str, Any]) -> tuple[int, int, int]:
        grp = 0 if ov["group"] == "subdeck" else 1
        priority = 0 if ("wrong" in ov["label"].lower() or "uworld" in ov["label"].lower()) else 1
        return (grp, priority, -ov["total_cards"])

    overlays.sort(key=_sort_key)
    return overlays


def build_graph(
    notes_rows: list[tuple[int, str, str]],
    cards_rows: list[tuple[int, int, int, int, int, int, int]],
    decks_map: dict[int, str],
    deck_filter: str = "auto",
    exam_scope: str = "all",
    lens_id: str | None = None,
    revlog_recent: dict[int, int] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Build the unified 3D Anki Atlas graph payload with deck, exam, overlay, and revlog data."""
    norm_decks = {did: name.replace("\x1f", "::").strip() for did, name in decks_map.items()}
    deck_options, default_deck = detect_deck_options(cards_rows, norm_decks)
    valid_deck_ids = {o["id"] for o in deck_options}

    # Backwards-compat support for legacy lens_id callers
    if lens_id == "firstaid_step1":
        exam_scope = "step1"
        if deck_filter == "auto":
            deck_filter = "ALL"
    elif lens_id == "step2_subjects":
        exam_scope = "step2"
        if deck_filter == "auto":
            deck_filter = "ALL"
    elif lens_id == "decks" and deck_filter == "auto":
        deck_filter = "ALL"

    chosen_deck = deck_filter if (deck_filter and deck_filter != "auto" and deck_filter in valid_deck_ids) else default_deck
    chosen_exam = exam_scope if exam_scope in ("all", "step1", "step2") else "all"

    if chosen_deck == "ALL":
        filtered_cards = cards_rows
    else:
        pref = chosen_deck + "::"
        allowed_dids = {did for did, name in norm_decks.items() if name == chosen_deck or name.startswith(pref)}
        filtered_cards = [row for row in cards_rows if row[2] in allowed_dids]

    note_stats, note_tags, note_did, note_dids = _aggregate_notes(
        notes_rows,
        filtered_cards,
        revlog_recent=revlog_recent,
        now_ms=now_ms,
    )

    # Check which Step tag taxonomies exist in the filtered deck
    has_step1 = False
    has_step2 = False
    has_yield = False
    for nid in note_stats:
        for t in note_tags.get(nid, ()):
            if not has_yield:
                low = t.lower()
                if "1-highyield" in low or "2-relativelyhighyield" in low:
                    has_yield = True
            if not has_step1 and t.startswith("#AK_Step1_v12::#FirstAid::"):
                has_step1 = True
            elif not has_step2 and t.startswith("#AK_Step2_v12::#Subjects::"):
                has_step2 = True
        if has_step1 and has_step2 and has_yield:
            break

    tag_strip_root = ""
    if (has_step1 or has_step2) and lens_id != "decks":
        taxonomy_mode = "step_subjects"
    elif lens_id != "decks":
        unique_decks = {
            norm_decks.get(did, "")
            for dids in note_dids.values()
            for did in dids
            if norm_decks.get(did, "") and "Filtered Deck" not in norm_decks.get(did, "")
        }
        filtered_note_tags = {nid: note_tags.get(nid, []) for nid in note_stats}
        use_generic, tag_strip_root = detect_generic_tag_config(filtered_note_tags, len(unique_decks))
        taxonomy_mode = "generic_tags" if use_generic else "decks"
    else:
        taxonomy_mode = "decks"

    use_step_subjects = taxonomy_mode == "step_subjects"
    query_kind = "tag" if taxonomy_mode in ("step_subjects", "generic_tags") else "deck"
    if use_step_subjects:
        if chosen_exam == "step1" and not has_step1 and has_step2:
            chosen_exam = "all"
        elif chosen_exam == "step2" and not has_step2 and has_step1:
            chosen_exam = "all"

    # Build hierarchy nodes and deduplicated nid sets per node
    node_nids: dict[int, dict[str, set[int]]] = {
        1: collections.defaultdict(set),
        2: collections.defaultdict(set),
        3: collections.defaultdict(set),
    }
    node_meta: dict[str, dict[str, Any]] = {}
    children_sets: dict[str, set[str]] = collections.defaultdict(set)

    for nid, _tags_str, _flds_str in notes_rows:
        if nid not in note_stats:
            continue
        if taxonomy_mode == "step_subjects":
            paths = extract_step_paths(note_tags.get(nid, []), exam_scope=chosen_exam)
        elif taxonomy_mode == "generic_tags":
            paths = extract_generic_tag_paths(note_tags.get(nid, []), strip_root=tag_strip_root)
            if not paths:
                dname = norm_decks.get(note_did.get(nid, 0), "")
                dpath = extract_deck_path(dname, base_prefix=chosen_deck)
                paths = [dpath] if dpath else []
        else:
            dname = norm_decks.get(note_did.get(nid, 0), "")
            dpath = extract_deck_path(dname, base_prefix=chosen_deck)
            paths = [dpath] if dpath else []

        for path in paths:
            parent_id: str | None = None
            clean_trail: list[str] = []
            for idx, (key, label, raw) in enumerate(path):
                lvl = idx + 1
                node_id = f"L{lvl}:{key}"
                clean_trail.append(label)
                node_nids[lvl][node_id].add(nid)
                if node_id not in node_meta:
                    node_meta[node_id] = {
                        "id": node_id,
                        "level": lvl,
                        "parent_id": parent_id,
                        "label": label,
                        "path": list(clean_trail),
                        "raw": raw,
                        "raw_list": [raw] if raw else [],
                        "query_kind": query_kind,
                    }
                elif raw and raw not in node_meta[node_id]["raw_list"]:
                    node_meta[node_id]["raw_list"].append(raw)
                if parent_id is not None:
                    children_sets[parent_id].add(node_id)
                parent_id = node_id

    # Compute node metrics (deduplicated per nid)
    nodes_by_id: dict[str, dict[str, Any]] = {}
    node_sizes: dict[str, int] = {}
    all_nids_in_view: set[int] = set()
    browser_deck = chosen_deck if taxonomy_mode in ("step_subjects", "generic_tags") else ""

    for lvl in (1, 2, 3):
        for node_id, nids in node_nids[lvl].items():
            if not nids:
                continue
            tot = mat = yng = nw = susp = hy_tot = hy_susp = lapses_sum = act = leech = weak_c = r7 = r30 = 0
            for nid in nids:
                st = note_stats[nid]
                tot += st[0]
                mat += st[1]
                yng += st[2]
                nw += st[3]
                susp += st[4]
                hy_tot += st[5]
                hy_susp += st[6]
                lapses_sum += st[7]
                act += st[8]
                leech += st[9]
                weak_c += st[10]
                r7 += st[11]
                r30 += st[12]
            if tot == 0:
                continue
            if lvl == 1:
                all_nids_in_view.update(nids)
            meta = node_meta[node_id]
            learned_pct = round(act / tot, 4)
            mature_pct = round(mat / tot, 4)
            suspended_pct = round(susp / tot, 4)
            hy_suspended_pct = round(hy_susp / hy_tot, 4) if hy_tot > 0 else 0.0
            lapses_avg = round(lapses_sum / act, 3) if act > 0 else 0.0
            weak_score = round((lapses_sum + 2.0 * leech) / act, 4) if act >= 5 else 0.0
            raw_arg = meta["raw_list"] if len(meta["raw_list"]) > 1 else meta["raw"]

            nodes_by_id[node_id] = {
                "id": node_id,
                "level": lvl,
                "parent_id": meta["parent_id"],
                "label": meta["label"],
                "path": meta["path"],
                "raw": meta["raw"],
                "query_kind": query_kind,
                "children": sorted(children_sets.get(node_id, ())),
                "state": _classify_node_state(mat, yng, nw, susp, tot),
                "total": tot,
                "mature": mat,
                "young": yng,
                "new": nw,
                "suspended": susp,
                "active": act,
                "hy_total": hy_tot,
                "hy_suspended": hy_susp,
                "lapses_avg": lapses_avg,
                "leech_count": leech,
                "weak_cards": weak_c,
                "rev_7d": r7,
                "rev_30d": r30,
                "learned_pct": learned_pct,
                "mature_pct": mature_pct,
                "suspended_pct": suspended_pct,
                "hy_suspended_pct": hy_suspended_pct,
                "weak_score": weak_score,
                "is_frontier": False,
                "mastered_neighbors": [],
                "lobe_r": 0.0,
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "queries": {
                    "all": build_browser_query(raw_arg, query_kind, "all", deck_prefix=browser_deck),
                    "suspended": build_browser_query(raw_arg, query_kind, "suspended", deck_prefix=browser_deck),
                    "hy_suspended": build_browser_query(raw_arg, query_kind, "hy_suspended", deck_prefix=browser_deck),
                    "weak": build_browser_query(raw_arg, query_kind, "weak", deck_prefix=browser_deck),
                },
            }
            node_sizes[node_id] = tot

    # Layer 2: Shared-card bridges at each level
    l1_min = 5 if len(node_nids[1]) >= 10 else 2
    edges_l1 = _compute_shared_edges(1, node_nids[1], node_meta, min_shared=l1_min, max_per_node=8, max_total=70, deck_prefix=browser_deck)
    edges_l2 = _compute_shared_edges(2, node_nids[2], node_meta, min_shared=3 if len(node_nids[2]) >= 12 else 1, max_per_node=6, max_total=280, deck_prefix=browser_deck)
    edges_l3 = _compute_shared_edges(3, node_nids[3], node_meta, min_shared=2, max_per_node=6, max_total=1500, deck_prefix=browser_deck)

    if query_kind == "deck":
        if not edges_l1 and len(node_nids[1]) >= 2:
            edges_l1 = _compute_deck_tag_bridges(1, node_nids[1], node_meta, note_tags, min_shared=2, max_per_node=6, max_total=60)
        if not edges_l2 and len(node_nids[2]) >= 2:
            edges_l2 = _compute_deck_tag_bridges(2, node_nids[2], node_meta, note_tags, min_shared=2, max_per_node=6, max_total=160)
        if not edges_l3 and len(node_nids[3]) >= 2:
            edges_l3 = _compute_deck_tag_bridges(3, node_nids[3], node_meta, note_tags, min_shared=2, max_per_node=5, max_total=300)

    shared_edges_by_level = {1: edges_l1, 2: edges_l2, 3: edges_l3}
    existing_shared_pairs = {
        lvl: {tuple(sorted((e["source"], e["target"]))) for e in elist}
        for lvl, elist in shared_edges_by_level.items()
    }

    # Layer 3: Offline TF-IDF concept links (run at finest populated level)
    target_lvl = 3 if len(node_nids[3]) >= 2 else (2 if len(node_nids[2]) >= 2 else 1)
    target_nodes = sorted(nid for nid in node_nids[target_lvl] if nid in nodes_by_id)
    concept_by_level = _compute_concept_edges(
        notes_rows=notes_rows,
        target_nodes=target_nodes,
        node_nids=node_nids[target_lvl],
        node_meta=node_meta,
        existing_shared_pairs_by_level=existing_shared_pairs,
        target_level=target_lvl,
    )

    edges_by_level = {
        1: edges_l1 + concept_by_level.get(1, []),
        2: edges_l2 + concept_by_level.get(2, []),
        3: edges_l3 + concept_by_level.get(3, []),
    }

    # Connected Gaps (Frontier) metadata
    _attach_frontier_metrics(nodes_by_id, edges_by_level)

    # Organic 3D force-directed layout across L1/L2/L3
    _layout_3d_organic(nodes_by_id, edges_by_level, node_sizes)

    l1_ids = [nid for nid, n in nodes_by_id.items() if n["level"] == 1]
    l2_ids = [nid for nid, n in nodes_by_id.items() if n["level"] == 2]

    tree_edges: list[dict[str, Any]] = []
    for nid, n in nodes_by_id.items():
        pid = n.get("parent_id")
        if pid and pid in nodes_by_id:
            tree_edges.append({
                "id": f"ET:{pid}|{nid}",
                "level": n["level"],
                "source": pid,
                "target": nid,
                "kind": "tree",
                "shared": 0,
                "strength": 0.38 if n["level"] == 2 else 0.32,
                "terms": [],
                "query": "",
            })

    # Overall collection summary for this filtered view
    s_tot = s_mat = s_yng = s_nw = s_susp = s_act = s_hy_susp = s_hy_tot = s_weak = s_r7 = s_r30 = 0
    for nid in all_nids_in_view:
        st = note_stats[nid]
        s_tot += st[0]
        s_mat += st[1]
        s_yng += st[2]
        s_nw += st[3]
        s_susp += st[4]
        s_hy_tot += st[5]
        s_hy_susp += st[6]
        s_act += st[8]
        s_weak += st[10]
        s_r7 += st[11]
        s_r30 += st[12]

    nodes_list = list(nodes_by_id.values())

    # Overlays (subdecks like UWorld Wrong + resource tags like Pathoma/SketchyPharm)
    overlays = _compute_overlays(
        chosen_deck=chosen_deck,
        norm_decks=norm_decks,
        note_stats=note_stats,
        note_tags=note_tags,
        note_dids=note_dids,
        node_nids=node_nids,
        nodes_list=nodes_list,
        taxonomy_mode=taxonomy_mode,
        tag_strip_root=tag_strip_root,
    )

    # Ranked "Next Gaps" queue at finest populated topic level
    l3_count = sum(1 for n in nodes_by_id.values() if n["level"] == 3)
    gap_lvl = 3 if l3_count > 0 else (2 if len(l2_ids) > 0 else 1)
    gap_candidates = [n for n in nodes_by_id.values() if n["level"] == gap_lvl and n["suspended"] > 0]
    gap_candidates.sort(
        key=lambda n: (
            -(n["suspended"] * (1.5 if n["is_frontier"] else 1.0)),
            -n["suspended"],
            n["label"],
        )
    )
    next_gaps = [n["id"] for n in gap_candidates[:50]]

    all_edges = tree_edges + edges_by_level[1] + edges_by_level[2] + edges_by_level[3]
    lens_label = (
        f"subjects_{chosen_exam}"
        if taxonomy_mode == "step_subjects"
        else ("generic_tags" if taxonomy_mode == "generic_tags" else "decks")
    )

    return {
        "lens": lens_label,
        "deck_filter": chosen_deck,
        "exam_scope": chosen_exam,
        "decks": deck_options,
        "overlays": overlays,
        "next_gaps": next_gaps,
        "summary": {
            "total_cards": s_tot,
            "mature": s_mat,
            "young": s_yng,
            "new": s_nw,
            "suspended": s_susp,
            "active": s_act,
            "hy_total": s_hy_tot,
            "hy_suspended": s_hy_susp,
            "weak_cards": s_weak,
            "rev_7d": s_r7,
            "rev_30d": s_r30,
            "has_revlog": s_r30 > 0,
            "learned_pct": round(s_act / s_tot, 4) if s_tot else 0.0,
            "l1_count": len(l1_ids),
            "l2_count": len(l2_ids),
            "l3_count": l3_count,
            "shared_edges": len(edges_l1) + len(edges_l2) + len(edges_l3),
            "concept_edges": len(concept_by_level[1]) + len(concept_by_level[2]) + len(concept_by_level[3]),
            "has_yield": has_yield,
            "has_step1": has_step1,
            "has_step2": has_step2,
            "use_step_subjects": use_step_subjects,
            "taxonomy_mode": taxonomy_mode,
            "tag_strip_root": tag_strip_root,
        },
        "nodes": list(nodes_by_id.values()),
        "edges": all_edges,
    }
