/* Personal, reversible review. Does not modify the shared report or CSV. */
(async function () {
  const list = document.querySelector('.results-list');
  const summary = document.querySelector('.summary');
  const originalSummary = summary.textContent;
  const cards = Array.from(list.children);
  const choices = {};
  const original = new Map();
  const selections = new Map();
  const candidatesByRow = cards.map(card => card.dataset.status === 'ambiguous'
    ? Array.from(card.querySelectorAll('.candidate-card')) : []);
  if (!cards.some(card => card.dataset.status === 'ambiguous')) return;
  const styles = document.createElement('style');
  styles.textContent = `
    .manual-toolbar { margin: 20px 0; padding: 14px; border: 1px solid GrayText; border-radius: 12px; }
    .manual-toolbar p { margin-bottom: 8px; }
    .manual-action { font: inherit; padding: 7px 12px; border: 1px solid GrayText; border-radius: 8px; color: CanvasText; background: Canvas; cursor: pointer; margin: 6px 6px 0 0; }
    .manual-action:focus-visible { outline: 3px solid LinkText; outline-offset: 3px; }
    .manual-note { font-size: .85rem; margin: 6px 0; }
    .manual-flash { outline: 2px solid LinkText; outline-offset: 3px; }
    .candidate-list { grid-auto-rows: 1fr; }
    .already-matched-note, .manually-confirmed-tag { display: inline-block; font-size: .75rem; padding: 3px 7px; border: 1px solid GrayText; border-radius: 999px; vertical-align: middle; margin: 6px 0 0 4px; }
  `;
  document.head.append(styles);
  const toolbar = document.createElement('section');
  toolbar.className = 'manual-toolbar';
  const explanation = document.createElement('p');
  explanation.textContent = 'Personal review — choices apply only in this browser. They do not change the shared report or CSV, or affect other visitors. Export selections to keep a record.';
  const message = document.createElement('p');
  message.setAttribute('role', 'status');
  toolbar.append(explanation, message);
  document.querySelector('header').after(toolbar);
  const button = (text, action) => {
    const el = document.createElement('button');
    el.type = 'button'; el.className = 'manual-action'; el.textContent = text;
    el.addEventListener('click', action); return el;
  };
  const rating = card => {
    const el = card.querySelector('.rating-badge');
    const number = Number.parseFloat(el ? el.textContent : '');
    return Number.isFinite(number) ? number : -Infinity;
  };
  const baselineRatings = new Map(cards.map(card => [card, rating(card)]));
  // Hash the original report, not its filesystem path or title alone.
  let reportId = null;
  let storageKey = null;
  try {
    const bytes = new TextEncoder().encode(list.innerHTML + originalSummary + document.title);
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    reportId = Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, '0')).join('');
    storageKey = 'untap-review-v1:' + reportId;
  } catch (_) {
    message.textContent = 'Browser saving is unavailable here. Export your selections before closing.';
  }
  function updateAlreadyMatchedHints() {
    const beerId = card => {
      const link = card.querySelector('.beer-link');
      if (!link) return null;
      try {
        const url = new URL(link.href);
        if (!['untappd.com', 'www.untappd.com'].includes(url.hostname)) return null;
        const match = url.pathname.match(/\/b\/[^/]+\/(\d+)\/?$/);
        return match ? match[1] : null;
      } catch (_) { return null; }
    };
    const confirmed = cards.filter(card => card.dataset.status === 'ok');
    cards.filter(card => card.dataset.status === 'ambiguous').forEach(group => {
      group.querySelectorAll('.candidate-card').forEach(candidate => {
        candidate.querySelectorAll('.already-matched-note').forEach(note => note.remove());
        const id = beerId(candidate);
        if (!id || !confirmed.some(card => card !== group && beerId(card) === id)) return;
        const note = document.createElement('span');
        note.className = 'manual-note already-matched-note';
        note.textContent = 'Already matched';
        note.title = 'Already matched to another menu item';
        note.setAttribute('aria-label', note.title);
        const content = candidate.lastElementChild;
        content.append(note);
      });
    });
  }
  function refresh() {
    updateAlreadyMatchedHints();
    cards.slice().sort((a, b) => {
      const ar = selections.has(a) ? rating(a) : baselineRatings.get(a);
      const br = selections.has(b) ? rating(b) : baselineRatings.get(b);
      return (br > ar ? 1 : br < ar ? -1 : 0) || cards.indexOf(a) - cards.indexOf(b);
    }).forEach(card => list.append(card));
    const count = status => cards.filter(card => card.dataset.status === status).length;
    const other = cards.length - count('ok') - count('ambiguous') - count('failed');
    summary.textContent = `${cards.length} beers · ${count('ok')} confirmed (${selections.size} manually) · ${count('ambiguous')} ambiguous` +
      (count('failed') ? ` · ${count('failed')} failed` : '') + (other ? ` · ${other} unresolved` : '');
    // Existing filtering handlers retain references to the original group elements.
    const all = document.querySelector('input[data-status-filter]:checked');
    if (all) all.dispatchEvent(new Event('change'));
    // Selected cards no longer contain candidate cards; apply their own style.
    const enabled = new Set(Array.from(document.querySelectorAll('input[data-style-filter]:checked'), el => el.value));
    selections.forEach((_, card) => {
      card.hidden = (all && all.value !== 'all' && all.value !== 'ok') ||
        (Boolean(card.dataset.styleGroup) && !enabled.has(card.dataset.styleGroup));
    });
  }
  function persist() {
    try {
      if (!storageKey) throw new Error();
      localStorage.setItem(storageKey, JSON.stringify(choices));
      message.textContent = 'Choices saved in this browser. Export to keep them outside the browser.';
    } catch (_) {
      message.textContent = 'Browser saving is unavailable. Export your selections before closing.';
    }
  }
  function focusCard(card, control) {
    const all = document.querySelector('input[data-status-filter][value="all"]');
    if (all) { all.checked = true; all.dispatchEvent(new Event('change')); }
    const style = Array.from(document.querySelectorAll('input[data-style-filter]')).find(el => el.value === card.dataset.styleGroup);
    if (style && !style.checked) { style.checked = true; style.dispatchEvent(new Event('change')); }
    card.hidden = false;
    control.focus({preventScroll: true});
    card.scrollIntoView({block: 'nearest', behavior: 'auto'});
    card.classList.add('manual-flash');
    setTimeout(() => card.classList.remove('manual-flash'), 1500);
  }
  function choose(card, index, candidate, url, interactive = true) {
    if (selections.has(card)) return;
    original.set(card, {nodes: Array.from(card.childNodes), className: card.className});
    card.replaceChildren();
    card.className = 'beer-card' + (candidate.querySelector('.beer-label') ? ' has-label' : '');
    card.dataset.status = 'ok';
    card.dataset.styleGroup = candidate.dataset.styleGroup || '';
    // Move the original nodes so thumbnail preview listeners remain attached.
    const nodes = Array.from(candidate.childNodes);
    nodes.forEach(node => card.append(node));
    const content = card.lastElementChild;
    content.querySelectorAll('.manual-action, .already-matched-note').forEach(el => el.remove());
    const note = document.createElement('span'); note.className = 'manual-note manually-confirmed-tag';
    note.textContent = 'Manually confirmed';
    const undo = button('Change selection', () => {
      note.remove(); undo.remove();
      nodes.forEach(node => candidate.append(node));
      const previous = original.get(card);
      card.replaceChildren(...previous.nodes); card.className = previous.className;
      card.dataset.status = 'ambiguous'; delete card.dataset.styleGroup;
      selections.delete(card); delete choices[index];
      addButtons(card, index); refresh(); persist();
      focusCard(card, card.querySelector('.manual-action'));
    });
    content.append(undo, note);
    selections.set(card, url); choices[index] = url;
    refresh();
    if (interactive) { persist(); focusCard(card, undo); }
  }
  function addButtons(card, index) {
    card.querySelectorAll('.candidate-card').forEach(candidate => {
      if (candidate.querySelector('.manual-action')) return;
      const link = candidate.querySelector('.beer-link');
      if (!link) return;
      const url = new URL(link.href);
      if (url.protocol !== 'https:' || !['untappd.com', 'www.untappd.com'].includes(url.hostname) || !/\/b\/[^/]+\/\d+\/?$/.test(url.pathname)) return;
      candidate.lastElementChild.append(button('Confirm this beer', () => choose(card, index, candidate, url.href)));
    });
  }
  cards.forEach((card, index) => { if (card.dataset.status === 'ambiguous') addButtons(card, index); });
  toolbar.append(button('Export selections', () => {
    const payload = {format: 'untap-manual-review-trial-v1', report_id: reportId,
      title: document.title, selections: Object.entries(choices).map(([index, url]) => ({row: Number(index), url}))};
    const blob = new Blob([JSON.stringify(payload, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob); const link = document.createElement('a');
    link.href = url; link.download = 'untap-selections.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }));
  updateAlreadyMatchedHints();
  const importFile = document.createElement('input');
  importFile.type = 'file'; importFile.accept = '.json,application/json'; importFile.hidden = true;
  toolbar.append(importFile, button('Import selections', () => importFile.click()));
  importFile.addEventListener('change', async () => {
    const file = importFile.files[0];
    if (!file) return;
    try {
      if (file.size > 1000000) throw new Error('File is too large.');
      const payload = JSON.parse(await file.text());
      if (!payload || payload.format !== 'untap-manual-review-trial-v1' ||
          !reportId || payload.report_id !== reportId || !Array.isArray(payload.selections)) {
        throw new Error('This is not a selections file for this exact report.');
      }
      const seen = new Set();
      // Validate the entire file before changing any choices.
      const entries = payload.selections.map(entry => {
        if (!entry || !Number.isInteger(entry.row) || seen.has(entry.row) ||
            typeof entry.url !== 'string') throw new Error('Invalid or duplicate selection row.');
        seen.add(entry.row);
        const candidate = candidatesByRow[entry.row]?.find(el =>
          el.querySelector('.beer-link')?.href === entry.url);
        if (!candidate || !/^https:\/\/(www\.)?untappd\.com\/b\/[^/]+\/\d+\/?$/.test(entry.url)) {
          throw new Error('A selection is not an available candidate.');
        }
        return {card: cards[entry.row], candidate, row: entry.row, url: entry.url};
      });
      entries.forEach(({card, candidate, row, url}) => {
        if (selections.get(card) === url) return;
        if (selections.has(card)) card.querySelector('.manual-action').click();
        choose(card, row, candidate, url, false);
      });
      persist();
      message.textContent = 'Imported ' + entries.length + ' selections. Other choices were kept. ' + message.textContent;
    } catch (error) {
      message.textContent = 'Could not import selections: ' + error.message;
    } finally { importFile.value = ''; }
  });
  if (storageKey) {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
      cards.forEach((card, index) => {
        if (card.dataset.status !== 'ambiguous' || typeof saved[index] !== 'string') return;
        const candidate = Array.from(card.querySelectorAll('.candidate-card')).find(el => el.querySelector('.beer-link')?.href === saved[index]);
        if (candidate) choose(card, index, candidate, saved[index], false);
      });
      if (selections.size) message.textContent = 'Restored your choices for this report.';
    } catch (_) { message.textContent = 'Saved choices could not be loaded; the original report is shown.'; }
  }
  // Run after the report's existing handlers, including after future filter changes.
  document.querySelectorAll('input[data-style-filter], input[data-status-filter]').forEach(el => el.addEventListener('change', () => {
    const status = document.querySelector('input[data-status-filter]:checked')?.value || 'all';
    const enabled = new Set(Array.from(document.querySelectorAll('input[data-style-filter]:checked'), input => input.value));
    selections.forEach((_, card) => { card.hidden = (status !== 'all' && status !== 'ok') || (Boolean(card.dataset.styleGroup) && !enabled.has(card.dataset.styleGroup)); });
  }));
})();
