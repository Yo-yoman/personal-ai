/* Personal AI frontend: vanilla JS. Chats live in localStorage; answers stream over SSE. */
const $ = (s) => document.querySelector(s);
const MAX_HISTORY = 8;
const SUGGESTIONS = ['What skills are listed?', 'Which projects are described?', 'What education is listed?',
  'Which programming languages are mentioned?', 'What work experience is described?'];

const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage full */ } },
};
let chats = store.get('pai_chats', []);
let currentId = store.get('pai_current', null);
let busy = false, abortCtrl = null;

/* ---------- helpers ---------- */
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function toast(msg, type = 'ok') {
  const t = document.createElement('div');
  t.className = 'toast ' + (type === 'error' ? 'error' : '');
  t.textContent = msg;
  $('#toasts').append(t);
  setTimeout(() => t.remove(), 4500);
}
const sourceLabel = (s) => `Profile${s.page ? ' — Page ' + s.page : ''}`;

function displayProfilePhoto(photo) {
  const image = $('#profilePhoto');
  const fallback = $('#profilePhotoFallback');
  image.hidden = !photo;
  fallback.hidden = !!photo;
  if (photo) image.src = photo;
  else image.removeAttribute('src');
}

async function saveProfilePhoto(file) {
  if (!file) return;
  if (!file.type.startsWith('image/')) {
    toast('Choose an image file for your profile photo.', 'error');
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    toast('Choose an image smaller than 10 MB.', 'error');
    return;
  }

  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
    const scale = Math.min(1, 320 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Image processing is unavailable in this browser.');
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const photo = canvas.toDataURL('image/webp', 0.82);
    localStorage.setItem('pai_profile_photo', photo);
    displayProfilePhoto(photo);
    toast('Profile photo updated.');
  } catch (error) {
    toast(`Could not save profile photo: ${error.message}`, 'error');
  } finally {
    bitmap?.close();
  }
}

/* ---------- tiny markdown renderer (escape first, then format) ---------- */
function inline(s) {
  return s.replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function md(src) {
  const blocks = [];
  const stash = (lang, code) => {
    blocks.push(`<div class="code"><div class="code-head"><span>${lang || 'code'}</span><button class="copy-code">Copy</button></div><pre><code>${code}</code></pre></div>`);
    return `\x00${blocks.length - 1}\x00`;
  };
  let s = esc(src);
  s = s.replace(/```(\w*)\n([\s\S]*?)```/g, (_, l, c) => stash(l, c));
  s = s.replace(/```(\w*)\n([\s\S]*)$/, (_, l, c) => stash(l, c)); // block still streaming
  const out = []; let para = [], list = null;
  const flushP = () => { if (para.length) { out.push('<p>' + inline(para.join('<br>')) + '</p>'); para = []; } };
  const flushL = () => { if (list) { out.push(`<${list.t}>` + list.items.map((i) => `<li>${inline(i)}</li>`).join('') + `</${list.t}>`); list = null; } };
  for (const line of s.split('\n')) {
    let m;
    if ((m = line.match(/^(#{1,4})\s+(.*)/))) { flushP(); flushL(); const n = m[1].length + 1; out.push(`<h${n}>${inline(m[2])}</h${n}>`); }
    else if ((m = line.match(/^\s*[-*•]\s+(.*)/))) { flushP(); if (!list || list.t !== 'ul') { flushL(); list = { t: 'ul', items: [] }; } list.items.push(m[1]); }
    else if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { flushP(); if (!list || list.t !== 'ol') { flushL(); list = { t: 'ol', items: [] }; } list.items.push(m[1]); }
    else if (!line.trim()) { flushP(); flushL(); }
    else if (/^\x00\d+\x00$/.test(line.trim())) { flushP(); flushL(); out.push(line.trim()); }
    else { flushL(); para.push(line); }
  }
  flushP(); flushL();
  return out.join('').replace(/\x00(\d+)\x00/g, (_, i) => blocks[i]);
}

/* ---------- chats (localStorage) ---------- */
function current() {
  let c = chats.find((x) => x.id === currentId);
  if (!c) { c = { id: Date.now().toString(36), title: 'New chat', messages: [] }; chats.unshift(c); currentId = c.id; }
  return c;
}
function save() {
  store.set('pai_chats', chats.filter((c) => c.messages.length || c.id === currentId).slice(0, 30));
  store.set('pai_current', currentId);
}
function renderChatList() {
  const ul = $('#chatList'); ul.innerHTML = '';
  const shown = chats.filter((c) => c.messages.length);
  if (!shown.length) ul.innerHTML = '<li class="empty">No conversations yet</li>';
  shown.forEach((c) => {
    const li = document.createElement('li');
    li.className = c.id === currentId ? 'active' : '';
    li.innerHTML = `<span class="name">${esc(c.title)}</span><button class="x" aria-label="Delete chat">×</button>`;
    li.onclick = () => { if (busy) return; currentId = c.id; save(); renderAll(); closeMenu(); };
    li.querySelector('.x').onclick = (e) => {
      e.stopPropagation(); if (busy) return;
      chats = chats.filter((x) => x.id !== c.id);
      if (currentId === c.id) currentId = null;
      save(); renderAll();
    };
    ul.append(li);
  });
}
function renderAll() {
  const chat = current();
  $('#chatTitle').textContent = chat.title;
  const box = $('#messages'); box.innerHTML = '';
  if (!chat.messages.length) {
    box.innerHTML = `<div class="welcome"><span class="eyebrow">YAMAN'S PERSONAL AI</span><h1>Hi, this is Yaman's Chat Assistant</h1>
      <p>Ask me about my skills, projects, education, or experience.</p>
      <div class="chips">${SUGGESTIONS.map((q) => `<button class="chip">${esc(q)}</button>`).join('')}</div></div>`;
    box.querySelectorAll('.chip').forEach((b) => (b.onclick = () => send(b.textContent)));
  } else chat.messages.forEach((m) => box.append(messageEl(m)));

  requestAnimationFrame(() => {
    box.querySelectorAll('.chip, .welcome > *').forEach((el, idx) => {
      el.style.animationDelay = `${idx * 50}ms`;
    });
  });

  renderChatList(); scrollDown(true);
}

/* ---------- message rendering ---------- */
function sourcesHTML(list) {
  if (!list?.length) return '';
  return `<div class="sources"><div class="t">Sources</div>${list.map((s) =>
    `<span class="src" title="${esc(s.preview || '')}">${esc(sourceLabel(s))}<em>${s.score.toFixed(2)}</em></span>`).join('')}</div>`;
}
function debugHTML(d) {
  const e = d.embedding;
  return `<details class="debug" open><summary>RAG debug</summary><ol class="flow">
    <li><b>User question</b><p>${esc(d.question)}</p>${d.retrieval_query !== d.question ? `<p>Searched as: ${esc(d.retrieval_query)}</p>` : ''}</li>
    <li><b>Query embedding</b><p>${esc(e.model)}, ${e.dimensions} dimensions, norm ${e.norm}</p><code>[${e.preview.join(', ')}, …]</code></li>
    <li><b>Retrieved chunks and similarity scores</b>${d.chunks.map((c) => `<div class="hit"><div class="sc"><span>#${c.rank}</span>
      <div class="meter"><i style="width:${Math.max(0, Math.min(100, c.score * 100))}%"></i></div><span>${c.score.toFixed(4)}</span></div>
      <p>${esc(sourceLabel(c))}</p><pre>${esc(c.text)}</pre></div>`).join('')}</li>
    <li><b>Context sent to the LLM</b><details><summary>Show full context</summary><pre>${esc(d.context)}</pre></details></li>
    <li><b>LLM</b><p>${esc(d.llm.model)} · ${d.llm.messages} messages · streaming</p></li></ol></details>`;
}
function messageEl(m) {
  const el = document.createElement('div'); el.className = 'msg ' + m.role;
  if (m.role === 'user') { el.innerHTML = '<div class="bubble"></div>'; el.firstChild.textContent = m.content; return el; }
  el.innerHTML = `<div class="avatar">AI</div><div class="ai-col"><div class="bubble md"></div><div class="extras"></div>
    <div class="actions"><button class="copy-msg">Copy response</button></div></div>`;
  paint(el, m);
  return el;
}
function paint(el, m, typing = false) {
  const bubble = el.querySelector('.bubble');
  bubble.innerHTML = m.content ? md(m.content) : (typing ? '<span class="typing"><i></i><i></i><i></i></span>' : '');
  const showSources = !!m.debug || $('#debugToggle').checked;
  el.querySelector('.extras').innerHTML = (showSources ? sourcesHTML(m.sources) : '') + (m.debug ? debugHTML(m.debug) : '');
  el.querySelector('.copy-msg').onclick = () => navigator.clipboard.writeText(m.content).then(() => toast('Response copied'));
}
$('#messages').addEventListener('click', (e) => {
  if (e.target.classList.contains('copy-code')) {
    navigator.clipboard.writeText(e.target.closest('.code').querySelector('code').textContent).then(() => {
      e.target.textContent = 'Copied'; setTimeout(() => (e.target.textContent = 'Copy'), 1500);
    });
  }
});
function scrollDown(force = false) {
  const b = $('#messages');
  if (force || b.scrollHeight - b.scrollTop - b.clientHeight < 140) b.scrollTop = b.scrollHeight;
}

/* ---------- chat + SSE streaming ---------- */
function setBusy(v) {
  busy = v;
  const btn = $('#sendBtn');
  btn.textContent = v ? 'Stop' : 'Send';
  btn.classList.toggle('stop', v);
}
async function send(text) {
  text = text.trim();
  if (!text || busy) return;
  const chat = current();
  const history = chat.messages.slice(-MAX_HISTORY).filter((m) => m.content).map(({ role, content }) => ({ role, content }));
  const user = { role: 'user', content: text };
  const ai = { role: 'assistant', content: '', sources: [] };
  chat.messages.push(user, ai);
  if (chat.title === 'New chat') chat.title = text.slice(0, 48);
  $('#chatTitle').textContent = chat.title;
  const box = $('#messages');
  if (box.querySelector('.welcome')) box.innerHTML = '';
  const aiEl = messageEl(ai); box.append(messageEl(user), aiEl);
  paint(aiEl, ai, true); renderChatList(); scrollDown(true);
  $('#input').value = ''; autosize(); setBusy(true);
  abortCtrl = new AbortController();

  try {
    const res = await fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: abortCtrl.signal,
      body: JSON.stringify({ message: text, history, debug: $('#debugToggle').checked }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {   // one SSE event per blank line
        const raw = buf.slice(0, i).replace(/^data: /, ''); buf = buf.slice(i + 2);
        const ev = JSON.parse(raw);
        if (ev.type === 'sources') ai.sources = ev.sources;
        else if (ev.type === 'debug') ai.debug = ev.debug;
        else if (ev.type === 'token') ai.content += ev.text;
        else if (ev.type === 'error') { toast(ev.message, 'error'); if (!ai.content) ai.content = '⚠️ ' + ev.message; }
        paint(aiEl, ai, true); scrollDown();
      }
    }
  } catch (err) {
    if (err.name !== 'AbortError') { toast(err.message, 'error'); if (!ai.content) ai.content = '⚠️ ' + err.message; }
  } finally {
    const { debug, ...persist } = ai;            // debug data stays in memory only
    chat.messages[chat.messages.length - 1] = persist;
    paint(aiEl, ai); setBusy(false); abortCtrl = null; save(); renderChatList();
  }
}

/* ---------- status, theme, layout ---------- */
async function checkHealth() {
  const pill = $('#status');
  try {
    const h = await (await fetch('/api/health')).json();
    if (!h.rag_ready) { pill.textContent = 'Preparing assistant…'; pill.className = 'pill warn'; setTimeout(checkHealth, 2000); }
    else if (!h.groq_configured) { pill.textContent = 'Add GROQ_API_KEY to .env'; pill.className = 'pill warn'; }
    else { pill.textContent = h.documents ? 'Ready' : 'Profile unavailable'; pill.className = h.documents ? 'pill ok' : 'pill warn'; }
  } catch { pill.textContent = 'Server offline'; pill.className = 'pill warn'; }
}
function setTheme(t) { document.documentElement.dataset.theme = t; store.set('pai_theme', t); }
function autosize() { const i = $('#input'); i.style.height = 'auto'; i.style.height = Math.min(i.scrollHeight, 180) + 'px'; }
const closeMenu = () => { $('#sidebar').classList.remove('open'); $('#scrim').classList.remove('open'); };

$('#sendBtn').onclick = () => (busy ? abortCtrl?.abort() : send($('#input').value));
$('#input').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send($('#input').value); } });
$('#input').addEventListener('input', autosize);
$('#newChat').onclick = () => { if (busy) return; const c = current(); if (c.messages.length) { currentId = null; } save(); renderAll(); closeMenu(); $('#input').focus(); };
$('#clearChat').onclick = () => { if (busy) return; current().messages = []; current().title = 'New chat'; save(); renderAll(); toast('Chat cleared'); };
$('#themeToggle').onclick = () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
$('#menuBtn').onclick = () => { $('#sidebar').classList.add('open'); $('#scrim').classList.add('open'); };
$('#scrim').onclick = closeMenu;
$('#debugToggle').checked = store.get('pai_debug', false);
$('#debugToggle').onchange = (e) => store.set('pai_debug', e.target.checked);
$('#profilePhotoButton').onclick = () => $('#profilePhotoInput').click();
$('#profilePhotoInput').onchange = (e) => {
  saveProfilePhoto(e.target.files[0]);
  e.target.value = '';
};

setTheme(store.get('pai_theme', matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'));
displayProfilePhoto(store.get('pai_profile_photo', null));
renderAll(); checkHealth();
