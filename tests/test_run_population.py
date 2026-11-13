"""Tests for Stage A population orchestration (BUG B and BUG D regressions)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.population import run_population
from src.population.build import PlayerRecord
from src.population.identity import generate_aliases


def _make_config(path: Path, clubs: list[str], *, target_players: int = 16) -> Path:
    cfg = {
        "league": {"clubs": clubs, "club_name_aliases": {}},
        "population": {"min_minutes": 900},
        "text_sample": {
            "target_players": target_players,
            "per_position_group": 4,
            "min_per_cell": 1,
            "random_seed": 20252026,
            "locked": False,
        },
    }
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return path


def _synthetic_records() -> tuple[list[PlayerRecord], list[str]]:
    clubs = [f"Club {i:02d}" for i in range(1, 21)]
    records: list[PlayerRecord] = []
    fid = 1000

    def add(name: str, group: str, club: str, mv: float) -> None:
        nonlocal fid
        fid += 1
        records.append(
            PlayerRecord(
                player_id=f"fotmob_{fid}",
                fotmob_id=fid,
                name_canonical=name,
                name_aliases=generate_aliases(name),
                position=group,
                position_group=group,
                club=club,
                minutes=1800,
                market_value_eur=mv,
            )
        )

    # Build 20 distinct clubs across GK/DEF/MID/FWD:
    # GK: 4 players, FWD: 4 players, MID: 4 players (two sharing "Henderson"
    # so they collide inside the sample), DEF: 8 players across 4 quartiles.
    for i in range(4):
        add(f"Keeper {i}", "GK", clubs[i], float(1e6 * (i + 1)))
    add("Jordan Henderson", "MID", clubs[4], 1e6)
    add("Dean Henderson", "MID", clubs[5], 2e6)
    add("Declan Rice", "MID", clubs[6], 3e6)
    add("Martin Odegaard", "MID", clubs[7], 4e6)

    for i in range(4):
        add(f"Forward {i}", "FWD", clubs[8 + i], float(1e6 * (i + 1)))

    # 8 defenders covering clubs[12..19]; Cristhian Mosquera in Q1, Yerson in Q4.
    add("Cristhian Mosquera", "DEF", clubs[12], 1e6)
    add("Extra Defender A", "DEF", clubs[13], 1.1e6)
    add("Extra Defender B", "DEF", clubs[14], 2e6)
    add("Extra Defender C", "DEF", clubs[15], 2.1e6)
    add("Extra Defender D", "DEF", clubs[16], 3e6)
    add("Extra Defender E", "DEF", clubs[17], 3.1e6)
    add("Extra Defender F", "DEF", clubs[18], 4e6)
    add("Yerson Mosquera", "DEF", clubs[19], 5e6)

    return records, clubs


def test_sample_aliases_keep_out_of_sample_non_collisions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """BUG B: aliases colliding only with non-sampled players must survive in text_sample."""
    records, clubs = _synthetic_records()
    cfg_path = _make_config(tmp_path / "config.yaml", clubs, target_players=16)
    out_players = tmp_path / "players.parquet"
    sample_locked = tmp_path / "text_sample.parquet"
    sample_review = tmp_path / "text_sample_review.csv"

    # Seed 5 deterministically selects Cristhian Mosquera and omits Yerson Mosquera.
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["text_sample"]["random_seed"] = 5
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    monkeypatch.setattr(run_population, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(run_population, "OUT_PLAYERS", out_players)
    monkeypatch.setattr(run_population, "SAMPLE_LOCKED", sample_locked)
    monkeypatch.setattr(run_population, "SAMPLE_REVIEW", sample_review)
    monkeypatch.setattr(run_population, "load_population", lambda **kw: (records, []))

    rc = run_population.main(lock=True)
    assert rc == 0

    locked = pd.read_parquet(sample_locked)
    assert locked["in_text_sample"].all()
    mosquera_row = locked.loc[locked["name_canonical"] == "Cristhian Mosquera"].iloc[0]
    assert "Mosquera" in list(mosquera_row["name_aliases"])

    # In-sample collision (Jordan Henderson vs Dean Henderson) must STILL be pruned.
    jh = locked.loc[locked["name_canonical"] == "Jordan Henderson"].iloc[0]
    dh = locked.loc[locked["name_canonical"] == "Dean Henderson"].iloc[0]
    assert "Henderson" not in list(jh["name_aliases"])
    assert "Henderson" not in list(dh["name_aliases"])


def test_dry_run_preserves_derived_columns_and_locked_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """BUG D: `make population` (lock=False) must not strip price_quartile/stratum/in_text_sample."""
    records, clubs = _synthetic_records()
    cfg_path = _make_config(tmp_path / "config.yaml", clubs, target_players=16)
    out_players = tmp_path / "players.parquet"
    sample_locked = tmp_path / "text_sample.parquet"
    sample_review = tmp_path / "text_sample_review.csv"

    monkeypatch.setattr(run_population, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(run_population, "OUT_PLAYERS", out_players)
    monkeypatch.setattr(run_population, "SAMPLE_LOCKED", sample_locked)
    monkeypatch.setattr(run_population, "SAMPLE_REVIEW", sample_review)
    monkeypatch.setattr(run_population, "load_population", lambda **kw: (list(records), []))

    # First lock the sample so players.parquet has 17 cols and 16 in_text_sample=True.
    assert run_population.main(lock=True) == 0
    before = pd.read_parquet(out_players)
    assert "price_quartile" in before.columns
    assert "stratum" in before.columns
    assert int(before["in_text_sample"].sum()) == 16

    # Re-seed fresh records and run dry-run (make population).
    records2, _ = _synthetic_records()
    monkeypatch.setattr(run_population, "load_population", lambda **kw: (records2, []))
    assert run_population.main(lock=False) == 0

    after = pd.read_parquet(out_players)
    assert len(after.columns) == 17
    assert "price_quartile" in after.columns
    assert "stratum" in after.columns
    assert int(after["in_text_sample"].sum()) == 16


def test_failed_sample_gate_does_not_overwrite_players_parquet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative boundary: failed verify_sample must not touch existing players.parquet."""
    records, clubs = _synthetic_records()
    cfg_path = _make_config(tmp_path / "config.yaml", clubs, target_players=16)
    out_players = tmp_path / "players.parquet"
    sample_locked = tmp_path / "text_sample.parquet"
    sample_review = tmp_path / "text_sample_review.csv"

    sentinel = pd.DataFrame({"sentinel": [123]})
    sentinel.to_parquet(out_players, index=False)

    monkeypatch.setattr(run_population, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(run_population, "OUT_PLAYERS", out_players)
    monkeypatch.setattr(run_population, "SAMPLE_LOCKED", sample_locked)
    monkeypatch.setattr(run_population, "SAMPLE_REVIEW", sample_review)
    monkeypatch.setattr(run_population, "load_population", lambda **kw: (records, []))
    monkeypatch.setattr(run_population, "verify_sample", lambda *a, **kw: ["forced gate failure"])

    assert run_population.main(lock=False) == 1
    assert list(pd.read_parquet(out_players).columns) == ["sentinel"]


def test_dry_run_without_locked_file_writes_17_columns_with_false_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Boundary: initial dry run with no locked sample yet still emits all 17 columns."""
    records, clubs = _synthetic_records()
    cfg_path = _make_config(tmp_path / "config.yaml", clubs, target_players=16)
    out_players = tmp_path / "players.parquet"
    sample_locked = tmp_path / "text_sample.parquet"
    sample_review = tmp_path / "text_sample_review.csv"

    monkeypatch.setattr(run_population, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(run_population, "OUT_PLAYERS", out_players)
    monkeypatch.setattr(run_population, "SAMPLE_LOCKED", sample_locked)
    monkeypatch.setattr(run_population, "SAMPLE_REVIEW", sample_review)
    monkeypatch.setattr(run_population, "load_population", lambda **kw: (records, []))

    assert run_population.main(lock=False) == 0
    assert not sample_locked.exists()
    df = pd.read_parquet(out_players)
    assert len(df.columns) == 17
    assert "price_quartile" in df.columns
    assert "stratum" in df.columns
    assert int(df["in_text_sample"].sum()) == 0
