"use strict";

const COLORS = { Test: "#8C1C13", ODI: "#1D3557", T20: "#0B6E4F", Other: "#8D99AE" };
const GREEN = "#0B6E4F";
const NAVY = "#1D3557";
const charts = {};
const $ = (id) => document.getElementById(id);

function currentParams(extra = {}) {
  const formats = [...document.querySelectorAll("#fmt-box input:checked")].map((x) => x.value).join(",");
  const p = new URLSearchParams({
    formats, year_from: $("year-from").value, year_to: $("year-to").value, gender: $("gender").value,
  });
  Object.entries(extra).forEach(([k, v]) => p.set(k, v));
  return p;
}

async function getJSON(path, extra = {}, withFilters = true) {
  const res = await fetch(withFilters ? `${path}?${currentParams(extra)}` : path);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

function showBanner(message) {
  $("banner").textContent = message;
  $("banner").hidden = !message;
}

function draw(id, config) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart($(id), config);
}

function barChart(id, labels, values, colors, horizontal = false) {
  draw(id, {
    type: "bar",
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderRadius: 4 }] },
    options: { indexAxis: horizontal ? "y" : "x", maintainAspectRatio: false, plugins: { legend: { display: false } } },
  });
}

function lineChart(rows) {
  const years = [...new Set(rows.map((r) => r.year))];
  const formats = [...new Set(rows.map((r) => r.format))];
  const datasets = formats.map((f) => ({
    label: f, borderColor: COLORS[f], backgroundColor: COLORS[f], tension: 0.25,
    data: years.map((y) => (rows.find((r) => r.year === y && r.format === f) || { value: 0 }).value),
  }));
  draw("c-years", { type: "line", data: { labels: years, datasets }, options: { maintainAspectRatio: false } });
}

function fillTable(bodyId, rows, columns) {
  const body = $(bodyId);
  body.replaceChildren();
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((c) => {
      const td = document.createElement("td");
      td.textContent = row[c] ?? "-";       
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });
}

const fmtColors = (rows) => rows.map((r) => COLORS[r.label] || GREEN);

async function refresh() {
  try {
    showBanner("");
    const [sum, formats, years, runrate, bat, teams, venues, matches] = await Promise.all([
      getJSON("/api/summary"), getJSON("/api/formats"), getJSON("/api/years"), getJSON("/api/runrate"),
      getJSON("/api/batting_first"), getJSON("/api/teams", { min: $("min-matches").value }),
      getJSON("/api/venues"), getJSON("/api/matches", { q: $("search").value }),
    ]);

    $("kpi-matches").textContent = sum.matches.toLocaleString();
    $("kpi-innings").textContent = sum.innings.toLocaleString();
    $("kpi-teams").textContent = sum.teams;
    $("kpi-runs").textContent = sum.avg_runs ?? "-";

    barChart("c-formats", formats.map((r) => r.label), formats.map((r) => r.value), fmtColors(formats));
    lineChart(years);
    barChart("c-runrate", runrate.map((r) => r.label), runrate.map((r) => r.value), fmtColors(runrate));
    barChart("c-batfirst", bat.map((r) => r.label), bat.map((r) => r.value), fmtColors(bat));
    barChart("c-teams", teams.map((r) => `${r.team} (${r.played})`), teams.map((r) => r.win_pct), GREEN, true);
    barChart("c-venues", venues.map((r) => r.label), venues.map((r) => r.value), NAVY, true);

    $("match-count").textContent = `(showing ${matches.rows.length} of ${matches.total})`;
    fillTable("matches-body", matches.rows, ["match_date", "match_name", "format", "venue", "winner", "status"]);
  } catch (err) {
    showBanner(err.message);
  }
}

async function loadQuality() {
  const q = await getJSON("/api/quality", {}, false);
  const items = [
    ["Records extracted", q.report.records_extracted], ["Rejected by Pydantic", q.report.rejected_by_pydantic],
    ["Duplicates removed", q.report.duplicates_removed], ["Matches loaded", q.report.clean_matches_loaded],
  ];
  $("dq-cards").replaceChildren(...items.map(([label, value]) => {
    const card = document.createElement("div");
    card.className = "kpi";
    const small = document.createElement("span");
    small.textContent = label;
    const big = document.createElement("strong");
    big.textContent = value ?? "-";
    card.append(small, big);
    return card;
  }));
  fillTable("runs-body", q.runs, ["run_id", "finished_at", "source", "extracted", "rejected", "loaded_matches", "status"]);
}

async function init() {
  try {
    const f = await getJSON("/api/filters", {}, false);
    if (f.year_min === null) {
      showBanner("The database has no matches yet. Run: python main.py etl");
      return;
    }
    $("fmt-box").replaceChildren(...f.formats.map((fmt) => {
      const label = document.createElement("label");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.value = fmt;
      box.checked = true;
      label.append(box, ` ${fmt}`);
      return label;
    }));
    ["year-from", "year-to"].forEach((id) => { $(id).min = f.year_min; $(id).max = f.year_max; });
    $("year-from").value = f.year_min;
    $("year-to").value = f.year_max;

    document.querySelectorAll("#filters input, #filters select, #min-matches").forEach((el) =>
      el.addEventListener("change", refresh));
    let timer;
    $("search").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(refresh, 300); });

    await loadQuality();
    await refresh();
  } catch (err) {
    showBanner(err.message);
  }
}

init();