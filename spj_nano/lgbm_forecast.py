"""LightGBMによるCO2予測の学習・保存・推論。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json

import pandas as pd

from spj_nano.features import make_supervised


@dataclass(frozen=True)
class LGBMConfig:
    learning_rate: float = 0.03
    n_estimators: int = 1200
    num_leaves: int = 31
    max_depth: int = -1
    min_child_samples: int = 30
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    reg_alpha: float = 0.1
    reg_lambda: float = 1.0
    random_state: int = 42


def _lightgbm():
    try:
        import lightgbm as lgb
    except ImportError as exc:
        raise RuntimeError(
            "LightGBMがインストールされていません。" 
            "pyproject.toml反映後に `uv sync` または `pip install lightgbm` を実行してください。"
        ) from exc
    return lgb


def train_models(
    features: pd.DataFrame,
    target: pd.Series,
    horizons_minutes: tuple[int, ...] = (15, 30, 60, 120, 180),
    validation_days: int = 14,
    config: LGBMConfig | None = None,
) -> tuple[dict[int, object], pd.DataFrame]:
    lgb = _lightgbm()
    config = config or LGBMConfig()
    cutoff = features.index.max() - pd.Timedelta(days=validation_days)
    models: dict[int, object] = {}
    metrics: list[dict] = []

    for horizon in horizons_minutes:
        x, y = make_supervised(features, target, horizon)
        train_mask = x.index < cutoff
        valid_mask = x.index >= cutoff
        if train_mask.sum() < 100 or valid_mask.sum() < 50:
            raise ValueError(f"+{horizon}分の学習・検証データが不足しています")
        model = lgb.LGBMRegressor(
            objective="regression_l1",
            learning_rate=config.learning_rate,
            n_estimators=config.n_estimators,
            num_leaves=config.num_leaves,
            max_depth=config.max_depth,
            min_child_samples=config.min_child_samples,
            subsample=config.subsample,
            colsample_bytree=config.colsample_bytree,
            reg_alpha=config.reg_alpha,
            reg_lambda=config.reg_lambda,
            random_state=config.random_state,
            verbosity=-1,
        )
        model.fit(
            x.loc[train_mask],
            y.loc[train_mask],
            eval_set=[(x.loc[valid_mask], y.loc[valid_mask])],
            eval_metric="l1",
            callbacks=[lgb.early_stopping(80, verbose=False)],
        )
        prediction = pd.Series(model.predict(x.loc[valid_mask]), index=y.loc[valid_mask].index)
        error = prediction - y.loc[valid_mask]
        metrics.append(
            {
                "horizon_minutes": horizon,
                "mae_ppm": float(error.abs().mean()),
                "rmse_ppm": float((error.pow(2).mean()) ** 0.5),
                "n_validation": int(len(error)),
                "best_iteration": int(model.best_iteration_),
            }
        )
        models[horizon] = model
    return models, pd.DataFrame(metrics)


def save_models(
    models: dict[int, object],
    metrics: pd.DataFrame,
    output_dir: str | Path,
    feature_names: list[str],
    config: LGBMConfig | None = None,
) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for horizon, model in models.items():
        # LightGBMのWindowsネイティブ保存は日本語を含むパスで失敗する
        # ことがあるため、モデル文字列をPythonでUTF-8保存する。
        model_text = model.booster_.model_to_string(num_iteration=model.best_iteration_)
        (output_dir / f"model_{horizon}m.txt").write_text(
            model_text, encoding="utf-8"
        )
    metadata = {
        "horizons_minutes": sorted(models),
        "feature_names": feature_names,
        "metrics": metrics.to_dict(orient="records"),
        "config": asdict(config or LGBMConfig()),
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_models(model_dir: str | Path) -> tuple[dict[int, object], dict]:
    lgb = _lightgbm()
    model_dir = Path(model_dir)
    metadata = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
    models = {
        int(horizon): lgb.Booster(
            model_str=(model_dir / f"model_{horizon}m.txt").read_text(encoding="utf-8")
        )
        for horizon in metadata["horizons_minutes"]
    }
    return models, metadata


def predict_latest(
    models: dict[int, object], features: pd.DataFrame
) -> pd.DataFrame:
    if features.empty:
        raise ValueError("予測用特徴量が空です")
    latest = features.iloc[[-1]]
    base_time = latest.index[0]
    rows = []
    for horizon, model in sorted(models.items()):
        rows.append(
            {
                "horizon_minutes": horizon,
                "time": base_time + pd.Timedelta(minutes=horizon),
                "predicted_co2": float(model.predict(latest)[0]),
            }
        )
    return pd.DataFrame(rows)


def forecast_from_database(
    db_path: str | Path,
    calendar_path: str | Path,
    model_dir: str | Path,
) -> tuple[pd.DataFrame, dict]:
    """保存済みモデルを使ってDBの最新時点から予測する。"""
    from spj_nano import db
    from spj_nano import features as feature_module
    from spj_nano import forecast as baseline_forecast

    calendar = feature_module.load_calendar_csv(calendar_path)
    with db.connect(Path(db_path)) as conn:
        co2_wide, target = feature_module.load_clean_co2(conn)
    profile = baseline_forecast.BaselineProfile.fit(target)
    frame = feature_module.build_feature_frame(
        co2_wide, baseline=profile, calendar=calendar
    )
    models, metadata = load_models(model_dir)
    result = predict_latest(models, frame)
    result["baseline_co2"] = profile.predict(
        pd.DatetimeIndex(result["time"])
    ).to_numpy()
    result["residual0"] = result["predicted_co2"] - result["baseline_co2"]
    result["data_time"] = target.index[-1]
    return result, metadata
