async function postAction(url) {
  const res = await fetch(url, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

const sendBtn = document.getElementById("send-btn");
const voidBtn = document.getElementById("void-btn");
const deleteBtn = document.getElementById("delete-btn");

if (sendBtn) {
  sendBtn.addEventListener("click", async () => {
    try {
      await postAction(`/api/documents/${sendBtn.dataset.id}/send`);
      window.location.reload();
    } catch (err) {
      alert(err.message);
    }
  });
}

if (voidBtn) {
  voidBtn.addEventListener("click", async () => {
    if (!confirm("Void this document? Signers will no longer be able to sign.")) return;
    try {
      await postAction(`/api/documents/${voidBtn.dataset.id}/void`);
      window.location.reload();
    } catch (err) {
      alert(err.message);
    }
  });
}

if (deleteBtn) {
  deleteBtn.addEventListener("click", async () => {
    if (!confirm("Delete this document permanently? This cannot be undone.")) return;
    try {
      const res = await fetch(`/api/documents/${deleteBtn.dataset.id}`, {
        method: "DELETE",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Failed to delete document");
      window.location.href = "/";
    } catch (err) {
      alert(err.message);
    }
  });
}

document.querySelectorAll(".btn-copy").forEach((btn) => {
  btn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(btn.dataset.url);
      btn.textContent = "Copied";
      setTimeout(() => (btn.textContent = "Copy"), 1200);
    } catch {
      prompt("Copy this signing link:", btn.dataset.url);
    }
  });
});
