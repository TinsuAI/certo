(function() {
  'use strict';

  const root = document.querySelector('.agent-workspace');
  if (!root) return;

  const clientId = root.dataset.clientId;
  const currentThreadId = root.dataset.currentThreadId || '';
  const i18n = {
    untitled: root.dataset.i18nUntitled || 'Thread',
    error: root.dataset.i18nError || 'Something went wrong.',
    deleteConfirm: root.dataset.i18nDeleteConfirm || 'Delete this conversation?',
  };

  function endpoint(threadId, action) {
    return `/clients/${encodeURIComponent(clientId)}/agent/_widget/threads/${encodeURIComponent(threadId)}/${action}`;
  }

  function beginRename(row) {
    const link = row.querySelector('.agent-thread-main');
    const titleEl = row.querySelector('[data-thread-title]');
    const input = row.querySelector('.agent-thread-rename-input');
    if (!link || !titleEl || !input) return;

    const original = titleEl.textContent === i18n.untitled ? '' : titleEl.textContent;
    input.value = original;
    link.hidden = true;
    input.hidden = false;
    input.focus();
    input.select();

    let done = false;
    const restore = (value) => {
      titleEl.textContent = value || i18n.untitled;
      input.hidden = true;
      link.hidden = false;
    };
    const cancel = () => {
      if (done) return;
      done = true;
      restore(original);
    };
    const save = async () => {
      if (done) return;
      done = true;
      const title = input.value.trim();
      try {
        const res = await fetch(endpoint(row.dataset.threadId, 'rename'), {
          method: 'POST',
          credentials: 'same-origin',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify({title}),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        restore(title);
        if (row.dataset.threadId === currentThreadId) {
          const current = root.querySelector('.agent-current-title');
          if (current) current.textContent = title || i18n.untitled;
        }
      } catch (err) {
        restore(original);
        window.alert(i18n.error);
      }
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

  async function deleteThread(row) {
    if (!window.confirm(i18n.deleteConfirm)) return;
    try {
      const res = await fetch(endpoint(row.dataset.threadId, 'delete'), {
        method: 'POST',
        credentials: 'same-origin',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      if (row.dataset.threadId === currentThreadId) {
        window.location.href = `/clients/${encodeURIComponent(clientId)}/agent`;
      } else {
        row.remove();
      }
    } catch (err) {
      window.alert(i18n.error);
    }
  }

  root.addEventListener('click', (e) => {
    const renameBtn = e.target.closest('[data-agent-rename]');
    if (renameBtn) {
      e.preventDefault();
      beginRename(renameBtn.closest('.agent-thread-row'));
      return;
    }
    const deleteBtn = e.target.closest('[data-agent-delete]');
    if (deleteBtn) {
      e.preventDefault();
      deleteThread(deleteBtn.closest('.agent-thread-row'));
    }
  });
})();
