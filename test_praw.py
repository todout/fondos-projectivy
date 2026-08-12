import praw
import os
from dotenv import load_dotenv

load_dotenv()

client_id = os.getenv('REDDIT_CLIENT_ID')
client_secret = os.getenv('REDDIT_CLIENT_SECRET')
username = os.getenv('REDDIT_USERNAME')
password = os.getenv('REDDIT_PASSWORD', '').strip("'")

reddit = praw.Reddit(
    client_id=client_id,
    client_secret=client_secret,
    username=username,
    password=password,
    user_agent='python:fondos-projectivy:v1.0 (by /u/' + username + ')'
)

sub = reddit.subreddit('IMDB_esp')
posts = list(sub.new(limit=35))
print(f"PRAW devolvió {len(posts)} posts recientes de r/IMDB_esp:")
for p in posts[:15]:
    print("-", p.title)
