const SLOT_W = 28;
const SLOT_H = 10;
const GAP_X = 6;
const GAP_Y = 4;
const MARGIN_X = 8;
const START_Y = 82;
const MIN_Y = 8;
const COLS = 2;

function slotsPerPage() {
  const rows = Math.max(1, Math.floor((START_Y - MIN_Y) / (SLOT_H + GAP_Y)) + 1);
  return COLS * rows;
}

function slotPosition(slotIndex) {
  const perPage = slotsPerPage();
  const page = 1 + Math.floor(slotIndex / perPage);
  const local = slotIndex % perPage;
  const col = local % COLS;
  const row = Math.floor(local / COLS);
  return {
    type: "signature",
    page,
    x: Number((MARGIN_X + col * (SLOT_W + GAP_X)).toFixed(2)),
    y: Number((START_Y - row * (SLOT_H + GAP_Y)).toFixed(2)),
    w: SLOT_W,
    h: SLOT_H,
  };
}

function widgetsOverlap(a, b) {
  if (Number(a.page) !== Number(b.page)) return false;
  const pad = 0.5;
  return !(
    a.x + a.w + pad <= b.x ||
    b.x + b.w + pad <= a.x ||
    a.y + a.h + pad <= b.y ||
    b.y + b.h + pad <= a.y
  );
}

function formatWidgets(widgets) {
  return JSON.stringify(widgets, null, 0);
}

function signerRow() {
  const row = document.createElement("div");
  row.className = "signer-card";
  row.innerHTML = `
    <div class="signer-row">
      <span class="signer-order-badge" data-field="order-label">#1</span>
      <input type="text" placeholder="Full name" required data-field="name" />
      <input type="email" placeholder="Email" required data-field="email" />
      <select data-field="role">
        <option value="signer">Signer</option>
        <option value="approver">Approver</option>
        <option value="viewer">Viewer</option>
      </select>
      <button type="button" class="btn btn-ghost remove">Remove</button>
    </div>
    <div class="widget-meta muted" data-field="widget-meta"></div>
    <label class="widgets-label">
      Widgets JSON (auto-ordered, non-overlapping)
      <textarea data-field="widgets" rows="3"></textarea>
    </label>
  `;

  row.querySelector(".remove").addEventListener("click", () => {
    row.remove();
    relayoutAllSignerWidgets();
  });

  row.querySelector('[data-field="role"]').addEventListener("change", () => {
    relayoutAllSignerWidgets();
  });

  return row;
}

function actionableCards() {
  return [...signersEl.querySelectorAll(".signer-card")].filter((card) => {
    const role = card.querySelector('[data-field="role"]').value;
    return role !== "viewer";
  });
}

function relayoutAllSignerWidgets() {
  const cards = [...signersEl.querySelectorAll(".signer-card")];
  let slot = 0;

  cards.forEach((card, index) => {
    const role = card.querySelector('[data-field="role"]').value;
    const ta = card.querySelector('[data-field="widgets"]');
    const meta = card.querySelector('[data-field="widget-meta"]');
    const orderLabel = card.querySelector('[data-field="order-label"]');
    orderLabel.textContent = `#${index + 1}`;

    if (role === "viewer") {
      ta.value = "[]";
      meta.textContent = "Viewer — no signature widget";
      return;
    }

    const widget = slotPosition(slot);
    slot += 1;
    ta.value = formatWidgets([widget]);
    meta.textContent =
      `Sign order ${index + 1} · page ${widget.page} · ` +
      `position (${widget.x}%, ${widget.y}%) · size ${widget.w}%×${widget.h}%`;
  });

  // Extra safety: ensure no overlaps if user manually edits later on submit
  validateNoConflicts(false);
}

function validateNoConflicts(showError) {
  const placed = [];
  for (const card of actionableCards()) {
    let widgets;
    try {
      widgets = JSON.parse(card.querySelector('[data-field="widgets"]').value.trim() || "[]");
    } catch {
      if (showError) throw new Error("Invalid widgets JSON");
      return false;
    }
    for (const w of widgets) {
      if (placed.some((p) => widgetsOverlap(w, p))) {
        if (showError) {
          throw new Error(
            "Signature widgets overlap between signers. Use auto-layout or adjust positions."
          );
        }
        return false;
      }
      placed.push(w);
    }
  }
  return true;
}

const signersEl = document.getElementById("signers");
const form = document.getElementById("create-form");
const errorEl = document.getElementById("form-error");

document.getElementById("add-signer").addEventListener("click", () => {
  signersEl.appendChild(signerRow());
  relayoutAllSignerWidgets();
});

signersEl.appendChild(signerRow());
relayoutAllSignerWidgets();

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorEl.hidden = true;

  // Re-apply ordered layout so final payload has no conflicts
  relayoutAllSignerWidgets();

  const rows = [...signersEl.querySelectorAll(".signer-card")];
  if (!rows.length) {
    errorEl.textContent = "Add at least one signer.";
    errorEl.hidden = false;
    return;
  }

  let signers;
  try {
    validateNoConflicts(true);
    signers = rows.map((row, index) => {
      const widgetsRaw = row.querySelector('[data-field="widgets"]').value.trim() || "[]";
      const widgets = JSON.parse(widgetsRaw);
      if (!Array.isArray(widgets)) throw new Error("Widgets must be a JSON array");
      return {
        name: row.querySelector('[data-field="name"]').value.trim(),
        email: row.querySelector('[data-field="email"]').value.trim(),
        role: row.querySelector('[data-field="role"]').value,
        order_index: index,
        widgets,
      };
    });
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.hidden = false;
    return;
  }

  const fd = new FormData();
  fd.append("title", form.title.value.trim());
  fd.append("description", form.description.value.trim());
  fd.append("sequential", form.sequential.checked ? "true" : "false");
  fd.append("signers_json", JSON.stringify(signers));
  fd.append("file", form.file.files[0]);

  try {
    const res = await fetch("/api/documents", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map((d) => d.msg || d).join(", ")
        : data.detail || "Failed to create document";
      throw new Error(detail);
    }
    window.location.href = `/documents/${data.id}`;
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.hidden = false;
  }
});
