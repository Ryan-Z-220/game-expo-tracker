import math
import os

from dotenv import load_dotenv
from flask import Flask, render_template, request, abort
from supabase import create_client, Client


load_dotenv()

app = Flask(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Missing Supabase config. Please set SUPABASE_URL and SUPABASE_KEY in .env"
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


@app.route("/")
def home():
    return render_template("base.html")


@app.route("/games")
def games():
    page = request.args.get("page", 1, type=int)
    search_type = request.args.get("search_type", "name")
    query = request.args.get("q", "").strip()
    release_filter = request.args.get("release_filter", "all")

    per_page = 8

    if page < 1:
        page = 1

    start = (page - 1) * per_page
    end = start + per_page - 1

    selected_columns = (
        "id, slug, name, card_image_url, publisher, developer, "
        "release_date, release_window, release_year, platforms, genres, "
        "short_description, display_order"
    )

    count_query = supabase.table("games").select("id", count="exact")
    data_query = supabase.table("games").select(selected_columns)

    if query:
        pattern = f"%{query}%"

        if search_type == "company":
            filter_text = f"publisher.ilike.{pattern},developer.ilike.{pattern}"
            count_query = count_query.or_(filter_text)
            data_query = data_query.or_(filter_text)
        else:
            search_type = "name"
            count_query = count_query.ilike("name", pattern)
            data_query = data_query.ilike("name", pattern)

    if release_filter == "no_exact_date":
        count_query = count_query.is_("release_date", "null")
        data_query = data_query.is_("release_date", "null")

    elif release_filter == "exact_date":
        count_query = count_query.not_.is_("release_date", "null")
        data_query = data_query.not_.is_("release_date", "null")

    elif release_filter == "2026":
        count_query = count_query.eq("release_year", 2026)
        data_query = data_query.eq("release_year", 2026)

    elif release_filter == "2027":
        count_query = count_query.eq("release_year", 2027)
        data_query = data_query.eq("release_year", 2027)

    else:
        release_filter = "all"

    count_response = count_query.execute()
    total_games = count_response.count or 0
    total_pages = max(math.ceil(total_games / per_page), 1)

    if page > total_pages:
        page = total_pages
        start = (page - 1) * per_page
        end = start + per_page - 1

    response = (
        data_query
        .order("display_order")
        .range(start, end)
        .execute()
    )

    games_data = response.data or []

    return render_template(
        "games.html",
        games=games_data,
        page=page,
        total_pages=total_pages,
        total_games=total_games,
        query=query,
        search_type=search_type,
        release_filter=release_filter,
    )

@app.route("/games/<slug>")
def game_detail(slug):
    response = (
        supabase.table("games")
        .select("*")
        .eq("slug", slug)
        .maybe_single()
        .execute()
    )

    game = response.data

    if not game:
        abort(404)

    page = request.args.get("page", 1, type=int)
    query = request.args.get("q", "").strip()
    search_type = request.args.get("search_type", "name")
    release_filter = request.args.get("release_filter", "all")

    return render_template(
        "game_detail.html",
        game=game,
        page=page,
        query=query,
        search_type=search_type,
        release_filter=release_filter,
    )


if __name__ == "__main__":
    app.run(debug=True)