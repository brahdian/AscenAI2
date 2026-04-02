/*!
 * AscenAI Chat Widget v1.0
 * Drop-in embeddable chat widget. Configure via window.AscenAI before loading.
 *
 * window.AscenAI = {
 *   agentId:       'your-agent-uuid',   // required
 *   apiKey:        'sk_live_...',        // required
 *   apiUrl:        'https://...',        // required (your API gateway base URL)
 *   theme: {
 *     primaryColor: '#7c3aed',          // default violet
 *     position:     'right',            // 'right' | 'left'
 *   },
 *   title:         'Chat with us',      // bubble header text
 *   greeting:      'Hi! How can I help you today?',
 * };
 */
(function () {
  'use strict';

  // ──────────────────────────────────────────────────────────────────────────
  // Config
  // ──────────────────────────────────────────────────────────────────────────
  var cfg = window.AscenAI || {};
  if (!cfg.agentId || !cfg.apiKey || !cfg.apiUrl) {
    console.warn('[AscenAI] Missing required config: agentId, apiKey, apiUrl');
    return;
  }

  var API_URL        = cfg.apiUrl.replace(/\/$/, '');
  var AGENT_ID       = cfg.agentId;
  var API_KEY        = cfg.apiKey;
  var PRIMARY        = (cfg.theme && cfg.theme.primaryColor) || '#7c3aed';
  var POSITION       = (cfg.theme && cfg.theme.position) || 'right';
  var TITLE          = cfg.title || 'Chat with us';
  var GREETING       = cfg.greeting || 'Hi! How can I help you today?';
  var SESSION_KEY    = 'ascenai_session_' + AGENT_ID;

  // ──────────────────────────────────────────────────────────────────────────
  // State
  // ──────────────────────────────────────────────────────────────────────────
  var sessionId   = sessionStorage.getItem(SESSION_KEY) || null;
  var isOpen      = false;
  var isTyping    = false;
  var host        = null;  // the outer div injected into page
  var shadow      = null;  // shadow root
  var messagesEl  = null;  // messages container
  var inputEl     = null;  // textarea
  var sendBtn     = null;  // send button
  var badgeEl     = null;  // unread dot on bubble
  var feedbackModal = null; // feedback modal overlay

  // ──────────────────────────────────────────────────────────────────────────
  // CSS (injected into shadow DOM — zero page interference)
  // ──────────────────────────────────────────────────────────────────────────
  var STYLES = '\n    :host { all: initial; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }\n\n    * { box-sizing: border-box; margin: 0; padding: 0; }\n\n    /* Bubble */\n    #bubble {\n      position: fixed;\n      ' + POSITION + ': 24px;\n      bottom: 24px;\n      width: 56px;\n      height: 56px;\n      border-radius: 50%;\n      background: ' + PRIMARY + ';\n      cursor: pointer;\n      display: flex;\n      align-items: center;\n      justify-content: center;\n      box-shadow: 0 4px 16px rgba(0,0,0,0.25);\n      z-index: 2147483646;\n      border: none;\n      transition: transform 0.2s ease, box-shadow 0.2s ease;\n    }\n    #bubble:hover { transform: scale(1.08); box-shadow: 0 6px 20px rgba(0,0,0,0.3); }\n    #bubble svg { width: 26px; height: 26px; fill: #fff; transition: opacity 0.2s; }\n    #badge {\n      position: absolute;\n      top: 2px;\n      right: 2px;\n      width: 12px;\n      height: 12px;\n      background: #ef4444;\n      border-radius: 50%;\n      border: 2px solid #fff;\n      display: none;\n    }\n\n    /* Panel */\n    #panel {\n      position: fixed;\n      ' + POSITION + ': 24px;\n      bottom: 92px;\n      width: 360px;\n      max-width: calc(100vw - 32px);\n      height: 520px;\n      max-height: calc(100vh - 120px);\n      border-radius: 16px;\n      background: #fff;\n      box-shadow: 0 8px 40px rgba(0,0,0,0.18);\n      z-index: 2147483645;\n      display: flex;\n      flex-direction: column;\n      overflow: hidden;\n      transform: translateY(12px) scale(0.97);\n      opacity: 0;\n      pointer-events: none;\n      transition: transform 0.22s ease, opacity 0.22s ease;\n    }\n    #panel.open {\n      transform: translateY(0) scale(1);\n      opacity: 1;\n      pointer-events: all;\n    }\n\n    /* Header */\n    #header {\n      background: ' + PRIMARY + ';\n      color: #fff;\n      padding: 14px 16px;\n      display: flex;\n      align-items: center;\n      justify-content: space-between;\n      flex-shrink: 0;\n    }\n    #header-left { display: flex; align-items: center; gap: 10px; }\n    #avatar {\n      width: 34px; height: 34px;\n      border-radius: 50%;\n      background: rgba(255,255,255,0.25);\n      display: flex; align-items: center; justify-content: center;\n    }\n    #avatar svg { width: 18px; height: 18px; fill: #fff; }\n    #title { font-size: 15px; font-weight: 600; }\n    #status { font-size: 11px; opacity: 0.8; margin-top: 1px; }\n    #close-btn {\n      background: none; border: none; cursor: pointer;\n      color: rgba(255,255,255,0.85); padding: 4px;\n      border-radius: 6px; display: flex;\n      transition: background 0.15s;\n    }\n    #close-btn:hover { background: rgba(255,255,255,0.15); }\n    #close-btn svg { width: 18px; height: 18px; stroke: currentColor; fill: none; }\n\n    /* Messages */\n    #messages {\n      flex: 1;\n      overflow-y: auto;\n      padding: 16px;\n      display: flex;\n      flex-direction: column;\n      gap: 10px;\n      scroll-behavior: smooth;\n    }\n    #messages::-webkit-scrollbar { width: 4px; }\n    #messages::-webkit-scrollbar-thumb { background: #e5e7eb; border-radius: 4px; }\n\n    .msg {\n      max-width: 82%;\n      padding: 9px 13px;\n      border-radius: 14px;\n      font-size: 14px;\n      line-height: 1.5;\n      word-break: break-word;\n      animation: msgIn 0.18s ease;\n    }\n    @keyframes msgIn {\n      from { opacity: 0; transform: translateY(6px); }\n      to   { opacity: 1; transform: translateY(0); }\n    }\n    .msg.bot {\n      background: #f3f4f6;\n      color: #111827;\n      border-bottom-left-radius: 4px;\n      align-self: flex-start;\n    }\n    .msg.user {\n      background: ' + PRIMARY + ';\n      color: #fff;\n      border-bottom-right-radius: 4px;\n      align-self: flex-end;\n    }\n\n    /* Typing indicator */\n    .typing {\n      display: flex; gap: 4px; padding: 10px 14px;\n      background: #f3f4f6;\n      border-radius: 14px;\n      border-bottom-left-radius: 4px;\n      align-self: flex-start;\n      width: fit-content;\n    }\n    .typing span {\n      width: 7px; height: 7px;\n      background: #9ca3af;\n      border-radius: 50%;\n      animation: bounce 1.2s infinite;\n    }\n    .typing span:nth-child(2) { animation-delay: 0.2s; }\n    .typing span:nth-child(3) { animation-delay: 0.4s; }\n    @keyframes bounce {\n      0%, 80%, 100% { transform: translateY(0); }\n      40%           { transform: translateY(-6px); }\n    }\n\n    /* Input area */\n    #input-area {\n      border-top: 1px solid #e5e7eb;\n      padding: 12px 12px 12px 14px;\n      display: flex;\n      align-items: flex-end;\n      gap: 8px;\n      flex-shrink: 0;\n      background: #fff;\n    }\n    #input {\n      flex: 1;\n      border: 1px solid #e5e7eb;\n      border-radius: 20px;\n      padding: 9px 14px;\n      font-size: 14px;\n      resize: none;\n      outline: none;\n      line-height: 1.45;\n      max-height: 100px;\n      overflow-y: auto;\n      font-family: inherit;\n      color: #111827;\n      background: #fff;\n      transition: border-color 0.15s;\n    }\n    #input:focus { border-color: ' + PRIMARY + '; }\n    #input::placeholder { color: #9ca3af; }\n    #send {\n      width: 36px; height: 36px;\n      border-radius: 50%;\n      background: ' + PRIMARY + ';\n      border: none;\n      cursor: pointer;\n      display: flex; align-items: center; justify-content: center;\n      flex-shrink: 0;\n      transition: background 0.15s, transform 0.1s;\n    }\n    #send:hover { filter: brightness(1.1); transform: scale(1.05); }\n    #send:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }\n    #send svg { width: 16px; height: 16px; fill: #fff; }\n\n    /* Powered-by footer */\n    #powered {\n      text-align: center;\n      font-size: 10px;\n      color: #d1d5db;\n      padding: 4px 0 8px;\n      flex-shrink: 0;\n    }\n    #powered a { color: #d1d5db; text-decoration: none; }\n    #powered a:hover { color: #9ca3af; }\n\n    /* Feedback Modal */\n    #feedback-overlay {\n      position: absolute;\n      top: 0; left: 0; right: 0; bottom: 0;\n      background: rgba(255,255,255,0.97);\n      z-index: 10;\n      display: flex;\n      flex-direction: column;\n      align-items: center;\n      justify-content: center;\n      padding: 24px;\n      animation: fadeIn 0.2s ease;\n    }\n    @keyframes fadeIn {\n      from { opacity: 0; }\n      to { opacity: 1; }\n    }\n    #feedback-overlay h3 {\n      font-size: 16px;\n      font-weight: 600;\n      color: #1f2937;\n      margin-bottom: 16px;\n    }\n    .fb-rating {\n      display: flex;\n      gap: 16px;\n      margin-bottom: 20px;\n    }\n    .fb-confirm-text { color: #6b7280; font-size: 13px; margin-bottom: 16px; text-align: center; }
    .fb-btn {\n      width: 56px;\n      height: 56px;\n      border-radius: 50%;\n      border: 2px solid #e5e7eb;\n      background: #fff;\n      cursor: pointer;\n      display: flex;\n      align-items: center;\n      justify-content: center;\n      transition: all 0.15s ease;\n      font-size: 24px;\n    }\n    .fb-btn:hover {\n      border-color: ' + PRIMARY + ';\n      background: #f5f3ff;\n    }\n    .fb-btn.selected {\n      border-color: ' + PRIMARY + ';\n      background: ' + PRIMARY + ';\n      color: #fff;\n    }\n    .fb-textarea {\n      width: 100%;\n      min-height: 60px;\n      border: 1px solid #e5e7eb;\n      border-radius: 8px;\n      padding: 10px;\n      font-size: 13px;\n      font-family: inherit;\n      resize: vertical;\n      outline: none;\n      margin-bottom: 16px;\n      transition: border-color 0.15s;\n    }\n    .fb-textarea:focus {\n      border-color: ' + PRIMARY + ';\n    }\n    .fb-actions {\n      display: flex;\n      gap: 10px;\n      width: 100%;\n    }\n    .fb-submit {\n      flex: 1;\n      padding: 10px;\n      border: none;\n      border-radius: 8px;\n      background: ' + PRIMARY + ';\n      color: #fff;\n      font-size: 14px;\n      font-weight: 500;\n      cursor: pointer;\n      transition: opacity 0.15s;\n    }\n    .fb-submit:hover { opacity: 0.9; }\n    .fb-skip {\n      padding: 10px 16px;\n      border: 1px solid #e5e7eb;\n      border-radius: 8px;\n      background: #fff;\n      color: #6b7280;\n      font-size: 14px;\n      cursor: pointer;\n      transition: background 0.15s;\n    }\n    .fb-skip:hover { background: #f9fafb; }\n  ';

  // ──────────────────────────────────────────────────────────────────────────
  // SVG icons
  // ──────────────────────────────────────────────────────────────────────────
  var ICON_CHAT   = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M20 2H4a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2z"/></svg>';
  var ICON_CLOSE  = '<svg viewBox="0 0 24 24" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
  var ICON_BOT    = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h3a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3v-8a3 3 0 0 1 3-3h3V5.73A2 2 0 0 1 10 4a2 2 0 0 1 2-2zm-3 9a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zm6 0a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z"/></svg>';
  var ICON_SEND   = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M2 21l21-9L2 3v7l15 2-15 2z"/></svg>';

  // ──────────────────────────────────────────────────────────────────────────
  // Build DOM inside a shadow root
  // ──────────────────────────────────────────────────────────────────────────
  function buildWidget() {
    host = document.createElement('div');
    host.id = 'ascenai-widget-root';
    document.body.appendChild(host);

    shadow = host.attachShadow({ mode: 'open' });

    var style = document.createElement('style');
    style.textContent = STYLES;
    shadow.appendChild(style);

    // ── Bubble ──────────────────────────────────────────────────
    var bubble = document.createElement('button');
    bubble.id = 'bubble';
    bubble.setAttribute('aria-label', 'Open chat');
    bubble.innerHTML = ICON_CHAT;

    badgeEl = document.createElement('div');
    badgeEl.id = 'badge';
    bubble.appendChild(badgeEl);
    shadow.appendChild(bubble);

    // ── Panel ───────────────────────────────────────────────────
    var panel = document.createElement('div');
    panel.id = 'panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', TITLE);

    // Header
    var header = document.createElement('div');
    header.id = 'header';
    header.innerHTML =
      '<div id="header-left">' +
        '<div id="avatar">' + ICON_BOT + '</div>' +
        '<div><div id="title">' + esc(TITLE) + '</div><div id="status">Online</div></div>' +
      '</div>';

    var closeBtn = document.createElement('button');
    closeBtn.id = 'close-btn';
    closeBtn.setAttribute('aria-label', 'Close chat');
    closeBtn.innerHTML = ICON_CLOSE;
    header.appendChild(closeBtn);
    panel.appendChild(header);

    // Messages
    messagesEl = document.createElement('div');
    messagesEl.id = 'messages';
    messagesEl.setAttribute('aria-live', 'polite');
    panel.appendChild(messagesEl);

    // Input area
    var inputArea = document.createElement('div');
    inputArea.id = 'input-area';

    inputEl = document.createElement('textarea');
    inputEl.id = 'input';
    inputEl.rows = 1;
    inputEl.placeholder = 'Type a message…';
    inputEl.setAttribute('aria-label', 'Message');
    inputArea.appendChild(inputEl);

    sendBtn = document.createElement('button');
    sendBtn.id = 'send';
    sendBtn.setAttribute('aria-label', 'Send message');
    sendBtn.innerHTML = ICON_SEND;
    inputArea.appendChild(sendBtn);
    panel.appendChild(inputArea);

    // Powered by
    var powered = document.createElement('div');
    powered.id = 'powered';
    powered.innerHTML = 'Powered by <a href="https://ascenai.com" target="_blank" rel="noopener">AscenAI</a>';
    panel.appendChild(powered);

    shadow.appendChild(panel);

    // ── Events ──────────────────────────────────────────────────
    bubble.addEventListener('click', togglePanel);
    closeBtn.addEventListener('click', closePanel);
    sendBtn.addEventListener('click', sendMessage);
    inputEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    inputEl.addEventListener('input', autoResize);

    // Show greeting
    addBotMessage(GREETING);
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Panel open/close
  // ──────────────────────────────────────────────────────────────────────────
  function togglePanel() {
    isOpen ? closePanel() : openPanel();
  }
  function openPanel() {
    isOpen = true;
    shadow.getElementById('panel').classList.add('open');
    badgeEl.style.display = 'none';
    shadow.getElementById('bubble').innerHTML = ICON_CLOSE;
    badgeEl = shadow.getElementById('badge');
    shadow.getElementById('bubble').appendChild(badgeEl);
    setTimeout(function () { if (inputEl) inputEl.focus(); }, 220);
    scrollBottom();
  }
  function closePanel() {
    var hasMessages = messagesEl && messagesEl.querySelectorAll('.msg.user').length > 0;
    if (hasMessages && sessionId) {
      showEndChatConfirmation();
    } else {
      closePanelUI();
    }
  }

  function closePanelUI() {
    isOpen = false;
    shadow.getElementById('panel').classList.remove('open');
    shadow.getElementById('bubble').innerHTML = ICON_CHAT;
    badgeEl = shadow.getElementById('badge');
    shadow.getElementById('bubble').appendChild(badgeEl);
  }

  function showFeedbackModal() {
    if (feedbackModal) return;

    feedbackModal = document.createElement('div');
    feedbackModal.id = 'feedback-overlay';
    feedbackModal.innerHTML =
      '<h3>How was your experience?</h3>' +
      '<div class="fb-rating">' +
        '<button class="fb-btn" data-rating="up" aria-label="Thumbs up">&#128077;</button>' +
        '<button class="fb-btn" data-rating="down" aria-label="Thumbs down">&#128078;</button>' +
      '</div>' +
      '<textarea class="fb-textarea" placeholder="Any feedback? (optional)" aria-label="Feedback"></textarea>' +
      '<div class="fb-actions">' +
        '<button class="fb-submit">Submit</button>' +
        '<button class="fb-skip">Skip</button>' +
      '</div>';

    var panel = shadow.getElementById('panel');
    panel.appendChild(feedbackModal);

    var selectedRating = null;
    var ratingBtns = feedbackModal.querySelectorAll('.fb-btn');
    var textarea = feedbackModal.querySelector('.fb-textarea');
    var submitBtn = feedbackModal.querySelector('.fb-submit');
    var skipBtn = feedbackModal.querySelector('.fb-skip');

    ratingBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        ratingBtns.forEach(function (b) { b.classList.remove('selected'); });
        btn.classList.add('selected');
        selectedRating = btn.getAttribute('data-rating');
      });
    });

    submitBtn.addEventListener('click', function () {
      submitFeedback(selectedRating, textarea.value.trim());
    });

    skipBtn.addEventListener('click', function () {
      submitFeedback(null, null);
    });
  }

  function showEndChatConfirmation() {
    if (feedbackModal) return;

    feedbackModal = document.createElement('div');
    feedbackModal.id = 'feedback-overlay';
    feedbackModal.innerHTML =
      '<h3>End this chat?</h3>' +
      '<p class="fb-confirm-text">Your feedback helps us improve.</p>' +
      '<div class="fb-actions">' +
        '<button class="fb-submit">End Chat</button>' +
        '<button class="fb-skip">Continue Chat</button>' +
      '</div>';

    var panel = shadow.getElementById('panel');
    panel.appendChild(feedbackModal);

    var submitBtn = feedbackModal.querySelector('.fb-submit');
    var skipBtn = feedbackModal.querySelector('.fb-skip');

    submitBtn.addEventListener('click', function () {
      removeFeedbackModal();
      showFeedbackModal();
    });

    skipBtn.addEventListener('click', function () {
      removeFeedbackModal();
      closePanelUI();
    });
  }

  function submitFeedback(rating, comment) {
    var sid = sessionId;
    var body = {};
    if (rating) body.rating = rating === 'up' ? 'positive' : 'negative';
    if (comment) body.comment = comment;

    removeFeedbackModal();

    if (sid) {
      fetchWithRetry(API_URL + '/api/v1/proxy/sessions/' + sid + '/end', {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + API_KEY,
          'Content-Type': 'application/json',
        },
        body: Object.keys(body).length > 0 ? JSON.stringify(body) : undefined,
      }).catch(function (err) {
        console.error('[AscenAI] Failed to end session:', err);
      });
    }

    sessionId = null;
    sessionStorage.removeItem(SESSION_KEY);
    closePanelUI();
  }

  function removeFeedbackModal() {
    if (feedbackModal && feedbackModal.parentNode) {
      feedbackModal.parentNode.removeChild(feedbackModal);
      feedbackModal = null;
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Messaging
  // ──────────────────────────────────────────────────────────────────────────

  var MAX_RETRIES = 3;
  var BASE_BACKOFF_MS = 1000; // 1s, 2s, 4s

  function delay(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function fetchWithRetry(url, options, attempt) {
    attempt = attempt || 0;
    return fetch(url, options).then(function (res) {
      // Rate limited — honour Retry-After if present
      if (res.status === 429) {
        if (attempt >= MAX_RETRIES) {
          return Promise.reject(new Error('Rate limited after ' + MAX_RETRIES + ' retries'));
        }
        var retryAfterSec = parseFloat(res.headers.get('Retry-After') || '0');
        var waitMs = retryAfterSec > 0
          ? retryAfterSec * 1000
          : BASE_BACKOFF_MS * Math.pow(2, attempt);
        return delay(waitMs).then(function () {
          return fetchWithRetry(url, options, attempt + 1);
        });
      }
      // Transient server errors — retry with exponential backoff
      if ((res.status === 502 || res.status === 503 || res.status === 504) && attempt < MAX_RETRIES) {
        var backoff = BASE_BACKOFF_MS * Math.pow(2, attempt);
        return delay(backoff).then(function () {
          return fetchWithRetry(url, options, attempt + 1);
        });
      }
      return res;
    }).catch(function (err) {
      // Network-level error (offline, DNS failure, etc.)
      if (attempt < MAX_RETRIES) {
        var backoff = BASE_BACKOFF_MS * Math.pow(2, attempt);
        return delay(backoff).then(function () {
          return fetchWithRetry(url, options, attempt + 1);
        });
      }
      return Promise.reject(err);
    });
  }

  function sendMessage() {
    var text = inputEl.value.trim();
    if (!text || isTyping) return;

    addUserMessage(text);
    inputEl.value = '';
    inputEl.style.height = 'auto';
    sendBtn.disabled = true;
    isTyping = true;
    showTyping();

    var body = {
      agent_id: AGENT_ID,
      message: text,
      channel: 'web',
    };
    if (sessionId) body.session_id = sessionId;

    var botMsgDiv = null;
    var botMsgText = '';

    fetch(API_URL + '/api/v1/proxy/chat/stream', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + API_KEY,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        hideTyping();
        
        // Prepare to receive chunks
        botMsgDiv = document.createElement('div');
        botMsgDiv.className = 'msg bot';
        messagesEl.appendChild(botMsgDiv);
        scrollBottom();

        var reader = res.body.getReader();
        var decoder = new TextDecoder();

        function read() {
          return reader.read().then(function (result) {
            if (result.done) return;

            var chunk = decoder.decode(result.value, { stream: true });
            var lines = chunk.split('\n');

            lines.forEach(function (line) {
              if (line.startsWith('data: ')) {
                try {
                  var data = JSON.parse(line.substring(6));
                  if (data.type === 'text' && data.data) {
                    botMsgText += data.data;
                    botMsgDiv.textContent = botMsgText;
                    scrollBottom();
                  } else if (data.type === 'session' || data.session_id) {
                    sessionId = data.session_id || data.data;
                    sessionStorage.setItem(SESSION_KEY, sessionId);
                  }
                } catch (e) {
                  // Partial JSON or unexpected format, skip
                }
              }
            });

            return read();
          });
        }
        return read();
      })
      .catch(function (err) {
        hideTyping();
        addBotMessage('Sorry, something went wrong. Please try again.');
        console.error('[AscenAI]', err);
      })
      .finally(function () {
        isTyping = false;
        sendBtn.disabled = false;
        if (inputEl) inputEl.focus();
        if (!isOpen && botMsgText) {
          badgeEl.style.display = 'block';
        }
      });
  }

  function addBotMessage(text) {
    var div = document.createElement('div');
    div.className = 'msg bot';
    div.textContent = text;
    messagesEl.appendChild(div);
    // Show unread badge if panel is closed
    if (!isOpen) {
      badgeEl.style.display = 'block';
    }
    scrollBottom();
  }

  function addUserMessage(text) {
    var div = document.createElement('div');
    div.className = 'msg user';
    div.textContent = text;
    messagesEl.appendChild(div);
    scrollBottom();
  }

  var typingEl = null;
  function showTyping() {
    typingEl = document.createElement('div');
    typingEl.className = 'typing';
    typingEl.innerHTML = '<span></span><span></span><span></span>';
    messagesEl.appendChild(typingEl);
    scrollBottom();
  }
  function hideTyping() {
    if (typingEl && typingEl.parentNode) {
      typingEl.parentNode.removeChild(typingEl);
      typingEl = null;
    }
  }

  function scrollBottom() {
    if (messagesEl) {
      requestAnimationFrame(function () {
        messagesEl.scrollTop = messagesEl.scrollHeight;
      });
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Helpers
  // ──────────────────────────────────────────────────────────────────────────
  function autoResize() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 100) + 'px';
  }

  function esc(str) {
    return (str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Init on DOM ready
  // ──────────────────────────────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildWidget);
  } else {
    buildWidget();
  }
})();
