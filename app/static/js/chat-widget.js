// Floating chat widget for the Data Hub agent.
// - Lazy-load: first toggle-click fetches the latest thread.
// - Enter to send, Shift+Enter for newline.
// - Sync POST with "thinking" indicator while waiting (LLM 5–30s).
// - Disables input during in-flight requests; re-enables on response.
//
// All state in widget element dataset; no globals leak to page.
(function() {
  'use strict';

  const widget = document.getElementById('chat-widget');
  if (!widget) return;

  const clientId = widget.dataset.clientId;
  const I18N = {
    thinking: widget.dataset.i18nThinking || 'Trợ lý đang suy nghĩ…',
    empty:    widget.dataset.i18nEmpty    || 'Bắt đầu hỏi…',
    error:    widget.dataset.i18nError    || 'Có lỗi. Thử lại nhé.',
  };

  const toggleBtn = widget.querySelector('.chat-widget-toggle');
  const panel     = widget.querySelector('.chat-widget-panel');
  const closeBtn  = widget.querySelector('.chat-widget-close');
  const newBtn    = widget.querySelector('.chat-widget-new');
  const form      = widget.querySelector('.chat-widget-form');
  const input     = widget.querySelector('.chat-widget-input');
  const sendBtn   = widget.querySelector('.chat-widget-send');
  const msgList   = widget.querySelector('.chat-widget-messages');
  const empty     = widget.querySelector('.chat-widget-empty');

  let threadId = null;
  let busy = false;
  let initialized = false;

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
    e.preventDefault();
    e.stopPropagation();
    close();
  });

  // ── Bootstrap: fetch latest thread ───────────────────────────────────
  async function bootstrap() {
    setBusy(true, 'loading');
    try {
      const res = await fetch(`/clients/${clientId}/agent/_widget`, {
        credentials: 'same-origin',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      threadId = data.thread_id;
      renderMessages(data.messages);
    } catch (e) {
      console.error('chat-widget bootstrap failed', e);
      msgList.innerHTML = `<p class="chat-widget-error">${escapeHtml(I18N.error)}</p>`;
    } finally {
      setBusy(false);
    }
  }

  // ── New thread ───────────────────────────────────────────────────────
  newBtn.addEventListener('click', async (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch(`/clients/${clientId}/agent/_widget/new`, {
        method: 'POST',
        credentials: 'same-origin',
      });
      const data = await res.json();
      threadId = data.thread_id;
      renderMessages([]);
      input.focus();
    } catch (err) {
      console.error('chat-widget new-thread failed', err);
    } finally {
      setBusy(false);
    }
  });

  // ── Send message ─────────────────────────────────────────────────────
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    sendMessage();
  });

  // Enter to send, Shift+Enter to insert newline. Don't send on
  // composition (IME — Vietnamese, Chinese, etc.).
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Auto-grow textarea up to 5 rows
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    const max = parseInt(getComputedStyle(input).lineHeight) * 5;
    input.style.height = Math.min(input.scrollHeight, max) + 'px';
  });

  async function sendMessage() {
    if (busy) return;
    const text = input.value.trim();
    if (!text) return;
    // If user typed + hit Enter before bootstrap finished, run bootstrap
    // synchronously now so we have a thread to send into.
    if (!threadId) {
      if (!initialized) {
        initialized = true;
        await bootstrap();
      }
      if (!threadId) return;  // bootstrap failed; error already shown
    }

    // Optimistic UI: append user message + thinking indicator
    appendMessage({role: 'user', content: text});
    appendThinking();
    input.value = '';
    input.style.height = 'auto';
    setBusy(true);

    try {
      const res = await fetch(`/clients/${clientId}/agent/_widget/send`, {
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
    for (const m of msgs) appendMessage(m, /* skipScroll */ true);
    scrollToBottom();
  }

  function appendMessage(m, skipScroll) {
    if (empty && empty.parentNode === msgList) msgList.removeChild(empty);

    // Skip the noise: tool-result rows (raw JSON) are useful in the
    // full thread page but cluttery in the widget. Show only:
    // - user content
    // - assistant content (final or intermediate)
    // - assistant tool_call_summary as "→ tool_a, tool_b"
    if (m.role === 'tool') return;
    if (m.role === 'system') return;
    if (m.role === 'assistant' && !m.content && !m.tool_call_summary) return;

    const div = document.createElement('div');
    div.className = 'chat-widget-msg chat-widget-msg-' + m.role;
    if (m._isError) div.classList.add('chat-widget-msg-error');

    if (m.role === 'assistant' && m.tool_call_summary && !m.content) {
      // Intermediate "I'm calling these tools" turn
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

  function scrollToBottom() {
    msgList.scrollTop = msgList.scrollHeight;
  }

  function setBusy(state) {
    busy = state;
    input.disabled = state;
    sendBtn.disabled = state;
    newBtn.disabled = state;
    widget.classList.toggle('chat-widget-busy', state);
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  // Keyboard shortcut: Ctrl+/ or Cmd+/ to toggle widget
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === '/') {
      e.preventDefault();
      if (panel.hidden) open();
      else close();
    }
  });
})();
