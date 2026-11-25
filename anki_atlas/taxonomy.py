"""Pure-Python tag/deck taxonomy, unified Step 1+2 subject mapping, and filter helpers.

Kept free of ``aqt`` imports so unit tests run under plain ``python3``.
"""

from __future__ import annotations

import collections
import re
from typing import Iterable

RESOURCE_ROOTS = frozenset({"#B&B", "#Pathoma", "#SketchyPharm", "#SketchyMicro"})

RESOURCE_LABELS = {
    "#B&B": "Boards & Beyond",
    "#Pathoma": "Pathoma",
    "#SketchyPharm": "Sketchy Pharm",
    "#SketchyMicro": "Sketchy Micro",
}

OVERLAY_RESOURCES = (
    ("#AK_Step1_v12::#Pathoma", "Pathoma"),
    ("#AK_Step1_v12::#B&B", "Boards & Beyond"),
    ("#AK_Step1_v12::#SketchyPharm", "Sketchy Pharm"),
    ("#AK_Step1_v12::#SketchyMicro", "Sketchy Micro"),
    ("#AK_Step1_v12::#SketchyPath", "Sketchy Path"),
    ("#AK_Step1_v12::#Pixorize", "Pixorize"),
    ("#AK_Step1_v12::#Bootcamp", "Bootcamp"),
    ("#AK_Step1_v12::#UWorld", "UWorld (Step 1)"),
    ("#AK_Step2_v12::#UWorld", "UWorld (Step 2)"),
    ("#AK_Step1_v12::#AMBOSS", "AMBOSS"),
    ("#AK_Step1_v12::#NBME", "NBME"),
)

# Canonical 17-subject unified map across AnKing Step 1 (#FirstAid) & Step 2 (#Subjects)
STEP1_SUBJECT_MAP = {
    "01_Biochem": "Biochemistry",
    "02_Immunology": "Immunology",
    "03_Microbiology": "Microbiology",
    "04_Pathology": "Pathology",
    "05_Pharm": "Pharmacology",
    "06_Public_Health": "Public Health & Biostats",
    "07_Cardiovascular": "Cardiology",
    "08_Endocrine": "Endocrine",
    "09_Gastrointestinal": "Gastrointestinal",
    "10_Hematology_and_Oncology": "Heme / Onc",
    "11_Musculoskeletal_Skin_and_Connective_Tissue": "MSK & Derm",
    "12_Neurology_and_Special_Senses": "Neurology",
    "13_Psych": "Psychiatry",
    "14_Renal": "Renal",
    "15_Repro": "Repro & OB-GYN",
    "16_Respiratory": "Pulmonology",
}

STEP2_SUBJECT_MAP = {
    "Cardiology": "Cardiology",
    "Dermatology": "MSK & Derm",
    "Endocrinology": "Endocrine",
    "Epidemiology_&_Social_Sciences": "Public Health & Biostats",
    "Gastroenterology": "Gastrointestinal",
    "Hematology": "Heme / Onc",
    "Immunology_&_Pathology": "Immunology",
    "Microbiology": "Microbiology",
    "Nephrology_&_Urology": "Renal",
    "Neurology": "Neurology",
    "Obstetrics_&_Gynecology": "Repro & OB-GYN",
    "Orthopedics_&_Rheumatology": "MSK & Derm",
    "Psychiatry": "Psychiatry",
    "Pulmonology": "Pulmonology",
    "Surgery_&_EM": "Surgery & EM",
    "*Pharm_Extra": "Pharmacology",
}

PRESERVED_ACRONYMS = {
    "gi", "msk", "cns", "pns", "pth", "dna", "rna", "mrna", "trna", "rrna",
    "hiv", "aids", "copd", "gerd", "ecg", "ekg", "b&b", "ent", "ob", "gyn",
    "cv", "uti", "htn", "dm", "ckd", "aki", "chf", "mi", "em", "im", "hpv",
    "sle", "ra", "ibd", "tb", "hbv", "hcv", "hsv", "ebv", "cmv", "rsv",
    "mri", "ct", "csf", "rbc", "wbc", "bun", "gfr", "adh", "acth", "tsh",
    "lh", "fsh", "hcg", "iga", "ige", "igg", "igm", "mhc", "hla", "pcr",
    "atp", "nadh", "fadh2", "tca", "hmg", "ace", "arb", "nsaid", "ssri",
    "snri", "maoi", "ppi", "ccb", "dvt", "pe", "ards", "dic", "ttp", "hus",
    "itp", "all", "aml", "cll", "cml", "mm", "nhl", "hl", "anca", "gbm",
    "pkd", "rta", "men", "pcos", "bph", "psa", "er", "pr", "her2", "brca",
    "ms", "als", "mg", "gbs", "tia", "cva", "sah", "sdh", "edh", "icp",
    "nmda", "gaba", "ach", "da", "ne", "tnf", "il", "ifn", "tgf", "egf",
    "vegf", "pdgf", "hsk", "nbme", "usmle", "anki",
}

_PREFIX_NUM_RE = re.compile(r"^\d+[a-z]?[_\-.]+")


def clean_label(raw: str) -> str:
    """Turn an AnKing tag segment or deck segment into a clean readable title."""
    if not raw:
        return ""
    s = raw.strip()
    if s in RESOURCE_LABELS:
        return RESOURCE_LABELS[s]
    s = s.lstrip("#^*!~")
    s = _PREFIX_NUM_RE.sub("", s)
    s = s.lstrip("#^*!~")
    s = s.replace("_&_", " & ")
    s = re.sub(r"_and_", " & ", s)
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return raw.strip()

    words = []
    for i, word in enumerate(s.split(" ")):
        low = word.lower()
        stripped = low.strip("(),.:;/")
        if stripped in PRESERVED_ACRONYMS:
            words.append(word.upper() if word.islower() else word)
        elif i == 0 and word and word[0].islower():
            words.append(word[0].upper() + word[1:])
        else:
            words.append(word)
    return " ".join(words)


def escape_anki_tag(tag: str) -> str:
    """Escape an Anki hierarchical tag for exact Browser search matching."""
    escaped = (
        tag.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("*", "\\*")
        .replace("_", "\\_")
    )
    if any(ch.isspace() for ch in escaped):
        return f'tag:"{escaped}"'
    return f"tag:{escaped}"


def escape_anki_deck(deck_name: str) -> str:
    """Format an Anki deck name for Browser search matching."""
    escaped = deck_name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"deck:{escaped}"'


def is_high_yield_note(tags: Iterable[str]) -> bool:
    """Return True if note carries AnKing high-yield or generic high_yield tags."""
    for t in tags:
        low = t.lower()
        if "low/highyield" in low or "highyield" in low:
            tail = low.rsplit("::", 1)[-1]
            if tail.startswith("1-highyield") or tail.startswith("2-relativelyhighyield"):
                return True
        for seg in low.split("::"):
            clean_seg = seg.lstrip("#^!")
            if clean_seg in ("high_yield", "highyield", "high-yield") or clean_seg.endswith("::high_yield"):
                return True
    return False


_UTILITY_TAG_EXACT = {
    "leech",
    "marked",
    "suspended",
    "buried",
    "flag",
    "flagged",
    "duplicate",
    "dupes",
    "ankihub",
    "delete",
    "deleted",
}


def is_utility_tag(tag: str) -> bool:
    """Return True for maintenance/status tags that shouldn't form map topics."""
    t = (tag or "").strip()
    if not t:
        return True
    low = t.lower()
    if low.startswith(("!", "^", "ankihub", "anki_hub")):
        return True
    for seg in low.split("::"):
        s = seg.lstrip("#")
        if not s or s in _UTILITY_TAG_EXACT or s.startswith(("!", "^", "ankihub")):
            return True
    if re.fullmatch(r"[#\d_.-]+", low):
        return True
    return False


def is_leech_note(tags: Iterable[str]) -> bool:
    """Return True if note is explicitly tagged as a leech."""
    for t in tags:
        if t.lower() == "leech" or t.lower().endswith("::leech"):
            return True
    return False


def detect_deck_options(
    cards_rows: Iterable[tuple],
    decks_map: dict[int, str],
) -> tuple[list[dict], str]:
    """Return ordered deck filter options and the smart default deck filter."""
    exact_counts: collections.Counter[str] = collections.Counter()
    rollup_counts: collections.Counter[str] = collections.Counter()

    for row in cards_rows:
        did = row[2]
        dname = decks_map.get(did, "").replace("\x1f", "::").strip()
        if not dname:
            continue
        exact_counts[dname] += 1
        parts = dname.split("::")
        for depth in range(1, min(len(parts), 3) + 1):
            pref = "::".join(parts[:depth])
            rollup_counts[pref] += 1

    total_cards = sum(exact_counts.values())
    options: list[dict] = []

    has_anking = rollup_counts.get("AnKing Step Deck", 0) > 0
    if has_anking:
        options.append({
            "id": "AnKing Step Deck",
            "label": "AnKing Step Deck",
            "count": rollup_counts["AnKing Step Deck"],
        })

    options.append({
        "id": "ALL",
        "label": "All Decks",
        "count": total_cards,
    })

    # Add top-level decks and AnKing depth-2 subdecks (skipping empty & temp Filtered Decks)
    seen = {o["id"] for o in options}
    top_decks = sorted(
        (d for d in rollup_counts if "::" not in d and not d.startswith("Filtered Deck")),
        key=lambda d: (-rollup_counts[d], d),
    )
    for d in top_decks:
        if d not in seen and rollup_counts[d] >= 1:
            seen.add(d)
            options.append({"id": d, "label": clean_label(d), "count": rollup_counts[d]})

    if has_anking:
        sub_decks = sorted(
            (
                d
                for d in rollup_counts
                if d.startswith("AnKing Step Deck::") and d.count("::") == 1 and rollup_counts[d] >= 5
            ),
            key=lambda d: (-rollup_counts[d], d),
        )
        for d in sub_decks:
            if d not in seen:
                seen.add(d)
                short = d.split("::", 1)[1]
                options.append({"id": d, "label": f"AnKing › {clean_label(short)}", "count": rollup_counts[d]})

    default_deck = "AnKing Step Deck" if has_anking else "ALL"
    return options, default_deck


def extract_step_paths(tags: list[str], exam_scope: str = "all") -> list[list[tuple[str, str, str]]]:
    """Extract unified 1..3-level subject paths for Step 1, Step 2, or unified All.

    Each returned path element is ``(node_key, label, raw_tag_prefix)``.
    """
    paths: list[list[tuple[str, str, str]]] = []
    seen_leaves: set[tuple[str, ...]] = set()
    include_s1 = exam_scope in ("all", "step1")
    include_s2 = exam_scope in ("all", "step2")

    for t in tags:
        parts = t.split("::")
        if include_s1 and len(parts) >= 3 and parts[0] == "#AK_Step1_v12" and parts[1] == "#FirstAid":
            raw_sys = parts[2]
            subj = STEP1_SUBJECT_MAP.get(raw_sys) or clean_label(raw_sys)
            segs = parts[3:5]
            base_prefix = f"#AK_Step1_v12::#FirstAid::{raw_sys}"
            exam_tag = "S1"
        elif include_s2 and len(parts) >= 3 and parts[0] == "#AK_Step2_v12" and parts[1] == "#Subjects":
            raw_sys = parts[2]
            if raw_sys == "*Memes":
                continue
            subj = STEP2_SUBJECT_MAP.get(raw_sys) or clean_label(raw_sys)
            segs = parts[3:5]
            base_prefix = f"#AK_Step2_v12::#Subjects::{raw_sys}"
            exam_tag = "S2"
        else:
            continue

        # Build unified L1 -> L2 -> L3 path
        trail_key = (subj, exam_tag, *segs)
        if trail_key in seen_leaves:
            continue
        seen_leaves.add(trail_key)

        path: list[tuple[str, str, str]] = [(subj, subj, base_prefix)]
        raw_acc = base_prefix
        key_acc = [subj, exam_tag]
        for seg in segs:
            if not seg:
                break
            raw_acc = f"{raw_acc}::{seg}"
            key_acc.append(seg)
            path.append((
                "::".join(key_acc),
                clean_label(seg),
                raw_acc,
            ))
        paths.append(path)

    return paths


def extract_deck_path(deck_name: str, base_prefix: str = "") -> list[tuple[str, str, str]]:
    """Extract up to 3-level hierarchy path for a deck name (normalized with '::')."""
    normalized = deck_name.replace("\x1f", "::").strip()
    if not normalized:
        return []
    parts = [p for p in normalized.split("::") if p]
    if base_prefix and base_prefix != "ALL":
        pref_parts = [p for p in base_prefix.split("::") if p]
        if len(parts) > len(pref_parts) and parts[: len(pref_parts)] == pref_parts:
            parts = parts[len(pref_parts) :]
            acc = list(pref_parts)
        else:
            acc = []
    else:
        acc = []

    segs = parts[:3]
    path: list[tuple[str, str, str]] = []
    for seg in segs:
        acc.append(seg)
        full = "::".join(acc)
        path.append((full, clean_label(seg), full))
    return path


def detect_lenses(notes_tags: Iterable[list[str]], decks_map: dict[int, str] | None = None) -> list[dict]:
    """Backwards-compatible lens detector returning Step 1/Step 2/Decks flags."""
    has_s1 = False
    has_s2 = False
    has_yield = False
    for tags in notes_tags:
        for t in tags:
            if not has_yield:
                low = t.lower()
                if "1-highyield" in low or "2-relativelyhighyield" in low:
                    has_yield = True
            if t.startswith("#AK_Step1_v12::#FirstAid::"):
                has_s1 = True
            elif t.startswith("#AK_Step2_v12::#Subjects::"):
                has_s2 = True
        if has_s1 and has_s2 and has_yield:
            break
    lenses = []
    if has_s1 or has_s2:
        lenses.append({"id": "step_subjects", "label": "Step Subjects", "kind": "tag", "has_yield": has_yield})
    lenses.append({"id": "decks", "label": "Decks", "kind": "deck", "has_yield": has_yield})
    return lenses


def detect_generic_tag_config(
    note_tags: dict[int, list[str]],
    unique_deck_count: int,
) -> tuple[bool, str]:
    """Detect whether a non-AnKing deck should map generic hierarchical or flat tags.

    Returns ``(use_generic_tags, strip_root_prefix)``.
    """
    n_notes = len(note_tags)
    if n_notes == 0:
        return (False, "")

    hier_notes = 0
    root_note_counts: collections.Counter[str] = collections.Counter()
    root_children: dict[str, set[str]] = collections.defaultdict(set)
    l1_stripped: set[str] = set()
    flat_notes = 0
    flat_distinct: set[str] = set()

    for tags in note_tags.values():
        has_h = False
        has_f = False
        note_roots: set[str] = set()
        for t in tags:
            if is_utility_tag(t):
                continue
            if "::" in t:
                parts = [p for p in t.split("::") if p]
                if len(parts) >= 2:
                    has_h = True
                    note_roots.add(parts[0])
                    root_children[parts[0]].add(parts[1])
            else:
                has_f = True
                flat_distinct.add(t)
        if has_h:
            hier_notes += 1
            for r in note_roots:
                root_note_counts[r] += 1
        if has_f:
            flat_notes += 1

    # 1. Prefer hierarchical tags when >= 25% of notes carry structured `::` tags
    if hier_notes >= max(1, int(n_notes * 0.25)):
        strip_root = ""
        if len(root_note_counts) == 1:
            only_root = next(iter(root_note_counts))
            if len(root_children[only_root]) >= 2:
                strip_root = only_root
        elif root_note_counts:
            ranked_roots = root_note_counts.most_common(2)
            top_root, top_notes = ranked_roots[0]
            second_notes = ranked_roots[1][1] if len(ranked_roots) > 1 else 0
            if (
                top_notes / max(1, hier_notes) >= 0.80
                and top_notes > second_notes * 1.4
                and len(root_children[top_root]) >= 2
            ):
                strip_root = top_root

        for tags in note_tags.values():
            for t in tags:
                if "::" not in t or is_utility_tag(t):
                    continue
                parts = [p for p in t.split("::") if p]
                if not parts:
                    continue
                if strip_root:
                    if parts[0] == strip_root and len(parts) >= 2:
                        l1_stripped.add(parts[1])
                else:
                    l1_stripped.add(parts[0])
        if len(l1_stripped) >= 2:
            return (True, strip_root)

    # 2. For single flat decks without subdecks, fall back to distinct flat tags
    if unique_deck_count <= 1 and flat_notes >= max(1, int(n_notes * 0.25)) and len(flat_distinct) >= 2:
        return (True, "")

    return (False, "")


def extract_generic_tag_paths(
    tags: list[str],
    strip_root: str = "",
) -> list[list[tuple[str, str, str]]]:
    """Extract 1..3-level paths from generic user tags while preserving raw prefixes for search."""
    valid = [t for t in tags if not is_utility_tag(t)]
    if not valid:
        return []

    has_hier = any("::" in t for t in valid)
    candidates = [t for t in valid if "::" in t] if has_hier else valid
    if strip_root and has_hier:
        primary = [t for t in candidates if t.split("::", 1)[0] == strip_root]
        if primary:
            candidates = primary

    paths: list[list[tuple[str, str, str]]] = []
    seen_leaves: set[tuple[str, ...]] = set()

    for t in candidates:
        parts = [p for p in t.split("::") if p]
        if not parts:
            continue
        raw_acc_start: list[str] = []
        if strip_root and parts[0] == strip_root and len(parts) >= 2:
            raw_acc_start = [strip_root]
            segs = parts[1:4]
        else:
            segs = parts[:3]

        leaf_key = tuple(segs)
        if leaf_key in seen_leaves:
            continue
        seen_leaves.add(leaf_key)

        path: list[tuple[str, str, str]] = []
        key_acc: list[str] = []
        raw_acc = list(raw_acc_start)
        for seg in segs:
            key_acc.append(seg)
            raw_acc.append(seg)
            path.append((
                "::".join(key_acc),
                clean_label(seg),
                "::".join(raw_acc),
            ))
        paths.append(path)

    return paths


def locate_primary_node_id(
    tags: list[str],
    deck_name: str,
    exam_scope: str = "all",
    use_step_subjects: bool = True,
    base_deck: str = "",
    taxonomy_mode: str | None = None,
    tag_strip_root: str = "",
) -> str | None:
    """Return the finest Atlas node ID matching a note/card for 'Show on Atlas'."""
    mode = taxonomy_mode or ("step_subjects" if use_step_subjects else "decks")
    if mode == "step_subjects":
        paths = extract_step_paths(tags, exam_scope=exam_scope)
        if not paths and exam_scope != "all":
            paths = extract_step_paths(tags, exam_scope="all")
        if paths:
            best = max(paths, key=len)
            return f"L{len(best)}:{best[-1][0]}"
    elif mode == "generic_tags":
        paths = extract_generic_tag_paths(tags, strip_root=tag_strip_root)
        if paths:
            best = max(paths, key=len)
            return f"L{len(best)}:{best[-1][0]}"
    dpath = extract_deck_path(deck_name, base_prefix=base_deck)
    if dpath:
        return f"L{len(dpath)}:{dpath[-1][0]}"
    return None
