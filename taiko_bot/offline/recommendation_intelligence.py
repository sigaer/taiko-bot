from __future__ import annotations

from taiko_application.query import RecommendationContext
from taiko_application.query import recommendation as application_recommendation

import argparse
import contextlib
import io
import json
import sys
from taiko_store import PublicationError
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal

from .score_calculator import (
    aggregate_topN_value,
    compute_all_from_userdata,
    compute_dim_topN_means,
    compute_recommendations_for_user,
)
from .target_recommend import (
    TargetRecommendationResult,
    compute_target_recommendations_for_user,
)


# Compatibility exports share the Application definitions.
from taiko_application.query.recommendation import (
    MODEL, RATING_AGGREGATION, RATING_TOP_N, RATING_DUPLICATE_HANDLING,
    ORDINARY_BASIS, TARGET_KEYS, DimensionKey, DIMENSION_COLUMNS, _round,
)


def build_player_rating_intelligence(
    user_id: int | str,
    *,
    json_path: str | Path = "./songs/rating_structured_with_ids.json"
) -> Dict[str, Any]:
    """Build the stable Viewer V1 rating contract without changing 0.49.8 semantics."""
    results = compute_all_from_userdata(
        int(user_id), json_path=json_path, collapse_duplicate_versions=False
    )
    return application_recommendation.project_player_rating(
        RecommendationContext(rating_results=results)
    )


def project_ordinary_recommendations(
    rows: Iterable[Dict[str, Any]], *, basis: str
) -> Dict[str, Any]:
    return application_recommendation.project_ordinary_recommendations(
        RecommendationContext(rows=rows, basis=basis)
    )


def build_ordinary_recommendation_intelligence(
    user_id: int | str,
    *,
    basis: str = "rating",
    limit: int = 20,
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
) -> Dict[str, Any]:
    rows = compute_recommendations_for_user(
        int(user_id),
        best_key=basis,
        limit=max(1, min(50, int(limit))),
        json_path=json_path,
    )
    return project_ordinary_recommendations(rows, basis=basis)


def project_target_recommendations(
    result: TargetRecommendationResult,
) -> Dict[str, Any]:
    return application_recommendation.project_target_recommendations(
        RecommendationContext(target_result=result)
    )


def build_target_recommendation_intelligence(
    user_id: int | str,
    *,
    target: str,
    limit: int = 20,
    star_filter: str | None = None,
) -> Dict[str, Any]:
    if target not in TARGET_KEYS:
        raise ValueError(f"unsupported target recommendation target: {target}")
    result = compute_target_recommendations_for_user(
        user_id=user_id,
        target_key=target,
        limit=max(1, min(20, int(limit))),
        star_filter=star_filter,
    )
    return project_target_recommendations(result)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Viewer Recommendation Intelligence bridge")
    sub = parser.add_subparsers(dest="command", required=True)

    rating = sub.add_parser("rating")
    rating.add_argument("user_id")
    rating.add_argument("--rating-data", default="./songs/rating_structured_with_ids.json")

    ordinary = sub.add_parser("ordinary")
    ordinary.add_argument("user_id")
    ordinary.add_argument("--basis", choices=ORDINARY_BASIS, default="rating")
    ordinary.add_argument("--limit", type=int, default=20)
    ordinary.add_argument("--rating-data", default="./songs/rating_structured_with_ids.json")

    target = sub.add_parser("target")
    target.add_argument("user_id")
    target.add_argument("--target", choices=TARGET_KEYS, required=True)
    target.add_argument("--limit", type=int, default=20)
    target.add_argument("--star")
    return parser


def main() -> int:
    args = _parser().parse_args()
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        if args.command == "rating":
            payload = build_player_rating_intelligence(args.user_id, json_path=args.rating_data)
        elif args.command == "ordinary":
            payload = build_ordinary_recommendation_intelligence(
                args.user_id,
                basis=args.basis,
                limit=args.limit,
                json_path=args.rating_data,
            )
        else:
            payload = build_target_recommendation_intelligence(
                args.user_id,
                target=args.target,
                limit=args.limit,
                star_filter=args.star,
            )
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


def entrypoint():
    try:
        return main()
    except PublicationError:
        print("Score publication is unavailable", file=sys.stderr)
        return 75


if __name__ == "__main__":
    raise SystemExit(entrypoint())
