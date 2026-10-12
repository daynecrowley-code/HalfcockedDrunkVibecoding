"""Reddit bot: replies with a random fart-sound YouTube video whenever "fart" is mentioned."""
import os
import random
import re
import time
from pathlib import Path

import praw

FART_RE = re.compile(r"\bfart(s|ed|ing|y)?\b", re.IGNORECASE)
VIDEOS_FILE = Path(__file__).with_name("videos.txt")
SUBREDDITS = os.environ.get("SUBREDDITS", "test")  # e.g. "test+AskReddit"; "all" is a bad idea
COOLDOWN_SECONDS = int(os.environ.get("COOLDOWN_SECONDS", "60"))  # min gap between replies


def load_videos():
    lines = VIDEOS_FILE.read_text().splitlines()
    videos = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
    if not videos:
        raise SystemExit("videos.txt has no URLs - add some fart sound YouTube links.")
    return videos


def main():
    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        username=os.environ["REDDIT_USERNAME"],
        password=os.environ["REDDIT_PASSWORD"],
        user_agent=f"fartbot by u/{os.environ['REDDIT_USERNAME']}",
    )
    me = reddit.user.me().name.lower()
    videos = load_videos()
    last_reply = 0.0

    print(f"Listening on r/{SUBREDDITS} as u/{me} ...")
    for comment in reddit.subreddit(SUBREDDITS).stream.comments(skip_existing=True):
        author = comment.author.name.lower() if comment.author else ""
        if author == me or author == "automoderator":
            continue
        if not FART_RE.search(comment.body):
            continue
        if time.time() - last_reply < COOLDOWN_SECONDS:
            continue
        try:
            comment.reply(f"Did somebody say fart? 💨\n\n{random.choice(videos)}")
            last_reply = time.time()
            print(f"Replied to {comment.id} in r/{comment.subreddit}")
        except praw.exceptions.RedditAPIException as e:
            print(f"Reddit refused reply: {e}")  # rate limit, banned, locked thread...
            time.sleep(60)


if __name__ == "__main__":
    main()
