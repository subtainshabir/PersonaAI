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