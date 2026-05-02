// Floating chat widget for the Data Hub agent.
// Two views inside the panel:
// - conversation: messages + compose
// - threads: list of saved conversations with rename/delete
//
// All state lives on the widget element + closure. No globals.
(function() {
  'use strict';

  const widget = document.getElementById('chat-widget');
  if (!widget) return;

  let clientId = widget.dataset.clientId;
  const I18N = {
    thinking:        widget.dataset.i18nThinking        || 'Đang suy nghĩ',
    empty:           widget.dataset.i18nEmpty           || 'Bắt đầu hỏi…',
    error:           widget.dataset.i18nError           || 'Có lỗi.',
    untitled:        widget.dataset.i18nUntitled        || '(không tên)',
    rename:          widget.dataset.i18nRename          || 'Đổi tên',
    renamePrompt:    widget.dataset.i18nRenamePrompt    || 'Tên mới:',
    delete:          widget.dataset.i18nDelete          || 'Xoá',
    deleteConfirm:   widget.dataset.i18nDeleteConfirm   || 'Xoá cuộc trò chuyện?',
    noThreads:       widget.dataset.i18nNoThreads       || 'Chưa có cuộc trò chuyện nào.',
    msgs:            widget.dataset.i18nMsgs            || 'tin nhắn',
  };

  const $ = (sel) => widget.querySelector(sel);
  const toggleBtn  = $('.chat-widget-toggle');
  const panel      = $('.chat-widget-panel');
  const closeBtn   = $('.chat-widget-close');
  const newBtn     = $('.chat-widget-new');
  const listBtn    = $('.chat-widget-list');
  const backBtn    = $('.chat-widget-back-to-chat');
  const clientSel  = $('.chat-widget-client-select');
  const fullLink   = $('.chat-widget-open-full');
  const form       = $('.chat-widget-form');
  const input      = $('.chat-widget-input');
  const sendBtn    = $('.chat-widget-send');
  const msgList    = $('.chat-widget-messages');
  const empty      = $('.chat-widget-empty');
  const titleEl    = $('.chat-widget-current-title');
  const viewConv   = $('.chat-widget-view-conversation');
  const viewThreads= $('.chat-widget-view-threads');
  const threadsList= $('.chat-widget-threads-list');

  let threadId = null;
  let busy = false;
  let initialized = false;

  function basePath() {
    return `/clients/${encodeURIComponent(clientId)}/agent`;
  }
  function refreshClientLinks() {
    if (fullLink) fullLink.href = `${basePath()}`;
  }
  refreshClientLinks();

  // ── Open / close ─────────────────────────────────────────────────────
  function isOpen() {
    return !panel.classList.contains('chat-widget-panel-hidden');
  }
  function open() {
    panel.classList.remove('chat-widget-panel-hidden');
    widget.classList.remove('chat-widget-collapsed');
    widget.classList.add('chat-widget-open');
    if (!initialized) {
      initialized = true;
      bootstrap();
    }
    setTimeout(() => input.focus(), 50);
  }
  function close() {
    panel.classList.add('chat-widget-panel-hidden');
    widget.classList.add('chat-widget-collapsed');
    widget.classList.remove('chat-widget-open');
  }

  toggleBtn.addEventListener('click', () => {
    if (isOpen()) close();
    else open();
  });
  closeBtn.addEventListener('click', (e) => {
    e.preventDefault(); e.stopPropagation(); close();
  });
  if (clientSel) {
    clientSel.addEventListener('change', () => {
      clientId = clientSel.value;
      widget.dataset.clientId = clientId;
      threadId = null;
      initialized = false;
      refreshClientLinks();
      updateTitle('');
      renderMessages([]);
      showView('conversation');
      if (isOpen()) {
        initialized = true;
        bootstrap();
      }
    });
  }

  // ── View switching ───────────────────────────────────────────────────
  function showView(name) {
    if (name === 'threads') {
      viewConv.classList.add('chat-widget-view-hidden');
      viewThreads.classList.remove('chat-widget-view-hidden');
    } else {
      viewConv.classList.remove('chat-widget-view-hidden');
      viewThreads.classList.add('chat-widget-view-hidden');
    }
  }
  listBtn.addEventListener('click', async (e) => {
    e.preventDefault(); e.stopPropagation();
    showView('threads');
    await loadThreadsList();
  });
  backBtn.addEventListener('click', (e) => {
    e.preventDefault(); e.stopPropagation();
    showView('conversation');
    setTimeout(() => input.focus(), 50);
  });

  // ── Bootstrap: fetch latest thread ───────────────────────────────────
  async function bootstrap() {
    setBusy(true);
    try {
      const res = await fetch(`${basePath()}/_widget`, {
        credentials: 'same-origin',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      threadId = data.thread_id;
      renderMessages(data.messages);
      updateTitle(data.title || '');
    } catch (e) {
      console.error('chat-widget bootstrap failed', e);
      msgList.innerHTML = `<p class="chat-widget-error">${escapeHtml(I18N.error)}</p>`;
    } finally {
      setBusy(false);
    }
  }

  // ── Threads CRUD ─────────────────────────────────────────────────────
  async function loadThreadsList() {
    threadsList.innerHTML = '<li class="meta chat-widget-threads-loading">…</li>';
    try {
      const res = await fetch(
        `${basePath()}/_widget/threads`,
        {credentials: 'same-origin'},
      );
      const data = await res.json();
      renderThreads(data.threads || []);
    } catch (e) {
      threadsList.innerHTML = `<li class="chat-widget-error">${escapeHtml(I18N.error)}</li>`;
    }
  }

  function renderThreads(threads) {
    threadsList.innerHTML = '';
    if (!threads.length) {
      threadsList.innerHTML = `<li class="meta chat-widget-empty">${escapeHtml(I18N.noThreads)}</li>`;
      return;
    }
    for (const t of threads) {
      const li = document.createElement('li');
      li.className = 'chat-widget-thread-item';
      if (t.thread_id === threadId) li.classList.add('chat-widget-thread-active');

      const main = document.createElement('button');
      main.type = 'button';
      main.className = 'chat-widget-thread-main';
      const title = document.createElement('strong');
      title.textContent = t.title || I18N.untitled;
      const meta = document.createElement('span');
      meta.className = 'meta';
      meta.textContent = `${t.message_count} ${I18N.msgs} · ${formatDate(t.updated_at)}`;
      main.appendChild(title);
      main.appendChild(meta);
      main.addEventListener('click', () => selectThread(t.thread_id));
      li.appendChild(main);

      const actions = document.createElement('div');
      actions.className = 'chat-widget-thread-actions';

      const renameBtn = document.createElement('button');
      renameBtn.type = 'button';
      renameBtn.className = 'btn-link';
      renameBtn.title = I18N.rename;
      renameBtn.textContent = '✎';
      renameBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        beginInlineRename(li, t);
      });
      actions.appendChild(renameBtn);

      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'btn-link chat-widget-thread-delete';
      delBtn.title = I18N.delete;
      delBtn.textContent = '🗑';
      delBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteThread(t);
      });
      actions.appendChild(delBtn);

      li.appendChild(actions);
      threadsList.appendChild(li);
    }
  }

  async function selectThread(tid) {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch(
        `${basePath()}/_widget/threads/${encodeURIComponent(tid)}`,
        {credentials: 'same-origin'},
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      threadId = data.thread_id;
      renderMessages(data.messages);
      updateTitle(data.title || '');
      showView('conversation');
      setTimeout(() => input.focus(), 50);
    } catch (e) {
      console.error('select thread failed', e);
    } finally {
      setBusy(false);
    }
  }

  function beginInlineRename(li, thread) {
    if (busy) return;
    const main = li.querySelector('.chat-widget-thread-main');
    if (!main) return;
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'chat-widget-thread-rename-input';
    input.value = thread.title || '';
    input.maxLength = 120;
    main.replaceChildren(input);
    input.focus();
    input.select();

    let finished = false;
    const cancel = () => {
      if (finished) return;
      finished = true;
      loadThreadsList();
    };
    const save = async () => {
      if (finished) return;
      finished = true;
      await renameThread(thread, input.value.trim());
    };
    input.addEventListener('click', (e) => e.stopPropagation());
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        save();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        cancel();
      }
    });
    input.addEventListener('blur', save);
  }

  async function renameThread(thread, title) {
    setBusy(true);
    try {
      const res = await fetch(
        `${basePath()}/_widget/threads/${encodeURIComponent(thread.thread_id)}/rename`,
        {
          method: 'POST',
          credentials: 'same-origin',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify({title}),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // Reflect locally
      thread.title = title;
      if (thread.thread_id === threadId) updateTitle(title);
      await loadThreadsList();
    } catch (e) {
      console.error('rename failed', e);
      alert(I18N.error);
    } finally {
      setBusy(false);
    }
  }

  async function deleteThread(thread) {
    if (!confirm(I18N.deleteConfirm)) return;
    setBusy(true);
    try {
      const res = await fetch(
        `${basePath()}/_widget/threads/${encodeURIComponent(thread.thread_id)}/delete`,
        {method: 'POST', credentials: 'same-origin'},
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // If we deleted the currently-loaded thread, drop it.
      if (thread.thread_id === threadId) {
        threadId = null;
        renderMessages([]);
        updateTitle('');
      }
      await loadThreadsList();
    } catch (e) {
      console.error('delete failed', e);
      alert(I18N.error);
    } finally {
      setBusy(false);
    }
  }

  // ── New thread ───────────────────────────────────────────────────────
  newBtn.addEventListener('click', async (e) => {
    e.preventDefault(); e.stopPropagation();
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch(`${basePath()}/_widget/new`, {
        method: 'POST', credentials: 'same-origin',
      });
      const data = await res.json();
      threadId = data.thread_id;
      renderMessages([]);
      updateTitle('');
      showView('conversation');
      input.focus();
    } catch (err) {
      console.error('new-thread failed', err);
    } finally {
      setBusy(false);
    }
  });

  // ── Send message ─────────────────────────────────────────────────────
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    sendMessage();
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      sendMessage();
    }
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    const max = parseInt(getComputedStyle(input).lineHeight) * 5;
    input.style.height = Math.min(input.scrollHeight, max) + 'px';
  });

  async function sendMessage() {
    if (busy) return;
    const text = input.value.trim();
    if (!text) return;
    if (!threadId) {
      if (!initialized) { initialized = true; await bootstrap(); }
      if (!threadId) return;
    }
    appendMessage({role: 'user', content: text});
    appendThinking();
    input.value = '';
    input.style.height = 'auto';
    setBusy(true);
    try {
      const res = await fetch(`${basePath()}/_widget/send`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({thread_id: threadId, text}),
      });
      if (!res.ok) {
        const errText = await res.text().catch(() => '');
        throw new Error(`HTTP ${res.status}: ${errText.slice(0, 200)}`);
      }
      const data = await res.json();
      renderMessages(data.messages);
    } catch (err) {
      console.error('chat-widget send failed', err);
      removeThinking();
      appendMessage({
        role: 'assistant',
        content: I18N.error + ' (' + err.message + ')',
        _isError: true,
      });
    } finally {
      setBusy(false);
      input.focus();
    }
  }

  // ── Rendering ────────────────────────────────────────────────────────
  function renderMessages(msgs) {
    msgList.innerHTML = '';
    if (!msgs || msgs.length === 0) {
      msgList.innerHTML = `<p class="chat-widget-empty meta">${escapeHtml(I18N.empty)}</p>`;
      return;
    }
    for (const m of msgs) appendMessage(m, true);
    scrollToBottom();
  }

  function appendMessage(m, skipScroll) {
    const e = msgList.querySelector('.chat-widget-empty');
    if (e) e.remove();
    if (m.role === 'tool') return;
    if (m.role === 'system') return;
    if (m.role === 'assistant' && !m.content && !m.tool_call_summary) return;

    const div = document.createElement('div');
    div.className = 'chat-widget-msg chat-widget-msg-' + m.role;
    if (m._isError) div.classList.add('chat-widget-msg-error');

    if (m.role === 'assistant' && m.tool_call_summary && !m.content) {
      const summary = m.tool_call_summary.join(', ');
      div.classList.add('chat-widget-msg-tools');
      div.innerHTML = '<span class="chat-widget-msg-meta">→ ' + escapeHtml(summary) + '</span>';
    } else {
      div.textContent = m.content;
    }
    msgList.appendChild(div);
    if (!skipScroll) scrollToBottom();
  }

  function appendThinking() {
    removeThinking();
    const d = document.createElement('div');
    d.className = 'chat-widget-msg chat-widget-msg-thinking';
    d.id = 'chat-widget-thinking';
    d.innerHTML = `<span>${escapeHtml(I18N.thinking)}</span><span class="chat-widget-dots"><span></span><span></span><span></span></span>`;
    msgList.appendChild(d);
    scrollToBottom();
  }
  function removeThinking() {
    const d = document.getElementById('chat-widget-thinking');
    if (d) d.remove();
  }

  function updateTitle(t) {
    if (titleEl) titleEl.textContent = t || I18N.untitled;
  }

  function scrollToBottom() {
    msgList.scrollTop = msgList.scrollHeight;
  }
  function setBusy(state) {
    busy = state;
    input.disabled = state;
    sendBtn.disabled = state;
    newBtn.disabled = state;
    listBtn.disabled = state;
    widget.classList.toggle('chat-widget-busy', state);
  }
  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }
  function formatDate(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      const yyyy = d.getFullYear();
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      const dd = String(d.getDate()).padStart(2, '0');
      const HH = String(d.getHours()).padStart(2, '0');
      const MM = String(d.getMinutes()).padStart(2, '0');
      return `${yyyy}-${mm}-${dd} ${HH}:${MM}`;
    } catch { return iso; }
  }

  // Ctrl+/ keyboard shortcut
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === '/') {
      e.preventDefault();
      if (isOpen()) close();
      else open();
    }
  });
})();
