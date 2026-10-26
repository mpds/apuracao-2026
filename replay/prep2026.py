"""Converte os boletins de urna de 2026 (NDJSON do coletor) para o mesmo esquema de votacao_<ano>/detalhe_<ano>.

Uso: python -I replay/prep2026.py <dir_ndjson> <parquet_dir>

T_TOT de 2026 = horário de recebimento do BU no TSE (dr/hr do hash totalizado), que é o que o arquivo auxiliar expõe.
"""
import sys, json, glob, os
import numpy as np, pandas as pd

def main(d, out):
    rows = []
    for f in sorted(glob.glob(os.path.join(d, "*.ndjson"))):
        uf = os.path.basename(f)[:2].upper(); last = {}
        for line in open(f, encoding="utf-8"):
            if not line.strip(): continue
            r = json.loads(line); last[(r["mun"], r["zona"], r["secao"])] = r      # vale a última tentativa
        for r in last.values():
            if not r.get("votos"): continue
            rows.append((uf, int(r["mun"]), int(r["zona"]), int(r["secao"]), int(r.get("local") or -1), int(r.get("aptos") or 0),
                         int(r.get("comparecimento") or 0), int(r.get("branco") or 0), int(r.get("nulo") or 0),
                         f"{r.get('dr')} {r.get('hr')}", r["votos"]))
    cols = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_LOCAL_VOTACAO", "QT_APTOS", "QT_COMPARECIMENTO", "QT_VOTOS_BRANCOS", "QT_VOTOS_NULOS", "T", "votos"]
    df = pd.DataFrame(rows, columns=cols)
    det = df.drop(columns=["votos"]).copy()
    det["DT_PRIM_TOT_PARCIAL_HOR_TSE"] = pd.to_datetime(det.pop("T"), format="%d/%m/%Y %H:%M:%S", errors="coerce")
    det["DT_RECEBIMENTO_BU_HOR_TSE"] = det.DT_PRIM_TOT_PARCIAL_HOR_TSE
    det["QT_VOTOS_NOMINAIS"] = df.votos.map(lambda v: sum(v.values())).values
    det["ST_SECAO_INSTALADA"] = "Sim"
    det.to_parquet(f"{out}/detalhe_2026.parquet", index=False)
    v = df[["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_LOCAL_VOTACAO", "votos"]].explode("votos")
    v = df[["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_LOCAL_VOTACAO"]].join(
        df.votos.apply(lambda x: pd.Series(x, dtype="float")).fillna(0)).melt(
        id_vars=["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_LOCAL_VOTACAO"], var_name="NR_VOTAVEL", value_name="QT_VOTOS")
    v = v[v.QT_VOTOS > 0].astype({"NR_VOTAVEL": "int16", "QT_VOTOS": "int32"})
    v.to_parquet(f"{out}/votacao_2026.parquet", index=False)
    print(f"2026: {len(det)} seções, {det.SG_UF.nunique()} UFs; aptos {det.QT_APTOS.sum():,}; comparecimento {det.QT_COMPARECIMENTO.sum():,}")
    print("sem horário:", det.DT_PRIM_TOT_PARCIAL_HOR_TSE.isna().sum(), "primeira:", det.DT_PRIM_TOT_PARCIAL_HOR_TSE.min(), "última:", det.DT_PRIM_TOT_PARCIAL_HOR_TSE.max())
    print(v.groupby("NR_VOTAVEL").QT_VOTOS.sum().sort_values(ascending=False).head(8))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
