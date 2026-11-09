#!/usr/bin/env node
"use strict";
// Launcher do npx: prepara um venv Python em ~/.youtube-kb-agent/venv e roda `python -m ytkb`.
// Sem dependências npm e sem postinstall. Processos são criados com array de argumentos, nunca via shell.

const { spawn, spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const PKG_ROOT = path.resolve(__dirname, "..");
const VERSION = require(path.join(PKG_ROOT, "package.json")).version;
const IS_WIN = process.platform === "win32";

const HELP = `youtube-kb-agent ${VERSION}

Uso: npx @kaddo-tecnologia/youtube-kb-agent [opções]

  --data-dir <pasta>  Onde ficam REGRAS.md, knowledge/, skills/ e o venv (padrão: ~/.youtube-kb-agent)
  --port <n>          Porta do painel (padrão: 8765)
  --no-open           Não abrir o navegador
  --update            Reinstala dependências e atualiza o yt-dlp para a versão mais nova
  doctor              Mostra diagnóstico do ambiente (Python, yt-dlp, Ollama)
  --version, --help
`;

function parseArgs(argv) {
  const opts = { dataDir: null, update: false, help: false, version: false, doctor: false, passthrough: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--data-dir") {
      opts.dataDir = argv[++i];
      if (!opts.dataDir) throw new Error("--data-dir precisa de um caminho");
    } else if (a.startsWith("--data-dir=")) opts.dataDir = a.slice("--data-dir=".length);
    else if (a === "--update") opts.update = true;
    else if (a === "--help" || a === "-h") opts.help = true;
    else if (a === "--version" || a === "-v") opts.version = true;
    else if (a === "doctor") opts.doctor = true;
    else opts.passthrough.push(a);
  }
  return opts;
}

function resolveDataDir(opts, env = process.env) {
  return path.resolve(opts.dataDir || env.YTKB_DATA_DIR || path.join(os.homedir(), ".youtube-kb-agent"));
}

function venvPython(venvDir, win = IS_WIN) {
  return win ? path.join(venvDir, "Scripts", "python.exe") : path.join(venvDir, "bin", "python");
}

function pythonCandidates(win = IS_WIN) {
  return win ? [["py", "-3"], ["python"], ["python3"]] : [["python3"], ["python"]];
}

function ollamaUrl(env = process.env) {
  let raw = (env.OLLAMA_HOST || "").trim() || "127.0.0.1:11434";
  if (!raw.includes("://")) raw = `http://${raw}`;
  const u = new URL(raw);
  if (u.hostname === "0.0.0.0") u.hostname = "127.0.0.1";
  if (!u.port) u.port = "11434";
  return u.origin;
}

function requirementsHash(files) {
  const h = crypto.createHash("sha256");
  for (const f of files) h.update(fs.readFileSync(f));
  return h.digest("hex");
}

function run(cmd, args, extra = {}) {
  return spawnSync(cmd, args, { encoding: "utf8", ...extra });
}

function must(result, what) {
  if (result.error) throw new Error(`Falha ao ${what}: ${result.error.message}`);
  if (result.status !== 0) throw new Error(`Falha ao ${what} (código ${result.status}).`);
}

function findPython() {
  for (const [cmd, ...pre] of pythonCandidates()) {
    const r = run(cmd, [...pre, "-c", "import sys; print(sys.version_info >= (3, 11))"]);
    if (r.status === 0 && r.stdout.trim() === "True") return { cmd, pre };
  }
  return null;
}

function ensureVenv(dataDir, opts) {
  const venvDir = path.join(dataDir, "venv");
  const py = venvPython(venvDir);
  // Venv criado pela metade (ex.: Ubuntu sem python3-venv) ou cujo Python foi desinstalado: recria do zero.
  if (fs.existsSync(py) && run(py, ["-m", "pip", "--version"]).status !== 0) {
    console.log(`Ambiente Python em ${venvDir} está quebrado; recriando...`);
    fs.rmSync(venvDir, { recursive: true, force: true });
  }
  if (!fs.existsSync(py)) {
    const found = findPython();
    if (!found) throw new Error("Python 3.11+ não encontrado. Instale em https://www.python.org/downloads/ e rode de novo.");
    console.log(`Criando ambiente Python em ${venvDir} ...`);
    fs.mkdirSync(dataDir, { recursive: true });
    const created = run(found.cmd, [...found.pre, "-m", "venv", venvDir], { stdio: "inherit" });
    if (created.error || created.status !== 0) fs.rmSync(venvDir, { recursive: true, force: true });
    must(created, "criar o ambiente Python");
  }
  const reqs = [path.join(PKG_ROOT, "requirements.txt")];
  const marker = path.join(venvDir, ".ytkb-requirements");
  const hash = requirementsHash(reqs);
  const current = fs.existsSync(marker) ? fs.readFileSync(marker, "utf8").trim() : "";
  if (opts.update || current !== hash) {
    console.log("Instalando dependências Python (yt-dlp) ...");
    const args = ["-m", "pip", "install", "--disable-pip-version-check", "-q"];
    for (const r of reqs) args.push("-r", r);
    must(run(py, args, { stdio: "inherit" }), "instalar as dependências");
    if (opts.update) {
      // O YouTube muda com frequência; o yt-dlp mais novo costuma ser a correção.
      must(run(py, ["-m", "pip", "install", "-q", "--upgrade", "yt-dlp"], { stdio: "inherit" }), "atualizar o yt-dlp");
    }
    fs.writeFileSync(marker, hash);
  }
  return py;
}

async function ollamaModels() {
  try {
    const res = await fetch(`${ollamaUrl()}/api/tags`, { signal: AbortSignal.timeout(2000) });
    if (!res.ok) return null;
    return ((await res.json()).models || []).map((m) => m.name);
  } catch {
    return null;
  }
}

async function doctor(py, dataDir) {
  const pyv = run(py, ["--version"]);
  const ytv = run(py, ["-c", "import yt_dlp; print(yt_dlp.version.__version__)"]);
  const models = await ollamaModels();
  console.log(`youtube-kb-agent ${VERSION}`);
  console.log(`Node:      ${process.version}`);
  console.log(`Python:    ${(pyv.stdout || pyv.stderr || "").trim()} (${py})`);
  console.log(`yt-dlp:    ${ytv.status === 0 ? ytv.stdout.trim() : "não instalado"}`);
  console.log(`Dados:     ${dataDir}`);
  console.log(`Ollama:    ${models ? `ok em ${ollamaUrl()} - modelos: ${models.join(", ") || "nenhum (rode: ollama pull qwen3.5:9b)"}` : `sem resposta em ${ollamaUrl()}`}`);
}

async function main(argv = process.argv.slice(2)) {
  const opts = parseArgs(argv);
  if (opts.version) return console.log(VERSION);
  if (opts.help) return console.log(HELP);
  const dataDir = resolveDataDir(opts);
  const py = ensureVenv(dataDir, opts);
  if (opts.doctor) return doctor(py, dataDir);
  if (!(await ollamaModels())) {
    console.warn(`Aviso: Ollama não respondeu em ${ollamaUrl()}. O agente tenta iniciar 'ollama serve'; instale em https://ollama.com se preciso.`);
  }
  const child = spawn(py, ["-m", "ytkb", "--data-dir", dataDir, ...opts.passthrough], { cwd: PKG_ROOT, stdio: "inherit" });
  // Ctrl+C chega direto ao Python pelo terminal; o Node só espera ele encerrar com limpeza.
  process.on("SIGINT", () => {});
  process.on("SIGTERM", () => child.kill("SIGTERM"));
  child.on("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`Erro: ${err.message}`);
    process.exit(1);
  });
}

module.exports = { parseArgs, resolveDataDir, venvPython, pythonCandidates, ollamaUrl, requirementsHash };
