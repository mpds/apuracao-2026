"""Cobertura da faixa de 90% em todos os pontos da grade (replay 2T 2022) para calibrar a faixa."""
import sys; sys.path.insert(0, __file__.rsplit("/", 1)[0])
import numpy as np, pandas as pd
from model2t import build_base_2t, Replay2T
b = build_base_2t(sys.argv[1], "2022", "2022_t2"); R = Replay2T(b)
grid = [0.5, 0.7, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.5, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 95]
df = R.run(grid, boot=200, boot_at=tuple(grid)); df["err"] = df.proj_PT - R.final[0]
df["half"] = (df.hi_PT - df.lo_PT) / 2; df["cobre"] = (df.lo_PT <= R.final[0]) & (df.hi_PT >= R.final[0]); df["z"] = df.err / (df.half / 1.645)
pd.set_option("display.width", 200); print(df[["pct", "proj_PT", "err", "half", "cobre", "z", "p_PT_vence"]].round(3).to_string(index=False))
print("cobertura:", df.cobre.mean().round(2), "| fator de calibração sugerido (quantil 90% de |z|):", np.percentile(df.z.abs(), 90).round(2))
df.to_csv(sys.argv[2], index=False)
