"""Replay de 2026 (base 2022) na mesma grade de % apurado dos pontos publicados pelo autor, e comparação ponto a ponto.

Uso: python -I replay/compare2026.py <base_2026.parquet> <rodrigo_apuracao.json> [--prior-shares 46,44,10] [--boot 200] [--out csv]
"""
import sys, json, argparse
import numpy as np, pandas as pd
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from model import Replay

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("rodrigo"); ap.add_argument("--prior-shares", default=None)
    ap.add_argument("--boot", type=int, default=0); ap.add_argument("--out", default=None)
    ap.add_argument("--mun-shrink", type=float, default=0.0)
    a = ap.parse_args()
    base = pd.read_parquet(a.base); base = base[base.T_TOT.notna()]
    ps = [float(x) for x in a.prior_shares.split(",")] if a.prior_shares else None
    R = Replay(base, prior_shares=ps, mun_shrink=a.mun_shrink)
    fin = R.final
    print(f"final (dados coletados): PT {fin[0]:.2f}  PL {fin[1]:.2f}  OUT {fin[2]:.2f}   | oficial: PT 45.16  PL 47.03  OUT 7.81  | seções {R.n}")
    rod = json.load(open(a.rodrigo))["pontos"]
    rod = [p for p in rod if p.get("projecao")]
    xs = sorted(set(round(p["x"], 2) for p in rod))
    order = np.argsort(R.t); cum = np.cumsum(R.aptos[order]) / R.aptos.sum()
    rng = np.random.default_rng(1); rows = []
    for p in rod:
        x = p["x"]; k = min(np.searchsorted(cum, x / 100), R.n - 1); apur = R.t <= R.t[order[k]]
        proj, obs = R.project(apur)
        row = dict(t=p["t"], x=x, meu_pct=R.aptos[apur].sum() / R.aptos.sum() * 100,
                   rod_obs_PT=p["apurado"]["PT"], rod_obs_PL=p["apurado"]["PL"], meu_obs_PT=obs[0], meu_obs_PL=obs[1],
                   rod_PT=p["projecao"]["PT"], rod_PL=p["projecao"]["PL"], meu_PT=proj[0], meu_PL=proj[1],
                   rod_lo_PT=p["faixa"]["PT"][0], rod_hi_PT=p["faixa"]["PT"][1], rod_lo_PL=p["faixa"]["PL"][0], rod_hi_PL=p["faixa"]["PL"][1],
                   rod_p2t=p["p_2turno"])
        rows.append(row)
    df = pd.DataFrame(rows)
    for who in ("rod", "meu"):
        df[f"{who}_err_PT"] = df[f"{who}_PT"] - 45.16; df[f"{who}_err_PL"] = df[f"{who}_PL"] - 47.03
        df[f"{who}_err_marg"] = (df[f"{who}_PL"] - df[f"{who}_PT"]) - (47.03 - 45.16)
    df["meu_err_PT_vs_meufinal"] = df.meu_PT - fin[0]; df["meu_err_PL_vs_meufinal"] = df.meu_PL - fin[1]
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 100)
    marks = [2.15, 3, 5, 8, 10, 13, 20, 30, 40, 50, 60, 70, 85, 95, 99]
    sel = pd.concat([df.iloc[[(df.x - m).abs().argmin()]] for m in marks]).drop_duplicates("x")
    cols = ["t", "x", "rod_obs_PT", "rod_obs_PL", "meu_obs_PT", "meu_obs_PL", "rod_PT", "rod_PL", "meu_PT", "meu_PL", "rod_err_PT", "rod_err_PL", "meu_err_PT", "meu_err_PL", "rod_lo_PT", "rod_hi_PT"]
    print(sel[cols].round(2).to_string(index=False))
    print("\nerro absoluto médio (pp) por faixa de % apurado:")
    bins = [(2, 5), (5, 10), (10, 25), (25, 50), (50, 90), (90, 100)]
    out = []
    for lo, hi in bins:
        s = df[(df.x >= lo) & (df.x < hi)]
        out.append(dict(faixa=f"{lo}-{hi}%", n=len(s), rod_PT=s.rod_err_PT.abs().mean(), meu_PT=s.meu_err_PT.abs().mean(), rod_PL=s.rod_err_PL.abs().mean(), meu_PL=s.meu_err_PL.abs().mean(),
                        rod_marg=s.rod_err_marg.abs().mean(), meu_marg=s.meu_err_marg.abs().mean(),
                        corr_proj_PT=np.corrcoef(s.rod_PT, s.meu_PT)[0, 1] if len(s) > 2 else np.nan,
                        rod_cobertura=((s.rod_lo_PT <= 45.16) & (s.rod_hi_PT >= 45.16)).mean()))
    print(pd.DataFrame(out).round(3).to_string(index=False))
    d = (df.meu_PT - df.rod_PT); print(f"\ndiferença minha - dele (PT): média {d.mean():+.2f}, dp {d.std():.2f}, |max| {d.abs().max():.2f}")
    d = (df.meu_PL - df.rod_PL); print(f"diferença minha - dele (PL): média {d.mean():+.2f}, dp {d.std():.2f}, |max| {d.abs().max():.2f}")
    if a.out: df.to_csv(a.out, index=False)

if __name__ == "__main__":
    main()
