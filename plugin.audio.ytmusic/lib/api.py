"""YouTube Music API - thin wrapper around innertube client."""

import json
import os
import re
import time

import xbmc
import xbmcaddon
import xbmcvfs
from lib.innertube import YTMusicClient

ADDON = xbmcaddon.Addon()
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
HOME_CACHE_FILE = os.path.join(PROFILE, 'home_cache.json')
HOME_CACHE_LOCK = os.path.join(PROFILE, 'home_cache.lock')
HOME_CACHE_TTL = 90

# Resolution setting -> pixel size for square Google cover art.
_THUMB_SIZES = {'0': 544, '1': 800, '2': 1200, '3': 1600}


def _thumb_size():
    """User-selected cover-art resolution (px). Defaults to 1200."""
    try:
        return _THUMB_SIZES.get(ADDON.getSetting('thumb_res') or '2', 1200)
    except Exception:
        return 1200

_client = None


def log(msg):
    xbmc.log('[YTMusic] api: {}'.format(msg), xbmc.LOGINFO)


def get_client():
    global _client
    if _client is None:
        from lib.auth import get_auth_header, get_cookie_header, get_page_id
        _client = YTMusicClient(
            auth_header_fn=get_auth_header,
            cookie_header_fn=get_cookie_header,
            page_id=get_page_id(),
        )
    return _client


def reset_client():
    global _client
    _client = None


def get_home():
    """Return the personalised Home feed, sharing it between dashboard widgets.

    Bingie loads its YTMusic widgets concurrently.  Without a small
    cross-process cache every widget makes the same authenticated browse call,
    which can make one of them exceed Kodi's directory timeout.
    """
    def read_cache():
        with open(HOME_CACHE_FILE, 'r') as f:
            cache = json.load(f)
        sections = cache.get('sections')
        age = time.time() - cache.get('timestamp', 0)
        return sections, age

    try:
        sections, age = read_cache()
        if isinstance(sections, list) and age < HOME_CACHE_TTL:
            log('Using cached home feed ({:.0f}s old)'.format(age))
            return sections
    except (IOError, ValueError, TypeError):
        sections = None

    # One widget fetches a missing or stale feed.  The others either use the
    # previous feed immediately or wait briefly for that one request to finish.
    try:
        os.makedirs(PROFILE, exist_ok=True)
        lock_fd = os.open(HOME_CACHE_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        if isinstance(sections, list):
            log('Using stale home feed while another widget refreshes it')
            return sections
        deadline = time.time() + 15
        while time.time() < deadline:
            time.sleep(0.2)
            try:
                sections, age = read_cache()
                if isinstance(sections, list) and age < HOME_CACHE_TTL:
                    log('Using home feed fetched by another widget')
                    return sections
            except (IOError, ValueError, TypeError):
                pass
        # A failed fetch must not leave the dashboard unusable.
        return get_client().get_home()

    try:
        sections = get_client().get_home()
        if isinstance(sections, list):
            with open(HOME_CACHE_FILE, 'w') as f:
                json.dump({'timestamp': time.time(), 'sections': sections}, f)
        return sections
    finally:
        try:
            os.close(lock_fd)
            os.remove(HOME_CACHE_LOCK)
        except OSError:
            pass


def get_library_playlists(limit=25):
    return get_client().get_library_playlists(limit=limit)


def get_library_songs(limit=25):
    return get_client().get_library_songs(limit=limit)


def get_library_albums(limit=25):
    return get_client().get_library_albums(limit=limit)


def get_library_artists(limit=25):
    return get_client().get_library_artists(limit=limit)


def get_liked_songs(limit=100):
    return get_client().get_liked_songs(limit=limit)


def get_playlist(playlist_id, limit=100):
    return get_client().get_playlist(playlist_id, limit=limit)


def get_album(browse_id):
    return get_client().get_album(browse_id)


def get_artist(channel_id):
    return get_client().get_artist(channel_id)


def search(query, filter_type=None, limit=50):
    return get_client().search(query, filter_type=filter_type, limit=limit)


def get_artist_albums(browse_id, params=''):
    return get_client().get_artist_albums(browse_id, params=params)


def get_watch_playlist(video_id):
    return get_client().get_watch_playlist(video_id)


def rate_song(video_id, rating):
    """Set a song's YouTube Music rating (LIKE, DISLIKE, or INDIFFERENT)."""
    return get_client().rate_song(video_id, rating)


def get_stream_url(video_id):
    from lib.resolver import get_stream_url as _resolve
    return _resolve(video_id)


def get_history():
    return get_client().get_history()


def get_thumbnails(item):
    thumbs = item.get('thumbnails') or []
    if not thumbs:
        return ''
    best = max(thumbs, key=lambda t: t.get('width', 0) * t.get('height', 0))
    url = best.get('url', '')
    return _upscale_thumbnail(url)


def _upscale_thumbnail(url):
    """Request high-res version of YouTube Music thumbnails."""
    if not url:
        return ''
    size = _thumb_size()
    # Google image-proxy hosts (lh3-lh6.googleusercontent.com, yt3.ggpht.com,
    # yt3.googleusercontent.com, music.youtube.com proxies, etc.) all accept a
    # size token after '='. Forms seen: =w120-h120, =w60-h60-l90-rj, =s226, =s0.
    if 'googleusercontent.com' in url or 'ggpht.com' in url:
        new = '=w{0}-h{1}-l90-rj'.format(size, size)
        if '=' in url:
            url = re.sub(r'=[swh]\d.*$', new, url)
        else:
            url = url + new
    # i.ytimg.com URLs: replace the default-variant basename with maxresdefault
    elif 'ytimg.com' in url:
        url = re.sub(r'/(?:default|mqdefault|hqdefault|sddefault)\.jpg',
                     '/maxresdefault.jpg', url)
    return url
