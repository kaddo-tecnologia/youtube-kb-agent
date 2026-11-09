"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cli = require("../bin/cli.js");

test("parseArgs separa flags do launcher das repassadas ao Python", () => {
  const o = cli.parseArgs(["--data-dir", "x", "--port", "9000", "--update", "--no-open"]);
  assert.equal(o.dataDir, "x");
  assert.equal(o.update, true);
  assert.deepEqual(o.passthrough, ["--port", "9000", "--no-open"]);
  assert.equal(cli.parseArgs(["--data-dir=y"]).dataDir, "y");
  assert.equal(cli.parseArgs(["doctor"]).doctor, true);
  assert.throws(() => cli.parseArgs(["--data-dir"]));
});

test("resolveDataDir: flag > env > home", () => {
  assert.equal(cli.resolveDataDir({ dataDir: "a" }, {}), path.resolve("a"));
  assert.equal(cli.resolveDataDir({}, { YTKB_DATA_DIR: "b" }), path.resolve("b"));
  assert.equal(cli.resolveDataDir({}, {}), path.join(os.homedir(), ".youtube-kb-agent"));
});

test("venvPython e candidatos por plataforma", () => {
  assert.equal(cli.venvPython("v", true), path.join("v", "Scripts", "python.exe"));
  assert.equal(cli.venvPython("v", false), path.join("v", "bin", "python"));
  assert.deepEqual(cli.pythonCandidates(true)[0], ["py", "-3"]);
  assert.deepEqual(cli.pythonCandidates(false)[0], ["python3"]);
});

test("ollamaUrl normaliza OLLAMA_HOST no formato do Ollama", () => {
  assert.equal(cli.ollamaUrl({}), "http://127.0.0.1:11434");
  assert.equal(cli.ollamaUrl({ OLLAMA_HOST: "0.0.0.0:11434" }), "http://127.0.0.1:11434");
  assert.equal(cli.ollamaUrl({ OLLAMA_HOST: "http://gpu-box" }), "http://gpu-box:11434");
});

test("requirementsHash muda quando o conteúdo muda", () => {
  const f = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "ytkb-")), "r.txt");
  fs.writeFileSync(f, "a==1\n");
  const h1 = cli.requirementsHash([f]);
  fs.writeFileSync(f, "a==2\n");
  assert.notEqual(h1, cli.requirementsHash([f]));
});
