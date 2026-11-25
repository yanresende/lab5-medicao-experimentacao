"""Analise estatistica das medicoes (frente de analise, ver PROPOSTA.md, secao 9).

Le um ou mais CSV gerados por scripts/benchmark.py e produz:
  1. descritiva: mediana, media, p95 e desvio por (estudo, consulta, condicao, ...);
  2. P1: efeito da estatistica de tenant_id (`ausente` contra `atualizada`);
  3. P3 e referencias: efeito de cada indice contra `sem_indice`;
  4. P2: relacao entre tempo e numero de empresas (Spearman);
  5. frequencia dos planos de execucao.

Escolha do teste: as duas amostras comparadas vem de condicoes diferentes medidas em
momentos diferentes (execucoes distintas ou blocos distintos), entao NAO sao pares
casados. Por isso o teste e o de Mann-Whitney (amostras independentes), nao o de
Wilcoxon pareado. O tamanho do efeito e o delta de Cliff, e a diferenca tipica e o
estimador de Hodges-Lehmann (mediana das diferencas par a par), em ms.
Correcao de Holm dentro de cada pergunta. Medicoes censuradas (timeout) sao excluidas
dos testes e contadas a parte, e o limite inferior delas e reportado.

Uso:
    python analise/analisar.py dados/piloto_ausente.csv dados/piloto_atualizada.csv
Saidas em analise/resultados/ (CSV) e um resumo no terminal.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

SAIDA = Path(__file__).resolve().parent / "resultados"
# `tamanho` (linhas por tabela) entra na chave porque a Matriz B tem tres bancos com 1 empresa.
CHAVE = ["estudo", "consulta_id", "variante", "modo_plano", "empresas", "tamanho"]


def holm(pvalores: list[float]) -> list[float]:
    """Correcao de Holm-Bonferroni (ajusta p-valores, mantendo a ordem original)."""
    m = len(pvalores)
    ordem = np.argsort(pvalores)
    ajustado = np.empty(m)
    maximo = 0.0
    for posicao, i in enumerate(ordem):
        maximo = max(maximo, (m - posicao) * pvalores[i])
        ajustado[i] = min(1.0, maximo)
    return list(ajustado)


def comparar(a: np.ndarray, b: np.ndarray) -> dict:
    """Compara duas amostras independentes de tempos. Positivo = `a` mais lento que `b`."""
    if len(a) < 3 or len(b) < 3:
        return {}
    u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    delta = 2 * u / (len(a) * len(b)) - 1  # delta de Cliff: P(a>b) - P(a<b)
    hl = float(np.median(np.subtract.outer(a, b)))  # Hodges-Lehmann
    return {
        "n_a": len(a), "n_b": len(b), "mediana_a_ms": float(np.median(a)),
        "mediana_b_ms": float(np.median(b)), "razao_medianas": float(np.median(a) / np.median(b)),
        "hodges_lehmann_ms": hl, "cliff_delta": float(delta), "p_valor": float(p),
    }


def carregar(caminhos: list[Path]) -> pd.DataFrame:
    df = pd.concat([pd.read_csv(c) for c in caminhos], ignore_index=True)
    df["censurada"] = df["estourou_timeout"] == 1
    return df


def descritiva(df: pd.DataFrame) -> pd.DataFrame:
    ok = df[~df["censurada"]]
    chaves = ["estudo", "consulta_id", "condicao", "modo_plano", "estatistica_tenant", "empresas", "tamanho"]
    g = ok.groupby(chaves)["tempo_exec_ms"]
    tabela = g.agg(n="count", mediana="median", media="mean", desvio="std",
                   p95=lambda s: s.quantile(0.95)).reset_index()
    censuradas = df.groupby(chaves)["censurada"].sum().rename("censuradas").reset_index()
    return tabela.merge(censuradas, on=chaves, how="left")


def p1_estatistica(df: pd.DataFrame) -> pd.DataFrame:
    """`ausente` contra `atualizada`, mesma consulta, variante, condicao, modo e empresas."""
    linhas = []
    base = df[(~df["censurada"]) & (df["estudo"] == "v2")]
    for chave, grupo in base.groupby(CHAVE + ["condicao"]):
        aus = grupo.loc[grupo["estatistica_tenant"] == "ausente", "tempo_exec_ms"].to_numpy()
        atu = grupo.loc[grupo["estatistica_tenant"] == "atualizada", "tempo_exec_ms"].to_numpy()
        r = comparar(aus, atu)
        if r:
            linhas.append({**dict(zip(CHAVE + ["condicao"], chave)), **r})
    tabela = pd.DataFrame(linhas)
    if not tabela.empty:
        tabela["p_holm"] = holm(tabela["p_valor"].tolist())
        tabela = tabela.rename(columns={"mediana_a_ms": "mediana_ausente_ms",
                                        "mediana_b_ms": "mediana_atualizada_ms",
                                        "razao_medianas": "razao_ausente_sobre_atualizada"})
    return tabela


def indice_contra_sem(df: pd.DataFrame) -> pd.DataFrame:
    """Cada condicao contra `sem_indice`, na mesma execucao (estatistica e empresas iguais)."""
    linhas = []
    base = df[~df["censurada"]]
    chaves = CHAVE + ["estatistica_tenant"]
    for chave, grupo in base.groupby(chaves):
        ref = grupo.loc[grupo["condicao"] == "sem_indice", "tempo_exec_ms"].to_numpy()
        for condicao in sorted(set(grupo["condicao"]) - {"sem_indice"}):
            x = grupo.loc[grupo["condicao"] == condicao, "tempo_exec_ms"].to_numpy()
            r = comparar(ref, x)
            if r:
                linhas.append({**dict(zip(chaves, chave)), "condicao": condicao, **r})
    tabela = pd.DataFrame(linhas)
    if not tabela.empty:
        tabela["p_holm"] = holm(tabela["p_valor"].tolist())
        tabela = tabela.rename(columns={"mediana_a_ms": "mediana_sem_indice_ms",
                                        "mediana_b_ms": "mediana_condicao_ms",
                                        "razao_medianas": "razao_sem_sobre_condicao"})
    return tabela


def p3_reescrita(df: pd.DataFrame) -> pd.DataFrame:
    """Estudo de vistorias: consulta original contra a reescrita, com e sem indice."""
    linhas = []
    base = df[(~df["censurada"]) & (df["estudo"] == "vistorias")]
    chaves = ["variante", "modo_plano", "empresas", "tamanho", "estatistica_tenant"]
    comparacoes = [
        ("original sem indice x reescrita sem indice", ("vistorias_alertas", "sem_indice"),
         ("vistorias_alertas_reescrita", "sem_indice")),
        ("original com indice x reescrita sem indice", ("vistorias_alertas", "com_indice"),
         ("vistorias_alertas_reescrita", "sem_indice")),
        ("original sem indice x original com indice", ("vistorias_alertas", "sem_indice"),
         ("vistorias_alertas", "com_indice")),
        ("reescrita sem indice x reescrita com indice", ("vistorias_alertas_reescrita", "sem_indice"),
         ("vistorias_alertas_reescrita", "com_indice")),
    ]
    for chave, grupo in base.groupby(chaves):
        for rotulo, (ca, cond_a), (cb, cond_b) in comparacoes:
            a = grupo.loc[(grupo["consulta_id"] == ca) & (grupo["condicao"] == cond_a), "tempo_exec_ms"].to_numpy()
            b = grupo.loc[(grupo["consulta_id"] == cb) & (grupo["condicao"] == cond_b), "tempo_exec_ms"].to_numpy()
            r = comparar(a, b)
            if r:
                linhas.append({**dict(zip(chaves, chave)), "comparacao": rotulo, **r})
    tabela = pd.DataFrame(linhas)
    if not tabela.empty:
        tabela["p_holm"] = holm(tabela["p_valor"].tolist())
    return tabela


def erro_estimativa(df: pd.DataFrame) -> pd.DataFrame:
    """M2: linhas reais / linhas estimadas no primeiro no de varredura (1 = estimativa certa)."""
    if "linhas_estimadas" not in df.columns:
        return pd.DataFrame()
    ok = df[(~df["censurada"]) & (df["linhas_estimadas"] > 0)].copy()
    ok["erro"] = ok["linhas_reais_no_scan"] / ok["linhas_estimadas"]
    chaves = ["estudo", "consulta_id", "condicao", "estatistica_tenant", "empresas", "tamanho"]
    return ok.groupby(chaves)["erro"].agg(mediana="median", minimo="min", maximo="max").reset_index()


def p2_escala(df: pd.DataFrame) -> pd.DataFrame:
    """Spearman entre numero de empresas e tempo, por consulta, condicao, modo e estatistica."""
    linhas = []
    base = df[~df["censurada"]]
    chaves = ["estudo", "consulta_id", "condicao", "modo_plano", "estatistica_tenant"]
    for chave, grupo in base.groupby(chaves):
        if grupo["empresas"].nunique() < 3:
            continue
        rho, p = stats.spearmanr(grupo["empresas"], grupo["tempo_exec_ms"])
        medianas = grupo.groupby("empresas")["tempo_exec_ms"].median()
        linhas.append({**dict(zip(chaves, chave)), "rho_spearman": float(rho), "p_valor": float(p),
                       "razao_maior_menor_empresas": float(medianas.iloc[-1] / medianas.iloc[0])})
    tabela = pd.DataFrame(linhas)
    if not tabela.empty:
        tabela["p_holm"] = holm(tabela["p_valor"].tolist())
    return tabela


def planos(df: pd.DataFrame) -> pd.DataFrame:
    ok = df[~df["censurada"]].copy()
    ok["no_principal"] = ok["nos"].str.split(">").map(
        lambda ns: next((n for n in ns if "Scan" in n), ns[0]))
    chaves = ["estudo", "consulta_id", "condicao", "estatistica_tenant", "empresas", "tamanho"]
    tabela = ok.groupby(chaves + ["no_principal"]).size().rename("medicoes").reset_index()
    tabela["percentual"] = 100 * tabela["medicoes"] / tabela.groupby(chaves)["medicoes"].transform("sum")
    return tabela


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", nargs="+", type=Path)
    args = ap.parse_args()

    df = carregar(args.csv)
    SAIDA.mkdir(parents=True, exist_ok=True)

    resultados = {
        "descritiva": descritiva(df),
        "p1_estatistica": p1_estatistica(df),
        "indice_contra_sem": indice_contra_sem(df),
        "p2_escala": p2_escala(df),
        "p3_reescrita": p3_reescrita(df),
        "erro_estimativa": erro_estimativa(df),
        "planos": planos(df),
    }
    for nome, tabela in resultados.items():
        tabela.to_csv(SAIDA / f"{nome}.csv", index=False)
        print(f"{nome}: {len(tabela)} linhas -> analise/resultados/{nome}.csv")

    p1 = resultados["p1_estatistica"]
    if not p1.empty:
        sig = p1[p1["p_holm"] < 0.05]
        print(f"\nP1: {len(sig)} de {len(p1)} comparacoes com p ajustado (Holm) < 0,05.")
        top = p1.reindex(p1["cliff_delta"].abs().sort_values(ascending=False).index).head(5)
        print(top[["consulta_id", "variante", "condicao", "modo_plano", "mediana_ausente_ms",
                   "mediana_atualizada_ms", "cliff_delta", "p_holm"]].to_string(index=False))
    print("\nAtencao: com poucas repeticoes (piloto) os p-valores nao sao confiaveis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
