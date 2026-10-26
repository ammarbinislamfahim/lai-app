/**
 * Leaf Area & LAI Analyzer v1.5.6 — Frontend Controller
 * 100% local vanilla JavaScript, zero external dependencies.
 */

(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // 1. State & Numeric Helpers
  // ---------------------------------------------------------------------------
  let selectedFiles = [];
  let objectUrls = [];
  let currentResponse = null;
  let activeImageIndex = 0;
  let activeViewMode = "side-by-side";
  let lightboxLayer = "overlay";
  let zoomScale = 1;
  let panX = 0;
  let panY = 0;
  let isDragging = false;
  let dragStartX = 0;
  let dragStartY = 0;

  function numVal(v, fallback) {
    const n = Number(v);
    return Number.isFinite(n) ? n : (fallback !== undefined ? fallback : 0);
  }

  function fmtFixed(v, decimals, fallbackStr) {
    const n = Number(v);
    if (!Number.isFinite(n)) return fallbackStr !== undefined ? fallbackStr : "0.00";
    return n.toFixed(decimals);
  }

  // ---------------------------------------------------------------------------
  // 2. DOM Elements
  // ---------------------------------------------------------------------------
  const htmlEl = document.documentElement;
  const metaThemeColor = document.getElementById("metaThemeColor");
  const appVersionBadge = document.getElementById("appVersionBadge");
  const footerVersion = document.getElementById("footerVersion");

  // Top bar
  const btnOpenHelp = document.getElementById("btnOpenHelp");
  const btnInlineHelpLink = document.getElementById("btnInlineHelpLink");
  const btnCloseHelp = document.getElementById("btnCloseHelp");
  const helpDrawer = document.getElementById("helpDrawer");
  const helpDrawerBackdrop = document.getElementById("helpDrawerBackdrop");

  const btnCalibSheets = document.getElementById("btnCalibSheets");
  const calibSheetsMenu = document.getElementById("calibSheetsMenu");
  const calibDropdownWrap = document.getElementById("calibDropdownWrap");

  const btnThemeToggle = document.getElementById("btnThemeToggle");
  const iconThemeSun = document.getElementById("iconThemeSun");
  const iconThemeMoon = document.getElementById("iconThemeMoon");
  const btnQuitApp = document.getElementById("btnQuitApp");

  // Upload card
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  const selectedFilesPanel = document.getElementById("selectedFilesPanel");
  const selectedFilesCount = document.getElementById("selectedFilesCount");
  const fileThumbList = document.getElementById("fileThumbList");
  const btnAddMoreFiles = document.getElementById("btnAddMoreFiles");
  const btnClearFiles = document.getElementById("btnClearFiles");

  const btnTrySample = document.getElementById("btnTrySample");
  const sampleMenu = document.getElementById("sampleMenu");

  // Settings
  const btnToggleSettings = document.getElementById("btnToggleSettings");
  const settingsGridWrap = document.getElementById("settingsGridWrap");
  const settingsSummaryPill = document.getElementById("settingsSummaryPill");

  const calibSideInput = document.getElementById("calibration_side_cm");
  const calibColorSelect = document.getElementById("calibration_color");
  const swatchButtons = document.querySelectorAll(".swatch-btn");

  const laiModeSelect = document.getElementById("lai_mode");
  const segmentButtons = document.querySelectorAll(".segment-btn");
  const laiNoneHint = document.getElementById("laiNoneHint");
  const laiMode1Fields = document.getElementById("laiMode1Fields");
  const laiMode2Fields = document.getElementById("laiMode2Fields");
  const groundAreaInput = document.getElementById("ground_area_m2");
  const numPlantsInput = document.getElementById("num_plants");
  const areaPerPlantInput = document.getElementById("area_per_plant_m2");

  // Primary Action & Banners
  const btnAnalyze = document.getElementById("btnAnalyze");
  const analyzeSpinner = document.getElementById("analyzeSpinner");
  const analyzeBtnText = document.getElementById("analyzeBtnText");
  const statusBanner = document.getElementById("statusBanner");
  const errorBanner = document.getElementById("errorBanner");

  // Manual scale fallback
  const manualScalePrompt = document.getElementById("manualScalePrompt");
  const manualScaleInput = document.getElementById("manual_px_per_cm");
  const btnRerunManual = document.getElementById("btnRerunManual");

  // Results section
  const resultsSection = document.getElementById("resultsSection");
  const resCalibLine = document.getElementById("resCalibLine");
  const btnCopySummary = document.getElementById("btnCopySummary");
  const copySummaryText = document.getElementById("copySummaryText");
  const btnExportCsv = document.getElementById("btnExportCsv");
  const btnExportXlsx = document.getElementById("btnExportXlsx");

  const resTotalArea = document.getElementById("resTotalArea");
  const resUncertainty = document.getElementById("resUncertainty");
  const resLeafCount = document.getElementById("resLeafCount");
  const resLeafSub = document.getElementById("resLeafSub");
  const resLai = document.getElementById("resLai");
  const resLaiSub = document.getElementById("resLaiSub");
  const resConfidenceBadge = document.getElementById("resConfidenceBadge");
  const resCalibDetail = document.getElementById("resCalibDetail");

  const imageTabsWrap = document.getElementById("imageTabsWrap");
  const imageTabs = document.getElementById("imageTabs");
  const warningsBox = document.getElementById("warningsBox");

  // Image comparison
  const currentImageTitle = document.getElementById("currentImageTitle");
  const currentImageMeta = document.getElementById("currentImageMeta");
  const viewModeButtons = document.querySelectorAll(".view-mode-btn[data-view-mode]");
  const viewSideBySide = document.getElementById("viewSideBySide");
  const viewSlider = document.getElementById("viewSlider");
  const viewOverlayOnly = document.getElementById("viewOverlayOnly");

  const origPreviewImg = document.getElementById("origPreviewImg");
  const overlayPreviewImg = document.getElementById("overlayPreviewImg");
  const boxOrigImg = document.getElementById("boxOrigImg");
  const boxOverlayImg = document.getElementById("boxOverlayImg");
  const boxSingleOverlay = document.getElementById("boxSingleOverlay");
  const singleOverlayImg = document.getElementById("singleOverlayImg");

  const sliderOverlayImg = document.getElementById("sliderOverlayImg");
  const sliderOrigImg = document.getElementById("sliderOrigImg");
  const sliderClipBefore = document.getElementById("sliderClipBefore");
  const sliderDivider = document.getElementById("sliderDivider");
  const compareSlider = document.getElementById("compareSlider");

  const leafTableBody = document.getElementById("leafTableBody");

  // Lightbox
  const btnOpenZoom = document.getElementById("btnOpenZoom");
  const lightboxModal = document.getElementById("lightboxModal");
  const lightboxTitle = document.getElementById("lightboxTitle");
  const lightboxViewport = document.getElementById("lightboxViewport");
  const lightboxImg = document.getElementById("lightboxImg");
  const btnLbOverlay = document.getElementById("btnLbOverlay");
  const btnLbOriginal = document.getElementById("btnLbOriginal");
  const btnZoomIn = document.getElementById("btnZoomIn");
  const btnZoomOut = document.getElementById("btnZoomOut");
  const btnZoomReset = document.getElementById("btnZoomReset");
  const zoomLevelLabel = document.getElementById("zoomLevelLabel");
  const btnCloseLightbox = document.getElementById("btnCloseLightbox");

  // ---------------------------------------------------------------------------
  // 3. Desktop Lifecycle Heartbeat & Version Sync
  // ---------------------------------------------------------------------------
  const clientId =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : "client-" + Date.now() + "-" + Math.random().toString(36).slice(2, 10);

  function sendPing() {
    fetch("/api/ping?client_id=" + encodeURIComponent(clientId), {
      method: "POST",
      keepalive: true,
    }).catch(function () {});
  }

  sendPing();
  setInterval(sendPing, 5000);

  function sendBye() {
    const url = "/api/bye?client_id=" + encodeURIComponent(clientId);
    if (navigator.sendBeacon) {
      navigator.sendBeacon(url, "");
    } else {
      fetch(url, { method: "POST", keepalive: true }).catch(function () {});
    }
  }

  window.addEventListener("pagehide", sendBye);
  window.addEventListener("beforeunload", sendBye);

  fetch("/api/health")
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d && d.version) {
        const vText = "v" + d.version;
        if (appVersionBadge) appVersionBadge.textContent = vText;
        if (footerVersion) footerVersion.textContent = vText;
      }
    })
    .catch(function () {});

  if (btnQuitApp) {
    btnQuitApp.addEventListener("click", function () {
      btnQuitApp.disabled = true;
      fetch("/api/quit", { method: "POST" })
        .then(function (r) {
          if (!r.ok) {
            btnQuitApp.classList.add("hidden");
            return;
          }
          document.body.innerHTML =
            '<div style="max-width:460px;margin:120px auto;padding:32px;background:var(--surface);border:1px solid var(--border);border-radius:14px;text-align:center;font-family:system-ui,sans-serif;">' +
            '<h2 style="margin:0 0 8px;color:var(--primary);">Leaf Area &amp; LAI Analyzer Stopped</h2>' +
            '<p style="margin:0;color:var(--text-secondary);">The local analyzer server has shut down cleanly. You may now close this window.</p>' +
            "</div>";
          try { window.close(); } catch (e) {}
        })
        .catch(function () {
          btnQuitApp.classList.add("hidden");
        });
    });
  }

  // ---------------------------------------------------------------------------
  // 4. Theme Toggle (Light default, respects prefers-color-scheme + manual)
  // ---------------------------------------------------------------------------
  function getEffectiveTheme() {
    const saved = localStorage.getItem("leafarea_theme");
    if (saved === "dark" || saved === "light") return saved;
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      return "dark";
    }
    return "light";
  }

  function applyTheme(theme) {
    htmlEl.setAttribute("data-theme", theme);
    if (metaThemeColor) {
      metaThemeColor.setAttribute("content", theme === "dark" ? "#17201B" : "#2F7D4F");
    }
    if (iconThemeSun && iconThemeMoon) {
      if (theme === "dark") {
        iconThemeSun.classList.remove("hidden");
        iconThemeMoon.classList.add("hidden");
      } else {
        iconThemeSun.classList.add("hidden");
        iconThemeMoon.classList.remove("hidden");
      }
    }
  }

  applyTheme(getEffectiveTheme());

  if (btnThemeToggle) {
    btnThemeToggle.addEventListener("click", function () {
      const current = htmlEl.getAttribute("data-theme") || getEffectiveTheme();
      const next = current === "dark" ? "light" : "dark";
      localStorage.setItem("leafarea_theme", next);
      applyTheme(next);
    });
  }

  // ---------------------------------------------------------------------------
  // 5. Drawers, Dropdowns & Keyboard Accessibility
  // ---------------------------------------------------------------------------
  function openHelpDrawer() {
    helpDrawer.classList.remove("hidden");
    helpDrawerBackdrop.classList.remove("hidden");
    btnOpenHelp.setAttribute("aria-expanded", "true");
    btnCloseHelp.focus();
  }

  function closeHelpDrawer() {
    if (helpDrawer.classList.contains("hidden")) return;
    helpDrawer.classList.add("hidden");
    helpDrawerBackdrop.classList.add("hidden");
    btnOpenHelp.setAttribute("aria-expanded", "false");
    btnOpenHelp.focus();
  }

  if (btnOpenHelp) btnOpenHelp.addEventListener("click", openHelpDrawer);
  if (btnInlineHelpLink) btnInlineHelpLink.addEventListener("click", openHelpDrawer);
  if (btnCloseHelp) btnCloseHelp.addEventListener("click", closeHelpDrawer);
  if (helpDrawerBackdrop) helpDrawerBackdrop.addEventListener("click", closeHelpDrawer);

  if (btnCalibSheets) {
    btnCalibSheets.addEventListener("click", function (e) {
      e.stopPropagation();
      const isHidden = calibSheetsMenu.classList.toggle("hidden");
      btnCalibSheets.setAttribute("aria-expanded", String(!isHidden));
    });
  }

  if (btnTrySample) {
    btnTrySample.addEventListener("click", function (e) {
      e.stopPropagation();
      const isHidden = sampleMenu.classList.toggle("hidden");
      btnTrySample.setAttribute("aria-expanded", String(!isHidden));
    });
  }

  document.addEventListener("click", function (e) {
    if (calibDropdownWrap && !calibDropdownWrap.contains(e.target)) {
      calibSheetsMenu.classList.add("hidden");
      btnCalibSheets.setAttribute("aria-expanded", "false");
    }
    if (sampleMenu && !sampleMenu.contains(e.target) && e.target !== btnTrySample) {
      sampleMenu.classList.add("hidden");
      btnTrySample.setAttribute("aria-expanded", "false");
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      if (!lightboxModal.classList.contains("hidden")) {
        closeLightbox();
      } else if (!helpDrawer.classList.contains("hidden")) {
        closeHelpDrawer();
      } else {
        calibSheetsMenu.classList.add("hidden");
        sampleMenu.classList.add("hidden");
      }
    }
  });

  // ---------------------------------------------------------------------------
  // 6. Settings Row & Live Summary
  // ---------------------------------------------------------------------------
  function updateSettingsSummary() {
    const side = parseFloat(calibSideInput.value || "2.0");
    const sideStr = Number.isFinite(side) ? side.toFixed(2) : "2.00";
    const color = calibColorSelect.value || "blue";
    const mode = laiModeSelect.value || "none";
    let modeLabel = "leaf area only";
    if (mode === "mode_1") {
      const ga = groundAreaInput.value ? groundAreaInput.value + " m² ground" : "ground area";
      modeLabel = "LAI (" + ga + ")";
    } else if (mode === "mode_2") {
      modeLabel = "LAI (plants × area)";
    }
    settingsSummaryPill.textContent = sideStr + " cm " + color + " square, " + modeLabel;
  }

  if (btnToggleSettings) {
    btnToggleSettings.addEventListener("click", function () {
      const expanded = btnToggleSettings.getAttribute("aria-expanded") === "true";
      btnToggleSettings.setAttribute("aria-expanded", String(!expanded));
      settingsGridWrap.classList.toggle("hidden", expanded);
    });
  }

  function setCalibrationColor(color) {
    calibColorSelect.value = color;
    swatchButtons.forEach(function (btn) {
      const active = btn.getAttribute("data-color") === color;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-checked", String(active));
    });
    updateSettingsSummary();
  }

  swatchButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setCalibrationColor(btn.getAttribute("data-color"));
    });
  });

  calibColorSelect.addEventListener("change", function () {
    setCalibrationColor(calibColorSelect.value);
  });

  function setLaiMode(mode) {
    laiModeSelect.value = mode;
    segmentButtons.forEach(function (btn) {
      const active = btn.getAttribute("data-lai-mode") === mode;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-checked", String(active));
    });
    laiNoneHint.classList.toggle("hidden", mode !== "none");
    laiMode1Fields.classList.toggle("hidden", mode !== "mode_1");
    laiMode2Fields.classList.toggle("hidden", mode !== "mode_2");
    updateSettingsSummary();
  }

  segmentButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setLaiMode(btn.getAttribute("data-lai-mode"));
    });
  });

  laiModeSelect.addEventListener("change", function () {
    setLaiMode(laiModeSelect.value);
  });

  [calibSideInput, groundAreaInput, numPlantsInput, areaPerPlantInput].forEach(function (el) {
    if (el) el.addEventListener("input", updateSettingsSummary);
  });

  // ---------------------------------------------------------------------------
  // 7. File Selection, Thumbnails & Built-in Samples
  // ---------------------------------------------------------------------------
  function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(2) + " MB";
  }

  function revokeObjectUrls() {
    objectUrls.forEach(function (u) {
      try { URL.revokeObjectURL(u); } catch (e) {}
    });
    objectUrls = [];
  }

  function renderFileThumbnails() {
    revokeObjectUrls();
    fileThumbList.innerHTML = "";

    if (selectedFiles.length === 0) {
      selectedFilesPanel.classList.add("hidden");
      btnAnalyze.disabled = true;
      analyzeBtnText.textContent = "Analyze";
      return;
    }

    selectedFilesPanel.classList.remove("hidden");
    selectedFilesCount.textContent =
      selectedFiles.length === 1
        ? "1 photo ready to analyze"
        : selectedFiles.length + " photos ready to analyze";
    btnAnalyze.disabled = false;
    analyzeBtnText.textContent =
      selectedFiles.length === 1
        ? "Analyze photo"
        : "Analyze " + selectedFiles.length + " photos";

    selectedFiles.forEach(function (file, idx) {
      const url = URL.createObjectURL(file);
      objectUrls.push(url);

      const item = document.createElement("div");
      item.className = "file-thumb-item";

      const img = document.createElement("img");
      img.className = "file-thumb-preview";
      img.src = url;
      img.alt = file.name;

      const info = document.createElement("div");
      info.className = "file-thumb-info";

      const nameEl = document.createElement("div");
      nameEl.className = "file-thumb-name";
      nameEl.title = file.name;
      nameEl.textContent = file.name;

      const sizeEl = document.createElement("div");
      sizeEl.className = "file-thumb-size";
      sizeEl.textContent = formatBytes(file.size);

      info.appendChild(nameEl);
      info.appendChild(sizeEl);

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "file-thumb-remove";
      removeBtn.setAttribute("aria-label", "Remove " + file.name);
      removeBtn.innerHTML = "&times;";
      removeBtn.addEventListener("click", function () {
        selectedFiles.splice(idx, 1);
        renderFileThumbnails();
      });

      item.appendChild(img);
      item.appendChild(info);
      item.appendChild(removeBtn);
      fileThumbList.appendChild(item);
    });
  }

  function addFiles(fileList) {
    const incoming = Array.from(fileList || []);
    if (incoming.length === 0) return;
    incoming.forEach(function (f) {
      const exists = selectedFiles.some(function (existing) {
        return existing.name === f.name && existing.size === f.size;
      });
      if (!exists) selectedFiles.push(f);
    });
    errorBanner.classList.add("hidden");
    manualScalePrompt.classList.add("hidden");
    renderFileThumbnails();
  }

  fileInput.addEventListener("change", function () {
    if (fileInput.files && fileInput.files.length > 0) {
      selectedFiles = Array.from(fileInput.files);
      errorBanner.classList.add("hidden");
      manualScalePrompt.classList.add("hidden");
      renderFileThumbnails();
    }
  });

  if (btnAddMoreFiles) {
    btnAddMoreFiles.addEventListener("click", function () {
      fileInput.value = "";
      fileInput.click();
    });
  }

  if (btnClearFiles) {
    btnClearFiles.addEventListener("click", function () {
      selectedFiles = [];
      fileInput.value = "";
      renderFileThumbnails();
    });
  }

  ["dragenter", "dragover"].forEach(function (evName) {
    dropZone.addEventListener(evName, function (e) {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach(function (evName) {
    dropZone.addEventListener(evName, function (e) {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("dragover");
    });
  });

  dropZone.addEventListener("drop", function (e) {
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      addFiles(e.dataTransfer.files);
    }
  });

  // Sample Picker Options
  document.querySelectorAll(".sample-option").forEach(function (btn) {
    btn.addEventListener("click", async function () {
      const sampleFile = btn.getAttribute("data-sample-file");
      const sampleColor = btn.getAttribute("data-sample-color") || "blue";
      sampleMenu.classList.add("hidden");
      btnTrySample.setAttribute("aria-expanded", "false");

      try {
        statusBanner.textContent = "Loading sample " + sampleFile + "...";
        statusBanner.classList.remove("hidden");
        const resp = await fetch("/static/samples/" + sampleFile);
        if (!resp.ok) throw new Error("Could not load sample file");
        const blob = await resp.blob();
        const fileObj = new File([blob], sampleFile, { type: "image/png" });
        selectedFiles = [fileObj];
        setCalibrationColor(sampleColor);
        renderFileThumbnails();
        statusBanner.classList.add("hidden");
        await runAnalysis(null);
      } catch (err) {
        statusBanner.classList.add("hidden");
        showError("Could not load built-in sample image: " + err.message);
      }
    });
  });

  // ---------------------------------------------------------------------------
  // 8. Run Analysis (POST /api/analyze)
  // ---------------------------------------------------------------------------
  function showError(msg) {
    errorBanner.textContent = msg;
    errorBanner.classList.remove("hidden");
  }

  async function runAnalysis(manualScaleOverride) {
    errorBanner.classList.add("hidden");
    if (selectedFiles.length === 0) {
      showError("Please choose at least one leaf photo first.");
      return;
    }

    const formData = new FormData();
    selectedFiles.forEach(function (f) {
      formData.append("files", f);
    });

    formData.append("calibration_side_cm", calibSideInput.value || "2.0");
    formData.append("calibration_color", calibColorSelect.value || "blue");
    formData.append("lai_mode", laiModeSelect.value || "none");

    if (laiModeSelect.value === "mode_1" && groundAreaInput.value) {
      formData.append("ground_area_m2", groundAreaInput.value);
    } else if (laiModeSelect.value === "mode_2") {
      if (numPlantsInput.value) formData.append("num_plants", numPlantsInput.value);
      if (areaPerPlantInput.value) formData.append("area_per_plant_m2", areaPerPlantInput.value);
    }

    if (manualScaleOverride !== null && manualScaleOverride !== undefined && manualScaleOverride !== "") {
      formData.append("manual_px_per_cm", String(manualScaleOverride));
    }

    btnAnalyze.disabled = true;
    analyzeSpinner.classList.remove("hidden");
    const count = selectedFiles.length;
    analyzeBtnText.textContent =
      count === 1 ? "Analyzing image 1 of 1..." : "Analyzing image 1 of " + count + "...";
    statusBanner.textContent =
      "Detecting calibration square, normalizing illumination, and measuring leaf contours...";
    statusBanner.classList.remove("hidden");

    try {
      const resp = await fetch("/api/analyze", {
        method: "POST",
        body: formData,
      });
      const data = await resp.json();
      statusBanner.classList.add("hidden");

      if (!resp.ok) {
        showError(data.detail || "Analysis failed.");
        return;
      }

      currentResponse = data;
      activeImageIndex = 0;

      if (data.needs_manual_scale) {
        manualScalePrompt.classList.remove("hidden");
      } else {
        manualScalePrompt.classList.add("hidden");
      }

      renderResults(data);
    } catch (err) {
      statusBanner.classList.add("hidden");
      showError("Error while analyzing photo: " + err.message);
    } finally {
      btnAnalyze.disabled = selectedFiles.length === 0;
      analyzeSpinner.classList.add("hidden");
      analyzeBtnText.textContent =
        selectedFiles.length <= 1 ? "Analyze photo" : "Analyze " + selectedFiles.length + " photos";
    }
  }

  btnAnalyze.addEventListener("click", function () {
    runAnalysis(null);
  });

  btnRerunManual.addEventListener("click", function () {
    const val = parseFloat(manualScaleInput.value);
    if (!Number.isFinite(val) || val <= 0) {
      showError("Please enter a valid positive number of pixels per cm (for example 100.0).");
      return;
    }
    runAnalysis(val);
  });

  // ---------------------------------------------------------------------------
  // 9. Render Results
  // ---------------------------------------------------------------------------
  function formatMethodLabel(method) {
    if (method === "calibration_square") return "calibration square detected";
    if (method === "exif_dpi" || method === "dpi_metadata") return "EXIF scanner DPI";
    if (method === "manual" || method === "manual_scale") return "manual scale fallback";
    return "uncalibrated";
  }

  function renderResults(data) {
    resultsSection.classList.remove("hidden");

    const images = data.images || [];
    const sessionId = data.session_id || "session";

    btnExportCsv.href = "/api/export/" + encodeURIComponent(sessionId) + "?format=csv";
    btnExportXlsx.href = "/api/export/" + encodeURIComponent(sessionId) + "?format=xlsx";

    // Render image tabs if more than 1 image
    imageTabs.innerHTML = "";
    if (images.length > 1) {
      imageTabsWrap.classList.remove("hidden");
      images.forEach(function (imgData, idx) {
        const tab = document.createElement("button");
        tab.type = "button";
        tab.className = "image-tab-btn";
        tab.setAttribute("role", "tab");
        tab.setAttribute("aria-selected", String(idx === activeImageIndex));
        tab.textContent = (idx + 1) + ". " + imgData.filename + " (" + fmtFixed(imgData.total_area_cm2, 2) + " cm²)";
        tab.addEventListener("click", function () {
          activeImageIndex = idx;
          Array.from(imageTabs.children).forEach(function (c, i) {
            c.setAttribute("aria-selected", String(i === activeImageIndex));
          });
          renderActiveImage(data, activeImageIndex);
        });
        imageTabs.appendChild(tab);
      });
    } else {
      imageTabsWrap.classList.add("hidden");
    }

    renderActiveImage(data, activeImageIndex);
    resultsSection.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderActiveImage(data, idx) {
    const batch = data.batch_summary || {};
    const images = data.images || [];
    const img = images[idx] || images[0];
    if (!img) return;

    const isMulti = images.length > 1;
    const totalArea = isMulti
      ? numVal(batch.total_leaf_area_cm2, img.total_area_cm2)
      : numVal(img.total_area_cm2, 0);
    const totalUnc = isMulti
      ? numVal(batch.total_uncertainty_cm2 !== undefined ? batch.total_uncertainty_cm2 : batch.uncertainty_cm2, img.uncertainty_cm2)
      : numVal(img.uncertainty_cm2, 0);
    const apiUncPct =
      !isMulti && img.uncertainty_pct !== undefined && img.uncertainty_pct !== null
        ? " (" + fmtFixed(img.uncertainty_pct, 2) + "%)"
        : "";

    resTotalArea.innerHTML = fmtFixed(totalArea, 2) + " cm&sup2;";
    resUncertainty.innerHTML = "&plusmn; " + fmtFixed(totalUnc, 2) + " cm&sup2;" + apiUncPct;

    const leafCount = isMulti ? numVal(batch.total_leaf_count, img.leaf_count) : numVal(img.leaf_count, 0);
    resLeafCount.textContent = String(leafCount);
    resLeafSub.textContent = isMulti
      ? "Across " + images.length + " photos (" + numVal(img.leaf_count, 0) + " in current photo)"
      : "Detected in " + img.filename;

    if (batch.lai !== null && batch.lai !== undefined && Number.isFinite(Number(batch.lai))) {
      resLai.textContent = fmtFixed(batch.lai, 3);
      resLaiSub.innerHTML =
        "Ground area: " + (batch.ground_area_m2 ? fmtFixed(batch.ground_area_m2, 4) + " m&sup2;" : "");
    } else {
      resLai.innerHTML = "&mdash;";
      resLaiSub.textContent = "Leaf area only";
    }

    const conf = String(img.confidence || batch.overall_confidence || "LOW").toUpperCase();
    resConfidenceBadge.textContent = conf === "HIGH" ? "High" : conf === "MEDIUM" ? "Medium" : "Low";
    resConfidenceBadge.className =
      "confidence-pill " +
      (conf === "HIGH"
        ? "confidence-high"
        : conf === "MEDIUM"
        ? "confidence-medium"
        : "confidence-low");

    const hasScale = img.px_per_cm !== null && img.px_per_cm !== undefined && Number.isFinite(Number(img.px_per_cm));
    const scaleText = hasScale ? fmtFixed(img.px_per_cm, 2) + " px/cm" : "Not calibrated";
    const methodText = formatMethodLabel(img.calibration_method);
    resCalibLine.textContent = "Scale " + scaleText + " (" + methodText + ")";
    resCalibDetail.textContent = scaleText + " · " + methodText;

    // Warnings
    warningsBox.innerHTML = "";
    const warnings = img.warnings || [];
    if (warnings.length === 0) {
      const okEl = document.createElement("div");
      okEl.className = "no-warnings-line";
      okEl.innerHTML =
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>' +
        "<span>No warnings</span>";
      warningsBox.appendChild(okEl);
    } else {
      warnings.forEach(function (w) {
        const wEl = document.createElement("div");
        wEl.className = "warning-callout";
        wEl.innerHTML =
          '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>' +
          "<span>" + escapeHtml(w) + "</span>";
        warningsBox.appendChild(wEl);
      });
    }

    // Images
    currentImageTitle.textContent = img.filename;
    currentImageMeta.textContent =
      numVal(img.width_px, 0) + " × " + numVal(img.height_px, 0) + " px · " + scaleText + " · Click image to inspect edges";

    const origFile = selectedFiles[idx] || selectedFiles[0];
    const origSrc = img.original_preview_b64 || (origFile ? URL.createObjectURL(origFile) : img.overlay_image_b64 || "");
    if (!img.original_preview_b64 && origFile) objectUrls.push(origSrc);
    const overSrc = img.overlay_image_b64 || origSrc;

    origPreviewImg.src = origSrc;
    overlayPreviewImg.src = overSrc;
    singleOverlayImg.src = overSrc;
    sliderOrigImg.src = origSrc;
    sliderOverlayImg.src = overSrc;

    // Per-Leaf Table (compatible with both LeafMeasurementOut and extended fields)
    leafTableBody.innerHTML = "";
    const leaves = img.leaves || [];
    let sumPx = 0;
    let sumPerim = 0;

    leaves.forEach(function (lf) {
      const areaCm2 = numVal(lf.area_cm2 !== undefined ? lf.area_cm2 : lf.net_area_cm2, 0);
      const areaPx = numVal(lf.area_px, 0);
      const lengthCm = numVal(lf.length_cm, 0);
      const widthCm = numVal(lf.width_cm, 0);
      const perimCm = numVal(lf.perimeter_cm, 0);
      const aspect = widthCm > 0 ? lengthCm / widthCm : numVal(lf.aspect_ratio, 1.0);
      const solidity = numVal(lf.solidity, 1.0);
      const cx = Array.isArray(lf.centroid_px) ? numVal(lf.centroid_px[0], 0) : 0;
      const cy = Array.isArray(lf.centroid_px) ? numVal(lf.centroid_px[1], 0) : 0;
      const isTouching = Boolean(
        lf.is_possible_touching !== undefined ? lf.is_possible_touching : lf.possible_touching_leaves
      );
      const touchesBorder = Boolean(lf.touches_border);

      sumPx += areaPx;
      sumPerim += perimCm;

      const tr = document.createElement("tr");
      let statusHtml = '<span class="status-chip status-chip-ok">Measured</span>';
      if (touchesBorder && isTouching) {
        statusHtml = '<span class="status-chip status-chip-danger">Cut off &amp; Possible touching</span>';
      } else if (touchesBorder) {
        statusHtml = '<span class="status-chip status-chip-danger">Cut off at border</span>';
      } else if (isTouching) {
        statusHtml = '<span class="status-chip status-chip-warn">Possible touching</span>';
      }

      tr.innerHTML =
        "<td><strong>#" + lf.leaf_id + "</strong></td>" +
        '<td class="num"><strong>' + fmtFixed(areaCm2, 2) + "</strong></td>" +
        '<td class="num">' + Math.round(areaPx).toLocaleString() + "</td>" +
        '<td class="num">' + fmtFixed(lengthCm, 2) + "</td>" +
        '<td class="num">' + fmtFixed(widthCm, 2) + "</td>" +
        '<td class="num">' + fmtFixed(perimCm, 2) + "</td>" +
        '<td class="num">' + fmtFixed(aspect, 2) + "</td>" +
        '<td class="num">' + fmtFixed(solidity, 3) + "</td>" +
        '<td class="num">(' + fmtFixed(cx, 1) + ", " + fmtFixed(cy, 1) + ")</td>" +
        "<td>" + statusHtml + "</td>";
      leafTableBody.appendChild(tr);
    });

    const totalTr = document.createElement("tr");
    totalTr.className = "total-row";
    totalTr.innerHTML =
      "<td>TOTAL</td>" +
      '<td class="num">' + fmtFixed(img.total_area_cm2, 2) + "</td>" +
      '<td class="num">' + Math.round(numVal(img.total_area_px, sumPx)).toLocaleString() + "</td>" +
      '<td class="num">&mdash;</td>' +
      '<td class="num">&mdash;</td>' +
      '<td class="num">' + fmtFixed(sumPerim, 2) + "</td>" +
      '<td class="num">&mdash;</td>' +
      '<td class="num">&mdash;</td>' +
      '<td class="num">&mdash;</td>' +
      "<td>" + leaves.length + (leaves.length === 1 ? " leaf" : " leaves") + "</td>";
    leafTableBody.appendChild(totalTr);
  }

  // ---------------------------------------------------------------------------
  // 10. Image Comparison Modes & Slider
  // ---------------------------------------------------------------------------
  function setViewMode(mode) {
    activeViewMode = mode;
    viewModeButtons.forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-view-mode") === mode);
    });
    viewSideBySide.classList.toggle("hidden", mode !== "side-by-side");
    viewSlider.classList.toggle("hidden", mode !== "slider");
    viewOverlayOnly.classList.toggle("hidden", mode !== "overlay");
  }

  viewModeButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setViewMode(btn.getAttribute("data-view-mode"));
    });
  });

  if (compareSlider) {
    compareSlider.addEventListener("input", function () {
      const pct = Number(compareSlider.value);
      const rightInset = 100 - pct;
      sliderClipBefore.style.clipPath = "inset(0 " + rightInset + "% 0 0)";
      sliderDivider.style.left = pct + "%";
    });
  }

  // ---------------------------------------------------------------------------
  // 11. Lightbox Zoom & Pan
  // ---------------------------------------------------------------------------
  function applyLightboxTransform() {
    lightboxImg.style.transform =
      "translate(" + panX + "px, " + panY + "px) scale(" + zoomScale + ")";
    zoomLevelLabel.textContent = Math.round(zoomScale * 100) + "%";
  }

  function openLightbox(layer) {
    if (!currentResponse) return;
    lightboxLayer = layer || "overlay";
    zoomScale = 1;
    panX = 0;
    panY = 0;
    updateLightboxImage();
    applyLightboxTransform();
    lightboxModal.classList.remove("hidden");
    btnCloseLightbox.focus();
  }

  function updateLightboxImage() {
    const isOrig = lightboxLayer === "original";
    btnLbOverlay.classList.toggle("active", !isOrig);
    btnLbOriginal.classList.toggle("active", isOrig);
    lightboxImg.src = isOrig ? origPreviewImg.src : overlayPreviewImg.src;
    lightboxTitle.textContent = isOrig ? "Original photo inspection" : "Segmented overlay inspection";
  }

  function closeLightbox() {
    lightboxModal.classList.add("hidden");
  }

  if (boxOrigImg) boxOrigImg.addEventListener("click", function () { openLightbox("original"); });
  if (boxOverlayImg) boxOverlayImg.addEventListener("click", function () { openLightbox("overlay"); });
  if (boxSingleOverlay) boxSingleOverlay.addEventListener("click", function () { openLightbox("overlay"); });
  if (btnOpenZoom) btnOpenZoom.addEventListener("click", function () { openLightbox("overlay"); });
  if (btnCloseLightbox) btnCloseLightbox.addEventListener("click", closeLightbox);

  if (btnLbOverlay) {
    btnLbOverlay.addEventListener("click", function () {
      lightboxLayer = "overlay";
      updateLightboxImage();
    });
  }
  if (btnLbOriginal) {
    btnLbOriginal.addEventListener("click", function () {
      lightboxLayer = "original";
      updateLightboxImage();
    });
  }

  if (btnZoomIn) {
    btnZoomIn.addEventListener("click", function () {
      zoomScale = Math.min(8, zoomScale * 1.25);
      applyLightboxTransform();
    });
  }
  if (btnZoomOut) {
    btnZoomOut.addEventListener("click", function () {
      zoomScale = Math.max(0.5, zoomScale / 1.25);
      applyLightboxTransform();
    });
  }
  if (btnZoomReset) {
    btnZoomReset.addEventListener("click", function () {
      zoomScale = 1;
      panX = 0;
      panY = 0;
      applyLightboxTransform();
    });
  }

  if (lightboxViewport) {
    lightboxViewport.addEventListener("wheel", function (e) {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      zoomScale = Math.min(8, Math.max(0.5, zoomScale * factor));
      applyLightboxTransform();
    });

    lightboxViewport.addEventListener("mousedown", function (e) {
      isDragging = true;
      dragStartX = e.clientX - panX;
      dragStartY = e.clientY - panY;
      lightboxViewport.classList.add("dragging");
    });

    window.addEventListener("mousemove", function (e) {
      if (!isDragging) return;
      panX = e.clientX - dragStartX;
      panY = e.clientY - dragStartY;
      applyLightboxTransform();
    });

    window.addEventListener("mouseup", function () {
      isDragging = false;
      lightboxViewport.classList.remove("dragging");
    });
  }

  // ---------------------------------------------------------------------------
  // 12. Copy Summary to Clipboard
  // ---------------------------------------------------------------------------
  if (btnCopySummary) {
    btnCopySummary.addEventListener("click", function () {
      if (!currentResponse) return;
      const batch = currentResponse.batch_summary || {};
      const img = (currentResponse.images || [])[activeImageIndex] || currentResponse.images[0] || {};
      const totalArea = numVal(batch.total_leaf_area_cm2, img.total_area_cm2);
      const totalUnc = numVal(
        batch.total_uncertainty_cm2 !== undefined ? batch.total_uncertainty_cm2 : batch.uncertainty_cm2,
        img.uncertainty_cm2
      );
      const lines = [
        "LeafArea & LAI Analyzer v" + (appVersionBadge ? appVersionBadge.textContent.replace(/^v/, "") : "1.5.6"),
        "File: " + (img.filename || "Batch"),
        "Total Leaf Area: " + fmtFixed(totalArea, 2) + " ± " + fmtFixed(totalUnc, 2) + " cm²",
        "Number of Leaves: " + numVal(batch.total_leaf_count, img.leaf_count),
        "LAI: " + (batch.lai !== null && batch.lai !== undefined ? fmtFixed(batch.lai, 3) : "N/A (Leaf area only)"),
        "Scale: " + (img.px_per_cm ? fmtFixed(img.px_per_cm, 2) + " px/cm (" + img.calibration_method + ")" : "Uncalibrated"),
        "Confidence: " + (batch.overall_confidence || img.confidence || "HIGH"),
      ];
      navigator.clipboard.writeText(lines.join("\n")).then(function () {
        copySummaryText.textContent = "Copied!";
        setTimeout(function () {
          copySummaryText.textContent = "Copy summary";
        }, 1800);
      });
    });
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  updateSettingsSummary();
})();
