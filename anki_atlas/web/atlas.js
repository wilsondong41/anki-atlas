/* Anki Atlas — 3D/2D Interactive Neural Network + Functional Study Radar */

(function () {
  "use strict";

  const canvas = document.getElementById("atlas-canvas");
  const ctx = canvas.getContext("2d");
  const elGridView = document.getElementById("grid-view");

  const elDeckSelect = document.getElementById("deck-select");
  const elExamPills = document.getElementById("exam-pills");
  const elExamBtns = Array.from(document.querySelectorAll("[data-exam]"));
  const elSearch = document.getElementById("search-input");
  const elSearchResults = document.getElementById("search-results");
  const elViewBtns = Array.from(document.querySelectorAll("[data-view]"));
  const elSpotlightSelect = document.getElementById("spotlight-select");
  const elOverlayWrap = document.getElementById("overlay-wrap");
  const elOverlayBtn = document.getElementById("btn-overlay-menu");
  const elOverlayPanel = document.getElementById("overlay-panel");
  const elConceptBtn = document.getElementById("btn-concepts");
  const elCbBtn = document.getElementById("btn-colorblind");
  const elFitBtn = document.getElementById("btn-fit");
  const elRefreshBtn = document.getElementById("btn-refresh");

  const elSubjectDock = document.getElementById("subject-dock");
  const elTabSubjects = document.getElementById("tab-subjects");
  const elTabPriority = document.getElementById("tab-priority");
  const elDockList = document.getElementById("dock-list");
  const elDockToggle = document.getElementById("btn-dock-toggle");
  const elDockOpen = document.getElementById("btn-dock-open");

  const elFocusBanner = document.getElementById("focus-banner");
  const elFocusLabel = document.getElementById("focus-label");
  const elHopPills = document.getElementById("hop-pills");
  const elHop1Btn = document.getElementById("btn-hop-1");
  const elHop2Btn = document.getElementById("btn-hop-2");
  const elExitFocus = document.getElementById("btn-exit-focus");

  const elHoverTip = document.getElementById("hover-tip");
  const elHudStats = document.getElementById("hud-stats");
  const elStateChips = Array.from(document.querySelectorAll(".state-chip"));
  const elInspector = document.getElementById("inspector");
  const elInsCrumb = document.getElementById("ins-crumb");
  const elInsTitle = document.getElementById("ins-title");
  const elInsBody = document.getElementById("ins-body");
  const elInsClose = document.getElementById("ins-close");
  const elToast = document.getElementById("atlas-toast");
  const elLoading = document.getElementById("loading-overlay");
  const elLoadingText = document.getElementById("loading-text");

  const FOV = 780;

  const state = {
    graph: null,
    nodesById: new Map(),
    allEdges: [],
    allNodeEdges: new Map(),
    overlaysById: new Map(),
    overlayCountsById: new Map(), // overlay_id -> Map(node_id -> card_count)

    // Modes & filters
    focusNodeId: null,     // Local Graph center
    localHops: 1,          // 1 | 2
    isolatedRootId: null,  // Isolated Subject/Subtopic cluster
    pathway: null,         // { fromId, toId, nodeIds: Set, edgeIds: Set, steps: [] }
    pathPickerOpen: false,

    viewMode: "grid",      // "grid" | "2d" | "3d"
    zMorph: 0.0,
    spotlight: "all",      // all | gaps | weak | recent_7d | recent_30d
    activeOverlayIds: new Set(),
    overlayMenuOpen: false,
    showConcepts: true,
    colorblind: false,
    stateFilter: null,
    dockTab: "subjects",   // "subjects" | "priority"
    inspectorTab: null,    // null (auto) | "inside" | "connections"
    gridRootId: null,      // current drill-down root in Grid view
    searchHighlightIds: null, // Set of node IDs matched by live search
    searchTimer: null,
    searchToken: 0,
    lastRemoteSearch: null,
    nodeDetailsCache: new Map(), // nodeId -> { subtags, gap_mode, gap_sources, cards }
    nodeDetailsPending: new Set(),
    dark: true,
    dockOpen: true,

    sceneNodes: [],
    sceneEdges: [],
    sceneById: new Map(),

    selectedNodeId: null,
    selectedEdgeId: null,
    hoveredNodeId: null,
    hoveredEdgeId: null,

    cam: { yaw: 0.26, pitch: 0.18, dist: 1200, tx: 0, ty: 0, tz: 0 },
    targetCam: null,
    velYaw: 0,
    velPitch: 0,

    pointerDown: false,
    dragMode: "orbit",
    dragNode: null,
    dragMoved: false,
    lastMouse: { x: 0, y: 0 },
    downMouse: { x: 0, y: 0 },
    lastInputTs: 0,
    pulsePhase: 0,
    dpr: window.devicePixelRatio || 1,
    width: 960,
    height: 680,
  };

  // --- Async-safe pycmd bridge queue ---
  const pendingCmds = [];
  let flushTimer = null;

  function flushCmds() {
    flushTimer = null;
    if (typeof pycmd === "function") {
      while (pendingCmds.length > 0) {
        pycmd(pendingCmds.shift());
      }
      return;
    }
    if (pendingCmds.length > 0) {
      flushTimer = setTimeout(flushCmds, 25);
    }
  }

  function sendCmd(cmd) {
    if (typeof pycmd === "function" && pendingCmds.length === 0) {
      pycmd(cmd);
      return;
    }
    pendingCmds.push(cmd);
    if (!flushTimer) {
      flushTimer = setTimeout(flushCmds, 25);
    }
  }

  function savePrefs() {
    sendCmd(
      "atlas:prefs:" +
        JSON.stringify({
          show_concept_links: state.showConcepts,
          high_yield_only: false,
          view_mode: state.viewMode,
          colorblind_mode: state.colorblind,
        })
    );
  }

  let toastTimer = null;
  function showToast(msg) {
    if (!msg) return;
    elToast.textContent = msg;
    elToast.classList.remove("hidden");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      elToast.classList.add("hidden");
    }, 1800);
  }

  function hideToast() {
    if (toastTimer) {
      clearTimeout(toastTimer);
      toastTimer = null;
    }
    elToast.classList.add("hidden");
  }

  function plural(n, one, many) {
    return n === 1 ? one : (many || `${one}s`);
  }

  function escHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function trunc(s, maxLen) {
    const str = String(s || "");
    return str.length > maxLen ? str.slice(0, maxLen - 1) + "…" : str;
  }

  function fmtPct(v) {
    return Math.round((v || 0) * 100) + "%";
  }

  function palette() {
    if (state.colorblind) {
      if (state.dark) {
        return {
          bgTop: "#0b101d",
          bgBottom: "#06080f",
          text: "#eef3fc",
          textMuted: "#98a6be",
          treeEdge: "rgba(148, 163, 184, 0.22)",
          treeEdgeHi: "rgba(226, 232, 240, 0.85)",
          sharedEdge: "rgba(148, 163, 184, 0.17)",
          sharedEdgeHi: "#7dd3fc",
          conceptEdge: "rgba(167, 139, 250, 0.15)",
          conceptEdgeHi: "#c4b5fd",
          pathEdge: "#38bdf8",
          selectedRing: "#ffffff",
          frontierRing: "#fde047",
          weakColor: "#fb923c",
          recentColor: "#38bdf8",
          overlayColor: "#fbbf24",
          states: {
            mature: "#3b82f6",
            young: "#7dd3fc",
            new: "#2dd4bf",
            mixed: "#e879f9",
            suspended: "#fde047",
          },
          stateLabels: {
            mature: "Mature",
            young: "Young / Learning",
            new: "New",
            mixed: "Mixed Progress",
            suspended: "Suspended Gap",
          },
        };
      }
      return {
        bgTop: "#f8faff",
        bgBottom: "#edf2fa",
        text: "#0f172a",
        textMuted: "#526075",
        treeEdge: "rgba(71, 85, 105, 0.16)",
        treeEdgeHi: "rgba(15, 23, 42, 0.65)",
        sharedEdge: "rgba(71, 85, 105, 0.13)",
        sharedEdgeHi: "#0072b2",
        conceptEdge: "rgba(79, 70, 229, 0.12)",
        conceptEdgeHi: "#4f46e5",
        pathEdge: "#0072b2",
        selectedRing: "#0f172a",
        frontierRing: "#e69f00",
        weakColor: "#d55e00",
        recentColor: "#56b4e9",
        overlayColor: "#d97706",
        states: {
          mature: "#0072b2",
          young: "#56b4e9",
          new: "#009e73",
          mixed: "#cc79a7",
          suspended: "#d4a700",
        },
        stateLabels: {
          mature: "Mature",
          young: "Young / Learning",
          new: "New",
          mixed: "Mixed Progress",
          suspended: "Suspended Gap",
        },
      };
    }

    // Default Anki Classic colors (aligned with aqt/colors.py + anki/stats.py)
    if (state.dark) {
      return {
        bgTop: "#0b101d",
        bgBottom: "#06080f",
        text: "#eef3fc",
        textMuted: "#98a6be",
        treeEdge: "rgba(148, 163, 184, 0.22)",
        treeEdgeHi: "rgba(226, 232, 240, 0.85)",
        sharedEdge: "rgba(148, 163, 184, 0.17)",
        sharedEdgeHi: "#60a5fa",
        conceptEdge: "rgba(167, 139, 250, 0.15)",
        conceptEdgeHi: "#c4b5fd",
        pathEdge: "#60a5fa",
        selectedRing: "#ffffff",
        frontierRing: "#facc15",
        weakColor: "#f87171",
        recentColor: "#22d3ee",
        overlayColor: "#fbbf24",
        states: {
          mature: "#16a34a",
          young: "#86efac",
          new: "#60a5fa",
          mixed: "#fb923c",
          suspended: "#facc15",
        },
        stateLabels: {
          mature: "Mature",
          young: "Young / Learning",
          new: "New",
          mixed: "Mixed Progress",
          suspended: "Suspended Gap",
        },
      };
    }
    return {
      bgTop: "#f8faff",
      bgBottom: "#edf2fa",
      text: "#0f172a",
      textMuted: "#526075",
      treeEdge: "rgba(71, 85, 105, 0.16)",
      treeEdgeHi: "rgba(15, 23, 42, 0.65)",
      sharedEdge: "rgba(71, 85, 105, 0.13)",
      sharedEdgeHi: "#2563eb",
      conceptEdge: "rgba(79, 70, 229, 0.12)",
      conceptEdgeHi: "#4f46e5",
      pathEdge: "#2563eb",
      selectedRing: "#0f172a",
      frontierRing: "#eab308",
      weakColor: "#dc2626",
      recentColor: "#0891b2",
      overlayColor: "#d97706",
      states: {
        mature: "#15803d",
        young: "#4ade80",
        new: "#2563eb",
        mixed: "#ea580c",
        suspended: "#eab308",
      },
      stateLabels: {
        mature: "Mature",
        young: "Young / Learning",
        new: "New",
        mixed: "Mixed Progress",
        suspended: "Suspended Gap",
      },
    };
  }

  function gridTileColors(hex) {
    const clean = (hex || "#16a34a").replace("#", "");
    const num = parseInt(clean.length === 3 ? clean.replace(/(.)/g, "$1$1") : clean, 16);
    const r = (num >> 16) & 255;
    const g = (num >> 8) & 255;
    const b = num & 255;
    const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    if (lum > 0.56) {
      return { bg: hex, fg: "#0f172a", subFg: "rgba(15,23,42,0.78)", pillBg: "rgba(15,23,42,0.16)", pillFg: "#0f172a" };
    }
    return { bg: hex, fg: "#ffffff", subFg: "rgba(255,255,255,0.88)", pillBg: "rgba(0,0,0,0.34)", pillFg: "#ffffff" };
  }

  const glowCache = new Map();
  function getGlowSprite(hex) {
    if (glowCache.has(hex)) return glowCache.get(hex);
    const c = document.createElement("canvas");
    c.width = 64;
    c.height = 64;
    const g = c.getContext("2d");
    const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0.0, hex);
    grad.addColorStop(0.28, hex + "99");
    grad.addColorStop(0.65, hex + "22");
    grad.addColorStop(1.0, hex + "00");
    g.fillStyle = grad;
    g.fillRect(0, 0, 64, 64);
    glowCache.set(hex, c);
    return c;
  }

  function applyTheme(isDark) {
    state.dark = !!isDark;
    glowCache.clear();
    document.documentElement.classList.toggle("night-mode", state.dark);
    document.body.classList.toggle("nightMode", state.dark);
    document.body.classList.toggle("atlas-dark", state.dark);
    document.body.classList.toggle("atlas-light", !state.dark);
    document.documentElement.classList.toggle("atlas-cb", state.colorblind);
    document.body.classList.toggle("atlas-cb", state.colorblind);
    updateChrome();
    requestDraw();
  }

  function applyColorblind(on) {
    state.colorblind = !!on;
    glowCache.clear();
    hideToast();
    document.documentElement.classList.toggle("atlas-cb", state.colorblind);
    document.body.classList.toggle("atlas-cb", state.colorblind);
    if (elCbBtn) elCbBtn.classList.toggle("active", state.colorblind);
    updateChrome();
    renderInspector();
    if (state.viewMode !== "grid") requestDraw();
  }

  function baseRadius(node) {
    if (node.level === 1) return 9.5;
    if (node.level === 2) return 5.5 + Math.min(2.5, Math.log1p(node.total || 0) * 0.42);
    return 2.9 + Math.min(2.6, Math.log1p(node.total || 0) * 0.48);
  }

  function getActiveOverlays() {
    const list = [];
    for (const id of state.activeOverlayIds) {
      const ov = state.overlaysById.get(id);
      if (ov) list.push(ov);
    }
    return list;
  }

  function hasActiveOverlays() {
    return state.activeOverlayIds.size > 0;
  }

  function getOverlayCount(nodeId) {
    if (!state.activeOverlayIds.size) return 0;
    let sum = 0;
    for (const id of state.activeOverlayIds) {
      const m = state.overlayCountsById.get(id);
      if (m) sum += m.get(nodeId) || 0;
    }
    const node = state.nodesById.get(nodeId);
    return node ? Math.min(node.total || sum, sum) : sum;
  }

  function getActiveOverlayQuery(baseQuery) {
    const ovs = getActiveOverlays();
    if (!ovs.length) return baseQuery;
    if (ovs.length === 1) return `${baseQuery} ${ovs[0].query_term}`;
    return `${baseQuery} (${ovs.map((ov) => ov.query_term).join(" OR ")})`;
  }

  function getActiveOverlayLabel() {
    const ovs = getActiveOverlays();
    if (!ovs.length) return "";
    if (ovs.length === 1) return ovs[0].label;
    if (ovs.length === 2) return `${ovs[0].label} + ${ovs[1].label}`;
    return `${ovs.length} tags`;
  }

  function buildScene() {
    if (!state.graph) {
      state.sceneNodes = [];
      state.sceneEdges = [];
      state.sceneById = new Map();
      return;
    }

    const sceneNodes = [];
    const byId = new Map();

    // 1. Local Graph (1 hop or 2 hops)
    if (state.focusNodeId && state.nodesById.has(state.focusNodeId)) {
      const center = state.nodesById.get(state.focusNodeId);
      const centerItem = {
        node: center,
        x: 0,
        y: 0,
        z: 0,
        baseR: Math.max(8.5, baseRadius(center) * 1.45),
        hop: 0,
      };
      sceneNodes.push(centerItem);
      byId.set(center.id, centerItem);

      function collectHop(sourceIds, hopNum, seenSet, limit) {
        const list = [];
        for (const sid of sourceIds) {
          for (const edge of state.allNodeEdges.get(sid) || []) {
            if (!state.showConcepts && edge.kind === "concept") continue;
            const otherId = edge.source === sid ? edge.target : edge.source;
            if (seenSet.has(otherId)) continue;
            const other = state.nodesById.get(otherId);
            if (!other) continue;
            list.push({ node: other, edge });
          }
        }
        const order = { shared: 0, tree: 1, concept: 2 };
        list.sort((a, b) => {
          if (a.edge.kind !== b.edge.kind) return (order[a.edge.kind] ?? 3) - (order[b.edge.kind] ?? 3);
          return b.edge.strength - a.edge.strength;
        });
        const picked = [];
        for (const entry of list) {
          if (seenSet.has(entry.node.id)) continue;
          seenSet.add(entry.node.id);
          picked.push(entry.node);
          if (picked.length >= limit) break;
        }
        return picked;
      }

      const seen = new Set([center.id]);
      const hop1 = collectHop([center.id], 1, seen, 26);
      const hop2 = state.localHops >= 2 ? collectHop(hop1.map((n) => n.id), 2, seen, 28) : [];

      function placeRing(nodesList, ringR, hopNum) {
        const k = nodesList.length;
        const golden = Math.PI * (3 - Math.sqrt(5));
        for (let i = 0; i < k; i++) {
          const nb = nodesList[i];
          const ang = (2 * Math.PI * i) / Math.max(1, k) - Math.PI / 2;
          const yOff = k >= 6 ? Math.sin(ang + i * golden * 0.16) * (ringR * 0.72) : ringR * Math.sin(ang);
          const zOff = k >= 6 ? Math.cos(i * golden) * (ringR * 0.42) : 0;
          const xOff = k >= 6 ? Math.cos(ang) * (ringR * 0.92) : ringR * Math.cos(ang);
          const item = {
            node: nb,
            x: xOff,
            y: yOff,
            z: zOff,
            baseR: Math.max(hopNum === 1 ? 5.5 : 4.2, baseRadius(nb) * (hopNum === 1 ? 1.15 : 0.92)),
            hop: hopNum,
          };
          sceneNodes.push(item);
          byId.set(nb.id, item);
        }
      }

      const r1 = Math.max(175, Math.min(310, 125 + hop1.length * 9));
      placeRing(hop1, r1, 1);
      if (hop2.length > 0) {
        placeRing(hop2, r1 + 150, 2);
      }

      const sceneEdges = [];
      for (const edge of state.allEdges) {
        if (!state.showConcepts && edge.kind === "concept") continue;
        const a = byId.get(edge.source);
        const b = byId.get(edge.target);
        if (a && b) sceneEdges.push({ edge, a, b });
      }

      state.sceneNodes = sceneNodes;
      state.sceneEdges = sceneEdges;
      state.sceneById = byId;
      updateChrome();
      return;
    }

    // 2. Isolated Subject / Subtopic Cluster (centered at origin + clean outer bridge halo)
    if (state.isolatedRootId && state.nodesById.has(state.isolatedRootId)) {
      const coreIds = new Set();
      function collectDescendants(id) {
        if (coreIds.has(id)) return;
        const n = state.nodesById.get(id);
        if (!n) return;
        coreIds.add(id);
        for (const cid of n.children || []) collectDescendants(cid);
      }
      collectDescendants(state.isolatedRootId);

      // Compute centroid of isolated subtree so core sits dead-center in workspace
      let rx = 0, ry = 0, rz = 0;
      for (const id of coreIds) {
        const n = state.nodesById.get(id);
        rx += n.x;
        ry += n.y;
        rz += n.z || 0;
      }
      const coreCount = Math.max(1, coreIds.size);
      rx /= coreCount;
      ry /= coreCount;
      rz /= coreCount;

      let coreMaxR = 160;
      for (const id of coreIds) {
        const n = state.nodesById.get(id);
        const cx = n.x - rx;
        const cy = n.y - ry;
        const cz = (n.z || 0) - rz;
        coreMaxR = Math.max(coreMaxR, Math.hypot(cx, cy, cz));
        const item = { node: n, x: cx, y: cy, z: cz, baseR: baseRadius(n), hop: 0, isExternal: false };
        sceneNodes.push(item);
        byId.set(n.id, item);
      }

      // Include top direct cross-system external bridge endpoints on a clean outer ring
      const extRanked = [];
      for (const id of coreIds) {
        for (const edge of state.allNodeEdges.get(id) || []) {
          if (edge.kind === "tree") continue;
          if (!state.showConcepts && edge.kind === "concept") continue;
          const otherId = edge.source === id ? edge.target : edge.source;
          if (!coreIds.has(otherId) && state.nodesById.has(otherId)) {
            extRanked.push({ id: otherId, score: (edge.kind === "shared" ? 1.5 : 0.8) * edge.strength });
          }
        }
      }
      extRanked.sort((a, b) => b.score - a.score);
      const extIds = [];
      const seenExt = new Set();
      for (const ext of extRanked) {
        if (seenExt.has(ext.id)) continue;
        seenExt.add(ext.id);
        extIds.push(ext.id);
        if (extIds.length >= 16) break;
      }

      const haloR = coreMaxR * 1.24 + 56;
      for (let i = 0; i < extIds.length; i++) {
        const n = state.nodesById.get(extIds[i]);
        let dx = n.x - rx;
        let dy = n.y - ry;
        let dz = (n.z || 0) - rz;
        let norm = Math.hypot(dx, dy, dz);
        if (norm < 1e-3) {
          const ang = (i / Math.max(1, extIds.length)) * Math.PI * 2;
          dx = Math.cos(ang);
          dy = Math.sin(ang);
          dz = 0.2 * Math.sin(ang * 2);
          norm = Math.hypot(dx, dy, dz);
        }
        const item = {
          node: n,
          x: (dx / norm) * haloR,
          y: (dy / norm) * haloR,
          z: (dz / norm) * haloR * 0.65,
          baseR: Math.max(baseRadius(n) * 0.92, 5.4),
          hop: 1,
          isExternal: true,
        };
        sceneNodes.push(item);
        byId.set(n.id, item);
      }

      const sceneEdges = [];
      for (const edge of state.allEdges) {
        if (!state.showConcepts && edge.kind === "concept") continue;
        const a = byId.get(edge.source);
        const b = byId.get(edge.target);
        if (a && b) sceneEdges.push({ edge, a, b });
      }
      state.sceneNodes = sceneNodes;
      state.sceneEdges = sceneEdges;
      state.sceneById = byId;
      updateChrome();
      return;
    }

    // 3. Full Unified Network
    for (const n of state.graph.nodes) {
      const item = {
        node: n,
        x: n.x,
        y: n.y,
        z: n.z || 0,
        baseR: baseRadius(n),
        hop: 0,
      };
      sceneNodes.push(item);
      byId.set(n.id, item);
    }

    const sceneEdges = [];
    for (const edge of state.allEdges) {
      if (!state.showConcepts && edge.kind === "concept") continue;
      const a = byId.get(edge.source);
      const b = byId.get(edge.target);
      if (a && b) sceneEdges.push({ edge, a, b });
    }

    state.sceneNodes = sceneNodes;
    state.sceneEdges = sceneEdges;
    state.sceneById = byId;
    updateChrome();
  }

  function renderDock() {
    if (!state.graph) {
      elDockList.innerHTML = "";
      return;
    }
    const p = palette();

    // Dynamic dock tab labels (plain English + adapts to non-AnKing decks)
    const taxMode = (state.graph.summary || {}).taxonomy_mode || "step_subjects";
    elTabSubjects.textContent = taxMode === "step_subjects" ? "Subjects" : "Topics";
    if (hasActiveOverlays()) {
      elTabPriority.textContent = "Matches";
    } else if (state.spotlight === "weak") {
      elTabPriority.textContent = "Weak Spots";
    } else if (state.spotlight === "recent_7d" || state.spotlight === "recent_30d") {
      elTabPriority.textContent = "Recent";
    } else {
      elTabPriority.textContent = "Study Next";
    }

    elTabSubjects.classList.toggle("active", state.dockTab === "subjects");
    elTabPriority.classList.toggle("active", state.dockTab === "priority");

    if (state.dockTab === "subjects") {
      const l1s = state.graph.nodes
        .filter((n) => n.level === 1)
        .sort((a, b) => b.total - a.total);
      elDockList.innerHTML = l1s
        .map((n) => {
          const col = p.states[n.state] || p.states.mature;
          let metric = fmtPct(n.learned_pct);
          if (hasActiveOverlays()) metric = String(getOverlayCount(n.id));
          else if (state.spotlight === "gaps") metric = String(n.suspended);
          else if (state.spotlight === "weak") metric = String(n.weak_cards || 0);
          else if (state.spotlight === "recent_7d") metric = String(n.rev_7d || 0);
          else if (state.spotlight === "recent_30d") metric = String(n.rev_30d || 0);

          const active = state.selectedNodeId === n.id || state.focusNodeId === n.id;
          const isIso = state.isolatedRootId === n.id;
          return `
            <div class="subj-row ${active ? "active" : ""}">
              <button class="subj-item" data-jump="${escHtml(n.id)}">
                <span class="subj-left">
                  <i class="lg-dot" style="background:${col}"></i>
                  <span class="subj-name">${escHtml(n.label)}</span>
                </span>
                <span class="subj-pct">${metric}</span>
              </button>
              <button class="dock-mini-btn ${isIso ? "active" : ""}" data-isolate="${escHtml(n.id)}" title="Isolate this cluster">&#9678;</button>
            </div>
          `;
        })
        .join("");
    } else {
      const finLvl = state.graph.summary.l3_count > 0 ? 3 : (state.graph.summary.l2_count > 0 ? 2 : 1);
      let rows = [];

      if (hasActiveOverlays()) {
        rows = state.graph.nodes
          .filter((n) => n.level === finLvl && getOverlayCount(n.id) > 0)
          .sort((a, b) => getOverlayCount(b.id) - getOverlayCount(a.id) || b.total - a.total)
          .slice(0, 45)
          .map((n) => ({
            node: n,
            metric: `${getOverlayCount(n.id)}`,
            query: getActiveOverlayQuery(n.queries.all),
          }));
      } else if (state.spotlight === "weak") {
        rows = state.graph.nodes
          .filter((n) => n.level === finLvl && (n.weak_cards > 0 || n.weak_score > 0.15))
          .sort((a, b) => b.weak_cards - a.weak_cards || b.weak_score - a.weak_score)
          .slice(0, 45)
          .map((n) => ({
            node: n,
            metric: `${n.weak_cards} weak`,
            query: n.queries.weak,
          }));
      } else if (state.spotlight === "recent_7d" || state.spotlight === "recent_30d") {
        const key = state.spotlight === "recent_7d" ? "rev_7d" : "rev_30d";
        rows = state.graph.nodes
          .filter((n) => n.level === finLvl && (n[key] || 0) > 0)
          .sort((a, b) => (b[key] || 0) - (a[key] || 0))
          .slice(0, 45)
          .map((n) => ({
            node: n,
            metric: `${n[key]} rev`,
            query: n.queries.all,
          }));
      } else {
        // Default Study Next gaps queue
        const ids = state.graph.next_gaps || [];
        rows = ids
          .map((id) => state.nodesById.get(id))
          .filter(Boolean)
          .slice(0, 45)
          .map((n) => ({
            node: n,
            metric: `${n.suspended} susp`,
            query: n.queries.suspended,
          }));
      }

      if (!rows.length) {
        elDockList.innerHTML = `<div style="padding:12px;color:var(--text-soft);font-size:12px;">No matching topics in this view.</div>`;
      } else {
        elDockList.innerHTML = rows
          .map(({ node, metric, query }) => {
            const col = p.states[node.state] || p.states.mature;
            const parent = (node.path || [])[0] || "";
            const active = state.selectedNodeId === node.id;
            return `
              <div class="subj-row ${active ? "active" : ""}">
                <button class="subj-item" data-jump="${escHtml(node.id)}">
                  <span class="subj-left" style="flex-direction:column;align-items:flex-start;gap:1px;">
                    <span style="display:flex;align-items:center;gap:5px;width:100%;">
                      <i class="lg-dot" style="background:${col}"></i>
                      <span class="subj-name">${escHtml(node.label)}</span>
                    </span>
                    <span class="subj-sub" style="padding-left:13px">${escHtml(parent)}</span>
                  </span>
                  <span class="subj-pct">${escHtml(metric)}</span>
                </button>
                <button class="dock-mini-btn" data-browser="${escHtml(query)}" title="Open in Anki Browser">&#8599;</button>
              </div>
            `;
          })
          .join("");
      }
    }

    for (const btn of elDockList.querySelectorAll("[data-jump]")) {
      btn.addEventListener("click", () => flyToNode(btn.getAttribute("data-jump")));
    }
    for (const btn of elDockList.querySelectorAll("[data-isolate]")) {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const id = btn.getAttribute("data-isolate");
        if (state.isolatedRootId === id) clearIsolation();
        else isolateCluster(id);
      });
    }
    for (const btn of elDockList.querySelectorAll("[data-browser]")) {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        sendCmd("atlas:browser:" + btn.getAttribute("data-browser"));
      });
    }
  }

  function sortNodesForStudy(list) {
    return [...list].sort((a, b) => {
      if (hasActiveOverlays()) {
        return getOverlayCount(b.id) - getOverlayCount(a.id) || b.total - a.total;
      }
      if (state.spotlight === "gaps") {
        return (b.suspended - a.suspended) || b.total - a.total;
      }
      if (state.spotlight === "weak") {
        return ((b.weak_cards || 0) - (a.weak_cards || 0)) || b.total - a.total;
      }
      if (state.spotlight === "recent_7d") {
        return ((b.rev_7d || 0) - (a.rev_7d || 0)) || b.total - a.total;
      }
      if (state.spotlight === "recent_30d") {
        return ((b.rev_30d || 0) - (a.rev_30d || 0)) || b.total - a.total;
      }
      return b.total - a.total;
    });
  }

  function gridGapPillText(node) {
    if (hasActiveOverlays()) {
      const ov = getOverlayCount(node.id);
      return ov > 0 ? `${ov} hits` : "";
    }
    if (state.spotlight === "weak") {
      return node.weak_cards > 0 ? `${node.weak_cards} weak` : "";
    }
    if (state.spotlight === "recent_7d") {
      return node.rev_7d > 0 ? `${node.rev_7d} rev` : "";
    }
    if (state.spotlight === "recent_30d") {
      return node.rev_30d > 0 ? `${node.rev_30d} rev` : "";
    }
    if (node.suspended > 0) return `${node.suspended} susp`;
    return "";
  }

  function renderGridView() {
    if (!elGridView) return;
    const isGrid = state.viewMode === "grid";
    canvas.classList.toggle("hidden", isGrid);
    elGridView.classList.toggle("hidden", !isGrid);
    elGridView.classList.toggle("has-dock", state.dockOpen);
    elGridView.classList.toggle("has-inspector", !elInspector.classList.contains("hidden"));
    if (!isGrid || !state.graph) {
      if (!isGrid) elGridView.innerHTML = "";
      return;
    }

    const p = palette();
    const filterActive = state.spotlight !== "all" || Boolean(state.stateFilter) || hasActiveOverlays();
    const searchHits = state.searchHighlightIds;
    const rootId = state.gridRootId || state.isolatedRootId || null;
    const rootNode = rootId && state.nodesById.has(rootId) ? state.nodesById.get(rootId) : null;

    if (!rootNode) {
      const l1s = sortNodesForStudy(state.graph.nodes.filter((n) => n.level === 1));
      const taxMode = (state.graph.summary || {}).taxonomy_mode || "step_subjects";
      const heading = taxMode === "step_subjects" ? "All Subjects" : "All Topics";
      let html = `
        <div class="grid-crumb-bar">
          <div class="grid-crumbs">
            <span>${heading} (${l1s.length})</span>
            ${searchHits ? `<span class="grid-tile-pill" style="background:var(--accent-bg);color:var(--accent)">Search Highlight Active</span>` : ""}
          </div>
          ${searchHits ? `<button class="neighbor-pill" id="grid-clear-search">Clear Highlight</button>` : ""}
        </div>
        <div class="grid-subjects">
      `;

      for (const n of l1s) {
        const tot = Math.max(1, n.total);
        const wMat = (n.mature / tot) * 100;
        const wYng = (n.young / tot) * 100;
        const wNew = (n.new / tot) * 100;
        const wSusp = (n.suspended / tot) * 100;
        const pill = gridGapPillText(n);
        const dimCard = (filterActive && !nodeMatchesFilter(n)) || (searchHits && !searchHits.has(n.id));
        const hitCard = searchHits && searchHits.has(n.id);
        const activeCard = state.selectedNodeId === n.id;

        const children = sortNodesForStudy((n.children || []).map((id) => state.nodesById.get(id)).filter(Boolean)).slice(0, 12);
        let tilesHtml = "";
        for (const ch of children) {
          const chCol = nodeVisualColor(ch, p);
          const tc = gridTileColors(chCol);
          const grow = Math.max(1, Math.round(Math.sqrt(ch.total || 1)));
          const dimTile = (filterActive && !nodeMatchesFilter(ch)) || (searchHits && !searchHits.has(ch.id));
          const hitTile = searchHits && searchHits.has(ch.id);
          tilesHtml += `<button class="grid-mini-tile ${dimTile ? "dimmed" : ""} ${hitTile ? "search-hit" : ""}" data-grid-jump="${escHtml(ch.id)}" style="background:${tc.bg};color:${tc.fg};flex-grow:${grow}" title="${escHtml(ch.label)} — ${ch.total} cards (${fmtPct(ch.learned_pct)} learned)">${escHtml(ch.label)}</button>`;
        }

        html += `
          <div class="grid-subj-card ${dimCard ? "dimmed" : ""} ${hitCard ? "search-hit" : ""} ${activeCard ? "active" : ""}">
            <button class="grid-subj-head" data-grid-drill="${escHtml(n.id)}">
              <div class="grid-subj-title-row">
                <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(n.label)}</span>
                ${pill ? `<span class="grid-tile-pill" style="background:var(--surface-muted);color:var(--c-suspended)">${escHtml(pill)}</span>` : `<span style="font-size:11.5px;color:var(--text-muted)">${fmtPct(n.learned_pct)}</span>`}
              </div>
              <div class="compact-counts" style="margin:0">${n.total.toLocaleString()} ${plural(n.total, "card")} &middot; ${fmtPct(n.learned_pct)} learned</div>
              <div class="drill-bar" style="margin-top:2px">
                <div class="seg-mature" style="width:${wMat.toFixed(1)}%"></div>
                <div class="seg-young" style="width:${wYng.toFixed(1)}%"></div>
                <div class="seg-new" style="width:${wNew.toFixed(1)}%"></div>
                <div class="seg-susp" style="width:${wSusp.toFixed(1)}%"></div>
              </div>
            </button>
            ${tilesHtml ? `<div class="grid-mini-tiles">${tilesHtml}</div>` : ""}
          </div>
        `;
      }
      html += `</div>`;
      elGridView.innerHTML = html;
    } else {
      // Drilled-in proportional Mastery Heatmap inside rootNode
      const ancestors = [];
      let curP = rootNode.parent_id;
      let s = 0;
      while (curP && state.nodesById.has(curP) && s++ < 6) {
        const anc = state.nodesById.get(curP);
        ancestors.unshift(anc);
        curP = anc.parent_id;
      }
      let crumbHtml = `<button class="crumb-btn" data-grid-drill="">All</button>`;
      for (const anc of ancestors) {
        crumbHtml += `<span class="crumb-sep">&rsaquo;</span><button class="crumb-btn" data-grid-drill="${escHtml(anc.id)}">${escHtml(anc.label)}</button>`;
      }
      crumbHtml += `<span class="crumb-sep">&rsaquo;</span><span>${escHtml(rootNode.label)}</span>`;

      const children = sortNodesForStudy((rootNode.children || []).map((id) => state.nodesById.get(id)).filter(Boolean));
      let tilesHtml = "";
      for (const ch of children) {
        const chCol = nodeVisualColor(ch, p);
        const tc = gridTileColors(chCol);
        const basis = Math.max(150, Math.min(340, 130 + Math.round(Math.sqrt(ch.total || 1) * 7.5)));
        const pill = gridGapPillText(ch);
        const dimTile = (filterActive && !nodeMatchesFilter(ch)) || (searchHits && !searchHits.has(ch.id));
        const hitTile = searchHits && searchHits.has(ch.id);
        const activeTile = state.selectedNodeId === ch.id;
        const hasKids = (ch.children || []).length > 0;
        tilesHtml += `
          <button class="grid-tile ${dimTile ? "dimmed" : ""} ${hitTile ? "search-hit" : ""} ${activeTile ? "active" : ""}" data-grid-jump="${escHtml(ch.id)}" style="background:${tc.bg};color:${tc.fg};flex-basis:${basis}px">
            <div class="grid-tile-title">${escHtml(ch.label)}${hasKids ? " &rsaquo;" : ""}</div>
            <div class="grid-tile-meta" style="color:${tc.subFg}">
              <span>${fmtPct(ch.learned_pct)} &middot; ${ch.total.toLocaleString()}</span>
              ${pill ? `<span class="grid-tile-pill" style="background:${tc.pillBg};color:${tc.pillFg}">${escHtml(pill)}</span>` : ""}
            </div>
          </button>
        `;
      }

      elGridView.innerHTML = `
        <div class="grid-crumb-bar">
          <div class="grid-crumbs">${crumbHtml}</div>
          <div style="display:flex;gap:6px">
            ${searchHits ? `<button class="neighbor-pill" id="grid-clear-search">Clear Highlight</button>` : ""}
            <button class="neighbor-pill" id="grid-open-3d">Show in 3D</button>
          </div>
        </div>
        <div class="grid-tiles">${tilesHtml || `<div style="color:var(--text-soft);padding:12px">No subtopics inside.</div>`}</div>
      `;
    }

    elGridView.querySelector("#grid-clear-search")?.addEventListener("click", () => {
      state.searchHighlightIds = null;
      updateChrome();
    });
    elGridView.querySelector("#grid-open-3d")?.addEventListener("click", () => {
      setViewMode("3d");
      flyToNode(rootNode.id);
    });
    for (const btn of elGridView.querySelectorAll("[data-grid-drill]")) {
      btn.addEventListener("click", () => {
        const tid = btn.getAttribute("data-grid-drill") || null;
        hideToast();
        state.gridRootId = tid;
        if (tid) {
          state.selectedNodeId = tid;
          state.selectedEdgeId = null;
          state.pathPickerOpen = false;
          state.inspectorTab = null;
          renderInspector();
        }
        renderDock();
        renderGridView();
      });
    }
    for (const btn of elGridView.querySelectorAll("[data-grid-jump]")) {
      btn.addEventListener("click", () => {
        const tid = btn.getAttribute("data-grid-jump");
        const targetNode = state.nodesById.get(tid);
        if (targetNode && (targetNode.children || []).length > 0) {
          state.gridRootId = tid;
        }
        flyToNode(tid);
      });
    }
  }

  function updateChrome() {
    // Banner priority: Pathway -> Local Graph -> Isolation
    if (state.pathway) {
      const a = state.nodesById.get(state.pathway.fromId);
      const b = state.nodesById.get(state.pathway.toId);
      const hops = Math.max(0, state.pathway.steps.length - 1);
      elFocusLabel.textContent = `Pathway: ${a?.label || ""} → ${b?.label || ""} (${hops} ${hops === 1 ? "hop" : "hops"})`;
      elHopPills.classList.add("hidden");
      elExitFocus.textContent = "Clear Path (Esc)";
      elFocusBanner.classList.remove("hidden");
    } else if (state.focusNodeId && state.nodesById.has(state.focusNodeId)) {
      const fn = state.nodesById.get(state.focusNodeId);
      const links = Math.max(0, state.sceneNodes.length - 1);
      elFocusLabel.textContent = `Local Graph: ${fn.label} (${state.localHops} ${plural(state.localHops, "hop")} · ${links} ${plural(links, "link")})`;
      elHopPills.classList.remove("hidden");
      elHop1Btn.classList.toggle("active", state.localHops === 1);
      elHop2Btn.classList.toggle("active", state.localHops === 2);
      elExitFocus.textContent = "Full Network (Esc)";
      elFocusBanner.classList.remove("hidden");
    } else if (state.isolatedRootId && state.nodesById.has(state.isolatedRootId)) {
      const iso = state.nodesById.get(state.isolatedRootId);
      const totVis = state.sceneNodes.length;
      elFocusLabel.textContent = `Isolated: ${iso.label} · ${totVis} ${plural(totVis, "topic")} + bridges`;
      elHopPills.classList.add("hidden");
      elExitFocus.textContent = "Show All (Esc)";
      elFocusBanner.classList.remove("hidden");
    } else {
      elFocusBanner.classList.add("hidden");
    }

    const chromePal = palette();
    for (const chip of elStateChips) {
      const s = chip.dataset.state;
      const dot = chip.querySelector(".lg-dot");
      if (dot && chromePal.states[s]) dot.style.background = chromePal.states[s];
      chip.classList.toggle("active", state.stateFilter === s);
      chip.classList.toggle("dimmed", Boolean(state.stateFilter && state.stateFilter !== s));
    }

    for (const btn of elViewBtns) {
      btn.classList.toggle("active", btn.dataset.view === state.viewMode);
    }
    if (elCbBtn) elCbBtn.classList.toggle("active", state.colorblind);
    if (elConceptBtn) elConceptBtn.classList.toggle("hidden", state.viewMode === "grid");
    if (elFitBtn) elFitBtn.classList.toggle("hidden", state.viewMode === "grid");
    elSpotlightSelect.classList.toggle("active-filter", state.spotlight !== "all");
    if (elOverlayBtn) {
      const ovCnt = state.activeOverlayIds.size;
      const ovLbl =
        ovCnt === 0
          ? "Highlight Tags ▾"
          : ovCnt === 1
          ? `${trunc(getActiveOverlayLabel(), 18)} ▾`
          : `Tags (${ovCnt}) ▾`;
      elOverlayBtn.textContent = ovLbl;
      elOverlayBtn.classList.toggle("active-filter", ovCnt > 0);
    }

    if (state.graph) {
      const sum = state.graph.summary;
      const topicCount = state.graph.nodes.length;
      const hint =
        state.viewMode === "grid"
          ? "Click any block to drill down · Yellow = suspended"
          : state.viewMode === "3d"
          ? "Drag: orbit · Scroll: zoom · Right-drag: pan"
          : "Drag: pan · Scroll: zoom";
      let statusPrefix = `${topicCount.toLocaleString()} ${plural(topicCount, "topic")} · ${sum.total_cards.toLocaleString()} ${plural(sum.total_cards, "card")} · ${fmtPct(sum.learned_pct)} learned`;

      const ovs = getActiveOverlays();
      if (ovs.length === 1) {
        const ov = ovs[0];
        statusPrefix = `${ov.label}: ${ov.total_cards.toLocaleString()} ${plural(ov.total_cards, "card")} across network`;
      } else if (ovs.length > 1) {
        statusPrefix = `${ovs.length} tags (${ovs.map((o) => o.label).join(", ")}): matching topics highlighted`;
      } else if (state.spotlight === "gaps") {
        statusPrefix = `${topicCount.toLocaleString()} ${plural(topicCount, "topic")} · ${sum.suspended.toLocaleString()} suspended`;
      } else if (state.spotlight === "weak") {
        const wc = sum.weak_cards || 0;
        statusPrefix = `${topicCount.toLocaleString()} ${plural(topicCount, "topic")} · ${wc.toLocaleString()} weak/lapsed ${plural(wc, "card")}`;
      } else if (state.spotlight === "recent_7d") {
        const r7 = sum.rev_7d || 0;
        statusPrefix = `${r7.toLocaleString()} ${plural(r7, "card")} reviewed in last 7 days`;
      } else if (state.spotlight === "recent_30d") {
        const r30 = sum.rev_30d || 0;
        statusPrefix = `${r30.toLocaleString()} ${plural(r30, "card")} reviewed in last 30 days`;
      }

      elHudStats.textContent = `${statusPrefix} · ${hint}`;
      renderDock();
      renderGridView();
    }
  }

  function fitCamera(immediate) {
    if (!state.sceneNodes.length) {
      state.cam = { yaw: 0.26, pitch: 0.18, dist: 900, tx: 0, ty: 0, tz: 0 };
      requestDraw();
      return;
    }
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity, minZ = Infinity, maxZ = -Infinity;
    for (const item of state.sceneNodes) {
      const pad = item.node.level === 1 && !state.focusNodeId ? 90 : 38;
      minX = Math.min(minX, item.x - pad);
      maxX = Math.max(maxX, item.x + pad);
      minY = Math.min(minY, item.y - pad);
      maxY = Math.max(maxY, item.y + pad);
      minZ = Math.min(minZ, item.z - pad);
      maxZ = Math.max(maxZ, item.z + pad);
    }
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    const cz = (minZ + maxZ) / 2;
    const spanW = Math.max(220, maxX - minX);
    const spanH = Math.max(220, maxY - minY);

    const dockPad = state.dockOpen ? 242 : 24;
    const insPad = !elInspector.classList.contains("hidden") ? 348 : 24;
    const usableW = Math.max(260, state.width - dockPad - insPad);
    const usableH = Math.max(240, state.height - 80);
    const distW = ((spanW * 0.52) * FOV) / (usableW * 0.44);
    const distH = ((spanH * 0.52) * FOV) / (usableH * 0.45);
    const dist = Math.max(360, distW, distH);

    const dest = {
      yaw: state.viewMode === "3d" ? (state.focusNodeId ? 0.18 : 0.26) : 0,
      pitch: state.viewMode === "3d" ? (state.focusNodeId ? 0.14 : 0.18) : 0,
      dist,
      tx: cx,
      ty: cy,
      tz: cz,
    };
    state.velYaw = 0;
    state.velPitch = 0;
    if (immediate) {
      state.cam = dest;
      state.targetCam = null;
      requestDraw();
    } else {
      state.targetCam = dest;
      requestDraw();
    }
  }

  function flyToNode(nodeId) {
    const node = state.nodesById.get(nodeId);
    if (!node) return;
    if (state.focusNodeId && !state.sceneById.has(nodeId)) {
      state.focusNodeId = null;
      buildScene();
    }
    if (state.isolatedRootId && !state.sceneById.has(nodeId)) {
      state.isolatedRootId = null;
      buildScene();
    }

    state.selectedNodeId = nodeId;
    state.selectedEdgeId = null;
    state.pathPickerOpen = false;
    state.inspectorTab = null;
    if ((node.children || []).length > 0) {
      state.gridRootId = nodeId;
    } else if (node.parent_id) {
      state.gridRootId = node.parent_id;
    }
    renderInspector();
    renderDock();
    if (state.viewMode === "grid") renderGridView();

    const item = state.sceneById.get(nodeId);
    if (!item) return;

    const targetDist =
      node.level === 1 ? Math.max(360, (node.lobe_r || 180) * 2.5) :
      node.level === 2 ? 420 :
      380;

    let yaw = state.cam.yaw;
    let pitch = state.cam.pitch;
    if (state.viewMode === "3d" && (Math.abs(item.x) + Math.abs(item.z) > 10)) {
      yaw = Math.atan2(item.x, item.z) * 0.45;
      pitch = Math.max(-0.45, Math.min(0.45, -item.y / 900));
    }

    state.velYaw = 0;
    state.velPitch = 0;
    state.targetCam = {
      yaw: state.viewMode === "3d" ? yaw : 0,
      pitch: state.viewMode === "3d" ? pitch : 0,
      dist: Math.min(state.cam.dist, targetDist),
      tx: item.x,
      ty: item.y,
      tz: item.z,
    };
    requestDraw();
  }

  function enterFocus(nodeId) {
    if (!state.nodesById.has(nodeId)) return;
    state.pathway = null;
    state.isolatedRootId = null;
    state.focusNodeId = nodeId;
    state.selectedNodeId = nodeId;
    state.selectedEdgeId = null;
    state.pathPickerOpen = false;
    buildScene();
    renderInspector();
    fitCamera(false);
  }

  function exitFocus() {
    if (!state.focusNodeId) return;
    hideToast();
    state.focusNodeId = null;
    buildScene();
    renderInspector();
    fitCamera(false);
  }

  function isolateCluster(nodeId) {
    if (!state.nodesById.has(nodeId)) return;
    hideToast();
    state.pathway = null;
    state.focusNodeId = null;
    state.isolatedRootId = nodeId;
    state.selectedNodeId = nodeId;
    state.selectedEdgeId = null;
    state.pathPickerOpen = false;
    buildScene();
    renderInspector();
    fitCamera(false);
  }

  function clearIsolation() {
    if (!state.isolatedRootId) return;
    hideToast();
    state.isolatedRootId = null;
    buildScene();
    renderInspector();
    fitCamera(false);
  }

  // --- Shortest Path Finder (A -> B) ---
  function findShortestPath(fromId, toId) {
    if (fromId === toId || !state.nodesById.has(fromId) || !state.nodesById.has(toId)) return null;
    const dist = new Map([[fromId, 0]]);
    const prev = new Map(); // id -> { prevId, edge }
    const visited = new Set();
    const queue = [{ id: fromId, d: 0 }];

    while (queue.length > 0) {
      queue.sort((a, b) => a.d - b.d);
      const cur = queue.shift();
      if (visited.has(cur.id)) continue;
      visited.add(cur.id);
      if (cur.id === toId) break;

      for (const edge of state.allNodeEdges.get(cur.id) || []) {
        if (!state.showConcepts && edge.kind === "concept") continue;
        const nb = edge.source === cur.id ? edge.target : edge.source;
        if (visited.has(nb)) continue;
        let cost = 2.6;
        if (edge.kind === "shared") cost = 1.0 - 0.35 * Math.min(1, edge.strength || 0);
        else if (edge.kind === "concept") cost = 1.35 - 0.25 * Math.min(1, edge.strength || 0);
        const nd = cur.d + cost;
        if (nd < (dist.get(nb) ?? Infinity)) {
          dist.set(nb, nd);
          prev.set(nb, { prevId: cur.id, edge });
          queue.push({ id: nb, d: nd });
        }
      }
    }

    if (!prev.has(toId)) return null;
    const steps = [];
    const nodeIds = new Set();
    const edgeIds = new Set();
    let cur = toId;
    let nextEdge = null;
    while (cur) {
      nodeIds.add(cur);
      steps.unshift({ node: state.nodesById.get(cur), edgeToNext: nextEdge });
      const p = prev.get(cur);
      if (!p) break;
      edgeIds.add(p.edge.id);
      nextEdge = p.edge;
      cur = p.prevId;
    }
    return { fromId, toId, nodeIds, edgeIds, steps };
  }

  function tracePathway(fromId, toId) {
    const res = findShortestPath(fromId, toId);
    if (!res) {
      showToast("No bridge pathway found between those topics.");
      return false;
    }
    hideToast();
    state.focusNodeId = null;
    state.isolatedRootId = null;
    state.pathway = res;
    state.pathPickerOpen = false;
    state.selectedNodeId = fromId;
    state.selectedEdgeId = null;
    buildScene();
    renderInspector();

    // Fit camera to the pathway nodes cleanly
    const items = Array.from(res.nodeIds).map((id) => state.sceneById.get(id)).filter(Boolean);
    if (items.length > 0) {
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity, minZ = Infinity, maxZ = -Infinity;
      for (const it of items) {
        minX = Math.min(minX, it.x - 60); maxX = Math.max(maxX, it.x + 60);
        minY = Math.min(minY, it.y - 60); maxY = Math.max(maxY, it.y + 60);
        minZ = Math.min(minZ, it.z - 60); maxZ = Math.max(maxZ, it.z + 60);
      }
      const dockPad = state.dockOpen ? 242 : 24;
      const insPad = 348;
      const usableW = Math.max(260, state.width - dockPad - insPad);
      const usableH = Math.max(240, state.height - 80);
      const distW = ((Math.max(240, maxX - minX) * 0.55) * FOV) / (usableW * 0.44);
      const distH = ((Math.max(240, maxY - minY) * 0.55) * FOV) / (usableH * 0.45);
      state.targetCam = {
        yaw: state.viewMode === "3d" ? state.cam.yaw : 0,
        pitch: state.viewMode === "3d" ? state.cam.pitch : 0,
        dist: Math.max(380, distW, distH),
        tx: (minX + maxX) / 2,
        ty: (minY + maxY) / 2,
        tz: (minZ + maxZ) / 2,
      };
    }
    requestDraw();
    return true;
  }

  function clearPathway() {
    if (!state.pathway) return;
    hideToast();
    state.pathway = null;
    renderInspector();
    updateChrome();
    requestDraw();
  }

  function nodeMatchesFilter(node) {
    if (state.stateFilter && node.state !== state.stateFilter) return false;
    if (hasActiveOverlays() && getOverlayCount(node.id) === 0) return false;
    if (state.spotlight === "gaps") return node.suspended > 0;
    if (state.spotlight === "weak") return (node.weak_cards || 0) > 0 || node.weak_score > 0.15;
    if (state.spotlight === "recent_7d") return (node.rev_7d || 0) > 0;
    if (state.spotlight === "recent_30d") return (node.rev_30d || 0) > 0;
    return true;
  }

  function nodeVisualColor(node, p) {
    if (hasActiveOverlays() && getOverlayCount(node.id) > 0) return p.overlayColor;
    if (state.spotlight === "weak" && ((node.weak_cards || 0) > 0 || node.weak_score > 0.15)) return p.weakColor;
    if ((state.spotlight === "recent_7d" || state.spotlight === "recent_30d") && ((node.rev_7d || 0) > 0 || (node.rev_30d || 0) > 0)) {
      return p.recentColor;
    }
    return p.states[node.state] || p.states.mature;
  }

  function getScreenCenter() {
    const leftPad = state.dockOpen ? 236 : 12;
    const rightPad = !elInspector.classList.contains("hidden") ? 344 : 12;
    return {
      cx: leftPad + (state.width - leftPad - rightPad) / 2,
      cy: state.height / 2,
    };
  }

  function projectScene() {
    const cosY = Math.cos(state.cam.yaw);
    const sinY = Math.sin(state.cam.yaw);
    const cosP = Math.cos(state.cam.pitch);
    const sinP = Math.sin(state.cam.pitch);
    const { cx, cy } = getScreenCenter();
    const zm = state.zMorph;

    for (const item of state.sceneNodes) {
      const dx = item.x - state.cam.tx;
      const dy = item.y - state.cam.ty;
      const dz = (item.z - state.cam.tz) * zm;

      const x1 = dx * cosY - dz * sinY;
      const z1 = dx * sinY + dz * cosY;
      const y2 = dy * cosP - z1 * sinP;
      const z2 = dy * sinP + z1 * cosP;

      const camZ = state.cam.dist + z2;
      if (camZ < 50) {
        item.visible = false;
        item.camZ = camZ;
        continue;
      }
      const scale = FOV / camZ;
      item.visible = true;
      item.camZ = camZ;
      item.scale = scale;
      item.sx = cx + x1 * scale;
      item.sy = cy + y2 * scale;
      item.drawR = Math.max(1.6, item.baseR * Math.pow(scale, 0.74));
    }
  }

  let drawQueued = false;
  function requestDraw() {
    if (!drawQueued) {
      drawQueued = true;
      requestAnimationFrame(drawFrame);
    }
  }

  function stepAnimation() {
    let keep = false;
    const wantMorph = state.viewMode === "3d" ? 1.0 : 0.0;
    if (Math.abs(state.zMorph - wantMorph) > 0.005) {
      state.zMorph += (wantMorph - state.zMorph) * 0.2;
      keep = true;
    } else {
      state.zMorph = wantMorph;
    }

    if (state.targetCam) {
      const t = state.targetCam;
      const k = 0.2;
      state.cam.yaw += (t.yaw - state.cam.yaw) * k;
      state.cam.pitch += (t.pitch - state.cam.pitch) * k;
      state.cam.dist += (t.dist - state.cam.dist) * k;
      state.cam.tx += (t.tx - state.cam.tx) * k;
      state.cam.ty += (t.ty - state.cam.ty) * k;
      state.cam.tz += (t.tz - state.cam.tz) * k;
      if (
        Math.abs(t.yaw - state.cam.yaw) < 0.003 &&
        Math.abs(t.pitch - state.cam.pitch) < 0.003 &&
        Math.abs(t.dist - state.cam.dist) < 1.5 &&
        Math.abs(t.tx - state.cam.tx) < 0.8 &&
        Math.abs(t.ty - state.cam.ty) < 0.8 &&
        Math.abs(t.tz - state.cam.tz) < 0.8
      ) {
        state.cam = t;
        state.targetCam = null;
      } else {
        keep = true;
      }
    } else if (!state.pointerDown && (Math.abs(state.velYaw) > 0.0004 || Math.abs(state.velPitch) > 0.0004)) {
      state.cam.yaw += state.velYaw;
      state.cam.pitch = Math.max(-1.35, Math.min(1.35, state.cam.pitch + state.velPitch));
      state.velYaw *= 0.88;
      state.velPitch *= 0.88;
      keep = true;
    }

    const activeId = state.hoveredNodeId || state.selectedNodeId;
    if ((activeId || state.pathway) && !window.__atlasNoIdleDrift) {
      state.pulsePhase = (state.pulsePhase + 0.016) % 1.0;
      keep = true;
    } else if (
      state.viewMode === "3d" &&
      !state.pointerDown &&
      !state.targetCam &&
      !activeId &&
      !state.pathway &&
      !window.__atlasNoIdleDrift &&
      Date.now() - state.lastInputTs > 2200
    ) {
      state.cam.yaw += 0.0009;
      keep = true;
    }

    return keep;
  }

  function drawFrame() {
    drawQueued = false;
    if (state.viewMode === "grid") {
      return;
    }
    const keepAnimating = stepAnimation();
    const p = palette();
    const w = state.width;
    const h = state.height;

    projectScene();

    ctx.save();
    ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);

    const bgGrad = ctx.createRadialGradient(w * 0.5, h * 0.48, 30, w * 0.5, h * 0.5, Math.max(w, h) * 0.72);
    bgGrad.addColorStop(0, p.bgTop);
    bgGrad.addColorStop(1, p.bgBottom);
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, w, h);

    const activeFocusId = state.hoveredNodeId || state.selectedNodeId;
    const connectedIds = new Set();
    if (state.pathway) {
      for (const id of state.pathway.nodeIds) connectedIds.add(id);
    } else if (activeFocusId) {
      connectedIds.add(activeFocusId);
      for (const se of state.sceneEdges) {
        if (se.a.node.id === activeFocusId) connectedIds.add(se.b.node.id);
        if (se.b.node.id === activeFocusId) connectedIds.add(se.a.node.id);
      }
    }

    const nearZ = Math.max(80, state.cam.dist - 540);
    const zSpan = 1080;
    function depthFade(camZ) {
      if (state.zMorph < 0.05) return 1.0;
      const t = Math.max(0, Math.min(1, (camZ - nearZ) / zSpan));
      return 1.0 - t * 0.65;
    }

    const macroView = state.cam.dist > 820 && !state.focusNodeId && !state.isolatedRootId && !state.pathway;
    const filterActive = state.spotlight !== "all" || Boolean(state.stateFilter) || hasActiveOverlays() || Boolean(state.searchHighlightIds);

    // 1. Edges
    const activeEdges = [];
    for (const se of state.sceneEdges) {
      const { edge, a, b } = se;
      if (!a.visible || !b.visible) continue;

      const isPathEdge = Boolean(state.pathway && state.pathway.edgeIds.has(edge.id));
      const isSel = state.selectedEdgeId === edge.id || state.hoveredEdgeId === edge.id;
      const touchesActive = !state.pathway && activeFocusId && (a.node.id === activeFocusId || b.node.id === activeFocusId);

      if (macroView && !touchesActive && !isSel && !isPathEdge && edge.kind !== "tree" && edge.level === 3) {
        continue;
      }

      let alpha = 1.0;
      if (state.pathway) {
        alpha = isPathEdge ? 0.96 : 0.03;
      } else if (activeFocusId) {
        alpha = touchesActive || isSel ? 0.92 : 0.035;
      } else if (filterActive) {
        alpha = nodeMatchesFilter(a.node) && nodeMatchesFilter(b.node) ? 0.52 : 0.04;
      } else {
        alpha = depthFade((a.camZ + b.camZ) * 0.5);
      }

      if (alpha <= 0.01) continue;

      if (edge.kind === "tree" && !isPathEdge) {
        se.cx = undefined;
        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.beginPath();
        ctx.moveTo(a.sx, a.sy);
        ctx.lineTo(b.sx, b.sy);
        ctx.strokeStyle = touchesActive ? p.treeEdgeHi : p.treeEdge;
        ctx.lineWidth = touchesActive ? 1.3 : 0.75;
        ctx.stroke();
        ctx.restore();
      } else {
        const mx = (a.sx + b.sx) / 2;
        const my = (a.sy + b.sy) / 2;
        const dx = b.sx - a.sx;
        const dy = b.sy - a.sy;
        const dist = Math.hypot(dx, dy) || 1;
        const bend = edge.kind === "concept" ? -Math.min(40, dist * 0.09) : Math.min(34, dist * 0.075);
        const cx = mx - (dy / dist) * bend;
        const cy = my + (dx / dist) * bend;
        se.cx = cx;
        se.cy = cy;

        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.beginPath();
        ctx.moveTo(a.sx, a.sy);
        ctx.quadraticCurveTo(cx, cy, b.sx, b.sy);
        if (edge.kind === "concept") {
          ctx.setLineDash([4, 4]);
          ctx.strokeStyle = isPathEdge || touchesActive || isSel ? p.conceptEdgeHi : p.conceptEdge;
          ctx.lineWidth = isPathEdge ? 2.2 : touchesActive || isSel ? 1.55 : 0.85;
        } else {
          ctx.strokeStyle = isPathEdge ? p.pathEdge : touchesActive || isSel ? p.sharedEdgeHi : p.sharedEdge;
          ctx.lineWidth = isPathEdge ? 2.4 : touchesActive || isSel ? 1.45 + edge.strength * 1.1 : 0.85;
        }
        ctx.stroke();
        ctx.restore();

        if (isPathEdge || touchesActive || isSel) {
          activeEdges.push(se);
        }
      }
    }

    // Animated photon pulses
    if (activeEdges.length > 0 && (activeFocusId || state.pathway)) {
      ctx.save();
      if (state.dark) ctx.globalCompositeOperation = "lighter";
      for (let i = 0; i < activeEdges.length; i++) {
        const se = activeEdges[i];
        const t = (state.pulsePhase + i * 0.23) % 1.0;
        const u = 1 - t;
        const px = se.cx !== undefined
          ? u * u * se.a.sx + 2 * u * t * se.cx + t * t * se.b.sx
          : se.a.sx + (se.b.sx - se.a.sx) * t;
        const py = se.cx !== undefined
          ? u * u * se.a.sy + 2 * u * t * se.cy + t * t * se.b.sy
          : se.a.sy + (se.b.sy - se.a.sy) * t;
        const col = se.edge.kind === "concept" ? p.conceptEdgeHi : p.sharedEdgeHi;
        ctx.drawImage(getGlowSprite(col), px - 7, py - 7, 14, 14);
      }
      ctx.restore();
    }

    // 2. Depth-sorted Nodes
    const visibleItems = state.sceneNodes.filter(
      (it) => it.visible && it.sx > -60 && it.sx < w + 60 && it.sy > -60 && it.sy < h + 60
    );
    visibleItems.sort((a, b) => b.camZ - a.camZ);

    for (const item of visibleItems) {
      const { node, sx, sy, drawR, camZ } = item;
      const isSel = state.selectedNodeId === node.id;
      const isHov = state.hoveredNodeId === node.id;
      const isConn = (state.pathway || activeFocusId) && connectedIds.has(node.id);

      let alpha = depthFade(camZ);
      if (state.pathway) {
        alpha = connectedIds.has(node.id) ? 1.0 : 0.08;
      } else if (activeFocusId) {
        alpha = isConn ? 1.0 : 0.10;
      } else if (filterActive) {
        const hitSearch = state.searchHighlightIds && state.searchHighlightIds.has(node.id);
        alpha = (nodeMatchesFilter(node) && (!state.searchHighlightIds || hitSearch)) ? Math.max(0.82, alpha) : 0.10;
      }

      const col = nodeVisualColor(node, p);

      if (state.dark && alpha > 0.22) {
        const haloR = drawR * (isSel || isHov ? 4.2 : isConn ? 3.5 : node.level === 1 ? 3.3 : 2.6);
        ctx.save();
        ctx.globalCompositeOperation = "lighter";
        ctx.globalAlpha = alpha * (isSel || isHov ? 0.72 : isConn ? 0.6 : 0.36);
        ctx.drawImage(getGlowSprite(col), sx - haloR, sy - haloR, haloR * 2, haloR * 2);
        ctx.restore();
      }

      ctx.save();
      ctx.globalAlpha = alpha;

      const showFrontier = state.spotlight === "gaps" && node.is_frontier;
      const showOverlayRing = hasActiveOverlays() && getOverlayCount(node.id) > 0;
      const showCbSuspRing = state.colorblind && node.state === "suspended";
      if ((showFrontier || showOverlayRing || showCbSuspRing) && alpha > 0.45) {
        ctx.beginPath();
        ctx.arc(sx, sy, drawR + 3.2, 0, Math.PI * 2);
        ctx.setLineDash(showOverlayRing ? [4, 2] : [3, 2.5]);
        ctx.strokeStyle = showOverlayRing ? p.recentColor : (showFrontier ? p.frontierRing : p.states.suspended);
        ctx.lineWidth = showOverlayRing ? 1.6 : 1.4;
        ctx.stroke();
        ctx.setLineDash([]);
      }

      ctx.beginPath();
      ctx.arc(sx, sy, drawR, 0, Math.PI * 2);
      ctx.fillStyle = col;
      ctx.fill();

      if (isSel || isHov || (state.pathway && connectedIds.has(node.id))) {
        ctx.strokeStyle = p.selectedRing;
        ctx.lineWidth = isSel ? 2.0 : 1.4;
        ctx.stroke();
      }

      ctx.restore();
    }

    // 3. Borderless Collision-Culled Labels
    drawCleanLabels(p, activeFocusId, connectedIds, depthFade);

    ctx.restore();

    if (keepAnimating) requestDraw();
  }

  function drawCleanLabels(p, activeFocusId, connectedIds, depthFade) {
    const placedBoxes = [];

    function intersectsAny(box) {
      for (const b of placedBoxes) {
        if (box.x1 < b.x2 && box.x2 > b.x1 && box.y1 < b.y2 && box.y2 > b.y1) return true;
      }
      return false;
    }

    function tryDrawText(item, opts) {
      if (!item.visible) return false;
      const sx = item.sx;
      const sy = item.sy;
      if (sx < 30 || sx > state.width - 30 || sy < 20 || sy > state.height - 20) return false;

      const text = opts.text;
      const sub = opts.sub || "";
      const fontSize = opts.fontSize;
      const fontWeight = opts.fontWeight || 600;
      ctx.font = `${fontWeight} ${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
      const tw = ctx.measureText(text).width;
      let subW = 0;
      if (sub) {
        ctx.font = `600 ${Math.max(9.5, fontSize - 2)}px -apple-system, sans-serif`;
        subW = ctx.measureText(sub).width;
      }
      const boxW = Math.max(tw, subW) + 8;
      const boxH = fontSize + (sub ? fontSize : 2);
      const topY = opts.above ? sy - item.drawR - boxH - 4 : sy + item.drawR + 5;
      const pad = 7;

      const box = { x1: sx - boxW / 2 - pad, y1: topY - pad, x2: sx + boxW / 2 + pad, y2: topY + boxH + pad };
      if (!opts.force && intersectsAny(box)) return false;
      placedBoxes.push(box);

      ctx.save();
      ctx.globalAlpha = opts.alpha ?? 1.0;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.lineJoin = "round";
      const haloStroke = state.dark ? "rgba(7, 10, 17, 0.9)" : "rgba(248, 250, 255, 0.95)";

      ctx.font = `${fontWeight} ${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
      ctx.strokeStyle = haloStroke;
      ctx.lineWidth = 4;
      ctx.strokeText(text, sx, topY);
      ctx.fillStyle = opts.color || p.text;
      ctx.fillText(text, sx, topY);

      if (sub) {
        ctx.font = `600 ${Math.max(9.5, fontSize - 2)}px -apple-system, sans-serif`;
        ctx.lineWidth = 3.5;
        ctx.strokeText(sub, sx, topY + fontSize + 2);
        ctx.fillStyle = p.textMuted;
        ctx.fillText(sub, sx, topY + fontSize + 2);
      }
      ctx.restore();
      return true;
    }

    // Pathway labels
    if (state.pathway) {
      for (let i = 0; i < state.pathway.steps.length; i++) {
        const st = state.pathway.steps[i];
        const item = state.sceneById.get(st.node.id);
        if (!item) continue;
        tryDrawText(item, {
          text: `${i + 1}. ${trunc(st.node.label, 28)}`,
          fontSize: 11.5,
          fontWeight: 700,
          above: true,
          force: i === 0 || i === state.pathway.steps.length - 1,
        });
      }
      return;
    }

    // Focused / Hovered / Selected / Local Graph: zero unrelated background words
    if (activeFocusId || state.focusNodeId) {
      const centerId = state.hoveredNodeId || state.selectedNodeId || state.focusNodeId;
      const centerItem = state.sceneById.get(centerId);
      if (centerItem) {
        const ovCnt = getOverlayCount(centerItem.node.id);
        const sub = hasActiveOverlays()
          ? `${ovCnt} tagged cards · ${centerItem.node.total} total`
          : `${fmtPct(centerItem.node.learned_pct)} learned · ${centerItem.node.total} cards`;
        tryDrawText(centerItem, {
          text: trunc(centerItem.node.label, 34),
          sub,
          fontSize: 12.5,
          fontWeight: 700,
          above: true,
          force: true,
        });
      }
      const nbItems = state.sceneNodes
        .filter((it) => it.visible && it.node.id !== centerId && connectedIds.has(it.node.id))
        .sort((a, b) => a.camZ - b.camZ || b.node.total - a.node.total);
      let count = 0;
      for (const item of nbItems) {
        if (tryDrawText(item, {
          text: trunc(item.node.label, 28),
          fontSize: 11,
          fontWeight: 600,
        })) {
          count++;
          if (count >= 16 && !state.focusNodeId) break;
        }
      }
      return;
    }

    // Overview & Zoom-in labels
    const dist = state.cam.dist;
    if (dist > 760 && !state.isolatedRootId) {
      const l1Items = state.sceneNodes
        .filter((it) => it.visible && it.node.level === 1)
        .sort((a, b) => a.camZ - b.camZ);
      for (const item of l1Items) {
        const n = item.node;
        const baseAlpha = Math.max(0.42, depthFade(item.camZ));
        let sub = "";
        let hasSpotlightMatch = true;
        if (hasActiveOverlays()) {
          const ovCnt = getOverlayCount(n.id);
          sub = ovCnt > 0 ? `${ovCnt} ${plural(ovCnt, "hit")}` : "";
          hasSpotlightMatch = ovCnt > 0;
        } else if (state.spotlight === "gaps") {
          sub = n.suspended > 0 ? `${n.suspended} susp` : "";
          hasSpotlightMatch = n.suspended > 0;
        } else if (state.spotlight === "weak") {
          const wc = n.weak_cards || 0;
          sub = wc > 0 ? `${wc} weak` : "";
          hasSpotlightMatch = wc > 0;
        } else if (state.spotlight === "recent_7d") {
          const r7 = n.rev_7d || 0;
          sub = r7 > 0 ? `${r7} rev` : "";
          hasSpotlightMatch = r7 > 0;
        } else if (state.spotlight === "recent_30d") {
          const r30 = n.rev_30d || 0;
          sub = r30 > 0 ? `${r30} rev` : "";
          hasSpotlightMatch = r30 > 0;
        }

        tryDrawText(item, {
          text: trunc(n.label, 28),
          sub,
          fontSize: 12,
          fontWeight: 700,
          above: true,
          alpha: hasSpotlightMatch ? baseAlpha : Math.min(baseAlpha, 0.34),
        });
      }
    } else if (dist > 410 || state.isolatedRootId) {
      const l1Items = state.sceneNodes.filter((it) => it.visible && (it.node.level === 1 || it.isExternal)).sort((a, b) => a.camZ - b.camZ);
      for (const item of l1Items) {
        tryDrawText(item, {
          text: item.isExternal ? trunc(item.node.label, 24) : item.node.label.toUpperCase(),
          fontSize: item.isExternal ? 10.5 : 11,
          fontWeight: item.isExternal ? 600 : 700,
          above: true,
          alpha: Math.max(item.isExternal ? 0.65 : 0.45, depthFade(item.camZ) * 0.9),
        });
      }
      const l2Items = state.sceneNodes
        .filter((it) => it.visible && !it.isExternal && it.node.level === 2 && it.camZ < state.cam.dist + 180)
        .sort((a, b) => a.camZ - b.camZ || b.node.total - a.node.total);
      for (const item of l2Items) {
        tryDrawText(item, {
          text: trunc(item.node.label, 26),
          fontSize: 11,
          fontWeight: 600,
          alpha: Math.max(0.38, depthFade(item.camZ)),
        });
      }
    } else {
      const l2Items = state.sceneNodes
        .filter((it) => it.visible && it.node.level === 2 && it.camZ < state.cam.dist + 160)
        .sort((a, b) => a.camZ - b.camZ);
      for (const item of l2Items) {
        tryDrawText(item, {
          text: trunc(item.node.label, 26),
          fontSize: 11.5,
          fontWeight: 700,
          above: true,
          alpha: Math.max(0.45, depthFade(item.camZ)),
        });
      }
      const l3Items = state.sceneNodes
        .filter((it) => it.visible && it.node.level === 3 && it.camZ < state.cam.dist + 110)
        .sort((a, b) => a.camZ - b.camZ || b.node.total - a.node.total);
      for (const item of l3Items) {
        tryDrawText(item, {
          text: trunc(item.node.label, 26),
          fontSize: 10.5,
          fontWeight: 500,
          alpha: Math.max(0.4, depthFade(item.camZ)),
        });
      }
    }
  }

  // --- Hit Testing ---
  function hitNodeScreen(sx, sy) {
    const vis = state.sceneNodes.filter((it) => it.visible);
    vis.sort((a, b) => a.camZ - b.camZ);
    for (const item of vis) {
      const r = Math.max(6, (item.drawR || 4) + 5);
      const dx = sx - item.sx;
      const dy = sy - item.sy;
      if (dx * dx + dy * dy <= r * r) return item;
    }
    return null;
  }

  function distToQuadBezier(px, py, ax, ay, cx, cy, bx, by) {
    let minD2 = Infinity;
    for (let t = 0; t <= 1; t += 0.1) {
      const u = 1 - t;
      const qx = u * u * ax + 2 * u * t * cx + t * t * bx;
      const qy = u * u * ay + 2 * u * t * cy + t * t * by;
      const d2 = (px - qx) * (px - qx) + (py - qy) * (py - qy);
      if (d2 < minD2) minD2 = d2;
    }
    return Math.sqrt(minD2);
  }

  function hitEdgeScreen(sx, sy) {
    const macroView = state.cam.dist > 820 && !state.focusNodeId && !state.isolatedRootId && !state.pathway;
    let best = null;
    let bestDist = 7;
    for (const se of state.sceneEdges) {
      if (se.edge.kind === "tree" || se.cx === undefined) continue;
      if (!se.a.visible || !se.b.visible) continue;
      if (macroView && se.edge.level === 3) continue;
      const d = distToQuadBezier(sx, sy, se.a.sx, se.a.sy, se.cx, se.cy, se.b.sx, se.b.sy);
      if (d < bestDist) {
        bestDist = d;
        best = se;
      }
    }
    return best;
  }

  // --- Inspector ---
  function renderInspector() {
    if (state.pathway) {
      renderPathwayInspector();
      if (elGridView) elGridView.classList.toggle("has-inspector", !elInspector.classList.contains("hidden"));
      return;
    }
    if (state.selectedEdgeId) {
      const se = state.sceneEdges.find((x) => x.edge.id === state.selectedEdgeId);
      if (se) {
        renderEdgeInspector(se.edge);
        if (elGridView) elGridView.classList.toggle("has-inspector", !elInspector.classList.contains("hidden"));
        return;
      }
    }
    if (state.selectedNodeId && state.nodesById.has(state.selectedNodeId)) {
      renderNodeInspector(state.nodesById.get(state.selectedNodeId));
      if (elGridView) elGridView.classList.toggle("has-inspector", !elInspector.classList.contains("hidden"));
      return;
    }
    elInspector.classList.add("hidden");
    if (elGridView) elGridView.classList.remove("has-inspector");
  }

  function renderPathwayInspector() {
    const pw = state.pathway;
    const a = state.nodesById.get(pw.fromId);
    const b = state.nodesById.get(pw.toId);
    if (!a || !b) return;
    elInspector.classList.remove("hidden");
    elInsCrumb.textContent = "Shortest Connection Pathway";
    elInsTitle.textContent = `${a.label} → ${b.label}`;

    const hops = Math.max(0, pw.steps.length - 1);
    const pathQuery = pw.steps.map((s) => `(${s.node.queries.all})`).join(" OR ");

    let html = `
      <div class="headline-row">
        <span class="headline-pct">${hops} ${hops === 1 ? "hop" : "hops"}</span>
        <span class="headline-sub">${pw.steps.length} connected topics</span>
      </div>
      <div class="action-stack">
        <div class="action-row">
          <button class="act-btn primary" id="pw-cram">Cram Pathway Deck</button>
          <button class="act-btn" id="pw-browser">Open All in Browser</button>
        </div>
        <button class="act-btn" id="pw-clear">Clear Pathway (Esc)</button>
      </div>
      <div class="section-hdr">Step-by-Step Chain</div>
      <div class="neighbor-list">
    `;

    for (let i = 0; i < pw.steps.length; i++) {
      const { node, edgeToNext } = pw.steps[i];
      const trail = (node.path || []).slice(0, -1).join(" › ");
      html += `
        <div class="neighbor-row">
          <button class="neighbor-jump" data-jump="${escHtml(node.id)}">
            <div class="neighbor-name">${i + 1}. ${escHtml(node.label)}</div>
            <div class="neighbor-meta">${escHtml(trail || "Subject")} · ${fmtPct(node.learned_pct)} learned</div>
          </button>
          <button class="neighbor-pill" data-browser="${escHtml(node.queries.all)}">Open ↗</button>
        </div>
      `;
      if (edgeToNext) {
        const desc =
          edgeToNext.kind === "shared"
            ? `${edgeToNext.shared} shared cards`
            : edgeToNext.kind === "concept"
            ? `Concepts: ${(edgeToNext.terms || []).join(" · ")}`
            : "Topic hierarchy";
        html += `<div class="path-step-hop"><span>↓ ${escHtml(desc)}</span>`;
        if (edgeToNext.query) {
          html += `<button class="neighbor-pill" data-browser="${escHtml(edgeToNext.query)}">Bridge ↗</button>`;
        }
        html += `</div>`;
      }
    }
    html += `</div>`;
    elInsBody.innerHTML = html;

    elInsBody.querySelector("#pw-clear")?.addEventListener("click", clearPathway);
    elInsBody.querySelector("#pw-browser")?.addEventListener("click", () => sendCmd("atlas:browser:" + pathQuery));
    elInsBody.querySelector("#pw-cram")?.addEventListener("click", () => {
      sendCmd(
        "atlas:cram:" +
          JSON.stringify({
            title: `${a.label} to ${b.label}`,
            query: pathQuery,
            limit: 60,
          })
      );
    });
    for (const btn of elInsBody.querySelectorAll("[data-jump]")) {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-jump");
        state.selectedNodeId = id;
        const it = state.sceneById.get(id);
        if (it) {
          state.targetCam = { ...state.cam, tx: it.x, ty: it.y, tz: it.z, dist: Math.min(state.cam.dist, 420) };
          requestDraw();
        }
      });
    }
    for (const btn of elInsBody.querySelectorAll("[data-browser]")) {
      btn.addEventListener("click", () => sendCmd("atlas:browser:" + btn.getAttribute("data-browser")));
    }
  }

  function renderNodeInspector(node) {
    const p = palette();
    elInspector.classList.remove("hidden");
    elInsTitle.textContent = node.label;

    // Clickable ancestor breadcrumb to step back up effortlessly
    const ancestors = [];
    let curParentId = node.parent_id;
    let safety = 0;
    while (curParentId && state.nodesById.has(curParentId) && safety++ < 6) {
      const anc = state.nodesById.get(curParentId);
      ancestors.unshift(anc);
      curParentId = anc.parent_id;
    }
    if (ancestors.length > 0) {
      elInsCrumb.innerHTML =
        ancestors
          .map((anc) => `<button class="crumb-btn" data-jump="${escHtml(anc.id)}">${escHtml(anc.label)}</button>`)
          .join(`<span class="crumb-sep">&rsaquo;</span>`) +
        `<span class="crumb-sep">&rsaquo;</span><span>${escHtml(node.label)}</span>`;
      for (const btn of elInsCrumb.querySelectorAll("[data-jump]")) {
        btn.addEventListener("click", () => flyToNode(btn.getAttribute("data-jump")));
      }
    } else {
      const taxMode = (state.graph?.summary || {}).taxonomy_mode || "step_subjects";
      elInsCrumb.textContent = taxMode === "step_subjects" ? "Subject" : "Top Topic";
    }

    const tot = Math.max(1, node.total);
    const pMat = (node.mature / tot) * 100;
    const pYng = (node.young / tot) * 100;
    const pNew = (node.new / tot) * 100;
    const pSusp = (node.suspended / tot) * 100;

    let html = `
      <div class="headline-row">
        <span class="headline-pct">${fmtPct(node.learned_pct)} learned</span>
        <span class="headline-sub">${node.total.toLocaleString()} ${plural(node.total, "card")}</span>
      </div>
      <div class="stack-bar" title="Mature / Young / New / Suspended">
        <div class="seg-mature" style="width:${pMat.toFixed(1)}%"></div>
        <div class="seg-young" style="width:${pYng.toFixed(1)}%"></div>
        <div class="seg-new" style="width:${pNew.toFixed(1)}%"></div>
        <div class="seg-susp" style="width:${pSusp.toFixed(1)}%"></div>
      </div>
      <div class="compact-counts">
        ${node.mature.toLocaleString()} mature &middot; ${node.young.toLocaleString()} young &middot; ${node.new.toLocaleString()} new &middot; ${node.suspended.toLocaleString()} suspended
      </div>
    `;

    // Request on-demand deep details (Level 4+ subtags, gap subdecks/tags, sample cards)
    const cachedDetails = state.nodeDetailsCache.get(node.id) || null;
    if (!cachedDetails && !state.nodeDetailsPending.has(node.id)) {
      state.nodeDetailsPending.add(node.id);
      sendCmd(
        "atlas:inspect_node:" +
          JSON.stringify({
            id: node.id,
            query: node.queries.all,
            raw: node.raw || "",
            query_kind: node.query_kind || "tag",
          })
      );
    }

    const children = (node.children || []).map((id) => state.nodesById.get(id)).filter(Boolean);
    const hasChildren = children.length > 0;
    const isFocused = state.focusNodeId === node.id;
    const isIso = state.isolatedRootId === node.id;
    const ovCnt = hasActiveOverlays() ? getOverlayCount(node.id) : 0;
    const wCount = node.weak_cards || node.leech_count || 0;

    // 1 calm primary row: Open Gaps / Open Cards + Cram Deck
    const primaryBtn =
      node.suspended > 0
        ? `<button class="act-btn primary" id="act-susp" title="Open suspended cards under this topic in Anki Browser">Open Gaps (${node.suspended.toLocaleString()})</button>`
        : `<button class="act-btn primary" id="act-all" title="Open all cards under this topic in Anki Browser">Open Cards (${node.total.toLocaleString()})</button>`;

    html += `<div class="action-stack">
      <div class="action-row">
        ${primaryBtn}
        <button class="act-btn" id="act-cram" title="Build a non-rescheduling Filtered Study Deck">Cram Deck</button>
      </div>
    </div>`;

    // Quiet secondary inline links (all cards, weak, optional HY, tagged, canvas focus)
    const qLinks = [];
    if (node.suspended > 0) {
      qLinks.push(`<button type="button" class="ins-link" id="act-all" title="Open all cards under this topic in Browser">All cards (${node.total.toLocaleString()}) &#8599;</button>`);
    }
    if (wCount > 0) {
      qLinks.push(`<button type="button" class="ins-link" id="act-weak" title="Open weak or lapsed cards in Browser">Weak (${wCount.toLocaleString()}) &#8599;</button>`);
    }
    if (node.hy_suspended > 0) {
      qLinks.push(`<button type="button" class="ins-link" id="act-hy" title="Open high-yield suspended cards in Browser">High-Yield (${node.hy_suspended.toLocaleString()}) &#8599;</button>`);
    }
    if (ovCnt > 0) {
      qLinks.push(`<button type="button" class="ins-link active" id="act-ov-open" title="Open matching tagged cards in Browser">${escHtml(getActiveOverlayLabel())} (${ovCnt.toLocaleString()}) &#8599;</button>`);
    }
    if (state.viewMode !== "grid") {
      qLinks.push(
        hasChildren
          ? `<button type="button" class="ins-link" id="act-isolate" title="Show just this topic and its cross-topic bridges">${isIso ? "Show All" : "Isolate Cluster"}</button>`
          : `<button type="button" class="ins-link" id="act-focus" title="Show only nearby connected topics">${isFocused ? "Exit Local" : "Local View"}</button>`
      );
    }
    if (qLinks.length > 0) {
      html += `<div class="ins-quick-links">${qLinks.join("")}</div>`;
    }

    // Collapsed secondary breakdown: where missing / weak cards live by subdeck or tag
    if (cachedDetails && cachedDetails.gap_sources && cachedDetails.gap_sources.length > 0) {
      const srcHeading =
        cachedDetails.gap_mode === "weak"
          ? "Where weak cards live"
          : "Where missing cards live";
      html += `
        <details class="ins-fold">
          <summary>${srcHeading} (${cachedDetails.gap_sources.length})</summary>
          <div class="ins-fold-body">
            <div class="stat-pills" style="margin-bottom:0">
              ${cachedDetails.gap_sources
                .map(
                  (gs) =>
                    `<button class="stat-pill ${cachedDetails.gap_mode === "weak" ? "weak" : "warn"}" data-browser="${escHtml(gs.query)}" title="Open these cards in Anki Browser">${escHtml(gs.label)} (${gs.count}) &#8599;</button>`
                )
                .join("")}
            </div>
          </div>
        </details>
      `;
    }

    // Gather connections upfront for accurate tab counts
    const rawEdges = state.allNodeEdges.get(node.id) || [];
    const sharedNb = [];
    const conceptNb = [];
    for (const edge of rawEdges) {
      if (edge.kind === "tree") continue;
      const otherId = edge.source === node.id ? edge.target : edge.source;
      const other = state.nodesById.get(otherId);
      if (!other) continue;
      if (edge.kind === "shared") sharedNb.push({ edge, other });
      else conceptNb.push({ edge, other });
    }
    sharedNb.sort((a, b) => b.edge.shared - a.edge.shared || b.edge.strength - a.edge.strength);
    conceptNb.sort((a, b) => b.edge.strength - a.edge.strength);
    const connCount = sharedNb.length + conceptNb.length;

    const activeTab = hasChildren
      ? (state.inspectorTab === "connections" ? "connections" : "inside")
      : "connections";

    if (hasChildren) {
      html += `
        <div class="ins-tabs">
          <button class="ins-tab ${activeTab === "inside" ? "active" : ""}" id="ins-tab-inside">Subtopics (${children.length})</button>
          <button class="ins-tab ${activeTab === "connections" ? "active" : ""}" id="ins-tab-conn">Connections (${connCount})</button>
        </div>
      `;
    }

    const renderDrillRow = (ch, subLabel, browserQuery) => {
      const chCol = p.states[ch.state] || p.states.mature;
      const cTot = Math.max(1, ch.total);
      const wMat = (ch.mature / cTot) * 100;
      const wYng = (ch.young / cTot) * 100;
      const wNew = (ch.new / cTot) * 100;
      const wSusp = (ch.suspended / cTot) * 100;
      let badgeCls = "drill-badge ok";
      let badgeTxt = `${fmtPct(ch.learned_pct)}`;
      if (ch.suspended > 0) {
        badgeCls = "drill-badge";
        badgeTxt = `${ch.suspended} susp`;
      } else if (ch.weak_cards > 0) {
        badgeCls = "drill-badge";
        badgeTxt = `${ch.weak_cards} weak`;
      }
      const qOpen = browserQuery || (ch.suspended > 0 ? ch.queries.suspended : ch.queries.all);
      const qTitle = ch.suspended > 0 ? "Open suspended gap cards in Browser" : "Open cards in Browser";
      return `
        <div class="drill-row">
          <button class="neighbor-jump" data-drill="${escHtml(ch.id)}">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:6px">
              <span class="neighbor-name" style="display:flex;align-items:center;gap:6px;min-width:0">
                <i class="lg-dot" style="background:${chCol};flex-shrink:0"></i>
                <span style="overflow:hidden;text-overflow:ellipsis">${escHtml(ch.label)}</span>
              </span>
              <span class="${badgeCls}">${escHtml(badgeTxt)}</span>
            </div>
            ${subLabel ? `<div class="neighbor-meta">${escHtml(subLabel)}</div>` : ""}
            <div class="drill-bar">
              <div class="seg-mature" style="width:${wMat.toFixed(1)}%"></div>
              <div class="seg-young" style="width:${wYng.toFixed(1)}%"></div>
              <div class="seg-new" style="width:${wNew.toFixed(1)}%"></div>
              <div class="seg-susp" style="width:${wSusp.toFixed(1)}%"></div>
            </div>
          </button>
          <button class="neighbor-pill" data-browser="${escHtml(qOpen)}" title="${qTitle}">&#8599;</button>
        </div>
      `;
    };

    if (activeTab === "inside") {
      const sortedChildren = [...children].sort(
        (a, b) =>
          (b.suspended - a.suspended) ||
          ((b.weak_cards || 0) - (a.weak_cards || 0)) ||
          a.learned_pct - b.learned_pct ||
          b.total - a.total
      );
      html += `<div class="neighbor-list">`;
      for (const ch of sortedChildren) {
        const kidCount = (ch.children || []).length;
        const metaParts = [`${ch.total.toLocaleString()} ${plural(ch.total, "card")}`, `${fmtPct(ch.learned_pct)} learned`];
        if (kidCount > 0) metaParts.push(`${kidCount} ${plural(kidCount, "topic")}`);
        html += renderDrillRow(ch, metaParts.join(" · "), ch.suspended > 0 ? ch.queries.suspended : ch.queries.all);
      }
      html += `</div>`;
    } else {
      // Deep Level 4+ sub-tags & collapsed sample card previews for leaf topics
      if (!hasChildren) {
        if (!cachedDetails && state.nodeDetailsPending.has(node.id)) {
          html += `<div class="headline-sub" style="margin:6px 0 8px">Loading deeper tags &amp; sample cards…</div>`;
        } else if (cachedDetails) {
          if (cachedDetails.subtags && cachedDetails.subtags.length > 0) {
            html += `<div class="section-hdr">Specific Tags Inside (${cachedDetails.subtags.length})</div><div class="neighbor-list">`;
            for (const st of cachedDetails.subtags) {
              const stCol = st.suspended >= st.total * 0.7 ? p.states.suspended : (st.learned_pct >= 0.7 ? p.states.mature : p.states.mixed);
              const badge = st.suspended > 0 ? `${st.suspended} susp` : `${fmtPct(st.learned_pct)}`;
              html += `
                <div class="drill-row">
                  <div style="min-width:0;flex:1">
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:6px">
                      <span class="neighbor-name" style="display:flex;align-items:center;gap:6px;min-width:0">
                        <i class="lg-dot" style="background:${stCol};flex-shrink:0"></i>
                        <span style="overflow:hidden;text-overflow:ellipsis">${escHtml(st.label)}</span>
                      </span>
                      <span class="drill-badge ${st.suspended > 0 ? "" : "ok"}">${escHtml(badge)}</span>
                    </div>
                    <div class="neighbor-meta">${st.total.toLocaleString()} ${plural(st.total, "card")} &middot; ${fmtPct(st.learned_pct)} learned</div>
                  </div>
                  <button class="neighbor-pill" data-browser="${escHtml(st.query)}" title="Open this deep tag in Browser">&#8599;</button>
                </div>
              `;
            }
            html += `</div>`;
          }
          if (cachedDetails.cards && cachedDetails.cards.length > 0) {
            html += `
              <details class="ins-fold">
                <summary>Sample Cards (${cachedDetails.cards.length}${cachedDetails.total_notes > cachedDetails.cards.length ? ` of ${cachedDetails.total_notes.toLocaleString()} notes` : ""})</summary>
                <div class="ins-fold-body">
                  <div class="neighbor-list">
                    ${cachedDetails.cards.slice(0, 8).map((crd) => {
                      const cCol = p.states[crd.state] || p.states.mature;
                      return `
                        <div class="card-preview-row">
                          <span class="lg-dot" style="background:${cCol}"></span>
                          <span class="card-snippet">${escHtml(crd.text)}</span>
                          <span class="card-state-tag">${escHtml(crd.state)}</span>
                          <button class="neighbor-pill" data-browser="${escHtml(crd.query)}" title="Open this card in Browser">&#8599;</button>
                        </div>
                      `;
                    }).join("")}
                  </div>
                </div>
              </details>
            `;
          }
        }
      }

      html += `<div class="action-stack" style="margin-top:8px">
        <div class="action-row${hasChildren ? "" : "-1"}" ${hasChildren ? "" : 'style="display:grid;grid-template-columns:1fr"'}>
          <button class="act-btn" id="act-trace">Trace Path To…</button>
          ${hasChildren
            ? `<button class="act-btn" id="act-focus">${isFocused ? "Exit Local (Esc)" : "Local Graph (F)"}</button>`
            : ""}
        </div>
      </div>`;

      if (state.pathPickerOpen) {
        html += `
          <div class="path-picker">
            <input id="path-dest-input" type="search" placeholder="Trace path from ${escHtml(node.label)} to..." autocomplete="off" />
            <div id="path-hits" class="path-hits"></div>
          </div>
        `;
      }

      if (sharedNb.length > 0) {
        html += `<div class="section-hdr">Shared-Card Bridges (${sharedNb.length})</div><div class="neighbor-list">`;
        for (const { edge, other } of sharedNb.slice(0, 18)) {
          const parentTrail = (other.path || []).slice(0, -1).join(" › ");
          html += `
            <div class="neighbor-row">
              <button class="neighbor-jump" data-jump="${escHtml(other.id)}">
                <div class="neighbor-name">${escHtml(other.label)}</div>
                <div class="neighbor-meta">${escHtml(parentTrail || "Top Topic")} · ${fmtPct(other.learned_pct)} learned</div>
              </button>
              <button class="neighbor-pill" data-browser="${escHtml(edge.query)}" title="Open bridging cards in Browser">${edge.shared} cards &#8599;</button>
            </div>
          `;
        }
        html += `</div>`;
      }

      if (conceptNb.length > 0) {
        html += `<div class="section-hdr">Related Concepts (${conceptNb.length})</div><div class="neighbor-list">`;
        for (const { edge, other } of conceptNb.slice(0, 14)) {
          const parentTrail = (other.path || []).slice(0, -1).join(" › ");
          const terms = (edge.terms || []).join(" · ");
          const metaLine = [parentTrail, terms, fmtPct(other.learned_pct)].filter(Boolean).join(" · ");
          html += `
            <div class="neighbor-row">
              <button class="neighbor-jump" data-jump="${escHtml(other.id)}">
                <div class="neighbor-name">${escHtml(other.label)}</div>
                <div class="neighbor-meta">${escHtml(metaLine)}</div>
              </button>
              <span class="neighbor-pill" style="cursor:default">${Math.round(edge.strength * 100)}%</span>
            </div>
          `;
        }
        html += `</div>`;
      }

      if (connCount === 0 && !state.pathPickerOpen) {
        html += `<div class="headline-sub" style="margin-top:8px">No cross-topic bridges connected to this node yet.</div>`;
      }
    }

    elInsBody.innerHTML = html;

    elInsBody.querySelector("#ins-tab-inside")?.addEventListener("click", () => {
      state.inspectorTab = "inside";
      state.pathPickerOpen = false;
      renderNodeInspector(node);
    });
    elInsBody.querySelector("#ins-tab-conn")?.addEventListener("click", () => {
      state.inspectorTab = "connections";
      renderNodeInspector(node);
    });
    elInsBody.querySelector("#act-focus")?.addEventListener("click", () => {
      if (state.focusNodeId === node.id) exitFocus();
      else enterFocus(node.id);
    });
    elInsBody.querySelector("#act-isolate")?.addEventListener("click", () => {
      if (state.isolatedRootId === node.id) clearIsolation();
      else isolateCluster(node.id);
    });
    elInsBody.querySelector("#act-trace")?.addEventListener("click", () => {
      state.pathPickerOpen = !state.pathPickerOpen;
      state.inspectorTab = "connections";
      renderInspector();
      elInsBody.querySelector("#path-dest-input")?.focus();
    });
    elInsBody.querySelector("#act-all")?.addEventListener("click", () => sendCmd("atlas:browser:" + node.queries.all));
    elInsBody.querySelector("#act-susp")?.addEventListener("click", () => sendCmd("atlas:browser:" + node.queries.suspended));
    elInsBody.querySelector("#act-hy")?.addEventListener("click", () => sendCmd("atlas:browser:" + node.queries.hy_suspended));
    elInsBody.querySelector("#act-weak")?.addEventListener("click", () => sendCmd("atlas:browser:" + node.queries.weak));
    elInsBody.querySelector("#act-ov-open")?.addEventListener("click", () => {
      if (hasActiveOverlays()) sendCmd("atlas:browser:" + getActiveOverlayQuery(node.queries.all));
    });
    elInsBody.querySelector("#act-cram")?.addEventListener("click", () => {
      let query = node.queries.all;
      let title = node.label;
      if (hasActiveOverlays() && ovCnt > 0) {
        query = getActiveOverlayQuery(node.queries.all);
        title = `${node.label} (${getActiveOverlayLabel()})`;
      } else if (state.spotlight === "weak" && node.weak_cards > 0) {
        query = node.queries.weak;
        title = `${node.label} (Weak)`;
      }
      sendCmd("atlas:cram:" + JSON.stringify({ title, query, limit: 50 }));
    });

    const pathInput = elInsBody.querySelector("#path-dest-input");
    const pathHits = elInsBody.querySelector("#path-hits");
    if (pathInput && pathHits && state.graph) {
      const renderHits = (qStr) => {
        const q = qStr.trim().toLowerCase();
        const cands = [];
        for (const n of state.graph.nodes) {
          if (n.id === node.id) continue;
          if (!q || n.label.toLowerCase().includes(q)) {
            cands.push(n);
          }
        }
        cands.sort((a, b) => b.level - a.level || b.total - a.total);
        const top = cands.slice(0, 10);
        pathHits.innerHTML = top
          .map(
            (n) => `
            <button class="search-item" data-path-to="${escHtml(n.id)}">
              <div class="search-item-main">
                <div class="search-item-title">${escHtml(n.label)}</div>
                <div class="search-item-path">${escHtml((n.path || []).slice(0, -1).join(" › ") || "Top Topic")}</div>
              </div>
            </button>
          `
          )
          .join("");
        for (const btn of pathHits.querySelectorAll("[data-path-to]")) {
          btn.addEventListener("click", () => tracePathway(node.id, btn.getAttribute("data-path-to")));
        }
      };
      pathInput.addEventListener("input", () => renderHits(pathInput.value));
      renderHits("");
    }

    for (const btn of elInsBody.querySelectorAll("[data-drill], [data-jump]")) {
      const tid = btn.getAttribute("data-drill") || btn.getAttribute("data-jump");
      btn.addEventListener("click", () => flyToNode(tid));
    }
    for (const btn of elInsBody.querySelectorAll("[data-browser]")) {
      btn.addEventListener("click", () => sendCmd("atlas:browser:" + btn.getAttribute("data-browser")));
    }
  }

  function renderEdgeInspector(edge) {
    const a = state.nodesById.get(edge.source);
    const b = state.nodesById.get(edge.target);
    if (!a || !b) return;
    elInspector.classList.remove("hidden");
    elInsCrumb.textContent = edge.kind === "shared" ? "Shared-Card Bridge" : "Related Concepts (TF-IDF)";
    elInsTitle.textContent = `${a.label} ↔ ${b.label}`;

    let html = "";
    if (edge.kind === "shared") {
      html += `
        <div class="headline-row">
          <span class="headline-pct">${edge.shared.toLocaleString()} cards</span>
          <span class="headline-sub">shared between both topics</span>
        </div>
      `;
      if (edge.query) {
        html += `<div class="action-stack">
          <button class="act-btn primary" id="edge-open-cards">Open Bridging Cards in Browser</button>
        </div>`;
      }
    } else {
      const terms = (edge.terms || []).map((t) => `<span class="chip-btn" style="cursor:default">${escHtml(t)}</span>`).join("");
      html += `
        <div class="headline-row">
          <span class="headline-pct">${Math.round(edge.strength * 100)}% match</span>
          <span class="headline-sub">shared card terms</span>
        </div>
        <div class="chip-row" style="margin-bottom:14px">${terms}</div>
      `;
    }

    html += `<div class="section-hdr">Connected Topics</div><div class="neighbor-list">`;
    for (const n of [a, b]) {
      html += `
        <div class="neighbor-row">
          <button class="neighbor-jump" data-jump="${escHtml(n.id)}">
            <div class="neighbor-name">${escHtml(n.label)}</div>
            <div class="neighbor-meta">${escHtml((n.path || []).join(" › "))} · ${fmtPct(n.learned_pct)} learned</div>
          </button>
          <button class="neighbor-pill" data-browser="${escHtml(n.queries.all)}">Open &#8599;</button>
        </div>
      `;
    }
    html += `</div>`;

    elInsBody.innerHTML = html;
    elInsBody.querySelector("#edge-open-cards")?.addEventListener("click", () => {
      sendCmd("atlas:browser:" + edge.query);
    });
    for (const btn of elInsBody.querySelectorAll("[data-jump]")) {
      btn.addEventListener("click", () => flyToNode(btn.getAttribute("data-jump")));
    }
    for (const btn of elInsBody.querySelectorAll("[data-browser]")) {
      btn.addEventListener("click", () => sendCmd("atlas:browser:" + btn.getAttribute("data-browser")));
    }
  }

  // --- Mouse / Wheel / Keyboard ---
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());

  canvas.addEventListener("mousedown", (e) => {
    state.lastInputTs = Date.now();
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    state.pointerDown = true;
    state.dragMoved = false;
    state.lastMouse = { x: sx, y: sy };
    state.downMouse = { x: sx, y: sy };
    state.targetCam = null;
    state.velYaw = 0;
    state.velPitch = 0;

    const hit = hitNodeScreen(sx, sy);
    if (hit && e.button === 0 && !e.shiftKey) {
      state.dragNode = hit;
      state.dragMode = "node";
    } else {
      state.dragNode = null;
      state.dragMode = state.viewMode === "2d" || e.button === 2 || e.shiftKey ? "pan" : "orbit";
      canvas.classList.add("dragging");
    }
  });

  window.addEventListener("mousemove", (e) => {
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    if (state.pointerDown) {
      state.lastInputTs = Date.now();
      const dx = sx - state.lastMouse.x;
      const dy = sy - state.lastMouse.y;
      if (Math.hypot(sx - state.downMouse.x, sy - state.downMouse.y) > 4) state.dragMoved = true;

      if (state.dragMode === "node" && state.dragNode) {
        const s = state.dragNode.scale || 1;
        const cosY = Math.cos(state.cam.yaw);
        const sinY = Math.sin(state.cam.yaw);
        const wdx = dx / s;
        const wdy = dy / s;
        state.dragNode.x += wdx * cosY;
        state.dragNode.z -= wdx * sinY;
        state.dragNode.y += wdy;
      } else if (state.dragMode === "pan") {
        const panScale = state.cam.dist / FOV;
        const cosY = Math.cos(state.cam.yaw);
        const sinY = Math.sin(state.cam.yaw);
        const wdx = dx * panScale;
        const wdy = dy * panScale;
        state.cam.tx -= wdx * cosY;
        state.cam.tz += wdx * sinY;
        state.cam.ty -= wdy;
      } else {
        const dYaw = dx * 0.0055;
        const dPitch = dy * 0.0055;
        state.cam.yaw += dYaw;
        state.cam.pitch = Math.max(-1.35, Math.min(1.35, state.cam.pitch + dPitch));
        state.velYaw = dYaw * 0.65;
        state.velPitch = dPitch * 0.65;
      }
      state.lastMouse = { x: sx, y: sy };
      elHoverTip.classList.add("hidden");
      requestDraw();
      return;
    }

    if (e.target !== canvas) {
      if (state.hoveredNodeId || state.hoveredEdgeId) {
        state.hoveredNodeId = null;
        state.hoveredEdgeId = null;
        elHoverTip.classList.add("hidden");
        requestDraw();
      }
      return;
    }

    const hn = hitNodeScreen(sx, sy);
    const he = hn ? null : hitEdgeScreen(sx, sy);
    const newHovNode = hn ? hn.node.id : null;
    const newHovEdge = he ? he.edge.id : null;
    canvas.classList.toggle("pointer", Boolean(hn || he));

    if (newHovNode !== state.hoveredNodeId || newHovEdge !== state.hoveredEdgeId) {
      state.hoveredNodeId = newHovNode;
      state.hoveredEdgeId = newHovEdge;
      requestDraw();
    }

    if (hn) {
      const n = hn.node;
      const ovCnt = hasActiveOverlays() ? getOverlayCount(n.id) : 0;
      const ovLine = ovCnt > 0 ? `<br><span style="color:var(--c-overlay)">${escHtml(getActiveOverlayLabel())}: ${ovCnt} cards</span>` : "";
      elHoverTip.innerHTML =
        `<b>${escHtml(n.label)}</b><br>` +
        `<span style="color:var(--text-muted)">${fmtPct(n.learned_pct)} learned · ${n.mature} mat · ${n.young} yng · ${n.suspended} susp</span>${ovLine}`;
      elHoverTip.style.left = Math.min(state.width - 270, sx + 14) + "px";
      elHoverTip.style.top = Math.min(state.height - 70, sy + 14) + "px";
      elHoverTip.classList.remove("hidden");
    } else if (he) {
      const ed = he.edge;
      elHoverTip.textContent = ed.kind === "shared" ? `${ed.shared} shared cards` : `Concepts: ${(ed.terms || []).join(" · ")}`;
      elHoverTip.style.left = Math.min(state.width - 240, sx + 14) + "px";
      elHoverTip.style.top = Math.min(state.height - 50, sy + 14) + "px";
      elHoverTip.classList.remove("hidden");
    } else {
      elHoverTip.classList.add("hidden");
    }
  });

  window.addEventListener("mouseup", (e) => {
    if (!state.pointerDown) return;
    const wasMoved = state.dragMoved;
    state.pointerDown = false;
    state.dragNode = null;
    canvas.classList.remove("dragging");

    if (wasMoved || e.target !== canvas) return;
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const hn = hitNodeScreen(sx, sy);
    if (hn) {
      if (state.pathway) state.pathway = null;
      state.selectedNodeId = hn.node.id;
      state.selectedEdgeId = null;
      state.pathPickerOpen = false;
      renderInspector();
      renderDock();
      requestDraw();
      return;
    }
    const he = hitEdgeScreen(sx, sy);
    if (he) {
      if (state.pathway) state.pathway = null;
      state.selectedEdgeId = he.edge.id;
      state.selectedNodeId = null;
      renderInspector();
      requestDraw();
      return;
    }
    if (!state.pathway) {
      state.selectedNodeId = null;
      state.selectedEdgeId = null;
      renderInspector();
      renderDock();
      requestDraw();
    }
  });

  canvas.addEventListener("dblclick", (e) => {
    const rect = canvas.getBoundingClientRect();
    const hn = hitNodeScreen(e.clientX - rect.left, e.clientY - rect.top);
    if (!hn) return;
    if (state.focusNodeId) enterFocus(hn.node.id);
    else flyToNode(hn.node.id);
  });

  canvas.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      state.lastInputTs = Date.now();
      state.targetCam = null;
      const factor = Math.exp(e.deltaY * 0.0014);
      state.cam.dist = Math.max(120, Math.min(3600, state.cam.dist * factor));
      requestDraw();
    },
    { passive: false }
  );

  // --- Controls ---
  elDeckSelect.addEventListener("change", () => {
    const activeExam = elExamBtns.find((b) => b.classList.contains("active"))?.dataset.exam || "all";
    elDeckSelect.blur();
    sendCmd("atlas:filter:" + JSON.stringify({ deck_filter: elDeckSelect.value, exam_scope: activeExam }));
  });

  for (const btn of elExamBtns) {
    btn.addEventListener("click", () => {
      for (const b of elExamBtns) b.classList.remove("active");
      btn.classList.add("active");
      sendCmd("atlas:filter:" + JSON.stringify({ deck_filter: elDeckSelect.value, exam_scope: btn.dataset.exam }));
    });
  }

  function setViewMode(mode) {
    state.viewMode = mode === "grid" || mode === "2d" || mode === "3d" ? mode : "grid";
    if (state.viewMode !== "grid") {
      state.targetCam = {
        yaw: state.viewMode === "3d" ? (state.cam.yaw || 0.26) : 0,
        pitch: state.viewMode === "3d" ? (state.cam.pitch || 0.18) : 0,
        dist: state.cam.dist,
        tx: state.cam.tx,
        ty: state.cam.ty,
        tz: state.cam.tz,
      };
    }
    savePrefs();
    updateChrome();
    if (state.viewMode !== "grid") requestDraw();
  }

  for (const btn of elViewBtns) {
    btn.addEventListener("click", () => setViewMode(btn.dataset.view));
  }

  if (elCbBtn) {
    elCbBtn.addEventListener("click", () => {
      applyColorblind(!state.colorblind);
      savePrefs();
    });
  }

  elSpotlightSelect.addEventListener("change", () => {
    state.spotlight = elSpotlightSelect.value || "all";
    if (state.spotlight !== "all") state.dockTab = "priority";
    elSpotlightSelect.blur();
    savePrefs();
    updateChrome();
    requestDraw();
  });

  function renderOverlayPanel() {
    if (!elOverlayPanel || !elOverlayWrap) return;
    const overlays = Array.from(state.overlaysById.values());
    elOverlayWrap.classList.toggle("hidden", overlays.length === 0);
    if (!overlays.length) {
      state.overlayMenuOpen = false;
      elOverlayPanel.classList.add("hidden");
      elOverlayPanel.innerHTML = "";
      return;
    }

    const subOpts = [];
    const resOpts = [];
    for (const ov of overlays) {
      const checked = state.activeOverlayIds.has(ov.id);
      const rowHtml = `
        <label class="ov-check-row">
          <span class="ov-check-left">
            <input type="checkbox" class="ov-checkbox" data-ov-id="${escHtml(ov.id)}" ${checked ? "checked" : ""} />
            <span class="ov-check-lbl">${escHtml(ov.label)}</span>
          </span>
          <span class="ov-cnt">${ov.total_cards.toLocaleString()}</span>
        </label>
      `;
      if (ov.group === "subdeck") subOpts.push(rowHtml);
      else resOpts.push(rowHtml);
    }

    let html = `
      <div class="ov-panel-head">
        <span>Highlight Tags</span>
        <button type="button" class="ins-link ${state.activeOverlayIds.size > 0 ? "" : "hidden"}" id="btn-overlay-clear">Clear</button>
      </div>
    `;
    if (subOpts.length) html += `<div class="ov-group-hdr">Subdecks</div>${subOpts.join("")}`;
    if (resOpts.length) html += `<div class="ov-group-hdr">Tags &amp; Resources</div>${resOpts.join("")}`;
    elOverlayPanel.innerHTML = html;

    const clearBtn = elOverlayPanel.querySelector("#btn-overlay-clear");
    clearBtn?.addEventListener("click", (e) => {
      e.stopPropagation();
      state.activeOverlayIds.clear();
      for (const cb of elOverlayPanel.querySelectorAll(".ov-checkbox")) cb.checked = false;
      clearBtn.classList.add("hidden");
      updateChrome();
      renderInspector();
      requestDraw();
    });

    for (const cb of elOverlayPanel.querySelectorAll(".ov-checkbox")) {
      cb.addEventListener("change", () => {
        const oid = cb.getAttribute("data-ov-id");
        if (!oid) return;
        if (cb.checked) state.activeOverlayIds.add(oid);
        else state.activeOverlayIds.delete(oid);
        if (state.activeOverlayIds.size > 0) state.dockTab = "priority";
        if (clearBtn) clearBtn.classList.toggle("hidden", state.activeOverlayIds.size === 0);
        updateChrome();
        renderInspector();
        requestDraw();
      });
    }
  }

  if (elOverlayBtn && elOverlayPanel) {
    elOverlayBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      state.overlayMenuOpen = !state.overlayMenuOpen;
      if (state.overlayMenuOpen) renderOverlayPanel();
      elOverlayPanel.classList.toggle("hidden", !state.overlayMenuOpen);
    });
  }

  elConceptBtn.addEventListener("click", () => {
    state.showConcepts = !state.showConcepts;
    elConceptBtn.classList.toggle("active", state.showConcepts);
    savePrefs();
    buildScene();
    requestDraw();
  });

  elTabSubjects.addEventListener("click", () => {
    state.dockTab = "subjects";
    renderDock();
  });

  elTabPriority.addEventListener("click", () => {
    state.dockTab = "priority";
    renderDock();
  });

  elHop1Btn.addEventListener("click", () => {
    state.localHops = 1;
    buildScene();
    fitCamera(false);
  });

  elHop2Btn.addEventListener("click", () => {
    state.localHops = 2;
    buildScene();
    fitCamera(false);
  });

  elExitFocus.addEventListener("click", () => {
    if (state.pathway) clearPathway();
    else if (state.focusNodeId) exitFocus();
    else if (state.isolatedRootId) clearIsolation();
  });

  for (const chip of elStateChips) {
    chip.addEventListener("click", () => {
      const s = chip.dataset.state;
      state.stateFilter = state.stateFilter === s ? null : s;
      updateChrome();
      requestDraw();
    });
  }

  elDockToggle.addEventListener("click", () => {
    state.dockOpen = false;
    elSubjectDock.classList.add("hidden");
    elDockOpen.classList.remove("hidden");
    if (elGridView) elGridView.classList.remove("has-dock");
    requestDraw();
  });

  elDockOpen.addEventListener("click", () => {
    state.dockOpen = true;
    elSubjectDock.classList.remove("hidden");
    elDockOpen.classList.add("hidden");
    if (elGridView) elGridView.classList.add("has-dock");
    requestDraw();
  });

  elFitBtn.addEventListener("click", () => fitCamera(false));
  elRefreshBtn.addEventListener("click", () => sendCmd("atlas:refresh"));
  elInsClose.addEventListener("click", () => {
    if (state.pathway) state.pathway = null;
    state.selectedNodeId = null;
    state.selectedEdgeId = null;
    state.pathPickerOpen = false;
    renderInspector();
    updateChrome();
    requestDraw();
  });

  function renderSearchPopup() {
    const rawQ = elSearch.value.trim();
    const q = rawQ.toLowerCase();
    if (!q || !state.graph) {
      elSearchResults.classList.add("hidden");
      return;
    }
    const p = palette();

    // Instant local node matches
    const localMatches = [];
    for (const n of state.graph.nodes) {
      const labelLow = n.label.toLowerCase();
      if (labelLow.includes(q)) {
        const starts = labelLow.startsWith(q) ? 2 : 1;
        localMatches.push({ score: starts * 10 + n.level, node: n });
      }
    }
    localMatches.sort((a, b) => b.score - a.score || b.node.total - a.node.total);
    const localTop = localMatches.slice(0, 8);

    const remote =
      state.lastRemoteSearch && state.lastRemoteSearch.query.toLowerCase() === q
        ? state.lastRemoteSearch
        : null;

    let html = "";
    const allHitIds = new Set(localTop.map((m) => m.node.id));
    if (remote && remote.topics) {
      for (const tp of remote.topics) allHitIds.add(tp.id);
    }

    if (remote) {
      const totalLabel = `${remote.total_notes.toLocaleString()} matching ${plural(remote.total_notes, "note")}`;
      html += `
        <div class="search-top-bar">
          <span>${totalLabel}</span>
          <div style="display:flex;gap:4px">
            ${allHitIds.size > 0 ? `<button class="neighbor-pill" id="sr-highlight">Highlight on Map</button>` : ""}
            ${remote.total_notes > 0 ? `<button class="neighbor-pill" data-browser="${escHtml(remote.browser_query)}">Browser &#8599;</button>` : ""}
          </div>
        </div>
      `;
    } else if (q.length >= 2) {
      html += `<div class="search-top-bar"><span>Searching all cards &amp; tags…</span></div>`;
    }

    if (remote && remote.subtags && remote.subtags.length > 0) {
      html += `<div class="search-section-hdr">Deep Tags (${remote.subtags.length})</div>`;
      for (const st of remote.subtags.slice(0, 4)) {
        const stCol = st.suspended > 0 ? p.states.suspended : p.states.mature;
        html += `
          <div class="search-item" style="padding:5px 7px">
            <button class="neighbor-jump" ${st.node_id ? `data-jump="${escHtml(st.node_id)}"` : `data-browser="${escHtml(st.query)}"`}>
              <div class="search-item-title">${escHtml(st.label)}</div>
              <div class="search-item-path">${escHtml(st.trail || "Tag")} &middot; ${st.hits} ${plural(st.hits, "note")}${st.suspended ? ` (${st.suspended} susp)` : ""}</div>
            </button>
            <button class="neighbor-pill" data-browser="${escHtml(st.query)}" title="Open tag in Browser">&#8599;</button>
            <span class="search-dot" style="background:${stCol}"></span>
          </div>
        `;
      }
    }

    // Merge remote topics + local matches without duplicates
    const topicRows = [];
    const seenTopicIds = new Set();
    const maxTopics = remote && (remote.subtags?.length || remote.cards?.length) ? 4 : 12;
    for (const m of localTop.slice(0, maxTopics)) {
      seenTopicIds.add(m.node.id);
      topicRows.push({ node: m.node, sub: `${m.node.total} cards (${fmtPct(m.node.learned_pct)})` });
    }
    if (remote && remote.topics) {
      for (const tp of remote.topics) {
        if (topicRows.length >= maxTopics) break;
        if (seenTopicIds.has(tp.id)) continue;
        const node = state.nodesById.get(tp.id);
        if (!node) continue;
        seenTopicIds.add(tp.id);
        topicRows.push({
          node,
          sub: `${tp.hits} matching ${plural(tp.hits, "note")}${tp.suspended ? ` · ${tp.suspended} susp` : ""}`,
        });
      }
    }

    if (topicRows.length > 0) {
      html += `<div class="search-section-hdr">Topics (${topicRows.length})</div>`;
      for (const { node, sub } of topicRows) {
        const path = (node.path || []).slice(0, -1).join(" › ") || "Top Topic";
        const dotCol = p.states[node.state] || p.states.mature;
        html += `
          <button class="search-item" data-jump="${escHtml(node.id)}">
            <div class="search-item-main">
              <div class="search-item-title">${escHtml(node.label)}</div>
              <div class="search-item-path">${escHtml(path)} · ${escHtml(sub)}</div>
            </div>
            <span class="search-dot" style="background:${dotCol}"></span>
          </button>
        `;
      }
    }

    if (remote && remote.cards && remote.cards.length > 0) {
      html += `<div class="search-section-hdr">Matching Cards (${remote.cards.length})</div>`;
      for (const crd of remote.cards.slice(0, 4)) {
        const cCol = p.states[crd.state] || p.states.mature;
        html += `
          <div class="search-item" style="padding:5px 7px">
            <button class="neighbor-jump" ${crd.node_id ? `data-jump="${escHtml(crd.node_id)}"` : `data-browser="${escHtml(crd.query)}"`}>
              <div class="search-item-path" style="color:var(--text);white-space:normal">${escHtml(crd.text)}</div>
            </button>
            <button class="neighbor-pill" data-browser="${escHtml(crd.query)}" title="Open card in Browser">&#8599;</button>
            <span class="search-dot" style="background:${cCol}"></span>
          </div>
        `;
      }
    }

    if (!html || (topicRows.length === 0 && (!remote || (!remote.subtags.length && !remote.cards.length)))) {
      if (remote || q.length < 2) {
        html = `<div class="search-item" style="color:var(--text-soft)">No matching topics, tags, or cards</div>`;
      }
    }

    elSearchResults.innerHTML = html;
    elSearchResults.classList.remove("hidden");

    elSearchResults.querySelector("#sr-highlight")?.addEventListener("click", () => {
      state.searchHighlightIds = new Set(allHitIds);
      elSearchResults.classList.add("hidden");
      updateChrome();
      if (state.viewMode !== "grid") requestDraw();
      showToast(`Highlighted ${allHitIds.size} matching ${plural(allHitIds.size, "topic")}`);
    });
    for (const btn of elSearchResults.querySelectorAll("[data-jump]")) {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-jump");
        elSearchResults.classList.add("hidden");
        elSearch.blur();
        flyToNode(id);
      });
    }
    for (const btn of elSearchResults.querySelectorAll("[data-browser]")) {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        sendCmd("atlas:browser:" + btn.getAttribute("data-browser"));
      });
    }
  }

  elSearch.addEventListener("input", () => {
    const rawQ = elSearch.value.trim();
    if (state.searchTimer) {
      clearTimeout(state.searchTimer);
      state.searchTimer = null;
    }
    if (!rawQ || !state.graph) {
      state.searchHighlightIds = null;
      elSearchResults.classList.add("hidden");
      updateChrome();
      if (state.viewMode !== "grid") requestDraw();
      return;
    }
    renderSearchPopup();
    if (rawQ.length >= 2) {
      const tok = ++state.searchToken;
      state.searchTimer = setTimeout(() => {
        sendCmd("atlas:search:" + JSON.stringify({ query: rawQ, token: tok }));
      }, 170);
    }
  });

  document.addEventListener("click", (e) => {
    if (!elSearch.contains(e.target) && !elSearchResults.contains(e.target)) {
      elSearchResults.classList.add("hidden");
    }
    if (state.overlayMenuOpen && elOverlayWrap && !elOverlayWrap.contains(e.target)) {
      state.overlayMenuOpen = false;
      elOverlayPanel?.classList.add("hidden");
    }
  });

  window.addEventListener("keydown", (e) => {
    if (document.activeElement === elSearch || (document.activeElement && document.activeElement.id === "path-dest-input")) {
      if (e.key === "Escape") {
        elSearchResults.classList.add("hidden");
        document.activeElement.blur();
      }
      return;
    }
    if (e.key === "/") {
      e.preventDefault();
      elSearch.focus();
    } else if (e.key === "0") {
      fitCamera(false);
    } else if (e.key === "v" || e.key === "V") {
      const nextMode = state.viewMode === "grid" ? "2d" : (state.viewMode === "2d" ? "3d" : "grid");
      setViewMode(nextMode);
    } else if ((e.key === "f" || e.key === "F") && state.selectedNodeId) {
      if (state.focusNodeId === state.selectedNodeId) exitFocus();
      else enterFocus(state.selectedNodeId);
    } else if (e.key === "Escape") {
      if (state.overlayMenuOpen) {
        state.overlayMenuOpen = false;
        elOverlayPanel?.classList.add("hidden");
      } else if (state.pathway) clearPathway();
      else if (state.focusNodeId) exitFocus();
      else if (state.isolatedRootId) clearIsolation();
      else if (state.selectedNodeId || state.selectedEdgeId) {
        state.selectedNodeId = null;
        state.selectedEdgeId = null;
        state.pathPickerOpen = false;
        renderInspector();
        renderDock();
        requestDraw();
      } else if (state.stateFilter) {
        state.stateFilter = null;
        updateChrome();
        requestDraw();
      }
    }
  });

  function handleResize() {
    const rect = canvas.parentElement.getBoundingClientRect();
    state.dpr = window.devicePixelRatio || 1;
    state.width = Math.max(200, rect.width);
    state.height = Math.max(200, rect.height);
    canvas.width = Math.floor(state.width * state.dpr);
    canvas.height = Math.floor(state.height * state.dpr);
    requestDraw();
  }

  window.addEventListener("resize", () => {
    handleResize();
    fitCamera(true);
  });

  // --- Python Bridge Entrypoints ---
  window.atlasInitPrefs = function (prefs) {
    if (!prefs) return;
    if (typeof prefs.colorblind_mode === "boolean") {
      state.colorblind = prefs.colorblind_mode;
    }
    applyTheme(prefs.night_mode !== false);
    state.showConcepts = prefs.show_concept_links !== false;
    state.viewMode =
      prefs.view_mode === "grid" || prefs.view_mode === "2d" || prefs.view_mode === "3d"
        ? prefs.view_mode
        : "grid";
    state.zMorph = state.viewMode === "3d" ? 1.0 : 0.0;
    elSpotlightSelect.value = state.spotlight;
    elConceptBtn.classList.toggle("active", state.showConcepts);
    if (elCbBtn) elCbBtn.classList.toggle("active", state.colorblind);
    updateChrome();
  };

  window.atlasReceiveNodeDetails = function (details) {
    if (!details || !details.id) return;
    state.nodeDetailsPending.delete(details.id);
    state.nodeDetailsCache.set(details.id, details);
    if (state.selectedNodeId === details.id && !state.pathway) {
      renderInspector();
    }
  };

  window.atlasReceiveSearchResults = function (res) {
    if (!res) return;
    state.lastRemoteSearch = res;
    if (!elSearchResults.classList.contains("hidden") || elSearch.value.trim().length >= 2) {
      renderSearchPopup();
    }
  };

  window.atlasSetLoading = function (on) {
    elLoading.classList.toggle("hidden", !on);
    if (on) elLoadingText.textContent = "Mapping your Anki neural network...";
  };

  window.atlasShowError = function (msg) {
    elLoading.classList.remove("hidden");
    elLoadingText.textContent = msg || "Unable to load Anki Atlas.";
  };

  window.atlasToast = function (msg) {
    showToast(msg);
  };

  window.atlasLocateNode = function (nodeId) {
    if (!nodeId || !state.nodesById.has(nodeId)) {
      showToast("Topic not found in current Atlas view.");
      return;
    }
    state.pathway = null;
    state.focusNodeId = null;
    state.isolatedRootId = null;
    if (state.spotlight !== "all") {
      state.spotlight = "all";
      elSpotlightSelect.value = "all";
    }
    state.stateFilter = null;
    state.activeOverlayIds.clear();
    state.overlayMenuOpen = false;
    elOverlayPanel?.classList.add("hidden");
    renderOverlayPanel();
    buildScene();
    flyToNode(nodeId);
    const n = state.nodesById.get(nodeId);
    showToast(`Located: ${n.label}`);
  };

  window.atlasReceiveGraph = function (payload) {
    elLoading.classList.add("hidden");
    state.graph = payload;
    state.nodesById = new Map();
    state.allEdges = payload.edges || [];
    state.allNodeEdges = new Map();
    state.overlaysById = new Map();
    state.overlayCountsById = new Map();

    const nodesArr = payload.nodes || [];
    for (const n of nodesArr) {
      state.nodesById.set(n.id, n);
      state.allNodeEdges.set(n.id, []);
    }
    for (const e of state.allEdges) {
      if (state.allNodeEdges.has(e.source)) state.allNodeEdges.get(e.source).push(e);
      if (state.allNodeEdges.has(e.target)) state.allNodeEdges.get(e.target).push(e);
    }

    // Index overlays cleanly from compact pairs
    const overlays = payload.overlays || [];
    for (const ov of overlays) {
      state.overlaysById.set(ov.id, ov);
      const cmap = new Map();
      const pairs = ov.pairs || [];
      for (let i = 0; i < pairs.length; i += 2) {
        const nodeObj = nodesArr[pairs[i]];
        if (nodeObj) cmap.set(nodeObj.id, pairs[i + 1]);
      }
      state.overlayCountsById.set(ov.id, cmap);
    }

    for (const oid of Array.from(state.activeOverlayIds)) {
      if (!state.overlaysById.has(oid)) state.activeOverlayIds.delete(oid);
    }
    state.overlayMenuOpen = false;
    elOverlayPanel?.classList.add("hidden");
    renderOverlayPanel();

    // Deck dropdown
    const decks = payload.decks || [];
    elDeckSelect.innerHTML = decks
      .map((d) => `<option value="${escHtml(d.id)}" title="${d.count.toLocaleString()} cards">${escHtml(d.label)}</option>`)
      .join("");
    elDeckSelect.value = payload.deck_filter;

    // Exam pills + Spotlight availability
    const sum = payload.summary || {};
    const showExam = Boolean(sum.use_step_subjects && (sum.has_step1 || sum.has_step2));
    elExamPills.classList.toggle("hidden", !showExam);
    for (const btn of elExamBtns) {
      btn.classList.toggle("active", btn.dataset.exam === payload.exam_scope);
      if (btn.dataset.exam === "step1") btn.disabled = !sum.has_step1;
      if (btn.dataset.exam === "step2") btn.disabled = !sum.has_step2;
    }

    const optR7 = elSpotlightSelect.querySelector('[value="recent_7d"]');
    const optR30 = elSpotlightSelect.querySelector('[value="recent_30d"]');
    if (optR7) optR7.classList.toggle("hidden", !sum.has_revlog);
    if (optR30) optR30.classList.toggle("hidden", !sum.has_revlog);
    if (state.spotlight === "hy_gaps") state.spotlight = "all";
    if ((state.spotlight === "recent_7d" || state.spotlight === "recent_30d") && !sum.has_revlog) state.spotlight = "all";
    elSpotlightSelect.value = state.spotlight;

    state.focusNodeId = null;
    state.isolatedRootId = null;
    state.pathway = null;
    state.pathPickerOpen = false;
    state.inspectorTab = null;
    state.dockTab = "subjects";
    state.gridRootId = null;
    state.searchHighlightIds = null;
    state.lastRemoteSearch = null;
    state.nodeDetailsCache.clear();
    state.nodeDetailsPending.clear();
    state.selectedNodeId = null;
    state.selectedEdgeId = null;
    state.stateFilter = null;
    state.lastInputTs = Date.now();
    hideToast();
    renderInspector();
    handleResize();
    buildScene();
    fitCamera(true);
  };

  handleResize();
  sendCmd("atlas:ready");
})();
