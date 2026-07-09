"""
Build the video / hashtag datamart used by the TikTok sampling-strategy notebook.

Source files (raw, as actually delivered - NOT the schema described in the
proposal doc):
    data/tiktok-video_detail.csv            -> video identity / content fields
    data/tiktok-video_trending_score.csv    -> TCC "trending" score (rank 1..N)
    data/tiktok-video_virality_score.csv    -> TCC "emerging" score (rank 1..N)
                                                + 3-day view history (day 26/27/28)
    data/hashtag_to_video.csv               -> video <-> hashtag bridge (raw)
    data/hashtag_overview.csv               -> hashtag performance overview (raw)

Terminology mapping requested for this project:
    virality_score (raw file/column name) -> emerging_score
    trending_score (raw file/column name) -> trending_score (unchanged)

Universe definition:
    A video only belongs to the analysis universe if it has BOTH a trending
    score AND an emerging(virality) score. In the raw data every video that
    has a virality score also has a trending score, so the universe is simply
    the virality_score video set.

Outputs (written to processed/):
    video_datamart.csv      one row per video in the universe
    video_hashtag_map.csv   deduplicated video <-> hashtag bridge, universe only
    hashtag_datamart.csv    one row per (hashtag_id, country_code) touched by
                             the universe, taken from the latest available
                             hashtag_overview snapshot
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PROCESSED = ROOT / "processed"


def log(msg: str) -> None:
    print(f"[build_datamart] {msg}")


def build_video_datamart() -> pd.DataFrame:
    detail = pd.read_csv(DATA / "tiktok-video_detail.csv")
    trending = pd.read_csv(DATA / "tiktok-video_trending_score.csv")
    virality = pd.read_csv(DATA / "tiktok-video_virality_score.csv")

    universe_ids = set(trending["video_id"]) & set(virality["video_id"])
    log(
        f"trending videos={len(trending):,} | virality videos={len(virality):,} "
        f"| universe (trending & virality)={len(universe_ids):,}"
    )

    detail = detail[detail["video_id"].isin(universe_ids)].drop_duplicates(
        subset="video_id"
    )
    missing_detail = universe_ids - set(detail["video_id"])
    if missing_detail:
        log(f"WARNING: {len(missing_detail)} universe videos have no detail row")

    trending = trending[trending["video_id"].isin(universe_ids)].rename(
        columns={"rank": "trending_rank"}
    )
    virality = virality[virality["video_id"].isin(universe_ids)].rename(
        columns={"rank": "emerging_rank", "virality_score": "emerging_score"}
    )

    detail_cols = [
        "video_id",
        "video_url",
        "uploader",
        "uploader_id",
        "description",
        "upload_date",
        "duration_sec",
        "music_title",
        "music_author",
    ]
    video = detail[detail_cols].copy()

    # view/like/comment/share/followers: trending & virality agree with each
    # other (same underlying "day 28" pull) and are more recent/consistent
    # than detail.csv, so they are treated as the canonical engagement
    # snapshot instead of detail's own counters.
    metrics_cols = [
        "video_id",
        "view_count",
        "like_count",
        "comment_count",
        "share_count",
        "followers_count",
    ]
    video = video.merge(virality[metrics_cols], on="video_id", how="left")

    video = video.merge(
        trending[["video_id", "trending_score", "trending_rank"]],
        on="video_id",
        how="left",
    )
    video = video.merge(
        virality[
            [
                "video_id",
                "emerging_score",
                "emerging_rank",
                "views_day_26",
                "views_day_27",
                "views_day_28",
                "views_growth_short",
                "views_growth_long",
            ]
        ],
        on="video_id",
        how="left",
    )

    # Growth feature per proposal section 4.1: average daily increment over
    # the 26->27->28 window, smoother than a single endpoint-to-endpoint delta.
    inc_1 = video["views_day_27"] - video["views_day_26"]
    inc_2 = video["views_day_28"] - video["views_day_27"]
    video["growth_avg_daily_views"] = (inc_1 + inc_2) / 2

    ordered_cols = [
        "video_id",
        "video_url",
        "uploader",
        "uploader_id",
        "description",
        "upload_date",
        "duration_sec",
        "view_count",
        "like_count",
        "comment_count",
        "share_count",
        "followers_count",
        "music_title",
        "music_author",
        "views_day_26",
        "views_day_27",
        "views_day_28",
        "growth_avg_daily_views",
        "views_growth_short",
        "views_growth_long",
        "trending_score",
        "trending_rank",
        "emerging_score",
        "emerging_rank",
    ]
    video = video[ordered_cols].sort_values("video_id").reset_index(drop=True)
    log(f"video_datamart rows={len(video):,} cols={len(video.columns)}")
    return video


def build_hashtag_tables(universe_ids: set) -> tuple[pd.DataFrame, pd.DataFrame]:
    # VIDEO_ID in the raw file is corrupted to float64 on a naive read because
    # of a single stray NaN in the column, which silently truncates precision
    # on every 19-digit video id. Read as string to preserve exact ids.
    h2v = pd.read_csv(
        DATA / "hashtag_to_video.csv", dtype={"VIDEO_ID": "string"}
    )
    n_before = len(h2v)
    h2v = h2v.dropna(subset=["VIDEO_ID"])
    h2v["VIDEO_ID"] = h2v["VIDEO_ID"].astype("int64")
    log(f"hashtag_to_video rows={n_before:,}, dropped {n_before - len(h2v)} null VIDEO_ID")

    edges = h2v[h2v["VIDEO_ID"].isin(universe_ids)].copy()
    edges["DATA_EXTRACT_DATE"] = pd.to_datetime(edges["DATA_EXTRACT_DATE"])

    videos_with_hashtag = edges["VIDEO_ID"].nunique()
    log(
        f"edges touching universe={len(edges):,} | unique videos covered="
        f"{videos_with_hashtag:,}/{len(universe_ids):,} | unique hashtags={edges['HASHTAG_ID'].nunique():,}"
    )

    # One row per (video, hashtag, country): a video can only be listed once
    # under the same hashtag/country pair; keep the most recent listing.
    edges = edges.sort_values("DATA_EXTRACT_DATE").drop_duplicates(
        subset=["VIDEO_ID", "HASHTAG_ID", "COUNTRY_CODE"], keep="last"
    )

    video_hashtag_map = edges.rename(
        columns={
            "VIDEO_ID": "video_id",
            "HASHTAG_ID": "hashtag_id",
            "HASHTAG_NAME": "hashtag_name",
            "CATEGORY_NAME": "category_name",
            "COUNTRY_CODE": "country_code",
            "HASHTAG_TYPE": "hashtag_type",
            "DATA_EXTRACT_DATE": "data_extract_date",
        }
    )[
        [
            "video_id",
            "hashtag_id",
            "hashtag_name",
            "category_name",
            "country_code",
            "hashtag_type",
            "data_extract_date",
        ]
    ].sort_values(["video_id", "hashtag_id"]).reset_index(drop=True)

    relevant_hashtag_ids = set(video_hashtag_map["hashtag_id"].unique())

    overview = pd.read_csv(DATA / "hashtag_overview.csv")
    overview = overview[overview["HASHTAG_ID"].isin(relevant_hashtag_ids)].copy()
    overview["DATA_EXTRACT_DATE"] = pd.to_datetime(overview["DATA_EXTRACT_DATE"])

    missing_overview = relevant_hashtag_ids - set(overview["HASHTAG_ID"].unique())
    if missing_overview:
        log(
            f"WARNING: {len(missing_overview)} hashtags referenced by videos have "
            "no hashtag_overview row"
        )

    # A hashtag can appear under >1 CATEGORY_NAME on the same day (rare, ~3.7%
    # of hashtags). Keep the most recent snapshot per (hashtag, country) and
    # break remaining ties by best (lowest) RANK_POSITION_NUMBER.
    overview = overview.sort_values(
        ["DATA_EXTRACT_DATE", "RANK_POSITION_NUMBER"], ascending=[True, True]
    ).drop_duplicates(subset=["HASHTAG_ID", "COUNTRY_CODE"], keep="last")

    hashtag_datamart = overview.rename(
        columns={
            "COUNTRY_CODE": "country_code",
            "CATEGORY_NAME": "category_name",
            "HASHTAG_ID": "hashtag_id",
            "HASHTAG_NAME": "hashtag_name",
            "AUDIENCE_AGES": "audience_ages",
            "HASHTAG_TYPE": "hashtag_type",
            "DATA_EXTRACT_DATE": "data_extract_date",
            "RANK_POSITION_NUMBER": "rank_position_number",
            "RANK_CHANGE_NUMBER": "rank_change_number",
            "NEW_HASHTAG_FLAG": "new_hashtag_flag",
            "POST_COUNT": "post_count",
            "VIEW_COUNT": "view_count",
            "POST_GLOBAL_LIFETIME_COUNT": "post_global_lifetime_count",
            "VIEW_GLOBAL_LIFETIME_COUNT": "view_global_lifetime_count",
            "RANKING": "ranking",
        }
    )[
        [
            "hashtag_id",
            "country_code",
            "hashtag_name",
            "category_name",
            "hashtag_type",
            "audience_ages",
            "rank_position_number",
            "rank_change_number",
            "new_hashtag_flag",
            "post_count",
            "view_count",
            "post_global_lifetime_count",
            "view_global_lifetime_count",
            "ranking",
            "data_extract_date",
        ]
    ].sort_values(["hashtag_id", "country_code"]).reset_index(drop=True)

    log(
        f"hashtag_datamart rows={len(hashtag_datamart):,} "
        f"(unique hashtag_id={hashtag_datamart['hashtag_id'].nunique():,})"
    )
    return video_hashtag_map, hashtag_datamart


def main() -> None:
    PROCESSED.mkdir(exist_ok=True)

    video_datamart = build_video_datamart()
    universe_ids = set(video_datamart["video_id"])

    video_hashtag_map, hashtag_datamart = build_hashtag_tables(universe_ids)

    video_datamart.to_csv(PROCESSED / "video_datamart.csv", index=False, encoding="utf-8-sig")
    video_hashtag_map.to_csv(
        PROCESSED / "video_hashtag_map.csv", index=False, encoding="utf-8-sig"
    )
    hashtag_datamart.to_csv(
        PROCESSED / "hashtag_datamart.csv", index=False, encoding="utf-8-sig"
    )

    log("wrote video_datamart.csv, video_hashtag_map.csv, hashtag_datamart.csv")


if __name__ == "__main__":
    main()
