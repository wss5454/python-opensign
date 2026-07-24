async function deleteDocument(id, title) {
  const label = title ? `"${title}"` : "this document";
  if (!confirm(`Delete ${label}? This cannot be undone.`)) return;

  const res = await fetch(`/api/documents/${id}`, { method: "DELETE" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || "Failed to delete document");
  }
  return data;
}

document.querySelectorAll(".delete-doc-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    try {
      await deleteDocument(btn.dataset.id, btn.dataset.title);
      window.location.reload();
    } catch (err) {
      alert(err.message);
    }
  });
});

document.querySelectorAll(".menu-toggle").forEach((btn) => {
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const menu = btn.closest(".menu");
    const dropdown = menu.querySelector(".menu-dropdown");
    document.querySelectorAll(".menu-dropdown").forEach((el) => {
      if (el !== dropdown) el.hidden = true;
    });
    dropdown.hidden = !dropdown.hidden;
  });
});

document.addEventListener("click", () => {
  document.querySelectorAll(".menu-dropdown").forEach((el) => {
    el.hidden = true;
  });
});

function bindSearch(inputId, tableId) {
  const input = document.getElementById(inputId);
  const table = document.getElementById(tableId);
  if (!input || !table) return;
  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    table.querySelectorAll("tbody tr").forEach((row) => {
      const hay = row.dataset.search || row.textContent.toLowerCase();
      row.style.display = !q || hay.includes(q) ? "" : "none";
    });
  });
}

bindSearch("search-sent", "sent-table");
bindSearch("search-drafts", "drafts-table");
bindSearch("search-documents", "documents-table");
