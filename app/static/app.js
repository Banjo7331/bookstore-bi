'use strict';

const state = {
  store: null,
  dateFrom: null,
  dateTo: null,
  view: 'overview',
  bookFilter: null,
  customerFilter: null,
  chips: [],
  history: [],
};

const charts = {};
const $ = (selector) => document.querySelector(selector);
const money = (value) =>
  '$' + Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const count = (value) => Number(value).toLocaleString('en-US');

function ink(name) {
  return getComputedStyle(document.body).getPropertyValue(name).trim();
}

function baseScales(extra) {
  return Object.assign({
    x: { grid: { display: false }, border: { color: ink('--axis') },
         ticks: { color: ink('--muted'), font: { size: 11 }, maxRotation: 0, autoSkipPadding: 18 } },
    y: { beginAtZero: true, grid: { color: ink('--grid'), drawTicks: false },
         border: { display: false },
         ticks: { color: ink('--muted'), font: { size: 11 },
                  callback: (v) => '$' + Number(v).toLocaleString('en-US') } },
  }, extra || {});
}

const noLegend = { legend: { display: false } };

function tooltipStyle(labelFn) {
  return {
    backgroundColor: ink('--surface'), titleColor: ink('--ink'), bodyColor: ink('--ink-2'),
    borderColor: ink('--ring'), borderWidth: 1, padding: 10, displayColors: false,
    callbacks: labelFn ? { label: labelFn } : undefined,
  };
}

function render(id, config) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart($('#' + id), config);
}

function drawDaily(rows) {
  render('dailyChart', {
    type: 'line',
    data: {
      labels: rows.map((r) => r.date),
      datasets: [{
        label: 'Revenue',
        data: rows.map((r) => r.revenue),
        borderColor: ink('--series-1'),
        backgroundColor: ink('--series-1-soft'),
        borderWidth: 2, pointRadius: 0, pointHoverRadius: 5,
        pointHoverBackgroundColor: ink('--series-1'),
        pointHoverBorderColor: ink('--surface'), pointHoverBorderWidth: 2,
        fill: true, tension: 0.15,
      }],
    },
    options: {
      maintainAspectRatio: false, responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: { ...noLegend, tooltip: tooltipStyle((c) => money(c.parsed.y)) },
      scales: baseScales(),
    },
  });
}

function drawTopDays(rows) {
  render('topDaysChart', {
    type: 'bar',
    data: {
      labels: rows.map((r) => r.date),
      datasets: [{ data: rows.map((r) => r.revenue), backgroundColor: ink('--series-1'),
                   borderRadius: 4, borderSkipped: false, barPercentage: 0.7 }],
    },
    options: {
      indexAxis: 'y', maintainAspectRatio: false, responsive: true,
      plugins: { ...noLegend, tooltip: tooltipStyle((c) => money(c.parsed.x)) },
      scales: {
        x: { beginAtZero: true, grid: { color: ink('--grid'), drawTicks: false },
             border: { display: false },
             ticks: { color: ink('--muted'), font: { size: 11 },
                      callback: (v) => '$' + Number(v).toLocaleString('en-US') } },
        y: { grid: { display: false }, border: { color: ink('--axis') },
             ticks: { color: ink('--ink-2'), font: { size: 11 } } },
      },
    },
  });
}

function drawMonth(rows) {
  render('monthChart', {
    type: 'bar',
    data: {
      labels: rows.map((r) => r.group),
      datasets: [{ data: rows.map((r) => r.revenue), backgroundColor: ink('--series-1'),
                   borderRadius: 4, borderSkipped: false, barPercentage: 0.78 }],
    },
    options: {
      maintainAspectRatio: false, responsive: true,
      plugins: { ...noLegend, tooltip: tooltipStyle((c) => money(c.parsed.y)) },
      scales: baseScales(),
    },
  });
}

function drawUnits(id, rows, colour) {
  render(id, {
    type: 'bar',
    data: {
      labels: rows.map((r) => r.group ?? '(none)'),
      datasets: [{ data: rows.map((r) => r.units), backgroundColor: ink(colour),
                   borderRadius: 4, borderSkipped: false, barPercentage: 0.72 }],
    },
    options: {
      indexAxis: 'y', maintainAspectRatio: false, responsive: true,
      plugins: { ...noLegend, tooltip: tooltipStyle((c) => count(c.parsed.x) + ' units') },
      scales: {
        x: { beginAtZero: true, grid: { color: ink('--grid'), drawTicks: false },
             border: { display: false }, ticks: { color: ink('--muted'), font: { size: 11 } } },
        y: { grid: { display: false }, border: { color: ink('--axis') },
             ticks: { color: ink('--ink-2'), font: { size: 11 },
                      callback(value) {
                        const text = this.getLabelForValue(value);
                        return text.length > 26 ? text.slice(0, 25) + '…' : text;
                      } } },
      },
    },
  });
}

function fillTable(selector, rows, cells) {
  const body = $(selector + ' tbody');
  body.innerHTML = '';
  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 9; td.className = 'note'; td.textContent = 'No rows match the current filters.';
    tr.appendChild(td); body.appendChild(tr);
    return;
  }
  for (const row of rows) {
    const tr = document.createElement('tr');
    for (const cell of cells(row)) {
      const td = document.createElement('td');
      if (cell && typeof cell === 'object') {
        td.textContent = cell.text;
        if (cell.num) td.className = 'num';
      } else {
        td.textContent = cell === null || cell === undefined ? '—' : String(cell);
      }
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
}

function query(extra) {
  const params = new URLSearchParams({ store: state.store });
  if (state.dateFrom) params.set('date_from', state.dateFrom);
  if (state.dateTo) params.set('date_to', state.dateTo);
  for (const [key, value] of Object.entries(extra || {})) {
    if (value !== null && value !== undefined && value !== '') params.set(key, value);
  }
  return params.toString();
}

async function loadDashboard() {
  const data = await fetch('/api/dashboard?' + query()).then((r) => r.json());

  $('#kpiRevenue').textContent = money(data.kpi.revenue);
  $('#kpiRevenueNote').textContent =
    `${count(data.kpi.units)} units · ${money(data.kpi.avg_order_value)} average order`;
  $('#kpiUsers').textContent = count(data.kpi.unique_users);
  $('#kpiUsersNote').textContent =
    `from ${count(data.kpi.raw_user_records)} records (${count(data.kpi.raw_user_records - data.kpi.unique_users)} aliases)`;
  $('#kpiAuthorSets').textContent = count(data.kpi.unique_author_sets);
  $('#kpiBooksNote').textContent = `${count(data.kpi.books)} titles in the catalogue`;
  $('#kpiOrders').textContent = count(data.kpi.orders);
  $('#kpiOrdersNote').textContent = `${count(data.daily_revenue.length)} days with sales`;

  $('#dailySub').textContent = data.daily_revenue.length
    ? `${data.daily_revenue[0].date} – ${data.daily_revenue[data.daily_revenue.length - 1].date}`
    : '';

  const popular = data.most_popular_author_set;
  $('#popularAuthors').textContent = popular.authors;
  $('#popularAuthorsNote').textContent = `${count(popular.books_sold)} copies sold (author set)`;
  const single = data.most_popular_single_author;
  $('#popularSingle').textContent = single
    ? `Most popular individual author: ${single.author} (${count(single.books_sold)} units)` : '';

  const buyer = data.best_buyer;
  $('#bestBuyerIds').textContent = '[' + buyer.user_ids.join(', ') + ']';
  $('#bestBuyerNote').textContent = `${money(buyer.total_spent)} in total`;
  $('#bestBuyerNames').textContent = buyer.names.length > 1
    ? `Names in the data (aliases): ${buyer.names.join(' · ')}`
    : `Name: ${buyer.names[0] || '—'}`;

  fillTable('#topDaysTable', data.top_5_days,
    (row) => [row.date, { text: money(row.revenue), num: true }]);

  drawDaily(data.daily_revenue);
  drawTopDays(data.top_5_days);
  drawMonth(data.by_month);
  drawUnits('genreChart', data.by_genre, '--series-1');
  drawUnits('booksChart', data.top_books, '--series-2');
}

async function loadBooks() {
  const extra = {};
  if (state.bookFilter) {
    if (state.bookFilter.book_ids && state.bookFilter.book_ids.length) {
      extra.book_ids = state.bookFilter.book_ids.join(',');
      extra.mode = state.bookFilter.mode || 'include';
    }
    if (state.bookFilter.title_contains) extra.title_contains = state.bookFilter.title_contains;
    if (state.bookFilter.genre) extra.genre = state.bookFilter.genre;
  }
  const data = await fetch('/api/books?' + query(extra)).then((r) => r.json());
  $('#booksSub').textContent = `${count(data.returned)} of ${count(data.matched_books)} titles`;
  fillTable('#booksTable', data.books, (row) => [
    { text: row.id, num: true }, row.title, row.author_label, row.genre,
    { text: row.year ? Math.round(row.year) : '—', num: true },
    { text: count(row.units_sold), num: true },
    { text: money(row.revenue_usd), num: true },
  ]);
}

async function loadCustomers() {
  const extra = {};
  if (state.customerFilter) {
    if (state.customerFilter.email_starts_with) extra.email_starts_with = state.customerFilter.email_starts_with;
    if (state.customerFilter.name_contains) extra.name_contains = state.customerFilter.name_contains;
    if (state.customerFilter.min_spend) extra.min_spend = state.customerFilter.min_spend;
  }
  const data = await fetch('/api/customers?' + query(extra)).then((r) => r.json());
  let people = data.people;
  if (state.customerFilter && state.customerFilter.person_ids && state.customerFilter.person_ids.length) {
    const wanted = new Set(state.customerFilter.person_ids);
    people = people.filter((p) => wanted.has(p.person_id));
  }
  $('#customersSub').textContent = `${count(people.length)} of ${count(data.matched_people)} real people`;
  fillTable('#customersTable', people, (row) => [
    row.names.join(' · '), '[' + row.user_ids.join(', ') + ']', row.emails.join(' · '),
    { text: count(row.orders), num: true },
    { text: money(row.total_spent_usd), num: true },
  ]);
}

function renderChips() {
  const box = $('#chips');
  box.innerHTML = '';
  box.hidden = state.chips.length === 0;
  state.chips.forEach((chip, index) => {
    const el = document.createElement('span');
    el.className = 'chip';
    el.textContent = chip.label;
    const close = document.createElement('button');
    close.type = 'button';
    close.textContent = '×';
    close.setAttribute('aria-label', 'Remove filter');
    close.addEventListener('click', () => {
      state.chips.splice(index, 1);
      if (chip.kind === 'books') state.bookFilter = null;
      if (chip.kind === 'customers') state.customerFilter = null;
      if (chip.kind === 'dates') { state.dateFrom = state.dateTo = null; $('#dateFrom').value = ''; $('#dateTo').value = ''; }
      refresh();
    });
    el.appendChild(close);
    box.appendChild(el);
  });
}

function setView(view) {
  state.view = view;
  document.querySelectorAll('.tab').forEach((tab) =>
    tab.classList.toggle('is-active', tab.dataset.view === view));
  document.querySelectorAll('.view').forEach((section) =>
    section.classList.toggle('is-active', section.dataset.view === view));
  if (location.hash.slice(1) !== view) history.replaceState(null, '', '#' + view);
}

async function refresh() {
  renderChips();
  await Promise.all([loadDashboard(), loadBooks(), loadCustomers()]);
}

function applyUiAction(action) {
  if (action.type === 'set_store') {
    state.store = action.store;
    $('#store').value = action.store;
  } else if (action.type === 'set_view') {
    setView(action.view);
  } else if (action.type === 'set_date_range') {
    state.dateFrom = action.date_from || null;
    state.dateTo = action.date_to || null;
    $('#dateFrom').value = state.dateFrom || '';
    $('#dateTo').value = state.dateTo || '';
    state.chips = state.chips.filter((c) => c.kind !== 'dates');
    if (state.dateFrom || state.dateTo) {
      state.chips.push({ kind: 'dates', label: `Dates: ${state.dateFrom || '…'} → ${state.dateTo || '…'}` });
    }
  } else if (action.type === 'filter_books') {
    state.bookFilter = action;
    state.chips = state.chips.filter((c) => c.kind !== 'books');
    state.chips.push({ kind: 'books', label: action.label });
    setView('catalog');
  } else if (action.type === 'filter_customers') {
    state.customerFilter = action;
    state.chips = state.chips.filter((c) => c.kind !== 'customers');
    state.chips.push({ kind: 'customers', label: action.label });
    setView('catalog');
  } else if (action.type === 'reset_filters') {
    state.bookFilter = state.customerFilter = null;
    state.dateFrom = state.dateTo = null;
    state.chips = [];
    $('#dateFrom').value = ''; $('#dateTo').value = '';
  }
}

function bubble(className, text) {
  const el = document.createElement('div');
  el.className = 'bubble ' + className;
  const p = document.createElement('p');
  p.textContent = text;
  el.appendChild(p);
  $('#chatLog').appendChild(el);
  $('#chatLog').scrollTop = $('#chatLog').scrollHeight;
  return el;
}

async function ask(question) {
  bubble('me', question);
  state.history.push({ role: 'user', content: question });
  const pending = bubble('bot', 'Working…');

  let payload;
  try {
    const response = await fetch('/api/chat', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ store: state.store, messages: state.history }),
    });
    payload = await response.json();
  } catch (error) {
    pending.className = 'bubble err';
    pending.firstChild.textContent = 'Could not reach the server.';
    return;
  }

  if (payload.error) {
    pending.className = 'bubble err';
    pending.firstChild.textContent = payload.error;
    state.history.pop();
    return;
  }

  pending.firstChild.textContent = payload.reply || '(no answer)';
  state.history.push({ role: 'assistant', content: payload.reply || '' });

  if (payload.tool_calls && payload.tool_calls.length) {
    const trace = document.createElement('div');
    trace.className = 'trace';
    trace.textContent = 'API: ' + payload.tool_calls
      .map((c) => c.tool + (c.ok ? '' : ' ✗')).join(' → ');
    pending.appendChild(trace);
  }

  if (payload.ui_actions && payload.ui_actions.length) {
    payload.ui_actions.forEach(applyUiAction);
    await refresh();
  }
  $('#chatLog').scrollTop = $('#chatLog').scrollHeight;
}

document.addEventListener('DOMContentLoaded', () => {
  state.store = $('#store').value;
  const wanted = location.hash.slice(1);
  if (['overview', 'revenue', 'catalog'].includes(wanted)) setView(wanted);

  $('#store').addEventListener('change', (event) => {
    state.store = event.target.value;
    refresh();
  });
  ['dateFrom', 'dateTo'].forEach((id) => {
    $('#' + id).addEventListener('change', () => {
      state.dateFrom = $('#dateFrom').value || null;
      state.dateTo = $('#dateTo').value || null;
      state.chips = state.chips.filter((c) => c.kind !== 'dates');
      if (state.dateFrom || state.dateTo) {
        state.chips.push({ kind: 'dates', label: `Dates: ${state.dateFrom || '…'} → ${state.dateTo || '…'}` });
      }
      refresh();
    });
  });
  $('#resetFilters').addEventListener('click', () => {
    applyUiAction({ type: 'reset_filters' });
    refresh();
  });
  document.querySelectorAll('.tab').forEach((tab) =>
    tab.addEventListener('click', () => setView(tab.dataset.view)));
  document.querySelectorAll('.examples button').forEach((button) =>
    button.addEventListener('click', () => ask(button.textContent)));
  $('#chatForm').addEventListener('submit', (event) => {
    event.preventDefault();
    const text = $('#chatInput').value.trim();
    if (!text) return;
    $('#chatInput').value = '';
    ask(text);
  });

  refresh();
});
