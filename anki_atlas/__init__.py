"""Anki Atlas: offline visual knowledge map & study radar for Anki."""

from __future__ import annotations

from typing import Any

_atlas_window: Any = None


def open_atlas(reload_existing: bool = True) -> Any:
    """Open or focus the singleton Anki Atlas window and return it."""
    global _atlas_window
    from aqt import mw
    from aqt.qt import Qt
    from aqt.utils import showInfo

    if mw is None or getattr(mw, "col", None) is None:
        showInfo("Please open an Anki profile first.")
        return None

    if _atlas_window is not None:
        try:
            if _atlas_window.isVisible():
                if _atlas_window.windowState() & Qt.WindowState.WindowMinimized:
                    _atlas_window.setWindowState(
                        _atlas_window.windowState() & ~Qt.WindowState.WindowMinimized
                    )
                _atlas_window.raise_()
                _atlas_window.activateWindow()
                if reload_existing:
                    _atlas_window.reload_current()
                return _atlas_window
        except RuntimeError:
            _atlas_window = None

    from .window import create_atlas_window

    win = create_atlas_window(mw)

    def _clear_ref(*_args: Any) -> None:
        global _atlas_window
        if _atlas_window is win:
            _atlas_window = None

    win.destroyed.connect(_clear_ref)
    _atlas_window = win
    win.show()
    return win


def locate_card_on_atlas(card: Any = None) -> None:
    """Open Anki Atlas and fly straight to a card's topic."""
    from aqt import mw
    from aqt.utils import tooltip

    if mw is None or getattr(mw, "col", None) is None:
        return
    if card is None:
        rev = getattr(mw, "reviewer", None)
        card = getattr(rev, "card", None) if rev is not None else None
    if card is None:
        tooltip("Open a card in Reviewer or right-click a card in Browser to show it on Atlas.")
        return
    win = open_atlas(reload_existing=False)
    if win is not None:
        win.locate_card(card)


def _on_reviewer_context_menu(reviewer: Any, menu: Any) -> None:
    card = getattr(reviewer, "card", None)
    if card is None:
        return
    act = menu.addAction("Show on Anki Atlas")
    act.triggered.connect(lambda *_args, c=card: locate_card_on_atlas(c))


def _on_browser_context_menu(browser: Any, menu: Any) -> None:
    try:
        cids = browser.selected_cards()
    except Exception:
        cids = []
    if not cids:
        return
    from aqt import mw

    def _locate_first(*_args: Any) -> None:
        col = getattr(mw, "col", None)
        if col is None:
            return
        try:
            card = col.get_card(cids[0])
        except Exception:
            return
        locate_card_on_atlas(card)

    act = menu.addAction("Show on Anki Atlas")
    act.triggered.connect(_locate_first)


def _on_top_toolbar_links(links: list[str], toolbar: Any) -> None:
    link = toolbar.create_link(
        "atlas",
        "Atlas",
        open_atlas,
        tip="Anki Atlas (Ctrl+Shift+M)",
        id="atlas",
    )
    if len(links) >= 5:
        links.insert(4, link)
    else:
        links.append(link)


def _on_profile_will_close() -> None:
    global _atlas_window
    from .window import clear_cache

    if _atlas_window is not None:
        try:
            _atlas_window.close()
        except Exception:
            pass
        _atlas_window = None
    clear_cache()


def _init() -> None:
    from aqt import gui_hooks, mw
    from aqt.qt import QAction, QKeySequence

    if mw is None:
        return

    gui_hooks.top_toolbar_did_init_links.append(_on_top_toolbar_links)
    gui_hooks.profile_will_close.append(_on_profile_will_close)
    gui_hooks.reviewer_will_show_context_menu.append(_on_reviewer_context_menu)
    gui_hooks.browser_will_show_context_menu.append(_on_browser_context_menu)

    action = QAction("Anki Atlas", mw)
    action.setShortcut(QKeySequence("Ctrl+Shift+M"))
    action.triggered.connect(open_atlas)
    mw.form.menuTools.addAction(action)

    locate_action = QAction("Locate Current Card on Atlas", mw)
    locate_action.setShortcut(QKeySequence("Ctrl+Shift+L"))
    locate_action.triggered.connect(lambda *_args: locate_card_on_atlas())
    mw.form.menuTools.addAction(locate_action)


try:
    import aqt

    if getattr(aqt, "mw", None) is not None:
        _init()
except ImportError:
    pass
