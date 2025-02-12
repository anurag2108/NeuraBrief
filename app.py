from flask import Flask, render_template, request, jsonify
import arxiv
import requests
import math
import os

from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# Configure SQLite database for votes
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///votes.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Define a Vote model to track upvotes and downvotes per URL
class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), unique=True, nullable=False)
    upvotes = db.Column(db.Integer, default=0)
    downvotes = db.Column(db.Integer, default=0)

# Create tables if they don't exist
with app.app_context():
    db.create_all()

# -------------------------
# ArXiv Papers (for the Papers tab)
# -------------------------
def fetch_arxiv_papers(page=1, per_page=10):
    search = arxiv.Search(
        query="cat:cs.AI",
        max_results=50,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending
    )
    results = list(search.results())
    start = (page - 1) * per_page
    end = start + per_page
    return results[start:end], len(results)

# -------------------------
# YouTube Search Function (fetch view counts, etc.)
# -------------------------
def get_youtube_results(query, youtube_api_key, max_results=5):
    search_url = "https://www.googleapis.com/youtube/v3/search"
    search_params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "key": youtube_api_key
    }
    response = requests.get(search_url, params=search_params)
    if response.status_code != 200:
        print("Error fetching YouTube search results:", response.text)
        return []
    items = response.json().get("items", [])
    video_ids = [item["id"]["videoId"] for item in items]
    videos_url = "https://www.googleapis.com/youtube/v3/videos"
    videos_params = {
        "part": "statistics,snippet",
        "id": ",".join(video_ids),
        "key": youtube_api_key
    }
    videos_response = requests.get(videos_url, params=videos_params)
    yt_results = []
    if videos_response.status_code == 200:
        video_items = videos_response.json().get("items", [])
        for idx, item in enumerate(video_items):
            video_id = item["id"]
            title = item["snippet"]["title"]
            channel_title = item["snippet"]["channelTitle"]
            views = int(item["statistics"].get("viewCount", 0))
            yt_results.append({
                "source": "YouTube",
                "title": title,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "author": channel_title,
                "views": views,
                "order": idx
            })
    return yt_results

# -------------------------
# Google Custom Search Function
# -------------------------
def get_google_search_results(query, google_api_key, google_cse_id, max_results=5):
    google_search_url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "q": query,
        "key": google_api_key,
        "cx": google_cse_id,
        "num": max_results
    }
    response = requests.get(google_search_url, params=params)
    gs_results = []
    if response.status_code == 200:
        items = response.json().get("items", [])
        for idx, item in enumerate(items):
            title = item.get("title")
            link = item.get("link")
            author = "N/A"
            if "pagemap" in item and "metatags" in item["pagemap"]:
                for tag in item["pagemap"]["metatags"]:
                    if "og:site_name" in tag:
                        author = tag["og:site_name"]
                        break
            gs_results.append({
                "source": "Google",
                "title": title,
                "url": link,
                "author": author,
                "order": idx
            })
    else:
        print("Error fetching Google search results:", response.text)
    return gs_results

# -------------------------
# Aggregation Function (simply concatenates results)
# -------------------------
def aggregate_search_results(query, youtube_api_key, google_api_key, google_cse_id, max_results=5):
    yt_results = get_youtube_results(query, youtube_api_key, max_results)
    gs_results = get_google_search_results(query, google_api_key, google_cse_id, max_results)
    # Simply combine both results directly.
    return yt_results + gs_results

# -------------------------
# Flask Routes
# -------------------------
@app.route("/")
def index():
    # Render the index page with both tabs
    papers, total = fetch_arxiv_papers(page=1, per_page=10)
    return render_template("index.html", papers=papers, current_page=1)

# Partial for papers tab (loaded via AJAX in the same tab)
@app.route("/papers_partial")
def papers_partial():
    page = int(request.args.get("page", 1))
    papers, total = fetch_arxiv_papers(page=page, per_page=10)
    return render_template("papers_partial.html", papers=papers, current_page=page)

# Partial for search tab (loaded via AJAX in the same tab)
@app.route("/search_partial", methods=["POST"])
def search_partial():
    query = request.form.get("query")
    # Replace with your actual API keys and CSE ID
    YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
    GOOGLE_CSE_ID = os.environ.get("GOOGLE_CSE_ID")
    results = aggregate_search_results(query, YOUTUBE_API_KEY, GOOGLE_API_KEY, GOOGLE_CSE_ID, max_results=5)
    return render_template("search_partial.html", results=results)

# Endpoint to handle vote updates (upvote/downvote)
@app.route("/vote", methods=["POST"])
def vote():
    # Expecting parameters: url and vote_type ("up" or "down")
    url = request.form.get("url")
    vote_type = request.form.get("vote")
    if not url or vote_type not in ["up", "down"]:
        return jsonify({"error": "Invalid parameters"}), 400

    vote_record = Vote.query.filter_by(url=url).first()
    if not vote_record:
        vote_record = Vote(url=url, upvotes=0, downvotes=0)
        db.session.add(vote_record)

    if vote_type == "up":
        vote_record.upvotes += 1
    else:
        vote_record.downvotes += 1

    db.session.commit()
    return jsonify({"url": url, "upvotes": vote_record.upvotes, "downvotes": vote_record.downvotes})

if __name__ == "__main__":
    app.run()