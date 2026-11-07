/**
 * MemoryAgent Chat UI — app.js
 * Vanilla JS, no frameworks, no build step.
 */

// ── State ──────────────────────────────────────────────────────────────────

const TOKEN_KEY = 'memoryagent_token';
const USER_KEY  = 'memoryagent_user_id';

let authToken = localStorage.getItem(TOKEN_KEY) || null;
let userId    = localStorage.getItem(USER_KEY)  || null;
let authMode  = 'login'; // 'login' | 'signup'

let isSending = false;
let modelSelect = null;
let currentSelectedModelValue = '';
let activeConversationId = null;
let activeTab = 'chats'; // 'chats' | 'teams'
let activeTeamId = null;
let activeTeamConversationId = null;

// ── Auth-aware fetch wrapper ──────────────────────────────────────────────

async function apiFetch(url, options = {}) {
  options.headers = options.headers || {};
  if (!options.headers['Content-Type'] && options.body) {
    options.headers['Content-Type'] = 'application/json';
  }
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) options.headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(url, options);

  if ((res.status === 401 || res.status === 403) && authToken) {
    const data = await res.clone().json().catch(() => ({}));
    showToast(`⚠️ ${data.detail || 'Session expired. Please log in again.'}`);
    performLogout();
  }
  return res;
}

// ── Logout helper ─────────────────────────────────────────────────────────

async function performLogout() {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    try {
      await fetch('/auth/logout', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
    } catch (_) {}
  }
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  authToken = null;
  userId = null;
  activeConversationId = null;
  activeTeamId = null;
  activeTeamConversationId = null;
  if (messagesInner) messagesInner.innerHTML = '';
  if (nameInput) { nameInput.value = ''; nameInput.focus(); }
  if (document.getElementById('password-input')) document.getElementById('password-input').value = '';
  if (document.getElementById('auth-error-msg')) {
    document.getElementById('auth-error-msg').style.display = 'none';
    document.getElementById('auth-error-msg').textContent = '';
  }
  showScreen('login');
}

// ── DOM refs (resolved after DOMContentLoaded) ─────────────────────────────

let loginScreen, chatScreen, memoryScreen, teamsScreen;
let nameInput, loginForm, loginBtn;
let messagesInner, chatBody, chatInput, sendBtn;
let headerUsername, userAvatar, switchUserBtn;
let toastContainer;
let viewMemoriesBtn, backToChatBtn, downloadDataBtn, memoriesList;
let copyContextBtn, teachInput, teachBtn;
let newChatBtn, conversationsList;
let viewTeamsBtn, teamsBackToChatBtn, pendingInvitesContainer, teamNameInput, createTeamBtn, userTeamsList;

let tabChatsBtn, tabTeamsBtn, sidebarChatsView, sidebarTeamsView, sidebarNewTeamBtn, sidebarTeamsList;
let teamActiveBar, teamBarTitle, teamBarPendingBadge, teamBarMembers, teamInviteBtn, teamLeaveBtn;
let sharedFactsList, shareFactInput, shareFactBtn;

// ── Bootstrap ──────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loginScreen    = document.getElementById('login-screen');
  chatScreen     = document.getElementById('chat-screen');
  memoryScreen   = document.getElementById('memory-screen');
  teamsScreen    = document.getElementById('teams-screen');

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

  viewMemoriesBtn = document.getElementById('view-memories-btn');
  backToChatBtn   = document.getElementById('back-to-chat-btn');
  downloadDataBtn = document.getElementById('download-data-btn');
  memoriesList    = document.getElementById('memories-list');

  copyContextBtn  = document.getElementById('copy-context-btn');
  teachInput      = document.getElementById('teach-input');
  teachBtn        = document.getElementById('teach-btn');
  modelSelect     = document.getElementById('model-select');

  newChatBtn        = document.getElementById('new-chat-btn');
  conversationsList = document.getElementById('conversations-list');

  viewTeamsBtn            = document.getElementById('view-teams-btn');
  teamsBackToChatBtn      = document.getElementById('teams-back-to-chat-btn');
  pendingInvitesContainer = document.getElementById('pending-invites-container');
  teamNameInput           = document.getElementById('team-name-input');
  createTeamBtn           = document.getElementById('create-team-btn');
  userTeamsList           = document.getElementById('user-teams-list');

  tabChatsBtn       = document.getElementById('tab-chats-btn');
  tabTeamsBtn       = document.getElementById('tab-teams-btn');
  sidebarChatsView  = document.getElementById('sidebar-chats-view');
  sidebarTeamsView  = document.getElementById('sidebar-teams-view');
  sidebarNewTeamBtn = document.getElementById('sidebar-new-team-btn');
  sidebarTeamsList  = document.getElementById('sidebar-teams-list');

  teamActiveBar        = document.getElementById('team-active-bar');
  teamBarTitle         = document.getElementById('team-bar-title');
  teamBarPendingBadge  = document.getElementById('team-bar-pending-badge');
  teamBarMembers       = document.getElementById('team-bar-members');
  teamInviteBtn        = document.getElementById('team-invite-btn');
  teamLeaveBtn         = document.getElementById('team-leave-btn');

  sharedFactsList = document.getElementById('shared-facts-list');
  shareFactInput  = document.getElementById('share-fact-input');
  shareFactBtn    = document.getElementById('share-fact-btn');

  if (tabChatsBtn) {
    tabChatsBtn.addEventListener('click', () => switchSidebarTab('chats'));
  }
  if (tabTeamsBtn) {
    tabTeamsBtn.addEventListener('click', () => switchSidebarTab('teams'));
  }
  if (sidebarNewTeamBtn) {
    sidebarNewTeamBtn.addEventListener('click', () => {
      showScreen('teams');
      loadUserTeams();
    });
  }
  if (shareFactBtn) {
    shareFactBtn.addEventListener('click', sendShareFact);
  }

  if (viewTeamsBtn) {
    viewTeamsBtn.addEventListener('click', () => {
      showScreen('teams');
      loadUserTeams();
    });
  }

  if (teamsBackToChatBtn) {
    teamsBackToChatBtn.addEventListener('click', () => {
      showScreen('chat');
    });
  }

  if (createTeamBtn) {
    createTeamBtn.addEventListener('click', createNewTeam);
  }

  if (newChatBtn) {
    newChatBtn.addEventListener('click', startNewChat);
  }

  // Handle model selection change
  if (modelSelect) {
    modelSelect.addEventListener('change', async () => {
      const selected = modelSelect.value;
      const parts = selected.split(':');
      const provider = parts[0];
      const model = parts.slice(1).join(':');

      try {
        const res = await apiFetch('/providers/set', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider, model })
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }

        currentSelectedModelValue = selected;
        showToast(`⚡ Model switched to ${model}`);
      } catch (err) {
        showToast(`⚠️ ${err.message}`);
        if (currentSelectedModelValue) {
          modelSelect.value = currentSelectedModelValue;
        }
      }
    });
  }

  // Load provider information
  loadProviderInfo();

  // View memories button
  if (viewMemoriesBtn) {
    viewMemoriesBtn.addEventListener('click', () => {
      showScreen('memory');
      loadMemoriesList();
    });
  }

  // Back to chat button
  if (backToChatBtn) {
    backToChatBtn.addEventListener('click', () => {
      showScreen('chat');
    });
  }

  // Download data button
  if (downloadDataBtn) {
    downloadDataBtn.addEventListener('click', downloadUserData);
  }

  // Copy context button
  if (copyContextBtn) {
    copyContextBtn.addEventListener('click', copyMemoryContext);
  }

  // Teach button
  if (teachBtn) {
    teachBtn.addEventListener('click', learnFromText);
  }

  // Auth mode toggle
  const authLoginBtn  = document.getElementById('auth-mode-login-btn');
  const authSignupBtn = document.getElementById('auth-mode-signup-btn');
  const authErrorMsg  = document.getElementById('auth-error-msg');
  const passwordInput = document.getElementById('password-input');

  function setAuthMode(mode) {
    authMode = mode;
    const isLogin = (mode === 'login');
    if (authLoginBtn)  authLoginBtn.classList.toggle('active', isLogin);
    if (authSignupBtn) authSignupBtn.classList.toggle('active', !isLogin);
    const title = document.getElementById('auth-heading-title');
    const desc  = document.getElementById('auth-heading-desc');
    if (title) title.textContent = isLogin ? 'Welcome back' : 'Create an account';
    if (desc)  desc.textContent  = isLogin
      ? 'Enter your username and password to log in securely.'
      : 'Choose a username and password to create your MemoryAgent account.';
    if (loginBtn) loginBtn.textContent = isLogin ? 'Log In →' : 'Sign Up & Create Account →';
    if (passwordInput) passwordInput.setAttribute('autocomplete', isLogin ? 'current-password' : 'new-password');
    if (authErrorMsg) { authErrorMsg.style.display = 'none'; authErrorMsg.textContent = ''; }
  }

  if (authLoginBtn)  authLoginBtn.addEventListener('click',  () => setAuthMode('login'));
  if (authSignupBtn) authSignupBtn.addEventListener('click',  () => setAuthMode('signup'));
  setAuthMode('login');

  // Check if already logged in via stored token
  if (authToken && userId) {
    enterChat(userId);
  } else {
    showScreen('login');
    nameInput.focus();
  }

  // Login / Signup form submit
  loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = nameInput.value.trim();
    const password = passwordInput ? passwordInput.value : '';
    if (!username) { nameInput.focus(); return; }
    if (!password) { if (passwordInput) passwordInput.focus(); return; }

    if (authErrorMsg) { authErrorMsg.style.display = 'none'; authErrorMsg.textContent = ''; }
    loginBtn.disabled = true;
    loginBtn.textContent = authMode === 'login' ? 'Logging in…' : 'Creating account…';

    try {
      const endpoint = authMode === 'signup' ? '/auth/signup' : '/auth/login';
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: username, password })
      });
      const data = await res.json();
      if (!res.ok) {
        const msg = data.detail || (authMode === 'signup' ? 'Signup failed.' : 'Login failed.');
        if (authErrorMsg) { authErrorMsg.textContent = msg; authErrorMsg.style.display = 'block'; }
        showToast(`⚠️ ${msg}`);
        return;
      }
      // Success
      authToken = data.token;
      userId    = data.user_id;
      localStorage.setItem(TOKEN_KEY, data.token);
      localStorage.setItem(USER_KEY,  data.user_id);
      if (passwordInput) passwordInput.value = '';
      enterChat(data.user_id);
    } catch (err) {
      const msg = err.message || 'Network error. Please try again.';
      if (authErrorMsg) { authErrorMsg.textContent = msg; authErrorMsg.style.display = 'block'; }
      showToast(`⚠️ ${msg}`);
    } finally {
      loginBtn.disabled = false;
      setAuthMode(authMode);
    }
  });

  // Switch user / logout
  switchUserBtn.addEventListener('click', () => {
    performLogout();
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
  memoryScreen.classList.toggle('active', name === 'memory');
  if (teamsScreen) teamsScreen.classList.toggle('active', name === 'teams');
}

async function enterChat(name) {
  userId = name;

  // Header
  headerUsername.textContent = name;
  userAvatar.textContent = nameInitials(name);

  showScreen('chat');

  startNewChat();
  loadConversationsList();
  checkPendingInvites();
}

// ── Teams & Pending Invites ───────────────────────────────────────────────

async function checkPendingInvites() {
  if (!pendingInvitesContainer || !userId) return;
  try {
    const res = await apiFetch(`/users/${encodeURIComponent(userId)}/invites`);
    if (!res.ok) return;
    const invites = await res.json();

    pendingInvitesContainer.innerHTML = '';
    if (invites.length === 0) return;

    invites.forEach(inv => {
      const item = document.createElement('div');
      item.className = 'invite-banner-item';
      item.innerHTML = `
        <div class="invite-banner-text">
          📩 You've been invited to join <strong>${escapeHtml(inv.team_name)}</strong> by <strong>${escapeHtml(inv.invited_by)}</strong>
        </div>
        <div class="invite-banner-actions">
          <button class="btn-accept-invite" onclick="respondToTeamInvite(${inv.id}, true)">Accept</button>
          <button class="btn-decline-invite" onclick="respondToTeamInvite(${inv.id}, false)">Decline</button>
        </div>
      `;
      pendingInvitesContainer.appendChild(item);
    });
  } catch (e) {
    console.error('Failed to check pending invites:', e);
  }
}

async function respondToTeamInvite(inviteId, accept) {
  try {
    const res = await apiFetch(`/invites/${inviteId}/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ accept: accept }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    showToast(accept ? '✅ Team invite accepted!' : '❌ Team invite declined');
    checkPendingInvites();
    if (teamsScreen && teamsScreen.classList.contains('active')) {
      loadUserTeams();
    }
  } catch (err) {
    showToast(`⚠️ Failed: ${err.message}`);
  }
}

async function deleteTeam(teamId) {
  if (!confirm("Are you sure you want to delete this team? This action cannot be undone and will delete all team data.")) return;

  try {
    const res = await apiFetch(`/teams/${teamId}?caller_id=${encodeURIComponent(userId)}`, {
      method: 'DELETE',
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    showToast("🗑️ Team deleted successfully");

    if (activeTeamId === teamId) {
      activeTeamId = null;
      if (teamActiveBar) teamActiveBar.style.display = 'none';
      startNewChat();
    }

    if (typeof loadSidebarTeams === 'function') loadSidebarTeams();
    if (teamsScreen && teamsScreen.classList.contains('active')) loadUserTeams();

  } catch (err) {
    showToast(`⚠️ Failed to delete team: ${err.message}`);
  }
}

async function loadUserTeams() {
  if (!userTeamsList || !userId) return;
  userTeamsList.innerHTML = '<div style="color: var(--text-muted); padding: 12px;">Loading teams...</div>';

  try {
    const res = await apiFetch(`/users/${encodeURIComponent(userId)}/teams`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const teams = await res.json();

    userTeamsList.innerHTML = '';
    if (teams.length === 0) {
      userTeamsList.innerHTML = `
        <div class="empty-teams-card">
          🤝 You are not a member of any teams yet.<br/>
          <span style="font-size: 12px; opacity: 0.8;">Create a team above or accept an invite to collaborate!</span>
        </div>
      `;
      return;
    }

    for (const t of teams) {
      const isCreator = t.created_by === userId;
      const card = document.createElement('div');
      card.className = 'team-card';

      const membersRes = await apiFetch(`/teams/${t.id}/members`);
      const members = membersRes.ok ? await membersRes.json() : [];

      const memberPills = members.map(m => {
        const isMemCreator = m.user_id === t.created_by;
        return `
          <div class="member-pill">
            <span style="font-weight: 500;">${escapeHtml(m.display_name || m.user_id)}</span>
            ${isMemCreator ? '<span style="font-size: 10px; opacity: 0.7;">(Creator)</span>' : ''}
          </div>
        `;
      }).join('');

      card.innerHTML = `
        <div class="team-card-header">
          <span class="team-card-title">🤝 ${escapeHtml(t.name)}</span>
          <span class="team-card-creator-badge">Creator: ${escapeHtml(t.created_by)}</span>
        </div>
        <div class="team-card-body">
          <div class="team-card-members-label">Confirmed Members:</div>
          <div class="team-members-list" style="display: flex; flex-wrap: wrap; gap: 6px;">
            ${memberPills}
          </div>
        </div>

        <div class="invite-member-row" style="display: flex; gap: 8px; margin-top: 4px;">
          <input id="invite-user-input-${t.id}" class="chat-text-input" type="text" placeholder="Invite user by exact name..." style="flex: 1; border-radius: var(--radius-sm); padding: 8px 10px; font-size: 12px; height: auto;" />
          <button class="btn-primary" style="width: auto; padding: 8px 14px; font-size: 12px;" onclick="sendTeamInvite(${t.id})">+ Invite Member</button>
        </div>

        <div class="team-card-actions">
          <div class="team-actions-use">
            <button class="btn-primary" style="width: auto; padding: 8px 14px; font-size: 12px;" onclick="showScreen('chat'); openTeamNegotiatorChat(${t.id})">💬 Open Negotiator Chat</button>
          </div>
          <div class="team-actions-manage">
            ${isCreator ? `
              <button class="btn-danger" onclick="deleteTeam(${t.id})">🗑️ Delete Team</button>
            ` : `
              <button class="btn-danger" onclick="leaveOrRemoveTeamMember(${t.id}, '${escapeHtml(userId)}')">Leave Team</button>
            `}
          </div>
        </div>
      `;

      userTeamsList.appendChild(card);
    }
  } catch (err) {
    userTeamsList.innerHTML = `<div style="color: #ff7070; padding: 12px;">Failed to load teams: ${escapeHtml(err.message)}</div>`;
  }
}

async function runTeamNegotiation(teamId) {
  const goalInput = document.getElementById(`neg-goal-input-${teamId}`);
  const resultDiv = document.getElementById(`neg-result-${teamId}`);
  if (!goalInput || !resultDiv) return;

  const goal = goalInput.value.trim();
  if (!goal) {
    showToast('⚠️ Please enter a negotiation goal');
    return;
  }

  const checks = document.querySelectorAll(`.neg-member-check-${teamId}:checked`);
  const selectedUserIds = Array.from(checks).map(cb => cb.value);

  if (selectedUserIds.length === 0) {
    showToast('⚠️ Please select at least one team member');
    return;
  }

  resultDiv.style.display = 'block';
  resultDiv.innerHTML = '<div style="color: var(--text-muted); font-size: 13px; padding: 8px;">🤝 Deriving constraints and negotiating...</div>';

  try {
    const res = await apiFetch('/negotiate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        team_id: teamId,
        user_ids: selectedUserIds,
        goal: goal,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();

    let constraintsHtml = '';
    for (const [uid, constraints] of Object.entries(data.member_constraints || {})) {
      const pills = (constraints || []).map(c => `<span class="member-pill" style="font-size: 11px;">${escapeHtml(c)}</span>`).join(' ');
      constraintsHtml += `
        <div style="margin-top: 8px;">
          <strong style="font-size: 12px; color: var(--text-primary);">${escapeHtml(uid)}'s Derived Constraints:</strong>
          <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;">${pills}</div>
        </div>
      `;
    }

    resultDiv.innerHTML = `
      <div class="negotiator-recommendation-card">
        <div class="negotiator-badge">🤝 Neutral Negotiator Recommendation</div>
        <div style="font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 12px; line-height: 1.5; white-space: pre-wrap;">${escapeHtml(data.recommendation)}</div>
        <div style="border-top: 1px solid var(--border); padding-top: 10px; margin-top: 10px;">
          <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.5px;">Derived Constraints (No Raw Memory Shared):</div>
          ${constraintsHtml}
        </div>
      </div>
    `;

  } catch (err) {
    resultDiv.innerHTML = `<div style="color: #ff7070; font-size: 13px; padding: 8px;">⚠️ Negotiation failed: ${escapeHtml(err.message)}</div>`;
  }
}

async function createNewTeam() {
  const name = teamNameInput.value.trim();
  if (!name) {
    showToast('⚠️ Please enter a team name');
    return;
  }

  try {
    const res = await apiFetch('/teams', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, created_by: userId }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    teamNameInput.value = '';
    showToast('🎉 Team created!');
    loadUserTeams();
  } catch (err) {
    showToast(`⚠️ ${err.message}`);
  }
}

async function sendTeamInvite(teamId) {
  const input = document.getElementById(`invite-user-input-${teamId}`);
  if (!input) return;
  const targetUser = input.value.trim();
  if (!targetUser) {
    showToast('⚠️ Please enter an exact user name/ID');
    return;
  }

  try {
    const checkRes = await apiFetch(`/users/check/${encodeURIComponent(targetUser)}`);
    const checkData = await checkRes.json();
    if (!checkData.exists) {
      showToast(`⚠️ User '${targetUser}' does not exist.`);
      return;
    }

    const inviteRes = await apiFetch(`/teams/${teamId}/invite`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ invited_user_id: targetUser, invited_by: userId }),
    });
    if (!inviteRes.ok) {
      const err = await inviteRes.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${inviteRes.status}`);
    }
    input.value = '';
    showToast(`📩 Invite sent to ${targetUser}!`);
  } catch (err) {
    showToast(`⚠️ ${err.message}`);
  }
}

// ── Conversation threads management ───────────────────────────────────────

function startNewChat() {
  activeTeamId = null;
  activeConversationId = null;
  if (teamActiveBar) teamActiveBar.style.display = 'none';
  messagesInner.innerHTML = '';
  renderEmptyStateIfNeeded();
  highlightActiveConversation(null);
  setTimeout(() => chatInput.focus(), 80);
}

async function loadConversationsList() {
  if (!conversationsList || !userId) return;

  try {
    const res = await apiFetch(`/conversations/${encodeURIComponent(userId)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const conversations = await res.json();

    conversationsList.innerHTML = '';
    if (conversations.length === 0) {
      conversationsList.innerHTML = `
        <div style="color: var(--text-muted); font-size: 12px; text-align: center; padding: 16px 8px;">
          No past chats yet.
        </div>
      `;
      return;
    }

    conversations.forEach(c => {
      const item = document.createElement('div');
      item.className = 'conversation-item';
      if (c.id === activeConversationId) {
        item.classList.add('active');
      }
      item.id = `conv-item-${c.id}`;

      const titleText = c.title && c.title.trim() ? c.title : 'New conversation';
      const dateText = formatRelativeTime(c.updated_at || c.created_at);

      item.innerHTML = `
        <div class="conversation-info" onclick="selectConversation(${c.id})">
          <span class="conversation-title">${escapeHtml(titleText)}</span>
          <span class="conversation-date">${escapeHtml(dateText)}</span>
        </div>
        <button class="btn-delete-conversation" title="Delete conversation" onclick="event.stopPropagation(); deleteConversationThread(${c.id})">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2 2v2"></path>
          </svg>
        </button>
      `;

      conversationsList.appendChild(item);
    });
  } catch (err) {
    console.error('Failed to load conversations:', err);
  }
}

function highlightActiveConversation(convId) {
  if (!conversationsList) return;
  conversationsList.querySelectorAll('.conversation-item').forEach(el => {
    el.classList.toggle('active', el.id === `conv-item-${convId}`);
  });
}

async function selectConversation(convId) {
  activeConversationId = convId;
  highlightActiveConversation(convId);
  messagesInner.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 24px;">Loading messages...</div>';

  try {
    const res = await apiFetch(`/conversations/${convId}/messages`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const msgs = await res.json();

    messagesInner.innerHTML = '';
    if (msgs.length === 0) {
      renderEmptyStateIfNeeded();
    } else {
      msgs.forEach(m => {
        if (m.role === 'user') {
          appendUserBubble(m.content);
        } else {
          appendAgentBubble(m.content, []);
        }
      });
      scrollToBottom();
    }
  } catch (err) {
    messagesInner.innerHTML = `<div style="color: #ff7070; text-align: center; padding: 24px;">Failed to load messages: ${escapeHtml(err.message)}</div>`;
  }
}

async function deleteConversationThread(convId) {
  if (!confirm('Are you sure you want to delete this conversation?')) return;

  try {
    const res = await apiFetch(`/conversations/${convId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    if (activeConversationId === convId) {
      startNewChat();
    }
    showToast('🗑️ Conversation deleted');
    loadConversationsList();
  } catch (err) {
    showToast(`⚠️ Failed to delete: ${err.message}`);
  }
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

  if (activeTeamId) {
    await sendTeamMessage(text);
    return;
  }

  // Create conversation if starting a new thread
  if (!activeConversationId) {
    try {
      const convRes = await apiFetch('/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });
      if (convRes.ok) {
        const convData = await convRes.json();
        activeConversationId = convData.id;
        highlightActiveConversation(activeConversationId);
      }
    } catch (e) {
      console.error('Failed to create conversation thread:', e);
    }
  }

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
    const res = await apiFetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        message: text,
        conversation_id: activeConversationId
      }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();

    typingEl.remove();
    appendAgentBubble(data.reply, data.recalled_memories || []);
    scrollToBottom();

    // Refresh conversation list in sidebar to update title/date
    loadConversationsList();

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

// ── Markdown-to-HTML Renderer ──────────────────────────────────────────────

function renderMarkdownSafe(text) {
  if (!text) return '';

  // 1. Escape literal raw HTML tags to prevent XSS injection
  const escaped = String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // 2. Use marked library if available
  if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
    try {
      return marked.parse(escaped);
    } catch (e) {
      console.warn("marked.parse error, fallback to simple parser:", e);
    }
  }

  // 3. Fallback parser
  return simpleMarkdownParse(escaped);
}

function simpleMarkdownParse(escaped) {
  const paragraphs = escaped.split(/\n\n+/);
  const htmlParts = paragraphs.map(p => {
    const lines = p.split('\n');
    let inList = false;
    let listType = null;
    let out = '';

    lines.forEach(line => {
      const isBullet = /^\s*[-*•]\s+(.*)/.exec(line);
      const isNum = /^\s*(\d+)\.\s+(.*)/.exec(line);

      if (isBullet) {
        if (!inList || listType !== 'ul') {
          if (inList) out += listType === 'ul' ? '</ul>' : '</ol>';
          out += '<ul>';
          inList = true;
          listType = 'ul';
        }
        out += `<li>${inlineFormat(isBullet[1])}</li>`;
      } else if (isNum) {
        if (!inList || listType !== 'ol') {
          if (inList) out += listType === 'ul' ? '</ul>' : '</ol>';
          out += '<ol>';
          inList = true;
          listType = 'ol';
        }
        out += `<li>${inlineFormat(isNum[2])}</li>`;
      } else {
        if (inList) {
          out += listType === 'ul' ? '</ul>' : '</ol>';
          inList = false;
          listType = null;
        }
        const headerMatch = /^(#{1,4})\s+(.*)/.exec(line);
        if (headerMatch) {
          const level = headerMatch[1].length;
          out += `<h${level}>${inlineFormat(headerMatch[2])}</h${level}>`;
        } else {
          out += (out ? '<br/>' : '') + inlineFormat(line);
        }
      }
    });

    if (inList) {
      out += listType === 'ul' ? '</ul>' : '</ol>';
    }

    return `<p>${out}</p>`;
  });

  return htmlParts.join('');
}

function inlineFormat(str) {
  return str
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>');
}

// ── Bubble renderers ───────────────────────────────────────────────────────

function appendUserBubble(text) {
  const row = document.createElement('div');
  row.className = 'message-row user-row';
  row.innerHTML = `
    <div class="bubble-wrap">
      <div class="message-sender message-sender-user">👤 ${escapeHtml(userId)}</div>
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
      <div class="bubble agent-bubble">${renderMarkdownSafe(text)}</div>
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

async function loadProviderInfo() {
  try {
    const res = await apiFetch('/providers');
    if (res.ok) {
      const data = await res.json();
      const targetValue = `${data.provider}:${data.model}`;
      const select = document.getElementById('model-select');
      if (select) {
        let match = Array.from(select.options).find(opt => opt.value === targetValue);
        if (!match) {
          const newOpt = document.createElement('option');
          newOpt.value = targetValue;
          newOpt.textContent = `${data.model} (${data.provider})`;
          select.appendChild(newOpt);
        }
        select.value = targetValue;
        currentSelectedModelValue = targetValue;
      }
    }
  } catch (e) {
    console.error('Failed to load provider info:', e);
  }
}

function formatRelativeTime(timestamp) {
  if (!timestamp) return 'unknown date';
  const diffMs = Date.now() - (timestamp * 1000);
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDays = Math.floor(diffHr / 24);

  if (diffSec < 60) return 'Just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDays === 1) return 'Yesterday';
  return new Date(timestamp * 1000).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric'
  });
}

async function loadMemoriesList() {
  if (!memoriesList) return;
  memoriesList.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 24px;">Loading memories...</div>';

  try {
    const res = await apiFetch(`/memories/${encodeURIComponent(userId)}/export`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const memories = await res.json();

    if (memories.length === 0) {
      memoriesList.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 24px;">No memories saved yet. Talk to the agent to help it learn about you!</div>';
      return;
    }

    memoriesList.innerHTML = '';
    memories.forEach(m => {
      const card = document.createElement('div');
      card.className = 'memory-card';
      card.id = `memory-card-${m.id}`;
      
      const timeStr = formatRelativeTime(m.last_accessed || m.created_at);
      
      card.innerHTML = `
        <div class="memory-card-content">
          <div class="memory-text">${escapeHtml(m.content)}</div>
          <div class="memory-meta">Category: ${escapeHtml(m.category)} • Updated ${timeStr}</div>
        </div>
        <button class="btn-delete-memory" title="Delete this memory" onclick="deleteMemoryItem(${m.id})">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2 2v2"></path>
            <line x1="10" y1="11" x2="10" y2="17"></line>
            <line x1="14" y1="11" x2="14" y2="17"></line>
          </svg>
        </button>
      `;
      memoriesList.appendChild(card);
    });
  } catch (err) {
    memoriesList.innerHTML = `<div style="color: #ff7070; text-align: center; padding: 24px;">Error: ${escapeHtml(err.message)}</div>`;
  }
}

async function deleteMemoryItem(memId) {
  if (!confirm('Are you sure you want to delete this memory?')) return;
  
  try {
    const res = await apiFetch(`/memories/${memId}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    
    const card = document.getElementById(`memory-card-${memId}`);
    if (card) {
      card.style.opacity = '0';
      card.style.transform = 'scale(0.95)';
      card.style.transition = 'all 0.2s ease';
      setTimeout(() => {
        card.remove();
        if (memoriesList && !memoriesList.querySelector('.memory-card')) {
          memoriesList.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 24px;">No memories saved yet. Talk to the agent to help it learn about you!</div>';
        }
      }, 200);
    }
    showToast('🗑️ Memory deleted successfully.');
  } catch (err) {
    showToast(`⚠️ Failed to delete memory: ${err.message}`);
  }
}

async function downloadUserData() {
  try {
    const res = await apiFetch(`/memories/${encodeURIComponent(userId)}/export`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `memoryagent_memories_${userId}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('📥 Memories downloaded successfully!');
  } catch (err) {
    showToast(`⚠️ Failed to download: ${err.message}`);
  }
}

function formatMemoriesToParagraph(memories) {
  if (!memories || memories.length === 0) {
    return "No known facts about this user yet.";
  }
  
  const clauses = memories.map(m => {
    let text = m.content.trim();
    text = text.replace(/\.+$/, '');
    
    // Convert common patterns grammatically for "they [clause]" format:
    text = text.replace(/^user is /i, "are ");
    text = text.replace(/^user prefers /i, "prefer ");
    text = text.replace(/^user likes /i, "like ");
    text = text.replace(/^user has /i, "have ");
    text = text.replace(/^user /i, "");
    
    return text.charAt(0).toLowerCase() + text.slice(1);
  });

  if (clauses.length === 1) {
    return `Known facts about this user: they ${clauses[0]}.`;
  }
  if (clauses.length === 2) {
    return `Known facts about this user: they ${clauses[0]} and they ${clauses[1]}.`;
  }
  
  const lastClause = clauses.pop();
  return `Known facts about this user: they ${clauses.join(', they ')}, and they ${lastClause}.`;
}

async function copyMemoryContext() {
  try {
    const res = await apiFetch(`/memories/${encodeURIComponent(userId)}/export`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const memories = await res.json();
    
    const paragraphText = formatMemoriesToParagraph(memories);
    
    await navigator.clipboard.writeText(paragraphText);
    showToast("📋 Copied — paste this into any other AI chat");
  } catch (err) {
    console.error("Clipboard copy error:", err);
    showToast(`⚠️ Failed to copy context: ${err.message}`);
  }
}

async function learnFromText() {
  if (!teachInput || !teachBtn) return;
  const text = teachInput.value.trim();
  if (!text) {
    showToast("⚠️ Please paste a conversation first.");
    return;
  }
  
  // Set disabled state
  teachInput.disabled = true;
  teachBtn.disabled = true;
  const originalBtnText = teachBtn.textContent;
  teachBtn.textContent = "✨ Learning...";
  
  try {
    const res = await apiFetch(`/memories/${encodeURIComponent(userId)}/learn-from-text`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text })
    });
    
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${res.status}`);
    }
    
    const data = await res.json();
    const extracted = data.extracted || [];
    
    if (extracted.length > 0) {
      showToast(`🧠 Learned ${extracted.length} new fact${extracted.length === 1 ? '' : 's'}!`);
      teachInput.value = "";
      // Refresh memory list
      loadMemoriesList();
    } else {
      showToast("💡 Checked text, but found no new durable facts to remember.");
    }
  } catch (err) {
    showToast(`⚠️ Failed to learn: ${err.message}`);
  } finally {
    teachInput.disabled = false;
    teachBtn.disabled = false;
    teachBtn.textContent = originalBtnText;
  }
}

window.deleteMemoryItem = deleteMemoryItem;
window.selectConversation = selectConversation;
window.deleteConversationThread = deleteConversationThread;
window.respondToTeamInvite = respondToTeamInvite;
window.sendTeamInvite = sendTeamInvite;
window.runTeamNegotiation = runTeamNegotiation;

// ── Sidebar Tabs & Team Negotiator Chat Mode ───────────────────────────────

function switchSidebarTab(tab) {
  activeTab = tab;
  if (tabChatsBtn) tabChatsBtn.classList.toggle('active', tab === 'chats');
  if (tabTeamsBtn) tabTeamsBtn.classList.toggle('active', tab === 'teams');
  if (sidebarChatsView) sidebarChatsView.classList.toggle('active', tab === 'chats');
  if (sidebarTeamsView) sidebarTeamsView.classList.toggle('active', tab === 'teams');

  if (tab === 'teams') {
    loadSidebarTeams();
  }
}

async function loadSidebarTeams() {
  if (!sidebarTeamsList || !userId) return;
  sidebarTeamsList.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; text-align: center; padding: 16px 8px;">Loading teams...</div>';

  try {
    const res = await apiFetch(`/users/${encodeURIComponent(userId)}/teams`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const teams = await res.json();

    sidebarTeamsList.innerHTML = '';
    if (teams.length === 0) {
      sidebarTeamsList.innerHTML = `
        <div style="color: var(--text-muted); font-size: 12px; text-align: center; padding: 16px 8px;">
          No teams yet. Click "+ New team" to create one!
        </div>
      `;
      return;
    }

    teams.forEach(t => {
      const item = document.createElement('div');
      item.className = 'conversation-item';
      if (t.id === activeTeamId) {
        item.classList.add('active');
      }
      item.setAttribute('data-team-id', t.id);
      item.innerHTML = `
        <div class="conversation-info" onclick="openTeamNegotiatorChat(${t.id})">
          <span class="conversation-title">🤝 ${escapeHtml(t.name)}</span>
          <span class="conversation-date">Created by ${escapeHtml(t.created_by)}</span>
        </div>
      `;
      sidebarTeamsList.appendChild(item);
    });
  } catch (err) {
    sidebarTeamsList.innerHTML = `<div style="color: #ff7070; font-size: 12px; padding: 8px;">Error loading teams</div>`;
  }
}

async function openTeamNegotiatorChat(teamId) {
  activeTeamId = teamId;
  activeConversationId = null; // Exit 1-on-1 mode
  if (teamActiveBar) teamActiveBar.style.display = 'flex';

  // Highlight active team item in sidebar
  document.querySelectorAll('#sidebar-teams-list .conversation-item').forEach(el => {
    el.classList.toggle('active', el.getAttribute('data-team-id') == teamId);
  });
  document.querySelectorAll('#conversations-list .conversation-item').forEach(el => {
    el.classList.remove('active');
  });

  try {
    const [teamRes, membersRes, convRes, sharedRes, invitesRes] = await Promise.all([
      fetch(`/users/${encodeURIComponent(userId)}/teams`),
      fetch(`/teams/${teamId}/members`),
      fetch(`/teams/${teamId}/conversations?user_id=${encodeURIComponent(userId)}`),
      fetch(`/teams/${teamId}/shared?user_id=${encodeURIComponent(userId)}`),
      fetch(`/teams/${teamId}/invites`),
    ]);

    const userTeams = teamRes.ok ? await teamRes.json() : [];
    const teamObj = userTeams.find(t => t.id === teamId) || { id: teamId, name: `Team #${teamId}`, created_by: '' };
    const members = membersRes.ok ? await membersRes.json() : [];
    const conv = convRes.ok ? await convRes.json() : null;
    const sharedFacts = sharedRes.ok ? await sharedRes.json() : [];
    const pendingInvites = invitesRes.ok ? await invitesRes.json() : [];

    activeTeamConversationId = conv ? conv.id : null;

    if (teamBarTitle) teamBarTitle.textContent = `🤝 ${teamObj.name} Negotiator`;
    if (teamBarPendingBadge) {
      if (pendingInvites.length > 0) {
        teamBarPendingBadge.style.display = 'inline-block';
        teamBarPendingBadge.textContent = `${pendingInvites.length} pending invite(s)`;
      } else {
        teamBarPendingBadge.style.display = 'none';
      }
    }

    if (teamBarMembers) {
      teamBarMembers.innerHTML = members.map(m => {
        const isCreator = teamObj.created_by === m.user_id;
        const isMe = m.user_id === userId;
        const amCreator = teamObj.created_by === userId;

        let actionBtn = '';
        if (isMe && !amCreator) {
          actionBtn = `<button style="background:none; border:none; color:#ff7070; cursor:pointer; font-size:10px; margin-left:4px;" onclick="event.stopPropagation(); leaveOrRemoveTeamMember(${teamId}, '${escapeHtml(m.user_id)}')">Leave</button>`;
        } else if (!isMe && amCreator) {
          actionBtn = `<button style="background:none; border:none; color:#ff7070; cursor:pointer; font-size:10px; margin-left:4px;" onclick="event.stopPropagation(); leaveOrRemoveTeamMember(${teamId}, '${escapeHtml(m.user_id)}')">Remove</button>`;
        }

        return `
          <div class="member-pill">
            <span style="font-weight: 500;">${escapeHtml(m.display_name || m.user_id)}</span>
            ${isCreator ? '<span style="font-size: 10px; opacity: 0.7;">(Creator)</span>' : ''}
            ${actionBtn}
          </div>
        `;
      }).join('');
    }

    if (teamInviteBtn) {
      teamInviteBtn.onclick = () => promptInviteMember(teamId);
    }
    if (teamLeaveBtn) {
      const amCreator = teamObj.created_by === userId;
      teamLeaveBtn.textContent = amCreator ? 'Manage Team' : 'Leave Team';
      teamLeaveBtn.onclick = () => {
        if (amCreator) {
          showScreen('teams');
          loadUserTeams();
        } else {
          leaveOrRemoveTeamMember(teamId, userId);
        }
      };
    }

    renderSharedFactsList(sharedFacts);

    if (conv) {
      const msgRes = await apiFetch(`/team-conversations/${conv.id}/messages`);
      const msgs = msgRes.ok ? await msgRes.json() : [];
      renderTeamMessages(msgs);
    } else {
      messagesInner.innerHTML = '';
    }

  } catch (err) {
    showToast(`⚠️ Error loading team chat: ${err.message}`);
  }
}

function renderSharedFactsList(sharedFacts) {
  if (!sharedFactsList) return;
  sharedFactsList.innerHTML = '';
  if (!sharedFacts || sharedFacts.length === 0) {
    sharedFactsList.innerHTML = `<div style="font-size: 11px; color: var(--text-muted);">No private constraints disclosed to engine yet.</div>`;
    return;
  }
  sharedFacts.forEach(f => {
    const item = document.createElement('div');
    item.className = 'shared-fact-item';
    item.style.display = 'flex';
    item.style.justifyContent = 'space-between';
    item.style.alignItems = 'center';
    item.innerHTML = `
      <span>🔒 ${escapeHtml(f.content)}</span>
      <button style="background:none; border:none; color:#ff7070; cursor:pointer; font-size:11px; margin-left:8px;" onclick="deleteSharedFact(${f.id})">Delete</button>
    `;
    sharedFactsList.appendChild(item);
  });
}

function formatConstraintPill(c) {
  if (typeof c === 'object' && c !== null) {
    const cat = c.category ? `<small style="font-size: 9px; font-weight: 700; text-transform: uppercase; color: var(--accent); opacity: 0.85; margin-right: 3px;">[${escapeHtml(c.category)}]</small>` : '';
    const text = escapeHtml(c.constraint || '');
    return `<span class="member-pill" style="font-size: 11px;">${cat}${text}</span>`;
  } else if (typeof c === 'string') {
    return `<span class="member-pill" style="font-size: 11px;">${escapeHtml(c)}</span>`;
  }
  return '';
}

function renderTeamMessages(msgs) {
  messagesInner.innerHTML = '';
  if (!msgs || msgs.length === 0) {
    messagesInner.innerHTML = `
      <div style="text-align: center; color: var(--text-muted); font-size: 13px; margin: 30px 0;">
        🤝 Welcome to <strong>Team Negotiator Chat</strong>!<br/>
        Send a message to start negotiating choices, plans, or recommendations for your team.
      </div>
    `;
    return;
  }

  msgs.forEach(msg => {
    const isAssistant = msg.role === 'assistant' || msg.user_id === 'negotiator';
    const row = document.createElement('div');
    row.className = `message-row ${isAssistant ? 'agent-row' : 'user-row'}`;

    const label = isAssistant ? '🤝 Negotiator' : `👤 ${escapeHtml(msg.user_id)}`;
    const bodyHtml = isAssistant ? renderMarkdownSafe(msg.content) : escapeHtml(msg.content);

    let constraintsHtml = '';
    if (isAssistant && msg.derived_constraints) {
      let constraintsDetails = '';
      for (const [uid, constraints] of Object.entries(msg.derived_constraints)) {
        const pills = (constraints || []).map(c => formatConstraintPill(c)).join(' ');
        constraintsDetails += `
          <div style="margin-top: 4px;">
            <strong style="color: var(--text-primary);">${escapeHtml(uid)}:</strong>
            <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 2px;">${pills || '<span style="font-size: 11px; color: var(--text-muted);">None</span>'}</div>
          </div>
        `;
      }

      constraintsHtml = `
        <details class="debug-reason-details">
          <summary>⚠️ Reason (debug — remove before real use)</summary>
          <div style="margin-top: 6px;">
            <div style="font-size: 11px; opacity: 0.8; margin-bottom: 4px;">Derived member constraints for this turn (no raw memories passed):</div>
            ${constraintsDetails}
          </div>
        </details>
      `;
    }

    if (isAssistant) {
      row.innerHTML = `
        <div class="agent-avatar-sm" aria-hidden="true">🤝</div>
        <div class="bubble-wrap">
          <div class="message-sender">${label}</div>
          <div class="bubble agent-bubble">${bodyHtml}</div>
          ${constraintsHtml}
        </div>
      `;
    } else {
      row.innerHTML = `
        <div class="bubble-wrap">
          <div class="message-sender message-sender-user">${label}</div>
          <div class="bubble user-bubble">${bodyHtml}</div>
        </div>
      `;
    }

    messagesInner.appendChild(row);
  });

  chatBody.scrollTop = chatBody.scrollHeight;
}

async function sendTeamMessage(text) {
  if (!text || isSending || !activeTeamId) return;

  isSending = true;
  setInputDisabled(true);

  // Append user bubble immediately (plain text)
  const userRow = document.createElement('div');
  userRow.className = 'message-row user-row';
  userRow.innerHTML = `
    <div class="bubble-wrap">
      <div class="message-sender message-sender-user">👤 ${escapeHtml(userId)}</div>
      <div class="bubble user-bubble">${escapeHtml(text)}</div>
    </div>
  `;
  messagesInner.appendChild(userRow);
  chatInput.value = '';
  chatInput.style.height = 'auto';
  scrollToBottom();

  const typingEl = appendTypingIndicator();
  scrollToBottom();

  try {
    const res = await apiFetch(`/teams/${activeTeamId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        message: text,
        team_conversation_id: activeTeamConversationId,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();
    typingEl.remove();

    const assistRow = document.createElement('div');
    assistRow.className = 'message-row agent-row';

    let constraintsHtml = '';
    if (data.derived_constraints) {
      let constraintsDetails = '';
      for (const [uid, constraints] of Object.entries(data.derived_constraints)) {
        const pills = (constraints || []).map(c => formatConstraintPill(c)).join(' ');
        constraintsDetails += `
          <div style="margin-top: 4px;">
            <strong style="color: var(--text-primary);">${escapeHtml(uid)}:</strong>
            <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 2px;">${pills || '<span style="font-size: 11px; color: var(--text-muted);">None</span>'}</div>
          </div>
        `;
      }
      constraintsHtml = `
        <details class="debug-reason-details">
          <summary>⚠️ Reason (debug — remove before real use)</summary>
          <div style="margin-top: 6px;">
            <div style="font-size: 11px; opacity: 0.8; margin-bottom: 4px;">Derived member constraints for this turn (no raw memories passed):</div>
            ${constraintsDetails}
          </div>
        </details>
      `;
    }

    assistRow.innerHTML = `
      <div class="agent-avatar-sm" aria-hidden="true">🤝</div>
      <div class="bubble-wrap">
        <div class="message-sender">🤝 Negotiator</div>
        <div class="bubble agent-bubble">${renderMarkdownSafe(data.reply)}</div>
        ${constraintsHtml}
      </div>
    `;

    messagesInner.appendChild(assistRow);
    scrollToBottom();

  } catch (err) {
    typingEl.remove();
    showToast(`⚠️ ${err.message}`);
  } finally {
    isSending = false;
    setInputDisabled(false);
    chatInput.focus();
  }
}

async function sendShareFact() {
  if (!shareFactInput || !activeTeamId) return;
  const content = shareFactInput.value.trim();
  if (!content) {
    showToast('⚠️ Please enter a constraint to disclose');
    return;
  }

  try {
    const res = await apiFetch(`/teams/${activeTeamId}/share`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, content: content }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    shareFactInput.value = '';
    showToast('🔒 Constraint disclosed to engine!');
    const sharedRes = await apiFetch(`/teams/${activeTeamId}/shared?user_id=${encodeURIComponent(userId)}`);
    if (sharedRes.ok) {
      const sharedFacts = await sharedRes.json();
      renderSharedFactsList(sharedFacts);
    }
  } catch (err) {
    showToast(`⚠️ ${err.message}`);
  }
}

async function deleteSharedFact(factId) {
  if (!activeTeamId || !factId) return;
  try {
    const res = await apiFetch(`/teams/${activeTeamId}/shared/${factId}?user_id=${encodeURIComponent(userId)}`, {
      method: 'DELETE',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    showToast('🗑️ Disclosed constraint deleted');
    const sharedRes = await apiFetch(`/teams/${activeTeamId}/shared?user_id=${encodeURIComponent(userId)}`);
    if (sharedRes.ok) {
      const sharedFacts = await sharedRes.json();
      renderSharedFactsList(sharedFacts);
    }
  } catch (err) {
    showToast(`⚠️ ${err.message}`);
  }
}

async function leaveOrRemoveTeamMember(teamId, targetUserId) {
  const isSelf = targetUserId === userId;
  const actionText = isSelf ? 'leave this team' : `remove ${targetUserId} from this team`;
  if (!confirm(`Are you sure you want to ${actionText}?`)) return;

  try {
    const res = await apiFetch(`/teams/${teamId}/members/${encodeURIComponent(targetUserId)}?caller_id=${encodeURIComponent(userId)}`, {
      method: 'DELETE',
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    showToast(`✅ ${isSelf ? 'Left team' : `Removed ${targetUserId}`}`);
    if (isSelf) {
      if (teamActiveBar) teamActiveBar.style.display = 'none';
      activeTeamId = null;
      startNewChat();
      if (activeTab === 'teams') loadSidebarTeams();
    } else {
      openTeamNegotiatorChat(teamId);
    }
  } catch (err) {
    showToast(`⚠️ ${err.message}`);
  }
}

async function promptInviteMember(teamId) {
  const targetUser = prompt("Enter the exact user name to invite to this team:");
  if (!targetUser || !targetUser.trim()) return;

  try {
    const checkRes = await apiFetch(`/users/check/${encodeURIComponent(targetUser.trim())}`);
    const checkData = await checkRes.json();
    if (!checkData.exists) {
      showToast(`⚠️ User '${targetUser}' does not exist.`);
      return;
    }

    const inviteRes = await apiFetch(`/teams/${teamId}/invite`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ invited_user_id: targetUser.trim(), invited_by: userId }),
    });

    if (!inviteRes.ok) {
      const err = await inviteRes.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${inviteRes.status}`);
    }

    showToast(`📩 Invite sent to ${targetUser}!`);
    openTeamNegotiatorChat(teamId);
  } catch (err) {
    showToast(`⚠️ ${err.message}`);
  }
}

window.openTeamNegotiatorChat = openTeamNegotiatorChat;
window.leaveOrRemoveTeamMember = leaveOrRemoveTeamMember;
window.deleteSharedFact = deleteSharedFact;
window.deleteTeam = deleteTeam;
