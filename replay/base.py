"""Constrói a base do replay: cada seção do ano-alvo recebe o resultado do ano-base do seu local de votação.

Uso: python -I replay/base.py <ano_base> <ano_alvo> <parquet_dir> <out_parquet> [--cand-pt 13 --cand-dir 17]

Pareamento de locais (cascata, como descrito pelo autor):
  1 exato     mesma chave (UF, município, zona, nº do local) com mesmo CEP ou distância < 200 m
  2 prédio    local do ano-base a < 100 m (qualquer chave), no mesmo município
  3 vizinhos  até 5 locais do ano-base no município, ponderados por eleitorado/distância
  4 zona      média da zona (município+zona) no ano-base
  5 município média do município no ano-base
  6 UF        média da UF (municípios novos)
"""
import sys, argparse, time
import numpy as np, pandas as pd
from scipy.spatial import cKDTree

KEY = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]
LKEY = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO"]
BLOCOS = ["PT", "DIR", "OUT"]

def votos_por_secao(pq, ano, cand_pt, cand_dir):
    v = pd.read_parquet(f"{pq}/votacao_{ano}.parquet")
    v = v[~v.NR_VOTAVEL.isin([95, 96])]                      # só válidos (nominais; 95 branco, 96 nulo)
    v["bloco"] = np.where(v.NR_VOTAVEL == cand_pt, "PT", np.where(v.NR_VOTAVEL == cand_dir, "DIR", "OUT"))
    w = v.pivot_table(index=KEY, columns="bloco", values="QT_VOTOS", aggfunc="sum", fill_value=0).reset_index()
    for b in BLOCOS:
        if b not in w: w[b] = 0
    w["VALIDOS"] = w[BLOCOS].sum(axis=1)
    d = pd.read_parquet(f"{pq}/detalhe_{ano}.parquet")
    s = d.merge(w, on=KEY, how="left")
    s[BLOCOS + ["VALIDOS"]] = s[BLOCOS + ["VALIDOS"]].fillna(0).astype("int64")
    return s

def tabela_locais(pq, ano):
    l = pd.read_parquet(f"{pq}/locais_{ano}.parquet")
    l = l.drop_duplicates(KEY)
    g = l.groupby(LKEY).agg(NR_CEP=("NR_CEP", "first"), LAT=("NR_LATITUDE", "first"), LON=("NR_LONGITUDE", "first"),
                            NM=("NM_LOCAL_VOTACAO", "first"), ELEITORES=("QT_ELEITOR_SECAO", "sum")).reset_index()
    g.loc[(g.LAT.abs() < 0.01) | (g.LAT.abs() > 90) | (g.LON.abs() > 180), ["LAT", "LON"]] = np.nan
    return g

def xy(lat, lon):
    return np.c_[lon * np.cos(np.deg2rad(-15)) * 111_320, lat * 110_540]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ano_base", type=int); ap.add_argument("ano_alvo", type=int)
    ap.add_argument("pq"); ap.add_argument("out")
    ap.add_argument("--cand-pt", type=int, default=13); ap.add_argument("--cand-dir", type=int, default=17)
    ap.add_argument("--cand-pt-alvo", type=int, default=13); ap.add_argument("--cand-dir-alvo", type=int, default=22)
    a = ap.parse_args(); t0 = time.time()

    # --- ano-base agregado por local ---------------------------------------------------------
    sb = votos_por_secao(a.pq, a.ano_base, a.cand_pt, a.cand_dir)
    lb = sb.groupby(LKEY).agg(PT=("PT", "sum"), DIR=("DIR", "sum"), OUT=("OUT", "sum"), VALIDOS=("VALIDOS", "sum"),
                              COMP=("QT_COMPARECIMENTO", "sum"), APTOS=("QT_APTOS", "sum")).reset_index()
    lb = lb.merge(tabela_locais(a.pq, a.ano_base), on=LKEY, how="left")
    lb = lb[lb.VALIDOS > 0].reset_index(drop=True)
    print(f"{a.ano_base}: {len(lb)} locais com votos; coords {lb.LAT.notna().mean():.1%}", flush=True)

    # --- ano-alvo por seção -------------------------------------------------------------------
    st = votos_por_secao(a.pq, a.ano_alvo, a.cand_pt_alvo, a.cand_dir_alvo)
    lt = tabela_locais(a.pq, a.ano_alvo)
    st = st.merge(lt[LKEY + ["NR_CEP", "LAT", "LON"]], on=LKEY, how="left")
    print(f"{a.ano_alvo}: {len(st)} seções; coords {st.LAT.notna().mean():.1%}", flush=True)

    # --- pareamento por local do ano-alvo ----------------------------------------------------
    loc_t = st.groupby(LKEY).agg(NR_CEP=("NR_CEP", "first"), LAT=("LAT", "first"), LON=("LON", "first"),
                                 APTOS_T=("QT_APTOS", "sum")).reset_index()
    cols = ["PT", "DIR", "OUT", "VALIDOS", "COMP", "APTOS"]
    res = np.zeros((len(loc_t), len(cols))); nivel = np.zeros(len(loc_t), dtype=np.int8)

    # nível 1: mesma chave
    m = loc_t.merge(lb, on=LKEY, how="left", suffixes=("", "_B"))
    has = m.VALIDOS.notna().values
    dist = np.full(len(m), np.inf)
    ok_xy = has & m.LAT.notna().values & m.LAT_B.notna().values
    if ok_xy.any():
        dist[ok_xy] = np.linalg.norm(xy(m.LAT.values[ok_xy], m.LON.values[ok_xy]) - xy(m.LAT_B.values[ok_xy], m.LON_B.values[ok_xy]), axis=1)
    same_cep = has & (m.NR_CEP.values == m.NR_CEP_B.values) & m.NR_CEP.notna().values
    exato = has & (same_cep | (dist < 200))
    res[exato] = m.loc[exato, cols].values; nivel[exato] = 1
    print(f"nível 1 (exato): {exato.mean():.1%} dos locais", flush=True)

    # níveis 2 e 3: por município, com coordenadas
    lb_mun = {k: g for k, g in lb[lb.LAT.notna()].groupby(["SG_UF", "CD_MUNICIPIO"])}
    pend = np.where(~exato & loc_t.LAT.notna().values)[0]
    for (uf, mun), idx in pd.Series(pend).groupby([loc_t.SG_UF.values[pend], loc_t.CD_MUNICIPIO.values[pend]]):
        g = lb_mun.get((uf, mun))
        if g is None: continue
        tree = cKDTree(xy(g.LAT.values, g.LON.values)); P = xy(loc_t.LAT.values[idx.values], loc_t.LON.values[idx.values])
        k = min(5, len(g)); dd, ii = tree.query(P, k=k); dd = np.atleast_2d(dd.T).T if k > 1 else dd[:, None]; ii = np.atleast_2d(ii.T).T if k > 1 else ii[:, None]
        G = g[cols].values
        for r, i in enumerate(idx.values):
            if dd[r, 0] < 100:
                res[i] = G[ii[r, 0]]; nivel[i] = 2
            else:
                sel = dd[r] < 3000
                if not sel.any(): continue
                w = G[ii[r, sel], 5] / (dd[r, sel] + 50)          # eleitorado / distância
                res[i] = (G[ii[r, sel]] * (w / w.sum())[:, None]).sum(axis=0); nivel[i] = 3
    for n in (2, 3): print(f"nível {n}: {(nivel == n).mean():.1%}", flush=True)

    # níveis 4-6: zona, município, UF
    for n, keys in ((4, ["SG_UF", "CD_MUNICIPIO", "NR_ZONA"]), (5, ["SG_UF", "CD_MUNICIPIO"]), (6, ["SG_UF"])):
        pend = nivel == 0
        if not pend.any(): break
        agg = lb.groupby(keys)[cols].sum().reset_index()
        m = loc_t.loc[pend, keys].merge(agg, on=keys, how="left")
        ok = m.VALIDOS.notna().values
        ix = np.where(pend)[0][ok]
        res[ix] = m.loc[ok, cols].values; nivel[ix] = n
        print(f"nível {n}: {(nivel == n).mean():.1%}", flush=True)
    assert (nivel > 0).all(), "locais sem pareamento"

    # shares da base por local -> seções do alvo
    loc_t["NIVEL"] = nivel
    for j, c in enumerate(cols): loc_t["B_" + c] = res[:, j]
    out = st.merge(loc_t[LKEY + ["NIVEL"] + ["B_" + c for c in cols]], on=LKEY, how="left")
    for b in BLOCOS: out["BS_" + b] = out["B_" + b] / out.B_VALIDOS            # share da base por bloco
    out["B_COMP_RATE"] = out.B_COMP / out.B_APTOS                               # comparecimento da base
    out["B_VAL_RATE"] = out.B_VALIDOS / out.B_COMP                              # taxa de válidos da base
    out = out.rename(columns={"DT_PRIM_TOT_PARCIAL_HOR_TSE": "T_TOT", "DT_RECEBIMENTO_BU_HOR_TSE": "T_BU"})
    out.to_parquet(a.out, index=False)
    w = out.QT_APTOS
    print("eleitorado por nível de pareamento:", {n: f"{w[out.NIVEL == n].sum() / w.sum():.1%}" for n in range(1, 7)})
    print(f"salvo {a.out}: {len(out)} seções em {time.time() - t0:.0f}s")

if __name__ == "__main__":
    main()
