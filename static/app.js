/**
 * MemoryAgent Chat UI — app.js
 * Vanilla JS, no frameworks, no build step.
 */

// ── State ──────────────────────────────────────────────────────────────────

const STORAGE_KEY = 'memoryagent_user_id';

let userId = null;
let isSending = false;

// ── DOM refs (resolved after DOMContentLoaded) ─────────────────────────────

let loginScreen, chatScreen;
let nameInput, loginForm, loginBtn;
let messagesInner, chatBody, chatInput, sendBtn;
let headerUsername, userAvatar, switchUserBtn;
let toastContainer;

// ── Bootstrap ──────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loginScreen    = document.getElementById('login-screen');
  chatScreen     = document.getElementById('chat-screen');

  nameInput      = document.getElementById('name-input');
  loginForm      = document.getElementById('login-form');
  loginBtn       = document.getElementById('login-btn');

  messagesInner  = document.getElementById('messages-inner');
  chatBody       = document.getElementById('chat-body');
  chatInput      = document.getElementById('chat-input');
  sendBtn        = document.getElementById('send-btn');
  headerUsername = document.getElementById('header-username');
  userAvatar     = document.getElementById('user-avatar');
  switchUserBtn  = document.getElementById('switch-user-btn');
  toastContainer = document.getElementById('toast-container');

  // Check if already logged in
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored && stored.trim()) {
    enterChat(stored.trim());
  } else {
    showScreen('login');
    nameInput.focus();
  }

  // Login form submit
  loginForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const name = nameInput.value.trim();
    if (!name) return;
    localStorage.setItem(STORAGE_KEY, name);
    enterChat(name);
  });

  // Switch user
  switchUserBtn.addEventListener('click', () => {
    localStorage.removeItem(STORAGE_KEY);
    userId = null;
    messagesInner.innerHTML = '';
    nameInput.value = '';
    showScreen('login');
    nameInput.focus();
  });

  // Send message
  sendBtn.addEventListener('click', sendMessage);

  chatInput.addEventListener('keydown', (e) => {
    // Send on Enter (not Shift+Enter)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Auto-resize textarea
  chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + 'px';
  });
});

// ── Screens ────────────────────────────────────────────────────────────────

function showScreen(name) {
  loginScreen.classList.toggle('active', name === 'login');
  chatScreen.classList.toggle('active', name === 'chat');
}

function enterChat(name) {
  userId = name;

  // Header
  headerUsername.textContent = name;
  userAvatar.textContent = nameInitials(name);

  showScreen('chat');

  // Show empty state if no messages yet
  renderEmptyStateIfNeeded();

  // Focus input
  setTimeout(() => chatInput.focus(), 80);
}

// ── Helpers ────────────────────────────────────────────────────────────────

function nameInitials(name) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map(w => w[0].toUpperCase())
    .join('');
}

function scrollToBottom() {
  chatBody.scrollTop = chatBody.scrollHeight;
}

function renderEmptyStateIfNeeded() {
  if (!messagesInner.querySelector('.message-row, .typing-row')) {
    const el = document.createElement('div');
    el.className = 'empty-state';
    el.id = 'empty-state';
    el.innerHTML = `
      <div class="empty-icon">🧠</div>
      <p>Say hello! I remember things you tell me across conversations.</p>
    `;
    messagesInner.appendChild(el);
  }
}

function removeEmptyState() {
  const el = document.getElementById('empty-state');
  if (el) el.remove();
}

// ── Send message ───────────────────────────────────────────────────────────

async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text || isSending) return;

  isSending = true;
  setInputDisabled(true);

  removeEmptyState();

  // Add user bubble
  appendUserBubble(text);
  chatInput.value = '';
  chatInput.style.height = 'auto';
  scrollToBottom();

  // Show typing indicator
  const typingEl = appendTypingIndicator();
  scrollToBottom();

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, message: text }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();

    typingEl.remove();
    appendAgentBubble(data.reply, data.recalled_memories || []);
    scrollToBottom();

    // Toast for new memory
    if (data.new_memory_stored) {
      showToast(`🧠 Remembered: ${data.new_memory_stored}`);
    }

  } catch (err) {
    typingEl.remove();
    appendErrorBubble(err.message || 'Something went wrong. Try again.');
    scrollToBottom();
  } finally {
    isSending = false;
    setInputDisabled(false);
    chatInput.focus();
  }
}

function setInputDisabled(disabled) {
  chatInput.disabled = disabled;
  sendBtn.disabled = disabled;
}

// ── Bubble renderers ───────────────────────────────────────────────────────

function appendUserBubble(text) {
  const row = document.createElement('div');
  row.className = 'message-row user-row';
  row.innerHTML = `
    <div class="bubble-wrap">
      <div class="bubble user-bubble">${escapeHtml(text)}</div>
    </div>
  `;
  messagesInner.appendChild(row);
  return row;
}

function appendAgentBubble(text, memories) {
  const row = document.createElement('div');
  row.className = 'message-row agent-row';

  const badgeId = `mem-${Date.now()}`;
  const detailId = `mem-detail-${Date.now()}`;

  const memoryHtml = memories.length > 0 ? `
    <div class="memory-badge" role="button" tabindex="0"
         aria-expanded="false" aria-controls="${detailId}"
         onclick="toggleMemoryDetail('${badgeId}', '${detailId}')"
         onkeydown="if(event.key==='Enter'||event.key===' ') toggleMemoryDetail('${badgeId}','${detailId}')"
         id="${badgeId}">
      <span class="memory-badge-icon">🧠</span>
      <span>${memories.length} memor${memories.length === 1 ? 'y' : 'ies'} recalled</span>
    </div>
    <div class="memory-detail" id="${detailId}" role="region" aria-label="Recalled memories">
      ${memories.map(m => `<div class="memory-detail-item">${escapeHtml(m)}</div>`).join('')}
    </div>
  ` : '';

  row.innerHTML = `
    <div class="agent-avatar-sm" aria-hidden="true">🤖</div>
    <div class="bubble-wrap">
      <div class="bubble agent-bubble">${escapeHtml(text)}</div>
      ${memoryHtml}
    </div>
  `;

  messagesInner.appendChild(row);
  return row;
}

function appendErrorBubble(msg) {
  const row = document.createElement('div');
  row.className = 'message-row agent-row';
  row.innerHTML = `
    <div class="agent-avatar-sm" aria-hidden="true">⚠️</div>
    <div class="bubble-wrap">
      <div class="bubble agent-bubble" style="color:#ff7070;border-color:rgba(255,80,80,0.25);">
        Error: ${escapeHtml(msg)}
      </div>
    </div>
  `;
  messagesInner.appendChild(row);
  return row;
}

function appendTypingIndicator() {
  const row = document.createElement('div');
  row.className = 'typing-row message-row';
  row.innerHTML = `
    <div class="agent-avatar-sm" aria-hidden="true">🤖</div>
    <div class="typing-bubble" aria-label="Agent is typing">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
    </div>
  `;
  messagesInner.appendChild(row);
  return row;
}

// ── Memory detail toggle ───────────────────────────────────────────────────

function toggleMemoryDetail(badgeId, detailId) {
  const badge  = document.getElementById(badgeId);
  const detail = document.getElementById(detailId);
  if (!badge || !detail) return;
  const isOpen = detail.classList.toggle('open');
  badge.setAttribute('aria-expanded', String(isOpen));
}

// ── Toast ──────────────────────────────────────────────────────────────────

function showToast(message) {
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `<span class="toast-icon">💡</span><span>${escapeHtml(message)}</span>`;
  toastContainer.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('fade-out');
    toast.addEventListener('animationend', () => toast.remove(), { once: true });
  }, 2500);
}

// ── Utilities ──────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
