"""Downloads MovieLens Latest-Small dataset and generates preprocessed tenant data.

Source: https://files.grouplens.org/datasets/movielens/ml-latest-small.zip
License: Free for research/educational use with attribution (GroupLens Research).

Usage:
    python scripts/download_movielens.py
"""

from __future__ import annotations

import io
from pathlib import Path
import urllib.request
import zipfile
from collections import Counter

import pandas as pd

from src.utils.config import load_config, resolve_path
from src.utils.logger import get_logger

logger = get_logger(__name__)

MOVIELENS_URL = "https://files.grouplens.org/datasets/movielens/ml-latest-small.zip"
GENRES = [
    "Action",
    "Adventure",
    "Animation",
    "Children",
    "Comedy",
    "Crime",
    "Documentary",
    "Drama",
    "Fantasy",
    "Film-Noir",
    "Horror",
    "Musical",
    "Mystery",
    "Romance",
    "Sci-Fi",
    "Thriller",
    "War",
    "Western",
]


def download_and_extract_movielens(dest_dir: Path | None = None) -> Path:
    """Download MovieLens Latest-Small zip and extract CSVs to raw directory."""
    if dest_dir is None:
        dest_dir = resolve_path(Path("data") / "raw" / "movielens_small")
    dest_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Downloading MovieLens Latest-Small from {MOVIELENS_URL}...")
    req = urllib.request.Request(MOVIELENS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        data = resp.read()

    z = zipfile.ZipFile(io.BytesIO(data))
    for filename in ["movies.csv", "ratings.csv", "tags.csv", "links.csv", "README.txt"]:
        member = f"ml-latest-small/{filename}"
        if member in z.namelist():
            with open(dest_dir / filename, "wb") as f:
                f.write(z.read(member))

    logger.info(f"Extracted MovieLens raw files to {dest_dir}")
    return dest_dir


def prepare_movielens_tenant_csv(
    raw_dir: Path | None = None,
    output_csv: Path | None = None,
) -> pd.DataFrame:
    """Transform MovieLens ratings and movies into tenant-compatible customer and interaction features."""
    if raw_dir is None:
        raw_dir = resolve_path(Path("data") / "raw" / "movielens_small")
    if output_csv is None:
        output_csv = resolve_path(Path("data") / "raw" / "movielens_small.csv")

    movies_path = raw_dir / "movies.csv"
    ratings_path = raw_dir / "ratings.csv"

    if not movies_path.exists() or not ratings_path.exists():
        download_and_extract_movielens(raw_dir)

    movies = pd.read_csv(movies_path)
    ratings = pd.read_csv(ratings_path)

    # 1. Compute user profile statistics
    user_stats = (
        ratings.groupby("userId")
        .agg(
            rating_count=("rating", "count"),
            avg_rating=("rating", lambda x: round(float(x.mean()), 2)),
        )
        .reset_index()
    )

    # 2. Extract favorite genre per user based on positive interactions (rating >= 3.5)
    positive_ratings = ratings[ratings["rating"] >= 3.5].merge(
        movies[["movieId", "genres"]], on="movieId"
    )

    def get_fav_genre(user_group: pd.DataFrame) -> str:
        genres: list[str] = []
        for g_str in user_group["genres"]:
            if pd.notna(g_str) and g_str != "(no genres listed)":
                genres.extend(g_str.split("|"))
        counts = Counter(genres)
        if not counts:
            return "Drama"
        return counts.most_common(1)[0][0]

    fav_genres = (
        positive_ratings.groupby("userId")
        .apply(get_fav_genre, include_groups=False)
        .reset_index(name="favorite_genre")
    )
    user_df = user_stats.merge(fav_genres, on="userId", how="left")
    user_df["favorite_genre"] = user_df["favorite_genre"].fillna("Drama")

    # 3. Derive multi-genre interaction columns (Yes/No for each genre)
    for g in GENRES:
        col_name = g.lower().replace("-", "_")
        users_with_genre = set(
            positive_ratings[positive_ratings["genres"].str.contains(g, regex=False, na=False)]["userId"]
        )
        user_df[col_name] = user_df["userId"].apply(
            lambda uid: "Yes" if uid in users_with_genre else "No"
        )

    user_df = user_df.rename(columns={"userId": "user_id"})

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    user_df.to_csv(output_csv, index=False)
    logger.info(
        f"Saved MovieLens tenant CSV to {output_csv} with {len(user_df)} customers and {len(user_df.columns)} columns."
    )
    return user_df


def main() -> None:
    download_and_extract_movielens()
    prepare_movielens_tenant_csv()


if __name__ == "__main__":
    main()
