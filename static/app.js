"use strict";

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function badge(text, cls) {
  return `<span class="badge ${cls}">${text}</span>`;
}

// --- providers ---

async function loadProviders() {
  const providers = await getJSON("/api/providers");
  const tbody = document.querySelector("#providers tbody");
  tbody.innerHTML = "";
  for (const p of providers) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${p.name}</strong><div class="mono">${p.base_url}</div></td>
      <td>${p.models.join("<br>")}</td>
      <td>${p.has_key ? badge("有", "ok") : badge("无", "bad")}</td>
      <td><input type="checkbox" data-f="enabled" ${p.enabled ? "checked" : ""}></td>
      <td><input type="number" data-f="concurrency" value="${p.concurrency}" min="1"></td>
      <td><input type="number" data-f="rpm" value="${p.rpm}" min="1"></td>
      <td><input type="number" data-f="tpm" value="${p.tpm}" min="1"></td>
      <td>${p.melted ? badge("熔断中", "warn") : badge("正常", "ok")}</td>
      <td><button class="ghost" data-save="${p.name}">保存</button></td>`;
    tr.querySelector("[data-save]").addEventListener("click", () => saveProvider(p.name, tr));
    tbody.appendChild(tr);
  }
}

async function saveProvider(name, tr) {
  const get = (f) => tr.querySelector(`[data-f="${f}"]`);
  const body = {
    enabled: get("enabled").checked,
    concurrency: parseInt(get("concurrency").value, 10),
    rpm: parseInt(get("rpm").value, 10),
    tpm: parseInt(get("tpm").value, 10),
  };
  await fetch(`/api/providers/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  loadProviders();
}

// --- batches ---

async function loadBatches() {
  const batches = await getJSON("/api/batches");
  const tbody = document.querySelector("#batches tbody");
  tbody.innerHTML = "";
  for (const b of batches) {
    const tr = document.createElement("tr");
    const statusCls = b.status === "completed" ? "ok" : (b.status === "in_progress" ? "warn" : "bad");
    tr.innerHTML = `
      <td class="mono">${b.id}</td>
      <td>${badge(b.status, statusCls)}</td>
      <td>${b.request_counts.total}/${b.request_counts.completed}/${b.request_counts.failed}</td>
      <td>${new Date(b.created_at * 1000).toLocaleString()}</td>
      <td><button class="ghost" data-view="${b.id}">结果</button></td>`;
    tr.querySelector("[data-view]").addEventListener("click", async () => {
      const r = await fetch(`/v1/batches/${b.id}/content`);
      const text = await r.text();
      alert(text || "(空)");
    });
    tbody.appendChild(tr);
  }
}

async function createBatch() {
  const input = document.querySelector("#batch-input").value;
  if (!input.trim()) return;
  await fetch("/v1/batches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input }),
  });
  document.querySelector("#batch-input").value = "";
  loadBatches();
}

document.querySelector("#create-batch").addEventListener("click", createBatch);

loadProviders();
loadBatches();
setInterval(loadBatches, 3000);
