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
const kbJobsSection = document.getElementById("kbJobsSection");
const kbJobsList = document.getElementById("kbJobsList");

let kbJobsPollTimer = null;
let kbHadActiveJob = false;

function kbJobBadgeClass(status) {
  if (status === "completed") return "admin-kb-badge admin-kb-badge-ok";
  if (status === "failed") return "admin-kb-badge admin-kb-badge-error";
  return "admin-kb-badge admin-kb-badge-pending";
}

function renderJobs(jobs) {
  if (!kbJobsList || !kbJobsSection) return;

  if (jobs.length === 0) {
    kbJobsSection.hidden = true;
    return;
  }

  kbJobsSection.hidden = false;
  kbJobsList.innerHTML = jobs
    .map((job) => {
      const statusLabel = job.status.charAt(0).toUpperCase() + job.status.slice(1);
      const errorLine =
        job.status === "failed" && job.error
          ? `<div class="kb-doc-error">${escapeHtml(job.error)}</div>`
          : "";
      return `
        <div class="admin-kb-doc-row">
          <div class="admin-kb-doc-icon"><i class="bi bi-file-earmark-arrow-up"></i></div>
          <div class="admin-kb-doc-main">
            <div class="admin-kb-doc-name">${escapeHtml(job.label)}</div>
            <div class="admin-kb-doc-meta">
              <span class="${kbJobBadgeClass(job.status)}">${statusLabel}</span>
            </div>
            ${errorLine}
          </div>
        </div>`;
    })
    .join("");
}

async function refreshJobs() {
  try {
    const response = await fetch("/admin/knowledge/jobs");
    if (!response.ok) return;
    const jobs = await response.json();
    renderJobs(jobs);

    const hasActive = jobs.some((job) => job.status === "pending" || job.status === "processing");

    if (hasActive) {
      kbHadActiveJob = true;
      if (!kbJobsPollTimer) {
        kbJobsPollTimer = setInterval(refreshJobs, 1500);
      }
    } else {
      if (kbJobsPollTimer) {
        clearInterval(kbJobsPollTimer);
        kbJobsPollTimer = null;
      }
      if (kbHadActiveJob) {
        window.location.reload();
      }
    }
  } catch (error) {
    // Best-effort status display — a failed poll just tries again next tick.
  }
}

if (kbJobsList) {
  refreshJobs();
}

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
    kbUploadBtn.innerHTML = '<i class="bi bi-arrow-repeat spinning"></i> Uploading...';
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

      kbUploadStatus.textContent = `"${data.filename}" was accepted and is now processing in the background.`;
      kbUploadStatus.className = "admin-upload-status success";
      kbUploadStatus.hidden = false;

      kbFileInput.value = "";
      setSelectedFile(null);
      refreshJobs();
    } catch (error) {
      kbUploadStatus.textContent = error.message;
      kbUploadStatus.className = "admin-upload-status error";
      kbUploadStatus.hidden = false;
    } finally {
      kbUploadBtn.disabled = false;
      kbUploadBtn.innerHTML = '<i class="bi bi-upload"></i> Upload';
    }
  });
}

const kbRebuildBtn = document.getElementById("kbRebuildBtn");
const kbRebuildStatus = document.getElementById("kbRebuildStatus");

async function runRebuild(button, statusEl) {
  const originalHTML = button.innerHTML;
  button.disabled = true;
  button.innerHTML = '<i class="bi bi-arrow-repeat spinning"></i> Rebuilding...';
  if (statusEl) statusEl.hidden = true;

  try {
    const response = await fetch("/admin/knowledge/rebuild", { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Rebuild failed.");
    }

    const message =
      data.status === "rebuilt"
        ? `Index rebuilt — ${data.total_chunks} chunk(s) across ${data.documents} document(s).`
        : "Nothing to rebuild yet.";

    if (statusEl) {
      statusEl.textContent = message;
      statusEl.className = "admin-upload-status success";
      statusEl.hidden = false;
    }

    setTimeout(() => window.location.reload(), 1200);
  } catch (error) {
    if (statusEl) {
      statusEl.textContent = error.message;
      statusEl.className = "admin-upload-status error";
      statusEl.hidden = false;
    }
    button.disabled = false;
    button.innerHTML = originalHTML;
  }
}

if (kbRebuildBtn) {
  kbRebuildBtn.addEventListener("click", () => runRebuild(kbRebuildBtn, kbRebuildStatus));
}

const kbValidateBtn = document.getElementById("kbValidateBtn");
const kbValidateResult = document.getElementById("kbValidateResult");

function integrityOverallClass(status) {
  return `admin-integrity-overall admin-integrity-overall-${status === "healthy" ? "healthy" : status}`;
}

function renderValidation(data) {
  if (!kbValidateResult) return;

  const overallLabel = data.status.charAt(0).toUpperCase() + data.status.slice(1);
  const stats = `
    <div class="admin-integrity-stats">
      <span>${data.total_documents} document(s)</span>
      <span>${data.total_chunks} chunk(s)</span>
      <span>${data.total_vectors === null ? "—" : data.total_vectors} vector(s)</span>
    </div>`;

  const checksHtml = data.checks
    .map((check) => {
      const icon =
        check.status === "ok"
          ? "bi-check-circle-fill"
          : check.status === "warning"
          ? "bi-exclamation-triangle-fill"
          : check.status === "error"
          ? "bi-x-circle-fill"
          : "bi-question-circle-fill";
      return `
        <div class="admin-integrity-check-row">
          <i class="bi ${icon} admin-integrity-check-icon ${check.status}"></i>
          <div>
            <div class="admin-integrity-check-name">${escapeHtml(check.name.replace(/_/g, " "))}</div>
            <div class="admin-integrity-check-message">${escapeHtml(check.message)}</div>
          </div>
        </div>`;
    })
    .join("");

  const failedHtml =
    data.failed_documents && data.failed_documents.length > 0
      ? `<div class="admin-integrity-failed-list">${data.failed_documents
          .map(
            (doc) =>
              `<div class="admin-integrity-failed-item">${escapeHtml(doc.filename)}: ${escapeHtml(doc.error || "Unknown error")}</div>`
          )
          .join("")}</div>`
      : "";

  const faissIssue = data.checks.some(
    (check) =>
      ["faiss_files", "faiss_index", "vector_metadata_count"].includes(check.name) &&
      (check.status === "error" || check.status === "warning")
  );

  const rebuildHtml =
    faissIssue && data.can_rebuild
      ? `<button type="button" id="kbValidateRebuildBtn" class="admin-kb-confirm-btn">
           <i class="bi bi-arrow-repeat"></i> Rebuild Index Now
         </button>`
      : "";

  kbValidateResult.innerHTML = `
    <div class="admin-integrity-summary">
      Status: <span class="${integrityOverallClass(data.status)}">${overallLabel}</span>
    </div>
    ${stats}
    <div class="admin-integrity-checks">${checksHtml}</div>
    ${failedHtml}
    ${rebuildHtml}
  `;
  kbValidateResult.hidden = false;

  const rebuildNowBtn = document.getElementById("kbValidateRebuildBtn");
  if (rebuildNowBtn) {
    rebuildNowBtn.addEventListener("click", () => runRebuild(rebuildNowBtn, null));
  }
}

if (kbValidateBtn) {
  kbValidateBtn.addEventListener("click", async () => {
    const originalHTML = kbValidateBtn.innerHTML;
    kbValidateBtn.disabled = true;
    kbValidateBtn.innerHTML = '<i class="bi bi-arrow-repeat spinning"></i> Checking...';
    kbValidateResult.hidden = true;

    try {
      const response = await fetch("/admin/knowledge/validate", { method: "POST" });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Validation failed.");
      }
      renderValidation(data);
    } catch (error) {
      kbValidateResult.innerHTML = `<div class="admin-upload-status error">${escapeHtml(error.message)}</div>`;
      kbValidateResult.hidden = false;
    } finally {
      kbValidateBtn.disabled = false;
      kbValidateBtn.innerHTML = originalHTML;
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