import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from io import BytesIO
import os
import shutil
from urllib.request import urlopen
import textwrap
from datetime import datetime, timedelta
import praw
import time
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

# Base URL for the API
url = "https://api.themoviedb.org/3/"

# Set your TMDB API Read Access Token key here
headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {os.getenv('TMDB_TOKEN')}"
}

# Load font
truetype_path = 'Roboto-Light.ttf'
if not os.path.exists(truetype_path):
    truetype_url = 'https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Light.ttf'
    response = requests.get(truetype_url, timeout=10)
    if response.status_code == 200:
        with open(truetype_path, 'wb') as f:
            f.write(response.content)

# Configuración
date_str = datetime.now().strftime("%Y%m%d")
numberofmovies = 5
numberoftvshows = 5
max_air_date = datetime.now() - timedelta(days=90)
background_dir = "tmdbbackgrounds"

# Eliminar imágenes anteriores
i = 0
if os.path.exists(background_dir):
    for file in os.listdir(background_dir):
        if file.endswith(".jpg"):
            os.remove(os.path.join(background_dir, file))
            i += 1
    print(f"Se eliminaron {i} imágenes previas")
os.makedirs(background_dir, exist_ok=True)

# Obtener lista de géneros en español
genre_map = {}
def load_genres():
    global genre_map
    response = requests.get(f"{url}genre/movie/list?language=es-ES", headers=headers)
    if response.status_code == 200:
        genres = response.json().get("genres", [])
        genre_map = {g['id']: g['name'] for g in genres}

# Funciones auxiliares
def resize_image(image, height):
    ratio = height / image.height
    width = int(image.width * ratio)
    return image.resize((width, height))

def clean_filename(filename):
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)

def draw_multiline_text(draw, position, text, font, fill, spacing, shadow_color=None, shadow_offset=2):
    if shadow_color:
        draw.multiline_text((position[0] + shadow_offset, position[1] + shadow_offset), text, font=font, fill=shadow_color, spacing=spacing)
    draw.multiline_text(position, text, font=font, fill=fill, spacing=spacing)

def process_image(image_url, title, overview, is_movie, genre_ids, year, rating, duration=None, seasons=None):
    response = requests.get(image_url, timeout=10)
    if response.status_code != 200:
        print(f"Failed to download image for {title}")
        return

    image = Image.open(BytesIO(response.content))
    image = resize_image(image, 1500)
    bckg = Image.open("bckg.png")
    overlay = Image.open("overlay.png")
    bckg.paste(image, (1175, 0))
    bckg.paste(overlay, (1175, 0), overlay)

    draw = ImageDraw.Draw(bckg)
    font_title = ImageFont.truetype(truetype_path, size=190)
    font_overview = ImageFont.truetype(truetype_path, size=50)

    shadow_color = "black"
    main_color = "white"
    overview_color = (150, 150, 150)
    metadata_color = "white"

    title_position = (200, 420)
    overview_position = (210, 730)
    shadow_offset = 2
    info_position = (210, 650)

    wrapped_overview = "\n".join(textwrap.wrap(overview, width=70))
    draw_multiline_text(draw, overview_position, wrapped_overview, font=font_overview, fill=metadata_color, spacing=10, shadow_color=shadow_color, shadow_offset=shadow_offset)

    if is_movie:
        additional_info = f"{duration}"
    else:
        additional_info = f"{seasons} {'Temporada' if seasons == 1 else 'Temporadas'}"

    genre_names = [genre_map.get(gid, str(gid)) for gid in genre_ids]
    genre_text = ", ".join(genre_names)

    rating_text = "TMDB: " + str(rating)
    year_text = str(year)[:4]
    info_text = f"{genre_text}  •  {year_text}  •  {additional_info}  •  {rating_text}"

    draw.text((info_position[0] + shadow_offset, info_position[1] + shadow_offset), info_text, font=font_overview, fill=shadow_color)
    draw.text(info_position, info_text, font=font_overview, fill=overview_color)

    draw.text((title_position[0] + shadow_offset, title_position[1] + shadow_offset), title, font=font_title, fill=shadow_color)
    draw.text(title_position, title, font=font_title, fill=main_color)

    filename = os.path.join(background_dir, f"{clean_filename(title)}_{date_str}.jpg")
    bckg.convert('RGB').save(filename)
    print(f"Image saved: {filename}")

# Obtener trending
def get_trending(media_type):
    endpoint = f"{url}trending/{media_type}/week?language=es-ES"
    return requests.get(endpoint, headers=headers).json().get("results", [])

def get_movie_details(movie_id):
    return requests.get(f"{url}movie/{movie_id}?language=es-ES", headers=headers).json()

def get_tv_details(tv_id):
    return requests.get(f"{url}tv/{tv_id}?language=es-ES", headers=headers).json()

# Cargar géneros
load_genres()

# Procesar películas
for movie in get_trending("movie")[:numberofmovies]:
    details = get_movie_details(movie['id'])
    process_image(
        f"https://image.tmdb.org/t/p/original{movie['backdrop_path']}",
        movie['title'],
        movie['overview'],
        is_movie=True,
        genre_ids=movie.get('genre_ids', []),
        year=movie.get('release_date', '')[:4],
        rating=round(movie.get('vote_average', 0), 1),
        duration=details.get('runtime', 'N/A')
    )

# Procesar series
for tv in get_trending("tv")[:numberoftvshows]:
    details = get_tv_details(tv['id'])
    process_image(
        f"https://image.tmdb.org/t/p/original{tv['backdrop_path']}",
        tv['name'],
        tv['overview'],
        is_movie=False,
        genre_ids=tv.get('genre_ids', []),
        year=tv.get('first_air_date', '')[:4],
        rating=round(tv.get('vote_average', 0), 1),
        seasons=details.get('number_of_seasons', 0)
    )

# Subir a Reddit
reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent="tmdb uploader by u/" + os.getenv("REDDIT_USERNAME"),
    username=os.getenv("REDDIT_USERNAME"),
    password=os.getenv("REDDIT_PASSWORD")
)

subreddit = reddit.subreddit("IMDB_esp")
for file in os.listdir(background_dir):
    if file.endswith(".jpg"):
        filepath = os.path.join(background_dir, file)
        title = os.path.splitext(file)[0].replace("_", " ")
        try:
            subreddit.submit_image(title, filepath)
            print(f"Subido a Reddit: {title}")
        except Exception as e:
            print(f"Error subiendo {title}: {e}")
