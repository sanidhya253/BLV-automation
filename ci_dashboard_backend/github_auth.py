"""
GitHub OAuth Authentication for BLV Dashboard
==============================================
- AUTH_ENABLED=true  → GitHub OAuth enforced (use on Railway)
- AUTH_ENABLED=false → No auth, open access (default for local Docker)
- Only the GITHUB_ALLOWED_USER can access when auth is enabled
- MFA is inherited from the user's GitHub account settings
"""

import os
import secrets
import functools
import requests as http_requests  # renamed to avoid clash with flask.request
from flask import session, redirect, request, url_for, jsonify

# ─── Configuration ───────────────────────────────────────────────────────────
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").lower() == "true"
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_ALLOWED_USER = os.environ.get("GITHUB_ALLOWED_USER", "")

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_API = "https://api.github.com/user"


# ─── Decorator: Protect Routes ──────────────────────────────────────────────
def login_required(f):
    """
    Protects dashboard routes.
    - If AUTH_ENABLED=false → allows everyone through (local Docker mode)
    - If AUTH_ENABLED=true  → requires GitHub OAuth session
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not AUTH_ENABLED:
            return f(*args, **kwargs)
        if not session.get("github_user"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated_function


# ─── Route Handlers ─────────────────────────────────────────────────────────
def register_auth_routes(app):
    """Register all authentication routes on the Flask app."""

    @app.route("/login")
    def login_page():
        """Show login page with 'Login with GitHub' button."""
        # If auth is disabled, just go straight to dashboard
        if not AUTH_ENABLED:
            return redirect(url_for("dashboard"))

        error_html = ""
        if request.args.get("error"):
            error_html = f'<div class="error-msg">{request.args.get("error")}</div>'

        return f'''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>BLV Dashboard: Login</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    background: #020617;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    color: #e2e8f0;
                }}
                .login-card {{
                    background: #052E16;
                    border: 1px solid #14532D;
                    border-radius: 16px;
                    padding: 48px 40px;
                    text-align: center;
                    max-width: 420px;
                    width: 90%;
                    box-shadow: 0 25px 50px rgba(0,0,0,0.4);
                }}
                .shield-icon {{ font-size: 48px; margin-bottom: 16px; }}
                h1 {{ font-size: 24px; font-weight: 700; margin-bottom: 8px; color: #F8FAFC; }}
                .subtitle {{
                    font-size: 14px; color: #94A3B8;
                    margin-bottom: 32px; line-height: 1.5;
                }}
                .github-btn {{
                    display: inline-flex; align-items: center; gap: 10px;
                    background: #f8fafc; color: #0f172a;
                    padding: 14px 32px; border-radius: 10px;
                    text-decoration: none; font-size: 16px; font-weight: 600;
                    transition: all 0.2s; border: none;
                }}
                .github-btn:hover {{
                    background: #e2e8f0; transform: translateY(-1px);
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                }}
                .github-btn svg {{ width: 22px; height: 22px; }}
                .error-msg {{
                    background: #451a2a; border: 1px solid #f87171;
                    color: #fca5a5; padding: 12px 16px;
                    border-radius: 8px; margin-bottom: 24px; font-size: 14px;
                }}
                .info {{ margin-top: 24px; font-size: 12px; color: #64748b; }}
            </style>
        </head>
        <body>
            <div class="login-card">
                <div class="shield-icon">&#128737;</div>
                <h1>BLV Dashboard</h1>
                <p class="subtitle">
                    Authorized access only.<br>
                    Sign in with the GitHub account that owns this repository.
                </p>
                {error_html}
                <a href="/auth/github" class="github-btn">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
                    </svg>
                    Sign in with GitHub
                </a>
                <p class="info">
                    &#128274; Only the repository owner can access this dashboard.<br>
                    GitHub MFA is enforced if enabled on your account.
                </p>
            </div>
        </body>
        </html>
        '''

    @app.route("/auth/github")
    def github_login():
        """Redirect user to GitHub for OAuth authorization."""
        if not AUTH_ENABLED:
            return redirect(url_for("dashboard"))

        if not GITHUB_CLIENT_ID:
            return "Error: GITHUB_CLIENT_ID not configured. Set it in environment variables.", 500

        # Generate a random state to prevent CSRF
        state = secrets.token_hex(16)
        session["oauth_state"] = state

        params = {
            "client_id": GITHUB_CLIENT_ID,
            "redirect_uri": url_for("github_callback", _external=True),
            "scope": "read:user",
            "state": state,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return redirect(f"{GITHUB_AUTH_URL}?{query}")

    @app.route("/auth/callback")
    def github_callback():
        """Handle the OAuth callback from GitHub."""
        if not AUTH_ENABLED:
            return redirect(url_for("dashboard"))

        # Verify state to prevent CSRF
        if request.args.get("state") != session.pop("oauth_state", None):
            return redirect(url_for("login_page", error="Invalid state. Please try again."))

        code = request.args.get("code")
        if not code:
            return redirect(url_for("login_page", error="Authorization denied."))

        # Exchange code for access token
        try:
            token_resp = http_requests.post(
                GITHUB_TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": GITHUB_CLIENT_ID,
                    "client_secret": GITHUB_CLIENT_SECRET,
                    "code": code,
                },
                timeout=10,
            )
        except Exception as e:
            return redirect(url_for("login_page", error=f"Connection error: {e}"))

        if token_resp.status_code != 200:
            return redirect(url_for("login_page", error="GitHub token exchange failed."))

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            error_desc = token_data.get("error_description", "No access token received.")
            return redirect(url_for("login_page", error=error_desc))

        # Fetch the authenticated user's profile
        try:
            user_resp = http_requests.get(
                GITHUB_USER_API,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                timeout=10,
            )
        except Exception as e:
            return redirect(url_for("login_page", error=f"GitHub API error: {e}"))

        if user_resp.status_code != 200:
            return redirect(url_for("login_page", error="Failed to fetch GitHub profile."))

        user_data = user_resp.json()
        github_username = user_data.get("login", "")

        # Check if this user is the allowed owner
        if GITHUB_ALLOWED_USER and github_username.lower() != GITHUB_ALLOWED_USER.lower():
            return redirect(url_for(
                "login_page",
                error=f"Access denied. User '{github_username}' is not the repository owner."
            ))

        # Store authenticated user in session
        session["github_user"] = github_username
        session["github_avatar"] = user_data.get("avatar_url", "")

        return redirect(url_for("dashboard"))

    @app.route("/auth/logout")
    def logout():
        """Clear session and redirect to login."""
        session.clear()
        if AUTH_ENABLED:
            return redirect(url_for("login_page"))
        return redirect(url_for("dashboard"))

    @app.route("/auth/status")
    def auth_status():
        """API endpoint to check auth status."""
        if not AUTH_ENABLED:
            return jsonify({"authenticated": True, "auth_enabled": False, "username": "local"})
        if session.get("github_user"):
            return jsonify({
                "authenticated": True,
                "auth_enabled": True,
                "username": session["github_user"],
                "avatar": session.get("github_avatar", ""),
            })
        return jsonify({"authenticated": False, "auth_enabled": True}), 401
