"""Numeric metrics for validation: ratings and per-90 performance.

FotMob's stat names are not reliable about units. Verified against the live
API for Premier League 2025/26 (league 47, season 27110):

**Totals** (round numbers, equal ``per_90 * minutes / 90``):

* ``goals`` - 243 rows, exact match with the per-90 series
* ``expected_goals`` - 295 of 314 rows match within 15 percent
* ``expected_assists`` - 292 of 336 match within 15 percent

**Per-90 despite the name** (``total_tackle`` and ``accurate_pass`` have no
``_per_90`` suffix but are already per 90):

* ``accurate_pass`` - Rodri reads 86.7. As a total over 1513 minutes that
  would be about one accurate pass per match, which is impossible for a
  defensive midfielder. As a per-90 it is ordinary.
* ``total_tackle``, ``interception``, ``rating``, ``saves``, and every
  ``_per_90`` series.

The check used to confirm this is recorded in ``SEMANTICS_VERIFIED_ON`` so a
future reader can re-run it rather than trust the name.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import pandas as pd

logger = logging.getLogger(__name__)

STATS_DIR: Final[Path] = Path("data/raw/fotmob/stats")
OUT_METRICS: Final[Path] = Path("data/processed/metrics_numeric.parquet")
OUT_REPORT: Final[Path] = Path("reports/numeric_validation.md")

SEMANTICS_VERIFIED_ON: Final[str] = "2026-11-12"

Unit = Literal["total", "per90"]


@dataclass(frozen=True)
class StatSpec:
    """One FotMob stat, with the unit that was actually verified."""

    name: str
    unit: Unit
    column: str
    note: str = ""


# Only stats whose unit was verified. Adding one without checking invites a
# silently wrong column, which is worse than a missing column.
STAT_SPECS: Final[tuple[StatSpec, ...]] = (
    StatSpec("goals", "total", "goals", "verified: equals per_90 * minutes / 90"),
    StatSpec("expected_goals", "total", "xg", "verified against expected_goals_per_90"),
    StatSpec("expected_assists", "total", "xa", "verified against expected_assists_per_90"),
    StatSpec(
        "expected_goals_per_90",
        "per90",
        "xg_per90",
        "meets PRD section 8 requirement",
    ),
    StatSpec(
        "expected_assists_per_90",
        "per90",
        "xa_per90",
        "meets PRD section 8 requirement",
    ),
    StatSpec("rating", "per90", "avg_rating", "match rating, already an average"),
    StatSpec("total_tackle", "per90", "tackles_per90", "name misleads; already per 90"),
    StatSpec("interception", "per90", "interceptions_per90", "already per 90"),
    StatSpec("accurate_pass", "per90", "accurate_pass_per90", "name misleads; already per 90"),
    StatSpec(
        "saves",
        "per90",
        "saves_per90",
        "goalkeepers only; FotMob lists 20 with >=1800 minutes, so the four "
        "keepers below that cut-off read null rather than zero",
    ),
)

# FotMob returns partial leaderboards for some stats rather than a row per
# player. ``saves`` covers 20 goalkeepers, all with at least 1800 minutes;
# the four keepers under that bound are absent, not zero. Recorded here so
# nobody reads the nulls as "made no saves".
KNOWN_COVERAGE_LIMITS: Final[dict[str, str]] = {
    "saves": "leaderboard only: 20 keepers, all >=1800 minutes",
    "goals": "counts only players who scored; a null means zero goals",
    "expected_goals": "present for 444 of 537 players; null means very low xG",
}


def load_stat(name: str, stats_dir: Path = STATS_DIR) -> dict[int, float]:
    """Return ``{fotmob_id: value}`` for one cached stat, skipping nulls."""
    import json

    path = stats_dir / f"{name}.json"
    if not path.exists():
        logger.warning("stat file missing: %s", path)
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    values: dict[int, float] = {}
    for row in payload.get("statsData") or []:
        raw = (row.get("statValue") or {}).get("value")
        if isinstance(raw, (int, float)):
            values[int(row["id"])] = float(raw)
    return values


def build_metrics(
    players: pd.DataFrame,
    *,
    stats_dir: Path = STATS_DIR,
    specs: tuple[StatSpec, ...] = STAT_SPECS,
) -> pd.DataFrame:
    """Join cached stats onto the population, one column per verified stat.

    Left join on ``fotmob_id``: a player without a given stat keeps a null in
    that column and is never dropped. Rating coverage is genuinely partial
    (291 of 340 players have one), so an inner join would quietly remove 49
    players from the validation set.
    """
    frame = players.copy()
    if "fotmob_id" not in frame.columns:
        raise ValueError("players frame must carry fotmob_id")

    for spec in specs:
        values = load_stat(spec.name, stats_dir)
        frame[spec.column] = frame["fotmob_id"].map(values)

        covered = int(frame[spec.column].notna().sum())
        logger.debug("%s: %d/%d players", spec.column, covered, len(frame))

    return frame


def rating_zscore_within_position(
    frame: pd.DataFrame,
    *,
    rating_column: str = "avg_rating",
    group_column: str = "position_group",
    minutes_column: str = "minutes",
    min_minutes: int = 900,
) -> pd.Series:
    """Z-score the rating inside each position group.

    Minutes-weighting is deliberately not used: a weighted mean is not a
    z-score, and mixing the two produces a number that is neither. Instead the
    minutes threshold is applied first and then a plain z-score is computed,
    which is what docs/PRD.md section 9 describes.

    Returns a Series aligned to ``frame.index``; null where undefined.
    """
    result = pd.Series(index=frame.index, dtype="float64")
    eligible = frame[minutes_column] >= min_minutes

    for group, subset in frame[eligible].groupby(group_column, observed=True):
        ratings = subset[rating_column].dropna()
        if len(ratings) < 2:
            logger.warning("group %s has %d ratings; z-score undefined", group, len(ratings))
            continue
        std = ratings.std(ddof=0)
        if not std:
            logger.warning("group %s has zero rating spread; z-score undefined", group)
            continue
        result.loc[ratings.index] = (ratings - ratings.mean()) / std

    return result


def positional_percentiles(
    frame: pd.DataFrame,
    *,
    rating_column: str = "avg_rating",
    value_column: str = "market_value_eur",
    group_column: str = "position_group",
    minutes_column: str = "minutes",
    min_minutes: int = 900,
) -> pd.DataFrame:
    """Compute within-position value/rating percentiles, rank, and median flag.

    Unrated or below-threshold players keep ``pd.NA`` in ``rating_above_median``
    rather than ``False``, so downstream candidate flagging never mistakes a
    leaderboard coverage gap for poor performance.
    """
    out = frame.copy()
    out["value_pos_percentile"] = pd.Series(index=frame.index, dtype="float64")
    out["rating_pos_percentile"] = pd.Series(index=frame.index, dtype="float64")
    out["rating_pos_rank"] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    out["rating_above_median"] = pd.Series(pd.NA, index=frame.index, dtype="boolean")

    if frame.empty or group_column not in frame.columns:
        return out

    for _, subset in frame.groupby(group_column, observed=True):
        if value_column in frame.columns:
            prices = subset[value_column].dropna()
            if not prices.empty:
                out.loc[prices.index, "value_pos_percentile"] = (
                    prices.rank(method="average", pct=True) * 100.0
                )

        if rating_column in frame.columns:
            eligible = (
                subset[minutes_column] >= min_minutes
                if minutes_column in frame.columns
                else pd.Series(True, index=subset.index)
            )
            ratings = subset.loc[eligible, rating_column].dropna()
            if not ratings.empty:
                out.loc[ratings.index, "rating_pos_percentile"] = (
                    ratings.rank(method="average", pct=True) * 100.0
                )
                out.loc[ratings.index, "rating_pos_rank"] = (
                    ratings.rank(method="min", ascending=False).astype("Int64")
                )
                median_rating = float(ratings.median())
                out.loc[ratings.index, "rating_above_median"] = (
                    ratings > median_rating
                ).astype("boolean")

    return out


def _bootstrap_quantile_ci(
    values: list[float],
    q: float,
    *,
    iterations: int,
    seed: int,
) -> tuple[float, float, float]:
    """Return (point_estimate, ci_low_95, ci_high_95) for a sample quantile."""
    if not values:
        return float("nan"), float("nan"), float("nan")
    series = pd.Series(values, dtype="float64")
    point = float(series.quantile(q))
    if len(values) < 2 or iterations <= 0:
        return point, point, point

    rng = random.Random(seed)
    n = len(values)
    estimates = sorted(
        float(pd.Series(rng.choices(values, k=n), dtype="float64").quantile(q))
        for _ in range(iterations)
    )
    low_idx = max(0, int(0.025 * len(estimates)))
    high_idx = min(len(estimates) - 1, int(0.975 * len(estimates)))
    return point, estimates[low_idx], estimates[high_idx]


def positional_summary(
    frame: pd.DataFrame,
    *,
    min_minutes: int = 900,
    bootstrap_iterations: int = 1000,
    seed: int = 20252026,
    market_value_percentile: float = 40.0,
) -> pd.DataFrame:
    """Summarize positional medians, price cutoffs, and 95% bootstrap CIs (PRD §9)."""
    rows: list[dict[str, object]] = []
    if frame.empty or "position_group" not in frame.columns:
        return pd.DataFrame()

    order = ["GK", "DEF", "MID", "FWD"]
    groups = [g for g in order if g in set(frame["position_group"].dropna())] + sorted(
        g for g in set(frame["position_group"].dropna()) if g not in order
    )

    for pos_idx, group in enumerate(groups):
        subset = frame[frame["position_group"] == group]
        eligible = (
            subset[subset["minutes"] >= min_minutes]
            if "minutes" in subset.columns
            else subset
        )
        ratings = (
            eligible["avg_rating"].dropna().astype(float).tolist()
            if "avg_rating" in eligible.columns
            else []
        )
        prices = (
            subset["market_value_eur"].dropna().astype(float).tolist()
            if "market_value_eur" in subset.columns
            else []
        )

        r_med, r_lo, r_hi = _bootstrap_quantile_ci(
            ratings, 0.5, iterations=bootstrap_iterations, seed=seed + pos_idx * 2
        )
        v_p40, v_lo, v_hi = _bootstrap_quantile_ci(
            prices,
            market_value_percentile / 100.0,
            iterations=bootstrap_iterations,
            seed=seed + pos_idx * 2 + 1,
        )

        in_sample = (
            subset[subset["in_text_sample"].fillna(False)]
            if "in_text_sample" in subset.columns
            else subset.iloc[0:0]
        )
        sample_rated = (
            int(in_sample["avg_rating"].notna().sum())
            if "avg_rating" in in_sample.columns
            else 0
        )

        rows.append(
            {
                "position_group": group,
                "n_players": len(subset),
                "n_rated": len(ratings),
                "n_unrated": len(subset) - len(ratings),
                "rating_median": r_med,
                "rating_median_ci_low": r_lo,
                "rating_median_ci_high": r_hi,
                "value_p40": v_p40,
                "value_p40_ci_low": v_lo,
                "value_p40_ci_high": v_hi,
                "n_sample": len(in_sample),
                "n_sample_rated": sample_rated,
            }
        )

    return pd.DataFrame(rows)


def write_numeric_validation_report(
    frame: pd.DataFrame,
    summary: pd.DataFrame,
    *,
    path: Path = OUT_REPORT,
    min_minutes: int = 900,
    bootstrap_iterations: int = 1000,
) -> Path:
    """Write Stage A/E numeric benchmark & coverage report for Stage E/F."""
    n_total = len(frame)
    n_rated = int(frame["avg_rating"].notna().sum()) if "avg_rating" in frame.columns else 0
    n_priced = (
        int(frame["market_value_eur"].notna().sum())
        if "market_value_eur" in frame.columns
        else 0
    )
    in_sample = (
        frame[frame["in_text_sample"].fillna(False)]
        if "in_text_sample" in frame.columns
        else frame.iloc[0:0]
    )
    sample_rated = (
        int(in_sample["avg_rating"].notna().sum())
        if "avg_rating" in in_sample.columns
        else 0
    )

    lines = [
        "# Validasi Numerik & Tolok Ukur Posisi (Tahap A/E)",
        "",
        f"Dihasilkan otomatis oleh `src/score/run_metrics.py` (ambang menit >= **{min_minutes}**, "
        f"bootstrap **{bootstrap_iterations}x**).",
        "",
        "## Cakupan Data",
        "",
        f"- Populasi total: **{n_total}** pemain",
        f"- Market value FotMob tersedia: **{n_priced}/{n_total}**",
        f"- Rating FotMob (`stats/rating.json`) tersedia: **{n_rated}/{n_total}** "
        f"({n_total - n_rated} pemain tidak masuk papan peringkat leaderboard FotMob)",
        f"- Sampel teks terkunci: **{len(in_sample)}** pemain "
        f"(**{sample_rated}/{len(in_sample)}** memiliki rating di `rating.json`)",
        "",
        "> **Catatan bias cakupan leaderboard:** kolom *Median Rating (95% CI)* dihitung hanya dari "
        f"pemain yang memiliki entri di `rating.json` (**{n_rated}/{n_total}**), yang umumnya memiliki menit main "
        "lebih tinggi daripada pemain tanpa rating. Untuk posisi dengan *n* kecil (mis. GK, *n* = 20 rated), "
        "interval kepercayaan bootstrap harga dan rating melebar secara alami.",
        "",
        "## Ringkasan per Posisi (dengan Interval Kepercayaan Bootstrap 95%)",
        "",
        "| Posisi | Pemain | Punya Rating | Sampel (Rated) | Median Rating (95% CI) | P40 Harga EUR (95% CI) |",
        "|---|---|---|---|---|---|",
    ]
    for _, row in summary.iterrows():
        r_str = (
            f"{row['rating_median']:.2f} ({row['rating_median_ci_low']:.2f}–{row['rating_median_ci_high']:.2f})"
            if pd.notna(row["rating_median"])
            else "—"
        )
        v_str = (
            f"€{row['value_p40']/1e6:.2f}M (€{row['value_p40_ci_low']/1e6:.2f}M–€{row['value_p40_ci_high']/1e6:.2f}M)"
            if pd.notna(row["value_p40"])
            else "—"
        )
        lines.append(
            f"| {row['position_group']} | {int(row['n_players'])} | {int(row['n_rated'])} | "
            f"{int(row['n_sample'])} ({int(row['n_sample_rated'])}) | {r_str} | {v_str} |"
        )

    unrated_sample = (
        in_sample[in_sample["avg_rating"].isna()]
        if "avg_rating" in in_sample.columns
        else in_sample.iloc[0:0]
    )
    lines += [
        "",
        "## Pemain Sampel Tanpa Rating di `rating.json`",
        "",
        "Pemain di bawah ini tidak tercantum di leaderboard `leagueseasondeepstats` (`rating.json`), "
        "sehingga `rating_above_median` bernilai `<NA>` (bukan `False`). Stage E wajib memperlakukannya "
        "sebagai tidak tervalidasi rating, bukan otomatis di bawah median.",
        "",
    ]
    if unrated_sample.empty:
        lines.append("- Tidak ada.")
    else:
        lines += [
            "| player_id | Nama | Posisi | Klub | Menit | Harga (EUR) |",
            "|---|---|---|---|---|---|",
        ]
        for _, r in unrated_sample.sort_values(["position_group", "minutes"], ascending=[True, False]).iterrows():
            mv = f"€{r['market_value_eur']/1e6:.2f}M" if pd.notna(r.get("market_value_eur")) else "—"
            lines.append(
                f"| `{r['player_id']}` | {r['name_canonical']} | {r['position_group']} | "
                f"{r['club']} | {int(r['minutes'])} | {mv} |"
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("wrote numeric validation report -> %s", path)
    return path


def validate_metrics(frame: pd.DataFrame, *, min_minutes: int = 900) -> list[str]:
    """Check the metrics table before it is written. Empty list means OK."""
    problems: list[str] = []

    if frame.empty:
        return ["metrics frame is empty"]

    if "player_id" not in frame.columns:
        problems.append("missing player_id")
    elif not frame["player_id"].is_unique:
        problems.append("player_id is not unique")

    if "minutes" in frame.columns:
        under = int((frame["minutes"] < min_minutes).sum())
        if under:
            problems.append(f"{under} players below the {min_minutes}-minute threshold")

    if "avg_rating" in frame.columns:
        ratings = frame["avg_rating"].dropna()
        if ratings.empty:
            problems.append("no ratings at all")
        else:
            if ratings.min() < 0 or ratings.max() > 10:
                problems.append(
                    f"rating outside 0-10: min={ratings.min()}, max={ratings.max()}"
                )
            covered = len(ratings) / len(frame)
            if covered < 0.5:
                problems.append(f"rating coverage only {covered:.0%}")

    return problems
