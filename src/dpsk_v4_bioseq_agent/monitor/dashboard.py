"""Zero-dependency live dashboard for ONE benchmark run.

  python -m dpsk_v4_bioseq_agent.monitor.dashboard \
         --progress runs/cloning_flash/progress.json --port 8765 --title "CloningQA"
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>__TITLE__ · Live</title>
<style>
 body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1117;color:#e6e6e6}
 .wrap{max-width:1040px;margin:0 auto;padding:22px}
 h1{font-size:20px;margin:0 0 2px} .sub{color:#8b93a7;font-size:12px;margin-bottom:16px}
 .card{background:#171a23;border:1px solid #232838;border-radius:12px;padding:16px 18px;margin-bottom:16px}
 .row{display:flex;gap:12px;flex-wrap:wrap}
 .stat{flex:1;min-width:104px;background:#10131b;border:1px solid #232838;border-radius:10px;padding:9px 12px}
 .stat .v{font-size:21px;font-weight:600} .stat .k{color:#8b93a7;font-size:10.5px;text-transform:uppercase;letter-spacing:.04em}
 .bar{height:16px;background:#10131b;border-radius:8px;overflow:hidden;border:1px solid #232838;position:relative}
 .bar>.fill{height:100%;background:linear-gradient(90deg,__ACCENT__,#3b82f6);transition:width .4s}
 .bar>.pass{position:absolute;top:0;left:0;height:100%;background:linear-gradient(90deg,#16a34a,#4ade80);opacity:.85;transition:width .4s}
 table{width:100%;border-collapse:collapse;font-size:12.5px} th,td{text-align:left;padding:5px 8px;border-bottom:1px solid #232838}
 th{color:#8b93a7;font-weight:500;position:sticky;top:0;background:#171a23}
 .pill{padding:1px 8px;border-radius:20px;font-size:11px}
 .ok{background:#16351f;color:#6ee7a8}.bad{background:#3a1d1d;color:#f3a3a3}
 .tool_only{background:#1d2b3a;color:#7cc4ff}.tool_assisted_llm{background:#2c2440;color:#c4a3ff}
 .llm_only{background:#3a331d;color:#f3d77c}.ERROR{background:#3a1d1d;color:#f3a3a3}
 .scroll{max-height:360px;overflow:auto}.mut{color:#8b93a7}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px;margin-top:8px}
 .typ{background:#10131b;border:1px solid #232838;border-radius:8px;padding:5px 8px;font-size:11px}
 .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}
 .live{background:#4ade80}.done{background:#7cc4ff}
</style></head><body><div class="wrap">
 <h1><span class="dot live" id="dot"></span>__TITLE__ · Live Monitor</h1>
 <div class="sub" id="sub">connecting…</div>
 <div class="card"><div class="row">
   <div class="stat"><div class="k">Status</div><div class="v" id="status">—</div></div>
   <div class="stat"><div class="k">Done</div><div class="v" id="done">—</div></div>
   <div class="stat"><div class="k">Passed</div><div class="v" id="passed">—</div></div>
   <div class="stat"><div class="k">Conc limit</div><div class="v" id="limit">—</div></div>
   <div class="stat"><div class="k">In flight</div><div class="v" id="active">—</div></div>
   <div class="stat"><div class="k">429s</div><div class="v" id="thr">—</div></div>
   <div class="stat"><div class="k">Calls</div><div class="v" id="calls">—</div></div>
   <div class="stat"><div class="k">Elapsed</div><div class="v" id="elapsed">—</div></div>
 </div>
 <div class="bar" style="margin-top:14px"><div class="pass" id="passbar" style="width:0%"></div><div class="fill" id="fill" style="width:0%"></div></div>
 <div id="splits" style="margin-top:10px"></div>
 </div>
 <div class="card"><b>By type</b><div class="grid" id="bytype"></div></div>
 <div class="card"><b>Items</b> <span class="mut" id="ihdr"></span>
   <div class="scroll"><table><thead><tr><th>#</th><th>type</th><th>route</th><th>score</th><th>how</th><th>lat</th><th>reason</th></tr></thead>
   <tbody id="rows"></tbody></table></div></div>
</div>
<script>
const $=id=>document.getElementById(id);
const fmtT=s=>{s=Math.max(0,Math.floor(s));return Math.floor(s/60)+"m"+String(s%60).padStart(2,"0")+"s"};
const short=c=>(c||'').replace('tool_assisted_llm','tool+llm').replace('tool_only','tool').replace('llm_only','llm');
async function tick(){
 let st; try{st=await (await fetch("/api/progress?_="+Date.now())).json()}catch(e){$("sub").textContent="waiting for run…";return}
 if(!st.title){$("sub").textContent="waiting for run…";return}
 const age=(Date.now()/1000-st.updated_at);
 $("sub").textContent="updated "+age.toFixed(1)+"s ago";
 $("dot").className="dot "+(st.status==="done"?"done":"live");
 $("status").textContent=st.status; $("done").textContent=`${st.done}/${st.total}`;
 $("passed").textContent=st.passed;
 const L=st.limiter||{};
 $("limit").textContent=L.limit??"—";$("active").textContent=L.active??"—";
 $("thr").textContent=L.throttles??0;$("calls").textContent=L.calls??0;
 $("elapsed").textContent=fmtT(st.updated_at-st.started_at);
 const pct=st.total?100*st.done/st.total:0, pp=st.total?100*st.passed/st.total:0;
 $("fill").style.width=pct+"%"; $("passbar").style.width=pp+"%";
 $("splits").innerHTML=Object.entries(st.category_split||{}).map(([k,v])=>
   `<span class="pill ${k}" style="margin-right:6px">${short(k)}: ${v}</span>`).join("");
 $("bytype").innerHTML=Object.entries(st.by_type||{}).sort().map(([t,d])=>
   `<div class="typ"><b>${t}</b><br><span class="mut">${d.pass}/${d.n} pass</span></div>`).join("");
 const items=st.items||[];
 $("ihdr").textContent=`(${items.length})`;
 $("rows").innerHTML=items.slice(-60).reverse().map((x)=>{
   const ok=x.score===1.0, sc=(x.score===undefined?'':x.score);
   return `<tr><td class="mut">${x.idx??''}</td><td>${x.type||''}</td>
   <td><span class="pill ${x.category||''}">${short(x.category)}</span></td>
   <td>${sc!==''?`<span class="pill ${ok?'ok':'bad'}">${sc}</span>`:''}</td>
   <td class="mut">${x.method||x.n_tool_calls||''}</td>
   <td class="mut">${x.latency_s??''}s</td>
   <td class="mut">${(x.reason||'').slice(0,60)}</td></tr>`}).join("");
}
tick(); setInterval(tick,1200);
</script></body></html>"""


def make_handler(progress_path, title, accent):
    html = PAGE.replace("__TITLE__", title).replace("__ACCENT__", accent).encode()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/api/progress"):
                try:
                    data = open(progress_path, "rb").read()
                except FileNotFoundError:
                    data = b"{}"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html)
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--progress", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--title", default="Routed Pipeline")
    ap.add_argument("--accent", default="#22d3ee")
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.progress, args.title, args.accent))
    print(f"[{args.title}] http://localhost:{args.port}  <- {args.progress}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
