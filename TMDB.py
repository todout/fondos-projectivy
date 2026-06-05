import requests
from PIL import Image, ImageDraw, ImageFont
from PIL import Image as PILImage
import unicodedata
from io import BytesIO
import os
import json
import textwrap
from datetime import datetime
import praw
from dotenv import load_dotenv
import re
import urllib.parse
from bs4 import BeautifulSoup

# Intentar importar traductor, si falla lo desactivamos
try:
    from googletrans import Translator
    translator = Translator()
except ImportError:
    translator = None

# Cargar variables de entorno desde .env
load_dotenv()

# Base URL de la API de TMDB
tmdb_url = "https://api.themoviedb.org/3/"
headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {os.getenv('TMDB_TOKEN')}"
}

# Configuración básica
date_str = datetime.now().strftime("%Y%m%d")
numberofmovies = int(os.getenv("TMDB_NUMBER_OF_MOVIES", "2"))
numberoftvshows = int(os.getenv("TMDB_NUMBER_OF_TV_SHOWS", "2"))
current_year = datetime.now().year
background_dir = "tmdbbackgrounds"

# Configuración de Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
FORCE_REGENERATE = os.getenv("TMDB_FORCE_REGENERATE", "False").lower() == "true"


# Descargar fuentes adicionales si faltan
font_bold_path = 'Roboto-Black.ttf'
if not os.path.exists(font_bold_path):
    try:
        print("Descargando fuente Roboto-Black.ttf...")
        r_f = requests.get('https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Black.ttf', timeout=10)
        if r_f.status_code == 200:
            with open(font_bold_path, 'wb') as f_b:
                f_b.write(r_f.content)
            print("Fuente Roboto-Black.ttf descargada con éxito.")
    except Exception as e:
        print(f"Error descargando Roboto-Black: {e}")

# Cargar Exclusiones Dinámicas
exclude_genres_env = os.getenv('TMDB_EXCLUDE_GENRES', 'Animación, Ciencia ficción, Terror, Sci-Fi & Fantasy')
excluded_genres = {g.strip() for g in exclude_genres_env.split(',') if g.strip()}

exclude_languages_env = os.getenv('TMDB_EXCLUDE_LANGUAGES', 'zh, ko')
excluded_languages = {l.strip().lower() for l in exclude_languages_env.split(',') if l.strip()}

exclude_movies_env = os.getenv('TMDB_EXCLUDE_MOVIES', '')
excluded_movies = {int(mid.strip()) for mid in exclude_movies_env.split(',') if mid.strip().isdigit()}

exclude_tv_env = os.getenv('TMDB_EXCLUDE_TV', '')
excluded_tv = {int(tid.strip()) for tid in exclude_tv_env.split(',') if tid.strip().isdigit()}

FALLBACK_GENRES_ES = {
    28: "Acción", 12: "Aventura", 16: "Animación", 35: "Comedia", 80: "Crimen",
    99: "Documental", 18: "Drama", 10751: "Familia", 14: "Fantasía", 36: "Historia",
    27: "Terror", 10402: "Música", 9648: "Misterio", 10749: "Romance",
    878: "Ciencia ficción", 10770: "Película de TV", 53: "Suspenso", 10752: "Bélica",
    37: "Western", 10759: "Action & Adventure", 10762: "Kids", 10763: "News",
    10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk",
    10768: "War & Politics"
}

FALLBACK_GENRES_EN = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime",
    99: "Documentary", 18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History",
    27: "Horror", 10402: "Music", 9648: "Mystery", 10749: "Romance",
    878: "Science Fiction", 10770: "TV Movie", 53: "Thriller", 10752: "War",
    37: "Western", 10759: "Action & Adventure", 10762: "Kids", 10763: "News",
    10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk",
    10768: "War & Politics"
}

genre_map = {}
genre_name_to_id = {}

# Caché de películas/series ya publicadas para evitar duplicados y consultas innecesarias
POSTED_CACHE_FILE = "posted_cache.json"
already_posted_set = set()

# Umbrales mínimos de votos para mostrar calificaciones y validar recomendaciones
VOTE_THRESHOLDS = {
    "metacritic": 10,
    "filmaffinity": 20,
    "imdb": 50,
    "tmdb": 50,
    "letterboxd": 50,
    "rottentomatoes": 50
}

def load_posted_cache(subreddit=None):
    global already_posted_set
    already_posted_set = set()
    if os.path.exists(POSTED_CACHE_FILE):
        try:
            with open(POSTED_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    already_posted_set = set(data)
            print(f"Cargados {len(already_posted_set)} títulos publicados desde el caché local.")
        except Exception as e:
            print(f"Error al cargar caché local de títulos publicados: {e}")
            
    if subreddit:
        print("Sincronizando títulos publicados con Reddit...")
        try:
            reddit_titles = set()
            for sub in subreddit.new(limit=1000):
                title_norm = normalize_title(sub.title).upper()
                reddit_titles.add(title_norm)
            
            before_len = len(already_posted_set)
            already_posted_set.update(reddit_titles)
            added = len(already_posted_set) - before_len
            print(f"Sincronizados {len(reddit_titles)} títulos desde Reddit. Añadidos {added} nuevos al caché.")
            save_posted_cache()
        except Exception as e:
            print(f"Error al sincronizar con Reddit: {e}")

def save_posted_cache():
    try:
        with open(POSTED_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(already_posted_set), f, ensure_ascii=False, indent=4)
        print("Caché de títulos publicados guardado localmente.")
    except Exception as e:
        print(f"Error al guardar caché de títulos publicados: {e}")

def was_already_posted_cached(title):
    if not title:
        return False
    title_norm = normalize_title(str(title)).upper()
    return title_norm in already_posted_set

# Crear directorio de fondos
os.makedirs(background_dir, exist_ok=True)

def download_favicons():
    domains = {
        "imdb": "imdb.com",
        "letterboxd": "letterboxd.com",
        "rottentomatoes": "rottentomatoes.com",
        "filmaffinity": "filmaffinity.com",
        "metacritic": "metacritic.com",
        "tmdb": "themoviedb.org"
    }
    cwd = os.path.dirname(os.path.abspath(__file__))
    for name, domain in domains.items():
        path = os.path.join(cwd, f"{name}_favicon.png")
        if not os.path.exists(path):
            try:
                print(f"Descargando favicon para {name}...")
                url = f"https://www.google.com/s2/favicons?sz=64&domain={domain}"
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    with open(path, "wb") as f:
                        f.write(r.content)
                    print(f"Favicon de {name} guardado con éxito.")
            except Exception as e:
                print(f"Error descargando favicon de {name}: {e}")

def slugify(text):
    if not text:
        return ""
    normalized = unicodedata.normalize('NFKD', text)
    ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
    ascii_text = ascii_text.lower()
    cleaned = re.sub(r'[^a-z0-9\s\-]', '', ascii_text)
    slug = re.sub(r'[\s\-]+', '-', cleaned)
    return slug.strip('-')

def clean_title_url(text):
    if not text:
        return ""
    normalized = unicodedata.normalize('NFKD', text)
    ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
    ascii_text = ascii_text.lower()
    cleaned = re.sub(r'[^a-z0-9\s_\-]', '', ascii_text)
    return cleaned

def format_votes(count):
    if not count:
        return ""
    try:
        if isinstance(count, str):
            count = count.replace(".", "").replace(",", "").strip()
            count = re.sub(r'[^\d]', '', count)
        val = int(count)
        if val >= 1000000:
            return f"{val / 1000000:.1f}M".replace(".0M", "M")
        elif val >= 1000:
            return f"{val / 1000:.0f}k"
        else:
            return str(val)
    except Exception:
        return str(count)

def parse_votes_to_int(votes):
    if not votes:
        return 0
    if isinstance(votes, (int, float)):
        return int(votes)
    try:
        clean = str(votes).replace(",", "").replace(" ", "").strip()
        if "." in clean:
            parts = clean.split(".")
            if len(parts) == 2 and len(parts[1]) == 3:
                clean = clean.replace(".", "")
        clean = clean.lower()
        if clean.endswith('k'):
            return int(float(clean[:-1]) * 1000)
        elif clean.endswith('m'):
            return int(float(clean[:-1]) * 1000000)
        return int(clean)
    except Exception:
        return 0

def get_imdb_rating(imdb_id):
    omdb_key = os.getenv("OMDB_API_KEY")
    if not omdb_key or not imdb_id:
        return None
    url = f"http://www.omdbapi.com/?i={imdb_id}&apikey={omdb_key}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            rating = data.get("imdbRating")
            votes = data.get("imdbVotes")
            if rating and rating != "N/A":
                try:
                    return {"rating": float(rating), "votes": format_votes(votes), "raw_votes": parse_votes_to_int(votes)}
                except ValueError:
                    pass
    except Exception as e:
        print(f"Error al obtener calificación de IMDb vía OMDb: {e}")
    return None

def get_letterboxd_rating(original_title, english_title, spanish_title, year=None):
    slugs = []
    if english_title:
        slugs.append(slugify(english_title))
    if original_title:
        slugs.append(slugify(original_title))
    if spanish_title:
        slugs.append(slugify(spanish_title))
        
    seen = set()
    unique_slugs = []
    for s in slugs:
        if s and s not in seen:
            seen.add(s)
            unique_slugs.append(s)
            
    # Intentar primero con el año de lanzamiento para evitar colisión de títulos
    urls = []
    for slug in unique_slugs:
        if year:
            urls.append(f"https://letterboxd.com/film/{slug}-{year}/")
        urls.append(f"https://letterboxd.com/film/{slug}/")
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                script = soup.find("script", {"type": "application/ld+json"})
                if script:
                    content = script.string.strip()
                    if content.startswith("/* <![CDATA[ */"):
                        content = content[len("/* <![CDATA[ */"):].strip()
                    if content.endswith("/* ]]> */"):
                        content = content[:-len("/* ]]> */")].strip()
                    data = json.loads(content)
                    
                    # Validar año para evitar colisiones de títulos
                    if year:
                        released_events = data.get("releasedEvent", [])
                        if not isinstance(released_events, list):
                            released_events = [released_events]
                        
                        movie_years = []
                        for event in released_events:
                            if isinstance(event, dict) and "startDate" in event:
                                movie_years.append(str(event["startDate"])[:4])
                        if "dateCreated" in data:
                            movie_years.append(str(data["dateCreated"])[:4])
                            
                        try:
                            year_int = int(year)
                            target_years = {str(year_int), str(year_int - 1), str(year_int + 1)}
                            if movie_years and not any(y in target_years for y in movie_years):
                                continue
                        except ValueError:
                            pass

                    agg = data.get("aggregateRating", {})
                    rating = agg.get("ratingValue")
                    votes = agg.get("ratingCount")
                    if rating is not None:
                        # Normalizar nota de Letterboxd (escala de 5 a escala de 10)
                        return {"rating": round(float(rating) * 2, 1), "votes": format_votes(votes), "raw_votes": parse_votes_to_int(votes)}
        except Exception:
            pass
    return None

def get_rottentomatoes_rating(original_title, english_title, spanish_title, is_movie):
    titles = [english_title, original_title, spanish_title]
    unique_titles = []
    for t in titles:
        if t and t not in unique_titles:
            unique_titles.append(t)
            
    prefix = "m" if is_movie else "tv"
    urls = []
    for t in unique_titles:
        cleaned = clean_title_url(t)
        slug_under = re.sub(r'[\s\-_\s]+', '_', cleaned).strip('_')
        urls.append(f"https://www.rottentomatoes.com/{prefix}/{slug_under}")
        slug_hyphen = re.sub(r'[\s\-_\s]+', '-', cleaned).strip('-')
        urls.append(f"https://www.rottentomatoes.com/{prefix}/{slug_hyphen}")
        
    seen = set()
    unique_urls = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)
            
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    for url in unique_urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                script = soup.find("script", {"type": "application/ld+json"})
                if script:
                    data = json.loads(script.string)
                    agg = data.get("aggregateRating", {})
                    rating = agg.get("ratingValue")
                    votes = agg.get("ratingCount")
                    if rating is not None:
                        # Normalizar de porcentaje a escala de 10
                        return {"rating": round(float(rating) / 10, 1), "votes": format_votes(votes), "raw_votes": parse_votes_to_int(votes)}
        except Exception:
            pass
    return None

def get_filmaffinity_rating(title):
    search_url = f"https://www.filmaffinity.com/es/search.php?stext={urllib.parse.quote(title)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "es-ES,es;q=0.9"
    }
    try:
        r = requests.get(search_url, headers=headers, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            
            # Redirección directa al detalle
            rat_avg = soup.find("div", id="movie-rat-avg")
            if rat_avg:
                count_rat = soup.find("div", id="movie-count-rat")
                rating_str = rat_avg.text.strip().replace(",", ".")
                votes_str = count_rat.text.strip() if count_rat else ""
                try:
                    return {"rating": float(rating_str), "votes": format_votes(votes_str), "raw_votes": parse_votes_to_int(votes_str)}
                except ValueError:
                    pass
            
            # Si no es directo, tomar el primer resultado
            first_result = soup.find("div", class_="mc-title")
            if first_result:
                a = first_result.find("a")
                if a and a.get("href"):
                    movie_url = a.get("href")
                    r_movie = requests.get(movie_url, headers=headers, timeout=10)
                    if r_movie.status_code == 200:
                        soup_movie = BeautifulSoup(r_movie.text, "html.parser")
                        rat_avg = soup_movie.find("div", id="movie-rat-avg")
                        count_rat = soup_movie.find("div", id="movie-count-rat")
                        if rat_avg:
                            rating_str = rat_avg.text.strip().replace(",", ".")
                            votes_str = count_rat.text.strip() if count_rat else ""
                            try:
                                return {"rating": float(rating_str), "votes": format_votes(votes_str), "raw_votes": parse_votes_to_int(votes_str)}
                            except ValueError:
                                pass
    except Exception as e:
        print(f"Error al obtener calificación de FilmAffinity: {e}")
    return None

def get_metacritic_rating(title, is_movie):
    slugs = [slugify(title)]
    prefix = "movie" if is_movie else "tv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    for slug in slugs:
        url = f"https://www.metacritic.com/{prefix}/{slug}/"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                script = soup.find("script", {"type": "application/ld+json"})
                if script:
                    data = json.loads(script.string)
                    agg = data.get("aggregateRating", {})
                    rating = agg.get("ratingValue")
                    votes = agg.get("reviewCount")
                    if rating is not None:
                        # Normalizar metascore de 100 a escala de 10
                        return {"rating": round(float(rating) / 10, 1), "votes": format_votes(votes), "raw_votes": parse_votes_to_int(votes)}
        except Exception:
            pass
    return None

def get_all_ratings_for_media(tmdb_id, is_movie, tmdb_rating=None, tmdb_votes=None):
    media_type = "movie" if is_movie else "tv"
    details_es = tmdb_get(f"{media_type}/{tmdb_id}", {"language": "es-ES"})
    details_en = tmdb_get(f"{media_type}/{tmdb_id}", {"language": "en-US"})
    
    if not details_es:
        return {}
        
    imdb_id = details_es.get("imdb_id")
    if not imdb_id and not is_movie:
        ext_ids = tmdb_get(f"tv/{tmdb_id}/external_ids")
        if ext_ids:
            imdb_id = ext_ids.get("imdb_id")
            
    original_title = details_es.get("original_title") or details_es.get("original_name")
    spanish_title = details_es.get("title") or details_es.get("name")
    english_title = details_en.get("title") or details_en.get("name") if details_en else spanish_title
    
    ratings = {}
    
    # TMDB rating
    t_rating = tmdb_rating or details_es.get("vote_average")
    t_votes = tmdb_votes or details_es.get("vote_count")
    if t_rating:
        ratings["tmdb"] = {"rating": round(float(t_rating), 1), "votes": format_votes(t_votes), "raw_votes": parse_votes_to_int(t_votes)}
        
    # IMDb rating
    imdb_res = get_imdb_rating(imdb_id)
    if imdb_res:
        ratings["imdb"] = imdb_res
        
    # Letterboxd rating (películas únicamente)
    if is_movie:
        date_key = 'release_date' if is_movie else 'first_air_date'
        year = details_es.get(date_key, '')[:4]
        lb_res = get_letterboxd_rating(original_title, english_title, spanish_title, year=year)
        if lb_res:
            ratings["letterboxd"] = lb_res
            
    # Rotten Tomatoes rating
    rt_res = get_rottentomatoes_rating(original_title, english_title, spanish_title, is_movie)
    if rt_res:
        ratings["rottentomatoes"] = rt_res
        
    # FilmAffinity rating
    fa_res = get_filmaffinity_rating(spanish_title)
    if fa_res:
        ratings["filmaffinity"] = fa_res
        
    # Metacritic rating
    mc_res = get_metacritic_rating(english_title, is_movie)
    if mc_res:
        ratings["metacritic"] = mc_res
        
    return ratings

# Normalizar título para filename y Reddit title
def normalize_title(title):
    return " ".join(title.replace("_", " ").replace(date_str, "").split()).strip()

# Helper centralizado para consultas TMDB
def tmdb_get(endpoint, params=None):
    try:
        r = requests.get(f"{tmdb_url}{endpoint}", headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"TMDB API error {r.status_code} para {endpoint}")
            return None
    except Exception as e:
        print(f"Error de conexión a TMDB API {endpoint}: {e}")
        return None

# Cargar géneros y crear mapeos bidireccionales
def load_genres():
    global genre_map, genre_name_to_id
    genres_es = []
    genres_en = []
    
    # Intenta cargar desde la API de TMDB
    api_success = False
    try:
        data_es = tmdb_get("genre/movie/list", {"language": "es-ES"})
        data_es_tv = tmdb_get("genre/tv/list", {"language": "es-ES"})
        data_en = tmdb_get("genre/movie/list", {"language": "en-US"})
        data_en_tv = tmdb_get("genre/tv/list", {"language": "en-US"})
        
        if data_es and data_es_tv and data_en and data_en_tv:
            genres_es.extend(data_es.get('genres', []))
            genres_es.extend(data_es_tv.get('genres', []))
            genres_en.extend(data_en.get('genres', []))
            genres_en.extend(data_en_tv.get('genres', []))
            api_success = True
    except Exception as e:
        print(f"Error cargando géneros desde API de TMDB: {e}")
        
    cache_path = "genres_cache.json"
    if api_success:
        # Guardar en caché
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"genres_es": genres_es, "genres_en": genres_en}, f, indent=2, ensure_ascii=False)
            print("Lista de géneros guardada en caché local.")
        except Exception as e:
            print(f"No se pudo guardar la caché de géneros: {e}")
    else:
        # Intentar cargar desde caché
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    genres_es = cached_data.get("genres_es", [])
                    genres_en = cached_data.get("genres_en", [])
                    print("Lista de géneros cargada desde caché local.")
                    api_success = True
            except Exception as e:
                print(f"Error cargando caché de géneros: {e}")
                
    # Fallback total con diccionarios hardcodeados si todo lo anterior falló
    if not genres_es or not genres_en:
        print("Usando géneros de fallback hardcodeados.")
        genres_es = [{"id": gid, "name": name} for gid, name in FALLBACK_GENRES_ES.items()]
        genres_en = [{"id": gid, "name": name} for gid, name in FALLBACK_GENRES_EN.items()]
        
    # Mapeo de ID -> Nombre en español
    genre_map = {g['id']: g['name'] for g in genres_es}
    
    # Ajuste de traducción específico
    for gid, name in list(genre_map.items()):
        if name == 'Suspense':
            genre_map[gid] = 'Suspenso'
            
    # Mapeo Nombre -> ID (tanto inglés como español)
    genre_name_to_id = {}
    for g in genres_es:
        name = g['name']
        if name == 'Suspense':
            name = 'Suspenso'
        genre_name_to_id[name.lower().strip()] = g['id']
        
    for g in genres_en:
        genre_name_to_id[g['name'].lower().strip()] = g['id']
        
    # Variaciones comunes
    genre_name_to_id['suspense'] = genre_name_to_id.get('suspenso') or 9648

# Cargar gustos del usuario
def load_preferences():
    path = "user_preferences.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error cargando user_preferences.json: {e}")
            
    # Fallback inicial en caso de error
    return {
        "likes": [{"title": t} for t in ["Contratiempo", "El ciudadano ilustre", "Un cuento chino", "El hombre de al lado", "Mi obra maestra", "Sin retorno", "El patrón, radiografía de un crimen", "Crímenes de familia", "El cuento de las comadrejas"]],
        "dislikes": [{"title": t} for t in ["El aura", "Tesis sobre un homicidio", "Plata quemada", "Al final del túnel", "Nieve negra", "Sin hijos"]],
        "neutral": []
    }

def resize_image(img, height):
    ratio = height / img.height
    return img.resize((int(img.width * ratio), height))

def clean_filename(name):
    return ''.join(c if c.isalnum() or c in '._-' else '_' for c in name)

def draw_multiline_text(draw, pos, text, font, fill, spacing, shadow_color=None, shadow_offset=2):
    if shadow_color:
        draw.multiline_text((pos[0]+shadow_offset, pos[1]+shadow_offset), text, font=font, fill=shadow_color, spacing=spacing)
    draw.multiline_text(pos, text, font=font, fill=fill, spacing=spacing)

def format_duration(minutes):
    if not isinstance(minutes, int):
        return ''
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m" if h else f"{m}m"

# Limpiar caracteres incompatibles con fuentes latinas para evitar cuadrados (tofu)
def sanitize_title_font(text):
    cleaned = []
    for c in text:
        o = ord(c)
        # Permitir caracteres de bloques básicos de Europa y América (Latin extended, puntuación común, etc.)
        if 32 <= o <= 500 or c.isspace() or c in ['–', '—', '’', '‘', '“', '”']:
            cleaned.append(c)
    result = "".join(cleaned).strip()
    if not result:
        return "Recomendación"
    return result

# Dividir un título largo en exactamente dos líneas equilibradas
def split_title_into_two_lines(title):
    words = title.split(' ')
    if len(words) <= 1:
        return title
    best_diff = float('inf')
    best_split = len(words) // 2
    for i in range(1, len(words)):
        line1 = " ".join(words[:i])
        line2 = " ".join(words[i:])
        diff = abs(len(line1) - len(line2))
        if diff < best_diff:
            best_diff = diff
            best_split = i
    line1 = " ".join(words[:best_split])
    line2 = " ".join(words[best_split:])
    return f"{line1}\n{line2}"

# Extraer el color dominante vibrante de la imagen para el título fallback
def extract_accent_color(img):
    try:
        small_img = img.resize((100, 100))
        paletted = small_img.convert('P', palette=PILImage.Palette.ADAPTIVE, colors=16)
        palette = paletted.getpalette()
        color_counts = paletted.getcolors()
        
        candidates = []
        fallback_candidates = []
        for count, index in color_counts:
            r = palette[index*3]
            g = palette[index*3 + 1]
            b = palette[index*3 + 2]
            
            brightness = 0.299*r + 0.587*g + 0.114*b
            max_val = max(r, g, b)
            min_val = min(r, g, b)
            saturation = (max_val - min_val) / max_val if max_val > 0 else 0
            
            # Buscar colores vibrantes destacados con buen contraste
            if 60 < brightness < 220 and saturation > 0.15:
                # Priorizar fuertemente la saturación para destacar colores vivos sobre tonos de piel/neutros
                score = count * (saturation ** 3)
                candidates.append((score, (r, g, b)))
                
            # Fallback en caso de que no haya colores altamente saturados
            if 80 < brightness < 230 and saturation > 0.05:
                score = count * saturation
                fallback_candidates.append((score, (r, g, b)))
                
        import colorsys
        def make_color_vibrant(rgb):
            r_val, g_val, b_val = [x / 255.0 for x in rgb]
            h, s, v = colorsys.rgb_to_hsv(r_val, g_val, b_val)
            v = max(v, 0.92) # Asegurar brillo mínimo del 92% para legibilidad
            s = max(s, 0.55) # Asegurar saturación mínima del 55% para vivacidad
            r_new, g_new, b_new = colorsys.hsv_to_rgb(h, s, v)
            return (int(r_new * 255), int(g_new * 255), int(b_new * 255))

        if candidates:
            candidates.sort(reverse=True)
            return make_color_vibrant(candidates[0][1])
        elif fallback_candidates:
            fallback_candidates.sort(reverse=True)
            return make_color_vibrant(fallback_candidates[0][1])
            
        return (255, 105, 180) # Fallback fucsia si todo falla
    except Exception as e:
        print(f"Error extrayendo color de acento: {e}")
        return (255, 105, 180)


def get_logo_path(mtype, mid):
    r_json = tmdb_get(f"{mtype}/{mid}/images")
    if not r_json:
        return None
    logos = r_json.get('logos', [])
    es = [l for l in logos if l.get('iso_639_1') == 'es']
    en = [l for l in logos if l.get('iso_639_1') == 'en']
    none = [l for l in logos if l.get('iso_639_1') is None]
    candidates = es or en or none
    if not candidates:
        return None
        
    # Filtrar candidatos por relación de aspecto horizontal razonable (evitar créditos/banners muy finos)
    filtered_candidates = [l for l in candidates if 1.5 <= l['width']/l['height'] <= 8.0]
    if filtered_candidates:
        candidates = filtered_candidates
        
    sorted_by_ratio = sorted(candidates, key=lambda l: l['width']/l['height'], reverse=True)[:2]
    
    def luminance(path):
        try:
            # Usar tamaño pequeño w185 para calcular luminancia de forma rápida y eficiente
            data = requests.get('https://image.tmdb.org/t/p/w185' + path, timeout=10).content
            img = PILImage.open(BytesIO(data)).convert('RGBA').resize((50,50))
            pix = img.load()
            pixels = []
            for y in range(img.height):
                for x in range(img.width):
                    p = pix[x, y]
                    if p[3] > 0:
                        pixels.append(p)
            if not pixels:
                return 0
            return sum(0.299*r+0.587*g+0.114*b for r,g,b,a in pixels)/len(pixels)
        except:
            return 0
            
    if len(sorted_by_ratio) == 1:
        return sorted_by_ratio[0]['file_path']
        
    best = sorted_by_ratio[0] if luminance(sorted_by_ratio[0]['file_path']) >= luminance(sorted_by_ratio[1]['file_path']) else sorted_by_ratio[1]
    return best['file_path']


def summarize_with_gemini(title, overview, reason=None):
    if not GEMINI_API_KEY:
        return None
        
    prompt = f"""Eres un editor de texto experto. Tu tarea es condensar y estructurar la sinopsis y el motivo de recomendación de la obra '{title}' en español.
    
    Sinopsis original:
    {overview}
    """
    if reason:
        prompt += f"\nMotivo de recomendación original:\n{reason}\n"
        
    prompt += """
    Instrucciones de formato y longitud:
    1. Debes generar exactamente DOS bloques separados por un único salto de línea simple (\\n), es decir, un punto y aparte inmediato sin ninguna línea en blanco o vacía entre ellos.
    2. El BLOQUE 1 debe ser la sinopsis condensada pero informativa de la trama (entre 260 y 310 caracteres).
    3. El BLOQUE 2 debe ser el motivo de recomendación de por qué le gustará al usuario (entre 110 y 140 caracteres). IMPORTANTE: No incluyas ningún prefijo del estilo "Por qué te gustará:" o "Te gustará:". Escribe el motivo directamente con naturalidad en español.
    4. La suma total de caracteres de ambos bloques combinados no debe superar los 450 caracteres bajo ninguna circunstancia.
    5. Devuelve ÚNICAMENTE el texto resultante en español, sin comillas externas, sin bloques de código, y sin texto introductorio.
    """
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    try:
        r = requests.post(url, json=payload, timeout=45)
        if r.status_code == 200:
            resp_json = r.json()
            summary = resp_json['candidates'][0]['content']['parts'][0]['text'].strip()
            # Limpiar comillas si las hay
            if (summary.startswith('"') and summary.endswith('"')) or (summary.startswith("'") and summary.endswith("'")):
                summary = summary[1:-1].strip()
            # Limpiar markdown de bloques de código por si acaso
            if summary.startswith("```"):
                lines = summary.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].strip() == "```":
                    lines = lines[:-1]
                summary = "\n".join(lines).strip()
            return summary
    except Exception as e:
        print(f"Error al resumir con Gemini: {e}")
    return None



# Procesar y componer imagen
def process_image(image_url, title, overview, is_movie, genre_ids, year, ratings, duration=None, seasons=None, media_type=None, media_id=None, short_overview=None, reason=None, tv_type=None):
    filename = os.path.join(background_dir, clean_filename(title) + '.jpg')
    if os.path.exists(filename) and not FORCE_REGENERATE:
        print(f"Imagen ya existe: {filename}")
        return True
        
    # Validar que tenga al menos una plataforma con calificación aceptable (>= 6.5) y suficientes votos
    has_valid_rating = False
    if isinstance(ratings, dict):
        for platform, data in ratings.items():
            p_rating = data.get('rating')
            p_votes = data.get('raw_votes', 0)
            threshold = VOTE_THRESHOLDS.get(platform, 50)
            if p_rating is not None and p_rating >= 6.5 and p_votes >= threshold:
                has_valid_rating = True
                break
                
    if not has_valid_rating:
        print(f"Saltando '{title}' (ID: {media_id}) por no tener calificaciones suficientes/buenas (rating >= 6.5 y votos suficientes).")
        return False
        
    # Obtener descripción en español si falta
    if not overview.strip():
        det = tmdb_get(f"{media_type}/{media_id}", {"language": "es-ES"})
        if det:
            overview = det.get('overview', '') or overview
            
    # Intentar traducción de inglés si sigue vacía
    if not overview.strip():
        det = tmdb_get(f"{media_type}/{media_id}", {"language": "en-US"})
        if det:
            overview_en = det.get('overview', '')
            if overview_en and translator:
                try:
                    overview = translator.translate(overview_en, dest='es').text
                except Exception as e:
                    print(f"Error de traducción de Google: {e}")
                    overview = overview_en
            else:
                overview = overview_en
                
    if not overview.strip():
        print(f"{title} ignorado por falta de descripción")
        return False
        
    # Filtrar géneros
    if any(genre_map.get(g,'') in excluded_genres for g in genre_ids):
        print(f"{title} ignorado por género excluido")
        return False
        
    # Descargar imagen
    try:
        r = requests.get(image_url, timeout=15)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content))
    except Exception as e:
        print(f"Error al descargar imagen de {title}: {e}")
        return False
        
    # Redimensionar y componer fondos
    img = resize_image(img, 1500)
    bg = Image.open('bckg.png')
    ov = Image.open('overlay.png')
    bg.paste(img, (1175,0))
    bg.paste(ov, (1175,0), ov)
    
    draw = ImageDraw.Draw(bg)
    font_t = ImageFont.truetype('Roboto-Light.ttf', 190)
    
    # Determinar si el logo se puede cargar antes de dibujar info/sinopsis
    logo_path = get_logo_path(media_type, media_id)
    logo_drawn = False
    logo_img = None
    if logo_path:
        try:
            data = requests.get('https://image.tmdb.org/t/p/original'+logo_path, timeout=10).content
            logo_img = Image.open(BytesIO(data)).convert('RGBA')
            logo_drawn = True
        except Exception as e:
            print(f"Error cargando logo de {title}, usando texto: {e}")
            
    # Fuentes para el nuevo layout
    font_metadata = ImageFont.truetype('Roboto-Light.ttf', 50)
    font_o = ImageFont.truetype('Roboto-Light.ttf', 78)
    
    # 1. Dibujar Título o Logo
    title_pos_y = 160
    title_actual_bottom_y = title_pos_y + 100 # Fallback por si acaso
    title_width = 800 # Fallback
    
    if logo_drawn and logo_img:
        try:
            w, h = logo_img.size
            max_h = 380 # Altura máxima para dejar suficiente espacio al resto de elementos
            max_w = 1600
            ratio = min(max_h/h, max_w/w)
            logo_img = logo_img.resize((int(w*ratio), int(h*ratio)), Image.Resampling.LANCZOS)
            x_logo = 210 + (max_w - logo_img.width) // 2
            y_logo = title_pos_y + (max_h - logo_img.height) // 2
            bg.paste(logo_img, (x_logo, y_logo), logo_img)
            title_actual_bottom_y = y_logo + logo_img.height
            title_width = logo_img.width
        except Exception as e:
            print(f"Error pegando logo de {title}: {e}")
            logo_drawn = False  # Intentar dibujar el texto si falla
            
    if not logo_drawn:
        # Sanitizar título para prevenir tofu y pasar a mayúsculas
        title_clean = sanitize_title_font(title).upper()
        # Extraer color de acento dinámico de la foto
        accent_color = extract_accent_color(img)
        
        try:
            # Dividir en 2 líneas si tiene más de 16 caracteres y contiene espacios
            if len(title_clean) > 16 and ' ' in title_clean:
                title_text = split_title_into_two_lines(title_clean)
                lines = title_text.split('\n')
                max_line = max(lines, key=len)
                
                font_size = 320
                font_t_bold = ImageFont.truetype('Roboto-Black.ttf', font_size)
                while draw.textlength(max_line, font=font_t_bold) > 2200 and font_size > 80:
                    font_size -= 5
                    font_t_bold = ImageFont.truetype('Roboto-Black.ttf', font_size)
                    
                bbox = draw.multiline_textbbox((0, 0), title_text, font=font_t_bold, spacing=10)
                title_pos = (210, title_pos_y)
                line_spacing = 10
            else:
                title_text = title_clean
                font_size = 380
                font_t_bold = ImageFont.truetype('Roboto-Black.ttf', font_size)
                while draw.textlength(title_text, font=font_t_bold) > 2200 and font_size > 110:
                    font_size -= 5
                    font_t_bold = ImageFont.truetype('Roboto-Black.ttf', font_size)
                    
                bbox = draw.textbbox((0, 0), title_text, font=font_t_bold)
                title_pos = (210, title_pos_y)
                line_spacing = 0
                
            # Sombra negra
            shadow_offset = 4
            draw.multiline_text((title_pos[0]+shadow_offset, title_pos[1]+shadow_offset), title_text, fill='black', font=font_t_bold, spacing=line_spacing)
            # Título principal con el color extraído
            draw.multiline_text(title_pos, title_text, fill=accent_color, font=font_t_bold, spacing=line_spacing)
            title_actual_bottom_y = title_pos_y + bbox[3]
            title_width = bbox[2] - bbox[0]
        except Exception as e:
            print(f"Error dibujando título estilizado: {e}")
            fallback_y = 338
            draw.text((202, fallback_y), title_clean, fill='white', font=font_t, stroke_width=2, stroke_fill='black')
            title_actual_bottom_y = fallback_y + 190
            title_width = int(draw.textlength(title_clean, font=font_t))
            
    # 2. Construir Metadatos
    if is_movie:
        info_extra = format_duration(duration)
    else:
        # Detectar miniserie
        if not tv_type and media_type == 'tv' and media_id:
            det = tmdb_get(f"{media_type}/{media_id}", {"language": "es-ES"})
            if det:
                tv_type = det.get('type')
        
        if tv_type == 'Miniseries':
            info_extra = "Miniserie"
        else:
            info_extra = f"{seasons} Temporada{'s' if seasons > 1 else ''}"
            
    genre_names = [genre_map.get(g, '') for g in genre_ids]
    genre_names = [gn for gn in genre_names if gn]
    
    metadata_parts = [", ".join(genre_names), year, info_extra]
    metadata_parts = [p for p in metadata_parts if p.strip()]
    metadata_text = "  •  ".join(metadata_parts)
    
    metadata_width = draw.textlength(metadata_text, font=font_metadata)
    
    # 3. Determinar calificaciones que entran por ancho de pantalla y cumplen los umbrales de votos
    platforms_priority = ["imdb", "tmdb", "letterboxd", "metacritic", "rottentomatoes", "filmaffinity"]
    available_platforms = []
    if isinstance(ratings, dict):
        for p in platforms_priority:
            if p in ratings and ratings[p].get('rating') is not None:
                p_votes = ratings[p].get('raw_votes', 0)
                threshold = VOTE_THRESHOLDS.get(p, 50)
                if p_votes >= threshold:
                    available_platforms.append(p)
        
    # Deduplicar imdb y tmdb para no mostrar dos iconos de imdb idénticos
    if "imdb" in available_platforms and "tmdb" in available_platforms:
        available_platforms.remove("tmdb")
        
    # Límite dinámico basado en el ancho del título
    max_allowed_width = max(title_width, 1000)
    max_allowed_width = min(max_allowed_width, 1600)  # Evitar desbordar la parte oscura
    
    fav_size = 44  # Tamaño unificado para ir en la misma línea
    sep = "  •  "
    sep_w = draw.textlength(sep, font=font_metadata)
    
    platforms_to_draw = []
    if available_platforms:
        # Siempre incluir el primero (IMDb o TMDb)
        platforms_to_draw.append(available_platforms[0])
        
        # Calcular ancho acumulado con el primero
        data = ratings[available_platforms[0]]
        rating_val = data.get("rating")
        votes_val = data.get("votes")
        rating_text = f"{rating_val:.1f} ({votes_val})" if votes_val else f"{rating_val:.1f}"
        
        current_w = metadata_width + sep_w + fav_size + 10 + draw.textlength(rating_text, font=font_metadata)
        
        # Probar si caben los demás
        for platform in available_platforms[1:]:
            data = ratings[platform]
            rating_val = data.get("rating")
            votes_val = data.get("votes")
            rating_text = f"{rating_val:.1f} ({votes_val})" if votes_val else f"{rating_val:.1f}"
            
            # Ancho de calificación: separador (35px) + favicon (fav_size) + gap (10px) + texto
            rating_w = 35 + fav_size + 10 + draw.textlength(rating_text, font=font_metadata)
            
            if current_w + rating_w <= max_allowed_width:
                platforms_to_draw.append(platform)
                current_w += rating_w
            else:
                break
                
    # 4. Dibujar Metadatos y Calificaciones inline
    metadata_pos_y = title_actual_bottom_y + 40
    y_center = metadata_pos_y + fav_size // 2
    
    # Dibujar metadatos con sombra y centrado vertical
    m_bbox = draw.textbbox((0, 0), metadata_text, font=font_metadata)
    m_offset_y = (m_bbox[1] + m_bbox[3]) / 2
    y_text = y_center - m_offset_y
    draw.text((210 + 2, y_text + 2), metadata_text, fill='black', font=font_metadata)
    draw.text((210, y_text), metadata_text, fill=(150, 150, 150), font=font_metadata)
    
    x = 210 + int(metadata_width)
    
    if platforms_to_draw:
        # Separador inicial
        sep_bbox = draw.textbbox((0, 0), sep, font=font_metadata)
        sep_offset_y = (sep_bbox[1] + sep_bbox[3]) / 2
        y_sep = y_center - sep_offset_y
        draw.text((x + 2, y_sep + 2), sep, fill='black', font=font_metadata)
        draw.text((x, y_sep), sep, fill=(150, 150, 150), font=font_metadata)
        x += int(sep_w)
        
        cwd = os.path.dirname(os.path.abspath(__file__))
        for idx, platform in enumerate(platforms_to_draw):
            data = ratings[platform]
            rating_val = data.get("rating")
            votes_val = data.get("votes")
            rating_text = f"{rating_val:.1f} ({votes_val})" if votes_val else f"{rating_val:.1f}"
            
            # Dibujar favicon
            favicon_name = "imdb" if platform == "tmdb" else platform
            favicon_path = os.path.join(cwd, f"{favicon_name}_favicon.png")
            if os.path.exists(favicon_path):
                try:
                    fav = Image.open(favicon_path).convert("RGBA")
                    fav = fav.resize((fav_size, fav_size), Image.Resampling.LANCZOS)
                    # Centrado vertical de la imagen
                    bg.paste(fav, (x, y_center - fav_size // 2), fav)
                    x += fav_size + 10
                except Exception as e:
                    print(f"Error pegando favicon de {platform}: {e}")
            
            # Dibujar texto de calificación con sombra y centrado vertical
            r_bbox = draw.textbbox((0, 0), rating_text, font=font_metadata)
            r_offset_y = (r_bbox[1] + r_bbox[3]) / 2
            y_r_text = y_center - r_offset_y
            
            draw.text((x + 2, y_r_text + 2), rating_text, fill='black', font=font_metadata)
            draw.text((x, y_r_text), rating_text, fill=(150, 150, 150), font=font_metadata)
            x += int(draw.textlength(rating_text, font=font_metadata))
            
            # Separador entre calificaciones
            if idx < len(platforms_to_draw) - 1:
                x += 35
                
    # 5. Dibujar Sinopsis
    overview_pos_y = metadata_pos_y + 80
    overview_pos = (210, overview_pos_y)
    
    # 1. Intentar con la sinopsis oficial completa + recomendación
    tmdb_desc = overview.strip()
    
    # Limpiar el prefijo redundante "Por qué te gustará:" de la recomendación
    if reason:
        reason = re.sub(r'^por qué te gustar[aá]:?\s*', '', reason.strip(), flags=re.IGNORECASE).strip()
        
    def format_combined(desc, rec_reason):
        if rec_reason:
            return f"{desc}\n{rec_reason.strip()}"
        return desc

    def wrap_text_to_paragraphs(text, max_total_lines=7):
        paragraphs = text.split('\n')
        wrapped_p = []
        lines_count = 0
        for p in paragraphs:
            if not p.strip():
                continue
            p_lines = textwrap.wrap(p.strip(), 75)
            wrapped_p.append(p_lines)
            lines_count += len(p_lines)
        return wrapped_p, lines_count

    combined_text = format_combined(tmdb_desc, reason)
    wrapped_p, lines_count = wrap_text_to_paragraphs(combined_text)
    
    # Si la combinación supera las 7 líneas:
    if lines_count > 7:
        success_summarize = False
        if GEMINI_API_KEY:
            print(f"La sinopsis completa de '{title}' supera las 7 líneas ({lines_count} líneas). Solicitando resumen dinámico a Gemini...")
            summarized = summarize_with_gemini(title, tmdb_desc, reason)
            if summarized:
                combined_text = summarized
                wrapped_p, lines_count = wrap_text_to_paragraphs(combined_text)
                success_summarize = True
                
        # Fallback si Gemini falla o no hay API key: usar short_overview si existe
        if not success_summarize and short_overview and reason:
            combined_text = format_combined(short_overview.strip(), reason)
            wrapped_p, lines_count = wrap_text_to_paragraphs(combined_text)
            
    # Si sigue superando las 7 líneas, truncamos estrictamente a 7 líneas como último recurso
    if lines_count > 7:
        flat_lines = []
        for p_lines in wrapped_p:
            flat_lines.extend(p_lines)
        
        flat_lines = flat_lines[:7]
        flat_lines[-1] += '...'
        overview_text = '\n'.join(flat_lines)
    else:
        overview_text = "\n".join(["\n".join(p_lines) for p_lines in wrapped_p])
        
    draw_multiline_text(draw, overview_pos, overview_text, font_o, (150, 150, 150), 16, 'black', 2)
    
    bg.convert('RGB').save(filename)
    print(f"Image saved: {filename}")
    return True

# Procesar película/serie recomendada a partir de ID
def process_recommended_item(item_id, media_type, short_overview=None, reason=None):
    details = tmdb_get(f"{media_type}/{item_id}", {"language": "es-ES"})
    if not details:
        return False
        
    is_movie = (media_type == 'movie')
    title = details.get('title') if is_movie else details.get('name')
    overview = details.get('overview', '')
    genre_ids = [g['id'] for g in details.get('genres', [])]
    date_key = 'release_date' if is_movie else 'first_air_date'
    year = details.get(date_key, '')[:4]
    
    # Obtener todas las calificaciones
    ratings = get_all_ratings_for_media(item_id, is_movie, details.get('vote_average', 0), details.get('vote_count', 0))
    
    backdrop_path = details.get('backdrop_path')
    if not backdrop_path:
        print(f"No hay backdrop de fondo disponible para: {title}")
        return False
        
    image_url = f"https://image.tmdb.org/t/p/original{backdrop_path}"
    duration = details.get('runtime') if is_movie else None
    seasons = details.get('number_of_seasons') if not is_movie else None
    
    return process_image(
        image_url=image_url,
        title=title,
        overview=overview,
        is_movie=is_movie,
        genre_ids=genre_ids,
        year=year,
        ratings=ratings,
        duration=duration,
        seasons=seasons,
        media_type=media_type,
        media_id=item_id,
        short_overview=short_overview,
        reason=reason,
        tv_type=details.get('type') if not is_movie else None
    )

# Obtener lista amplia de candidatos
def get_candidates(media_type, max_results=40):
    trending_results = []
    page = 1
    while len(trending_results) < max_results:
        data = tmdb_get(f"trending/{media_type}/week", {"language": "es-ES", "page": page})
        if not data or not data.get('results'):
            break
        for item in data.get('results', []):
            item['media_type'] = media_type
            trending_results.append(item)
        page += 1
        if page > 3:
            break
            
    classic_results = []
    if media_type == 'movie':
        # Descubrir clásicos populares aclamados (1990-2020)
        params = {
            "language": "es-ES",
            "sort_by": "popularity.desc",
            "vote_average.gte": 7.5,
            "vote_count.gte": 1000,
            "primary_release_date.gte": "1990-01-01",
            "primary_release_date.lte": "2020-12-31",
            "page": 1
        }
        data = tmdb_get("discover/movie", params=params)
        if data and data.get('results'):
            for item in data.get('results'):
                item['media_type'] = 'movie'
                classic_results.append(item)
                
    candidates = []
    seen_ids = set()
    
    # Priorizar tendencias
    for item in trending_results[:max_results]:
        if item['id'] not in seen_ids:
            seen_ids.add(item['id'])
            candidates.append(item)
            
    # Añadir clásicos para Gemini
    for item in classic_results:
        if len(candidates) >= max_results + 15:
            break
        if item['id'] not in seen_ids:
            seen_ids.add(item['id'])
            candidates.append(item)
            
    return candidates

# Llamada inteligente a Gemini
def ask_gemini_recommendations(likes, dislikes, neutral, candidates, count_m, count_t):
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY no configurado. Usando modo de fallback tradicional.")
        return None
        
    def format_pref_list(arr):
        return "\n".join([f"- {x['title']} (Géneros: {', '.join(x.get('genres', []))})" for x in arr]) if arr else "Ninguno"
        
    likes_str = format_pref_list(likes)
    dislikes_str = format_pref_list(dislikes)
    neutral_str = format_pref_list(neutral)
    
    cand_lines = []
    for c in candidates:
        media_type = c.get('media_type', 'movie')
        title = c.get('title') or c.get('name')
        date_key = 'release_date' if media_type == 'movie' else 'first_air_date'
        year = c.get(date_key, '')[:4]
        genres = [genre_map.get(gid, '') for gid in c.get('genre_ids', [])]
        genres = [g for g in genres if g]
        overview = c.get('overview', '')
        if len(overview) > 200:
            overview = overview[:200] + "..."
        cand_lines.append(
            f"- [{media_type.upper()}] ID: {c['id']}, Título: '{title}', Año: {year}, Géneros: {', '.join(genres)}, Puntuación: {c.get('vote_average')}\n  Resumen: {overview}"
        )
    candidates_str = "\n".join(cand_lines)
    
    prompt = f"""Eres un recomendador experto de cine y televisión. Tu tarea es analizar la lista de candidatos y seleccionar las mejores recomendaciones para el usuario basándote en su historial.

Historial del usuario:
Películas y series que le gustaron (LIKES):
{likes_str}

Películas y series que NO le gustaron (DISLIKES):
{dislikes_str}

Películas y series neutrales ("ni fu ni fa"):
{neutral_str}

Candidatos disponibles (películas y series nuevas, en tendencia o clásicos populares):
{candidates_str}

Instrucciones de recomendación:
1. Analiza los gustos del usuario. Le suelen gustar thrillers ingeniosos, suspense policial con giros narrativos, comedias negras con personajes satíricos y diálogos agudos (cine argentino/español muy valorado). Le desagradan las películas lentas, dramas sombríos o thrillers mediocres/tediosos.
2. Selecciona las mejores {count_m} películas y las mejores {count_t} series de la lista de candidatos que más se adapten a sus gustos.
3. Prioriza las novedades de los últimos años (2024-2026), pero OCASIONALMENTE (aproximadamente 1 de cada 4 recomendaciones) incluye un clásico aclamado (anterior a 2020) de la lista de candidatos que se adapte perfectamente a sus gustos y que no esté en sus listas de calificados.
4. Evita a toda costa recomendar títulos similares a los que NO le gustaron (DISLIKES). Usa la lista NEUTRAL para entender qué cosas le parecen indiferentes y afinar el límite.
5. Devuelve los resultados en formato JSON con la siguiente estructura exacta:
{{
  "movies": [
    {{
      "id": <tmdb_id>, 
      "title": "<titulo>", 
      "short_overview": "<sinopsis_condensada_en_espanol>",
      "reason": "<motivo_de_recomendacion>"
    }}
  ],
  "tv": [
    {{
      "id": <tmdb_id>, 
      "title": "<titulo>", 
      "short_overview": "<sinopsis_condensada_en_espanol>",
      "reason": "<motivo_de_recomendacion>"
    }}
  ]
}}
Nota crítica sobre los campos:
- "short_overview" debe ser una sinopsis condensada de la trama en español, muy concisa y directa (máximo 150 caracteres).
- "reason" debe ser una explicación breve de por qué se recomienda o gustará (máximo 100 caracteres).
  - No siempre tiene que relacionarla con una película que ya vio.
  - Puede basarse en que la obra ganó algún premio importante (ej. Oscar, Goya, etc.), porque es tendencia o popular por algún motivo (ej. dirección, banda sonora, reparto), o porque encaja en su perfil de gustos (thrillers ingeniosos, suspenso, comedia negra).
  - El texto debe escribirse directamente como la afirmación del motivo (ej: "Te encantará por su dirección ganadora del Oscar y su ritmo implacable." o "Es tendencia mundial por su sorprendente giro final y reparto estelar.").
  - IMPORTANTE: No incluyas ningún prefijo del estilo "Por qué te gustará" ni "Te gustará" por defecto. Escribe el motivo directamente con naturalidad en español.
- Mantén el lenguaje natural y atractivo en español.

Devuelve ÚNICAMENTE el código JSON limpio. No uses bloques de código markdown (como ```json) ni explicaciones de texto adicionales.
"""
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    try:
        r = requests.post(url, json=payload, timeout=60)
        if r.status_code == 200:
            resp_json = r.json()
            text_res = resp_json['candidates'][0]['content']['parts'][0]['text'].strip()
            
            # Limpiar markdown por seguridad
            if text_res.startswith("```"):
                lines = text_res.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].strip() == "```":
                    lines = lines[:-1]
                text_res = "\n".join(lines).strip()
                
            return json.loads(text_res)
        else:
            print(f"Error llamando a Gemini API: HTTP {r.status_code} - {r.text}")
            return None
    except Exception as e:
        print(f"Excepción al llamar a Gemini API: {e}")
        return None

# Buscar el ID de un título en TMDB
def find_tmdb_id_by_title(title, media_type, year=None):
    params = {
        "query": title,
        "language": "es-ES"
    }
    endpoint = f"search/{media_type}"
    
    if year:
        try:
            year_int = int(year)
            if media_type == 'movie':
                params['primary_release_year'] = year_int
            else:
                params['first_air_date_year'] = year_int
        except ValueError:
            pass
            
    data = tmdb_get(endpoint, params)
    if data and data.get('results'):
        return data['results'][0]['id']
        
    if year and (media_type == 'movie' and 'primary_release_year' in params or media_type == 'tv' and 'first_air_date_year' in params):
        params.pop('primary_release_year', None)
        params.pop('first_air_date_year', None)
        data = tmdb_get(endpoint, params)
        if data and data.get('results'):
            return data['results'][0]['id']
            
    data_multi = tmdb_get("search/multi", {"query": title, "language": "es-ES"})
    if data_multi and data_multi.get('results'):
        results = [item for item in data_multi['results'] if item.get('media_type') == media_type]
        if results:
            return results[0]['id']
            
    return None

# Pedir a Gemini recomendaciones libres basadas en el perfil de usuario (sin candidatos limitados)
def ask_gemini_free_form_recommendations(likes, dislikes, neutral, needed_movies, needed_tv):
    if not GEMINI_API_KEY:
        return None
        
    def format_pref_list(arr):
        return "\n".join([f"- {x['title']} (Géneros: {', '.join(x.get('genres', []))})" for x in arr]) if arr else "Ninguno"
        
    likes_str = format_pref_list(likes)
    dislikes_str = format_pref_list(dislikes)
    neutral_str = format_pref_list(neutral)
    
    excl_genres_str = ", ".join(list(excluded_genres))
    excl_langs_str = ", ".join(list(excluded_languages))
    
    prompt = f"""Eres un recomendador experto de cine y televisión. Tu tarea es generar exactamente {needed_movies} películas y {needed_tv} series excelentes que encajen a la perfección con el perfil del usuario.
    
Historial del usuario:
Películas y series que le gustaron (LIKES):
{likes_str}

Películas y series que NO le gustaron (DISLIKES):
{dislikes_str}

Películas y series neutrales ("ni fu ni fa"):
{neutral_str}

Instrucciones críticas de filtrado:
- NO recomiendes NADA de los siguientes géneros bajo ninguna circunstancia: {excl_genres_str}
- NO recomiendes NADA en los siguientes idiomas originales: {excl_langs_str}
- Evita a toda costa recomendar títulos similares a los que NO le gustaron (DISLIKES).
- No recomiendes títulos que ya figuren en sus listas de calificados (LIKES, DISLIKES, NEUTRAL).

Instrucciones de recomendación:
1. El usuario valora mucho los thrillers ingeniosos, suspense policial con giros narrativos y ritmo implacable, comedias negras con personajes satíricos y diálogos agudos (cine argentino/español muy valorado). Le desagradan las películas lentas, dramas sombríos o thrillers mediocres/tediosos.
2. Selecciona obras aclamadas mundialmente y populares que el usuario pueda encontrar fácilmente en plataformas de streaming o TMDB.
3. Devuelve los resultados en formato JSON con la siguiente estructura exacta:
{{
  "movies": [
    {{
      "title": "<titulo_en_espanol>",
      "year": "<año_lanzamiento>",
      "short_overview": "<sinopsis_condensada_en_espanol>",
      "reason": "<motivo_de_recomendacion>"
    }}
  ],
  "tv": [
    {{
      "title": "<titulo_en_espanol>",
      "year": "<año_lanzamiento>",
      "short_overview": "<sinopsis_condensada_en_espanol>",
      "reason": "<motivo_de_recomendacion>"
    }}
  ]
}}
Nota crítica sobre los campos:
- "short_overview" debe ser una sinopsis condensada de la trama en español, muy concisa y directa (máximo 150 caracteres).
- "reason" debe ser una explicación breve de por qué se recomienda o gustará (máximo 100 caracteres).
  - No incluyas ningún prefijo del estilo "Por qué te gustará" ni "Te gustará" por defecto. Escribe el motivo directamente con naturalidad en español.
  
Devuelve ÚNICAMENTE el código JSON limpio. No uses bloques de código markdown (como ```json) ni explicaciones de texto adicionales.
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    try:
        r = requests.post(url, json=payload, timeout=60)
        if r.status_code == 200:
            resp_json = r.json()
            text_res = resp_json['candidates'][0]['content']['parts'][0]['text'].strip()
            
            if text_res.startswith("```"):
                lines = text_res.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].strip() == "```":
                    lines = lines[:-1]
                text_res = "\n".join(lines).strip()
                
            return json.loads(text_res)
        else:
            print(f"Error llamando a Gemini API para recomendaciones libres: HTTP {r.status_code} - {r.text}")
            return None
    except Exception as e:
        print(f"Excepción al llamar a Gemini API para recomendaciones libres: {e}")
        return None

# Chequear duplicados en Reddit con resiliencia
def was_already_posted(subreddit, title, limit=1000):
    try:
        for sub in subreddit.new(limit=limit):
            if sub.title.strip().lower() == title.strip().lower():
                return True
    except Exception as e:
        print(f"Error al verificar duplicados en Reddit para '{title}': {e}")
        return False
    return False

# Sincronización de fondos locales existentes con Reddit
def sync_existing_backgrounds_to_reddit(subreddit):
    print("\n--- Iniciando Sincronización de Fondos Locales con Reddit ---")
    if not os.path.exists(background_dir):
        print("El directorio de fondos no existe.")
        return
        
    files = [f for f in os.listdir(background_dir) if f.endswith('.jpg')]
    if not files:
        print("No se encontraron fondos locales (.jpg) para sincronizar.")
        return
        
    print(f"Detectados {len(files)} fondos locales. Verificando subidas en Reddit...")
    for filename in files:
        filepath = os.path.join(background_dir, filename)
        # Reconstruir el título a partir del nombre del archivo
        name_no_ext = os.path.splitext(filename)[0]
        title_reconstructed = name_no_ext.replace('_', ' ').strip()
        title_norm = " ".join(title_reconstructed.split()).upper()
        
        # Consultar usando el caché local
        if not was_already_posted_cached(title_norm):
            try:
                subreddit.submit_image(title_norm, filepath)
                print(f"Sincronizado/Subido a Reddit: {title_norm}")
                already_posted_set.add(title_norm)
                save_posted_cache()
            except Exception as e:
                print(f"Error subiendo '{title_norm}' durante sincronización: {e}")
        else:
            print(f"Ya publicado en Reddit: {title_norm}")
    print("--- Sincronización de Fondos Locales Finalizada ---\n")

# Funciones auxiliares de filtrado
    
def filter_candidates_list(candidates, is_movie):
    filtered = []
    for c in candidates:
        mid = c.get('id')
        title = c.get('title') or c.get('name')
        
        # 0. Verificar si ya fue publicado (usando el cache local)
        if title and was_already_posted_cached(title):
            continue
            
        # 0.5. Verificar mínimo de votos en TMDB (>= 10)
        vote_count = c.get('vote_count', 0)
        if vote_count < 10:
            continue
            
        # 1. Verificar exclusiones de IDs
        if is_movie:
            if mid in excluded_movies:
                continue
        else:
            if mid in excluded_tv:
                continue
                
        # 2. Idiomas excluidos
        if c.get('original_language') in excluded_languages:
            continue
            
        # 3. Sinopsis vacía o sin backdrop
        if not c.get('overview', '').strip() or not c.get('backdrop_path'):
            continue
            
        # 4. Géneros excluidos (usando genre_map robusto)
        genre_ids = c.get('genre_ids', [])
        if any(genre_map.get(gid, '') in excluded_genres for gid in genre_ids):
            continue
            
        filtered.append(c)
    return filtered

def main():
    download_favicons()
    load_genres()
    
    reddit = praw.Reddit(
        client_id=os.getenv('REDDIT_CLIENT_ID'),
        client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
        user_agent="tmdb uploader by u/" + os.getenv('REDDIT_USERNAME'),
        username=os.getenv('REDDIT_USERNAME'),
        password=os.getenv('REDDIT_PASSWORD')
    )
    subreddit = reddit.subreddit(os.getenv('REDDIT_SUBREDDIT','IMDB_esp'))
    
    # Inicializar y cargar el cache de publicados, y sincronizar con Reddit
    load_posted_cache(subreddit)
    
    # Sincronizar fondos ya existentes en disco con Reddit al arrancar
    sync_existing_backgrounds_to_reddit(subreddit)
    
    # Cargar gustos del usuario
    preferences = load_preferences()
    likes = preferences.get('likes', [])
    dislikes = preferences.get('dislikes', [])
    neutral = preferences.get('neutral', [])
    
    # Obtener candidatos
    print("Recuperando candidatos de TMDB...")
    movie_candidates = get_candidates('movie', max_results=20)
    tv_candidates = get_candidates('tv', max_results=20)
    
    # Pre-filtrar candidatos antes de mandárselos a Gemini
    movie_candidates_filtered = filter_candidates_list(movie_candidates, is_movie=True)
    tv_candidates_filtered = filter_candidates_list(tv_candidates, is_movie=False)
    all_candidates_filtered = movie_candidates_filtered + tv_candidates_filtered
    
    # Consultar Gemini
    print(f"Consultando recomendaciones a Gemini ({GEMINI_MODEL})...")
    recommendations = ask_gemini_recommendations(
        likes, dislikes, neutral, all_candidates_filtered,
        numberofmovies, numberoftvshows
    )
    
    success_movies = 0
    success_tv = 0
    
    if recommendations and ('movies' in recommendations or 'tv' in recommendations):
        print("Recomendaciones inteligentes de Gemini recibidas:")
        rec_movies = recommendations.get('movies', [])
        rec_tv = recommendations.get('tv', [])
        
        # Películas recomendadas por IA
        print(f"\n--- Procesando {len(rec_movies)} Películas Recomendadas por Gemini ---")
        for rec in rec_movies:
            mid = rec.get('id')
            title = rec.get('title')
            short_overview = rec.get('short_overview', '')
            reason = rec.get('reason', '')
            if not mid:
                continue
                
            if was_already_posted_cached(title):
                print(f"Película '{title}' saltada porque ya fue publicada (según caché).")
                continue
                
            print(f"Película elegida: {title} (ID: {mid})")
            if mid in excluded_movies:
                print(f"Ignorada (exclusión manual): {title}")
                continue
                
            ok = process_recommended_item(mid, 'movie', short_overview=short_overview, reason=reason)
            filename = os.path.join(background_dir, clean_filename(title) + '.jpg')
            if os.path.exists(filename):
                if ok:
                    success_movies += 1
                    title_norm = normalize_title(title).upper()
                    if not was_already_posted_cached(title_norm):
                        try:
                            subreddit.submit_image(title_norm, filename)
                            print(f"Subido a Reddit: {title_norm}")
                            already_posted_set.add(title_norm)
                            save_posted_cache()
                        except Exception as e:
                            print(f"Error subiendo '{title_norm}' a Reddit: {e}")
                else:
                    print(f"No se procesó la película {title} por filtros locales o error.")
                        
        # Series recomendadas por IA
        print(f"\n--- Procesando {len(rec_tv)} Series Recomendadas por Gemini ---")
        for rec in rec_tv:
            tid = rec.get('id')
            title = rec.get('title')
            short_overview = rec.get('short_overview', '')
            reason = rec.get('reason', '')
            if not tid:
                continue
                
            if was_already_posted_cached(title):
                print(f"Serie '{title}' saltada porque ya fue publicada (según caché).")
                continue
                
            print(f"Serie elegida: {title} (ID: {tid})")
            if tid in excluded_tv:
                print(f"Ignorada (exclusión manual): {title}")
                continue
                
            ok = process_recommended_item(tid, 'tv', short_overview=short_overview, reason=reason)
            filename = os.path.join(background_dir, clean_filename(title) + '.jpg')
            if os.path.exists(filename):
                if ok:
                    success_tv += 1
                    title_norm = normalize_title(title).upper()
                    if not was_already_posted_cached(title_norm):
                        try:
                            subreddit.submit_image(title_norm, filename)
                            print(f"Subido a Reddit: {title_norm}")
                            already_posted_set.add(title_norm)
                            save_posted_cache()
                        except Exception as e:
                            print(f"Error subiendo '{title_norm}' a Reddit: {e}")
                else:
                    print(f"No se procesó la serie {title} por filtros locales o error.")
    else:
        print("Fallo en Gemini o sin recomendaciones iniciales de candidatos.")
 
    # === BACKFILL CON RECOMENDACIONES LIBRES DE GEMINI ===
    needed_movies = numberofmovies - success_movies
    needed_tv = numberoftvshows - success_tv
    
    if (needed_movies > 0 or needed_tv > 0) and GEMINI_API_KEY:
        print(f"\n--- Faltan {needed_movies} películas y {needed_tv} series para completar la cuota. Solicitando recomendaciones libres a Gemini... ---")
        free_recs = ask_gemini_free_form_recommendations(likes, dislikes, neutral, max(0, needed_movies), max(0, needed_tv))
        if free_recs:
            # Procesar películas libres
            if needed_movies > 0 and 'movies' in free_recs:
                for rec in free_recs.get('movies', []):
                    if success_movies >= numberofmovies:
                        break
                    title = rec.get('title')
                    year = rec.get('year')
                    short_overview = rec.get('short_overview', '')
                    reason = rec.get('reason', '')
                    
                    if was_already_posted_cached(title):
                        print(f"Película recomendada libre '{title}' saltada porque ya fue publicada (según caché).")
                        continue
                        
                    print(f"Buscando ID de película recomendada libre: {title} ({year})")
                    mid = find_tmdb_id_by_title(title, 'movie', year)
                    if mid:
                        print(f"Encontrado ID {mid} para película {title}")
                        if mid in excluded_movies:
                            continue
                        ok = process_recommended_item(mid, 'movie', short_overview=short_overview, reason=reason)
                        filename = os.path.join(background_dir, clean_filename(title) + '.jpg')
                        if os.path.exists(filename):
                            if ok:
                                success_movies += 1
                                title_norm = normalize_title(title).upper()
                                if not was_already_posted_cached(title_norm):
                                    try:
                                        subreddit.submit_image(title_norm, filename)
                                        print(f"Subido a Reddit (libre): {title_norm}")
                                        already_posted_set.add(title_norm)
                                        save_posted_cache()
                                    except Exception as e:
                                        print(f"Error subiendo '{title_norm}' a Reddit: {e}")
                            else:
                                print(f"No se pudo procesar la película libre {title} (filtros o error).")
                    else:
                        print(f"No se pudo encontrar el ID para la película: {title}")
                        
            # Procesar series libres
            if needed_tv > 0 and 'tv' in free_recs:
                for rec in free_recs.get('tv', []):
                    if success_tv >= numberoftvshows:
                        break
                    title = rec.get('title')
                    year = rec.get('year')
                    short_overview = rec.get('short_overview', '')
                    reason = rec.get('reason', '')
                    
                    if was_already_posted_cached(title):
                        print(f"Serie recomendada libre '{title}' saltada porque ya fue publicada (según caché).")
                        continue
                        
                    print(f"Buscando ID de serie recomendada libre: {title} ({year})")
                    tid = find_tmdb_id_by_title(title, 'tv', year)
                    if tid:
                        print(f"Encontrado ID {tid} para serie {title}")
                        if tid in excluded_tv:
                            continue
                        ok = process_recommended_item(tid, 'tv', short_overview=short_overview, reason=reason)
                        filename = os.path.join(background_dir, clean_filename(title) + '.jpg')
                        if os.path.exists(filename):
                            if ok:
                                success_tv += 1
                                title_norm = normalize_title(title).upper()
                                if not was_already_posted_cached(title_norm):
                                    try:
                                        subreddit.submit_image(title_norm, filename)
                                        print(f"Subido a Reddit (libre): {title_norm}")
                                        already_posted_set.add(title_norm)
                                        save_posted_cache()
                                    except Exception as e:
                                        print(f"Error subiendo '{title_norm}' a Reddit: {e}")
                            else:
                                print(f"No se pudo procesar la serie libre {title} (filtros o error).")
                    else:
                        print(f"No se pudo encontrar el ID para la serie: {title}")
 
    # === ULTIMO RECURSO: FALLBACK TRADICIONAL ===
    if success_movies < numberofmovies or success_tv < numberoftvshows:
        print("\n--- Aún faltan recomendaciones. Ejecutando fallback tradicional sin IA... ---")
        min_rating = float(os.getenv('TMDB_MIN_RATING', '6.5'))
        
        # Fallback Películas
        if success_movies < numberofmovies:
            for m in movie_candidates:
                if success_movies >= numberofmovies:
                    break
                mid = m.get('id')
                title = m.get('title', '')
                
                if was_already_posted_cached(title):
                    print(f"Película fallback '{title}' saltada porque ya fue publicada (según caché).")
                    continue
                    
                if mid in excluded_movies:
                    continue
                if m.get('original_language') in excluded_languages:
                    continue
                rating = m.get('vote_average', 0)
                if rating < min_rating:
                    continue
                    
                year = m.get('release_date', '')[:4]
                try:
                    item_year = int(year)
                    if item_year < current_year - 3:
                        continue
                except ValueError:
                    continue
                    
                # Exclusión de géneros
                genre_ids = m.get('genre_ids', [])
                if any(genre_map.get(gid, '') in excluded_genres for gid in genre_ids):
                    continue
                    
                details = tmdb_get(f"movie/{mid}", {"language": "es-ES"})
                if not details:
                    continue
                    
                ratings = get_all_ratings_for_media(mid, True, rating, details.get('vote_count', 0))
                ok = process_image(
                    f"https://image.tmdb.org/t/p/original{m.get('backdrop_path')}",
                    title, m.get('overview', ''), True,
                    genre_ids, year, ratings,
                    duration=details.get('runtime'), media_type='movie', media_id=mid
                )
                filename = os.path.join(background_dir, clean_filename(title) + '.jpg')
                if os.path.exists(filename):
                    if ok:
                        success_movies += 1
                        title_norm = normalize_title(title).upper()
                        if not was_already_posted_cached(title_norm):
                            try:
                                subreddit.submit_image(title_norm, filename)
                                print(f"Subido a Reddit (fallback): {title_norm}")
                                already_posted_set.add(title_norm)
                                save_posted_cache()
                            except Exception as e:
                                print(f"Error subiendo '{title_norm}' a Reddit: {e}")
                            
        # Fallback Series
        if success_tv < numberoftvshows:
            for tv in tv_candidates:
                if success_tv >= numberoftvshows:
                    break
                tid = tv.get('id')
                title = tv.get('name', '')
                
                if was_already_posted_cached(title):
                    print(f"Serie fallback '{title}' saltada porque ya fue publicada (según caché).")
                    continue
                    
                if tid in excluded_tv:
                    continue
                if tv.get('original_language') in excluded_languages:
                    continue
                rating = tv.get('vote_average', 0)
                if rating < min_rating:
                    continue
                    
                year = tv.get('first_air_date', '')[:4]
                try:
                    item_year = int(year)
                    if item_year < current_year - 3:
                        continue
                except ValueError:
                    continue
                    
                genre_ids = tv.get('genre_ids', [])
                if any(genre_map.get(gid, '') in excluded_genres for gid in genre_ids):
                    continue
                    
                details = tmdb_get(f"tv/{tid}", {"language": "es-ES"})
                if not details:
                    continue
                    
                ratings = get_all_ratings_for_media(tid, False, rating, details.get('vote_count', 0))
                ok = process_image(
                    f"https://image.tmdb.org/t/p/original{tv.get('backdrop_path')}",
                    title, tv.get('overview', ''), False,
                    genre_ids, year, ratings,
                    seasons=details.get('number_of_seasons'), media_type='tv', media_id=tid,
                    tv_type=details.get('type')
                )
                filename = os.path.join(background_dir, clean_filename(title) + '.jpg')
                if os.path.exists(filename):
                    if ok:
                        success_tv += 1
                        title_norm = normalize_title(title).upper()
                        if not was_already_posted_cached(title_norm):
                            try:
                                subreddit.submit_image(title_norm, filename)
                                print(f"Subido a Reddit (fallback): {title_norm}")
                                already_posted_set.add(title_norm)
                                save_posted_cache()
                            except Exception as e:
                                print(f"Error subiendo '{title_norm}' a Reddit: {e}")
                        
    print(f"\nProceso finalizado. Películas generadas/subidas: {success_movies}, Series: {success_tv}")

if __name__ == '__main__':
    main()
