# Fart Bot

Replies with a random fart-sound YouTube video whenever a comment mentions "fart".

## Setup
1. Create a "script" app at https://www.reddit.com/prefs/apps (use a dedicated bot account).
2. Add fart sound YouTube links to `videos.txt`, one per line.
3. Run:
```
pip install -r requirements.txt
export REDDIT_CLIENT_ID=... REDDIT_CLIENT_SECRET=... REDDIT_USERNAME=... REDDIT_PASSWORD=...
export SUBREDDITS=test        # subreddits to watch, e.g. test+mysub
python bot.py
```
Only run it in subreddits that allow bots (or that you mod) - Reddit bans spammy bots.
It has a 60s cooldown between replies (`COOLDOWN_SECONDS`) and ignores its own comments.
