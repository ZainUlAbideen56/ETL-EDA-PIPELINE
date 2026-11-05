from __future__ import annotations

import sqlite3
from datetime import datetime

import matplotlib

matplotlib.use("Agg")             
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats

from . import config
from .logger import get_logger

log = get_logger()

PALETTE = {"Test": "#8C1C13", "ODI": "#1D3557", "T20": "#0B6E4F", "Other": "#8D99AE"}
GREEN, NAVY, GOLD = "#0B6E4F", "#1D3557", "#E9B44C"
MIN_MATCHES_TEAM = 10


def _style() -> None:
    sns.set_theme(style="whitegrid", context="notebook", font_scale=1.05)
    plt.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 150, "axes.titleweight": "bold",
        "axes.titlesize": 14, "axes.spines.top": False, "axes.spines.right": False,
    })


def _save(fig: plt.Figure, name: str) -> str:
    config.FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(config.FIG_DIR / name, bbox_inches="tight")
    plt.close(fig)
    return f"figures/{name}"


def _order(df: pd.DataFrame) -> list[str]:
    present = set(df["format"].unique())
    return [f for f in ("Test", "ODI", "T20", "Other") if f in present]


def load_frames(db_path=config.DB_PATH) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read the analysis tables straight from the database with SQL."""
    if not db_path.exists():
        raise FileNotFoundError(f"{db_path} not found - run the ETL first (python main.py etl).")
    with sqlite3.connect(db_path) as conn:
        matches = pd.read_sql_query("SELECT * FROM fact_match", conn, parse_dates=["match_date"])
        innings = pd.read_sql_query(
            "SELECT i.*, m.format, m.match_date, m.is_women FROM fact_innings i "
            "JOIN fact_match m USING (match_id)", conn, parse_dates=["match_date"])
    matches["year"] = matches["match_date"].dt.year
    innings["year"] = innings["match_date"].dt.year
    return matches, innings


def overview(m: pd.DataFrame, i: pd.DataFrame, report: list, findings: list) -> None:
    report.append("## 1. Data overview & quality\n")
    report.append(f"- **Matches:** {len(m):,}  |  **Innings:** {len(i):,}  |  "
                  f"**Teams:** {pd.concat([m.team1, m.team2]).nunique()}  |  "
                  f"**Venues:** {m.venue.nunique()}")
    report.append(f"- **Date range:** {m.match_date.min():%d %b %Y} -> {m.match_date.max():%d %b %Y}")
    report.append(f"- **Formats:** " + ", ".join(f"{k}: {v}" for k, v in m.format.value_counts().items()))
    report.append(f"- **Women's matches:** {m.is_women.mean() * 100:.1f}%\n")

    desc = i[["runs", "wickets", "overs", "run_rate"]].describe().round(2)
    desc.to_csv(config.PROCESSED_DIR / "innings_summary_statistics.csv")
    report.append("**Innings summary statistics**\n")
    report.append(desc.to_markdown() + "\n")

    miss = (m.isna().mean() * 100).sort_values(ascending=False)
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.barplot(x=miss.values, y=miss.index, color=GOLD, ax=ax)
    ax.set(title="Missing values per column (fact_match)", xlabel="% missing", ylabel="")
    report.append(f"![missing]({_save(fig, 'fig01_missing_values.png')})\n")

    worst = miss[miss > 0].head(3)
    if len(worst):
        findings.append("Columns with most missing data: " +
                        ", ".join(f"`{c}` ({v:.0f}%)" for c, v in worst.items()) +
                        ". Some gaps are by design (`batting_first_won` only exists for ODI/T20 results); "
                        "toss and result fields depend on what the API supplies.")


def univariate(m: pd.DataFrame, i: pd.DataFrame, report: list, findings: list) -> None:
    report.append("## 2. Univariate analysis\n")
    order = _order(m)

    fig, ax = plt.subplots(figsize=(7, 4.5))
    sns.countplot(data=m, x="format", order=order, hue="format", palette=PALETTE, legend=False, ax=ax)
    for c in ax.containers:
        ax.bar_label(c, padding=3)
    ax.set(title="Matches by format", xlabel="", ylabel="Number of matches")
    report.append(f"![formats]({_save(fig, 'fig02_matches_by_format.png')})\n")
    top = m.format.value_counts()
    findings.append(f"**{top.index[0]}** is the most common format ({top.iloc[0] / len(m) * 100:.0f}% of matches).")

    ct = pd.crosstab(m.year, m.format)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ct.plot(ax=ax, marker="o", color=[PALETTE[c] for c in ct.columns], linewidth=2)
    ax.set(title="Matches played per year", xlabel="Year", ylabel="Matches")
    ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))
    report.append(f"![years]({_save(fig, 'fig03_matches_per_year.png')})\n")

    fmts = [f for f in order if f in config.FORMATS]
    fig, axes = plt.subplots(1, len(fmts), figsize=(5 * len(fmts), 4), squeeze=False)
    for ax, fmt in zip(axes[0], fmts):
        sub = i[i.format == fmt]
        sns.histplot(sub.runs, bins=25, kde=len(sub) >= 10, color=PALETTE[fmt], ax=ax)
        ax.axvline(sub.runs.mean(), color="black", ls="--", lw=1)
        ax.set(title=f"{fmt}: runs per innings (mean {sub.runs.mean():.0f})", xlabel="Runs", ylabel="Innings")
    report.append(f"![runs]({_save(fig, 'fig04_runs_distribution.png')})\n")


def bivariate(m: pd.DataFrame, i: pd.DataFrame, report: list, findings: list) -> None:
    report.append("## 3. Bivariate & multivariate analysis\n")
    order = _order(m)

    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    sns.boxplot(data=i, x="format", y="run_rate", order=order, hue="format", palette=PALETTE,
                legend=False, ax=ax)
    ax.set(title="Run rate (runs per over) by format", xlabel="", ylabel="Run rate")
    report.append(f"![runrate]({_save(fig, 'fig05_run_rate_by_format.png')})\n")
    rr = i.groupby("format").run_rate.mean().round(2)
    findings.append("Average run rate by format: " + ", ".join(f"{k} = {v}" for k, v in rr.items()) + ".")

    m = m.assign(outcome=m.win_type.fillna(m.result_type))
    share = pd.crosstab(m.format, m.outcome, normalize="index").mul(100).reindex(order)
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    share.plot(kind="barh", stacked=True, ax=ax, colormap="viridis")
    ax.set(title="How matches end (% of matches)", xlabel="%", ylabel="")
    ax.legend(title="Outcome", bbox_to_anchor=(1.02, 1), loc="upper left")
    report.append(f"![outcomes]({_save(fig, 'fig06_result_types.png')})\n")

    fig, ax = plt.subplots(figsize=(6.5, 5))
    corr = i[["runs", "wickets", "overs", "balls", "run_rate"]].corr()
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="YlGnBu", vmin=-1, vmax=1, square=True, ax=ax)
    ax.set_title("Correlation between innings variables")
    report.append(f"![corr]({_save(fig, 'fig07_correlation_heatmap.png')})\n")

    trend = i[i.innings_no == 1].groupby(["year", "format"]).runs.mean().reset_index()
    trend = trend[trend.format.isin(config.LIMITED_OVERS)]
    if not trend.empty:
        fig, ax = plt.subplots(figsize=(9, 4.5))
        sns.lineplot(data=trend, x="year", y="runs", hue="format", palette=PALETTE, marker="o", ax=ax)
        ax.set(title="Average first-innings score by year (limited overs)", xlabel="Year", ylabel="Avg runs")
        ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))
        report.append(f"![trend]({_save(fig, 'fig08_scoring_trend.png')})\n")


def teams_and_venues(m: pd.DataFrame, report: list, findings: list) -> None:
    report.append("## 4. Team & venue analysis\n")
    played = pd.concat([m.team1, m.team2]).value_counts()
    wins = m.winner.value_counts()
    table = pd.DataFrame({"played": played, "wins": wins}).fillna(0).astype(int)
    table["win_pct"] = (table.wins / table.played * 100).round(1)
    table = table[table.played >= MIN_MATCHES_TEAM].sort_values("win_pct", ascending=False)
    table.to_csv(config.PROCESSED_DIR / "team_win_table.csv")

    if not table.empty:
        top = table.head(12).iloc[::-1]
        fig, ax = plt.subplots(figsize=(8, 5.5))
        ax.barh(top.index, top.win_pct, color=GREEN)
        for y, (pct, n) in enumerate(zip(top.win_pct, top.played)):
            ax.text(pct + 0.8, y, f"{pct}%  (n={n})", va="center", fontsize=9)
        ax.set(title=f"Win % by team (min {MIN_MATCHES_TEAM} matches)", xlabel="Win %", xlim=(0, 100))
        report.append(f"![teams]({_save(fig, 'fig09_team_win_pct.png')})\n")
        best = table.iloc[0]
        findings.append(f"Best win rate: **{table.index[0]}** with {best.win_pct}% from {int(best.played)} matches.")

    venues = m.venue[m.venue != "Unknown"].value_counts().head(10).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8.5, 5))
    ax.barh(venues.index, venues.values, color=NAVY)
    ax.set(title="Top 10 venues by matches hosted", xlabel="Matches")
    report.append(f"![venues]({_save(fig, 'fig10_top_venues.png')})\n")
    if len(venues):
        findings.append(f"Busiest venue: **{venues.index[-1]}** ({venues.iloc[-1]} matches).")


def match_situation(m: pd.DataFrame, report: list, findings: list) -> None:
    report.append("## 5. Match-situation analysis\n")
    lim = m[m.format.isin(config.LIMITED_OVERS) & m.batting_first_won.notna()].copy()
    if len(lim) >= 10:
        rate = lim.groupby("format").batting_first_won.mean().mul(100)
        data = pd.DataFrame({"Batting first": rate, "Chasing": 100 - rate})
        fig, ax = plt.subplots(figsize=(6.5, 4.5))
        data.plot(kind="bar", stacked=True, ax=ax, color=[NAVY, GOLD], rot=0)
        ax.axhline(50, color="black", ls="--", lw=1)
        ax.set(title="Who wins: batting first or chasing?", xlabel="", ylabel="% of decided matches")
        report.append(f"![chase]({_save(fig, 'fig11_batting_first_vs_chasing.png')})\n")
        findings.append("Teams batting first win " +
                        ", ".join(f"{v:.0f}% of {k}" for k, v in rate.items()) + " matches.")
    else:
        report.append("_Not enough limited-overs results to analyse batting first vs chasing._\n")

    toss = m[m.toss_won_match.notna()]
    if len(toss) >= 30:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.3))
        dec = pd.crosstab(toss.format, toss.toss_decision, normalize="index").mul(100)
        dec.plot(kind="bar", ax=axes[0], color=[GREEN, GOLD], rot=0)
        axes[0].set(title="Toss winner's decision", xlabel="", ylabel="%")
        win = toss.groupby("format").toss_won_match.mean().mul(100)
        axes[1].bar(win.index, win.values, color=[PALETTE.get(f, GREEN) for f in win.index])
        axes[1].axhline(50, color="black", ls="--", lw=1)
        axes[1].set(title="Toss winner also wins the match (%)", ylabel="%", ylim=(0, 100))
        report.append(f"![toss]({_save(fig, 'fig12_toss_analysis.png')})\n")
    else:
        report.append("_Toss columns were too sparse (<30 rows) for a toss analysis._\n")



def tests_and_outliers(m: pd.DataFrame, i: pd.DataFrame, report: list, findings: list) -> None:
    report.append("## 6. Statistical tests & outliers\n")
    rows = []

    for fmt in config.LIMITED_OVERS:
        sub = m[(m.format == fmt) & m.batting_first_won.notna()]
        if len(sub) >= 20:
            k, n = int(sub.batting_first_won.sum()), len(sub)
            p = stats.binomtest(k, n, 0.5).pvalue
            rows.append((f"{fmt}: is batting first a 50/50 advantage?", f"{k}/{n} = {k / n:.1%}", p))

    toss = m[m.toss_won_match.notna()]
    if len(toss) >= 30:
        k, n = int(toss.toss_won_match.sum()), len(toss)
        rows.append(("Does winning the toss help win the match?", f"{k}/{n} = {k / n:.1%}",
                     stats.binomtest(k, n, 0.5).pvalue))

    groups = [g.run_rate.dropna().values for _, g in i.groupby("format") if len(g) >= 10]
    if len(groups) >= 2:
        h, p = stats.kruskal(*groups)
        rows.append(("Is run rate different across formats? (Kruskal-Wallis)", f"H = {h:.1f}", p))

    if rows:
        tests = pd.DataFrame(rows, columns=["Question", "Result", "p-value"])
        tests["Conclusion (alpha = 0.05)"] = np.where(tests["p-value"] < 0.05, "Significant", "Not significant")
        tests["p-value"] = tests["p-value"].map(lambda v: f"{v:.4g}")
        report.append(tests.to_markdown(index=False) + "\n")
        sig = tests[tests["Conclusion (alpha = 0.05)"] == "Significant"]
        findings.append(f"{len(sig)} of {len(tests)} statistical tests were significant at the 5% level.")

    out_rows = []
    for fmt, g in i.groupby("format"):
        q1, q3 = g.runs.quantile([.25, .75])
        iqr = q3 - q1
        mask = (g.runs < q1 - 1.5 * iqr) | (g.runs > q3 + 1.5 * iqr)
        out_rows.append({"format": fmt, "innings": len(g), "outliers": int(mask.sum()),
                         "outlier_%": round(mask.mean() * 100, 1), "max_runs": int(g.runs.max())})
    report.append("**Outlier check (1.5 x IQR rule on runs per innings)**\n")
    report.append(pd.DataFrame(out_rows).to_markdown(index=False) + "\n")
    report.append("_Outliers were inspected, not deleted: high scores such as 250+ in T20 or 400+ in ODI "
                  "are real cricket events, not data errors._\n")

    hi = i.sort_values("runs", ascending=False).head(5)[["format", "team", "runs", "wickets", "overs"]]
    report.append("**Five highest innings in the dataset**\n")
    report.append(hi.to_markdown(index=False) + "\n")

def run_eda(db_path=config.DB_PATH) -> str:
    config.ensure_dirs()
    _style()
    log.info("EDA started")
    m, i = load_frames(db_path)
    if m.empty:
        raise RuntimeError("fact_match is empty - run the ETL first.")


    report: list[str] = []
    findings: list[str] = []
    overview(m, i, report, findings)
    univariate(m, i, report, findings)
    bivariate(m, i, report, findings)
    teams_and_venues(m, report, findings)
    match_situation(m, report, findings)
    tests_and_outliers(m, i, report, findings)

    header = [
        "# Cricket Data - Exploratory Data Analysis Report\n",
        f"_Generated {datetime.now():%d %b %Y, %H:%M} from `data/cricket.db`_\n",
        "## Key findings\n",
        *[f"{n}. {f}" for n, f in enumerate(findings, 1)],
        "",
    ]
    path = config.REPORT_DIR / "eda_report.md"
    path.write_text("\n".join(header + report), encoding="utf-8")
    log.info("EDA finished -> %s (%d figures)", path.relative_to(config.ROOT_DIR),
             len(list(config.FIG_DIR.glob("*.png"))))
    return str(path)