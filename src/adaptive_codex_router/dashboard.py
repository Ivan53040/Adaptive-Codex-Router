"""Small dependency-free local dashboard for Phase 5 JSONL results."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from uuid import uuid4
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def _run_router_job(job_id: str, prompt: str, working_directory: str, planner: str, dry_run: bool) -> None:
    project_root = Path.cwd().resolve()
    command = [
        sys.executable, "-m", "adaptive_codex_router", "--planner", planner,
        "--working-directory", working_directory,
    ]
    if dry_run:
        command.append("--dry-run")
    command.append(prompt)
    with _JOBS_LOCK:
        _JOBS[job_id]["status"] = "running"
        _JOBS[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()
    try:
        process = subprocess.Popen(
            command,
            cwd=str(project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            env=os.environ.copy(),
        )
        output, _ = process.communicate()
        with _JOBS_LOCK:
            _JOBS[job_id].update(
                status="completed" if process.returncode == 0 else "failed",
                returncode=process.returncode,
                output=output[-12000:],
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
    except OSError as exc:
        with _JOBS_LOCK:
            _JOBS[job_id].update(
                status="failed", returncode=127, output=str(exc),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )


def discover_runs(data_dir: Path) -> list[str]:
    return sorted(
        (
            path.name
            for path in data_dir.glob("phase5*.jsonl")
            if path.is_file() and not path.name.endswith(".telemetry.jsonl")
        ),
        reverse=True,
    )


def load_run(data_dir: Path, name: str | None = None) -> dict:
    runs = discover_runs(data_dir)
    selected = name if name in runs else (runs[0] if runs else None)
    rows: list[dict] = []
    if selected:
        path = (data_dir / selected).resolve()
        if not path.is_relative_to(data_dir.resolve()):
            raise ValueError("run path escaped data directory")
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    successes = sum(bool(row.get("success")) for row in rows)
    planners = Counter((row.get("planner_used") or "unknown") for row in rows)
    models = Counter((row.get("final_model") or row.get("selected_model") or "unknown") for row in rows)
    usage = [row.get("usage", {}).get("reported_tokens") for row in rows]
    usage = [value for value in usage if isinstance(value, (int, float))]
    local_input = sum(row.get("usage", {}).get("local_planning_input_tokens") or 0 for row in rows)
    local_output = sum(row.get("usage", {}).get("local_planning_output_tokens") or 0 for row in rows)
    return {
        "selected": selected,
        "runs": runs,
        "rows": rows,
        "metrics": {
            "tasks": len(rows),
            "successes": successes,
            "success_rate": successes / len(rows) if rows else 0,
            "planner_distribution": dict(planners),
            "model_distribution": dict(models),
            "average_latency_ms": sum(row.get("latency_ms", 0) for row in rows) / len(rows) if rows else 0,
            "reported_tokens_total": sum(usage) if usage else None,
            "local_planning_input_tokens": local_input or None,
            "local_planning_output_tokens": local_output or None,
        },
    }


HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Adaptive Codex Router</title>
<style>
:root{color-scheme:dark;--bg:#0c1220;--panel:#151d2e;--muted:#9aa8bd;--accent:#62d6c7;--bad:#ff8c8c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#edf3fb;font:14px system-ui,Segoe UI,sans-serif}
main{max-width:1240px;margin:0 auto;padding:28px}h1{margin:0 0 6px;font-size:28px}p{color:var(--muted)}
.toolbar{display:flex;gap:12px;align-items:center;margin:22px 0}select,button{background:var(--panel);color:#edf3fb;border:1px solid #34425c;border-radius:8px;padding:9px 12px}button{cursor:pointer}
.cards{display:grid;grid-template-columns:repeat(6,minmax(130px,1fr));gap:12px}.card,.panel{background:var(--panel);border:1px solid #273550;border-radius:12px;padding:16px}.label{color:var(--muted);font-size:12px}.value{font-size:24px;margin-top:5px;color:var(--accent)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}.panel h2{font-size:16px;margin:0 0 12px}.dist{display:flex;flex-wrap:wrap;gap:8px}.pill{background:#23314b;border-radius:999px;padding:7px 10px}.table-wrap{overflow:auto;margin-top:14px}.wide{grid-column:1/-1}table{width:100%;border-collapse:collapse;white-space:nowrap}th,td{text-align:left;padding:10px;border-bottom:1px solid #293752}th{color:var(--muted);font-weight:500}.ok{color:var(--accent)}.fail{color:var(--bad)}.small{font-size:12px;color:var(--muted)}
@media(max-width:900px){.cards{grid-template-columns:repeat(3,1fr)}.grid{grid-template-columns:1fr}}@media(max-width:560px){main{padding:16px}.cards{grid-template-columns:repeat(2,1fr)}}
</style></head><body><main>
<h1>Adaptive Codex Router</h1><p>Live view of Phase 5 planner and executor runs. Refreshes every 5 seconds.</p>
<div class="toolbar"><label for="runs">Run</label><select id="runs"></select><button id="refresh">Refresh</button><span id="updated" class="small"></span></div>
<div class="panel"><h2>Run a task</h2><form id="task-form">
<div class="toolbar"><label for="planner">Planner</label><select id="planner"><option value="qwen">Qwen (local)</option><option value="auto">Auto</option><option value="luna">Luna</option><option value="none">None</option></select>
<label for="workdir">Repository</label><input id="workdir" size="48" value="." placeholder="C:\\path\\to\\git-repository"><button id="browse" type="button">Browse…</button></div>
<textarea id="prompt" rows="4" style="width:100%;background:#0c1220;color:#edf3fb;border:1px solid #34425c;border-radius:8px;padding:10px" placeholder="Describe the coding task..."></textarea>
<div class="toolbar"><label><input id="dry-run" type="checkbox"> Dry run (no file changes)</label><button type="submit">Send to router</button><span id="submit-status" class="small"></span></div>
</form></div>
<section id="cards" class="cards"></section><section class="grid">
<div class="panel"><h2>Planner distribution</h2><div id="planners" class="dist"></div></div>
<div class="panel"><h2>Execution model distribution</h2><div id="models" class="dist"></div></div>
<div class="panel wide"><h2>Recent runs</h2><div class="table-wrap"><table><thead><tr><th>Task</th><th>Scenario</th><th>Planner</th><th>Model</th><th>Status</th><th>Attempts</th><th>Latency</th><th>Codex tokens</th><th>Stop reason</th></tr></thead><tbody id="rows"></tbody></table></div></div>
<div class="panel wide"><h2>Dashboard jobs</h2><div id="jobs" class="small">No dashboard jobs.</div></div>
</section></main><script>
const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let selected='';
async function load(){const q=selected?('?run='+encodeURIComponent(selected)):'', d=await fetch('/api/summary'+q).then(r=>r.json());
 $('runs').innerHTML=d.runs.map(x=>`<option ${x===d.selected?'selected':''}>${esc(x)}</option>`).join(''); selected=d.selected||'';
 const m=d.metrics, cards=[['Tasks',m.tasks],['Successes',m.successes],['Success rate',(m.success_rate*100).toFixed(1)+'%'],['Avg latency',(m.average_latency_ms/1000).toFixed(1)+'s'],['Codex tokens',m.reported_tokens_total==null?'—':m.reported_tokens_total.toLocaleString()],['Qwen local tokens',((m.local_planning_input_tokens||0)+(m.local_planning_output_tokens||0)||null)?.toLocaleString()||'—']];
 $('cards').innerHTML=cards.map(([a,b])=>`<div class="card"><div class="label">${a}</div><div class="value">${b}</div></div>`).join('');
 const renderDist=o=>Object.entries(o).map(([k,v])=>`<span class="pill">${esc(k)}: ${v}</span>`).join('')||'<span class="small">No data</span>';
 $('planners').innerHTML=renderDist(m.planner_distribution); $('models').innerHTML=renderDist(m.model_distribution);
 $('rows').innerHTML=d.rows.slice().reverse().map(r=>{const ok=r.success; const u=r.usage?.reported_tokens; return `<tr><td>${esc(r.task_id)}</td><td>${esc(r.scenario)}</td><td>${esc(r.planner_used)}</td><td>${esc(r.final_model||r.selected_model)}</td><td class="${ok?'ok':'fail'}">${ok?'success':'failed'}</td><td>${r.attempts??''}</td><td>${((r.latency_ms||0)/1000).toFixed(1)}s</td><td>${u==null?'—':u.toLocaleString()}</td><td>${esc(r.stop_reason)}</td></tr>`}).join('')||'<tr><td colspan="9" class="small">No Phase 5 JSONL runs found.</td></tr>';
 const jobs=await fetch('/api/jobs').then(r=>r.json()); $('jobs').innerHTML=jobs.length?jobs.slice().reverse().map(j=>`<div class="pill" style="margin:4px 0"><b>${esc(j.id)}</b> · ${esc(j.status)} · planner=${esc(j.planner)} · ${esc(j.working_directory)}${j.returncode==null?'':` · exit=${j.returncode}`}<br><span class="small">${esc(j.output||'')}</span></div>`).join(''):'No dashboard jobs.';
 $('updated').textContent='Updated '+new Date().toLocaleTimeString(); }
$('runs').onchange=e=>{selected=e.target.value;load()}; $('refresh').onclick=load; load(); setInterval(load,5000);
$('task-form').onsubmit=async e=>{e.preventDefault(); const prompt=$('prompt').value.trim(), working_directory=$('workdir').value.trim()||'.'; if(!prompt){$('submit-status').textContent='Enter a prompt first.';return} $('submit-status').textContent='Starting…'; const response=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt,working_directory,planner:$('planner').value,dry_run:$('dry-run').checked})}); const result=await response.json(); $('submit-status').textContent=response.ok?`Started job ${result.id}`:(result.error||'Could not start'); if(response.ok){$('prompt').value='';load()}};
$('browse').onclick=async()=>{ $('submit-status').textContent='Choose a repository folder…'; const response=await fetch('/api/pick-directory',{method:'POST'}); const result=await response.json(); $('submit-status').textContent=response.ok?(result.path?'Selected repository folder.':'No folder selected.'):(result.error||'Folder picker failed'); if(response.ok&&result.path)$('workdir').value=result.path; };
</script></body></html>"""


def build_handler(data_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, value: object) -> None:
            payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/summary":
                name = parse_qs(parsed.query).get("run", [None])[0]
                self._json(200, load_run(data_dir, name))
                return
            if parsed.path == "/api/jobs":
                with _JOBS_LOCK:
                    jobs = [dict(job) for job in _JOBS.values()]
                self._json(200, jobs)
                return
            payload = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path == "/api/pick-directory":
                try:
                    import tkinter as tk
                    from tkinter import filedialog

                    root = tk.Tk()
                    root.withdraw()
                    root.attributes("-topmost", True)
                    selected = filedialog.askdirectory(title="Select repository folder")
                    root.destroy()
                    self._json(200, {"path": selected or None})
                except (ImportError, OSError, RuntimeError) as exc:
                    self._json(500, {"error": f"native folder picker unavailable: {exc}"})
                return
            if urlparse(self.path).path != "/api/run":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                value = json.loads(self.rfile.read(length).decode("utf-8"))
                prompt = value.get("prompt", "").strip()
                working_directory = str(value.get("working_directory", ".")).strip() or "."
                planner = str(value.get("planner", "qwen"))
                dry_run = bool(value.get("dry_run", False))
                if not prompt or len(prompt) > 20000:
                    raise ValueError("prompt must contain 1-20000 characters")
                if planner not in {"qwen", "luna", "auto", "none"}:
                    raise ValueError("unsupported planner")
                target = Path(working_directory).expanduser().resolve()
                if not target.is_dir():
                    raise ValueError(f"working directory does not exist: {target}")
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})
                return
            job_id = uuid4().hex[:10]
            with _JOBS_LOCK:
                _JOBS[job_id] = {
                    "id": job_id, "status": "queued", "planner": planner,
                    "working_directory": str(target), "prompt_preview": prompt[:120],
                    "dry_run": dry_run, "output": "",
                }
            threading.Thread(
                target=_run_router_job,
                args=(job_id, prompt, str(target), planner, dry_run),
                daemon=True,
            ).start()
            self._json(202, {"id": job_id, "status": "queued"})

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the local Phase 5 dashboard")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), build_handler(data_dir))
    print(f"Dashboard: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
