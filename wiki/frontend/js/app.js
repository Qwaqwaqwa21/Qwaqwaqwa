const API = "/api";

const state = {
  pages: [],
  currentSlug: null,
  currentPage: null,
  view: "article", // 'article' | 'edit' | 'history' | 'revision' | 'new'
};

const els = {
  pageList: document.getElementById("pageList"),
  content: document.getElementById("content"),
  searchBox: document.getElementById("searchBox"),
  editorName: document.getElementById("editorName"),
  roleSelect: document.getElementById("activeRoleSelect"),
  newPageBtn: document.getElementById("newPageBtn"),
};

function loadPrefs() {
  els.editorName.value = localStorage.getItem("wiki_editor_name") || "";
  els.roleSelect.value = localStorage.getItem("wiki_role") || "viewer";
}
els.editorName.addEventListener("change", () => localStorage.setItem("wiki_editor_name", els.editorName.value));
els.roleSelect.addEventListener("change", () => {
  localStorage.setItem("wiki_role", els.roleSelect.value);
  if (state.view === "article" && state.currentPage) renderArticle();
});

function authHeaders(extra) {
  return Object.assign(
    { "Content-Type": "application/json", "X-Role": els.roleSelect.value },
    extra || {}
  );
}

async function api(path, opts) {
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

async function loadPages(q) {
  state.pages = await api("/pages" + (q ? `?q=${encodeURIComponent(q)}` : ""));
  renderPageList();
}

function renderPageList() {
  const groups = {};
  for (const p of state.pages) {
    groups[p.category] = groups[p.category] || [];
    groups[p.category].push(p);
  }
  let html = "";
  for (const cat of Object.keys(groups).sort()) {
    html += `<div class="category-group"><div class="category-title">${cat}</div>`;
    for (const p of groups[cat]) {
      const active = p.slug === state.currentSlug ? "active" : "";
      html += `<button class="wiki-page-card ${active}" data-slug="${p.slug}">${p.title}</button>`;
    }
    html += `</div>`;
  }
  els.pageList.innerHTML = html || `<div class="empty-state">Ничего не найдено</div>`;
  els.pageList.querySelectorAll(".wiki-page-card").forEach(btn => {
    btn.addEventListener("click", () => openArticle(btn.dataset.slug));
  });
}

let searchTimer = null;
els.searchBox.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadPages(els.searchBox.value.trim()), 250);
});

function canEdit() {
  return els.roleSelect.value === "editor" || els.roleSelect.value === "admin";
}
function isAdmin() {
  return els.roleSelect.value === "admin";
}

async function openArticle(slug) {
  state.currentSlug = slug;
  state.currentPage = await api(`/pages/${slug}`);
  renderPageList();
  renderArticle();
}

function renderArticle() {
  state.view = "article";
  const p = state.currentPage;
  const bodyHtml = renderMarkdown(p.content);
  els.content.innerHTML = `
    <div class="article-toolbar">
      <button class="btn" id="wikiEditBtn" ${canEdit() ? "" : "disabled"}>Редактировать</button>
      <button class="btn" id="wikiHistoryBtn">История</button>
      ${isAdmin() ? '<button class="btn danger" id="wikiDeleteBtn">Удалить</button>' : ""}
    </div>
    <h1>${p.title}</h1>
    <div class="article-meta">${p.category} · обновлено ${p.updated_at} пользователем ${p.updated_by || "—"}</div>
    <div class="article-body">${bodyHtml}</div>
  `;
  document.getElementById("wikiEditBtn").addEventListener("click", () => renderEdit());
  document.getElementById("wikiHistoryBtn").addEventListener("click", () => renderHistory());
  const delBtn = document.getElementById("wikiDeleteBtn");
  if (delBtn) delBtn.addEventListener("click", onDelete);
}

function renderEdit() {
  const p = state.currentPage;
  state.view = "edit";
  els.content.innerHTML = `
    <div class="article-toolbar">
      <button class="btn" id="wikiCancelEditBtn">Отмена</button>
      <button class="btn primary" id="wikiSaveBtn">Сохранить</button>
    </div>
    <div class="field-label">Заголовок</div>
    <input id="editTitle" value="${p.title.replace(/"/g, "&quot;")}">
    <div class="field-label">Категория</div>
    <input id="editCategory" value="${p.category.replace(/"/g, "&quot;")}">
    <div class="field-label">Содержимое (Markdown)</div>
    <textarea id="editContent">${p.content}</textarea>
  `;
  document.getElementById("wikiCancelEditBtn").addEventListener("click", renderArticle);
  document.getElementById("wikiSaveBtn").addEventListener("click", onSave);
}

async function onSave() {
  const title = document.getElementById("editTitle").value.trim();
  const category = document.getElementById("editCategory").value.trim();
  const content = document.getElementById("editContent").value;
  const comment = prompt("Комментарий к правке (необязательно):", "") || "";
  try {
    state.currentPage = await api(`/pages/${state.currentSlug}`, {
      method: "PUT",
      headers: authHeaders(),
      body: JSON.stringify({ title, category, content, editor_name: els.editorName.value, comment }),
    });
    await loadPages(els.searchBox.value.trim());
    renderArticle();
  } catch (e) {
    alert("Не удалось сохранить: " + e.message);
  }
}

async function onDelete() {
  if (!confirm(`Удалить страницу «${state.currentPage.title}»?`)) return;
  try {
    await api(`/pages/${state.currentSlug}`, { method: "DELETE", headers: authHeaders() });
    state.currentSlug = null;
    state.currentPage = null;
    await loadPages();
    renderEmpty();
  } catch (e) {
    alert("Не удалось удалить: " + e.message);
  }
}

async function renderHistory() {
  state.view = "history";
  const revisions = await api(`/pages/${state.currentSlug}/history`);
  let rowsHtml = revisions.length
    ? revisions.map(r => `
      <div class="history-row">
        <div>
          <div>${r.title}</div>
          <div class="article-meta">${r.edited_at} · ${r.edited_by || "—"} ${r.comment ? "· " + r.comment : ""}</div>
        </div>
        <div>
          <button class="btn" data-rev="${r.id}" data-action="view">Просмотр</button>
          ${canEdit() ? `<button class="btn" data-rev="${r.id}" data-action="revert">Откатить</button>` : ""}
        </div>
      </div>
    `).join("")
    : `<div class="empty-state">Правок пока нет</div>`;

  els.content.innerHTML = `
    <div class="article-toolbar">
      <button class="btn" id="wikiHistBackBtn">Назад к странице</button>
    </div>
    <h1>История: ${state.currentPage.title}</h1>
    ${rowsHtml}
  `;
  document.getElementById("wikiHistBackBtn").addEventListener("click", renderArticle);
  els.content.querySelectorAll("[data-action='view']").forEach(btn =>
    btn.addEventListener("click", () => viewRevision(btn.dataset.rev)));
  els.content.querySelectorAll("[data-action='revert']").forEach(btn =>
    btn.addEventListener("click", () => revertRevision(btn.dataset.rev)));
}

async function viewRevision(id) {
  const rev = await api(`/pages/${state.currentSlug}/history/${id}`);
  els.content.innerHTML = `
    <div class="article-toolbar">
      <button class="btn" id="wikiRevBackBtn">Назад к истории</button>
    </div>
    <h1>${rev.title} <span class="article-meta">(версия от ${rev.edited_at})</span></h1>
    <div class="article-body">${renderMarkdown(rev.content)}</div>
  `;
  document.getElementById("wikiRevBackBtn").addEventListener("click", renderHistory);
}

async function revertRevision(id) {
  if (!confirm("Откатить страницу к этой версии?")) return;
  try {
    state.currentPage = await api(`/pages/${state.currentSlug}/revert/${id}?editor_name=${encodeURIComponent(els.editorName.value)}`, {
      method: "POST",
      headers: authHeaders(),
    });
    await loadPages(els.searchBox.value.trim());
    renderArticle();
  } catch (e) {
    alert("Не удалось откатить: " + e.message);
  }
}

function renderEmpty() {
  els.content.innerHTML = `<div class="empty-state">Выберите страницу слева или создайте новую.</div>`;
}

els.newPageBtn.addEventListener("click", () => {
  if (!canEdit()) { alert("Нужна роль «Редактор» или выше"); return; }
  state.view = "new";
  els.content.innerHTML = `
    <div class="article-toolbar">
      <button class="btn" id="wikiCancelNewBtn">Отмена</button>
      <button class="btn primary" id="wikiCreateBtn">Создать</button>
    </div>
    <div class="field-label">Заголовок</div>
    <input id="editTitle" placeholder="Название страницы">
    <div class="field-label">Категория</div>
    <input id="editCategory" placeholder="Общее" value="Общее">
    <div class="field-label">Содержимое (Markdown)</div>
    <textarea id="editContent" placeholder="# Заголовок&#10;&#10;Текст страницы..."></textarea>
  `;
  document.getElementById("wikiCancelNewBtn").addEventListener("click", renderEmpty);
  document.getElementById("wikiCreateBtn").addEventListener("click", onCreate);
});

async function onCreate() {
  const title = document.getElementById("editTitle").value.trim();
  const category = document.getElementById("editCategory").value.trim() || "Общее";
  const content = document.getElementById("editContent").value;
  if (!title) { alert("Укажите заголовок"); return; }
  try {
    const page = await api("/pages", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ title, category, content, editor_name: els.editorName.value }),
    });
    await loadPages();
    openArticle(page.slug);
  } catch (e) {
    alert("Не удалось создать страницу: " + e.message);
  }
}

(async function init() {
  loadPrefs();
  await loadPages();
  if (state.pages.length) {
    await openArticle(state.pages[0].slug);
  } else {
    renderEmpty();
  }
})();
