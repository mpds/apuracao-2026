"""Cliente HTTP para a divulgação do TSE: limite de taxa, ETag, paralelismo e pausa em caso de bloqueio."""
import time, threading, json, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

class Cliente:
    def __init__(self, base, rps=60, workers=16, ua="Mozilla/5.0 apuracao-2t/0.1"):
        self.base, self.rps, self.ua = base.rstrip("/"), rps, ua
        self.pool = ThreadPoolExecutor(workers); self.lock = threading.Lock(); self.marcas = []
        self.etags = {}; self.cache = {}; self.bloqueado_ate = 0; self.stats = dict(req=0, n304=0, n404=0, erro=0)

    def _espera(self):
        while True:
            with self.lock:
                agora = time.time(); self.marcas = [m for m in self.marcas if agora - m < 1.0]
                if agora < self.bloqueado_ate: dorme = self.bloqueado_ate - agora
                elif len(self.marcas) < self.rps: self.marcas.append(agora); return
                else: dorme = 1.0 - (agora - self.marcas[0]) + 0.005
            time.sleep(max(dorme, 0.005))

    def get(self, path, timeout=20):
        """Devolve (status, bytes|None). 304 -> conteúdo do cache. 404 -> (404, None)."""
        self._espera(); url = self.base + path
        h = {"User-Agent": self.ua, "Accept": "application/json"}
        if path in self.etags: h["If-None-Match"] = self.etags[path]
        self.stats["req"] += 1
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                dados = r.read(); et = r.headers.get("ETag")
                if et: self.etags[path] = et; self.cache[path] = dados
                return r.status, dados
        except urllib.error.HTTPError as e:
            if e.code == 304: self.stats["n304"] += 1; return 304, self.cache.get(path)
            if e.code == 404: self.stats["n404"] += 1; return 404, None
            if e.code in (403, 429, 503):
                with self.lock: self.bloqueado_ate = time.time() + 30
                print(f"[tse] {e.code} em {path}: pausa de 30 s", flush=True)
            self.stats["erro"] += 1; return e.code, None
        except Exception as e:
            self.stats["erro"] += 1; return 0, None

    def json(self, path):
        st, d = self.get(path)
        if d is None: return st, None
        try: return st, json.loads(d)
        except Exception: return st, None

    def muitos(self, paths):
        """Busca em paralelo; devolve {path: (status, json|None)}."""
        return dict(zip(paths, self.pool.map(self.json, paths)))

def caminhos(ciclo, pleito, eleicao):
    e6, p6 = f"{int(eleicao):06d}", f"{int(pleito):06d}"
    return dict(
        secoes=lambda uf: f"/{ciclo}/arquivo-urna/{int(pleito)}/config/{uf}/{uf}-p{p6}-cs.json",
        mun=lambda uf, mun: f"/{ciclo}/{int(eleicao)}/dados/{uf}/{uf}{int(mun):05d}-c0001-e{e6}-u.json",
        uf=lambda uf: f"/{ciclo}/{int(eleicao)}/dados/{uf}/{uf}-c0001-e{e6}-u.json",
        brasil=lambda: f"/{ciclo}/{int(eleicao)}/dados/br/br-c0001-e{e6}-u.json",
        municipios=lambda: f"/{ciclo}/{int(eleicao)}/config/mun-e{e6}-cm.json",
        elec=lambda: "/comum/config/ele-c.json",
    )
