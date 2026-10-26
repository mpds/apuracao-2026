"""Extrai dos zips do TSE o que o replay precisa e grava parquet.

Uso:
  python -I replay/prep.py votacao <ano> <zip> <out_dir>   # votos por seção x candidato (presidente, 1º turno)
  python -I replay/prep.py detalhe <ano> <zip> <out_dir>   # aptos, comparecimento, horário de totalização
  python -I replay/prep.py locais  <ano> <zip> <out_dir>   # locais de votação (endereço, CEP, coordenadas) e seções
"""
import sys, zipfile, io, time
import pandas as pd

def csv_in_zip(zpath, pick):
    z = zipfile.ZipFile(zpath)
    names = [n for n in z.namelist() if n.lower().endswith(".csv")]
    name = pick(names)
    print("lendo", name, flush=True)
    return z.open(name)

def votacao(ano, zpath, out, turno=1):
    fh = csv_in_zip(zpath, lambda ns: ns[0])
    use = ["NR_TURNO","SG_UF","CD_MUNICIPIO","NR_ZONA","NR_SECAO","CD_CARGO","NR_VOTAVEL","QT_VOTOS","NR_LOCAL_VOTACAO"]
    parts = []; t0 = time.time(); n = 0
    for ch in pd.read_csv(io.TextIOWrapper(fh, encoding="latin-1"), sep=";", usecols=use, chunksize=2_000_000,
                          dtype={"SG_UF": "category"}, low_memory=False):
        n += len(ch)
        ch = ch[(ch.NR_TURNO == turno) & (ch.CD_CARGO == 1)]
        parts.append(ch.drop(columns=["NR_TURNO","CD_CARGO"]))
        print(f"  {n:,} linhas  {time.time()-t0:.0f}s", flush=True)
    df = pd.concat(parts)
    df["SG_UF"] = df.SG_UF.astype(str)
    df = df.astype({"CD_MUNICIPIO":"int32","NR_ZONA":"int16","NR_SECAO":"int16","NR_VOTAVEL":"int16","QT_VOTOS":"int32","NR_LOCAL_VOTACAO":"int32"})
    df.to_parquet(f"{out}/votacao_{ano}{'' if turno == 1 else '_t2'}.parquet", index=False)
    print(ano, "votacao:", len(df), "linhas,", df.groupby(["SG_UF","CD_MUNICIPIO","NR_ZONA","NR_SECAO"]).ngroups, "seções,",
          "votos:", df.QT_VOTOS.sum(), flush=True)
    print(df.groupby("NR_VOTAVEL").QT_VOTOS.sum().sort_values(ascending=False).head(8))

def detalhe(ano, zpath, out, turno=1):
    fh = csv_in_zip(zpath, lambda ns: [n for n in ns if n.endswith("_BR.csv")][0])
    use = ["NR_TURNO","SG_UF","CD_MUNICIPIO","NR_ZONA","NR_SECAO","CD_CARGO","QT_APTOS","QT_COMPARECIMENTO",
           "QT_VOTOS_NOMINAIS","QT_VOTOS_BRANCOS","QT_VOTOS_NULOS","NR_LOCAL_VOTACAO",
           "DT_RECEBIMENTO_BU_HOR_TSE","DT_PRIM_TOT_PARCIAL_HOR_TSE","ST_SECAO_INSTALADA"]
    parts = []; t0 = time.time(); n = 0
    for ch in pd.read_csv(io.TextIOWrapper(fh, encoding="latin-1"), sep=";", usecols=use, chunksize=1_000_000, low_memory=False):
        n += len(ch)
        ch = ch[(ch.NR_TURNO == turno) & (ch.CD_CARGO == 1)]
        parts.append(ch.drop(columns=["NR_TURNO","CD_CARGO"]))
        print(f"  {n:,} linhas  {time.time()-t0:.0f}s", flush=True)
    df = pd.concat(parts)
    for c in ["DT_RECEBIMENTO_BU_HOR_TSE","DT_PRIM_TOT_PARCIAL_HOR_TSE"]:
        df[c] = pd.to_datetime(df[c], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    df.to_parquet(f"{out}/detalhe_{ano}{'' if turno == 1 else '_t2'}.parquet", index=False)
    print(ano, "detalhe:", len(df), "seções; aptos", df.QT_APTOS.sum(), "comparecimento", df.QT_COMPARECIMENTO.sum(),
          "\n  sem horário:", df.DT_PRIM_TOT_PARCIAL_HOR_TSE.isna().sum(),
          "primeira:", df.DT_PRIM_TOT_PARCIAL_HOR_TSE.min(), "última:", df.DT_PRIM_TOT_PARCIAL_HOR_TSE.max(), flush=True)

def locais(ano, zpath, out):
    use = ["NR_TURNO","SG_UF","CD_MUNICIPIO","NM_MUNICIPIO","NR_ZONA","NR_SECAO","CD_TIPO_SECAO_AGREGADA","NR_SECAO_PRINCIPAL",
           "NR_LOCAL_VOTACAO","NM_LOCAL_VOTACAO","DS_ENDERECO","NM_BAIRRO","NR_CEP","NR_LATITUDE","NR_LONGITUDE","QT_ELEITOR_SECAO"]
    z = zipfile.ZipFile(zpath)
    df = pd.concat([pd.read_csv(io.TextIOWrapper(z.open(n), encoding="latin-1"), sep=";", usecols=use, low_memory=False, dtype=str)
                    for n in z.namelist() if n.lower().endswith(".csv")])
    df = df[df.NR_TURNO == "1"].drop(columns=["NR_TURNO"])
    for c in ["CD_MUNICIPIO","NR_ZONA","NR_SECAO","NR_LOCAL_VOTACAO","CD_TIPO_SECAO_AGREGADA","NR_SECAO_PRINCIPAL","QT_ELEITOR_SECAO"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(-1).astype("int64")
    for c in ["NR_LATITUDE","NR_LONGITUDE"]:
        df[c] = pd.to_numeric(df[c].str.replace(",", ".", regex=False), errors="coerce")
        df.loc[df[c] == -1, c] = float("nan")
    df["NR_CEP"] = df.NR_CEP.str.replace(r"\D", "", regex=True).str.zfill(8)
    df.to_parquet(f"{out}/locais_{ano}.parquet", index=False)
    loc = df.drop_duplicates(["SG_UF","CD_MUNICIPIO","NR_ZONA","NR_LOCAL_VOTACAO"])
    print(ano, "locais:", len(df), "seções,", len(loc), "locais; com coordenada:",
          f"{loc.NR_LATITUDE.notna().mean():.1%}", "eleitores:", df.QT_ELEITOR_SECAO.sum(), flush=True)

if __name__ == "__main__":
    cmd, ano, zpath, out = sys.argv[1:5]
    turno = int(sys.argv[5]) if len(sys.argv) > 5 else 1
    f = {"votacao": votacao, "detalhe": detalhe, "locais": locais}[cmd]
    f(int(ano), zpath, out, turno) if cmd != "locais" else f(int(ano), zpath, out)
