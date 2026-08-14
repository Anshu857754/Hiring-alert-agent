const $ = (id) => document.getElementById(id);

let allJobs = [];
let sortKey = 'matchScore';
let sortDir = -1;

const COLS = [
  { key: 'matchScore', label: 'Match', num: true },
  { key: 'source', label: 'Source' },
  { key: 'title', label: 'Job Title' },
  { key: 'company', label: 'Company' },
  { key: 'location', label: 'Location' },
  { key: 'contractType', label: 'Type' },
  { key: 'experienceLevel', label: 'Level' },
  { key: 'salary', label: 'Salary' },
  { key: 'postedAt', label: 'Posted' },
];

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ---------------- JD source tabs ---------------- */

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('on', t === tab));
    document.querySelectorAll('.pane').forEach((p) => p.classList.toggle('on', p.id === `pane-${tab.dataset.pane}`));
  });
});

/* ---------------- PDF / DOCX upload ----------------
   markitdown backend par chalta hai — parsing local hoti hai, koi LLM token kharch nahi hota. */

const drop = $('drop');
const fileInput = $('file');

drop.addEventListener('click', () => fileInput.click());
drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('hot'); });
drop.addEventListener('dragleave', () => drop.classList.remove('hot'));
drop.addEventListener('drop', (e) => {
  e.preventDefault();
  drop.classList.remove('hot');
  if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) uploadFile(fileInput.files[0]);
});

function fileStatus(html, isErr) {
  $('fileRow').classList.add('on');
  $('fileRow').innerHTML = isErr ? `<div class="err">${html}</div>` : html;
}

async function uploadFile(file) {
  drop.classList.add('busy');
  fileStatus(`<span class="stat">${escapeHtml(file.name)} padh raha hoon...</span>`);
  $('preview').classList.remove('on');

  try {
    const body = new FormData();
    body.append('file', file);
    const res = await fetch('/api/extract', { method: 'POST', body });
    const data = await res.json();

    if (!res.ok) {
      fileStatus(escapeHtml(data.error || 'File parse nahi hui'), true);
      return;
    }

    // Extracted text seedha JD box me chala jaata hai — search wahi text use karti hai.
    $('jd').value = data.text;
    $('preview').textContent = data.text;
    $('preview').classList.add('on');

    fileStatus(`
      <span class="name">${escapeHtml(data.filename)}</span>
      <span class="stat">${data.chars.toLocaleString()} chars &middot; ${data.words.toLocaleString()} words</span>
      <span class="stat">&middot; markitdown se local parse &mdash; $0 LLM</span>
      <span class="spacer"></span>
      <button class="link" id="editText" type="button">Text edit karo</button>
      <button class="link" id="clearFile" type="button">Hatao</button>`);

    $('editText').onclick = () => document.querySelector('.tab[data-pane="paste"]').click();
    $('clearFile').onclick = () => {
      fileInput.value = '';
      $('jd').value = '';
      $('preview').classList.remove('on');
      $('fileRow').classList.remove('on');
    };
  } catch (err) {
    fileStatus(escapeHtml('Upload fail hua: ' + err.message), true);
  } finally {
    drop.classList.remove('busy');
  }
}

/* ---------------- Cost hint ---------------- */

function updateHint() {
  const n = +$('limit').value;
  const perSource = $('source').value === 'both' ? 2 : 1;
  $('hint').textContent = `Approx ${n * perSource} jobs scrape honge — roughly $${(n * perSource * 0.0026).toFixed(2)} Apify credits lagenge.`;
}

$('limit').addEventListener('input', (e) => {
  $('limitVal').textContent = e.target.value;
  updateHint();
});
$('source').addEventListener('change', updateHint);
updateHint();

/* ---------------- Search ---------------- */

function log(msg, isErr) {
  const box = $('logBox');
  const d = document.createElement('div');
  d.className = 'log-line' + (isErr ? ' err' : '');
  d.innerHTML = `<b>&rsaquo;</b> ${escapeHtml(msg)}`;
  box.appendChild(d);
  box.scrollTop = box.scrollHeight;
}

$('go').addEventListener('click', async () => {
  const jobDescription = $('jd').value.trim();
  if (jobDescription.length < 20) {
    alert('Job description kam se kam 20 characters ka daaliye (ya PDF upload kariye).');
    return;
  }

  $('go').disabled = true;
  $('go').textContent = 'Searching...';
  $('log').classList.add('on');
  $('logBox').innerHTML = '';
  $('summary').classList.remove('on');
  $('results').classList.remove('on');

  try {
    const res = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jobDescription,
        limit: +$('limit').value,
        source: $('source').value,
        useAi: $('useAi').checked,
      }),
    });

    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      log(e.error || e.detail || `Request fail hua (${res.status})`, true);
      return;
    }

    // NDJSON stream padhte hain taaki progress live dikhe.
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (line.trim()) handleEvent(JSON.parse(line));
      }
    }
  } catch (err) {
    log('Error: ' + err.message, true);
  } finally {
    $('go').disabled = false;
    $('go').textContent = 'Search Jobs';
  }
});

function handleEvent(ev) {
  if (ev.type === 'progress') log(ev.message, ev.isError);
  else if (ev.type === 'error') log(ev.message, true);
  else if (ev.type === 'done') {
    log(`Ho gaya — ${ev.jobs.length} jobs table me hain.`);
    showSummary(ev);
    allJobs = ev.jobs;
    sortKey = ev.jobs.some((j) => j.matchScore != null) ? 'matchScore' : 'source';
    sortDir = -1;
    render();
  }
}

function showSummary(ev) {
  const p = ev.params || {};
  const chips = [
    `Search: <b>${escapeHtml(p.title || '-')}</b>`,
    `Location: <b>${escapeHtml(p.location || '-')} (${escapeHtml(p.country || '-')})</b>`,
  ];
  if (p.seniority && p.seniority !== 'unknown') chips.push(`Seniority: <b>${escapeHtml(p.seniority)}</b>`);
  if (p.mustHaveSkills?.length) chips.push(`Skills: <b>${escapeHtml(p.mustHaveSkills.join(', '))}</b>`);
  if (ev.usage?.prompt_tokens) {
    const t = ev.usage.prompt_tokens + ev.usage.completion_tokens;
    chips.push(`AI tokens: <b>${t.toLocaleString()}</b>`);
  }
  $('summary').innerHTML = chips.map((c) => `<div class="chip">${c}</div>`).join('');
  $('summary').classList.add('on');
}

/* ---------------- Table ---------------- */

$('filter').addEventListener('input', render);

function render() {
  const q = $('filter').value.toLowerCase();
  const rows = allJobs.filter((j) =>
    !q || (j.title || '').toLowerCase().includes(q) || (j.company || '').toLowerCase().includes(q));

  rows.sort((a, b) => {
    const col = COLS.find((c) => c.key === sortKey);
    const av = a[sortKey];
    const bv = b[sortKey];
    if (col?.num) return ((bv ?? -1) - (av ?? -1)) * (sortDir === -1 ? 1 : -1);
    return String(av ?? '').localeCompare(String(bv ?? '')) * (sortDir === -1 ? -1 : 1);
  });

  $('resTitle').textContent = `${rows.length} jobs`;
  $('thead').innerHTML = COLS.map((c) =>
    `<th data-k="${c.key}">${c.label} <span class="arr">${sortKey === c.key ? (sortDir === -1 ? '▼' : '▲') : ''}</span></th>`
  ).join('');

  $('thead').querySelectorAll('th').forEach((th) => {
    th.onclick = () => {
      const k = th.dataset.k;
      if (sortKey === k) sortDir *= -1;
      else { sortKey = k; sortDir = -1; }
      render();
    };
  });

  $('tbody').innerHTML = rows.length ? rows.map((j) => {
    const s = j.matchScore;
    const cls = s == null ? 'lo' : s >= 75 ? 'hi' : s >= 55 ? 'mid' : 'lo';
    return `<tr>
      <td><div class="score ${cls}">${s == null ? '&ndash;' : s}</div>
          ${j.matchReason ? `<div class="reason">${escapeHtml(j.matchReason)}</div>` : ''}</td>
      <td><span class="src ${escapeHtml(j.source)}">${escapeHtml(j.source)}</span></td>
      <td><a class="jt" href="${escapeHtml(j.url || '#')}" target="_blank" rel="noopener">${escapeHtml(j.title || '-')}</a></td>
      <td>${escapeHtml(j.company || '-')}</td>
      <td class="meta">${escapeHtml(j.location || '-')}</td>
      <td class="meta">${escapeHtml(j.contractType || '-')}</td>
      <td class="meta">${escapeHtml(j.experienceLevel || '-')}</td>
      <td class="meta">${escapeHtml(j.salary || '-')}</td>
      <td class="meta">${escapeHtml(j.postedAt || '-')}</td>
    </tr>`;
  }).join('') : `<tr><td colspan="${COLS.length}" class="empty">Koi job nahi mili.</td></tr>`;

  $('results').classList.add('on');
}

$('csv').addEventListener('click', () => {
  const cols = ['matchScore', 'matchReason', 'source', 'title', 'company', 'location',
    'contractType', 'experienceLevel', 'salary', 'postedAt', 'url'];
  const esc = (v) => `"${String(v ?? '').replace(/"/g, '""').replace(/\s+/g, ' ').trim()}"`;
  const csv = [cols.join(','), ...allJobs.map((j) => cols.map((c) => esc(j[c])).join(','))].join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = `jobs-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
});

/* ---------------- Startup: keys check ---------------- */

fetch('/api/health').then((r) => r.json()).then((h) => {
  $('model').textContent = h.model;
  const missing = [];
  if (!h.apifyKey) missing.push('APIFY_API_KEY');
  if (!h.openRouterKey) missing.push('OPENROUTER_API_KEY');
  if (missing.length) {
    $('log').classList.add('on');
    log(`.env me ye keys nahi mili: ${missing.join(', ')}`, true);
  }
}).catch(() => {});
