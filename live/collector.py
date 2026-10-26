"""Coletor da noite: lê a divulgação do TSE a cada ciclo, roda o modelo do 2º turno e grava saida/apuracao.json.

Uso:
  python live/collector.py --pq data_tse/parquet --t1 2026 --data 25/10/2026 --out saida --site site/dados/apuracao.json
  python live/collector.py --base http://localhost:8787 --pleito 9999 --eleicao 9998 --t1 2022 ...   # ensaio contra o TSE falso

Retoma sozinho: ao iniciar, recarrega os pontos de saida/apuracao.json e o último estado bruto de saida/historico/.
"""
import argparse, json, os, sys, time, gzip, glob, traceback, datetime as dt
import numpy as np
from tse_client import Cliente, caminhos
from live_model import carregar_base_1t, ModeloVivo

UFS = "ac al am ap ba ce df es go ma mg ms mt pa pb pe pi pr rj rn ro rr rs sc se sp to zz".split()
CAND = {"PT": "13", "PL": "22"}

def descobrir(cli, data):
    st, d = cli.json(caminhos("ele2026", 0, 0)["elec"]())
    for p in (d or {}).get("pl", []):
        if p.get("dt") == data:
            for e in p.get("e", []):
                if "Federal" in e.get("nm", "") and str(e.get("t")) == "2":
                    return int(p["cd"]), int(e["cd"])
    return None

def num(s): return float(str(s or "0").replace(",", "."))

def ler_mun(j):
    """Do arquivo EA20 municipal: votos por candidato, eleitorado das seções totalizadas, comparecimento, válidos, seções."""
    vap = {}
    for c in j.get("carg", []):
        for a in c.get("agr", []):
            for p in a.get("par", []):
                for k in p.get("cand", []): vap[k["n"]] = num(k.get("vap"))
    e, v, s = j.get("e", {}), j.get("v", {}), j.get("s", {})
    return dict(pt=vap.get(CAND["PT"], 0.0), pl=vap.get(CAND["PL"], 0.0), est=num(e.get("est")), comp=num(e.get("c")),
                vv=num(v.get("vv")), vb=num(v.get("vb")), vn=num(v.get("vn")), st=int(num(s.get("st"))), ts=int(num(s.get("ts"))), hg=j.get("hg"))

def gravar_json(caminho, obj):
    tmp = caminho + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, caminho)

def retomar(out):
    """Pontos já publicados e último estado bruto (municípios lidos + contagem de seções da lista)."""
    pontos, estado, st_lista, ciclo = [], {}, {}, 0
    try:
        with open(f"{out}/apuracao.json") as f: j = json.load(f)
        pontos = j.get("pontos", []); ciclo = j.get("diagnostico", {}).get("ciclo", 0)
    except Exception: pass
    hist = sorted(glob.glob(f"{out}/historico/*.json.gz"))
    if hist:
        try:
            with gzip.open(hist[-1], "rt") as f: h = json.load(f)
            estado, st_lista = h.get("estado", {}), h.get("st_lista", {})
        except Exception: estado, st_lista = {}, {}
    return pontos, estado, st_lista, ciclo

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://resultados.tse.jus.br/oficial"); ap.add_argument("--ciclo", default="ele2026")
    ap.add_argument("--pleito", type=int); ap.add_argument("--eleicao", type=int); ap.add_argument("--data", default="25/10/2026")
    ap.add_argument("--pq", default="data_tse/parquet"); ap.add_argument("--t1", default="2026"); ap.add_argument("--out", default="saida")
    ap.add_argument("--site", default=None, help="segunda cópia do apuracao.json (ex.: site/dados/apuracao.json)")
    ap.add_argument("--intervalo", type=float, default=60); ap.add_argument("--rps", type=int, default=60); ap.add_argument("--boot", type=int, default=150); ap.add_argument("--boot-uf", type=int, default=60)
    ap.add_argument("--prior-pt", type=float, default=None); ap.add_argument("--ate", default=None); ap.add_argument("--ciclos", type=int, default=0)
    ap.add_argument("--min-pct", type=float, default=2.0, help="só exibe projeção a partir deste %% apurado")
    ap.add_argument("--sem-retomar", action="store_true", help="ignora saida/ anterior e começa do zero")
    a = ap.parse_args()
    os.makedirs(f"{a.out}/historico", exist_ok=True)
    if a.site: os.makedirs(os.path.dirname(a.site) or ".", exist_ok=True)
    cli = Cliente(a.base, rps=a.rps, workers=24)
    pleito, eleicao = a.pleito, a.eleicao
    while not (pleito and eleicao):
        r = descobrir(cli, a.data)
        if r: pleito, eleicao = r; print(f"códigos: pleito {pleito} eleição {eleicao}", flush=True)
        else: print("aguardando o TSE configurar o 2º turno (ele-c.json)…", flush=True); time.sleep(300)
    P = caminhos(a.ciclo, pleito, eleicao)
    print("carregando base do 1º turno…", flush=True)
    M = ModeloVivo(carregar_base_1t(a.pq, a.t1), prior_share_pt=a.prior_pt)
    print(f"{M.n} seções, {M.nm} municípios | prior PT {a.prior_pt} | boot {a.boot}", flush=True)
    apur = np.zeros(M.n, bool)
    pontos, estado, st_lista, ciclo = ([], {}, {}, 0) if a.sem_retomar else retomar(a.out)
    if pontos or estado: print(f"retomando: {len(pontos)} pontos, {len(estado)} municípios, ciclo {ciclo}", flush=True)
    desconhecidas = 0; falhas = 0
    while True:
        t0 = time.time(); ciclo += 1
        try:
            # 1) lista de seções por UF -> quais já totalizaram
            res = cli.muitos([P["secoes"](uf) for uf in UFS])
            novo_st = {}; ufs_ok = 0; marcas = {}
            for uf, (st, j) in zip(UFS, res.values()):
                if not j: continue
                ufs_ok += 1
                for abr in j.get("abr", []):
                    for mu in abr.get("mu", []):
                        mk = f"{uf.upper()}-{int(mu['cd']):05d}"; n = 0
                        for z in mu.get("zon", []):
                            for s in z.get("sec", []):
                                if s.get("nsp") or not s.get("ha"): continue
                                n += 1; i = M.idx.get((uf.upper(), int(mu["cd"]), int(z["cd"]), int(s["ns"])))
                                if i is None: desconhecidas += 1
                                else: marcas.setdefault(mk, []).append(i)
                        if n: novo_st[mk] = n
            # 2) arquivos municipais: os que mudaram na lista + os cujo EA20 ainda traz menos seções que a lista (embargo até 17h / atraso do CDN)
            mudou = [mk for mk, n in novo_st.items() if st_lista.get(mk) != n or estado.get(mk, {}).get("st", 0) < n]
            st_lista.update(novo_st)
            paths = {P["mun"](mk[:2].lower(), mk[3:]): mk for mk in mudou}
            rm = cli.muitos(list(paths))
            for p, (st, j) in rm.items():
                if j: estado[paths[p]] = ler_mun(j)
            # 2b) a lista de seções atrasa vários minutos em relação aos arquivos: onde o total da UF está à frente do que temos, relê os municípios incompletos da UF
            ru = cli.muitos([P["uf"](uf) for uf in UFS]); uf_st = {uf.upper(): int(num(j.get("s", {}).get("st"))) for uf, (st, j) in zip(UFS, ru.values()) if j}
            held = {}
            for mk, e in estado.items(): held[mk[:2]] = held.get(mk[:2], 0) + e["st"]
            atras = {u for u, n in uf_st.items() if n > held.get(u, 0)}; ja = set(paths.values())
            extra = [mk for mk in M.mun_names if mk[:2] in atras and mk not in ja and estado.get(mk, {}).get("st", 0) < estado.get(mk, {}).get("ts", 10**9)]
            if extra:
                paths2 = {P["mun"](mk[:2].lower(), mk[3:]): mk for mk in extra}
                for p, (st, j) in cli.muitos(list(paths2)).items():
                    if j: estado[paths2[p]] = ler_mun(j)
            # seção só conta como apurada quando o arquivo municipal já traz votos (antes das 17h a lista marca o exterior, mas os votos ficam embargados)
            embargo = 0
            for mk, ix in marcas.items():
                e = estado.get(mk)
                if e and e["st"] > 0 and e["comp"] > 0: apur[ix] = True
                else: embargo += len(ix)
            stb, jbr = cli.json(P["brasil"]())
            # 3) vetores por município
            O = np.zeros((M.nm, 2)); esa = np.zeros(M.nm); comp = np.zeros(M.nm); vv = np.zeros(M.nm); vbn = np.zeros(M.nm)
            for mk, e in estado.items():
                i = M.mun_idx.get(mk)
                if i is None: continue
                O[i] = (e["pt"], e["pl"]); esa[i] = e["est"]; comp[i] = e["comp"]; vv[i] = e["vv"]; vbn[i] = e["vb"] + e["vn"]
            # 4) modelo
            r = M.ciclo(apur, O, esa, comp, vv, boot=a.boot, boot_uf=a.boot_uf)
            if r["n_ok"] < 20 or r["ufs_ok"] < 3:   # poucos municípios: prévia = perfil do 1T + prior, sem ajustar inclinações com meia dúzia de pontos
                r0 = M.projetar(apur, np.zeros_like(O), esa, comp, vv); r["proj"], r["uf_proj"] = r0["proj"], r0["uf_proj"]
            agora = dt.datetime.now().strftime("%H:%M"); pct = r["pct"]
            br = ler_mun(jbr) if jbr else None
            exibe = pct >= a.min_pct and np.isfinite(r["faixa"][0])
            lead = r["obs"][0] - r["obs"][1]
            ponto = dict(t=agora, x=round(pct, 2), apurado=dict(PT=round(r["apurado"][0], 2), PL=round(r["apurado"][1], 2)),
                         projecao=dict(PT=round(r["proj"][0], 2), PL=round(r["proj"][1], 2)) if exibe else None,
                         faixa=dict(PT=[round(r["faixa"][0], 2), round(r["faixa"][1], 2)], PL=[round(100 - r["faixa"][1], 2), round(100 - r["faixa"][0], 2)]) if exibe else None,
                         p_vitoria=dict(PT=round(r["p_pt"], 3), PL=round(1 - r["p_pt"], 3)) if exibe else None,
                         preliminar=dict(PT=round(r["proj"][0], 2), PL=round(r["proj"][1], 2)) if not exibe else None,
                         definido_mat=bool(abs(lead) > r["pend_aptos"]), eleitores_pendentes=int(r["pend_aptos"]), votos=dict(PT=int(r["obs"][0]), PL=int(r["obs"][1])),
                         comparecimento_proj=round(r["comp_proj"], 2), brancos_nulos_pct=round(vbn.sum() / max(comp.sum(), 1) * 100, 2),
                         incerteza=dict(sd=round(float(r["sd"]), 3), sd_mun=round(float(r["sd_mun"]), 3), sd_uf=round(float(r["sd_uf"]), 3), n_mun=r["n_ok"], n_ufs=r["ufs_ok"]) if np.isfinite(r["sd"]) else None)
            vazio = pct == 0 and O.sum() == 0
            if vazio and pontos and pontos[-1]["x"] == 0 and pontos[-1]["votos"]["PT"] + pontos[-1]["votos"]["PL"] == 0: pontos[-1] = ponto   # antes do início: um único ponto zero
            else: pontos.append(ponto)
            estados = [dict(uf=u, x=round(r["uf_pct"][i], 1), PT=round(r["uf_proj"][i], 2), PL=round(100 - r["uf_proj"][i], 2),
                            apurado_PT=round(r["uf_apur"][i], 2), PT_1t=round(r["uf_1t"][i], 2), swing=round(r["uf_proj"][i] - r["uf_1t"][i], 2),
                            comparecimento_vs_1t=round((r["adj_c"][i] - 1) * 100, 2)) for i, u in enumerate(M.uf_names)]
            saida = dict(eleicao="Eleições 2026 · Presidente", turno=2, ambiente="oficial" if "tse.jus.br" in a.base else "ensaio",
                         atualizado=dt.datetime.now().strftime("%d/%m/%Y %H:%M"), pct_eleitorado_apurado=round(pct, 2),
                         tse_pct_secoes=br["st"] / max(br["ts"], 1) * 100 if br else None, tse_hora=br["hg"] if br else None,
                         candidatos=[dict(bloco="PT", nome="Lula", partido="PT"), dict(bloco="PL", nome="Flávio Bolsonaro", partido="PL")],
                         base_1t=dict(PT=round(float(M.B[:, 0].sum() / M.B.sum() * 100), 2), PL=round(float(M.B[:, 1].sum() / M.B.sum() * 100), 2),
                                      comparecimento=round(float(M.b.QT_COMPARECIMENTO1.sum() / M.b.QT_APTOS1.sum() * 100), 2),
                                      brancos_nulos_pct=round(float((M.b.VB1.sum() + M.b.VN1.sum()) / M.b.QT_COMPARECIMENTO1.sum() * 100), 2),
                                      outros=round(float(M.b.OUT1.sum() / M.b.VALIDOS1.sum() * 100), 2)),
                         prior_pt=a.prior_pt, coef_outros=round(float(r["coef_br"][2]), 3), pontos=pontos, estados=estados,
                         diagnostico=dict(ciclo=ciclo, secoes_desconhecidas=desconhecidas, secoes_embargadas=embargo, municipios_lidos=len(estado), ufs_lidas=ufs_ok, req=cli.stats, falhas=falhas))
            gravar_json(f"{a.out}/apuracao.json", saida)
            if a.site: gravar_json(a.site, saida)
            if not vazio or ciclo == 1:
                with gzip.open(f"{a.out}/historico/{ciclo:04d}_{agora.replace(':', '')}.json.gz", "wt") as f: json.dump(dict(estado=estado, st_lista=st_lista), f)
            fx = f"faixa {r['faixa'][0]:.2f}-{r['faixa'][1]:.2f} P(PT)={r['p_pt']:.2f}" if exibe else "(preliminar)"
            print(f"[{agora}] ciclo {ciclo} {time.time() - t0:4.0f}s | apurado {pct:5.2f}% | PT {r['apurado'][0]:.2f} | proj PT {r['proj'][0]:.2f} {fx} | {len(mudou)}+{len(extra)} mun lidos, {embargo} seç. sem votos, {ufs_ok} UFs, req {cli.stats['req']} 304={cli.stats['n304']} erro={cli.stats['erro']}", flush=True)
            if a.ciclos and ciclo >= a.ciclos: break
            if a.ate and agora >= a.ate: break
            if pct > 99.995 and ciclo > 5: print("apuração concluída"); break
        except Exception:
            falhas += 1; print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] falha no ciclo {ciclo}:", flush=True); traceback.print_exc(); sys.stdout.flush()
            if falhas > 50: sys.exit(1)
        time.sleep(max(0, a.intervalo - (time.time() - t0)))

if __name__ == "__main__":
    main()
