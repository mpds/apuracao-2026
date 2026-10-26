"""Experimentos do modelo do 2º turno em duas noites reais: 2018 (Haddad 13 x Bolsonaro 17) e 2022 (Lula 13 x Bolsonaro 22).

Uso:
  python -I replay/exp2t.py variantes data_tse/parquet data_tse/exp                 # erro por % apurado de cada variante
  python -I replay/exp2t.py boot data_tse/parquet data_tse/exp --reps 60 --variantes base,stack_best
"""
import sys, os, time, argparse
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from model import REGIAO, wls_ridge, EPS
from model2t import build_base_2t

REGS = ["N", "NE", "CO", "SE", "S", "ZZ"]
NOITES = {2018: 17, 2022: 22}   # ano -> número do candidato da direita

class Noite:
    def __init__(self, pq, ano, cand_dir, cache_dir=None):
        cache = f"{cache_dir}/base2t_{ano}.parquet" if cache_dir else None
        if cache and os.path.exists(cache): b = pd.read_parquet(cache)
        else:
            b = build_base_2t(pq, str(ano), f"{ano}_t2", cand_pt=13, cand_dir=cand_dir)
            if cache: b.to_parquet(cache, index=False)
        self.ano, self.n = ano, len(b)
        self.mun, self.mun_names = pd.factorize(b.SG_UF + "-" + b.CD_MUNICIPIO.astype(str)); self.nm = len(self.mun_names)
        self.uf_names = sorted(set(b.SG_UF)); ufi = {u: i for i, u in enumerate(self.uf_names)}
        self.uf = np.array([ufi[u] for u in b.SG_UF]); self.nu = len(self.uf_names)
        self.uf_reg = np.array([REGS.index(REGIAO[u]) for u in self.uf_names]); self.nr = len(REGS)
        self.mun_uf = np.zeros(self.nm, int); self.mun_uf[self.mun] = self.uf
        self.aptos = b.QT_APTOS.values.astype(float); self.comp = b.QT_COMPARECIMENTO.values.astype(float)
        self.V = np.c_[b.PT.values, b.DIR.values].astype(float); self.valid = self.V.sum(1)
        self.B = np.c_[b.PT1.values, b.DIR1.values].astype(float)
        self.out1 = b.OUT1.values / np.maximum(b.VALIDOS1.values, 1)
        self.lp1 = np.log((self.B[:, 0] + EPS) / (self.B[:, 1] + EPS))
        self.comp1 = np.clip(b.QT_COMPARECIMENTO1.values / np.maximum(b.QT_APTOS1.values, 1), 0.4, 0.98)
        self.val1 = np.clip(b.VALIDOS1.values / np.maximum(b.QT_COMPARECIMENTO1.values, 1), 0.7, 1.0)
        self.e_comp = self.aptos * self.comp1; self.e_valid = self.e_comp * self.val1
        self.mun_aptos = np.bincount(self.mun, self.aptos, self.nm); self.porte = np.log10(self.mun_aptos[self.mun]) - 4
        self.porte_m = np.log10(np.maximum(self.mun_aptos, 10)) - 4
        self.sec_aptos = np.log10(np.maximum(self.aptos, 10)) - 2.5
        wts = self.B.sum(1)
        self.sd = {k: float(np.sqrt(np.average((v - np.average(v, weights=wts)) ** 2, weights=wts))) for k, v in (("lp1", self.lp1), ("out1", self.out1), ("porte", self.porte), ("sec", self.sec_aptos))}
        self.poll = {2018: 45.0, 2022: 52.0}.get(ano)      # Datafolha final, % válidos do candidato do PT
        self.t = b.T_TOT.values; self.final = self.V.sum(0) / self.valid.sum() * 100
        self.order = np.argsort(self.t); self.cum = np.cumsum(self.aptos[self.order]) / self.aptos.sum()
        self.base_share = self.B[:, 0].sum() / self.B.sum() * 100
    def apur_at(self, pct):
        k = min(np.searchsorted(self.cum, pct / 100), self.n - 1); return self.t <= self.t[self.order[k]]

class Modelo:
    """Swing hierárquico BR -> região -> UF. Variantes: covariáveis, resíduo municipal (mun_k), pesos, bootstrap por município ou UF."""
    def __init__(self, cov=("lp1", "out1", "porte"), mun_k=0.0, w_pow=1.0, cap_w=np.inf, prior_w=20_000, prior_share=None,
                 tau_floor=1e-4, min_valid=30, boot="mun", niveis=("reg", "uf"), slope_w=0.0, std=False, prior_poll=False, group_slopes="eb", group_slope_w=0.0):
        self.cov, self.mun_k, self.w_pow, self.cap_w, self.prior_w, self.prior_share = tuple(cov), mun_k, w_pow, cap_w, prior_w, prior_share
        self.tau_floor, self.min_valid, self.boot, self.niveis = tau_floor, min_valid, boot, niveis
        self.slope_w, self.std, self.prior_poll, self.group_slopes, self.group_slope_w = slope_w, std, prior_poll, group_slopes, group_slope_w

    def fit(self, N, X, y, w, ok, beta0):
        k = X.shape[1]; X, y, W = X[ok], y[ok], w[ok]; uf_m = N.mun_uf[ok]; reg_m = N.uf_reg[uf_m]
        lam = np.zeros(k); lam[0] = self.prior_w; lam[1:] = self.slope_w; b0 = np.zeros(k); b0[0] = beta0
        if len(y) == 0: return np.tile(b0, (N.nu, 1)), b0, 0.0
        b_br = wls_ridge(X, y, W, lam, b0); r = y - X @ b_br; sigma2 = max((W * r**2).sum() / max(W.sum(), 1), 1e-6)
        b_reg = np.tile(b_br, (N.nr, 1)); coef = np.tile(b_br, (N.nu, 1))
        for level, groups, parent in (("reg", reg_m, lambda g: b_br), ("uf", uf_m, lambda g: b_reg[N.uf_reg[g]])):
            if level not in self.niveis: continue
            ng = N.nr if level == "reg" else N.nu; est, par, prec = [], [], []
            if self.group_slopes == "int":
                resid = y - X[:, 1:] @ b_br[1:] if k > 1 else y
                for g in range(ng):
                    s = groups == g
                    if s.sum() < 3: continue
                    Wg = W[s].sum(); est.append((W[s] * resid[s]).sum() / Wg); par.append(parent(g)[0]); prec.append(sigma2 / Wg)
                if est:
                    est, par, prec = map(np.array, (est, par, prec)); lam0 = sigma2 / max(((est - par) ** 2).mean() - prec.mean(), self.tau_floor)
                else: lam0 = 1e12
                lam0 = max(lam0, self.group_slope_w)
                out = np.zeros((ng, k))
                for g in range(ng):
                    s = groups == g; p = parent(g); out[g] = p.copy()
                    if s.any(): Wg = W[s].sum(); out[g, 0] = ((W[s] * resid[s]).sum() + lam0 * p[0]) / (Wg + lam0)
                if level == "reg": b_reg = out
                else: coef = out
                continue
            for g in range(ng):
                s = groups == g
                if s.sum() < 3: continue
                XtW = X[s].T * W[s]; A = XtW @ X[s] + 1e-6 * np.eye(k)
                est.append(np.linalg.solve(A, XtW @ y[s])); par.append(parent(g)); prec.append(np.diag(np.linalg.inv(A)) * sigma2)
            if est:
                est, par, prec = map(np.array, (est, par, prec))
                lam_g = sigma2 / np.maximum(((est - par) ** 2).mean(0) - prec.mean(0), self.tau_floor)
            else: lam_g = np.full(k, 1e12)
            if k > 1: lam_g[1:] = np.maximum(lam_g[1:], self.group_slope_w)
            out = np.zeros((ng, k))
            for g in range(ng):
                s = groups == g; p = parent(g); out[g] = wls_ridge(X[s], y[s], W[s], lam_g, p) if s.any() else p
            if level == "reg": b_reg = out
            else: coef = out
        return coef, b_br, sigma2

    # ---- peças reutilizáveis (usadas pelo ensemble) ----
    def dados(self, N, apur):
        m = N.mun
        O = np.c_[np.bincount(m, N.V[:, 0] * apur, N.nm), np.bincount(m, N.V[:, 1] * apur, N.nm)]
        B = np.c_[np.bincount(m, N.B[:, 0] * apur, N.nm), np.bincount(m, N.B[:, 1] * apur, N.nm)]
        bo = np.bincount(m, N.out1 * N.B.sum(1) * apur, N.nm) / np.maximum(B.sum(1), 1)
        ov = O.sum(1); ok = ov >= self.min_valid
        y = np.log((O[:, 0] + EPS) / (O[:, 1] + EPS)) - np.log((B[:, 0] + EPS) / (B[:, 1] + EPS))
        cm = {"lp1": np.log((B[:, 0] + EPS) / (B[:, 1] + EPS)), "out1": bo, "porte": N.porte_m,
              "sec": np.bincount(m, N.sec_aptos * N.aptos * apur, N.nm) / np.maximum(np.bincount(m, N.aptos * apur, N.nm), 1)}
        sc = {c: (N.sd[c] if self.std else 1.0) for c in self.cov}
        X = np.c_[np.ones(N.nm), *[cm[c] / sc[c] for c in self.cov]] if self.cov else np.ones((N.nm, 1))
        pend = ~apur
        cs = {"lp1": N.lp1[pend], "out1": N.out1[pend], "porte": N.porte[pend], "sec": N.sec_aptos[pend]}
        Xs = np.c_[np.ones(pend.sum()), *[cs[c] / sc[c] for c in self.cov]] if self.cov else np.ones((pend.sum(), 1))
        beta0 = 0.0; ps = N.poll if self.prior_poll else self.prior_share
        if ps is not None:
            bn = N.B.sum(0); beta0 = np.log(ps / (100 - ps)) - np.log(bn[0] / bn[1])
        return dict(O=O, B=B, ov=ov, ok=ok, y=y, X=X, Xs=Xs, pend=pend, beta0=beta0)

    def pesos(self, N, D, boot_rng=None):
        ov, ok = D["ov"], D["ok"]; w = np.minimum(ov, self.cap_w) ** self.w_pow
        if boot_rng is not None:
            if self.boot == "mun":
                idx = np.where(ok)[0]; w = w * np.bincount(boot_rng.choice(idx, len(idx)), minlength=N.nm)
            else:
                ufs = np.unique(N.mun_uf[ok]); cnt = np.bincount(boot_rng.choice(ufs, len(ufs)), minlength=N.nu); w = w * cnt[N.mun_uf]
        return w

    def coef(self, N, D, w):
        return self.fit(N, D["X"], D["y"], w, D["ok"] & (w > 0), D["beta0"])

    def yhat_pend(self, N, D, coef):
        pend = D["pend"]; yhat = np.einsum("ik,ik->i", D["Xs"], coef[N.uf[pend]])
        if self.mun_k > 0:
            ov, ok = D["ov"], D["ok"]
            res = (D["y"] - np.einsum("ik,ik->i", D["X"], coef[N.mun_uf])) * (ov / (ov + self.mun_k)); res[~ok] = 0.0
            yhat = yhat + res[N.mun[pend]]
        return yhat

    def totais(self, N, D, apur, yhat):
        pend = D["pend"]; O = D["O"]
        sh = 1 / (1 + np.exp(-(N.lp1[pend] + yhat)))
        u = N.uf; K = 50_000.0
        oc, ec = np.bincount(u, N.comp * apur, N.nu), np.bincount(u, N.e_comp * apur, N.nu)
        ovl, evl = np.bincount(u, N.valid * apur, N.nu), np.bincount(u, N.e_valid * apur, N.nu)
        nat_c = (oc.sum() + K) / (ec.sum() + K); nat_v = (ovl.sum() + K) / (evl.sum() + K)
        adj_c = (oc + K * nat_c) / (ec + K); adj_v = (ovl + K * nat_v) / (evl + K)
        pv = N.aptos[pend] * np.clip(N.comp1[pend] * adj_c[u[pend]], 0.3, 1.0) * np.clip(N.val1[pend] * adj_v[u[pend]], 0.5, 1.0)
        tot = O.sum(0) + np.array([(pv * sh).sum(), (pv * (1 - sh)).sum()])
        return tot[0] / tot.sum() * 100

    def project(self, N, apur, boot_rng=None, detalhe=False):
        D = self.dados(N, apur); w = self.pesos(N, D, boot_rng); coef, b_br, sigma2 = self.coef(N, D, w)
        p = self.totais(N, D, apur, self.yhat_pend(N, D, coef))
        if not detalhe: return p
        ok, ov = D["ok"], D["ov"]
        return p, dict(coef_br=b_br, sigma2=sigma2, n_ok=int(ok.sum()), ufs_ok=int(len(np.unique(N.mun_uf[ok]))), obs=D["O"].sum(0)[0] / max(ov.sum(), 1) * 100)

class Stack:
    """Ensemble: média (em logit) das previsões de swing dos membros, com pesos por validação cruzada deixando uma UF de fora."""
    def __init__(self, membros, modo="best", boot="mun", temp=1.0):
        self.membros = [Modelo(**{**VARIANTES[m], "boot": boot}) for m in membros]; self.nomes = list(membros); self.modo, self.temp = modo, temp
    def cv(self, N, D, M, w):
        ok, ov, y, X = D["ok"], D["ov"], D["y"], D["X"]; sse = 0.0; sw = 0.0
        for u in np.unique(N.mun_uf[ok & (w > 0)]):
            held = ok & (N.mun_uf == u) & (w > 0); wu = w.copy(); wu[N.mun_uf == u] = 0
            if not (ok & (wu > 0)).any(): continue
            coef, _, _ = M.coef(N, D, wu); pred = X[held] @ coef[u]
            sse += (ov[held] * (y[held] - pred) ** 2).sum(); sw += ov[held].sum()
        return sse / max(sw, 1e-9)
    def project(self, N, apur, boot_rng=None, detalhe=False):
        Ds = [M.dados(N, apur) for M in self.membros]; w = self.membros[0].pesos(N, Ds[0], boot_rng)
        mse = np.array([self.cv(N, D, M, w) for D, M in zip(Ds, self.membros)])
        if self.modo == "best": a = (mse == mse.min()).astype(float)
        elif self.modo == "inv2": a = 1 / np.maximum(mse, 1e-12) ** 2
        else: a = np.exp(-(mse - mse.min()) / max(mse.min(), 1e-12) / self.temp * 10)
        a = a / a.sum()
        yh = sum(ak * M.yhat_pend(N, D, M.coef(N, D, w)[0]) for ak, D, M in zip(a, Ds, self.membros))
        p = self.membros[0].totais(N, Ds[0], apur, yh)
        if not detalhe: return p
        ok, ov = Ds[0]["ok"], Ds[0]["ov"]
        return p, dict(coef_br=np.zeros(4), sigma2=0, n_ok=int(ok.sum()), ufs_ok=int(len(np.unique(N.mun_uf[ok]))), obs=Ds[0]["O"].sum(0)[0] / max(ov.sum(), 1) * 100, pesos=dict(zip(self.nomes, a.round(2))), mse=dict(zip(self.nomes, mse.round(5))))

VARIANTES = {
    "base":        dict(),
    "int":         dict(cov=()),
    "lp":          dict(cov=("lp1",)),
    "lp_out":      dict(cov=("lp1", "out1")),
    "lp_porte":    dict(cov=("lp1", "porte")),
    "out":         dict(cov=("out1",)),
    "base_sec":    dict(cov=("lp1", "out1", "porte", "sec")),
    "base_cap50k": dict(cap_w=50_000),
    "base_tau1e-2": dict(tau_floor=1e-2),
    "r3e5":        dict(std=True, slope_w=3e5),
    "ri":          dict(group_slopes="int"),
    "ri_lp_out":   dict(group_slopes="int", cov=("lp1", "out1")),
}
STACKS = {
    "stack_best":   dict(membros=("base", "lp", "lp_out", "int"), modo="best"),
    "stack_inv2":   dict(membros=("base", "lp", "lp_out", "int"), modo="inv2"),
    "stack_soft":   dict(membros=("base", "lp", "lp_out", "int"), modo="soft"),
    "stack6_best":  dict(membros=("base", "lp", "lp_out", "lp_porte", "int", "ri"), modo="best"),
    "stack6_inv2":  dict(membros=("base", "lp", "lp_out", "lp_porte", "int", "ri"), modo="inv2"),
    "stack3_best":  dict(membros=("base", "lp_out", "int"), modo="best"),
    "stack_bl_best": dict(membros=("base", "lp"), modo="best"),
    "stack_bl_inv2": dict(membros=("base", "lp"), modo="inv2"),
}
def modelo(nome, **kw):
    return Stack(**{**STACKS[nome], **kw}) if nome in STACKS else Modelo(**{**VARIANTES[nome], **kw})

GRID = [0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10, 12, 15, 20, 25, 30, 40, 50, 60, 70, 80, 90, 95]

def carregar(pq, cache):
    return {ano: Noite(pq, ano, cd, cache) for ano, cd in NOITES.items()}

def fase_variantes(noites, out, nomes):
    rows = []
    for ano, N in noites.items():
        print(f"{ano}: final PT {N.final[0]:.2f} | base 1T PT {N.base_share:.2f} | {N.n} seções, {N.nm} mun", flush=True)
        for g in GRID:
            apur = N.apur_at(g); pct = N.aptos[apur].sum() / N.aptos.sum() * 100
            for nome in nomes:
                t0 = time.time(); p, d = modelo(nome).project(N, apur, detalhe=True)
                rows.append(dict(ano=ano, grid=g, pct=pct, variante=nome, proj=p, err=p - N.final[0], obs=d["obs"], n_ok=d["n_ok"], ufs_ok=d["ufs_ok"], ms=(time.time() - t0) * 1000, pesos=str(d.get("pesos", ""))))
        print(f"  {ano} ok", flush=True)
    df = pd.DataFrame(rows); df.to_csv(f"{out}/variantes_stack.csv", index=False)
    resumo(df)
    for ano in noites:
        s = df[(df.ano == ano) & df.variante.str.startswith("stack")]
        print(f"\n{ano} pesos do ensemble por % apurado:"); print(s.pivot(index="grid", columns="variante", values="pesos").to_string())

def resumo(df):
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 50); pd.set_option("display.max_rows", 500)
    faixas = [(1, 3), (3, 10), (10, 30), (30, 100)]; out = []
    for (ano, v), g in df.groupby(["ano", "variante"]):
        r = dict(ano=ano, variante=v)
        for lo, hi in faixas:
            s = g[(g.grid >= lo) & (g.grid < hi)]; r[f"mae_{lo}-{hi}"] = s.err.abs().mean(); r[f"max_{lo}-{hi}"] = s.err.abs().max()
        ok = g.sort_values("grid"); sus = ok.err.abs().lt(0.5)[::-1].cummin()[::-1]; r["sust<0.5"] = ok.grid[sus].min() if sus.any() else np.nan
        r["ms"] = g.ms.mean(); out.append(r)
    res = pd.DataFrame(out)
    piv = res.pivot(index="variante", columns="ano", values=["mae_1-3", "mae_3-10", "mae_10-30", "max_3-10", "sust<0.5", "ms"]); print("\n", piv.round(3).to_string())
    return res

def fase_boot(noites, out, reps, nomes, pts=(0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10, 15, 20, 30, 50, 70)):
    rows = []
    for ano, N in noites.items():
        for g in pts:
            apur = N.apur_at(g); pct = N.aptos[apur].sum() / N.aptos.sum() * 100
            for v in nomes:
                for lvl in ("mun", "uf"):
                    M = modelo(v, boot=lvl); rng = np.random.default_rng(1)
                    p = M.project(N, apur); r = np.array([M.project(N, apur, boot_rng=rng) for _ in range(reps)])
                    lo, hi = np.percentile(r, [5, 95]); half = (hi - lo) / 2; sd = r.std()
                    rows.append(dict(ano=ano, grid=g, pct=pct, variante=v, boot=lvl, proj=p, err=p - N.final[0], half=half, sd=sd, z=(p - N.final[0]) / max(sd, 1e-6), cobre=(lo <= N.final[0] <= hi)))
            print(f"  {ano} {g}% ok", flush=True)
    df = pd.DataFrame(rows); df.to_csv(f"{out}/boot_{'_'.join(nomes)}.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
    print(df.round(3).to_string(index=False))
    for (v, lvl), g in df.groupby(["variante", "boot"]):
        print(f"{v:12s} {lvl}: cobertura {g.cobre.mean():.2f} | |z| q90 {np.percentile(g.z.abs(), 90):.2f} | |z| mediana {np.median(g.z.abs()):.2f}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("fase"); ap.add_argument("pq"); ap.add_argument("out"); ap.add_argument("--reps", type=int, default=60)
    ap.add_argument("--variantes", default=None)
    a = ap.parse_args(); t0 = time.time()
    noites = carregar(a.pq, a.out)
    nomes = a.variantes.split(",") if a.variantes else list(VARIANTES) + list(STACKS)
    if a.fase == "variantes": fase_variantes(noites, a.out, nomes)
    elif a.fase == "boot": fase_boot(noites, a.out, a.reps, nomes)
    print(f"tempo {time.time() - t0:.0f}s")
