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
const conversationsList = document.getElementById("conversationsList");

let currentConversationId = null;

// ---------- SENDING A MESSAGE ----------
async function sendMessage(text) {
  const message = text.trim();
  if (!message) return;

  // First real message hides the welcome screen
  welcomeScreen.style.display = "none";

  if (currentConversationId === null) {
    try {
      const response = await fetch("/api/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });
      const data = await response.json();
      currentConversationId = data.id;
      loadConversations();
    } catch (error) {
      // Chat still works without persistence if this fails.
    }
  }

  addMessage("user", message);
  persistMessage("user", message);
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
      typingBubble.textContent = data.detail || "Something went wrong. Please try again.";
      typingBubble.classList.add("message-error");
    } else {
      typingBubble.textContent = data.answer;
      if (data.sources && data.sources.length > 0) {
        typingBubble.appendChild(buildSourcesElement(data.sources));
      }
      persistMessage("assistant", data.answer);
      loadConversations();
    }
  } catch (error) {
    typingBubble.textContent = "Something went wrong reaching PersonaAI. Please try again.";
    typingBubble.classList.add("message-error");
  }

  messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function persistMessage(role, content) {
  if (currentConversationId === null) return;
  fetch(`/api/conversations/${currentConversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role, content })
  }).catch(() => {});
}

function buildSourcesElement(sources) {
  const wrapper = document.createElement("div");
  wrapper.className = "message-sources";

  const label = document.createElement("div");
  label.className = "message-sources-label";
  label.textContent = "Sources:";
  wrapper.appendChild(label);

  sources.forEach((source) => {
    const item = document.createElement("div");
    item.className = "message-source-item";
    item.textContent = `📄 ${source.source} — Chunk ${source.chunk_id} — Similarity: ${source.score}`;
    wrapper.appendChild(item);
  });

  return wrapper;
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
  currentConversationId = null;
  messagesContainer.innerHTML = "";
  welcomeScreen.style.display = "block";
  messageInput.value = "";
  resizeInput();
  messageInput.focus();
  highlightActiveConversation();
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
  knowledgeProcessBtn.textContent = "Indexing...";

  try {
    // Phase 5: this endpoint extracts, cleans, chunks, embeds, AND adds
    // the vectors to FAISS — this is what makes the chat box able to
    // answer questions about the uploaded document.
    const response = await fetch("/api/documents/index", {
      method: "POST",
      body: formData
    });

    const data = await response.json();

    if (!response.ok) {
      showKnowledgeError(data.detail || "Could not index this file.");
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
    <div class="knowledge-result-row"><strong>Chunks Indexed:</strong> ${data.total_chunks}</div>
    <div class="knowledge-result-row"><strong>Vector Dimension:</strong> ${data.embedding_dimension}</div>
    <div class="knowledge-result-row"><strong>Index Type:</strong> ${escapeHtml(data.index_type)}</div>
    <div class="knowledge-result-row"><strong>Status:</strong> ${escapeHtml(data.status)}</div>
    <div class="knowledge-ready-note">You can now ask questions about this document in the chat.</div>
  `;
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

// ---------- CONVERSATION LIST (Phase 12) ----------
async function loadConversations() {
  try {
    const response = await fetch("/api/conversations");
    const conversations = await response.json();
    renderConversations(conversations);
  } catch (error) {
    // Sidebar list is a convenience — chat still works without it.
  }
}

function renderConversations(conversations) {
  if (!conversations || conversations.length === 0) {
    conversationsList.className = "conversations-empty";
    conversationsList.textContent = "Your conversations will appear here.";
    return;
  }

  conversationsList.className = "conversations-populated";
  conversationsList.innerHTML = "";

  conversations.forEach((conversation) => {
    const item = document.createElement("div");
    item.className = "conversation-item";
    item.dataset.id = conversation.id;
    if (conversation.id === currentConversationId) {
      item.classList.add("active");
    }

    const title = document.createElement("div");
    title.className = "conversation-item-title";
    title.textContent = conversation.title;

    const actions = document.createElement("div");
    actions.className = "conversation-item-actions";
    actions.innerHTML = `
      <button class="conversation-item-btn" data-action="rename" aria-label="Rename"><i class="bi bi-pencil"></i></button>
      <button class="conversation-item-btn" data-action="delete" aria-label="Delete"><i class="bi bi-trash"></i></button>
    `;

    item.appendChild(title);
    item.appendChild(actions);
    conversationsList.appendChild(item);
  });
}

function highlightActiveConversation() {
  document.querySelectorAll(".conversation-item").forEach((item) => {
    item.classList.toggle("active", Number(item.dataset.id) === currentConversationId);
  });
}

conversationsList.addEventListener("click", async (event) => {
  const actionBtn = event.target.closest(".conversation-item-btn");
  const item = event.target.closest(".conversation-item");
  if (!item) return;
  const conversationId = Number(item.dataset.id);

  if (actionBtn) {
    event.stopPropagation();
    const action = actionBtn.dataset.action;
    if (action === "rename") await renameConversationPrompt(conversationId, item);
    if (action === "delete") await deleteConversationConfirm(conversationId);
    return;
  }

  await openConversation(conversationId);
});

async function openConversation(conversationId) {
  try {
    const response = await fetch(`/api/conversations/${conversationId}/messages`);
    if (!response.ok) return;
    const messages = await response.json();

    currentConversationId = conversationId;
    messagesContainer.innerHTML = "";
    welcomeScreen.style.display = messages.length === 0 ? "block" : "none";

    messages.forEach((message) => {
      addMessage(message.role, message.content);
    });

    highlightActiveConversation();
  } catch (error) {
    // Leave current view unchanged if loading fails.
  }
}

async function renameConversationPrompt(conversationId, item) {
  const currentTitle = item.querySelector(".conversation-item-title").textContent;
  const newTitle = window.prompt("Rename conversation", currentTitle);
  if (!newTitle || !newTitle.trim() || newTitle.trim() === currentTitle) return;

  try {
    await fetch(`/api/conversations/${conversationId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: newTitle.trim() })
    });
    loadConversations();
  } catch (error) {
    // No-op — list will simply show the old title on next load.
  }
}

async function deleteConversationConfirm(conversationId) {
  if (!window.confirm("Delete this conversation? This cannot be undone.")) return;

  try {
    await fetch(`/api/conversations/${conversationId}`, { method: "DELETE" });
    if (conversationId === currentConversationId) {
      newChatBtn.click();
    }
    loadConversations();
  } catch (error) {
    // No-op — deleted item will simply remain visible until next load.
  }
}

loadConversations();