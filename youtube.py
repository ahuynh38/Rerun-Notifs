"""Signs in to YouTube as the channel owner and reads the newest uploads.

Calls the YouTube Data API directly over HTTPS instead of loading Google's
large google-api-python-client library, which keeps the background process small.
"""

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

from config import APP_DIR, CLIENT_SECRET_FILE, TOKEN_FILE

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
API_BASE = "https://www.googleapis.com/youtube/v3"


class AuthError(Exception):
    """Raised when there's no usable sign-in and `python main.py --auth` must be run."""


def authorize_interactive() -> None:
    """Open a browser for the one-time Google sign-in and save the token."""
    # Imported here so the background process never loads the sign-in flow.
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CLIENT_SECRET_FILE.exists():
        raise AuthError(f"Download your OAuth client file from Google Cloud and save it as {CLIENT_SECRET_FILE}.")

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
    # prompt="consent" makes Google always return a refresh token, which is what
    # lets the notifier keep working without ever showing a browser again.
    creds = flow.run_local_server(port=0, prompt="consent")

    APP_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")


class YouTubeClient:
    def __init__(self) -> None:
        if not TOKEN_FILE.exists():
            raise AuthError("Not signed in yet. Run `python main.py --auth`.")
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if not creds.refresh_token:
            raise AuthError("Saved sign-in has no refresh token. Run `python main.py --auth` again.")

        # AuthorizedSession renews the short-lived access token by itself when needed.
        self._session = AuthorizedSession(creds)
        self._uploads_playlist_id: str | None = None

    def _get(self, endpoint: str, **params) -> dict:
        try:
            resp = self._session.get(f"{API_BASE}/{endpoint}", params=params, timeout=30)
        except RefreshError as e:
            # The refresh token was revoked or expired (e.g. the app is still in "Testing").
            raise AuthError(f"Google rejected the saved sign-in ({e}). Run `python main.py --auth` again.") from e
        if resp.status_code == 401:
            raise AuthError("Google rejected the saved sign-in. Run `python main.py --auth` again.")
        resp.raise_for_status()
        return resp.json()

    def uploads_playlist_id(self) -> str:
        """Find the hidden playlist that holds every upload on the channel (looked up once)."""
        if self._uploads_playlist_id is None:
            items = self._get("channels", part="contentDetails", mine="true").get("items") or []
            if not items:
                raise AuthError("This Google account has no YouTube channel. Sign in with the channel owner's account.")
            self._uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        return self._uploads_playlist_id

    def recent_upload_statuses(self) -> dict[str, str]:
        """Return {video_id: privacy_status} for the 50 newest uploads, oldest first.

        privacy_status is "public", "unlisted" or "private". Costs 2 quota units.
        """
        playlist = self._get(
            "playlistItems",
            part="contentDetails",
            playlistId=self.uploads_playlist_id(),
            maxResults=50,
        )
        video_ids = [item["contentDetails"]["videoId"] for item in playlist.get("items", [])]
        if not video_ids:
            return {}

        # The playlist entry's own privacy field isn't reliable, so ask for each video's real status.
        videos = self._get("videos", part="status", id=",".join(video_ids), maxResults=50)
        statuses = {v["id"]: v["status"]["privacyStatus"] for v in videos.get("items", [])}

        # The playlist lists newest first; flip it so announcements post in upload order.
        # Deleted videos show up in the playlist but not in `statuses`, so they're skipped.
        return {vid: statuses[vid] for vid in reversed(video_ids) if vid in statuses}
