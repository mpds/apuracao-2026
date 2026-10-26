"""Modelo do 2º turno para a noite: recebe o que a divulgação do TSE expõe (quais seções já totalizaram e os totais por
município) e devolve a projeção. Mesma matemática de replay/model2t.py, sem acesso ao voto real por seção.

Base = 1º turno por seção (votacao_<t1>/detalhe_<t1>.parquet). Ordem das seções fixa (índice por chave UF-mun-zona-seção).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "replay"))
import numpy as np, pandas as pd
from math import erf, sqrt
from model import REGIAO, wls_ridge, EPS

def Phi(z): return 0.5 * (1 + erf(z / sqrt(2)))

KEY = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]

def carregar_base_1t(pq, t1="2026", cand_pt=13, cand_dir=22):
    v = pd.read_parquet(f"{pq}/votacao_{t1}.parquet"); v = v[~v.NR_VOTAVEL.isin([95, 96])]
    v["bloco"] = np.where(v.NR_VOTAVEL == cand_pt, "PT1", np.where(v.NR_VOTAVEL == cand_dir, "DIR1", "OUT1"))
    w = v.pivot_table(index=KEY, columns="bloco", values="QT_VOTOS", aggfunc="sum", fill_value=0).reset_index()
    d = pd.read_parquet(f"{pq}/detalhe_{t1}.parquet")[KEY + ["QT_APTOS", "QT_COMPARECIMENTO", "NR_LOCAL_VOTACAO", "QT_VOTOS_BRANCOS", "QT_VOTOS_NULOS"]]
    b = d.merge(w, on=KEY, how="left").fillna({"PT1": 0, "DIR1": 0, "OUT1": 0})
    b["VALIDOS1"] = b.PT1 + b.DIR1 + b.OUT1
    b = b[b.VALIDOS1 > 0].reset_index(drop=True)
    return b.rename(columns={"QT_APTOS": "QT_APTOS1", "QT_COMPARECIMENTO": "QT_COMPARECIMENTO1", "QT_VOTOS_BRANCOS": "VB1", "QT_VOTOS_NULOS": "VN1"})

class ModeloVivo:
    def __init__(self, b, prior_w=20_000, prior_share_pt=None, min_valid=30, tau_floor=1e-4, calib=1.3):
        self.b = b; self.n = len(b); self.prior_w, self.min_valid, self.tau_floor, self.calib = prior_w, min_valid, tau_floor, calib
        self.idx = {k: i for i, k in enumerate(zip(b.SG_UF, b.CD_MUNICIPIO, b.NR_ZONA, b.NR_SECAO))}
        self.mun_key = (b.SG_UF + "-" + b.CD_MUNICIPIO.astype(str).str.zfill(5)).values
        self.mun, self.mun_names = pd.factorize(self.mun_key); self.nm = len(self.mun_names)
        self.mun_idx = {k: i for i, k in enumerate(self.mun_names)}
        self.uf_names = sorted(set(b.SG_UF)); ufi = {u: i for i, u in enumerate(self.uf_names)}
        self.uf = np.array([ufi[u] for u in b.SG_UF]); self.nu = len(self.uf_names)
        self.uf_reg = np.array([["N", "NE", "CO", "SE", "S", "ZZ"].index(REGIAO[u]) for u in self.uf_names]); self.nr = 6
        self.mun_uf = np.zeros(self.nm, int); self.mun_uf[self.mun] = self.uf
        self.aptos = b.QT_APTOS1.values.astype(float)                      # eleitorado da seção (1T como proxy)
        self.B = np.c_[b.PT1.values, b.DIR1.values].astype(float); self.out1 = b.OUT1.values / b.VALIDOS1.values
        self.lp1 = np.log((self.B[:, 0] + EPS) / (self.B[:, 1] + EPS))
        self.comp1 = np.clip(b.QT_COMPARECIMENTO1.values / np.maximum(self.aptos, 1), 0.4, 0.98)
        self.val1 = np.clip(b.VALIDOS1.values / np.maximum(b.QT_COMPARECIMENTO1.values, 1), 0.7, 1.0)
        self.e_comp = self.aptos * self.comp1; self.e_valid = self.e_comp * self.val1
        self.porte = np.log10(np.bincount(self.mun, self.aptos, self.nm)[self.mun]) - 4
        self.mun_aptos = np.bincount(self.mun, self.aptos, self.nm)
        # totais do município inteiro (usados quando o arquivo municipal está à frente da lista de seções)
        self.B_mun = np.c_[np.bincount(self.mun, self.B[:, 0], self.nm), np.bincount(self.mun, self.B[:, 1], self.nm)]
        self.bon_mun = np.bincount(self.mun, self.out1 * self.B.sum(1), self.nm)
        self.ecomp_mun = np.bincount(self.mun, self.e_comp, self.nm); self.evalid_mun = np.bincount(self.mun, self.e_valid, self.nm)
        self.beta0 = 0.0
        if prior_share_pt is not None:
            bn = self.B.sum(0); self.beta0 = np.log(prior_share_pt / (100 - prior_share_pt)) - np.log(bn[0] / bn[1])

    def fit(self, X, y, w, ok):
        k = X.shape[1]; X, y, W = X[ok], y[ok], w[ok]; uf_m = self.mun_uf[ok]; reg_m = self.uf_reg[uf_m]
        lam = np.zeros(k); lam[0] = self.prior_w; b0 = np.zeros(k); b0[0] = self.beta0
        if len(y) == 0: return np.tile(b0, (self.nu, 1)), b0
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
        return coef, b_br

    def projetar(self, apur, O, esa, comp_m, valid_m, boot_rng=None, boot_nivel="mun"):
        """apur: bool por seção (totalizada segundo a lista). O: (nm,2) votos PT/DIR por município; esa: eleitorado
        apurado por município segundo o arquivo; comp_m, valid_m: comparecimento e válidos apurados por município.
        Se o arquivo municipal está à frente da lista (esa > eleitorado marcado), o excedente é tratado como amostra
        proporcional das seções não marcadas do município (base do swing, comparecimento esperado e pendência).
        boot_nivel: reamostra municípios ("mun") ou UFs inteiras ("uf")."""
        m = self.mun; Bs = self.B.sum(1)
        Bm = np.c_[np.bincount(m, self.B[:, 0] * apur, self.nm), np.bincount(m, self.B[:, 1] * apur, self.nm)]
        aptos_lista = np.bincount(m, self.aptos * apur, self.nm); au = np.maximum(self.mun_aptos - aptos_lista, 0)
        extra = np.clip(esa - aptos_lista, 0, au); g = extra / np.maximum(au, 1)          # fração da parte não marcada já apurada
        down = np.where((aptos_lista > 0) & (esa > 0) & (esa < aptos_lista), esa / np.maximum(aptos_lista, 1), 1.0); down = np.clip(down, 0.5, 1.0)
        B = Bm * down[:, None] + (self.B_mun - Bm) * g[:, None]
        bon_m = np.bincount(m, self.out1 * Bs * apur, self.nm); bo = (bon_m * down + (self.bon_mun - bon_m) * g) / np.maximum(B.sum(1), 1)
        ov = O.sum(1); ok = (ov >= self.min_valid) & (B.sum(1) > 0)
        y = np.log((O[:, 0] + EPS) / (O[:, 1] + EPS)) - np.log((B[:, 0] + EPS) / (B[:, 1] + EPS))
        X = np.c_[np.ones(self.nm), np.log((B[:, 0] + EPS) / (B[:, 1] + EPS)), bo, np.log10(np.maximum(self.mun_aptos, 10)) - 4]
        w = ov.copy()
        if boot_rng is not None:
            idx = np.where(ok)[0]
            if len(idx) and boot_nivel == "uf":
                ufs = np.unique(self.mun_uf[idx]); cnt = np.bincount(boot_rng.choice(ufs, len(ufs)), minlength=self.nu); w = w * cnt[self.mun_uf]
            elif len(idx): w = w * np.bincount(boot_rng.choice(idx, len(idx)), minlength=self.nm)
        coef, b_br = self.fit(X, y, w, ok & (w > 0))
        pend = ~apur; fp = 1 - g[m[pend]]                                                 # parte das seções não marcadas ainda pendente
        Xs = np.c_[np.ones(pend.sum()), self.lp1[pend], self.out1[pend], self.porte[pend]]
        yhat = np.einsum("ik,ik->i", Xs, coef[self.uf[pend]]); sh = 1 / (1 + np.exp(-np.clip(self.lp1[pend] + yhat, -30, 30)))
        # comparecimento e válidos por UF: observado (arquivos municipais) / esperado pelo 1T na parte apurada
        u = self.uf; K = 50_000.0
        ecm = np.bincount(m, self.e_comp * apur, self.nm); evm = np.bincount(m, self.e_valid * apur, self.nm)
        ec = np.bincount(self.mun_uf, ecm * down + (self.ecomp_mun - ecm) * g, self.nu); evl = np.bincount(self.mun_uf, evm * down + (self.evalid_mun - evm) * g, self.nu)
        oc = np.bincount(self.mun_uf, comp_m, self.nu); ovl = np.bincount(self.mun_uf, valid_m, self.nu)
        nat_c = (oc.sum() + K) / (ec.sum() + K); nat_v = (ovl.sum() + K) / (evl.sum() + K)
        adj_c = (oc + K * nat_c) / (ec + K); adj_v = (ovl + K * nat_v) / (evl + K)
        pc = fp * self.aptos[pend] * np.clip(self.comp1[pend] * adj_c[u[pend]], 0.3, 1.0)
        pv = pc * np.clip(self.val1[pend] * adj_v[u[pend]], 0.5, 1.0)
        pend_votes = np.array([(pv * sh).sum(), (pv * (1 - sh)).sum()])
        tot = O.sum(0) + pend_votes
        # por UF: projeção e apurado
        pu = np.bincount(u[pend], pv * sh, self.nu), np.bincount(u[pend], pv * (1 - sh), self.nu)
        Ou = np.c_[np.bincount(self.mun_uf, O[:, 0], self.nu), np.bincount(self.mun_uf, O[:, 1], self.nu)]
        tot_uf = Ou + np.c_[pu[0], pu[1]]
        ea = aptos_lista * down + extra                                                     # eleitorado apurado efetivo por município
        return dict(proj=tot / tot.sum() * 100, apurado=O.sum(0) / max(ov.sum(), 1) * 100, tot=tot, obs=O.sum(0),
                    pend_aptos=self.aptos.sum() - ea.sum(), pct=ea.sum() / self.aptos.sum() * 100,
                    coef_br=b_br, coef_uf=coef, uf_proj=tot_uf[:, 0] / np.maximum(tot_uf.sum(1), 1) * 100,
                    uf_apur=Ou[:, 0] / np.maximum(Ou.sum(1), 1) * 100, uf_pct=np.bincount(self.mun_uf, ea, self.nu) / np.bincount(u, self.aptos, self.nu) * 100,
                    uf_1t=np.bincount(u, self.B[:, 0], self.nu) / np.bincount(u, self.B.sum(1), self.nu) * 100,
                    n_ok=int(ok.sum()), ufs_ok=int(len(np.unique(self.mun_uf[ok]))) if ok.any() else 0,
                    comp_proj=(comp_m.sum() + pc.sum()) / self.aptos.sum() * 100,
                    adj_c=adj_c, adj_v=adj_v)

    def ciclo(self, apur, O, esa, comp_m, valid_m, boot=150, boot_uf=60, seed=None):
        """Incerteza = bootstrap de municípios (x calib) combinado com bootstrap de UFs inteiras ponderado pela fração do
        eleitorado ainda pendente: sd² = (calib·sd_mun)² + (sd_uf·pendente)². Calibrado nos replays de 2018 e 2022
        (cobertura 100% em 26 pontos, |z| q90 = 1,05). Faixa de 90% = ±1,645 sd; P(vitória) = Phi((proj-50)/sd)."""
        r = self.projetar(apur, O, esa, comp_m, valid_m)
        rng = np.random.default_rng(seed)
        r["sd"] = r["sd_mun"] = r["sd_uf"] = np.nan
        if boot and r["n_ok"] >= 20 and r["ufs_ok"] >= 3:
            med = r["proj"][0]
            reps_m = np.array([self.projetar(apur, O, esa, comp_m, valid_m, boot_rng=rng, boot_nivel="mun")["proj"][0] for _ in range(boot)])
            reps_u = np.array([self.projetar(apur, O, esa, comp_m, valid_m, boot_rng=rng, boot_nivel="uf")["proj"][0] for _ in range(boot_uf)]) if boot_uf else np.zeros(1)
            pend = 1 - r["pct"] / 100
            sd = max(np.sqrt((self.calib * reps_m.std()) ** 2 + (reps_u.std() * pend) ** 2), 0.02)
            r["sd"], r["sd_mun"], r["sd_uf"] = float(sd), float(reps_m.std()), float(reps_u.std())
            r["faixa"] = (med - 1.645 * sd, med + 1.645 * sd); r["p_pt"] = float(Phi((med - 50) / sd))
        else:
            r["faixa"] = (np.nan, np.nan); r["p_pt"] = np.nan
        return r
