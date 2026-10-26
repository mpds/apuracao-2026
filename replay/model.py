"""Replay da apuração com o modelo de swing hierárquico (reconstrução do método descrito pelo autor).

Uso: python -I replay/model.py <base.parquet> --out <csv> [--boot 200] [--mun-shrink 0] [--prior-w 20000]

Em cada instante t, as seções com T_TOT <= t estão apuradas. Por município, o swing é a diferença em razões log
(PT/OUT e DIR/OUT) entre o apurado e a base das mesmas seções. Regressão ponderada do swing no perfil da base
(razões log da base, porte do município), com coeficientes Brasil -> região -> UF e encolhimento empírico-bayesiano.
Seções pendentes recebem base + swing previsto pelo próprio perfil; comparecimento e taxa de válidos ajustados pela UF.
Faixa de 90% por bootstrap de municípios.
"""
import argparse, time
import numpy as np, pandas as pd

REGIAO = {**{u: "N" for u in "AC AM AP PA RO RR TO".split()}, **{u: "NE" for u in "AL BA CE MA PB PE PI RN SE".split()},
          **{u: "CO" for u in "DF GO MS MT".split()}, **{u: "SE" for u in "ES MG RJ SP".split()}, **{u: "S" for u in "PR RS SC".split()}, "ZZ": "ZZ"}
EPS = 0.5

def wls_ridge(X, y, w, lam, beta0):
    """Mínimos quadrados ponderados com penalidade lam*(beta-beta0)^2 por coeficiente."""
    XtW = X.T * w
    A = XtW @ X + np.diag(lam); b = XtW @ y + lam * beta0
    return np.linalg.solve(A, b)

class Replay:
    def __init__(self, base, prior_w=20_000, mun_shrink=0.0, min_valid=30, cap_w=np.inf, tau_floor=1e-4, w_pow=1.0, prior_shares=None):
        b = base.reset_index(drop=True)
        self.n = len(b)
        self.prior_w, self.mun_shrink, self.min_valid, self.cap_w, self.tau_floor, self.w_pow = prior_w, mun_shrink, min_valid, cap_w, tau_floor, w_pow
        # ids
        self.mun = pd.factorize(b.SG_UF + "-" + b.CD_MUNICIPIO.astype(str))[0]; self.nm = self.mun.max() + 1
        ufs = b.SG_UF.values; self.uf_names = sorted(set(ufs)); ufi = {u: i for i, u in enumerate(self.uf_names)}
        self.uf = np.array([ufi[u] for u in ufs]); self.nu = len(self.uf_names)
        self.uf_reg = np.array([["N", "NE", "CO", "SE", "S", "ZZ"].index(REGIAO[u]) for u in self.uf_names]); self.nr = 6
        self.mun_uf = np.zeros(self.nm, int); self.mun_uf[self.mun] = self.uf
        # verdade e base
        self.aptos = b.QT_APTOS.values.astype(float)
        self.V = np.c_[b.PT.values, b.DIR.values, b.OUT.values].astype(float)          # votos reais por bloco
        self.comp = b.QT_COMPARECIMENTO.values.astype(float)
        self.valid = self.V.sum(1)
        bs = np.c_[b.BS_PT.values, b.BS_DIR.values, b.BS_OUT.values]; bs = np.nan_to_num(bs, nan=1/3)
        bs = np.clip(bs, 1e-4, None); bs /= bs.sum(1, keepdims=True); self.bs = bs
        self.b_comp = np.clip(np.nan_to_num(b.B_COMP_RATE.values, nan=0.8), 0.5, 0.97)
        self.b_val = np.clip(np.nan_to_num(b.B_VAL_RATE.values, nan=0.93), 0.75, 1.0)
        self.e_valid = self.aptos * self.b_comp * self.b_val                                 # válidos esperados sob swing nulo
        self.e_comp = self.aptos * self.b_comp
        self.BV = self.e_valid[:, None] * bs                                                 # votos da base por bloco
        # perfil da seção e porte do município
        self.lp_s = np.log(bs[:, 0] / bs[:, 2]); self.ld_s = np.log(bs[:, 1] / bs[:, 2])
        mun_aptos = np.bincount(self.mun, self.aptos, self.nm); self.porte = np.log10(mun_aptos[self.mun]) - 4
        self.t = b.T_TOT.values
        # prior do intercepto nacional: swing nulo (0) ou pesquisa final (razões log da pesquisa - razões log da base nacional)
        self.beta0 = np.zeros(2)
        if prior_shares is not None:
            ps = np.array(prior_shares, float); bn = self.BV.sum(0)
            self.beta0 = np.array([np.log(ps[0] / ps[2]) - np.log(bn[0] / bn[2]), np.log(ps[1] / ps[2]) - np.log(bn[1] / bn[2])])
            print("prior do intercepto (swing PT, DIR):", self.beta0.round(3))
        self.final = self.V.sum(0) / self.valid.sum() * 100

    def X_of(self, lp, ld, porte):
        return np.c_[np.ones_like(lp), lp, ld, porte]

    def fit(self, Xm, Y, w, ok):
        """Coeficientes por UF (nu x 4 x 2) com hierarquia BR -> região -> UF e encolhimento EB."""
        k = Xm.shape[1]; coef_uf = np.zeros((self.nu, k, 2))
        X, Yo, W = Xm[ok], Y[ok], w[ok]; uf_m = self.mun_uf[ok]; reg_m = self.uf_reg[uf_m]
        for c in range(2):
            y = Yo[:, c]
            # Brasil: prior de swing nulo no intercepto, com peso prior_w (em votos)
            lam = np.zeros(k); lam[0] = self.prior_w
            if len(y) == 0:
                coef_uf[:, 0, c] = 0; continue
            b0 = np.zeros(k); b0[0] = self.beta0[c]
            b_br = wls_ridge(X, y, W, lam, b0)
            r = y - X @ b_br; sigma2 = max((W * r**2).sum() / max(W.sum(), 1), 1e-6)
            b_reg = np.tile(b_br, (self.nr, 1))
            for level, groups, parent in (("reg", reg_m, lambda g: b_br), ("uf", uf_m, lambda g: b_reg[self.uf_reg[g]])):
                ng = self.nr if level == "reg" else self.nu
                est, par, prec = [], [], []
                for g in range(ng):
                    s = groups == g
                    if s.sum() < 3: continue
                    Xg, yg, wg = X[s], y[s], W[s]
                    XtW = Xg.T * wg; A = XtW @ Xg + 1e-6 * np.eye(k)
                    bg = np.linalg.solve(A, XtW @ yg)
                    est.append(bg); par.append(parent(g)); prec.append(np.diag(np.linalg.inv(A)) * sigma2)
                if est:
                    est, par, prec = np.array(est), np.array(par), np.array(prec)
                    tau2 = np.maximum(((est - par) ** 2).mean(0) - prec.mean(0), self.tau_floor * np.ones(k))   # EB: var entre grupos
                    lam_g = sigma2 / tau2
                else:
                    lam_g = np.full(k, 1e12)
                out = np.zeros((ng, k))
                for g in range(ng):
                    s = groups == g; p = parent(g)
                    out[g] = wls_ridge(X[s], y[s], W[s], lam_g, p) if s.any() else p
                if level == "reg": b_reg = out
                else: coef_uf[:, :, c] = out
        return coef_uf

    def project(self, apur, boot_rng=None):
        """Projeção nacional (shares % dos válidos) dado o vetor booleano de seções apuradas."""
        m = self.mun
        O = np.stack([np.bincount(m, self.V[:, c] * apur, self.nm) for c in range(3)], 1)       # observado por município
        B = np.stack([np.bincount(m, self.BV[:, c] * apur, self.nm) for c in range(3)], 1)      # base das mesmas seções
        ov = O.sum(1)
        ok = ov >= self.min_valid
        Y = np.c_[np.log((O[:, 0] + EPS) / (O[:, 2] + EPS)) - np.log((B[:, 0] + EPS) / (B[:, 2] + EPS)),
                  np.log((O[:, 1] + EPS) / (O[:, 2] + EPS)) - np.log((B[:, 1] + EPS) / (B[:, 2] + EPS))]
        Bc = np.clip(B, EPS, None)
        Xm = self.X_of(np.log(Bc[:, 0] / Bc[:, 2]), np.log(Bc[:, 1] / Bc[:, 2]), np.log10(np.maximum(np.bincount(m, self.aptos, self.nm), 10)) - 4)
        w = np.minimum(ov, self.cap_w) ** self.w_pow
        if boot_rng is not None:                       # bootstrap de municípios: pesos multinomiais
            idx = np.where(ok)[0]; cnt = np.bincount(boot_rng.choice(idx, len(idx)), minlength=self.nm)
            w = w * cnt
        coef = self.fit(Xm, Y, w, ok & (w > 0))
        # swing previsto por seção pendente, pelo próprio perfil
        pend = ~apur
        Xs = self.X_of(self.lp_s[pend], self.ld_s[pend], self.porte[pend]); cu = coef[self.uf[pend]]
        yhat = np.einsum("ik,ikc->ic", Xs, cu)
        if self.mun_shrink > 0:                        # resíduo municipal encolhido (opcional)
            Xa = Xm; yh_m = np.einsum("ik,ikc->ic", Xa, coef[self.mun_uf]); res = (Y - yh_m) * (ov / (ov + self.mun_shrink))[:, None]
            res[~ok] = 0; yhat = yhat + res[m[pend]]
        a = self.lp_s[pend] + yhat[:, 0]; d = self.ld_s[pend] + yhat[:, 1]
        ea, ed = np.exp(a), np.exp(d); den = 1 + ea + ed
        sh = np.c_[ea / den, ed / den, 1 / den]
        # comparecimento e válidos: ajuste por UF (observado / esperado nas seções apuradas), encolhido ao nacional
        u = self.uf
        oc, ec = np.bincount(u, self.comp * apur, self.nu), np.bincount(u, self.e_comp * apur, self.nu)
        ovl, evl = np.bincount(u, self.valid * apur, self.nu), np.bincount(u, self.e_valid * apur, self.nu)
        K = 50_000.0
        nat_c = (oc.sum() + K) / (ec.sum() + K); nat_v = (ovl.sum() + K) / (evl.sum() + K)
        adj_c = (oc + K * nat_c) / (ec + K); adj_v = (ovl + K * nat_v) / (evl + K)
        pv = self.aptos[pend] * np.clip(self.b_comp[pend] * adj_c[u[pend]], 0.3, 1.0) * np.clip(self.b_val[pend] * adj_v[u[pend]], 0.5, 1.0)
        tot = O.sum(0) + (pv[:, None] * sh).sum(0)
        return tot / tot.sum() * 100, O.sum(0) / max(ov.sum(), 1) * 100

    def run(self, grid, boot=0, boot_at=(), seed=1):
        order = np.argsort(self.t); cum = np.cumsum(self.aptos[order]) / self.aptos.sum()
        rows = []; rng = np.random.default_rng(seed)
        for g in grid:
            k = np.searchsorted(cum, g / 100);
            if k >= self.n: k = self.n - 1
            t = self.t[order[k]]; apur = self.t <= t
            pct = self.aptos[apur].sum() / self.aptos.sum() * 100
            proj, obs = self.project(apur)
            row = dict(t=pd.Timestamp(t).strftime("%H:%M"), pct=pct, obs_PT=obs[0], obs_DIR=obs[1], proj_PT=proj[0], proj_DIR=proj[1], proj_OUT=proj[2])
            if boot and any(abs(g - a) < 1e-9 for a in boot_at):
                reps = np.array([self.project(apur, boot_rng=rng)[0] for _ in range(boot)])
                lo, hi = np.percentile(reps, [5, 95], axis=0)
                row.update(lo_PT=lo[0], hi_PT=hi[0], lo_DIR=lo[1], hi_DIR=hi[1], p2t=(reps.max(1) < 50).mean())
            rows.append(row)
        return pd.DataFrame(rows)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("--out", default=None)
    ap.add_argument("--boot", type=int, default=0); ap.add_argument("--mun-shrink", type=float, default=0.0)
    ap.add_argument("--prior-w", type=float, default=20_000); ap.add_argument("--cap-w", type=float, default=np.inf)
    ap.add_argument("--min-valid", type=int, default=30); ap.add_argument("--tau-floor", type=float, default=1e-4); ap.add_argument("--w-pow", type=float, default=1.0); ap.add_argument("--prior-shares", default=None, help="PT,DIR,OUT em %% dos válidos (pesquisa final)")
    a = ap.parse_args(); t0 = time.time()
    base = pd.read_parquet(a.base)
    base = base[base.T_TOT.notna()]
    R = Replay(base, prior_w=a.prior_w, mun_shrink=a.mun_shrink, min_valid=a.min_valid, cap_w=a.cap_w, tau_floor=a.tau_floor, w_pow=a.w_pow, prior_shares=[float(x) for x in a.prior_shares.split(",")] if a.prior_shares else None)
    print(f"final real: PT {R.final[0]:.2f}  DIR {R.final[1]:.2f}  OUT {R.final[2]:.2f}  ({R.n} seções)")
    grid = list(np.round(np.arange(0.1, 1.0, 0.1), 1)) + list(np.round(np.arange(1.0, 10.0, 0.5), 1)) + list(range(10, 100, 5)) + [99]
    boot_at = (0.5, 1.0, 2.0, 5.0, 10, 25, 50, 75)
    df = R.run(grid, boot=a.boot, boot_at=boot_at)
    df["err_PT"] = df.proj_PT - R.final[0]; df["err_DIR"] = df.proj_DIR - R.final[1]
    df["err_obs_PT"] = df.obs_PT - R.final[0]; df["err_margem"] = (df.proj_PT - df.proj_DIR) - (R.final[0] - R.final[1])
    pd.set_option("display.width", 200); pd.set_option("display.max_rows", 200)
    cols = ["t", "pct", "obs_PT", "obs_DIR", "proj_PT", "proj_DIR", "err_PT", "err_DIR", "err_margem"] + [c for c in ("lo_PT", "hi_PT", "lo_DIR", "hi_DIR", "p2t") if c in df]
    print(df[cols].round(2).to_string(index=False))
    ok = (df.err_PT.abs() < 0.5) & (df.err_DIR.abs() < 0.5)
    print("\nerro < 0,5 pp em ambos a partir de (sustentado):", df.pct[ok[::-1].cummin()[::-1]].min() if ok.any() else None)
    print(f"tempo {time.time() - t0:.0f}s")
    if a.out: df.to_csv(a.out, index=False)

if __name__ == "__main__":
    main()
