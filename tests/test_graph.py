"""Pure-Python unit tests for Anki Atlas taxonomy, graph metrics, bridges, and TF-IDF."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from anki_atlas.graph import build_browser_query, build_graph, extract_clean_tokens
from anki_atlas.taxonomy import clean_label, detect_lenses, is_high_yield_note, is_leech_note


class TestTaxonomy(unittest.TestCase):
    def test_clean_label_preserves_acronyms_and_strips_prefixes(self):
        self.assertEqual(clean_label("07_Cardiovascular"), "Cardiovascular")
        self.assertEqual(clean_label("10_Hematology_and_Oncology"), "Hematology & Oncology")
        self.assertEqual(clean_label("*Glucocorticoids"), "Glucocorticoids")
        self.assertEqual(clean_label("^Systems"), "Systems")
        self.assertEqual(clean_label("#B&B"), "Boards & Beyond")
        self.assertEqual(clean_label("01_gi_bleed_and_gerd"), "GI bleed & GERD")
        self.assertEqual(clean_label("03_Therapeutic_antibodies"), "Therapeutic antibodies")

    def test_yield_and_leech_flags(self):
        self.assertTrue(is_high_yield_note(["#AK_Step1_v12::#Low/HighYield::1-HighYield"]))
        self.assertTrue(is_high_yield_note(["#AK_Step1_v12::#Low/HighYield::2-RelativelyHighYield"]))
        self.assertFalse(is_high_yield_note(["#AK_Step1_v12::#Low/HighYield::5-LowYield"]))
        self.assertTrue(is_leech_note(["leech", "#AK_Step1_v12::#FirstAid::01_Biochem"]))
        self.assertFalse(is_leech_note(["#AK_Step1_v12::#FirstAid::01_Biochem"]))

    def test_detect_lenses_anking_and_generic(self):
        lenses_generic = detect_lenses([["biology", "genetics"]], {1: "Bio::Cells"})
        self.assertEqual([l["id"] for l in lenses_generic], ["decks"])

        lenses_ak = detect_lenses(
            [
                ["#AK_Step1_v12::#FirstAid::07_Cardiovascular::04_Pathology::01_HF", "#AK_Step1_v12::#B&B::06_Cardio::01_Phys::01_CO"],
                ["#AK_Step2_v12::#Subjects::Cardiology::01_HF::01_Management"],
            ],
            {1: "AnKing"},
        )
        self.assertEqual(
            [l["id"] for l in lenses_ak],
            ["step_subjects", "decks"],
        )


class TestGraphEngine(unittest.TestCase):
    def _sample_collection(self):
        # 6 notes spanning 3 FirstAid systems + shared bridge + TF-IDF overlap + HY gaps
        notes = [
            (
                1,
                "#AK_Step1_v12::#FirstAid::01_Biochem::05_Nutrition::15_Vitamin_D "
                "#AK_Step1_v12::#FirstAid::01_Biochem::05_Nutrition::16_Calcium_Homeostasis "
                "#AK_Step1_v12::#FirstAid::08_Endocrine::03_Physiology::06_Parathyroid_hormone "
                "#AK_Step1_v12::#Low/HighYield::1-HighYield",
                "{{c1::Calcitriol}} increases intestinal calcium and phosphate absorption via {{c2::PTH}} activation.\x1fExtra: Vitamin D deficiency causes rickets in children.",
            ),
            (
                2,
                "#AK_Step1_v12::#FirstAid::01_Biochem::05_Nutrition::15_Vitamin_D "
                "#AK_Step1_v12::#FirstAid::08_Endocrine::03_Physiology::06_Parathyroid_hormone "
                "#AK_Step1_v12::#Low/HighYield::1-HighYield",
                "1-alpha-hydroxylase in proximal convoluted tubule converts {{c1::25-OH vitamin D}} to active calcitriol.\x1fStimulated by parathyroid hormone PTH.",
            ),
            (
                3,
                "#AK_Step1_v12::#FirstAid::08_Endocrine::03_Physiology::06_Parathyroid_hormone",
                "Chief cells of the parathyroid gland secrete PTH in response to hypocalcemia.\x1fOsteoclast bone resorption.",
            ),
            (
                4,
                "#AK_Step1_v12::#FirstAid::11_MSK::02_Pathology::12_Osteomalacia_Rickets "
                "#AK_Step1_v12::#Low/HighYield::1-HighYield",
                '<img class="resizer" style="width: 120px" src="rickets.jpg">Defective mineralization of osteoid with {{c1::calcitriol}} deficiency, hypocalcemia, bowed legs.\x1fProximal convoluted tubule calcitriol loss causes osteomalacia.',
            ),
            (
                5,
                "#AK_Step1_v12::#FirstAid::11_MSK::02_Pathology::12_Osteomalacia_Rickets "
                "#AK_Step1_v12::#Low/HighYield::2-RelativelyHighYield",
                "Rickets shows rachitic rosary, craniotabes, and elevated alkaline phosphatase with hypocalcemia.\x1fParathyroid hormone PTH secondary elevation.",
            ),
            (
                6,
                "#AK_Step1_v12::#FirstAid::07_Cardiovascular::04_Pathology::01_Heart_Failure leech",
                "Heart failure triggers RAAS aldosterone vasoconstriction and remodeling.\x1fLoop diuretics reduce preload.",
            ),
        ]
        # Cards: (cid, nid, did, queue, ivl, lapses, factor)
        # Note 1 & 2 & 3 mature (Biochem & Endocrine mastered), Note 4 & 5 suspended HY (MSK frontier gap), Note 6 lapsed
        cards = [
            (101, 1, 1, 2, 45, 0, 2500),
            (102, 2, 1, 2, 30, 0, 2500),
            (103, 3, 1, 2, 60, 0, 2500),
            (104, 3, 1, 2, 28, 0, 2500),
            (105, 3, 1, 2, 35, 0, 2500),
            (106, 4, 1, -1, 0, 0, 0),
            (107, 4, 1, -1, 0, 0, 0),
            (108, 5, 1, -1, 0, 0, 0),
            (109, 6, 1, 2, 10, 5, 1800),
            (110, 6, 1, 2, 12, 4, 1900),
            (111, 6, 1, 2, 14, 4, 1900),
            (112, 6, 1, 2, 15, 4, 1900),
            (113, 6, 1, 2, 16, 4, 1900),
        ]
        decks = {1: "AnKing Step Deck"}
        return notes, cards, decks

    def test_no_double_counting_when_note_has_multiple_child_tags(self):
        notes, cards, decks = self._sample_collection()
        g = build_graph(notes, cards, decks, deck_filter="auto", exam_scope="all")
        nodes = {n["id"]: n for n in g["nodes"]}
        # Note 1 has two child tags under Biochemistry, so Biochem must still count Note 1 ONCE (total=2 cards: cid 101 + 102)
        bio = nodes["L1:Biochemistry"]
        self.assertEqual(bio["total"], 2)
        self.assertEqual(bio["mature"], 2)
        self.assertEqual(bio["learned_pct"], 1.0)

        # Endocrine has notes 1, 2, 3 -> 1+1+3 = 5 mature cards
        endo = nodes["L1:Endocrine"]
        self.assertEqual(endo["total"], 5)
        self.assertEqual(endo["mature"], 5)

        # MSK has notes 4, 5 -> 3 suspended HY cards
        msk = nodes["L1:MSK"]
        self.assertEqual(msk["total"], 3)
        self.assertEqual(msk["suspended"], 3)
        self.assertEqual(msk["hy_suspended"], 3)
        self.assertEqual(msk["learned_pct"], 0.0)

    def test_shared_bridges_and_tfidf_and_frontier(self):
        notes, cards, decks = self._sample_collection()
        g = build_graph(notes, cards, decks, deck_filter="auto", exam_scope="all")
        nodes = {n["id"]: n for n in g["nodes"]}

        # Layer 2 shared-card bridge between Biochemistry and Endocrine (notes 1 and 2)
        l1_shared = [e for e in g["edges"] if e["level"] == 1 and e["kind"] == "shared"]
        pairs = {tuple(sorted((e["source"], e["target"]))): e for e in l1_shared}
        self.assertIn(("L1:Biochemistry", "L1:Endocrine"), pairs)
        self.assertEqual(pairs[("L1:Biochemistry", "L1:Endocrine")]["shared"], 2)

        # Layer 3 TF-IDF cleans HTML/cloze and connects MSK Osteomalacia/Rickets to Vitamin D / PTH
        tokens = extract_clean_tokens(notes[3][2])
        self.assertNotIn("resizer", tokens)
        self.assertNotIn("width", tokens)
        self.assertIn("calcitriol", tokens)
        self.assertIn("osteomalacia", tokens)

        concept_edges = [e for e in g["edges"] if e["kind"] == "concept"]
        self.assertTrue(len(concept_edges) >= 1)

        # Connected Gaps (Frontier): MSK is suspended (3 HY cards) & linked via concept terms to mastered Endocrine/Biochem
        msk = nodes["L1:MSK"]
        self.assertTrue(msk["is_frontier"])
        self.assertTrue(len(msk["mastered_neighbors"]) >= 1)

        # Weak spot score on Cardiology (21 lapses + 5 leeches across 5 active cards)
        cv = nodes["L1:Cardiology"]
        self.assertGreater(cv["weak_score"], 4.0)
        self.assertEqual(cv["leech_count"], 5)
        self.assertEqual(cv["state"], "young")

        # Card-state classification + tree edges + 3D z coordinate + unified lobe radii
        self.assertEqual(nodes["L1:Endocrine"]["state"], "mature")
        self.assertEqual(msk["state"], "suspended")
        self.assertIn("z", msk)
        tree_edges = [e for e in g["edges"] if e["kind"] == "tree"]
        self.assertTrue(len(tree_edges) >= 4)
        self.assertGreater(nodes["L1:Endocrine"]["lobe_r"], 0.0)

    def test_unified_step1_and_step2_and_deck_filter(self):
        notes, cards, _decks = self._sample_collection()
        # Add a Step 2 Cardiology note and an unrelated Chinese deck note
        notes.append((
            7,
            "#AK_Step2_v12::#Subjects::Cardiology::Heart_Failure::GDMT",
            "Guideline directed medical therapy ARNI beta blocker MRA SGLT2i.",
        ))
        notes.append((8, "hsk1", "Ni hao hello."))
        cards.append((114, 7, 1, 0, 0, 0, 0))
        cards.append((115, 8, 2, 2, 30, 0, 2500))
        decks = {1: "AnKing Step Deck", 2: "Chinese"}

        # Default deck_filter="auto" picks AnKing Step Deck and unifies Step 1 + Step 2 Cardiology
        g_all = build_graph(notes, cards, decks, deck_filter="auto", exam_scope="all")
        self.assertEqual(g_all["deck_filter"], "AnKing Step Deck")
        nodes_all = {n["id"]: n for n in g_all["nodes"]}
        self.assertEqual(nodes_all["L1:Cardiology"]["total"], 6)  # 5 Step 1 + 1 Step 2
        self.assertIn("OR", nodes_all["L1:Cardiology"]["queries"]["all"])

        # Step 2 only sees note 7
        g_s2 = build_graph(notes, cards, decks, deck_filter="AnKing Step Deck", exam_scope="step2")
        nodes_s2 = {n["id"]: n for n in g_s2["nodes"]}
        self.assertEqual(nodes_s2["L1:Cardiology"]["total"], 1)
        self.assertNotIn("L1:Endocrine", nodes_s2)

        # Chinese deck falls back cleanly to deck hierarchy
        g_zh = build_graph(notes, cards, decks, deck_filter="Chinese", exam_scope="all")
        self.assertEqual(g_zh["lens"], "decks")
        self.assertEqual(g_zh["summary"]["total_cards"], 1)

    def test_browser_queries_escaped(self):
        q = build_browser_query("#AK_Step1_v12::#FirstAid::08_Endocrine::05_Pharm::*Glucocorticoids", "tag", "hy_suspended")
        self.assertIn(r"\*Glucocorticoids", q)
        self.assertIn("is:suspended", q)
        self.assertIn("1-HighYield", q)

        qd = build_browser_query("AnKing Step Deck::Derm", "deck", "suspended")
        self.assertEqual(qd, '"deck:AnKing Step Deck::Derm" is:suspended')

    def test_deterministic_layout_and_deck_fallback(self):
        notes = [
            (1, "neuro anatomy", "Acetylcholine at neuromuscular junction.\x1fNicotinic receptor."),
            (2, "neuro anatomy", "Myasthenia gravis autoantibodies against nicotinic receptor.\x1fAcetylcholine."),
            (3, "pharm", "Pyridostigmine acetylcholinesterase inhibitor for myasthenia gravis.\x1fNicotinic acetylcholine."),
        ]
        cards = [
            (10, 1, 100, 2, 30, 0, 2500),
            (11, 2, 100, -1, 0, 0, 0),
            (12, 3, 200, 2, 25, 0, 2500),
        ]
        decks = {100: "Med::Neuro", 200: "Med::Pharm"}
        g1 = build_graph(notes, cards, decks, lens_id="auto")
        g2 = build_graph(notes, cards, decks, lens_id="auto")
        self.assertEqual(g1["lens"], "decks")
        coords1 = [(n["id"], n["x"], n["y"], n["z"]) for n in g1["nodes"]]
        coords2 = [(n["id"], n["x"], n["y"], n["z"]) for n in g2["nodes"]]
        self.assertEqual(coords1, coords2)

    def test_overlays_revlog_weak_next_gaps_and_locate(self):
        from anki_atlas.taxonomy import locate_primary_node_id

        now_ms = 1_750_000_000_000
        day_ms = 86_400_000
        notes = [
            (
                1,
                "#AK_Step1_v12::#FirstAid::14_Renal::02_Pathology::01_Glomerular "
                "#AK_Step1_v12::^HighYield::1-HighYield #AK_Step1_v12::#Pathoma::Renal",
                "Nephritic syndrome\x1fHematuria",
            ),
            (
                2,
                "#AK_Step1_v12::#FirstAid::14_Renal::01_Physiology::02_Tubular "
                "#AK_Step1_v12::#Pathoma::Renal #AK_Step1_v12::#UWorld::Step1::123",
                "Fanconi syndrome\x1fProximal tubule",
            ),
            (
                3,
                "#AK_Step1_v12::#FirstAid::03_Cardiology::02_Pathology::01_Arrhythmias "
                "#AK_Step2_v12::#Internal_Medicine::Cardiology::Arrhythmias",
                "Atrial fibrillation\x1fIrregularly irregular",
            ),
        ]
        # (cid, nid, did, queue, ivl, lapses, factor)
        cards = [
            (101, 1, 10, 2, 12, 3, 1800),   # weak (lapses >= 2, factor <= 2000), mature? wait ivl=12 -> young+weak
            (102, 2, 11, -1, 0, 0, 0),     # suspended in Pathoma + UWorld + subdeck Wrong
            (103, 3, 10, 2, 30, 0, 2500),  # mature in AFib
        ]
        decks = {
            10: "AnKing Step Deck",
            11: "AnKing Step Deck::past::UWorld Wrong",
        }
        # cid -> latest review timestamp (epoch ms)
        revlog_recent = {
            101: now_ms - 2 * day_ms,   # within 7d & 30d
            103: now_ms - 14 * day_ms,  # within 30d only
        }
        g = build_graph(
            notes,
            cards,
            decks,
            deck_filter="AnKing Step Deck",
            exam_scope="all",
            revlog_recent=revlog_recent,
            now_ms=now_ms,
        )

        # Revlog & weak aggregation
        s = g["summary"]
        self.assertTrue(s["has_revlog"])
        self.assertEqual(s["rev_7d"], 1)
        self.assertEqual(s["rev_30d"], 2)
        self.assertGreaterEqual(s["weak_cards"], 1)

        # Overlays: subdeck ("UWorld Wrong") and resource tags ("Pathoma", "UWorld")
        ov_by_id = {ov["id"]: ov for ov in g["overlays"]}
        self.assertIn("subdeck:AnKing Step Deck::past::UWorld Wrong", ov_by_id)
        self.assertIn("res:#AK_Step1_v12::#Pathoma", ov_by_id)
        self.assertIn("res:#AK_Step1_v12::#UWorld", ov_by_id)
        uw_ov = ov_by_id["subdeck:AnKing Step Deck::past::UWorld Wrong"]
        self.assertTrue(uw_ov["pairs"])
        self.assertIn("deck:", uw_ov["query_term"])
        pathoma_ov = ov_by_id["res:#AK_Step1_v12::#Pathoma"]
        self.assertEqual(pathoma_ov["total_cards"], 2)
        self.assertIn("tag:", pathoma_ov["query_term"])

        # Next gaps queue contains the suspended subtopic (Tubular)
        self.assertTrue(g["next_gaps"])
        nodes_by_id = {n["id"]: n for n in g["nodes"]}
        top_gap = nodes_by_id[g["next_gaps"][0]]
        self.assertGreater(top_gap["suspended"], 0)
        self.assertIn("Tubular", top_gap["label"])

        # Locate primary node across Step 1, Step 2, all, and deck fallback
        n_s1 = locate_primary_node_id(notes[0][1].split(), "AnKing Step Deck", exam_scope="step1")
        n_s2 = locate_primary_node_id(notes[2][1].split(), "AnKing Step Deck", exam_scope="step2")
        n_all = locate_primary_node_id(notes[2][1].split(), "AnKing Step Deck", exam_scope="all")
        n_dk = locate_primary_node_id(["misc"], "Med::Neuro::Cranial", exam_scope="all", use_step_subjects=False)
        self.assertIn(n_s1, nodes_by_id)
        self.assertIsNotNone(n_s2)
        self.assertIn(n_all, nodes_by_id)
        self.assertTrue(n_dk is not None and n_dk.startswith("L"))

    def test_non_anking_hierarchical_tags_and_overlays(self):
        from anki_atlas.taxonomy import locate_primary_node_id

        notes = [
            (1, "MCAT::Bio::Biochem::Enzymes missed high_yield", "Michaelis Menten Vmax Km enzyme catalysis.\x1fSubstrate saturation."),
            (2, "MCAT::Bio::Biochem::Enzymes MCAT::Chem::General::Kinetics missed", "Enzyme kinetics lowering activation energy rate constant.\x1fArrhenius."),
            (3, "MCAT::Chem::General::Kinetics", "First order rate law half life reaction rate.\x1fk = 0.693/t1/2."),
        ]
        cards = [
            (10, 1, 50, -1, 0, 0, 0),  # suspended high_yield
            (11, 2, 50, 2, 25, 0, 2500),
            (12, 3, 50, 2, 10, 0, 2500),
        ]
        decks = {50: "MCAT Prep"}

        g = build_graph(notes, cards, decks, deck_filter="auto", exam_scope="all")
        self.assertEqual(g["lens"], "generic_tags")
        s = g["summary"]
        self.assertEqual(s["taxonomy_mode"], "generic_tags")
        self.assertEqual(s["tag_strip_root"], "MCAT")
        self.assertFalse(s["use_step_subjects"])
        self.assertEqual(s["hy_total"], 1)
        self.assertEqual(s["hy_suspended"], 1)

        l1_labels = {n["label"] for n in g["nodes"] if n["level"] == 1}
        self.assertEqual(l1_labels, {"Bio", "Chem"})
        # Shared card bridge between Bio and Chem because note 2 carries both tags
        self.assertGreaterEqual(s["shared_edges"], 1)
        # Auto-detected cross-cutting flat tag overlay (#Missed)
        ov_ids = {ov["id"]: ov for ov in g["overlays"]}
        self.assertIn("tag:missed", ov_ids)
        self.assertEqual(ov_ids["tag:missed"]["total_cards"], 2)

        # Locate card works under generic_tags
        nodes_by_id = {n["id"]: n for n in g["nodes"]}
        loc = locate_primary_node_id(
            notes[0][1].split(),
            "MCAT Prep",
            taxonomy_mode="generic_tags",
            tag_strip_root="MCAT",
        )
        self.assertIn(loc, nodes_by_id)
        self.assertIn("Enzymes", nodes_by_id[loc]["label"])

    def test_non_anking_flat_tags_single_deck(self):
        notes = [
            (1, "verbs", "Hablar comer vivir conjugation.\x1fTo speak."),
            (2, "nouns", "La mesa el libro vocab.\x1fTable."),
        ]
        cards = [
            (10, 1, 70, 2, 30, 0, 2500),
            (11, 2, 70, -1, 0, 0, 0),
        ]
        g = build_graph(notes, cards, {70: "Spanish"}, deck_filter="auto", exam_scope="all")
        self.assertEqual(g["lens"], "generic_tags")
        self.assertEqual(g["summary"]["taxonomy_mode"], "generic_tags")
        self.assertEqual(g["summary"]["tag_strip_root"], "")
        l1_labels = {n["label"] for n in g["nodes"] if n["level"] == 1}
        self.assertEqual(l1_labels, {"Verbs", "Nouns"})

    def test_non_anking_purely_nested_tags_and_secondary_tag_overlays(self):
        notes = [
            (1, "CS::Algorithms::Graphs::Dijkstra Exam::Midterm", "Shortest path priority queue relaxation.\x1fNon-negative edges."),
            (2, "CS::Algorithms::Trees::AVL Exam::Midterm", "Self balancing binary search tree rotation.\x1fHeight difference at most 1."),
            (3, "CS::Systems::Memory::Paging Quiz::Ch4", "Virtual memory page table TLB hit.\x1fTranslation lookaside buffer."),
            (4, "CS::Systems::Scheduling::CFS Quiz::Ch5", "Completely fair scheduler red black tree.\x1fVirtual runtime."),
        ]
        cards = [
            (10, 1, 80, 2, 21, 0, 2500),
            (11, 2, 80, -1, 0, 0, 0),
            (12, 3, 80, -1, 0, 0, 0),
            (13, 4, 80, 1, 5, 0, 2100),
        ]
        g = build_graph(notes, cards, {80: "Computer Science"}, deck_filter="auto", exam_scope="all")
        self.assertEqual(g["summary"]["taxonomy_mode"], "generic_tags")
        self.assertEqual(g["summary"]["tag_strip_root"], "CS")
        l1_labels = {n["label"] for n in g["nodes"] if n["level"] == 1}
        self.assertEqual(l1_labels, {"Algorithms", "Systems"})
        ov_ids = {ov["id"]: ov for ov in g["overlays"]}
        self.assertIn("tag:Exam", ov_ids)
        self.assertIn("tag:Quiz", ov_ids)
        self.assertNotIn("tag:CS", ov_ids)
        self.assertGreater(ov_ids["tag:Exam"]["total_cards"], 0)


if __name__ == "__main__":
    unittest.main()
