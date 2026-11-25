"""Offscreen Qt + Chromium smoke & interactive UI test for Anki Atlas.

Run with Anki's Python:
  QT_QPA_PLATFORM=offscreen ~/Library/Application\\ Support/AnkiProgramFiles/.venv/bin/python tests/test_qt_window.py
"""

import json
import os
import sys
import unittest

if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

try:
    import PyQt6.QtWebEngineWidgets  # must load before QApplication
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWebEngineCore import QWebEnginePage
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication(sys.argv)
    HAS_PYQT = True
except ImportError:
    _APP = None
    QWebEnginePage = object  # type: ignore[assignment,misc]
    HAS_PYQT = False

try:
    from anki.collection import Collection
    HAS_ANKI = True
except ImportError:
    Collection = None  # type: ignore[assignment,misc]
    HAS_ANKI = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from anki_atlas.graph import build_graph
from anki_atlas.window import (
    build_page_parts,
    create_or_rebuild_cram_deck,
    inspect_node_in_col,
    search_collection_for_atlas,
)


class AuditWebPage(QWebEnginePage):
    """Capture JavaScript console warnings/errors so functional tests catch runtime issues."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.console_issues: list[tuple[str, int, str]] = []

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceId):  # type: ignore[override]
        lvl_name = getattr(level, "name", str(level))
        if "Error" in lvl_name or "Warning" in lvl_name:
            self.console_issues.append((lvl_name, int(lineNumber), str(message)))


class TestQtWindow(unittest.TestCase):
    def test_page_bundle_inlined(self):
        head_html, body_html = build_page_parts()
        self.assertIn("<style>", head_html)
        self.assertIn("--bg:", head_html)
        self.assertIn("<script>", body_html)
        self.assertIn("atlasReceiveGraph", body_html)
        self.assertIn("atlas-canvas", body_html)
        self.assertNotIn("<link rel=", head_html)
        self.assertNotIn("<script src=", body_html)

    @unittest.skipUnless(HAS_PYQT, "Requires Anki's PyQt6/WebEngine Python")
    def test_chromium_canvas_and_inspector(self):
        app = _APP
        head_html, body_html = build_page_parts()

        notes = [
            (
                1,
                "#AK_Step1_v12::#FirstAid::01_Biochem::05_Nutrition::15_Vitamin_D "
                "#AK_Step1_v12::#FirstAid::08_Endocrine::03_Physiology::06_Parathyroid_hormone "
                "#AK_Step2_v12::#Internal_Medicine::Endocrinology::Vitamin_D "
                "#AK_Step1_v12::^HighYield::1-HighYield #AK_Step1_v12::#Pathoma::Renal",
                "Calcitriol vitamin D increases intestinal calcium and phosphate absorption via PTH.\x1fVitamin D rickets.",
            ),
            (
                2,
                "#AK_Step1_v12::#FirstAid::08_Endocrine::03_Physiology::06_Parathyroid_hormone "
                "#AK_Step1_v12::#Pathoma::Endocrine",
                "Parathyroid hormone PTH increases 1-alpha-hydroxylase calcitriol vitamin D.\x1fOsteoclast bone resorption.",
            ),
            (
                3,
                "#AK_Step1_v12::#FirstAid::11_MSK::02_Pathology::12_Osteomalacia_Rickets "
                "#AK_Step1_v12::#FirstAid::08_Endocrine::03_Physiology::06_Parathyroid_hormone "
                "#AK_Step1_v12::^HighYield::1-HighYield #AK_Step1_v12::#UWorld::Step1::999",
                "Rickets osteomalacia defective mineralization hypocalcemia calcitriol PTH.\x1fBowed legs.",
            ),
        ]
        cards = [
            (10, 1, 1, 2, 30, 0, 2500),
            (11, 2, 2, 2, 14, 3, 1800),  # weak card in UWorld Wrong + recent 7d
            (12, 3, 1, -1, 0, 0, 0),
            (13, 3, 2, -1, 0, 0, 0),
            (14, 3, 1, -1, 0, 0, 0),
        ]
        decks = {1: "AnKing Step Deck", 2: "AnKing Step Deck::past::UWorld Wrong"}
        payload = build_graph(
            notes,
            cards,
            decks,
            deck_filter="AnKing Step Deck",
            exam_scope="all",
            revlog_recent={10: 1_750_000_000_000 - 2 * 86_400_000, 11: 1_750_000_000_000 - 10 * 86_400_000},
            now_ms=1_750_000_000_000,
        )

        html = (
            '<!doctype html><html class="night-mode"><head>'
            f"{head_html}"
            '<script>window.__pycmds=[]; window.pycmd=function(c){window.__pycmds.push(c);};</script>'
            f"</head><body class=\"nightMode\">{body_html}</body></html>"
        )

        view = QWebEngineView()
        page = AuditWebPage(view)
        view.setPage(page)
        view.resize(1340, 860)
        view.show()

        loop = QEventLoop()
        page.loadFinished.connect(lambda _ok: loop.quit())
        page.setHtml(html)
        loop.exec()
        page.loadFinished.disconnect()

        def eval_js(code: str):
            out = []
            ev = QEventLoop()
            page.runJavaScript(code, lambda v: (out.append(v), ev.quit()))
            ev.exec()
            return out[0] if out else None

        ready_cmds = eval_js("window.__pycmds")
        self.assertIn("atlas:ready", ready_cmds)

        # Resolve deterministic node IDs to test pathway, overlay, weak, HY, and L1 isolation
        by_lbl = {n["label"]: n["id"] for n in payload["nodes"]}
        vitd_id = next(nid for lbl, nid in by_lbl.items() if "Vitamin D" in lbl)
        pth_id = next(nid for lbl, nid in by_lbl.items() if "Parathyroid" in lbl)
        osteo_id = next(nid for lbl, nid in by_lbl.items() if "Osteomalacia" in lbl)
        l1_id = next(n["id"] for n in payload["nodes"] if n["level"] == 1)

        check_js = f"""(() => {{
            window.__atlasNoIdleDrift = true;
            window.atlasInitPrefs({{night_mode: true, view_mode: "grid", colorblind_mode: false, show_concept_links: true, high_yield_only: false}});
            window.atlasReceiveGraph({json.dumps(payload)});
            const hudGrid = document.getElementById("hud-stats").textContent;
            const l1Bg = getComputedStyle(document.body).backgroundColor;
            const dockCount = document.querySelectorAll("#dock-list [data-jump]").length;
            const gridCards = document.querySelectorAll("#grid-view .grid-subj-card").length;
            const viewModeGridActive = Boolean(document.querySelector('[data-view="grid"].active'));

            // Grid drilldown -> crumb back -> switch 2D -> 3D
            const firstGridDrill = document.querySelector("#grid-view [data-grid-drill]");
            if (firstGridDrill) firstGridDrill.click();
            const gridDrilledTiles = document.querySelectorAll("#grid-view .grid-tile").length;
            const backAllCrumb = document.querySelector('#grid-view [data-grid-drill=""]');
            if (backAllCrumb) backAllCrumb.click();

            document.querySelector('[data-view="2d"]').click();
            const viewModeAfter2d = Boolean(document.querySelector('[data-view="2d"].active'));
            const gridHiddenIn2d = document.getElementById("grid-view").classList.contains("hidden");
            document.querySelector('[data-view="3d"]').click();
            const viewModeText = document.querySelector('#view-pills .seg-btn.active').textContent;
            const hud = document.getElementById("hud-stats").textContent;

            // Colorblind toggle switches --c-mature AND bottom legend .lg-dot computed color
            const matureDefault = getComputedStyle(document.body).getPropertyValue("--c-mature").trim();
            const legendDot = document.querySelector('.state-chip[data-state="mature"] .lg-dot');
            const legendMatureDefault = legendDot ? getComputedStyle(legendDot).backgroundColor : "";
            document.getElementById("btn-colorblind").click();
            const cbActive = document.documentElement.classList.contains("atlas-cb") && document.body.classList.contains("atlas-cb");
            const matureCb = getComputedStyle(document.body).getPropertyValue("--c-mature").trim();
            const legendMatureCb = legendDot ? getComputedStyle(legendDot).backgroundColor : "";
            document.getElementById("btn-colorblind").click();

            // Spotlight dropdown modes: gaps, weak, recent_7d, recent_30d, all (no hy_gaps)
            const sp = document.getElementById("spotlight-select");
            const hasHyOption = Boolean(sp.querySelector('[value="hy_gaps"]'));
            sp.value = "gaps";
            sp.dispatchEvent(new Event("change"));
            const hudGaps = document.getElementById("hud-stats").textContent;
            const activeSelectBg = getComputedStyle(sp).backgroundColor;

            sp.value = "weak";
            sp.dispatchEvent(new Event("change"));
            const hudWeak = document.getElementById("hud-stats").textContent;

            sp.value = "recent_7d";
            sp.dispatchEvent(new Event("change"));
            const hudRecent7 = document.getElementById("hud-stats").textContent;

            sp.value = "recent_30d";
            sp.dispatchEvent(new Event("change"));
            const hudRecent30 = document.getElementById("hud-stats").textContent;

            sp.value = "all";
            sp.dispatchEvent(new Event("change"));

            // Multi-select Highlight Tags popover + Priority Queue tab
            const ovBtn = document.getElementById("btn-overlay-menu");
            const ovPanel = document.getElementById("overlay-panel");
            ovBtn.click();
            const ovChecks = Array.from(ovPanel.querySelectorAll(".ov-checkbox"));
            const hasOverlayOpts = ovChecks.length >= 2;
            let ovTagOpened = false;
            let ovMultiLabel = "";
            if (ovChecks.length >= 2) {{
                ovChecks[0].click();
                ovChecks[1].click();
                ovMultiLabel = ovBtn.textContent.trim();
            }} else if (ovChecks.length === 1) {{
                ovChecks[0].click();
                ovMultiLabel = ovBtn.textContent.trim();
            }}
            const hudOverlay = document.getElementById("hud-stats").textContent;

            document.getElementById("tab-priority").click();
            const queueRows = document.querySelectorAll("#dock-list [data-jump]").length;
            const firstOvJump = document.querySelector("#dock-list [data-jump]");
            if (firstOvJump) firstOvJump.click();
            const ovOpenBtn = document.getElementById("act-ov-open");
            if (ovOpenBtn) {{
                const beforeLen = window.__pycmds.length;
                ovOpenBtn.click();
                const added = window.__pycmds.slice(beforeLen).find((c) => c.startsWith("atlas:browser:"));
                ovTagOpened = Boolean(added && added.includes(" OR ") && (added.includes("deck:") || added.includes("tag:")));
            }}
            const queueBrowserBtn = document.querySelector("#dock-list [data-browser]");
            if (queueBrowserBtn) queueBrowserBtn.click();

            // Clear overlay, switch back to Subjects, test Isolate button & Dock toggle
            const ovClearBtn = document.getElementById("btn-overlay-clear");
            if (ovClearBtn) ovClearBtn.click();
            document.body.click(); // closes overlay popover on outside click
            const ovClosedOutside = ovPanel.classList.contains("hidden");
            document.getElementById("tab-subjects").click();
            const isoBtn = document.querySelector("#dock-list [data-isolate]");
            if (!isoBtn) return {{ err: "subject isolate button missing" }};
            isoBtn.click();
            const isoFocusText = document.getElementById("focus-label").textContent;
            document.getElementById("btn-exit-focus").click();

            document.getElementById("btn-dock-toggle").click();
            const dockClosed = document.getElementById("subject-dock").classList.contains("hidden");
            document.getElementById("btn-dock-open").click();
            const dockReopened = !document.getElementById("subject-dock").classList.contains("hidden");

            // Topbar buttons: concepts, fit, refresh, exam pill, deck select
            document.getElementById("btn-concepts").click();
            document.getElementById("btn-concepts").click();
            document.getElementById("btn-fit").click();
            document.getElementById("btn-refresh").click();
            const s1Btn = document.querySelector('#exam-pills [data-exam="step1"]');
            if (s1Btn) s1Btn.click();
            const dk = document.getElementById("deck-select");
            if (dk && dk.options.length > 0) {{
                dk.dispatchEvent(new Event("change"));
            }}

            // State chip toggle
            const suspChip = document.querySelector('.state-chip[data-state="suspended"]');
            suspChip.click();
            const chipActive = suspChip.classList.contains("active");
            suspChip.click();

            // Live full-deck search popup + deep inspector details injection
            const sInput = document.getElementById("search-input");
            sInput.value = "Vitamin";
            sInput.dispatchEvent(new Event("input"));
            window.atlasReceiveSearchResults({{
                token: 99,
                query: "Vitamin",
                total_notes: 2,
                browser_query: "(Vitamin OR tag:*Vitamin*)",
                topics: [{{ id: {json.dumps(vitd_id)}, hits: 2, suspended: 0 }}],
                subtags: [{{ label: "Calcitriol Receptor", trail: "Biochem › Vitamin D", hits: 1, suspended: 0, node_id: {json.dumps(vitd_id)}, query: "tag:calcitriol" }}],
                cards: [{{ cid: 10, text: "Calcitriol increases calcium absorption", state: "mature", node_id: {json.dumps(vitd_id)}, query: "cid:10" }}]
            }});
            const searchHasDeepTag = document.getElementById("search-results").textContent.includes("Calcitriol Receptor");
            const srHi = document.getElementById("sr-highlight");
            if (srHi) srHi.click();

            // Clear search highlight cleanly
            sInput.value = "Vitamin D";
            sInput.dispatchEvent(new Event("input"));
            const firstHit = document.querySelector("#search-results [data-jump]");
            if (!firstHit) return {{ err: "search hit missing" }};
            firstHit.click();

            window.atlasReceiveNodeDetails({{
                id: {json.dumps(vitd_id)},
                total_notes: 1,
                gap_mode: "suspended",
                gap_sources: [{{ label: "Pathoma", kind: "tag", count: 1, query: "is:suspended tag:Pathoma" }}],
                subtags: [{{ label: "1,25-OH Vitamin D", tag: "tag:vitd_active", total: 1, mature: 1, young: 0, new: 0, suspended: 0, learned_pct: 1.0, query: "tag:vitd_active" }}],
                cards: [{{ cid: 10, text: "Calcitriol increases intestinal calcium", state: "mature", lapses: 0, query: "cid:10" }}]
            }});
            const insBodyText = document.getElementById("ins-body").textContent;
            const insDetailsRendered = insBodyText.includes("1,25-OH Vitamin D") && insBodyText.includes("Where missing cards live");
            const foldsCollapsedByDefault = Array.from(document.querySelectorAll("#ins-body details.ins-fold")).every((d) => !d.open);

            const insTitle = document.getElementById("ins-title").textContent;
            const insOpen = !document.getElementById("inspector").classList.contains("hidden");

            document.getElementById("act-focus").click();
            const focusText = document.getElementById("focus-label").textContent;
            const focusVisible = !document.getElementById("focus-banner").classList.contains("hidden");
            document.getElementById("btn-hop-2").click();
            const hop2Text = document.getElementById("focus-label").textContent;
            const hop2Active = document.getElementById("btn-hop-2").classList.contains("active");
            document.getElementById("btn-hop-1").click();

            // Trace pathway from Vitamin D -> Osteomalacia
            document.getElementById("act-trace").click();
            const pDest = document.getElementById("path-dest-input");
            if (!pDest) return {{ err: "path-dest-input missing" }};
            pDest.value = "Osteomalacia";
            pDest.dispatchEvent(new Event("input"));
            const pHit = document.querySelector('#path-hits [data-path-to]');
            if (!pHit) return {{ err: "pathway dest hit missing" }};
            pHit.click();
            const pathCardOpen = Boolean(document.getElementById("pw-clear"));
            if (!pathCardOpen) return {{ err: "pathway card (pw-clear) missing after trace click" }};
            const pwCramBtn = document.getElementById("pw-cram");
            if (pwCramBtn) pwCramBtn.click();
            const pwBrowserBtn = document.getElementById("pw-browser");
            if (pwBrowserBtn) pwBrowserBtn.click();
            document.getElementById("pw-clear").click();
            document.getElementById("btn-exit-focus").click();

            // Inspector actions on Vitamin D: cram, all
            document.getElementById("act-cram").click();
            document.getElementById("act-all").click();

            // Weak cards button on Parathyroid hormone
            window.atlasLocateNode({json.dumps(pth_id)});
            document.getElementById("act-weak").click();

            // Calm 2-button Inspector on Osteomalacia (Open Gaps + Cram Deck + quick-link High-Yield & All cards)
            window.atlasLocateNode({json.dumps(osteo_id)});
            const locatedTitle = document.getElementById("ins-title").textContent;
            const leafBtnCount = document.querySelector("#ins-body .action-stack").querySelectorAll(".act-btn").length;
            const hyIsQuietLink = Boolean(document.querySelector("#ins-body .ins-quick-links #act-hy"));
            document.getElementById("act-hy").click();
            document.getElementById("act-susp").click();

            // L1 Subject -> calm 2 buttons, Subtopics tab, single Subtopics list (no duplicate Top Specific Topics)
            window.atlasLocateNode({json.dumps(l1_id)});
            const l1InsideActive = Boolean(document.getElementById("ins-tab-inside")?.classList.contains("active"));
            const l1SubtopicsLabel = document.getElementById("ins-tab-inside")?.textContent || "";
            const l1NoDupHeading = !document.getElementById("ins-body").textContent.includes("Top Specific Topics to Study");
            const folderBtnCount = document.querySelectorAll("#ins-body .action-stack .act-btn").length;
            const firstDrill = document.querySelector("#ins-body [data-drill]");
            if (!firstDrill) return {{ err: "drill-down row missing on L1 subject" }};
            firstDrill.click();
            const drilledTitle = document.getElementById("ins-title").textContent;
            const crumbAncestor = document.querySelector("#ins-crumb [data-jump]");
            if (!crumbAncestor) return {{ err: "clickable breadcrumb ancestor missing" }};
            crumbAncestor.click();
            const backToTitle = document.getElementById("ins-title").textContent;

            // Isolate on L1 & Connections tab Local Graph
            document.getElementById("act-isolate").click();
            const l1IsoBanner = document.getElementById("focus-label").textContent;
            document.getElementById("btn-exit-focus").click();
            document.getElementById("ins-tab-conn").click();
            const connHasTrace = Boolean(document.getElementById("act-trace"));

            window.atlasToast("Test toast message");
            const toastText = document.getElementById("atlas-toast").textContent;
            document.getElementById("ins-close").click();

            window.atlasInitPrefs({{night_mode: false, view_mode: "3d", show_concept_links: true, high_yield_only: false}});
            const lightBg = getComputedStyle(document.body).backgroundColor;

            return {{
                hud,
                hudGrid,
                hudGaps,
                hasHyOption,
                activeSelectBg,
                hudWeak,
                hudRecent7,
                hudRecent30,
                hudOverlay,
                hasOverlayOpts,
                ovMultiLabel,
                ovTagOpened,
                ovClosedOutside,
                dockCount,
                gridCards,
                gridDrilledTiles,
                viewModeGridActive,
                viewModeAfter2d,
                gridHiddenIn2d,
                matureDefault,
                legendMatureDefault,
                cbActive,
                matureCb,
                legendMatureCb,
                searchHasDeepTag,
                insDetailsRendered,
                foldsCollapsedByDefault,
                leafBtnCount,
                folderBtnCount,
                hyIsQuietLink,
                l1SubtopicsLabel,
                l1NoDupHeading,
                queueRows,
                isoFocusText,
                l1InsideActive,
                drilledTitle,
                backToTitle,
                l1IsoBanner,
                connHasTrace,
                dockClosed,
                dockReopened,
                viewModeText,
                chipActive,
                l1Bg,
                lightBg,
                insTitle,
                insOpen,
                focusText,
                hop2Text,
                hop2Active,
                focusVisible,
                pathCardOpen,
                locatedTitle,
                toastText,
                pycmds: window.__pycmds,
            }};
        }})()"""

        res = eval_js(check_js)
        self.assertEqual(page.console_issues, [], msg=f"JS console issues: {page.console_issues}")
        self.assertIsNotNone(res)
        self.assertNotIn("err", res, msg=str(res))
        self.assertEqual(res["dockCount"], 3)
        self.assertEqual(res["gridCards"], 3)
        self.assertGreaterEqual(res["gridDrilledTiles"], 1)
        self.assertTrue(res["viewModeGridActive"])
        self.assertTrue(res["viewModeAfter2d"])
        self.assertTrue(res["gridHiddenIn2d"])
        self.assertIn("Yellow = suspended", res["hudGrid"])
        self.assertTrue(res["cbActive"])
        self.assertNotEqual(res["matureDefault"], res["matureCb"])
        self.assertNotEqual(res["legendMatureDefault"], res["legendMatureCb"])
        self.assertFalse(res["hasHyOption"])
        self.assertTrue(res["searchHasDeepTag"])
        self.assertTrue(res["insDetailsRendered"])
        self.assertTrue(res["foldsCollapsedByDefault"])
        self.assertEqual(res["leafBtnCount"], 2)
        self.assertEqual(res["folderBtnCount"], 2)
        self.assertTrue(res["hyIsQuietLink"])
        self.assertIn("Subtopics (", res["l1SubtopicsLabel"])
        self.assertTrue(res["l1NoDupHeading"])
        self.assertTrue(res["hasOverlayOpts"])
        self.assertIn("Tags (2)", res["ovMultiLabel"])
        self.assertTrue(res["ovTagOpened"])
        self.assertTrue(res["ovClosedOutside"])
        self.assertGreaterEqual(res["queueRows"], 1)
        self.assertIn("Isolated:", res["isoFocusText"])
        self.assertTrue(res["l1InsideActive"])
        self.assertNotEqual(res["drilledTitle"], res["backToTitle"])
        self.assertIn("Isolated:", res["l1IsoBanner"])
        self.assertTrue(res["connHasTrace"])
        # Active dark dropdown background must be opaque dark blue, never transparent or blank white
        self.assertFalse(res["activeSelectBg"].startswith("rgba("), msg=res["activeSelectBg"])
        self.assertNotEqual(res["activeSelectBg"], "rgb(255, 255, 255)")
        self.assertTrue(res["dockClosed"])
        self.assertTrue(res["dockReopened"])
        self.assertEqual(res["viewModeText"], "3D")
        self.assertIn("topics", res["hud"])
        self.assertIn("suspended", res["hudGaps"])
        self.assertIn("weak", res["hudWeak"])
        self.assertIn("7 days", res["hudRecent7"])
        self.assertIn("30 days", res["hudRecent30"])
        self.assertIn("tags (", res["hudOverlay"])
        self.assertTrue(res["chipActive"])
        self.assertTrue(res["insOpen"])
        self.assertIn("Vitamin D", res["insTitle"])
        self.assertTrue(res["focusVisible"])
        self.assertIn("Local Graph: Vitamin D", res["focusText"])
        self.assertTrue(res["hop2Active"])
        self.assertIn("links", res["hop2Text"])
        self.assertNotEqual(res["focusText"], res["hop2Text"])
        self.assertTrue(res["pathCardOpen"])
        self.assertIn("Osteomalacia", res["locatedTitle"])
        self.assertEqual(res["toastText"], "Test toast message")
        self.assertNotEqual(res["l1Bg"], res["lightBg"])
        self.assertTrue(any(c.startswith("atlas:browser:") and "is:suspended" in c for c in res["pycmds"]))
        self.assertTrue(any(c.startswith("atlas:cram:") for c in res["pycmds"]))
        self.assertTrue(any(c == "atlas:refresh" for c in res["pycmds"]))
        self.assertTrue(any(c.startswith("atlas:filter:") and '"exam_scope":"step1"' in c for c in res["pycmds"]))
        # Keep view referenced cleanly until interpreter exit to avoid headless Chromium teardown SIGSEGV
        self._view = view
        app.processEvents()

    @unittest.skipUnless(HAS_PYQT, "Requires Anki's PyQt6/WebEngine Python")
    def test_async_pycmd_queue_delivers_after_qwebchannel_ready(self):
        head_html, body_html = build_page_parts()
        html = (
            '<!doctype html><html class="night-mode"><head>'
            f"{head_html}"
            "<script>"
            "window.__pycmds=[];"
            "setTimeout(function(){ window.pycmd = function(c){ window.__pycmds.push(c); }; }, 60);"
            "</script>"
            f'</head><body class="nightMode">{body_html}</body></html>'
        )
        view = QWebEngineView()
        view.resize(800, 600)
        view.show()
        page = view.page()

        loop = QEventLoop()
        page.loadFinished.connect(lambda _ok: loop.quit())
        page.setHtml(html)
        loop.exec()
        page.loadFinished.disconnect()

        # Wait long enough for both the 60ms pycmd attach and 25ms flush timer
        wait_loop = QEventLoop()
        QTimer.singleShot(150, wait_loop.quit)
        wait_loop.exec()

        out = []
        ev = QEventLoop()
        page.runJavaScript("window.__pycmds", lambda v: (out.append(v), ev.quit()))
        ev.exec()
        self.assertIn("atlas:ready", out[0] if out else [])
        self._async_view = view


class TestCramDeck(unittest.TestCase):
    @unittest.skipUnless(HAS_ANKI, "Requires Anki's backend Python package")
    def test_create_or_rebuild_non_rescheduling_cram_deck(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "collection.anki2")
            col = Collection(db_path)
            try:
                model = col.models.by_name("Basic")
                assert model is not None
                n1 = col.new_note(model)
                n1["Front"] = "Vitamin D calcitriol"
                n1["Back"] = "Ca2+ absorption"
                n1.tags = ["atlas_test_tag"]
                col.add_note(n1, col.decks.get_current_id())

                n2 = col.new_note(model)
                n2["Front"] = "Other topic"
                n2["Back"] = "Other back"
                col.add_note(n2, col.decks.get_current_id())

                cid1 = n1.card_ids()[0]
                before_card = col.get_card(cid1)
                before_queue, before_ivl = before_card.queue, before_card.ivl

                # 1. Empty query must clean up any newly created deck and return 0
                deck_name_0, did_0, count_0 = create_or_rebuild_cram_deck(
                    col, "No Matches", "tag:nonexistent_atlas_xyz", limit=20
                )
                self.assertEqual(did_0, 0)
                self.assertEqual(count_0, 0)
                self.assertIsNone(col.decks.by_name(deck_name_0))

                # 2. Valid query builds a strictly non-rescheduling Filtered Deck
                deck_name, did, count = create_or_rebuild_cram_deck(
                    col, "Vitamin D", "tag:atlas_test_tag", limit=25
                )
                self.assertGreater(did, 0)
                self.assertGreater(count, 0)
                deck_obj = col.decks.get(did)
                self.assertIsNotNone(deck_obj)
                self.assertEqual(deck_obj.get("dyn"), 1)
                self.assertIs(deck_obj.get("resched", True), False)
                self.assertEqual(col.decks.card_count(did, include_subdecks=False), count)

                # 3. Rebuild existing deck in-place without creating duplicate deck
                deck_name_2, did_2, count_2 = create_or_rebuild_cram_deck(
                    col, "Vitamin D", "tag:atlas_test_tag", limit=10
                )
                self.assertEqual(deck_name_2, deck_name)
                self.assertEqual(did_2, did)
                self.assertEqual(count_2, count)

                # 4. Empty the filtered deck & confirm original card tags / scheduling are completely untouched
                col.sched.empty_filtered_deck(did)
                after_card = col.get_card(cid1)
                after_note = col.get_note(n1.id)
                self.assertEqual(after_card.queue, before_queue)
                self.assertEqual(after_card.ivl, before_ivl)
                self.assertEqual(after_note.tags, ["atlas_test_tag"])
            finally:
                col.close()

    @unittest.skipUnless(HAS_ANKI, "Requires Anki's backend Python package")
    def test_deep_inspect_and_live_collection_search(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "collection.anki2")
            col = Collection(db_path)
            try:
                model = col.models.by_name("Basic")
                assert model is not None
                did_root = col.decks.id("AnKing Step Deck")
                did_uw = col.decks.id("AnKing Step Deck::past::UWorld Wrong")

                n1 = col.new_note(model)
                n1["Front"] = "{{c1::Gas gangrene}} is caused by <b>Clostridium perfringens</b>"
                n1["Back"] = "Alpha toxin myonecrosis"
                n1.tags = [
                    "#AK_Step1_v12::#FirstAid::04_Pathology::01_Cellular_Injury::04_Necrosis::*Gangrenous_Necrosis",
                    "#AK_Step1_v12::#Pathoma::Ch1",
                ]
                col.add_note(n1, did_uw)
                c1 = n1.cards()[0]
                c1.queue = -1  # suspended
                col.update_card(c1)

                n2 = col.new_note(model)
                n2["Front"] = "Coagulative necrosis preserves tissue architecture"
                n2["Back"] = "Ischemic infarction"
                n2.tags = [
                    "#AK_Step1_v12::#FirstAid::04_Pathology::01_Cellular_Injury::04_Necrosis::*Coagulative_Necrosis",
                ]
                col.add_note(n2, did_root)

                node_id = "L3:Pathology::S1::01_Cellular_Injury::04_Necrosis"
                search_res = search_collection_for_atlas(
                    col,
                    "gangrene",
                    deck_filter="AnKing Step Deck",
                    exam_scope="all",
                    taxonomy_mode="step_subjects",
                    tag_strip_root="",
                    loaded_node_ids={node_id},
                    token=7,
                )
                self.assertGreaterEqual(search_res["total_notes"], 1)
                self.assertEqual(search_res["topics"][0]["id"], node_id)
                self.assertTrue(any("Gangrenous Necrosis" in s["label"] for s in search_res["subtags"]))
                self.assertTrue(search_res["cards"])
                self.assertNotIn("{{c1::", search_res["cards"][0]["text"])
                self.assertNotIn("<b>", search_res["cards"][0]["text"])

                ins_res = inspect_node_in_col(
                    col,
                    node_id=node_id,
                    query="tag:#AK\\_Step1\\_v12::#FirstAid::04\\_Pathology::01\\_Cellular\\_Injury::04\\_Necrosis",
                    raw_tag="#AK_Step1_v12::#FirstAid::04_Pathology::01_Cellular_Injury::04_Necrosis",
                    query_kind="tag",
                    taxonomy_mode="step_subjects",
                    deck_filter="AnKing Step Deck",
                )
                subtag_labels = [s["label"] for s in ins_res["subtags"]]
                self.assertTrue(any("Gangrenous" in s for s in subtag_labels))
                self.assertTrue(any("Coagulative" in s for s in subtag_labels))
                self.assertEqual(ins_res["gap_mode"], "suspended")
                gs_labels = {g["label"]: g for g in ins_res["gap_sources"]}
                self.assertIn("UWorld Wrong", gs_labels)
                self.assertIn("Pathoma", gs_labels)
                self.assertIn("is:suspended", gs_labels["Pathoma"]["query"])
                self.assertTrue(ins_res["cards"])
                self.assertTrue(ins_res["cards"][0]["query"].startswith("cid:"))

                # Also verify universal 4-level non-AnKing nested tags in live search & inspect
                n3 = col.new_note(model)
                n3["Front"] = "Dijkstra finds shortest weighted graph paths"
                n3["Back"] = "Non-negative edge weights priority queue"
                n3.tags = ["CS::Algorithms::Graphs::Dijkstra", "Exam::Midterm"]
                col.add_note(n3, did_root)
                for c3 in n3.card_ids():
                    cc3 = col.get_card(c3)
                    cc3.queue = -1
                    col.update_card(cc3)

                cs_node = "L3:Algorithms::Graphs"
                cs_search = search_collection_for_atlas(
                    col,
                    "Dijkstra",
                    deck_filter="ALL",
                    exam_scope="all",
                    taxonomy_mode="generic_tags",
                    tag_strip_root="CS",
                    loaded_node_ids={cs_node},
                    token=8,
                )
                self.assertTrue(any("Dijkstra" in s["label"] for s in cs_search["subtags"]))
                cs_ins = inspect_node_in_col(
                    col,
                    node_id=cs_node,
                    query="tag:CS::Algorithms::Graphs",
                    raw_tag="CS::Algorithms::Graphs",
                    query_kind="tag",
                    taxonomy_mode="generic_tags",
                    deck_filter="ALL",
                )
                self.assertTrue(any("Dijkstra" in s["label"] for s in cs_ins["subtags"]))
                self.assertEqual(cs_ins["gap_mode"], "suspended")
            finally:
                col.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
