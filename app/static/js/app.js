// ---------- ELEMENT REFERENCES ----------
const welcomeScreen = document.getElementById("welcomeScreen");
const messagesContainer = document.getElementById("messagesContainer");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const newChatBtn = document.getElementById("newChatBtn");
const themeToggle = document.getElementById("themeToggle");
const sidebarToggle = document.getElementById("sidebarToggle");
const sidebar = document.getElementById("sidebar");
const sidebarOverlay = document.getElementById("sidebarOverlay");
const suggestionCards = document.querySelectorAll(".suggestion-card");

// ---------- SENDING A MESSAGE ----------
async function sendMessage(text) {
  const message = text.trim();
  if (!message) return;

  // First real message hides the welcome screen
  welcomeScreen.style.display = "none";

  addMessage("user", message);
  messageInput.value = "";
  resizeInput();

  // Loading state: a placeholder bubble shown until the real answer (or an
  // error) comes back and replaces its text.
  const typingBubble = addMessage("assistant", "Thinking...");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: message })
    });

    const data = await response.json();

    if (!response.ok) {
      // Error state: backend returned a real error (e.g. missing Groq key,
      // bad request) — show its detail rather than a raw stack trace.
      typingBubble.textContent = data.detail || "Something went wrong. Please try again.";
      typingBubble.classList.add("message-error");
    } else {
      typingBubble.textContent = data.answer;
    }
  } catch (error) {
    // Error state: network failure, server unreachable, etc.
    typingBubble.textContent = "Something went wrong reaching PersonaAI. Please try again.";
    typingBubble.classList.add("message-error");
  }

  messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// Adds a message bubble to the chat and returns the bubble element
// (so we can update it later, e.g. to show the real reply after "Thinking...")
function addMessage(role, text) {
  const row = document.createElement("div");
  row.className = `message-row ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.innerHTML = role === "user"
    ? '<i class="bi bi-person-fill"></i>'
    : '<i class="bi bi-person-badge"></i>';

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.textContent = text;

  row.appendChild(avatar);
  row.appendChild(bubble);
  messagesContainer.appendChild(row);

  messagesContainer.scrollTop = messagesContainer.scrollHeight;
  return bubble;
}

// ---------- INPUT BEHAVIOR ----------
sendBtn.addEventListener("click", () => sendMessage(messageInput.value));

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage(messageInput.value);
  }
});

messageInput.addEventListener("input", resizeInput);

function resizeInput() {
  messageInput.style.height = "auto";
  messageInput.style.height = messageInput.scrollHeight + "px";
}

// ---------- SUGGESTION CARDS ----------
suggestionCards.forEach((card) => {
  card.addEventListener("click", () => {
    const question = card.getAttribute("data-question");
    messageInput.value = question;
    messageInput.focus();
  });
});

// ---------- NEW CHAT ----------
newChatBtn.addEventListener("click", () => {
  messagesContainer.innerHTML = "";
  welcomeScreen.style.display = "block";
  messageInput.value = "";
  resizeInput();
  messageInput.focus();
});

// ---------- DARK / LIGHT MODE ----------
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const icon = themeToggle.querySelector("i");
  icon.className = theme === "dark" ? "bi bi-sun" : "bi bi-moon-stars";
}

const savedTheme = localStorage.getItem("personaai-theme") || "light";
applyTheme(savedTheme);

themeToggle.addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme");
  const next = current === "dark" ? "light" : "dark";
  applyTheme(next);
  localStorage.setItem("personaai-theme", next);
});

// ---------- MOBILE SIDEBAR ----------
sidebarToggle.addEventListener("click", () => {
  sidebar.classList.add("open");
  sidebarOverlay.classList.add("open");
});

sidebarOverlay.addEventListener("click", () => {
  sidebar.classList.remove("open");
  sidebarOverlay.classList.remove("open");
});

// ---------- KNOWLEDGE INGESTION (Phase 2 dev/test panel) ----------
const knowledgeDevBtn = document.getElementById("knowledgeDevBtn");
const knowledgeModalOverlay = document.getElementById("knowledgeModalOverlay");
const knowledgeCloseBtn = document.getElementById("knowledgeCloseBtn");
const knowledgeFileInput = document.getElementById("knowledgeFileInput");
const knowledgeProcessBtn = document.getElementById("knowledgeProcessBtn");
const knowledgeResult = document.getElementById("knowledgeResult");

knowledgeDevBtn.addEventListener("click", () => {
  knowledgeModalOverlay.classList.add("open");
});

knowledgeCloseBtn.addEventListener("click", closeKnowledgeModal);
knowledgeModalOverlay.addEventListener("click", (event) => {
  // Only close when clicking the dark backdrop, not the modal card itself.
  if (event.target === knowledgeModalOverlay) closeKnowledgeModal();
});

function closeKnowledgeModal() {
  knowledgeModalOverlay.classList.remove("open");
}

knowledgeProcessBtn.addEventListener("click", async () => {
  const file = knowledgeFileInput.files[0];

  if (!file) {
    showKnowledgeError("Please choose a file first.");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  knowledgeProcessBtn.disabled = true;
  knowledgeProcessBtn.textContent = "Processing...";

  try {
    // Phase 4: this endpoint extracts, cleans, chunks, AND embeds the document.
    const response = await fetch("/api/documents/embed", {
      method: "POST",
      body: formData
    });

    const data = await response.json();

    if (!response.ok) {
      showKnowledgeError(data.detail || "Could not process this file.");
    } else {
      showKnowledgeSuccess(data);
    }
  } catch (error) {
    showKnowledgeError("Something went wrong while uploading the file.");
  }

  knowledgeProcessBtn.disabled = false;
  knowledgeProcessBtn.innerHTML = '<i class="bi bi-gear"></i> Process Document';
});

function showKnowledgeSuccess(data) {
  knowledgeResult.innerHTML = `
    <div class="knowledge-result-row"><strong>Document:</strong> ${escapeHtml(data.filename)}</div>
    <div class="knowledge-result-row"><strong>Chunks:</strong> ${data.total_chunks}</div>
    <div class="knowledge-result-row"><strong>Embedding Model:</strong> ${escapeHtml(data.embedding_model)}</div>
    <div class="knowledge-result-row"><strong>Vector Dimension:</strong> ${data.embedding_dimension}</div>
    <div class="chunks-heading">Chunk Details</div>
    <div id="chunkCardsContainer"></div>
  `;

  const chunkCardsContainer = knowledgeResult.querySelector("#chunkCardsContainer");
  data.chunks.forEach((chunk) => {
    const card = document.createElement("div");
    card.className = "chunk-card";

    const header = document.createElement("div");
    header.className = "chunk-card-header";
    header.innerHTML = `<span>Chunk ${chunk.chunk_id + 1}</span><span class="chunk-card-chars">${chunk.characters} characters</span>`;

    const body = document.createElement("div");
    body.className = "chunk-card-text";
    body.textContent = chunk.text;

    const vectorLabel = document.createElement("div");
    vectorLabel.className = "chunk-vector-label";
    vectorLabel.textContent = "Vector preview:";

    const vectorPreview = document.createElement("div");
    vectorPreview.className = "chunk-vector-preview";
    const previewText = "[" + chunk.embedding_preview.map((n) => n.toFixed(4)).join(", ") + ", ...]";
    vectorPreview.textContent = previewText;

    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(vectorLabel);
    card.appendChild(vectorPreview);
    chunkCardsContainer.appendChild(card);
  });

  knowledgeResult.classList.add("visible");
}

function showKnowledgeError(message) {
  knowledgeResult.innerHTML = `<div class="knowledge-error"></div>`;
  knowledgeResult.querySelector(".knowledge-error").textContent = message;
  knowledgeResult.classList.add("visible");
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}