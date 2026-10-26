"""TSE falso: reproduz a noite do 2º turno de 2022 no formato da divulgação de 2026, em relógio acelerado.

Uso: python live/fake_tse.py --pq data_tse/parquet --ano 2022 --speed 20 [--start 0] [--port 8787]
Serve: /comum/config/ele-c.json, cs.json por UF, EA20 por município, por UF e do Brasil (só os campos que o coletor usa).
"""
import argparse, json, time, hashlib, re, datetime as dt
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import numpy as np, pandas as pd

ap = argparse.ArgumentParser(); ap.add_argument("--pq", default="data_tse/parquet"); ap.add_argument("--ano", default="2022")
ap.add_argument("--speed", type=float, default=20); ap.add_argument("--start", type=float, default=0); ap.add_argument("--port", type=int, default=8787)
ap.add_argument("--pleito", type=int, default=9999); ap.add_argument("--eleicao", type=int, default=9998)
a = ap.parse_args()
KEY = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]
v = pd.read_parquet(f"{a.pq}/votacao_{a.ano}_t2.parquet")
w = v.pivot_table(index=KEY, columns="NR_VOTAVEL", values="QT_VOTOS", aggfunc="sum", fill_value=0).reset_index()
d = pd.read_parquet(f"{a.pq}/detalhe_{a.ano}_t2.parquet").merge(w, on=KEY, how="left").fillna(0)
dia = d.DT_PRIM_TOT_PARCIAL_HOR_TSE.min().normalize() + pd.Timedelta(hours=17)
d["seg"] = (d.DT_PRIM_TOT_PARCIAL_HOR_TSE - dia).dt.total_seconds()
d = d.sort_values(KEY).reset_index(drop=True)
UF = d.SG_UF.str.lower().values; MUN = d.CD_MUNICIPIO.values; ZON = d.NR_ZONA.values; SEC = d.NR_SECAO.values
SEG = d.seg.values; PT = d[13].values; PL = d[22].values; VB = d[95].values; VN = d[96].values
APT = d.QT_APTOS.values; COMP = d.QT_COMPARECIMENTO.values
por_uf = {u: np.where(UF == u)[0] for u in np.unique(UF)}
por_mun = {}
for i, (u, m) in enumerate(zip(UF, MUN)): por_mun.setdefault((u, int(m)), []).append(i)
por_mun = {k: np.array(ix) for k, ix in por_mun.items()}
T0 = time.time()
def agora(): return a.start * 60 + (time.time() - T0) * a.speed
def relogio(seg):
    t = dia + pd.Timedelta(seconds=float(seg)); return t.strftime("%d/%m/%Y"), t.strftime("%H:%M:%S")
def ea20(ix, tp, cd):
    ok = ix[SEG[ix] <= agora()]; n = agora(); dg, hg = relogio(n)
    vv = int(PT[ok].sum() + PL[ok].sum())
    cand = lambda nr, nm, votos: dict(n=str(nr), nm=nm, vap=str(int(votos)), pvap=f"{100 * votos / max(vv, 1):.2f}".replace(".", ","))
    return dict(ele=str(a.eleicao), t="2", tpabr=tp, cdabr=cd, dg=dg, hg=hg, dt=dg, ht=hg,
                s=dict(ts=str(len(ix)), st=str(len(ok)), pst=f"{100 * len(ok) / len(ix):.2f}".replace(".", ",")),
                e=dict(te=str(int(APT[ix].sum())), est=str(int(APT[ok].sum())), c=str(int(COMP[ok].sum())), a=str(int(APT[ok].sum() - COMP[ok].sum()))),
                v=dict(tv=str(int(COMP[ok].sum())), vv=str(vv), vb=str(int(VB[ok].sum())), vn=str(int(VN[ok].sum()))),
                carg=[dict(cd="1", nmn="Presidente", agr=[dict(n="1", par=[dict(n="13", sg="PT", cand=[cand(13, "LULA", PT[ok].sum())])]),
                                                           dict(n="2", par=[dict(n="22", sg="PL", cand=[cand(22, "JAIR BOLSONARO", PL[ok].sum())])])])])
def cs(uf):
    ix = por_uf[uf]; n = agora(); dg, hg = relogio(n); out = {}
    for i in ix:
        s = dict(ns=f"{SEC[i]:04d}")
        if SEG[i] <= n: s["da"], s["ha"] = relogio(SEG[i])
        out.setdefault(int(MUN[i]), {}).setdefault(int(ZON[i]), []).append(s)
    return dict(dg=dg, hg=hg, cdp=str(a.pleito), abr=[dict(cd=uf, mu=[dict(cd=f"{m:05d}", zon=[dict(cd=f"{z:04d}", sec=secs) for z, secs in zs.items()]) for m, zs in out.items()])])
def elec():
    hoje = dt.date.today().strftime("%d/%m/%Y")
    return dict(pl=[dict(cd=str(a.pleito), dt=hoje, e=[dict(cd=str(a.eleicao), nm="Eleição Ordinária Federal - 2026 2º Turno (ENSAIO)", t="2")])])

class H(BaseHTTPRequestHandler):
    def log_message(self, *x): pass
    def do_GET(self):
        p = self.path.split("?")[0]; body = None
        if p.endswith("ele-c.json"): body = elec()
        elif m := re.search(r"/config/(\w\w)/\w\w-p\d+-cs\.json$", p): body = cs(m.group(1)) if m.group(1) in por_uf else None
        elif m := re.search(r"/dados/(\w\w)/(\w\w)(\d{5})-c0001-e\d+-u\.json$", p):
            k = (m.group(1), int(m.group(3))); body = ea20(por_mun[k], "mu", m.group(3)) if k in por_mun else None
        elif p.endswith("/dados/br/br-c0001-e%06d-u.json" % a.eleicao): body = ea20(np.arange(len(d)), "br", "br")
        elif m := re.search(r"/dados/(\w\w)/(\w\w)-c0001-e\d+-u\.json$", p): body = ea20(por_uf[m.group(1)], "uf", m.group(1)) if m.group(1) in por_uf else None
        if body is None: self.send_response(404); self.end_headers(); return
        raw = json.dumps(body, ensure_ascii=False).encode(); et = '"' + hashlib.md5(raw).hexdigest()[:16] + '"'
        if self.headers.get("If-None-Match") == et: self.send_response(304); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("ETag", et); self.end_headers(); self.wfile.write(raw)

print(f"TSE falso: 2º turno de {a.ano}, {len(d)} seções, velocidade {a.speed}x, início em {a.start} min após 17:00, porta {a.port}", flush=True)
ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
