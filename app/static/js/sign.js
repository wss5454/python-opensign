/* global pdfjsLib */

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

const SIGNATURE_FONTS = [
  { id: "dancing", label: "Dancing Script", family: '"Dancing Script", cursive' },
  { id: "great-vibes", label: "Great Vibes", family: '"Great Vibes", cursive' },
  { id: "pacifico", label: "Pacifico", family: '"Pacifico", cursive' },
  { id: "satisfy", label: "Satisfy", family: '"Satisfy", cursive' },
  { id: "allura", label: "Allura", family: '"Allura", cursive' },
];

function normalizePct(value) {
  if (value > 100) return value <= 1000 ? value / 10 : Math.min(value / 10, 100);
  return value;
}

function createCanvasController(canvas) {
  const ctx = canvas.getContext("2d");
  const state = { hasInk: false };

  return {
    canvas,
    ctx,
    clear() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      state.hasInk = false;
    },
    markInk() {
      state.hasInk = true;
    },
    hasInk: () => state.hasInk,
    toDataURL: () => canvas.toDataURL("image/png"),
    drawImageContain(img) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const scale = Math.min(canvas.width / img.width, canvas.height / img.height);
      const w = img.width * scale;
      const h = img.height * scale;
      const x = (canvas.width - w) / 2;
      const y = (canvas.height - h) / 2;
      ctx.drawImage(img, x, y, w, h);
      state.hasInk = true;
    },
    drawText(text, fontFamily) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const value = (text || "").trim();
      if (!value) {
        state.hasInk = false;
        return false;
      }
      let size = Math.floor(canvas.height * 0.55);
      ctx.fillStyle = "#14201a";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      do {
        ctx.font = `700 ${size}px ${fontFamily}`;
        if (ctx.measureText(value).width <= canvas.width * 0.92) break;
        size -= 2;
      } while (size > 18);
      ctx.fillText(value, canvas.width / 2, canvas.height / 2);
      state.hasInk = true;
      return true;
    },
  };
}

function enableDrawing(canvas, controller) {
  const ctx = controller.ctx;
  let drawing = false;

  function pos(e) {
    const rect = canvas.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    return {
      x: ((clientX - rect.left) / rect.width) * canvas.width,
      y: ((clientY - rect.top) / rect.height) * canvas.height,
    };
  }

  function start(e) {
    e.preventDefault();
    drawing = true;
    const p = pos(e);
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
  }

  function move(e) {
    if (!drawing) return;
    e.preventDefault();
    const p = pos(e);
    ctx.lineWidth = 2.4;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#14201a";
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    controller.markInk();
  }

  function end() {
    drawing = false;
  }

  canvas.addEventListener("mousedown", start);
  canvas.addEventListener("mousemove", move);
  window.addEventListener("mouseup", end);
  canvas.addEventListener("touchstart", start, { passive: false });
  canvas.addEventListener("touchmove", move, { passive: false });
  canvas.addEventListener("touchend", end);
}

function createSignatureModal({ defaultName }) {
  const modal = document.getElementById("sign-modal");
  if (!modal) return null;

  const drawCanvas = document.getElementById("modal-draw-canvas");
  const drawPad = createCanvasController(drawCanvas);
  enableDrawing(drawCanvas, drawPad);

  const typeInput = document.getElementById("modal-type-text");
  const fontList = document.getElementById("font-style-list");
  const uploadInput = document.getElementById("modal-upload-input");
  const uploadPreview = document.getElementById("modal-upload-preview");
  const modalError = document.getElementById("modal-error");
  const applyBtn = document.getElementById("modal-apply");

  let activeTab = "draw";
  let selectedFont = SIGNATURE_FONTS[0];
  let uploadedImage = null;
  let onApply = null;

  SIGNATURE_FONTS.forEach((font, index) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `font-style-option${index === 0 ? " selected" : ""}`;
    btn.dataset.fontId = font.id;
    btn.style.fontFamily = font.family;
    btn.textContent = typeInput.value || defaultName || "Your Name";
    btn.addEventListener("click", () => {
      selectedFont = font;
      fontList.querySelectorAll(".font-style-option").forEach((el) => {
        el.classList.toggle("selected", el === btn);
      });
    });
    fontList.appendChild(btn);
  });

  function refreshFontPreviews() {
    const text = typeInput.value.trim() || "Your Name";
    fontList.querySelectorAll(".font-style-option").forEach((el) => {
      el.textContent = text;
    });
  }

  typeInput.addEventListener("input", refreshFontPreviews);

  function setTab(tab) {
    activeTab = tab;
    modal.querySelectorAll(".sign-tab").forEach((el) => {
      el.classList.toggle("active", el.dataset.tab === tab);
    });
    modal.querySelectorAll(".sign-tab-panel").forEach((el) => {
      const match = el.dataset.panel === tab;
      el.hidden = !match;
      el.classList.toggle("active", match);
    });
    modalError.hidden = true;
  }

  modal.querySelectorAll(".sign-tab").forEach((tabBtn) => {
    tabBtn.addEventListener("click", () => setTab(tabBtn.dataset.tab));
  });

  document.getElementById("modal-draw-clear").addEventListener("click", () => {
    drawPad.clear();
  });

  uploadInput.addEventListener("change", () => {
    modalError.hidden = true;
    const file = uploadInput.files && uploadInput.files[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      modalError.textContent = "Please choose an image file.";
      modalError.hidden = false;
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        uploadedImage = img;
        uploadPreview.src = reader.result;
        uploadPreview.hidden = false;
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });

  function close() {
    modal.hidden = true;
    document.body.classList.remove("modal-open");
    onApply = null;
  }

  modal.querySelectorAll("[data-close-modal]").forEach((el) => {
    el.addEventListener("click", close);
  });

  applyBtn.addEventListener("click", () => {
    modalError.hidden = true;
    if (!onApply) return;

    const temp = document.createElement("canvas");
    temp.width = 640;
    temp.height = 220;
    const tempPad = createCanvasController(temp);

    if (activeTab === "draw") {
      if (!drawPad.hasInk()) {
        modalError.textContent = "Please draw your signature first.";
        modalError.hidden = false;
        return;
      }
      onApply(drawPad.toDataURL());
      close();
      return;
    }

    if (activeTab === "type") {
      const ok = tempPad.drawText(typeInput.value, selectedFont.family);
      if (!ok) {
        modalError.textContent = "Please type your name.";
        modalError.hidden = false;
        return;
      }
      onApply(tempPad.toDataURL());
      close();
      return;
    }

    if (activeTab === "upload") {
      if (!uploadedImage) {
        modalError.textContent = "Please upload an image first.";
        modalError.hidden = false;
        return;
      }
      tempPad.drawImageContain(uploadedImage);
      onApply(tempPad.toDataURL());
      close();
    }
  });

  return {
    open({ onInsert }) {
      onApply = onInsert;
      setTab("draw");
      drawPad.clear();
      typeInput.value = defaultName || "";
      selectedFont = SIGNATURE_FONTS[0];
      fontList.querySelectorAll(".font-style-option").forEach((el, idx) => {
        el.classList.toggle("selected", idx === 0);
      });
      refreshFontPreviews();
      uploadedImage = null;
      uploadInput.value = "";
      uploadPreview.hidden = true;
      uploadPreview.removeAttribute("src");
      modalError.hidden = true;
      modal.hidden = false;
      document.body.classList.add("modal-open");
    },
    close,
  };
}

function showToast(message, type = "warn") {
  const root = document.getElementById("toast-root");
  if (!root) {
    window.alert(message);
    return;
  }
  const toast = document.createElement("div");
  toast.className = `sw-toast ${type}`;
  toast.innerHTML = `
    <span class="sw-toast-icon">${type === "success" ? "✓" : "!"}</span>
    <span class="sw-toast-msg"></span>
    <button type="button" class="sw-toast-close" aria-label="Dismiss">&times;</button>
  `;
  toast.querySelector(".sw-toast-msg").textContent = message;
  const remove = () => toast.remove();
  toast.querySelector(".sw-toast-close").addEventListener("click", remove);
  root.appendChild(toast);
  setTimeout(remove, 4200);
}

function openDeclineDialog() {
  return new Promise((resolve) => {
    const dialog = document.getElementById("decline-dialog");
    if (!dialog) {
      resolve(window.confirm("Decline to sign this document?"));
      return;
    }
    dialog.hidden = false;
    document.body.classList.add("modal-open");

    const cleanup = (result) => {
      dialog.hidden = true;
      document.body.classList.remove("modal-open");
      confirmBtn.removeEventListener("click", onConfirm);
      cancelEls.forEach((el) => el.removeEventListener("click", onCancel));
      resolve(result);
    };
    const onConfirm = () => cleanup(true);
    const onCancel = () => cleanup(false);
    const confirmBtn = document.getElementById("decline-confirm");
    const cancelEls = dialog.querySelectorAll("[data-decline-cancel]");
    confirmBtn.addEventListener("click", onConfirm);
    cancelEls.forEach((el) => el.addEventListener("click", onCancel));
  });
}

function setupConsentGate() {
  const consentModal = document.getElementById("consent-modal");
  const shell = document.getElementById("sign-shell");
  const continueBtn = document.getElementById("consent-continue");
  if (!consentModal || !continueBtn) return;

  continueBtn.addEventListener("click", () => {
    consentModal.hidden = true;
    if (shell) shell.dataset.locked = "false";
  });

  const disclosureModal = document.getElementById("disclosure-modal");
  document.getElementById("disclosure-link")?.addEventListener("click", (e) => {
    e.preventDefault();
    if (disclosureModal) disclosureModal.hidden = false;
  });
  document.querySelectorAll("[data-close-disclosure]").forEach((el) => {
    el.addEventListener("click", () => {
      if (disclosureModal) disclosureModal.hidden = true;
    });
  });
}

async function renderSigningViewer(root) {
  const token = root.dataset.token;
  const pdfUrl = root.dataset.pdfUrl;
  const signerName = root.dataset.signerName || "";
  const widgetsEl = document.getElementById("widgets-data");
  const widgets = JSON.parse(widgetsEl ? widgetsEl.textContent : "[]");
  const pads = new Map();
  const modal = createSignatureModal({ defaultName: signerName });
  const thumbsEl = document.getElementById("page-thumbs");
  const pageLabel = document.getElementById("page-label");

  let scale = 1.2;
  let currentPage = 1;
  let pdfDoc = null;
  const pageEls = [];

  async function renderAll() {
    root.innerHTML = "";
    pageEls.length = 0;
    if (thumbsEl) thumbsEl.innerHTML = "";

    for (let pageNum = 1; pageNum <= pdfDoc.numPages; pageNum++) {
      const page = await pdfDoc.getPage(pageNum);
      const viewport = page.getViewport({ scale });

      const pageWrap = document.createElement("div");
      pageWrap.className = "pdf-page sw-page";
      pageWrap.dataset.page = String(pageNum);
      pageWrap.style.width = `${viewport.width}px`;
      pageWrap.style.height = `${viewport.height}px`;
      if (pageNum !== currentPage) pageWrap.hidden = true;

      const pageCanvas = document.createElement("canvas");
      pageCanvas.width = viewport.width;
      pageCanvas.height = viewport.height;
      pageWrap.appendChild(pageCanvas);
      await page.render({
        canvasContext: pageCanvas.getContext("2d"),
        viewport,
        annotationMode: pdfjsLib.AnnotationMode.ENABLE,
      }).promise;

      const pageWidgets = widgets.filter((w) => Number(w.page) === pageNum);
      for (const widget of pageWidgets) {
        if (!["signature", "initials", "stamp"].includes(widget.type)) continue;

        const box = document.createElement("div");
        box.className = "sign-widget";
        box.style.left = `${normalizePct(widget.x)}%`;
        box.style.top = `${normalizePct(widget.y)}%`;
        box.style.width = `${normalizePct(widget.w)}%`;
        box.style.height = `${normalizePct(widget.h)}%`;
        box.title = "Click to add signature";

        const label = document.createElement("div");
        label.className = "sign-widget-label";
        label.textContent = "signature";
        box.appendChild(label);

        const sigCanvas = document.createElement("canvas");
        const boxW = Math.max(80, (normalizePct(widget.w) / 100) * viewport.width);
        const boxH = Math.max(40, (normalizePct(widget.h) / 100) * viewport.height);
        sigCanvas.width = Math.round(boxW * 2);
        sigCanvas.height = Math.round(boxH * 2);
        sigCanvas.className = "sign-widget-canvas";
        box.appendChild(sigCanvas);

        const existing = pads.get(widget.id);
        const pad = createCanvasController(sigCanvas);
        if (existing && existing.hasInk()) {
          const img = new Image();
          img.onload = () => pad.drawImageContain(img);
          img.src = existing.toDataURL();
          box.classList.add("signed");
          label.textContent = "Signed";
        }
        pads.set(widget.id, pad);

        box.addEventListener("click", () => {
          if (document.getElementById("sign-shell")?.dataset.locked === "true") return;
          modal?.open({
            onInsert(dataUrl) {
              const img = new Image();
              img.onload = () => {
                pad.drawImageContain(img);
                box.classList.add("signed");
                label.textContent = "Signed";
                updateThumbChecks();
              };
              img.src = dataUrl;
            },
          });
        });

        pageWrap.appendChild(box);
      }

      root.appendChild(pageWrap);
      pageEls.push(pageWrap);

      if (thumbsEl) {
        const thumbBtn = document.createElement("button");
        thumbBtn.type = "button";
        thumbBtn.className = `sw-thumb${pageNum === currentPage ? " active" : ""}`;
        thumbBtn.dataset.page = String(pageNum);
        const thumbCanvas = document.createElement("canvas");
        const thumbViewport = page.getViewport({ scale: 0.18 });
        thumbCanvas.width = thumbViewport.width;
        thumbCanvas.height = thumbViewport.height;
        await page.render({
          canvasContext: thumbCanvas.getContext("2d"),
          viewport: thumbViewport,
          annotationMode: pdfjsLib.AnnotationMode.ENABLE,
        }).promise;
        thumbBtn.appendChild(thumbCanvas);
        const check = document.createElement("span");
        check.className = "sw-thumb-check";
        check.textContent = "✓";
        thumbBtn.appendChild(check);
        thumbBtn.addEventListener("click", () => showPage(pageNum));
        thumbsEl.appendChild(thumbBtn);
      }
    }

    updatePageLabel();
    updateThumbChecks();
  }

  function updatePageLabel() {
    if (pageLabel && pdfDoc) {
      pageLabel.textContent = `${currentPage} of ${pdfDoc.numPages}`;
    }
  }

  function updateThumbChecks() {
    const signedPages = new Set();
    widgets.forEach((w) => {
      const pad = pads.get(w.id);
      if (pad && pad.hasInk()) signedPages.add(Number(w.page));
    });
    document.querySelectorAll(".sw-thumb").forEach((thumb) => {
      const page = Number(thumb.dataset.page);
      thumb.classList.toggle("checked", signedPages.has(page));
      thumb.classList.toggle("active", page === currentPage);
    });
  }

  function showPage(pageNum) {
    currentPage = pageNum;
    pageEls.forEach((el) => {
      el.hidden = Number(el.dataset.page) !== pageNum;
    });
    updatePageLabel();
    updateThumbChecks();
  }

  pdfDoc = await pdfjsLib.getDocument(pdfUrl).promise;
  await renderAll();

  document.getElementById("zoom-in")?.addEventListener("click", async () => {
    scale = Math.min(2.4, scale + 0.15);
    await renderAll();
    showPage(currentPage);
  });
  document.getElementById("zoom-out")?.addEventListener("click", async () => {
    scale = Math.max(0.7, scale - 0.15);
    await renderAll();
    showPage(currentPage);
  });
  document.getElementById("prev-page")?.addEventListener("click", () => {
    if (currentPage > 1) showPage(currentPage - 1);
  });
  document.getElementById("next-page")?.addEventListener("click", () => {
    if (pdfDoc && currentPage < pdfDoc.numPages) showPage(currentPage + 1);
  });

  document.getElementById("finish-btn")?.addEventListener("click", async () => {
    const signatures = [];
    for (const [widgetId, pad] of pads.entries()) {
      if (!pad.hasInk()) {
        showToast("Please complete every signature field before finishing.", "warn");
        return;
      }
      signatures.push({ widget_id: widgetId, signature_data: pad.toDataURL() });
    }

    if (!signatures.length) {
      showToast("No signature widgets found for this signer.", "warn");
      return;
    }

    try {
      const res = await fetch(`/api/sign/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ signatures, consent: true }),
      });
      const data = await res.json();
      if (!res.ok) {
        const detail = Array.isArray(data.detail)
          ? data.detail.map((d) => d.msg || d).join(", ")
          : data.detail || "Signing failed";
        throw new Error(detail);
      }
      showToast("Document signed successfully.", "success");
      setTimeout(() => window.location.reload(), 700);
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("decline-btn")?.addEventListener("click", async () => {
    const confirmed = await openDeclineDialog();
    if (!confirmed) return;
    try {
      const res = await fetch(`/api/sign/${token}/decline`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Decline failed");
      showToast("You declined this document.", "success");
      setTimeout(() => window.location.reload(), 700);
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

function formatBytes(n) {
  const size = Number(n) || 0;
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function apiError(data, fallback) {
  const detail = data && data.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    if (typeof first === "string") return first;
    if (first && first.msg) return first.msg;
  }
  return fallback;
}

function setupAttachments(token) {
  const listEl = document.getElementById("attach-list");
  const input = document.getElementById("attach-input");
  if (!listEl || !input || !token) return;

  async function refresh() {
    const res = await fetch(`/api/sign/${token}/attachments`);
    const items = await res.json().catch(() => []);
    listEl.replaceChildren();
    if (!Array.isArray(items) || !items.length) {
      const empty = document.createElement("li");
      empty.className = "muted";
      empty.textContent = "No files added yet.";
      listEl.appendChild(empty);
      return;
    }
    items.forEach((item) => {
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.append(String(item.filename || "file"));
      const size = document.createElement("span");
      size.className = "muted";
      size.textContent = ` (${formatBytes(item.size_bytes)})`;
      label.appendChild(size);

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "sw-attach-remove";
      remove.textContent = "Remove";
      remove.addEventListener("click", async () => {
        const del = await fetch(`/api/sign/${token}/attachments/${item.id}`, {
          method: "DELETE",
        });
        if (!del.ok) {
          const data = await del.json().catch(() => ({}));
          showToast(apiError(data, "Could not remove file"), "error");
          return;
        }
        await refresh();
      });
      li.append(label, remove);
      listEl.appendChild(li);
    });
  }

  input.addEventListener("change", async () => {
    const files = Array.from(input.files || []);
    input.value = "";
    for (const file of files) {
      const fd = new FormData();
      fd.append("file", file, file.name);
      try {
        const res = await fetch(`/api/sign/${token}/attachments`, {
          method: "POST",
          body: fd,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(apiError(data, `Could not upload ${file.name}`));
        }
      } catch (err) {
        showToast(err.message, "error");
      }
    }
    await refresh();
  });

  refresh().catch(() => {});
}

setupConsentGate();
setupAttachments(document.getElementById("pdf-viewer")?.dataset.token);

const viewer = document.getElementById("pdf-viewer");
if (viewer) {
  renderSigningViewer(viewer).catch((err) => {
    showToast(`Failed to load PDF: ${err.message}`, "error");
  });
}
