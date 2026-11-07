/**
 * app.js — Interactive Trained Soft Routes Dual-Map Controller
 * =============================================================
 * Synchronized Leaflet maps, 48-bin time scrubber, animated playback,
 * structural route HUD, and interactive corridor inspection.
 */

// Manhattan Geographical Center & Bounds
const MANHATTAN_CENTER = [40.7831, -73.9712];
const DEFAULT_ZOOM = 12;

// App State
let currentBin = 0;
let topoLimit = 50;
let isPlaying = false;
let playTimer = null;
let playSpeed = 800;
let currentTheme = "dark";
let currentView = "split";

// Leaflet Map Instances & Layers
let mapNLP = null;
let mapTopo = null;
let tileLayerNLP = null;
let tileLayerTopo = null;
let sumoWireframeNLP = null;
let sumoWireframeTopo = null;
let showWireframe = true;
let showTiles = true;
let nlpFeatureGroup = null;
let topoFeatureGroup = null;
let nlpPolylines = [];
let topoPolylines = [];
let isSyncing = false;

// Tile Providers (Clean, unwatermarked high-contrast basemaps)
const TILES = {
  dark: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
  light: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution: '&copy; <a href="https://www.esri.com/">Esri</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
};

// ── 1. Map Initialization ──
function initMaps() {
  const mapOptions = {
    center: MANHATTAN_CENTER,
    zoom: DEFAULT_ZOOM,
    zoomControl: true,
    attributionControl: false,
    preferCanvas: true
  };

  mapNLP = L.map("map-nlp", mapOptions);
  mapTopo = L.map("map-topo", mapOptions);

  tileLayerNLP = L.tileLayer(TILES[currentTheme], { attribution: TILES.attribution }).addTo(mapNLP);
  tileLayerTopo = L.tileLayer(TILES[currentTheme], { attribution: TILES.attribution }).addTo(mapTopo);

  nlpFeatureGroup = L.featureGroup().addTo(mapNLP);
  topoFeatureGroup = L.featureGroup().addTo(mapTopo);

  // Synchronize Pan & Zoom between Left and Right Maps
  function syncMaps(source, target) {
    if (isSyncing) return;
    isSyncing = true;
    target.setView(source.getCenter(), source.getZoom(), { animate: false });
    isSyncing = false;
  }

  mapNLP.on("move", () => syncMaps(mapNLP, mapTopo));
  mapTopo.on("move", () => syncMaps(mapTopo, mapNLP));

  window.addEventListener("resize", () => {
    mapNLP.invalidateSize();
    mapTopo.invalidateSize();
  });
}

// ── 1b. Load SUMO Native Road Network Wireframe ──
async function loadSumoNetwork() {
  try {
    const res = await fetch("/api/network_wireframe");
    const roadLines = await res.json();

    const wireframeStyle = {
      color: currentTheme === "dark" ? "rgba(148, 163, 184, 0.40)" : "rgba(71, 85, 105, 0.50)",
      weight: 1.1,
      renderer: L.canvas({ padding: 0.5 }),
      interactive: false
    };

    sumoWireframeNLP = L.polyline(roadLines, wireframeStyle).addTo(mapNLP);
    sumoWireframeTopo = L.polyline(roadLines, wireframeStyle).addTo(mapTopo);

    sumoWireframeNLP.bringToBack();
    sumoWireframeTopo.bringToBack();
    if (tileLayerNLP) tileLayerNLP.bringToBack();
    if (tileLayerTopo) tileLayerTopo.bringToBack();
  } catch (err) {
    console.warn("Could not load SUMO road network wireframe:", err);
  }
}

// ── 2. Data Fetching & Rendering ──
async function fetchAndRenderBin(binIdx) {
  currentBin = binIdx;
  document.getElementById("time-slider").value = binIdx;
  document.getElementById("bin-idx-label").textContent = `Bin ${String(binIdx).padStart(2, '0')}/48`;

  try {
    const res = await fetch(`/api/bin_data?bin=${binIdx}&topo_limit=${topoLimit}`);
    const data = await res.json();

    updateTimeDisplay(data.time_slot, data.macro_period);
    renderNLPRoutes(data.nlp_trunks);
    renderTopoRoutes(data.topo_trunks, data.total_topo_count);
    updateStructuralHUD(data.nlp_stats, data.topo_stats);
  } catch (err) {
    console.error("Error fetching bin data:", err);
  }
}

// ── 3. Render NLP Soft Routes (8 Clean Arterial Corridors) ──
function renderNLPRoutes(trunks) {
  nlpFeatureGroup.clearLayers();
  nlpPolylines = [];
  const listContainer = document.getElementById("nlp-trunk-list");
  listContainer.innerHTML = "";

  if (!trunks || trunks.length === 0) {
    listContainer.innerHTML = `<div style="font-size:11px;color:var(--text-muted);">No trunks active in this bin.</div>`;
    return;
  }

  trunks.forEach((t, idx) => {
    // 1. Glowing background polyline for neon aesthetic
    const glowLine = L.polyline(t.coordinates, {
      color: t.color,
      weight: 8,
      opacity: 0.35,
      lineCap: "round",
      interactive: false
    }).addTo(nlpFeatureGroup);

    // 2. Sharp foreground arterial polyline
    const line = L.polyline(t.coordinates, {
      color: t.color,
      weight: 4.5,
      opacity: 0.95,
      lineCap: "round"
    }).addTo(nlpFeatureGroup);

    line.bindTooltip(`
      <div style="font-weight:700;color:${t.color};margin-bottom:2px;">${t.name}</div>
      <div>Trunk ID: #${t.trunk_id + 1} | Sequence Edges: ${t.edge_count}</div>
    `, { className: "custom-tooltip", sticky: true });

    nlpPolylines.push({ line, glowLine, trunk: t });

    // 3. Create inspector card in the HUD panel
    const card = document.createElement("div");
    card.className = "trunk-card";
    card.id = `trunk-card-${idx}`;
    card.innerHTML = `
      <div class="trunk-card-left">
        <div class="trunk-swatch" style="background:${t.color}; box-shadow:0 0 8px ${t.color};"></div>
        <div>
          <div class="trunk-name">${t.name}</div>
          <div class="trunk-meta">Trunk #${t.trunk_id + 1} &bull; ${t.edge_count} arterial edges</div>
        </div>
      </div>
      <span style="font-size:11px;color:var(--text-muted);">&rarr;</span>
    `;

    card.addEventListener("mouseenter", () => highlightTrunk(idx));
    card.addEventListener("mouseleave", () => resetTrunkHighlight(idx));
    card.addEventListener("click", () => {
      mapNLP.fitBounds(line.getBounds(), { padding: [50, 50], maxZoom: 14 });
    });

    listContainer.appendChild(card);
  });
}

function highlightTrunk(idx) {
  nlpPolylines.forEach((item, i) => {
    if (i === idx) {
      item.line.setStyle({ weight: 7, opacity: 1.0 });
      item.glowLine.setStyle({ weight: 14, opacity: 0.7 });
      item.line.bringToFront();
      document.getElementById(`trunk-card-${i}`)?.classList.add("active");
    } else {
      item.line.setStyle({ opacity: 0.25 });
      item.glowLine.setStyle({ opacity: 0.05 });
      document.getElementById(`trunk-card-${i}`)?.classList.remove("active");
    }
  });
}

function resetTrunkHighlight(idx) {
  nlpPolylines.forEach((item, i) => {
    item.line.setStyle({ weight: 4.5, opacity: 0.95 });
    item.glowLine.setStyle({ weight: 8, opacity: 0.35 });
    document.getElementById(`trunk-card-${i}`)?.classList.remove("active");
  });
}

// ── 4. Render TopoScan Soft Routes (Dense Geometric Clusters) ──
function renderTopoRoutes(trunks, totalCount) {
  topoFeatureGroup.clearLayers();
  topoPolylines = [];

  const countStr = typeof totalCount === 'number' ? totalCount.toLocaleString() : totalCount;
  document.getElementById("topo-badge-sub").textContent = 
    `${countStr} Geometric Clusters (${trunks.length} displayed)`;

  if (!trunks || trunks.length === 0) return;

  trunks.forEach((t) => {
    const line = L.polyline(t.coordinates, {
      color: "#f59e0b", // Amber/Gold
      weight: 2.2,
      opacity: 0.55,
      lineCap: "round"
    }).addTo(topoFeatureGroup);

    line.bindTooltip(`
      <div style="font-weight:700;color:#f59e0b;">TopoScan Cluster Trunk #${t.trunk_id}</div>
      <div>Edges: ${t.edge_count}</div>
    `, { className: "custom-tooltip", sticky: true });

    line.on("mouseover", () => line.setStyle({ weight: 5, opacity: 1.0, color: "#fbbf24" }));
    line.on("mouseout", () => line.setStyle({ weight: 2.2, opacity: 0.55, color: "#f59e0b" }));

    topoPolylines.push(line);
  });
}

// ── 5. Structural HUD Updates ──
function updateStructuralHUD(nlpStats, topoStats) {
  const ns = nlpStats || {};
  const ts = topoStats || {};

  document.getElementById("kpi-nlp-count").textContent = `${ns.count || 8} Trunks`;
  document.getElementById("kpi-topo-count").textContent = `Topo: ${(ts.count || 2331).toLocaleString()}`;

  document.getElementById("kpi-nlp-edges").textContent = `${ns.mean_edges || 41} edges`;
  document.getElementById("kpi-topo-edges").textContent = `Topo: ${ts.mean_edges || 54.6}`;

  document.getElementById("kpi-nlp-structure").textContent = "Arterial Flows";
  document.getElementById("kpi-topo-structure").textContent = "Local Clusters";

  document.getElementById("kpi-nlp-scope").textContent = "Island-Wide";
  document.getElementById("kpi-topo-scope").textContent = "Fragmented";
}

// ── 6. UI Controls & Time Slider ──
function updateTimeDisplay(timeSlot, macroPeriod) {
  document.getElementById("clock-display").textContent = timeSlot;
  const badge = document.getElementById("macro-badge");
  badge.textContent = macroPeriod.split(" (")[0];

  badge.className = "macro-badge";
  if (macroPeriod.includes("Late Night")) badge.classList.add("macro-late-night");
  else if (macroPeriod.includes("Morning Rush")) badge.classList.add("macro-morning-rush");
  else if (macroPeriod.includes("Midday Steady")) badge.classList.add("macro-midday-steady");
  else if (macroPeriod.includes("Evening Rush")) badge.classList.add("macro-evening-rush");
  else if (macroPeriod.includes("Night Leisure")) badge.classList.add("macro-night-leisure");
}

function setupEventListeners() {
  // Scrubber slider
  const slider = document.getElementById("time-slider");
  slider.addEventListener("input", (e) => {
    fetchAndRenderBin(parseInt(e.target.value));
  });

  // Play / Pause Animation
  const playBtn = document.getElementById("btn-play");
  playBtn.addEventListener("click", () => {
    if (isPlaying) {
      clearInterval(playTimer);
      isPlaying = false;
      playBtn.textContent = "▶";
      playBtn.title = "Play";
    } else {
      isPlaying = true;
      playBtn.textContent = "⏸";
      playBtn.title = "Pause";
      playTimer = setInterval(() => {
        let nextBin = (currentBin + 1) % 48;
        fetchAndRenderBin(nextBin);
      }, playSpeed);
    }
  });

  // Speed selector
  document.getElementById("select-speed").addEventListener("change", (e) => {
    playSpeed = parseInt(e.target.value);
    if (isPlaying) {
      clearInterval(playTimer);
      playTimer = setInterval(() => {
        let nextBin = (currentBin + 1) % 48;
        fetchAndRenderBin(nextBin);
      }, playSpeed);
    }
  });

  // View Mode Selector (Split / NLP / Topo)
  document.querySelectorAll("#view-mode-selector .pill-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      document.querySelectorAll("#view-mode-selector .pill-btn").forEach(b => b.classList.remove("active"));
      e.target.classList.add("active");
      const mode = e.target.getAttribute("data-view");
      setViewMode(mode);
    });
  });

  // TopoScan Density Selector
  document.querySelectorAll(".density-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      document.querySelectorAll(".density-btn").forEach(b => b.classList.remove("active"));
      e.target.classList.add("active");
      topoLimit = parseInt(e.target.getAttribute("data-limit"));
      fetchAndRenderBin(currentBin);
    });
  });

  // Recenter Map
  document.getElementById("btn-recenter").addEventListener("click", () => {
    mapNLP.setView(MANHATTAN_CENTER, DEFAULT_ZOOM);
    mapTopo.setView(MANHATTAN_CENTER, DEFAULT_ZOOM);
  });

  // Theme Toggle (Dark vs Light)
  document.getElementById("btn-theme").addEventListener("click", () => {
    currentTheme = currentTheme === "dark" ? "light" : "dark";
    document.body.setAttribute("data-theme", currentTheme);
    tileLayerNLP.setUrl(TILES[currentTheme]);
    tileLayerTopo.setUrl(TILES[currentTheme]);
  });

  // Toggle SUMO Simulation Road Network
  const btnWireframe = document.getElementById("btn-toggle-wireframe");
  if (btnWireframe) {
    btnWireframe.addEventListener("click", () => {
      showWireframe = !showWireframe;
      btnWireframe.classList.toggle("active", showWireframe);
      if (sumoWireframeNLP && sumoWireframeTopo) {
        if (showWireframe) {
          mapNLP.addLayer(sumoWireframeNLP);
          mapTopo.addLayer(sumoWireframeTopo);
          sumoWireframeNLP.bringToBack();
          sumoWireframeTopo.bringToBack();
          if (showTiles && tileLayerNLP) tileLayerNLP.bringToBack();
          if (showTiles && tileLayerTopo) tileLayerTopo.bringToBack();
        } else {
          mapNLP.removeLayer(sumoWireframeNLP);
          mapTopo.removeLayer(sumoWireframeTopo);
        }
      }
    });
  }

  // Toggle Basemap Tiles
  const btnTiles = document.getElementById("btn-toggle-tiles");
  if (btnTiles) {
    btnTiles.addEventListener("click", () => {
      showTiles = !showTiles;
      btnTiles.classList.toggle("active", showTiles);
      if (showTiles) {
        mapNLP.addLayer(tileLayerNLP);
        mapTopo.addLayer(tileLayerTopo);
        tileLayerNLP.bringToBack();
        tileLayerTopo.bringToBack();
      } else {
        mapNLP.removeLayer(tileLayerNLP);
        mapTopo.removeLayer(tileLayerTopo);
      }
    });
  }

  // Collapse HUD Panel
  const hudBtn = document.getElementById("btn-toggle-hud");
  hudBtn.addEventListener("click", () => {
    const panel = document.getElementById("hud-panel");
    if (panel.style.transform === "translateX(330px)") {
      panel.style.transform = "translateX(0)";
      hudBtn.textContent = "Collapse";
    } else {
      panel.style.transform = "translateX(330px)";
      hudBtn.textContent = "Expand";
    }
  });
}

function setViewMode(mode) {
  currentView = mode;
  const cNLP = document.getElementById("container-nlp");
  const cTopo = document.getElementById("container-topo");

  if (mode === "split") {
    cNLP.style.display = "block";
    cTopo.style.display = "block";
    cNLP.style.flex = "1";
    cTopo.style.flex = "1";
  } else if (mode === "nlp") {
    cNLP.style.display = "block";
    cTopo.style.display = "none";
    cNLP.style.flex = "1";
  } else if (mode === "topo") {
    cNLP.style.display = "none";
    cTopo.style.display = "block";
    cTopo.style.flex = "1";
  }

  setTimeout(() => {
    mapNLP.invalidateSize();
    mapTopo.invalidateSize();
  }, 100);
}

// ── 7. DOM Ready Bootstrap ──
document.addEventListener("DOMContentLoaded", () => {
  initMaps();
  setupEventListeners();
  loadSumoNetwork();
  fetchAndRenderBin(0); // Start at Bin 0 (00:00 - 00:30)
});
