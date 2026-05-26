import os
import json
import requests
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

TMDB_TOKEN = os.getenv("TMDB_TOKEN")
if not TMDB_TOKEN:
    print("Error: No se encontró TMDB_TOKEN en el archivo .env")
    exit(1)

headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {TMDB_TOKEN}"
}
tmdb_url = "https://api.themoviedb.org/3/"

initial_likes = [
    "Contratiempo", "El ciudadano ilustre", "Un cuento chino",
    "El hombre de al lado", "Mi obra maestra", "Sin retorno",
    "El patrón: radiografía de un crimen", "Crímenes de familia", "El Cuento de las Comadrejas"
]

initial_dislikes = [
    "El aura", "Tesis sobre un homicidio", "Plata quemada",
    "Al final del túnel", "Nieve negra", "Sin hijos"
]

# Cargar géneros en español
def load_genre_map():
    genres = []
    for mtype in ['movie', 'tv']:
        r = requests.get(f"{tmdb_url}genre/{mtype}/list?language=es-ES", headers=headers)
        if r.status_code == 200:
            genres.extend(r.json().get('genres', []))
    return {g['id']: g['name'] for g in genres}

genre_map = load_genre_map()

def search_movie(title):
    print(f"Buscando en TMDB: {title}...")
    params = {
        "query": title,
        "language": "es-ES"
    }
    r = requests.get(f"{tmdb_url}search/movie", headers=headers, params=params)
    if r.status_code != 200:
        print(f"Error buscando '{title}': HTTP {r.status_code}")
        return None
    
    results = r.json().get("results", [])
    if not results:
        print(f"No se encontraron resultados para: {title}")
        return None
    
    # Tomar la mejor coincidencia
    best_match = results[0]
    movie_id = best_match["id"]
    
    # Obtener detalles completos
    details_r = requests.get(f"{tmdb_url}movie/{movie_id}?language=es-ES", headers=headers)
    if details_r.status_code == 200:
        details = details_r.json()
        genres = [g["name"] for g in details.get("genres", [])]
        year = details.get("release_date", "")[:4]
        return {
            "id": movie_id,
            "title": details.get("title", best_match.get("title")),
            "genres": genres,
            "year": year
        }
    
    return {
        "id": movie_id,
        "title": best_match.get("title"),
        "genres": [genre_map.get(gid, "Desconocido") for gid in best_match.get("genre_ids", [])],
        "year": best_match.get("release_date", "")[:4]
    }

def main():
    preferences = {
        "likes": [],
        "dislikes": [],
        "neutral": []
    }
    
    print("--- Procesando LIKES ---")
    for title in initial_likes:
        data = search_movie(title)
        if data:
            preferences["likes"].append(data)
            
    print("\n--- Procesando DISLIKES ---")
    for title in initial_dislikes:
        data = search_movie(title)
        if data:
            preferences["dislikes"].append(data)
            
    # Guardar en user_preferences.json
    output_path = "user_preferences.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(preferences, f, indent=2, ensure_ascii=False)
        
    print(f"\n¡Inicialización completada! Guardado en {output_path}")

if __name__ == "__main__":
    main()
