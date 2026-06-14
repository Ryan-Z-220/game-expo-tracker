# manage requests in project 

import math
import os
import secrets

from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from flask import Flask, render_template, request, abort, redirect, url_for, flash, session
from supabase import create_client, Client


load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Missing Supabase config. Please set SUPABASE_URL and SUPABASE_KEY in .env"
    )

# supabase create client request
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
admin_supabase: Client | None = None
if SUPABASE_SERVICE_ROLE_KEY:
    admin_supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def generate_public_username():
    return f"user_{secrets.token_hex(4)}"


@app.context_processor
def inject_user():
    return {
        "current_user": session.get("user"),
        "current_profile": session.get("profile"),
    }

def get_supabase_for_current_user():
    user_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    access_token = session.get("access_token")
    refresh_token = session.get("refresh_token")

    if access_token and refresh_token:
        user_client.auth.set_session(access_token, refresh_token)

    return user_client

def get_current_user_id():
    user = session.get("user")

    if not user:
        return None

    return user.get("id")

def create_unique_public_username():
    for _ in range(5):
        username = generate_public_username()

        existing = (
            supabase.table("profiles")
            .select("id")
            .eq("username", username)
            .limit(1)
            .execute()
        )

        if not existing.data:
            return username

    raise RuntimeError("Could not generate a unique username.")

# time format
@app.template_filter("format_datetime")
def format_datetime(value):
    if not value:
        return ""

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        nz_time = dt.astimezone(ZoneInfo("Pacific/Auckland"))
        return nz_time.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)[:16].replace("T", " ")

# request for base page
@app.route("/")
def home():
    return render_template("base.html")

# request for game gallery section
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

# requeste for game detail section by game name (include watchlist options)
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
    from_page = request.args.get("from_page", "gallery")

    is_in_watchlist = False
    user_id = get_current_user_id()

    if user_id:
        user_supabase = get_supabase_for_current_user()

        watchlist_response = (
            user_supabase.table("watchlist")
            .select("id")
            .eq("user_id", user_id)
            .eq("game_id", game["id"])
            .limit(1)
            .execute()
        )

        watchlist_rows = watchlist_response.data or []
        is_in_watchlist = len(watchlist_rows) > 0

    comments_response = (
        supabase.table("comments")
        .select("id, user_id, user_email, content, created_at")
        .eq("game_id", game["id"])
        .order("created_at", desc=True)
        .execute()
    )

    comments = comments_response.data or []

    comment_user_ids = list({
        comment["user_id"]
        for comment in comments
        if comment.get("user_id")
    })

    profiles_by_id = {}

    if comment_user_ids:
        profiles_response = (
            supabase.table("profiles")
            .select("id, username, display_name")
            .in_("id", comment_user_ids)
            .execute()
        )

        profiles_by_id = {
            profile["id"]: profile
            for profile in (profiles_response.data or [])
        }

    for comment in comments:
        profile = profiles_by_id.get(comment.get("user_id"))

        if profile:
            comment["author_name"] = profile.get("display_name") or profile.get("username")
            comment["author_username"] = profile.get("username")
        else:
            comment["author_name"] = comment.get("user_email") or "User"
            comment["author_username"] = None

    return render_template(
        "game_detail.html",
        game=game,
        page=page,
        query=query,
        search_type=search_type,
        release_filter=release_filter,
        is_in_watchlist=is_in_watchlist,
        from_page=from_page,
        comments=comments,
        current_user_id=user_id,
    )

# request for user signup section
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = create_unique_public_username()
        display_name = request.form.get("display_name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not email or not password or not confirm_password:
            flash("Please fill in all required fields.")
            return render_template("signup.html")

        if password != confirm_password:
            flash("Passwords do not match.")
            return render_template("signup.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters.")
            return render_template("signup.html")

        if not admin_supabase:
            flash("Signup is temporarily unavailable because server profile setup is missing.")
            return render_template("signup.html")

        try:
            existing_profile = (
                supabase.table("profiles")
                .select("id")
                .eq("username", username)
                .limit(1)
                .execute()
            )

            if existing_profile.data:
                flash("This username is already taken. Please choose another one.")
                return render_template("signup.html")

            auth_response = supabase.auth.sign_up(
                {
                    "email": email,
                    "password": password,
                }
            )

            user = auth_response.user

            if not user:
                flash("Could not create account. Please try again.")
                return render_template("signup.html")

            admin_supabase.table("profiles").insert(
                {
                    "id": user.id,
                    "username": username,
                    "display_name": display_name or "New User",
                    "role": "user",
                }
            ).execute()

            flash("Account created. Please check your email to confirm your account, then log in.")
            return redirect(url_for("login"))

        except Exception as error:
            error_text = str(error)

            if "duplicate" in error_text.lower() or "unique" in error_text.lower():
                flash("This username is already taken. Please choose another one.")
            else:
                flash(f"Signup failed: {error}")

            return render_template("signup.html")

    return render_template("signup.html")

# request for user login section
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter both email and password.")
            return render_template("login.html")

        try:
            response = supabase.auth.sign_in_with_password(
                {
                    "email": email,
                    "password": password,
                }
            )

            user = response.user
            session_data = response.session

            if not user or not session_data:
                flash("Login failed. Please check your email and password.")
                return render_template("login.html")

            session["user"] = {
                "id": user.id,
                "email": user.email,
            }

            profile_response = (
                supabase.table("profiles")
                .select("id, username, display_name, avatar_url, role")
                .eq("id", user.id)
                .limit(1)
                .execute()
            )

            profiles = profile_response.data or []
            profile = profiles[0] if profiles else None

            session["profile"] = profile or {
                "id": user.id,
                "username": user.email.split("@")[0],
                "display_name": user.email.split("@")[0],
                "avatar_url": None,
                "role": "user",
            }            

            session["access_token"] = session_data.access_token
            session["refresh_token"] = session_data.refresh_token

            flash("You are now logged in.")
            return redirect(url_for("games"))

        except Exception as error:
            flash(f"Login failed: {error}")
            return render_template("login.html")

    return render_template("login.html")

# request for user logout section
@app.route("/logout", methods=["POST"])
def logout():
    try:
        supabase.auth.sign_out()
    except Exception:
        pass

    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("games"))

# request for add a game into watchlist (login required)
@app.route("/watchlist/add/<game_id>", methods=["POST"])
def add_to_watchlist(game_id):
    next_url = request.form.get("next_url") or url_for("games")
    user_id = get_current_user_id()

    wants_json = request.headers.get("X-Requested-With") == "fetch"

    if not user_id:
        if wants_json:
            return {"success": False, "message": "Please log in first."}, 401

        flash("Please log in to add games to your watchlist.")
        return redirect(url_for("login"))

    user_supabase = get_supabase_for_current_user()

    try:
        user_supabase.table("watchlist").insert(
            {
                "user_id": user_id,
                "game_id": game_id,
            }
        ).execute()

        if wants_json:
            return {
                "success": True,
                "in_watchlist": True,
                "message": "Game added to your watchlist.",
            }

        flash("Game added to your watchlist.")

    except Exception as error:
        error_text = str(error)

        if "duplicate" in error_text.lower() or "unique" in error_text.lower():
            if wants_json:
                return {
                    "success": True,
                    "in_watchlist": True,
                    "message": "This game is already in your watchlist.",
                }

            flash("This game is already in your watchlist.")
        else:
            if wants_json:
                return {
                    "success": False,
                    "message": f"Could not add game to watchlist: {error}",
                }, 400

            flash(f"Could not add game to watchlist: {error}")

    return redirect(next_url)

# request for remove a game from watchlist (login required)
@app.route("/watchlist/remove/<game_id>", methods=["POST"])
def remove_from_watchlist(game_id):
    next_url = request.form.get("next_url") or url_for("games")
    user_id = get_current_user_id()

    wants_json = request.headers.get("X-Requested-With") == "fetch"

    if not user_id:
        if wants_json:
            return {"success": False, "message": "Please log in first."}, 401

        flash("Please log in first.")
        return redirect(url_for("login"))

    user_supabase = get_supabase_for_current_user()

    try:
        (
            user_supabase.table("watchlist")
            .delete()
            .eq("user_id", user_id)
            .eq("game_id", game_id)
            .execute()
        )

        if wants_json:
            return {
                "success": True,
                "in_watchlist": False,
                "message": "Game removed from your watchlist.",
            }

        flash("Game removed from your watchlist.")

    except Exception as error:
        if wants_json:
            return {
                "success": False,
                "message": f"Could not remove game from watchlist: {error}",
            }, 400

        flash(f"Could not remove game from watchlist: {error}")

    return redirect(next_url)

# request to show user's watchlist
@app.route("/watchlist")
def watchlist():
    user_id = get_current_user_id()

    if not user_id:
        flash("Please log in to view your watchlist.")
        return redirect(url_for("login"))

    user_supabase = get_supabase_for_current_user()

    response = (
        user_supabase.table("watchlist")
        .select(
            "created_at, games(id, slug, name, card_image_url, publisher, developer, "
            "release_date, release_window, platforms, genres, short_description, display_order)"
        )
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    watchlist_items = response.data or []

    games_data = [
        item["games"]
        for item in watchlist_items
        if item.get("games")
    ]

    return render_template(
        "watchlist.html",
        games=games_data,
        total_games=len(games_data),
    )

# request to add a comment
@app.route("/comments/add/<game_id>", methods=["POST"])
def add_comment(game_id):
    user_id = get_current_user_id()

    if not user_id:
        flash("Please log in to write a comment.")
        return redirect(url_for("login"))

    content = request.form.get("content", "").strip()
    next_url = request.form.get("next_url") or url_for("games")

    if not content:
        flash("Comment cannot be empty.")
        return redirect(next_url)

    if len(content) > 1000:
        flash("Comment is too long. Please keep it under 1000 characters.")
        return redirect(next_url)

    user = session.get("user") or {}
    user_email = user.get("email")

    user_supabase = get_supabase_for_current_user()

    try:
        user_supabase.table("comments").insert(
            {
                "user_id": user_id,
                "game_id": game_id,
                "user_email": user_email,
                "content": content,
            }
        ).execute()

        flash("Comment posted.")

    except Exception as error:
        flash(f"Could not post comment: {error}")

    return redirect(next_url)

# request to delete a comment
@app.route("/comments/delete/<comment_id>", methods=["POST"])
def delete_comment(comment_id):
    user_id = get_current_user_id()
    next_url = request.form.get("next_url") or url_for("games")

    if not user_id:
        flash("Please log in first.")
        return redirect(url_for("login"))

    user_supabase = get_supabase_for_current_user()

    try:
        (
            user_supabase.table("comments")
            .delete()
            .eq("id", comment_id)
            .eq("user_id", user_id)
            .execute()
        )

        flash("Comment deleted.")

    except Exception as error:
        flash(f"Could not delete comment: {error}")

    return redirect(next_url)

# request for profile section
@app.route("/profile")
def profile():
    user_id = get_current_user_id()

    if not user_id:
        flash("Please log in to view your profile.")
        return redirect(url_for("login"))

    user_supabase = get_supabase_for_current_user()

    profile_response = (
        user_supabase.table("profiles")
        .select("id, username, display_name, avatar_url, role, created_at")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )

    profiles = profile_response.data or []
    profile_data = profiles[0] if profiles else session.get("profile")

    watchlist_response = (
        user_supabase.table("watchlist")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )

    comments_response = (
        user_supabase.table("comments")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )

    return render_template(
        "profile.html",
        profile=profile_data,
        watchlist_count=watchlist_response.count or 0,
        comment_count=comments_response.count or 0,
    )

# request to edit profile
@app.route("/profile/edit", methods=["GET", "POST"])
def edit_profile():
    user_id = get_current_user_id()

    if not user_id:
        flash("Please log in to edit your profile.")
        return redirect(url_for("login"))

    user_supabase = get_supabase_for_current_user()

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()

        if len(display_name) > 40:
            flash("Display name must be 40 characters or less.")
            return redirect(url_for("edit_profile"))

        try:
            response = (
                user_supabase.table("profiles")
                .update({"display_name": display_name or None})
                .eq("id", user_id)
                .execute()
            )

            updated_profiles = response.data or []

            if updated_profiles:
                updated_profile = updated_profiles[0]
            else:
                profile_response = (
                    user_supabase.table("profiles")
                    .select("id, username, display_name, avatar_url, role")
                    .eq("id", user_id)
                    .limit(1)
                    .execute()
                )
                profiles = profile_response.data or []
                updated_profile = profiles[0] if profiles else None

            if updated_profile:
                session["profile"] = updated_profile

            flash("Profile updated.")
            return redirect(url_for("profile"))

        except Exception as error:
            flash(f"Could not update profile: {error}")
            return redirect(url_for("edit_profile"))

    profile_response = (
        user_supabase.table("profiles")
        .select("id, username, display_name, avatar_url, role")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )

    profiles = profile_response.data or []
    profile_data = profiles[0] if profiles else session.get("profile")

    return render_template("edit_profile.html", profile=profile_data)

if __name__ == "__main__":
    app.run(debug=True)