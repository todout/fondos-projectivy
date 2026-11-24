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

    det_es = tmdb_get(f"{mtype}/{item_id}", headers, {"language": "es-ES", "append_to_response": "alternative_titles"}) or {}
    det_en = tmdb_get(f"{mtype}/{item_id}", headers, {"language": "en-US"}) or {}
    credits = tmdb_get(f"{mtype}/{item_id}/credits", headers, {"language": "es-ES"}) or {}
    providers_data = tmdb_get(f"{mtype}/{item_id}/watch/providers", headers) or {}
    ext_ids = tmdb_get(f"{mtype}/{item_id}/external_ids", headers) or {}

    alt_block = det_es.get("alternative_titles") or {}
    alt_items = alt_block.get("titles") or alt_block.get("results") or []
    alt_titles = [a.get("title") for a in alt_items if a.get("title")]
    for orig_k in ("original_title", "original_name"):
        if det_es.get(orig_k):
            alt_titles.append(det_es[orig_k])

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
        "_tmdb_key": (mtype, item_id),
        "_poster_path": poster_path or "",
        "_alt_titles": alt_titles,
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


PLATFORM_LOGOS = {
    "Netflix": "https://image.tmdb.org/t/p/w92/rK1KljqmbvO9HQa1PBFLILWah72.png",
    "Prime Video": "https://image.tmdb.org/t/p/w92/gMZdpavHmxFNnLpMHwVxfqeux2g.png",
    "Disney+": "https://image.tmdb.org/t/p/w92/5eZ872CghnHFLB1j8grszbrx0dx.png",
    "Max": "https://image.tmdb.org/t/p/w92/skypuy7SXuugIQeYg0IglmzoKaS.png",
    "Apple TV+": "https://image.tmdb.org/t/p/w92/v9SnyvYt0U3KGgBH3Sbh3z4yODe.png",
}


def _extract_poster_path(url: str) -> str:
    """Extract TMDB poster filename (e.g. '/abc123.jpg') from a full poster_url."""
    if not url:
        return ""
    idx = url.rfind("/")
    return url[idx:] if idx != -1 else ""


def _resolve_tmdb_identity(title: str, mtype: str, headers: dict) -> tuple[tuple[str, int] | None, str]:
    """Resolve a streaming chart title (e.g. LatAm/AR Netflix title) to (tmdb_key, poster_path)."""
    if not title or not headers.get("Authorization") or headers["Authorization"] == "Bearer None":
        return None, ""
    for lang in ("es-MX", "es-ES"):
        res = tmdb_get(f"search/{mtype}", headers, {"query": title, "language": lang})
        items = (res or {}).get("results") or []
        if items:
            best = items[0]
            return (mtype, best["id"]), (best.get("poster_path") or "")
    return None, ""


def load_top10_maps(base_dir: Path, headers: dict | None = None) -> tuple[dict[str, dict], dict[tuple[str, int], dict], dict[str, dict]]:
    """Return (by_title, by_tmdb_key, by_poster_path) -> {'label', 'rank', 'platform', 'logo'}."""
    import re
    by_title: dict[str, dict] = {}
    by_tmdb: dict[tuple[str, int], dict] = {}
    by_poster: dict[str, dict] = {}

    # 1. Netflix Tudum Argentina en vivo (películas y series)
    for mtype, url in (
        ("movie", "https://www.netflix.com/tudum/top10/es/argentina"),
        ("tv", "https://www.netflix.com/tudum/top10/es/argentina/tv"),
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
                    clean_t = re.sub(r": Temporada \d+|: Miniserie|: Parte \d+", "", t_raw).strip()
                    norm = normalize_top_title(clean_t)
                    if not norm or clean_t.startswith("Top 10"):
                        continue
                    info = {
                        "label": f"Top #{idx} Netflix",
                        "rank": f"TOP {idx}",
                        "platform": "Netflix",
                        "logo": PLATFORM_LOGOS["Netflix"],
                    }
                    if norm not in by_title:
                        by_title[norm] = info
                    if headers:
                        tkey, ppath = _resolve_tmdb_identity(clean_t, mtype, headers)
                        if tkey and tkey not in by_tmdb:
                            by_tmdb[tkey] = info
                        if ppath and ppath not in by_poster:
                            by_poster[ppath] = info
        except Exception:
            pass

    # 2. Tops 10 de plataformas desde trailers.json (remoto actualizado o local)
    platform_labels = {
        "top 10 netflix": "Netflix",
        "top 10 disney+": "Disney+",
        "top 10 prime video": "Prime Video",
        "top 10 max": "Max",
        "top 10 apple tv+": "Apple TV+",
    }

    def _ingest_trailers_data(data: dict) -> None:
        for row in data.get("rows", []):
            cat_l = (row.get("category") or "").strip().lower()
            plat = platform_labels.get(cat_l)
            if not plat:
                continue
            for idx, item in enumerate((row.get("items") or [])[:10], 1):
                is_nf = (plat == "Netflix")
                info = {
                    "label": f"Top #{idx} {plat}" if is_nf else f"Top 10 {plat}",
                    "rank": f"TOP {idx}" if is_nf else "TOP 10",
                    "platform": plat,
                    "logo": PLATFORM_LOGOS.get(plat, ""),
                }
                norm = normalize_top_title(item.get("title") or "")
                if norm and norm not in by_title:
                    by_title[norm] = info
                ppath = _extract_poster_path(item.get("poster_url") or "")
                if ppath and ppath not in by_poster:
                    by_poster[ppath] = info

    loaded_remote = False
    try:
        r_tr = requests.get(
            "https://raw.githubusercontent.com/todout/trailers-projectivy/main/app/src/main/assets/trailers.json",
            timeout=10,
        )
        if r_tr.status_code == 200:
            _ingest_trailers_data(r_tr.json())
            loaded_remote = True
    except Exception:
        pass

    if not loaded_remote:
        possible_paths = [
            base_dir / "trailers.json",
            base_dir.parent / "trailers-projectivy" / "app" / "src" / "main" / "assets" / "trailers.json",
            Path("/home/pi/trailers-projectivy/app/src/main/assets/trailers.json"),
            base_dir / "trailers_cache.json",
        ]
        for p in possible_paths:
            if not p.exists():
                continue
            try:
                _ingest_trailers_data(json.loads(p.read_text(encoding="utf-8")))
                break
            except Exception:
                pass

    return by_title, by_tmdb, by_poster


def build_manifest(files: list[Path], raw_base: str, branch: str, base_dir: Path) -> list[dict]:
    """Build enriched JSON manifest with TMDB metadata, trailer, AR watch providers, and Top 10 badge."""
    load_dotenv(base_dir / ".env")
    tmdb_token = os.getenv("TMDB_TOKEN")
    omdb_key = os.getenv("OMDB_API_KEY")
    headers = {"accept": "application/json", "Authorization": f"Bearer {tmdb_token}"}
    cache_yt = load_trailers_cache_map(base_dir)
    top_by_title, top_by_tmdb, top_by_poster = load_top10_maps(base_dir, headers)

    base = f"{raw_base.rstrip('/')}/{branch}"
    manifest = []
    for p in files:
        title_guess = p.stem.replace("_", " ").strip()
        entry = {
            "title": title_guess,
            "url_img": f"{base}/{p.name}",
        }
        meta = fetch_tmdb_metadata(title_guess, headers, cache_yt, omdb_key)
        tmdb_key = meta.pop("_tmdb_key", None)
        poster_path = meta.pop("_poster_path", "")
        alt_titles = meta.pop("_alt_titles", [])
        entry.update(meta)

        top_info = None
        if tmdb_key and tmdb_key in top_by_tmdb:
            top_info = top_by_tmdb[tmdb_key]
        if not top_info and poster_path and poster_path in top_by_poster:
            top_info = top_by_poster[poster_path]
        if not top_info:
            for cand_title in (entry.get("title"), entry.get("title_en"), title_guess, *alt_titles):
                norm = normalize_top_title(cand_title or "")
                if norm and norm in top_by_title:
                    top_info = top_by_title[norm]
                    break
        if top_info:
            entry["top10"] = top_info["label"]
            entry["top10_rank"] = top_info["rank"]
            entry["top10_platform"] = top_info["platform"]
            entry["top10_logo"] = top_info["logo"]
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
