"""Generate a self-contained offender chart you can re-score without re-running.

The offender score is a *hypothesis about what matters*, not a measurement:

    score = z(vgprs) + z(-max_waves) + z(code_size) + 3·z(spilled_vgprs)

Those four terms and that 3x are a judgement call that has never been calibrated
against measured FPS. Baking them into a static PNG would freeze an uncalibrated
guess into every figure. So the page ships the **raw rows** and recomputes
z-scores in the browser: move a weight, add `vopd` or `s_delay_alu` as a term,
regroup, and the ranking updates with no replay. A replay costs ~70 s per driver
and the data does not change — only the question does.

Everything is inlined (no CDN, no fetch) so the file works from `file://`, from a
USB stick, and in five years when the CSV is gone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from core import util
from core.errors import TccError
from core.session import Session

from . import stats as stats_mod

#: Terms in the default score, and the direction each is bad in. Sign -1 means
#: "less is worse" (occupancy): the z-score is negated so every term points the
#: same way -- higher contribution = worse shader.
DEFAULT_TERMS: dict[str, tuple[float, int]] = {
    "vgprs": (1.0, +1),
    "max_waves": (1.0, -1),
    "code_size": (1.0, +1),
    "spilled_vgprs": (3.0, +1),
}

#: Never offered as scoring terms: identifiers, or values that would make the
#: score circular (score itself) or meaningless (a hash as a magnitude).
_NON_METRIC = {"pipeline_hash", "driver_pipeline_hash", "stage", "driver",
               "provenance", "pipeline_type", "extra", "score"}


class ChartError(TccError):
    pass


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns
            if c not in _NON_METRIC and pd.api.types.is_numeric_dtype(df[c])]


def build_payload(df: pd.DataFrame, max_rows: int = 20000) -> dict:
    """Columnar JSON: one array per column, not one object per row. At 17,736
    rows the row-object form is roughly 6x larger for identical content."""
    if df.empty:
        raise ChartError("stats table is empty")
    if len(df) > max_rows:
        # Keep the worst rows by the default score rather than an arbitrary
        # head(): truncation must not silently drop the offenders.
        from . import mine as mine_mod

        df = df.assign(_s=mine_mod.score(df)).nlargest(max_rows, "_s").drop(columns="_s")

    metrics = _numeric_columns(df)
    cols: dict[str, list] = {}
    for c in metrics:
        s = pd.to_numeric(df[c], errors="coerce").fillna(0)
        cols[c] = [int(v) if float(v).is_integer() else round(float(v), 4) for v in s]

    return {
        "n": int(len(df)),
        "hash": [str(h) for h in df.get("pipeline_hash", pd.Series([""] * len(df)))],
        "stage": [str(s) for s in df.get("stage", pd.Series(["?"] * len(df)))],
        "driver": [str(s) for s in df.get("driver", pd.Series(["?"] * len(df)))],
        "provenance": [str(s) for s in df.get("provenance", pd.Series(["unknown"] * len(df)))],
        "metrics": metrics,
        "cols": cols,
        "defaults": {k: {"weight": w, "sign": sgn} for k, (w, sgn) in DEFAULT_TERMS.items()
                     if k in metrics},
    }


def render(payload: dict, title: str) -> str:
    return _TEMPLATE.replace("__TITLE__", title).replace("__DATA__", json.dumps(payload, separators=(",", ":")))


def generate(session: Session, driver: str | None = None, out_path: Path | None = None) -> Path:
    df = stats_mod.load_session_stats(session, driver=driver)
    payload = build_payload(df)
    label = driver or "all-drivers"
    out = Path(out_path) if out_path else session.subdir("reports") / f"offenders.{label}.html"
    util.ensure_dir(out.parent)
    out.write_text(render(payload, f"{session.game} · {session.session_id} · {label}"),
                   encoding="utf-8")
    session.record_artifact(out, kind="offender_chart", producer="tcc chart", confidence="exact")
    return out


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Offenders — __TITLE__</title>
<style>
*{box-sizing:border-box}
.viz-root{
  color-scheme:light;
  --surface-1:#fcfcfb; --surface-2:#f4f3f0; --line:#dcdad4;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --text-muted:#78766f;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100;
  --s5:#e87ba4; --s6:#008300; --s7:#4a3aa7; --s8:#e34948;
  --neg:#8d8b84;
}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{
  color-scheme:dark;
  --surface-1:#1a1a19; --surface-2:#232322; --line:#3a3a37;
  --text-primary:#fff; --text-secondary:#c3c2b7; --text-muted:#96948b;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
  --s5:#d55181; --s6:#008300; --s7:#9085e9; --s8:#e66767;
  --neg:#6e6c66;
}}
:root[data-theme="dark"] .viz-root{
  color-scheme:dark;
  --surface-1:#1a1a19; --surface-2:#232322; --line:#3a3a37;
  --text-primary:#fff; --text-secondary:#c3c2b7; --text-muted:#96948b;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
  --s5:#d55181; --s6:#008300; --s7:#9085e9; --s8:#e66767;
  --neg:#6e6c66;
}
body{margin:0;background:var(--surface-1);color:var(--text-primary);
  font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1200px;margin:0 auto;padding:24px 20px 64px}
h1{font-size:20px;margin:0 0 2px;letter-spacing:-.01em}
.sub{color:var(--text-secondary);font-size:13px;margin:0 0 20px}
.panel{background:var(--surface-2);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:16px}
.controls{display:flex;flex-wrap:wrap;gap:18px;align-items:flex-start}
.ctl{display:flex;flex-direction:column;gap:5px;min-width:150px}
.ctl label{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted)}
select,input[type=number]{background:var(--surface-1);color:var(--text-primary);
  border:1px solid var(--line);border-radius:6px;padding:5px 7px;font:inherit;font-size:13px}
.terms{display:flex;flex-direction:column;gap:7px;margin-top:4px}
.term{display:grid;grid-template-columns:16px 1fr 118px 52px 26px;gap:9px;align-items:center}
.sw{width:11px;height:11px;border-radius:3px}
.term code{font-size:12.5px;color:var(--text-primary)}
input[type=range]{width:100%;accent-color:var(--s1)}
.wv{font-variant-numeric:tabular-nums;font-size:12.5px;color:var(--text-secondary);text-align:right}
.rm{background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:15px;line-height:1;padding:0}
.rm:hover{color:var(--s8)}
.addrow{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}
button.add{background:var(--s1);color:#fff;border:none;border-radius:6px;padding:6px 12px;font:inherit;font-size:12.5px;cursor:pointer}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin:2px 0 12px;font-size:12.5px;color:var(--text-secondary)}
.legend span{display:flex;align-items:center;gap:6px}
.chart{overflow-x:auto}
svg{display:block;min-width:640px}
.rowlab{font-size:11.5px;fill:var(--text-secondary);font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.val{font-size:11.5px;fill:var(--text-primary);font-variant-numeric:tabular-nums}
.ax{font-size:11px;fill:var(--text-muted)}
.grid{stroke:var(--line);stroke-width:1}
.zero{stroke:var(--text-muted);stroke-width:1.5}
table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:5px 9px;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
th{color:var(--text-muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.05em}
td code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.tblwrap{max-height:420px;overflow:auto}
details{margin-top:16px}
summary{cursor:pointer;color:var(--text-secondary);font-size:13px;padding:4px 0}
.note{font-size:12.5px;color:var(--text-secondary);line-height:1.65}
.note strong{color:var(--text-primary)}
.warn{border-left:3px solid var(--s4);padding-left:12px;margin:10px 0}
#tip{position:fixed;pointer-events:none;background:var(--surface-1);border:1px solid var(--line);
  border-radius:7px;padding:8px 10px;font-size:12.5px;box-shadow:0 4px 14px rgba(0,0,0,.18);
  opacity:0;transition:opacity .1s;z-index:9;max-width:290px}
#tip b{font-family:ui-monospace,Menlo,monospace}
.kv{display:flex;justify-content:space-between;gap:14px;color:var(--text-secondary)}
.kv span:last-child{color:var(--text-primary);font-variant-numeric:tabular-nums}
</style></head>
<body class="viz-root"><div class="wrap">
<h1>Offender ranking</h1>
<p class="sub">__TITLE__</p>

<div class="panel">
  <div class="controls">
    <div class="ctl"><label for="grp">z-score within</label>
      <select id="grp">
        <option value="driver,stage" selected>driver + stage</option>
        <option value="stage">stage</option>
        <option value="driver">driver</option>
        <option value="">whole table</option>
      </select></div>
    <div class="ctl"><label for="drv">driver</label><select id="drv"></select></div>
    <div class="ctl"><label for="prov">provenance</label><select id="prov"></select></div>
    <div class="ctl"><label for="topn">show top</label>
      <input id="topn" type="number" min="5" max="60" step="5" value="20"></div>
  </div>
  <div class="terms" id="terms"></div>
  <div class="addrow">
    <select id="newterm"></select>
    <button class="add" id="addbtn">add term</button>
    <button class="add" id="resetbtn" style="background:var(--surface-1);color:var(--text-secondary);border:1px solid var(--line)">reset</button>
  </div>
</div>

<div class="legend" id="legend"></div>
<div class="chart panel"><svg id="svg"></svg></div>

<details open><summary>Table view — the same ranking as numbers</summary>
  <div class="tblwrap panel"><table id="tbl"></table></div></details>

<details open><summary>Methodology &amp; what this does not tell you</summary>
<div class="panel note">
<p><strong>score = Σ weight<sub>i</sub> · z(metric<sub>i</sub>)</strong>, z computed
<strong>within each group</strong> (default: driver + stage). Grouping by stage is
because a compute shader's code-size distribution says nothing about a fragment
shader's. Grouping by driver too is because pooling stock and custom would z-score
every shader against a population containing its own duplicate.</p>
<p><code>max_waves</code> is occupancy — <strong>higher is better</strong> — so its
z-score is negated, making every bar segment point the same way: right = worse.</p>
<div class="warn">
<p><strong>The default weights are an uncalibrated guess.</strong> The 3× on spills
encodes a belief that a spill is qualitatively worse than high register pressure —
the compiler ran out and went to memory. Nothing has checked whether high-scoring
shaders correlate with anything measured. <strong>This ranks candidates for
inspection. It is not a severity measure and must not be reported as one.</strong>
That is exactly why the weights are sliders: the number is an argument, so you
should be able to change it and see whether your conclusion survives.</p>
</div>
<p>A z-score needs spread. Where a group has zero variance in a metric, that term
contributes 0 rather than dividing by zero — so a metric that is constant across
every shader can be given any weight and will never move the ranking.</p>
</div></details>
</div>
<div id="tip"></div>

<script>
const DATA = __DATA__;
const PAL = ["--s1","--s2","--s3","--s4","--s5","--s6","--s7","--s8"];
const cssv = n => getComputedStyle(document.body).getPropertyValue(n).trim();
let terms = [];

const el = id => document.getElementById(id);
const uniq = a => [...new Set(a)].sort();

function resetTerms(){
  terms = Object.entries(DATA.defaults).map(([k,v]) => ({m:k, w:v.weight, sign:v.sign}));
  if(!terms.length) terms = DATA.metrics.slice(0,3).map(m=>({m,w:1,sign:1}));
}

function initSelects(){
  const d = el("drv"); d.innerHTML = '<option value="">all</option>' +
    uniq(DATA.driver).map(v=>`<option>${v}</option>`).join("");
  const p = el("prov"); p.innerHTML = '<option value="">all</option>' +
    uniq(DATA.provenance).map(v=>`<option>${v}</option>`).join("");
}
function refreshNewTerm(){
  const used = new Set(terms.map(t=>t.m));
  el("newterm").innerHTML = DATA.metrics.filter(m=>!used.has(m))
    .map(m=>`<option>${m}</option>`).join("") || '<option disabled>all metrics used</option>';
}
function renderTerms(){
  el("terms").innerHTML = terms.map((t,i)=>`
    <div class="term">
      <span class="sw" style="background:var(${PAL[i%8]})"></span>
      <code>${t.m}${t.sign<0?' <span style="color:var(--text-muted)">(higher is better → negated)</span>':''}</code>
      <input type="range" min="-4" max="6" step="0.25" value="${t.w}" data-i="${i}">
      <span class="wv">${t.w.toFixed(2)}</span>
      <button class="rm" data-rm="${i}" title="remove">×</button>
    </div>`).join("");
  el("terms").querySelectorAll('input[type=range]').forEach(r=>{
    r.oninput = e => { terms[+e.target.dataset.i].w = +e.target.value;
      e.target.nextElementSibling.textContent = (+e.target.value).toFixed(2); draw(); };
  });
  el("terms").querySelectorAll('[data-rm]').forEach(b=>{
    b.onclick = e => { terms.splice(+e.target.dataset.rm,1); renderTerms(); refreshNewTerm(); draw(); };
  });
  el("legend").innerHTML = terms.map((t,i)=>
    `<span><span class="sw" style="background:var(${PAL[i%8]})"></span>${t.m}</span>`).join("")
    + `<span><span class="sw" style="background:var(--neg)"></span>pulls score down</span>`;
}

// z within group; zero-variance groups contribute 0 rather than dividing by 0.
function zscores(idx, metric, keyOf){
  const groups = new Map();
  for(const i of idx){ const k = keyOf(i); (groups.get(k) || groups.set(k,[]).get(k)).push(i); }
  const out = new Float64Array(DATA.n);
  const col = DATA.cols[metric];
  for(const g of groups.values()){
    let s=0; for(const i of g) s += col[i];
    const mean = s/g.length;
    let v=0; for(const i of g) v += (col[i]-mean)**2;
    const sd = Math.sqrt(v/g.length);
    if(!sd){ for(const i of g) out[i]=0; continue; }
    for(const i of g) out[i] = (col[i]-mean)/sd;
  }
  return out;
}

function compute(){
  const drv = el("drv").value, prov = el("prov").value;
  const idx = [];
  for(let i=0;i<DATA.n;i++){
    if(drv && DATA.driver[i]!==drv) continue;
    if(prov && DATA.provenance[i]!==prov) continue;
    idx.push(i);
  }
  const gk = el("grp").value.split(",").filter(Boolean);
  const keyOf = i => gk.map(k=>DATA[k][i]).join("|");
  const parts = terms.map(t => {
    const z = zscores(idx, t.m, keyOf);
    return {t, z};
  });
  const rows = idx.map(i=>{
    const contrib = parts.map(p => p.t.sign * p.t.w * p.z[i]);
    return {i, contrib, score: contrib.reduce((a,b)=>a+b,0)};
  });
  rows.sort((a,b)=>b.score-a.score);
  return rows;
}

function draw(){
  const rows = compute();
  const N = Math.min(+el("topn").value, rows.length);
  const top = rows.slice(0,N);
  const svg = el("svg");
  const W=1100, rowH=26, padL=290, padR=70, padT=34, H=padT+N*rowH+30;
  // Diverging: a term can pull a score DOWN (a shader with unusually low VGPR
  // pressure), so segments extend both ways from a zero line.
  let maxPos=0, maxNeg=0;
  for(const r of top){
    let p=0,n=0; for(const c of r.contrib){ c>=0?p+=c:n+=c; }
    maxPos=Math.max(maxPos,p); maxNeg=Math.min(maxNeg,n);
  }
  const span = Math.max(maxPos - maxNeg, 0.001);
  const plotW = W-padL-padR;
  const x = v => padL + ((v-maxNeg)/span)*plotW;

  let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="100%" height="${H}">`;
  const ticks=5;
  for(let k=0;k<=ticks;k++){
    const v = maxNeg + (span*k/ticks), px = x(v);
    s += `<line class="grid" x1="${px}" y1="${padT-8}" x2="${px}" y2="${H-26}"/>`;
    s += `<text class="ax" x="${px}" y="${H-10}" text-anchor="middle">${v.toFixed(1)}</text>`;
  }
  s += `<line class="zero" x1="${x(0)}" y1="${padT-8}" x2="${x(0)}" y2="${H-26}"/>`;
  s += `<text class="ax" x="${padL}" y="${padT-16}">← score contribution (right = worse) →</text>`;

  top.forEach((r,k)=>{
    const y = padT + k*rowH, h = rowH-9;
    const i = r.i;
    s += `<text class="rowlab" x="8" y="${y+h-2}">${DATA.hash[i].slice(0,16)}</text>`;
    s += `<text class="rowlab" x="180" y="${y+h-2}" fill="var(--text-muted)">${DATA.stage[i].slice(0,12)}</text>`;
    let cur=0;
    // positives right of zero, negatives left — 2px surface gap between fills
    r.contrib.forEach((c,ti)=>{ if(c<=0) return;
      const x0=x(cur), x1=x(cur+c);
      if(x1-x0>0.6) s += `<rect x="${x0}" y="${y}" width="${Math.max(x1-x0-2,0.6)}" height="${h}" rx="3" fill="var(${PAL[ti%8]})"
        data-i="${i}" data-t="${ti}" data-c="${c.toFixed(3)}"/>`;
      cur+=c; });
    let curn=0;
    r.contrib.forEach((c,ti)=>{ if(c>=0) return;
      const x1=x(curn), x0=x(curn+c);
      if(x1-x0>0.6) s += `<rect x="${x0}" y="${y}" width="${Math.max(x1-x0-2,0.6)}" height="${h}" rx="3" fill="var(--neg)"
        opacity="${0.45+0.12*(ti%4)}" data-i="${i}" data-t="${ti}" data-c="${c.toFixed(3)}"/>`;
      curn+=c; });
    s += `<text class="val" x="${W-padR+10}" y="${y+h-2}">${r.score.toFixed(2)}</text>`;
  });
  s += `</svg>`;
  svg.outerHTML = s;
  el("svg") || document.querySelector(".chart svg").id="svg";
  wireHover();
  renderTable(top);
}

function wireHover(){
  const tip = el("tip");
  document.querySelectorAll(".chart rect").forEach(r=>{
    r.style.cursor="crosshair";
    r.onmousemove = e => {
      const i=+r.dataset.i, ti=+r.dataset.t, t=terms[ti];
      tip.innerHTML = `<b>${DATA.hash[i]}</b><br>`+
        `<div class="kv"><span>stage</span><span>${DATA.stage[i]}</span></div>`+
        `<div class="kv"><span>driver</span><span>${DATA.driver[i]}</span></div>`+
        `<div class="kv"><span>provenance</span><span>${DATA.provenance[i]}</span></div>`+
        `<hr style="border:none;border-top:1px solid var(--line);margin:6px 0">`+
        `<div class="kv"><span>${t.m}</span><span>${DATA.cols[t.m][i]}</span></div>`+
        `<div class="kv"><span>contribution</span><span>${(+r.dataset.c).toFixed(3)}</span></div>`+
        `<div class="kv"><span>weight</span><span>${t.w.toFixed(2)}${t.sign<0?" (negated)":""}</span></div>`;
      tip.style.opacity=1;
      tip.style.left = Math.min(e.clientX+14, innerWidth-300)+"px";
      tip.style.top = Math.min(e.clientY+14, innerHeight-170)+"px";
    };
    r.onmouseleave = () => tip.style.opacity=0;
  });
}

function renderTable(top){
  const cols = terms.map(t=>t.m);
  let h = `<thead><tr><th>pipeline hash</th><th>stage</th><th>score</th>`+
    cols.map(c=>`<th>${c}</th>`).join("")+`</tr></thead><tbody>`;
  for(const r of top){
    const i=r.i;
    h += `<tr><td><code>${DATA.hash[i]}</code></td><td>${DATA.stage[i]}</td>`+
      `<td>${r.score.toFixed(2)}</td>`+
      cols.map(c=>`<td>${DATA.cols[c][i]}</td>`).join("")+`</tr>`;
  }
  el("tbl").innerHTML = h+`</tbody>`;
}

el("addbtn").onclick = () => {
  const m = el("newterm").value;
  if(!m || terms.some(t=>t.m===m)) return;
  terms.push({m, w:1, sign:1}); renderTerms(); refreshNewTerm(); draw();
};
el("resetbtn").onclick = () => { resetTerms(); renderTerms(); refreshNewTerm(); draw(); };
["grp","drv","prov","topn"].forEach(id => el(id).onchange = draw);

resetTerms(); initSelects(); renderTerms(); refreshNewTerm(); draw();
</script></body></html>
"""
