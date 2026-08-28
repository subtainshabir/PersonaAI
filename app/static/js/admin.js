const adminSidebar = document.getElementById("adminSidebar");
const adminSidebarToggle = document.getElementById("adminSidebarToggle");
const adminSidebarOverlay = document.getElementById("adminSidebarOverlay");
const adminThemeToggle = document.getElementById("adminThemeToggle");

function closeAdminSidebar() {
  adminSidebar.classList.remove("open");
  adminSidebarOverlay.classList.remove("open");
}

if (adminSidebarToggle) {
  adminSidebarToggle.addEventListener("click", () => {
    adminSidebar.classList.add("open");
    adminSidebarOverlay.classList.add("open");
  });
}

if (adminSidebarOverlay) {
  adminSidebarOverlay.addEventListener("click", closeAdminSidebar);
}

function applyAdminTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const icon = adminThemeToggle.querySelector("i");
  icon.className = theme === "dark" ? "bi bi-sun" : "bi bi-moon-stars";
}

const savedAdminTheme = localStorage.getItem("personaai-theme") || "light";
applyAdminTheme(savedAdminTheme);

adminThemeToggle.addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme");
  const next = current === "dark" ? "light" : "dark";
  localStorage.setItem("personaai-theme", next);
  applyAdminTheme(next);
});

const kbUploadForm = document.getElementById("kbUploadForm");
const kbFileInput = document.getElementById("kbFileInput");
const kbFileLabel = document.getElementById("kbFileLabel");
const kbUploadBtn = document.getElementById("kbUploadBtn");
const kbUploadStatus = document.getElementById("kbUploadStatus");
const kbDropzone = document.getElementById("kbDropzone");

if (kbUploadForm) {
  function setSelectedFile(fileList) {
    if (fileList && fileList.length > 0) {
      kbFileLabel.textContent = fileList[0].name;
      kbUploadBtn.disabled = false;
    } else {
      kbFileLabel.textContent = "Choose a file or drag it here";
      kbUploadBtn.disabled = true;
    }
  }

  kbFileInput.addEventListener("change", () => setSelectedFile(kbFileInput.files));

  kbDropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    kbDropzone.classList.add("dragover");
  });

  kbDropzone.addEventListener("dragleave", () => {
    kbDropzone.classList.remove("dragover");
  });

  kbDropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    kbDropzone.classList.remove("dragover");
    if (event.dataTransfer.files.length > 0) {
      kbFileInput.files = event.dataTransfer.files;
      setSelectedFile(kbFileInput.files);
    }
  });

  kbUploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (kbFileInput.files.length === 0) return;

    const formData = new FormData();
    formData.append("file", kbFileInput.files[0]);

    kbUploadBtn.disabled = true;
    kbUploadBtn.innerHTML = '<i class="bi bi-arrow-repeat"></i> Uploading...';
    kbUploadStatus.hidden = true;

    try {
      const response = await fetch("/admin/knowledge/upload", {
        method: "POST",
        body: formData,
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Upload failed.");
      }

      kbUploadStatus.textContent = `"${data.filename}" was added — ${data.total_chunks} chunk(s) indexed.`;
      kbUploadStatus.className = "admin-upload-status success";
      kbUploadStatus.hidden = false;

      setTimeout(() => window.location.reload(), 1200);
    } catch (error) {
      kbUploadStatus.textContent = error.message;
      kbUploadStatus.className = "admin-upload-status error";
      kbUploadStatus.hidden = false;
      kbUploadBtn.disabled = false;
      kbUploadBtn.innerHTML = '<i class="bi bi-upload"></i> Upload';
    }
  });
}

const kbDocList = document.getElementById("kbDocList");

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

if (kbDocList) {
  kbDocList.addEventListener("change", (event) => {
    const fileInput = event.target.closest(".kb-doc-replace-input");
    if (!fileInput) return;

    const panel = fileInput.closest(".kb-doc-replace-panel");
    const filenameSpan = panel.querySelector(".kb-doc-replace-filename");
    const confirmBtn = panel.querySelector(".kb-doc-replace-confirm-btn");

    if (fileInput.files.length > 0) {
      filenameSpan.textContent = fileInput.files[0].name;
      confirmBtn.disabled = false;
    } else {
      filenameSpan.textContent = "No file selected";
      confirmBtn.disabled = true;
    }
  });

  kbDocList.addEventListener("click", async (event) => {
    const viewBtn = event.target.closest(".kb-doc-view-btn");
    const deleteBtn = event.target.closest(".kb-doc-delete-btn");
    const cancelBtn = event.target.closest(".kb-doc-cancel-delete-btn");
    const confirmBtn = event.target.closest(".kb-doc-confirm-delete-btn");
    const replaceBtn = event.target.closest(".kb-doc-replace-btn");
    const replaceChooseBtn = event.target.closest(".kb-doc-replace-choose-btn");
    const replaceCancelBtn = event.target.closest(".kb-doc-replace-cancel-btn");
    const replaceConfirmBtn = event.target.closest(".kb-doc-replace-confirm-btn");

    if (viewBtn) {
      const row = viewBtn.closest(".admin-kb-doc-row");
      const documentId = row.dataset.documentId;
      const detailPanel = row.nextElementSibling;
      const isOpen = detailPanel.classList.contains("open");
      detailPanel.classList.toggle("open", !isOpen);

      if (!isOpen) {
        setTimeout(() => {
          detailPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }, 50);
      }

      if (isOpen || detailPanel.dataset.loaded === "true") return;

      detailPanel.innerHTML = '<div class="admin-kb-doc-detail-loading">Loading...</div>';
      try {
        const response = await fetch(`/admin/knowledge/documents/${encodeURIComponent(documentId)}`);
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail || "Could not load this document.");
        }

        const chunksHtml = data.chunks
          .map((chunk) => {
            const preview = chunk.text.length > 300 ? `${chunk.text.slice(0, 300)}…` : chunk.text;
            return `<div class="admin-kb-chunk"><span class="admin-kb-chunk-id">#${chunk.chunk_id}</span><p>${escapeHtml(preview)}</p></div>`;
          })
          .join("");

        detailPanel.innerHTML = chunksHtml || "<p>No chunk text available.</p>";
        detailPanel.dataset.loaded = "true";
      } catch (error) {
        detailPanel.innerHTML = `<div class="admin-upload-status error">${escapeHtml(error.message)}</div>`;
      }
      return;
    }

    if (deleteBtn) {
      const row = deleteBtn.closest(".admin-kb-doc-row");
      row.querySelector(".kb-doc-actions").hidden = true;
      row.querySelector(".kb-doc-confirm").hidden = false;
      return;
    }

    if (cancelBtn) {
      const row = cancelBtn.closest(".admin-kb-doc-row");
      row.querySelector(".kb-doc-confirm").hidden = true;
      row.querySelector(".kb-doc-actions").hidden = false;
      return;
    }

    if (confirmBtn) {
      const row = confirmBtn.closest(".admin-kb-doc-row");
      const documentId = row.dataset.documentId;
      const errorSpan = row.querySelector(".kb-doc-confirm .kb-doc-error");
      confirmBtn.disabled = true;
      confirmBtn.textContent = "Deleting...";
      errorSpan.textContent = "";

      try {
        const response = await fetch(`/admin/knowledge/documents/${encodeURIComponent(documentId)}`, {
          method: "DELETE",
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail || "Delete failed.");
        }
        const detailPanel = row.nextElementSibling;
        row.remove();
        if (detailPanel && detailPanel.classList.contains("admin-kb-doc-detail")) {
          detailPanel.remove();
        }
        if (!kbDocList.querySelector(".admin-kb-doc-row")) {
          window.location.reload();
        }
      } catch (error) {
        errorSpan.textContent = error.message;
        confirmBtn.disabled = false;
        confirmBtn.textContent = "Confirm";
      }
      return;
    }

    if (replaceBtn) {
      const row = replaceBtn.closest(".admin-kb-doc-row");
      row.querySelector(".kb-doc-actions").hidden = true;
      row.querySelector(".kb-doc-replace-panel").hidden = false;
      return;
    }

    if (replaceChooseBtn) {
      const panel = replaceChooseBtn.closest(".kb-doc-replace-panel");
      panel.querySelector(".kb-doc-replace-input").click();
      return;
    }

    if (replaceCancelBtn) {
      const row = replaceCancelBtn.closest(".admin-kb-doc-row");
      const panel = row.querySelector(".kb-doc-replace-panel");
      panel.querySelector(".kb-doc-replace-input").value = "";
      panel.querySelector(".kb-doc-replace-filename").textContent = "No file selected";
      panel.querySelector(".kb-doc-replace-confirm-btn").disabled = true;
      panel.querySelector(".kb-doc-replace-status").textContent = "";
      panel.querySelector(".kb-doc-replace-status").className = "kb-doc-error kb-doc-replace-status";
      panel.hidden = true;
      row.querySelector(".kb-doc-actions").hidden = false;
      return;
    }

    if (replaceConfirmBtn) {
      const panel = replaceConfirmBtn.closest(".kb-doc-replace-panel");
      const row = replaceConfirmBtn.closest(".admin-kb-doc-row");
      const documentId = row.dataset.documentId;
      const fileInput = panel.querySelector(".kb-doc-replace-input");
      const statusSpan = panel.querySelector(".kb-doc-replace-status");

      if (fileInput.files.length === 0) return;

      const formData = new FormData();
      formData.append("file", fileInput.files[0]);

      replaceConfirmBtn.disabled = true;
      replaceConfirmBtn.textContent = "Replacing...";
      statusSpan.className = "kb-doc-error kb-doc-replace-status";
      statusSpan.textContent = "";

      try {
        const response = await fetch(
          `/admin/knowledge/documents/${encodeURIComponent(documentId)}/replace`,
          { method: "POST", body: formData }
        );
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail || "Replace failed.");
        }

        row.dataset.documentId = data.document_id;
        row.querySelector(".admin-kb-doc-name").textContent = data.filename;

        const detailPanel = row.nextElementSibling;
        if (detailPanel && detailPanel.classList.contains("admin-kb-doc-detail")) {
          detailPanel.classList.remove("open");
          detailPanel.innerHTML = "";
          delete detailPanel.dataset.loaded;
        }

        statusSpan.className = "kb-doc-error kb-doc-replace-status success";
        statusSpan.textContent = `Replaced — ${data.total_chunks} chunk(s) indexed.`;

        setTimeout(() => window.location.reload(), 1200);
      } catch (error) {
        statusSpan.textContent = error.message;
        replaceConfirmBtn.disabled = false;
        replaceConfirmBtn.textContent = "Replace";
      }
    }
  });
}