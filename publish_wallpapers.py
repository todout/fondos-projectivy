"""Publish the latest generated wallpapers and wallpapers.json to a GitHub orphan branch."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests
from dotenv import load_dotenv

DEFAULT_REPO_URL = "https://github.com/todout/fondos-projectivy.git"
DEFAULT_RAW_BASE = "https://raw.githubusercontent.com/todout/fondos-projectivy"

OVERRIDE_TRAILERS = {
    "LOS CREYENTES": "svGU1Mq5irI",
    "THE BELIEVERS": "svGU1Mq5irI",
    "SILO": "0I7Q1WtTf_c",
    "HOUSE": "BLt3K0phvX0",
}

COUNTRY_ES = {
    "US": "Estados Unidos",
    "GB": "Reino Unido",
    "ES": "España",
    "AR": "Argentina",
    "MX": "México",
    "FR": "Francia",
    "DE": "Alemania",
    "IT": "Italia",
    "CA": "Canadá",
    "AU": "Australia",
    "JP": "Japón",
    "KR": "Corea del Sur",
    "PL": "Polonia",
    "BR": "Brasil",
    "CO": "Colombia",
    "CL": "Chile",
    "SE": "Suecia",
    "DK": "Dinamarca",
    "NO": "Noruega",
    "IE": "Irlanda",
    "IN": "India",
    "CN": "China",
}


def get_latest_wallpapers(source_dir: Path, limit: int) -> list[Path]:
    """Return up to `limit` newest .jpg/.png/.webp files sorted newest first."""
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    files = [p for p in source_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def tmdb_get(path: str, headers: dict, params: dict | None = None) -> dict | None:
    if not headers.get("Authorization") or headers["Authorization"] == "Bearer None":
        return None
    try:
        r = requests.get(f"https://api.themoviedb.org/3/{path}", headers=headers, params=params or {}, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def search_youtube_trailer(query: str) -> str | None:
    import re
    import urllib.parse
    try:
        q = urllib.parse.quote(query)
        r = requests.get(
            f"https://www.youtube.com/results?search_query={q}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6,
        )
        if r.status_code == 200:
            ids = re.findall(r'"videoId":"([\w\-]{11})"', r.text)
            if ids:
                return ids[0]
    except Exception:
        pass
    return None


def pick_youtube_trailer(media_type: str, item_id: int, title_es: str, title_en: str, headers: dict) -> tuple[str | None, str]:
    # 1. TMDB Español Latino (es-MX)
    data_mx = tmdb_get(f"{media_type}/{item_id}/videos", headers, {"language": "es-MX"})
    yt_mx = [v for v in (data_mx or {}).get("results", []) if v.get("site") == "YouTube" and v.get("key")]
    tr_mx = [v for v in yt_mx if v.get("type") == "Trailer"]
    if tr_mx or yt_mx:
        return (tr_mx[0] if tr_mx else yt_mx[0])["key"], "Latino"

    # 2. YouTube search Español Latino
    type_str = "serie" if media_type == "tv" else "pelicula"
    yt_lat = search_youtube_trailer(f"{title_es} {type_str} trailer oficial español latino")
    if yt_lat:
        return yt_lat, "Latino"

    # 3. TMDB Español (es-ES)
    data_es = tmdb_get(f"{media_type}/{item_id}/videos", headers, {"language": "es-ES"})
    yt_es = [v for v in (data_es or {}).get("results", []) if v.get("site") == "YouTube" and v.get("key")]
    tr_es = [v for v in yt_es if v.get("type") == "Trailer"]
    if tr_es or yt_es:
        return (tr_es[0] if tr_es else yt_es[0])["key"], "Español"

    # 4. YouTube search Subtitulado en español
    search_title = title_es or title_en
    yt_sub = search_youtube_trailer(f"{search_title} trailer subtitulado español")
    if yt_sub:
        return yt_sub, "Subtitulado"

    # 5. Último recurso: TMDB en-US
    data_en = tmdb_get(f"{media_type}/{item_id}/videos", headers, {"language": "en-US"})
    yt_en = [v for v in (data_en or {}).get("results", []) if v.get("site") == "YouTube" and v.get("key")]
    tr_en = [v for v in yt_en if v.get("type") == "Trailer"]
    if tr_en or yt_en:
        return (tr_en[0] if tr_en else yt_en[0])["key"], "Original"
    return None, ""


def load_trailers_cache_map(base_dir: Path) -> dict[str, str]:
    cache_path = base_dir / "trailers_cache.json"
    out: dict[str, str] = {}
    if not cache_path.exists():
        return out
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        for row in data.get("rows", []):
            for item in row.get("items", []):
                t = (item.get("title") or "").strip().upper()
                yt = item.get("youtube_id")
                if t and yt and t not in out:
                    out[t] = yt
    except Exception:
        pass
    return out


def fetch_tmdb_metadata(title_guess: str, headers: dict, cache_yt: dict[str, str], omdb_key: str | None) -> dict:
    meta: dict = {}
    search = tmdb_get("search/multi", headers, {"query": title_guess, "language": "es-ES"})
    results = [r for r in (search or {}).get("results", []) if r.get("media_type") in ("movie", "tv")]
    if not results:
        return meta

    def _score(r: dict) -> tuple:
        cand = (r.get("title") or r.get("name") or "").strip().lower()
        exact = 1 if cand == title_guess.strip().lower() else 0
        yr_str = (r.get("release_date") or r.get("first_air_date") or "")[:4]
        yr = int(yr_str) if yr_str.isdigit() else 0
        recent = 1 if yr >= 2020 else 0
        return (exact, recent, r.get("popularity", 0))

    results.sort(key=_score, reverse=True)
    best = results[0]
    mtype = best["media_type"]
    item_id = best["id"]

    det_es = tmdb_get(f"{mtype}/{item_id}", headers, {"language": "es-ES"}) or {}
    det_en = tmdb_get(f"{mtype}/{item_id}", headers, {"language": "en-US"}) or {}
    credits = tmdb_get(f"{mtype}/{item_id}/credits", headers, {"language": "es-ES"}) or {}
    providers_data = tmdb_get(f"{mtype}/{item_id}/watch/providers", headers) or {}
    ext_ids = tmdb_get(f"{mtype}/{item_id}/external_ids", headers) or {}

    title_es = det_es.get("title") or det_es.get("name") or title_guess
    title_en = det_en.get("title") or det_en.get("name") or det_es.get("original_title") or det_es.get("original_name") or ""
    date_str = det_es.get("release_date") or det_es.get("first_air_date") or ""
    year = date_str[:4] if date_str else ""

    duration = ""
    if mtype == "movie":
        rt = det_es.get("runtime") or 0
        if rt:
            h, m = divmod(rt, 60)
            duration = f"{h}h {m}m" if h else f"{m}m"
    else:
        if det_es.get("type") == "Miniseries":
            duration = "Miniserie"
        else:
            seasons = det_es.get("number_of_seasons") or 0
            if seasons:
                duration = f"{seasons} Temporada{'s' if seasons > 1 else ''}"

    countries_raw = det_es.get("origin_country") or []
    if not countries_raw:
        countries_raw = [c.get("iso_3166_1", "") for c in det_es.get("production_countries", [])]
    countries = [COUNTRY_ES.get(c, c) for c in countries_raw if c]

    director = ""
    if mtype == "movie":
        dirs = [c.get("name") for c in credits.get("crew", []) if c.get("job") == "Director" and c.get("name")]
        director = ", ".join(dirs[:2])
    else:
        creators = [c.get("name") for c in det_es.get("created_by", []) if c.get("name")]
        director = ", ".join(creators[:2])

    cast = [c.get("name") for c in credits.get("cast", [])[:5] if c.get("name")]

    poster_path = det_es.get("poster_path") or det_en.get("poster_path")
    poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""

    vote_avg = det_es.get("vote_average") or 0
    rating = f"{vote_avg:.1f}" if vote_avg else ""

    yt_id, yt_lang = pick_youtube_trailer(mtype, item_id, title_es, title_en, headers)
    if not yt_id:
        key_up = title_es.upper()
        yt_id = OVERRIDE_TRAILERS.get(key_up) or cache_yt.get(key_up) or cache_yt.get(title_guess.upper())
        if yt_id:
            yt_lang = "Latino"

    ar_prov = (providers_data.get("results") or {}).get("AR") or {}
    raw_providers = ar_prov.get("flatrate") or ar_prov.get("free") or ar_prov.get("ads") or []
    providers = []
    seen_prov = set()
    for p in raw_providers:
        pname = p.get("provider_name")
        plogo = p.get("logo_path")
        if pname and plogo and pname not in seen_prov:
            seen_prov.add(pname)
            providers.append({
                "name": pname,
                "logo_url": f"https://image.tmdb.org/t/p/w92{plogo}",
            })

    awards = ""
    imdb_id = ext_ids.get("imdb_id")
    if omdb_key and imdb_id:
        try:
            omdb = requests.get(f"https://www.omdbapi.com/?i={imdb_id}&apikey={omdb_key}", timeout=6).json()
            aw = omdb.get("Awards", "")
            if aw and aw != "N/A":
                awards = aw
        except Exception:
            pass

    meta.update({
        "title": title_es,
        "title_en": title_en,
        "overview": (det_es.get("overview") or det_en.get("overview") or "").strip(),
        "media_type": "Película" if mtype == "movie" else "Serie",
        "year": year,
        "duration": duration,
        "rating": rating,
        "country": ", ".join(countries[:3]),
        "director": director,
        "cast": cast,
        "poster_url": poster_url,
        "youtube_id": yt_id or "",
        "trailer_lang": yt_lang,
        "providers": providers,
        "awards": awards,
    })
    return meta


def normalize_top_title(title: str) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", (title or "").strip().lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r":\s*(temporada\s*\d+|miniserie|parte\s*\d+)$", "", s)
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return " ".join(s.split())


def load_top10_map(base_dir: Path) -> dict[str, str]:
    """Return normalized_title -> badge label (e.g. 'Top #1 Netflix', 'Top 10 Prime Video')."""
    import re
    top_map: dict[str, str] = {}

    # 1. Netflix Tudum Argentina en vivo (películas y series)
    for url in (
        "https://www.netflix.com/tudum/top10/es/argentina",
        "https://www.netflix.com/tudum/top10/es/argentina/tv",
    ):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "es-AR,es;q=0.9"},
                timeout=10,
            )
            if r.status_code == 200:
                raw_t = re.findall(r'<td[^>]*class="title"[^>]*>.*?<button>([^<]+)</button>', r.text, re.DOTALL)
                if not raw_t:
                    raw_t = re.findall(r'data-uia="top10-card-logo"[^>]*><img [^>]*alt="([^"]+)"', r.text)
                for idx, t_raw in enumerate(raw_t[:10], 1):
                    clean_t = re.sub(r": Temporada \d+|: Miniserie", "", t_raw).strip()
                    norm = normalize_top_title(clean_t)
                    if norm and not clean_t.startswith("Top 10") and norm not in top_map:
                        top_map[norm] = f"Top #{idx} Netflix"
        except Exception:
            pass

    # 2. Tops 10 de plataformas desde trailers.json / trailers_cache.json
    platform_labels = {
        "top 10 netflix": "Netflix",
        "top 10 disney+": "Disney+",
        "top 10 prime video": "Prime Video",
        "top 10 max": "Max",
        "top 10 apple tv+": "Apple TV+",
    }
    possible_paths = [
        base_dir / "trailers.json",
        base_dir / "trailers_cache.json",
        base_dir.parent / "trailers-projectivy" / "app" / "src" / "main" / "assets" / "trailers.json",
        Path("/home/pi/trailers-projectivy/app/src/main/assets/trailers.json"),
    ]
    for p in possible_paths:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for row in data.get("rows", []):
                cat_l = (row.get("category") or "").strip().lower()
                plat = platform_labels.get(cat_l)
                if not plat:
                    continue
                for idx, item in enumerate((row.get("items") or [])[:10], 1):
                    norm = normalize_top_title(item.get("title") or "")
                    if norm and norm not in top_map:
                        top_map[norm] = f"Top #{idx} {plat}" if plat == "Netflix" else f"Top 10 {plat}"
            break
        except Exception:
            pass

    return top_map


def build_manifest(files: list[Path], raw_base: str, branch: str, base_dir: Path) -> list[dict]:
    """Build enriched JSON manifest with TMDB metadata, trailer, AR watch providers, and Top 10 badge."""
    load_dotenv(base_dir / ".env")
    tmdb_token = os.getenv("TMDB_TOKEN")
    omdb_key = os.getenv("OMDB_API_KEY")
    headers = {"accept": "application/json", "Authorization": f"Bearer {tmdb_token}"}
    cache_yt = load_trailers_cache_map(base_dir)
    top10_map = load_top10_map(base_dir)

    base = f"{raw_base.rstrip('/')}/{branch}"
    manifest = []
    for p in files:
        title_guess = p.stem.replace("_", " ").strip()
        entry = {
            "title": title_guess,
            "url_img": f"{base}/{p.name}",
        }
        meta = fetch_tmdb_metadata(title_guess, headers, cache_yt, omdb_key)
        entry.update(meta)
        badge = ""
        for cand_title in (entry.get("title"), entry.get("title_en"), title_guess):
            norm = normalize_top_title(cand_title or "")
            if norm and norm in top10_map:
                badge = top10_map[norm]
                break
        if badge:
            entry["top10"] = badge
        manifest.append(entry)
    return manifest


def publish(source_dir: Path, branch: str, limit: int, repo_url: str, raw_base: str, dry_run: bool) -> None:
    files = get_latest_wallpapers(source_dir, limit)
    if not files:
        raise SystemExit(f"No wallpaper images found in {source_dir}")

    base_dir = Path(__file__).resolve().parent
    manifest = build_manifest(files, raw_base, branch, base_dir)
    if dry_run:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for f in files:
            shutil.copy2(f, tmp_path / f.name)
        (tmp_path / "wallpapers.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        def git(*args: str) -> None:
            subprocess.run(["git", "-C", str(tmp_path), *args], check=True)

        git("init")
        git("checkout", "-b", branch)
        git("add", ".")
        git("commit", "-m", f"Update {len(files)} wallpapers")
        git("remote", "add", "origin", repo_url)
        git("push", "--force", "origin", branch)

    print(f"Published {len(files)} wallpapers to {repo_url} ({branch}).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish latest wallpapers to GitHub branch.")
    parser.add_argument("--source", default="tmdbbackgrounds", help="Folder with generated wallpapers")
    parser.add_argument("--branch", default="wallpapers", help="Target orphan branch name")
    parser.add_argument("--limit", type=int, default=15, help="Number of latest wallpapers to publish")
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL, help="Git remote URL")
    parser.add_argument("--raw-base", default=DEFAULT_RAW_BASE, help="GitHub raw base URL")
    parser.add_argument("--dry-run", action="store_true", help="Print wallpapers.json without pushing")
    args = parser.parse_args()

    source_dir = Path(args.source)
    if not source_dir.is_absolute():
        source_dir = Path(__file__).resolve().parent / source_dir
    publish(source_dir, args.branch, args.limit, args.repo_url, args.raw_base, args.dry_run)


if __name__ == "__main__":
    main()
