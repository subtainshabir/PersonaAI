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
