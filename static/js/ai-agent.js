(function () {
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function addMessage(messages, type, text, action) {
    const msg = el('div', 'gm-ai-msg gm-ai-msg-' + type, text);
    if (action) msg.appendChild(renderActionCard(action));
    messages.appendChild(msg);
    messages.scrollTop = messages.scrollHeight;
  }

  async function continueWalletFlow(action, actionId) {
    if (!action) return false;
    if (window.GoodMarketAI && typeof window.GoodMarketAI.handleConfirmedAction === 'function') {
      return window.GoodMarketAI.handleConfirmedAction(action);
    }
    if (action.action_type === 'send_gd') {
      const target = new URL('/wallet', window.location.origin);
      if (actionId) target.searchParams.set('ai_action', actionId);
      window.location.href = target.toString();
      return true;
    }
    return false;
  }

  function renderActionCard(action) {
    const card = el('div', 'gm-ai-card');
    const title = el('strong', '', 'Review before signing');
    const dl = document.createElement('dl');
    const payload = action.payload || {};
    const rows = [
      ['Action', action.action_type],
      ['Amount', payload.amount || payload.fiat_amount],
      ['Token', payload.token || payload.from_token],
      ['To', payload.recipient_username ? ('@' + payload.recipient_username + ' (' + payload.recipient + ')') : (payload.recipient || payload.to_token || payload.phone)],
      ['Status', action.status]
    ].filter(function (row) { return row[1]; });
    rows.forEach(function (row) {
      dl.appendChild(el('dt', '', row[0]));
      dl.appendChild(el('dd', '', String(row[1])));
    });
    const note = el('p', '', payload.safety_note || 'No transaction will run until you confirm and sign.');
    const button = el('button', '', 'Confirm action');
    button.type = 'button';
    button.addEventListener('click', async function () {
      button.disabled = true;
      button.textContent = 'Confirming…';
      try {
        const res = await fetch('/api/ai-agent/actions/' + encodeURIComponent(action.id) + '/confirm', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          button.textContent = 'Confirmed — opening wallet flow…';
          const handled = await continueWalletFlow(data.action || action, action.id);
          if (!handled) button.textContent = data.message || 'Confirmed — continue in wallet flow';
        } else {
          button.disabled = false;
          button.textContent = data.error || 'Confirm failed';
        }
      } catch (err) {
        button.disabled = false;
        button.textContent = 'Confirm failed';
      }
    });
    card.appendChild(title);
    card.appendChild(dl);
    card.appendChild(note);
    card.appendChild(button);
    return card;
  }

  function initAgent(root) {
    const toggle = root.querySelector('.gm-ai-toggle');
    const panel = root.querySelector('.gm-ai-panel');
    const close = root.querySelector('.gm-ai-close');
    const form = root.querySelector('.gm-ai-form');
    const input = root.querySelector('.gm-ai-input');
    const messages = root.querySelector('.gm-ai-messages');

    function setOpen(open) {
      panel.hidden = !open;
      toggle.style.display = open ? 'none' : 'flex';
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) setTimeout(function () { input.focus(); }, 0);
    }

    toggle.addEventListener('click', function () { setOpen(true); });
    close.addEventListener('click', function () { setOpen(false); });
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      addMessage(messages, 'user', text);
      addMessage(messages, 'bot', 'Thinking…');
      const pending = messages.lastElementChild;
      try {
        const res = await fetch('/api/ai-agent/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text })
        });
        const data = await res.json();
        pending.remove();
        addMessage(messages, 'bot', data.reply || 'Done.', data.action);
      } catch (err) {
        pending.textContent = 'Sorry, the AI agent is unavailable right now.';
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-ai-agent]').forEach(initAgent);
  });
})();
