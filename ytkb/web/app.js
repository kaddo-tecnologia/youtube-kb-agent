"use strict";
// Painel do youtube-kb-agent. Todo Markdown vem de conteúdo não confiável (transcrições + LLM):
// sempre passa por DOMPurify antes de virar HTML. Sem handlers inline (CSP script-src 'self').

let selectedSlug = null;
let activeTab = "formatted"; // "formatted" | "raw" | "sources" | "skill"
let currentKbMarkdown = "";
let currentSkillMarkdown = "";
let currentVideos = [];
let currentQueries = [];
let cachedBases = [];
let formDirty = false;
let lastRenderKey = "";

const $ = (id) => document.getElementById(id);
const durationSelect = $("durationSelect");
const customMinutes = $("customMinutes");

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function safeHttpUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : "#";
  } catch {
    return "#";
  }
}

if (window.DOMPurify) {
  // Links do conteúdo abrem fora do painel e sem vazar referrer.
  window.DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A") {
      node.setAttribute("target", "_blank");
      node.setAttribute("rel", "noopener noreferrer");
    }
  });
}

function showToast(message, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  $("toastStack").appendChild(el);
  setTimeout(() => el.remove(), 3800);
}

async function api(path, body) {
  const opts = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  let data = {};
  try {
    data = await res.json();
  } catch {
    data = {};
  }
  return { ok: res.ok, status: res.status, data };
}

function formatSecs(sec) {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m ${String(r).padStart(2, "0")}s`;
  return `${String(m).padStart(2, "0")}m ${String(r).padStart(2, "0")}s`;
}

function renderMarkdownHtml(md) {
  if (!md || !md.trim()) {
    return `<p style="color:var(--text-muted)">Nenhum conteúdo disponível.</p>`;
  }
  if (window.marked && window.DOMPurify) {
    return `<div class="markdown-prose">${window.DOMPurify.sanitize(window.marked.parse(md))}</div>`;
  }
  return `<div class="raw-editor-view">${escapeHtml(md)}</div>`;
}

function renderSourcesView() {
  const vids = currentVideos || [];
  const queries = currentQueries || [];
  const vidsHtml = vids.length
    ? `<div class="sources-grid">${vids.map((v, i) => `
        <div class="source-card">
          <div>
            <span style="font-size:0.72rem;color:var(--accent-blue);font-family:'JetBrains Mono',monospace">#${i + 1} · ${escapeHtml(v.id)}</span>
            <div style="margin-top:4px"><a href="${escapeHtml(safeHttpUrl(v.url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(v.title || v.url)}</a></div>
          </div>
          <div class="source-footer">
            <span>${escapeHtml(v.channel || "YouTube")}</span>
            <span>${formatSecs(v.duration_sec || 0)} · ${escapeHtml(v.processed_at || "")}</span>
          </div>
        </div>`).join("")}</div>`
    : `<p style="color:var(--text-muted)">Nenhum vídeo processado ainda nesta base.</p>`;

  const queriesHtml = queries.length
    ? `<div class="query-chips">${queries.map((q) => `<span class="query-chip">${escapeHtml(q)}</span>`).join("")}</div>`
    : `<p style="color:var(--text-muted)">Nenhuma busca automática registrada.</p>`;

  return `
    <div class="sources-container">
      <div>
        <h2 style="margin-top:0">Vídeos Processados e Integrados (${vids.length})</h2>
        <p style="color:var(--text-muted);font-size:0.84rem">Cada vídeo abaixo teve a legenda lida via <code>yt-dlp</code> e seus conceitos inéditos fundidos na base sem repetição.</p>
        ${vidsHtml}
      </div>
      <div>
        <h3>Consultas de Busca Executadas (${queries.length})</h3>
        ${queriesHtml}
      </div>
    </div>`;
}

function updateStudioView() {
  const bodyEl = $("studioBody");
  const baseMeta = cachedBases.find((b) => b.slug === selectedSlug);
  const isSkillTab = activeTab === "skill";
  const activeText = isSkillTab ? currentSkillMarkdown : currentKbMarkdown;
  const words = activeText.trim() ? activeText.trim().split(/\s+/).length : 0;

  $("metricFile").textContent = isSkillTab ? `skills/${selectedSlug || "—"}/SKILL.md` : `knowledge/${selectedSlug || "—"}.md`;
  $("metricVideos").textContent = String((currentVideos || []).length);
  $("metricQueries").textContent = String((currentQueries || []).length);
  $("metricWords").textContent = words.toLocaleString("pt-BR");
  $("metricSkill").textContent = baseMeta && baseMeta.has_skill ? "Gerada (revise antes de instalar)" : "Não gerada";

  document.querySelectorAll("[data-tab]").forEach((btn) => {
    btn.className = "tab-btn" + (btn.dataset.tab === activeTab ? " active" : "");
  });

  // O polling chama isto a cada 2,5 s; redesenhar sem mudança apaga a seleção de texto do usuário.
  const renderKey = [activeTab, selectedSlug, activeText, (currentVideos || []).length, (currentQueries || []).length].join("\u0000");
  if (renderKey === lastRenderKey) return;
  lastRenderKey = renderKey;

  if (activeTab === "formatted") {
    bodyEl.innerHTML = renderMarkdownHtml(currentKbMarkdown);
  } else if (activeTab === "raw") {
    bodyEl.innerHTML = `<div class="raw-editor-view">${escapeHtml(currentKbMarkdown)}</div>`;
  } else if (activeTab === "sources") {
    bodyEl.innerHTML = renderSourcesView();
  } else if (!currentSkillMarkdown) {
    bodyEl.innerHTML = `
      <div class="markdown-prose" style="text-align:center;padding:48px 20px">
        <h2>Skill ainda não gerada para este assunto</h2>
        <p>Clique em <strong>Criar / Atualizar Skill</strong> para converter esta base em <code>skills/${escapeHtml(selectedSlug)}/SKILL.md</code>.</p>
      </div>`;
  } else {
    bodyEl.innerHTML = renderMarkdownHtml(currentSkillMarkdown) +
      `<hr style="border-color:var(--border-subtle);margin:28px 0"/><h3 style="max-width:920px;margin:0 auto 10px auto">Código-Fonte Bruto (SKILL.md)</h3><div class="raw-editor-view">${escapeHtml(currentSkillMarkdown)}</div>`;
  }
}

async function setStudioTab(tab) {
  activeTab = tab;
  if (tab === "skill" && selectedSlug) {
    const { ok, data } = await api(`/api/skill?slug=${encodeURIComponent(selectedSlug)}`);
    currentSkillMarkdown = ok ? data.content || "" : "";
  }
  updateStudioView();
}

async function selectKb(slug) {
  selectedSlug = slug;
  const { ok, data } = await api(`/api/kb?slug=${encodeURIComponent(slug)}`);
  if (ok) {
    currentKbMarkdown = data.content || "";
    currentVideos = data.processed_videos || [];
    currentQueries = data.used_queries || [];
  }
  if (activeTab === "skill") await setStudioTab("skill");
  else updateStudioView();
  refreshStatus();
}

async function createSkillFromSelected() {
  if (!selectedSlug) return;
  const { ok, data } = await api("/api/create-skill", { slug: selectedSlug });
  if (!ok) return showToast(data.error || "Não foi possível gerar a Skill.", "error");
  showToast(`Gerando Skill em skills/${selectedSlug}/SKILL.md via Ollama...`, "success");
  await refreshStatus();
}

async function processSingleUrl() {
  const input = $("singleUrlInput");
  const url = input.value.trim();
  if (!url) return showToast("Cole um link válido do YouTube.", "error");
  const { ok, data } = await api("/api/process-url", { url });
  if (!ok) return showToast(data.error || "Link inválido.", "error");
  input.value = "";
  showToast(data.queued ? `Vídeo ${data.video_id} entrou na fila de processamento.` : `Vídeo ${data.video_id} já está na fila.`, "success");
  await refreshStatus();
}

async function copyCurrentContent() {
  const text = activeTab === "skill" ? currentSkillMarkdown : currentKbMarkdown;
  if (!text) return;
  await navigator.clipboard.writeText(text);
  showToast("Conteúdo Markdown copiado!", "success");
}

function downloadCurrentMd() {
  const isSkill = activeTab === "skill" && currentSkillMarkdown;
  const text = isSkill ? currentSkillMarkdown : currentKbMarkdown;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text || ""], { type: "text/markdown;charset=utf-8" }));
  a.download = isSkill ? `${selectedSlug || "skill"}-SKILL.md` : `${selectedSlug || "conhecimento"}.md`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

async function startAgent() {
  const mins = durationSelect.value === "custom" ? Number(customMinutes.value || 0) : Number(durationSelect.value || 0);
  const { ok, data } = await api("/api/start", { duration_minutes: mins > 0 ? mins : null });
  if (!ok) return showToast(data.error || "Não foi possível iniciar o agente.", "error");
  showToast("Agente autônomo ativado!", "success");
  await refreshStatus();
}

async function stopAgent() {
  await api("/api/stop", {});
  showToast("Parada solicitada. A tarefa em andamento termina antes.", "info");
  await refreshStatus();
}

async function saveRules() {
  const topic = $("topicInput").value.trim();
  const max_minutes = Math.round(Number($("maxMinInput").value || 30));
  const guidelines = $("guidelinesInput").value.trim();
  if (!topic) return showToast("Informe um assunto válido.", "error");
  const { ok, data } = await api("/api/rules", { topic, max_minutes, guidelines });
  if (!ok) return showToast(data.error || "Não foi possível salvar as regras.", "error");
  formDirty = false;
  selectedSlug = data.active_kb_slug;
  activeTab = "formatted";
  showToast(`Regras salvas! Base ativa: knowledge/${data.active_kb_slug}.md`, "success");
  await refreshStatus();
}

function formatLogsHtml(logs) {
  return (logs || []).map((line) => {
    const colored = escapeHtml(line).replace(/^(\[\d{2}:\d{2}:\d{2}\])/, '<span class="log-time">$1</span>');
    if (/complementada|Skill criada|Conectado/.test(line)) return `<div class="log-line log-ok">${colored}</div>`;
    if (/Pulado|Erro|Aviso/.test(line)) return `<div class="log-line log-warn">${colored}</div>`;
    return `<div class="log-line">${colored}</div>`;
  }).join("");
}

function renderKbList(bases) {
  $("kbList").innerHTML = bases.map((b) => `
    <div class="kb-card ${b.slug === selectedSlug ? "selected" : ""}" data-slug="${escapeHtml(b.slug)}">
      <div class="kb-card-main">
        <div class="kb-card-title">
          <span>${escapeHtml(b.topic)}</span>
          ${b.active ? '<span class="pill-active">ATIVO</span>' : ""}
        </div>
        <div class="kb-card-meta">
          <span>knowledge/${escapeHtml(b.file)}</span>
          ${b.has_skill ? `<span class="pill-skill" data-skill-slug="${escapeHtml(b.slug)}">SKILL.md</span>` : ""}
        </div>
      </div>
      <span class="pill-count">${Number(b.videos_count) || 0} víd.</span>
    </div>`).join("");
}

async function refreshStatus() {
  try {
    const { ok, data: st } = await api("/api/status");
    if (!ok) return;
    const isActive = st.running || Boolean(st.busy_action);
    $("statusDot").className = "status-dot" + (isActive ? " running" : "");
    $("modelTag").textContent = st.model || "";
    $("phaseText").textContent = st.phase || "Parado";
    $("btnStart").style.display = st.running ? "none" : "inline-flex";
    $("btnStop").style.display = st.running ? "inline-flex" : "none";

    const timerEl = $("timerInfo");
    if (st.running) {
      timerEl.style.display = "inline-block";
      timerEl.textContent = st.remaining_seconds !== null && st.remaining_seconds !== undefined
        ? `Restante: ${formatSecs(st.remaining_seconds)} · Ativo: ${formatSecs(st.elapsed_seconds)}`
        : `Ativo há ${formatSecs(st.elapsed_seconds)}`;
    } else {
      timerEl.style.display = "none";
    }

    if (!formDirty && st.rules) {
      $("topicInput").value = st.rules.topic || "";
      $("maxMinInput").value = st.rules.max_minutes || 30;
      $("guidelinesInput").value = st.rules.guidelines || "";
    }

    const bases = st.knowledge_bases || [];
    cachedBases = bases;
    $("kbCountLabel").textContent = `${bases.length} base(s) · ${(st.skills || []).length} skill(s)`;
    if (!selectedSlug || !bases.some((b) => b.slug === selectedSlug)) selectedSlug = st.active_kb_slug;
    renderKbList(bases);

    if (selectedSlug === st.active_kb_slug) {
      currentKbMarkdown = st.active_kb_content || "";
      currentVideos = st.active_kb_videos || [];
      currentQueries = st.active_kb_queries || [];
      updateStudioView();
    }

    const logBox = $("logBox");
    const wasAtBottom = logBox.scrollHeight - logBox.clientHeight <= logBox.scrollTop + 35;
    logBox.innerHTML = formatLogsHtml(st.logs);
    if (wasAtBottom) logBox.scrollTop = logBox.scrollHeight;
  } catch (e) {
    console.error(e);
  }
}

durationSelect.addEventListener("change", () => {
  customMinutes.style.display = durationSelect.value === "custom" ? "inline-block" : "none";
});
["topicInput", "maxMinInput", "guidelinesInput"].forEach((id) => $(id).addEventListener("input", () => { formDirty = true; }));
$("singleUrlInput").addEventListener("keydown", (e) => { if (e.key === "Enter") processSingleUrl(); });
$("btnStart").addEventListener("click", startAgent);
$("btnStop").addEventListener("click", stopAgent);
$("btnSaveRules").addEventListener("click", saveRules);
$("btnProcessUrl").addEventListener("click", processSingleUrl);
$("btnCreateSkill").addEventListener("click", createSkillFromSelected);
$("btnCopy").addEventListener("click", copyCurrentContent);
$("btnDownload").addEventListener("click", downloadCurrentMd);
document.querySelectorAll("[data-tab]").forEach((btn) => btn.addEventListener("click", () => setStudioTab(btn.dataset.tab)));
$("kbList").addEventListener("click", (e) => {
  const skill = e.target.closest("[data-skill-slug]");
  if (skill) {
    selectedSlug = skill.dataset.skillSlug;
    setStudioTab("skill");
    return;
  }
  const card = e.target.closest("[data-slug]");
  if (card) selectKb(card.dataset.slug);
});

refreshStatus();
setInterval(refreshStatus, 2500);
