"""Modelo do 2º turno: base = 1º turno da mesma eleição, na mesma seção. Dois candidatos, uma equação de swing.

Uso (replay 2022): python -I replay/model2t.py replay <parquet_dir> --ano 2022 [--boot 200] [--out csv]

Swing municipal = log(PT/DIR) apurado no 2T - log(PT/DIR) no 1T das mesmas seções. Regressão ponderada no perfil do 1T
(razão log PT/DIR, fração de votos em outros candidatos, porte do município), Brasil -> região -> UF com encolhimento EB.
Seção pendente: share PT = sigmoide(razão log do 1T + swing previsto); válidos = aptos x comparecimento x taxa de válidos do
1T, ajustados pela UF (observado/1T nas seções apuradas). Bootstrap de municípios -> faixa de 90% e P(vitória).
"""
import argparse, time
import numpy as np, pandas as pd
import sys; sys.path.insert(0, __file__.rsplit("/", 1)[0])
from model import REGIAO, wls_ridge, EPS

KEY = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]

def votos(pq, nome, cand_pt, cand_dir):
    v = pd.read_parquet(f"{pq}/votacao_{nome}.parquet")
    v = v[~v.NR_VOTAVEL.isin([95, 96])]
    v["bloco"] = np.where(v.NR_VOTAVEL == cand_pt, "PT", np.where(v.NR_VOTAVEL == cand_dir, "DIR", "OUT"))
    w = v.pivot_table(index=KEY, columns="bloco", values="QT_VOTOS", aggfunc="sum", fill_value=0).reset_index()
    for b in ("PT", "DIR", "OUT"):
        if b not in w: w[b] = 0
    d = pd.read_parquet(f"{pq}/detalhe_{nome}.parquet")[KEY + ["QT_APTOS", "QT_COMPARECIMENTO", "NR_LOCAL_VOTACAO", "DT_PRIM_TOT_PARCIAL_HOR_TSE"]]
    s = d.merge(w, on=KEY, how="left"); s[["PT", "DIR", "OUT"]] = s[["PT", "DIR", "OUT"]].fillna(0)
    s["VALIDOS"] = s.PT + s.DIR + s.OUT
    return s

def build_base_2t(pq, t1, t2, cand_pt=13, cand_dir=22):
    """Tabela por seção do 2T com o 1T da mesma seção (fallback: local, zona, município do 1T)."""
    a = votos(pq, t1, cand_pt, cand_dir).rename(columns={c: c + "1" for c in ["PT", "DIR", "OUT", "VALIDOS", "QT_APTOS", "QT_COMPARECIMENTO"]})
    b = votos(pq, t2, cand_pt, cand_dir).rename(columns={"DT_PRIM_TOT_PARCIAL_HOR_TSE": "T_TOT"})
    cols1 = ["PT1", "DIR1", "OUT1", "VALIDOS1", "QT_APTOS1", "QT_COMPARECIMENTO1"]
    m = b.merge(a[KEY + cols1], on=KEY, how="left"); m[cols1] = m[cols1].astype(float); m["NIVEL"] = np.where(m.VALIDOS1.fillna(0) > 0, 1, 0)
    for n, keys in ((2, ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO"]), (3, ["SG_UF", "CD_MUNICIPIO", "NR_ZONA"]), (4, ["SG_UF", "CD_MUNICIPIO"]), (5, ["SG_UF"])):
        pend = m.NIVEL == 0
        if not pend.any(): break
        agg = a.groupby(keys)[cols1].sum().reset_index()
        agg = agg[agg.VALIDOS1 > 0]
        f = m.loc[pend, keys].merge(agg, on=keys, how="left")
        ok = f.VALIDOS1.notna().values; ix = m.index[pend][ok]
        # escala pelo eleitorado da seção (shares do agregado x aptos da seção)
        sc = (m.loc[ix, "QT_APTOS"].values / f.loc[ok, "QT_APTOS1"].values)[:, None]
        m.loc[ix, cols1] = f.loc[ok, cols1].values * sc; m.loc[ix, "NIVEL"] = n
    w = m.QT_APTOS
    print("base 2T: seções", len(m), "| eleitorado por nível:", {n: f"{w[m.NIVEL == n].sum() / w.sum():.1%}" for n in sorted(m.NIVEL.unique())})
    return m[m.T_TOT.notna() & (m.VALIDOS1 > 0)].reset_index(drop=True)

class Replay2T:
    def __init__(self, b, prior_w=20_000, prior_share_pt=None, min_valid=30, tau_floor=1e-4):
        self.n = len(b); self.prior_w, self.min_valid, self.tau_floor = prior_w, min_valid, tau_floor
        self.mun = pd.factorize(b.SG_UF + "-" + b.CD_MUNICIPIO.astype(str))[0]; self.nm = self.mun.max() + 1
        self.uf_names = sorted(set(b.SG_UF)); ufi = {u: i for i, u in enumerate(self.uf_names)}
        self.uf = np.array([ufi[u] for u in b.SG_UF]); self.nu = len(self.uf_names)
        self.uf_reg = np.array([["N", "NE", "CO", "SE", "S", "ZZ"].index(REGIAO[u]) for u in self.uf_names]); self.nr = 6
        self.mun_uf = np.zeros(self.nm, int); self.mun_uf[self.mun] = self.uf
        self.aptos = b.QT_APTOS.values.astype(float); self.comp = b.QT_COMPARECIMENTO.values.astype(float)
        self.V = np.c_[b.PT.values, b.DIR.values].astype(float); self.valid = self.V.sum(1)
        self.B = np.c_[b.PT1.values, b.DIR1.values].astype(float)                      # votos do 1T na seção
        self.out1 = b.OUT1.values / np.maximum(b.VALIDOS1.values, 1)
        self.lp1 = np.log((self.B[:, 0] + EPS) / (self.B[:, 1] + EPS))
        self.comp1 = np.clip(b.QT_COMPARECIMENTO1.values / np.maximum(b.QT_APTOS1.values, 1), 0.4, 0.98)
        self.val1 = np.clip(b.VALIDOS1.values / np.maximum(b.QT_COMPARECIMENTO1.values, 1), 0.7, 1.0)
        self.e_comp = self.aptos * self.comp1; self.e_valid = self.e_comp * self.val1
        mun_aptos = np.bincount(self.mun, self.aptos, self.nm); self.porte = np.log10(mun_aptos[self.mun]) - 4
        self.t = b.T_TOT.values; self.final = self.V.sum(0) / self.valid.sum() * 100
        self.beta0 = 0.0
        if prior_share_pt is not None:   # pesquisa final (% PT dos válidos entre os dois) -> prior do intercepto
            bn = self.B.sum(0); self.beta0 = np.log(prior_share_pt / (100 - prior_share_pt)) - np.log(bn[0] / bn[1])

    def fit(self, X, y, w, ok):
        k = X.shape[1]; X, y, W = X[ok], y[ok], w[ok]; uf_m = self.mun_uf[ok]; reg_m = self.uf_reg[uf_m]
        lam = np.zeros(k); lam[0] = self.prior_w; b0 = np.zeros(k); b0[0] = self.beta0
        if len(y) == 0: return np.tile(b0, (self.nu, 1))
        b_br = wls_ridge(X, y, W, lam, b0); r = y - X @ b_br; sigma2 = max((W * r**2).sum() / max(W.sum(), 1), 1e-6)
        b_reg = np.tile(b_br, (self.nr, 1)); coef = np.zeros((self.nu, k))
        for level, groups, parent in (("reg", reg_m, lambda g: b_br), ("uf", uf_m, lambda g: b_reg[self.uf_reg[g]])):
            ng = self.nr if level == "reg" else self.nu; est, par, prec = [], [], []
            for g in range(ng):
                s = groups == g
                if s.sum() < 3: continue
                XtW = X[s].T * W[s]; A = XtW @ X[s] + 1e-6 * np.eye(k)
                est.append(np.linalg.solve(A, XtW @ y[s])); par.append(parent(g)); prec.append(np.diag(np.linalg.inv(A)) * sigma2)
            if est:
                est, par, prec = map(np.array, (est, par, prec))
                lam_g = sigma2 / np.maximum(((est - par) ** 2).mean(0) - prec.mean(0), self.tau_floor)
            else: lam_g = np.full(k, 1e12)
            out = np.zeros((ng, k))
            for g in range(ng):
                s = groups == g; p = parent(g); out[g] = wls_ridge(X[s], y[s], W[s], lam_g, p) if s.any() else p
            if level == "reg": b_reg = out
            else: coef = out
        return coef

    def project(self, apur, boot_rng=None):
        m = self.mun
        O = np.c_[np.bincount(m, self.V[:, 0] * apur, self.nm), np.bincount(m, self.V[:, 1] * apur, self.nm)]
        B = np.c_[np.bincount(m, self.B[:, 0] * apur, self.nm), np.bincount(m, self.B[:, 1] * apur, self.nm)]
        bo = np.bincount(m, self.out1 * self.B.sum(1) * apur, self.nm) / np.maximum(B.sum(1), 1)   # fração "outros" no 1T (apuradas)
        ov = O.sum(1); ok = ov >= self.min_valid
        y = np.log((O[:, 0] + EPS) / (O[:, 1] + EPS)) - np.log((B[:, 0] + EPS) / (B[:, 1] + EPS))
        X = np.c_[np.ones(self.nm), np.log((B[:, 0] + EPS) / (B[:, 1] + EPS)), bo, np.log10(np.maximum(np.bincount(m, self.aptos, self.nm), 10)) - 4]
        w = ov.copy()
        if boot_rng is not None:
            idx = np.where(ok)[0]; w = w * np.bincount(boot_rng.choice(idx, len(idx)), minlength=self.nm)
        coef = self.fit(X, y, w, ok & (w > 0))
        pend = ~apur
        Xs = np.c_[np.ones(pend.sum()), self.lp1[pend], self.out1[pend], self.porte[pend]]
        yhat = np.einsum("ik,ik->i", Xs, coef[self.uf[pend]])
        sh = 1 / (1 + np.exp(-(self.lp1[pend] + yhat)))
        u = self.uf; K = 50_000.0
        oc, ec = np.bincount(u, self.comp * apur, self.nu), np.bincount(u, self.e_comp * apur, self.nu)
        ovl, evl = np.bincount(u, self.valid * apur, self.nu), np.bincount(u, self.e_valid * apur, self.nu)
        nat_c = (oc.sum() + K) / (ec.sum() + K); nat_v = (ovl.sum() + K) / (evl.sum() + K)
        adj_c = (oc + K * nat_c) / (ec + K); adj_v = (ovl + K * nat_v) / (evl + K)
        pv = self.aptos[pend] * np.clip(self.comp1[pend] * adj_c[u[pend]], 0.3, 1.0) * np.clip(self.val1[pend] * adj_v[u[pend]], 0.5, 1.0)
        tot = O.sum(0) + np.array([(pv * sh).sum(), (pv * (1 - sh)).sum()])
        return tot / tot.sum() * 100, O.sum(0) / max(ov.sum(), 1) * 100, dict(lead_votes=O[:, 0].sum() - O[:, 1].sum(), pend_aptos=self.aptos[pend].sum(), coef_br=coef.mean(0))

    def run(self, grid, boot=0, boot_at=(), seed=1):
        order = np.argsort(self.t); cum = np.cumsum(self.aptos[order]) / self.aptos.sum(); rng = np.random.default_rng(seed); rows = []
        for g in grid:
            k = min(np.searchsorted(cum, g / 100), self.n - 1); apur = self.t <= self.t[order[k]]
            proj, obs, info = self.project(apur)
            row = dict(t=pd.Timestamp(self.t[order[k]]).strftime("%H:%M"), pct=self.aptos[apur].sum() / self.aptos.sum() * 100,
                       obs_PT=obs[0], proj_PT=proj[0], proj_DIR=proj[1], definido_mat=abs(info["lead_votes"]) > info["pend_aptos"], coef_out1=info["coef_br"][2])
            if boot and any(abs(g - a) < 1e-9 for a in boot_at):
                reps = np.array([self.project(apur, boot_rng=rng)[0][0] for _ in range(boot)])
                row.update(lo_PT=np.percentile(reps, 5), hi_PT=np.percentile(reps, 95), p_PT_vence=(reps > 50).mean())
            rows.append(row)
        return pd.DataFrame(rows)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("pq"); ap.add_argument("--ano", type=int, default=2022)
    ap.add_argument("--boot", type=int, default=0); ap.add_argument("--out"); ap.add_argument("--prior-pt", type=float, default=None); ap.add_argument("--prior-w", type=float, default=20_000)
    a = ap.parse_args(); t0 = time.time()
    b = build_base_2t(a.pq, f"{a.ano}", f"{a.ano}_t2")
    R = Replay2T(b, prior_w=a.prior_w, prior_share_pt=a.prior_pt)
    print(f"final real 2T: PT {R.final[0]:.2f}  DIR {R.final[1]:.2f}  ({R.n} seções)")
    grid = list(np.round(np.arange(0.2, 1.0, 0.1), 1)) + list(np.round(np.arange(1.0, 10.0, 0.5), 1)) + list(range(10, 100, 5)) + [99]
    df = R.run(grid, boot=a.boot, boot_at=(0.5, 1.0, 2.0, 3.0, 5.0, 10, 25, 50, 75))
    df["err_PT"] = df.proj_PT - R.final[0]; df["err_obs"] = df.obs_PT - R.final[0]
    pd.set_option("display.width", 200); pd.set_option("display.max_rows", 200)
    print(df.round(3).to_string(index=False))
    ok = df.err_PT.abs() < 0.5; print("\nerro < 0,5 pp a partir de (sustentado):", df.pct[ok[::-1].cummin()[::-1]].min())
    print("primeiro 'definido matematicamente':", df.pct[df.definido_mat].min(), "% apurado")
    print(f"tempo {time.time() - t0:.0f}s")
    if a.out: df.to_csv(a.out, index=False)

if __name__ == "__main__":
    main()
