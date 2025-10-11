#!/usr/bin/env python3
"""
Command-line interface for halal-image-downloader
"""

import argparse
import asyncio
import sys
from pathlib import Path
import time
import json
from typing import List, Optional, cast, Dict, Any
from .extractors.instagram.saveclip import InstagramExtractor
from .extractors.instagram.direct import InstagramDirectExtractor
from .extractors.pinterest import PinterestExtractor
from .extractors.reddit import RedditExtractor
from .extractors.twitter import TwitterExtractor
from .extractors.base_extractor import logger, PermanentError
from . import __version__
import os
import re
import subprocess
import shutil


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser with yt-dlp style arguments."""
    
    parser = argparse.ArgumentParser(
        prog='halal-image-downloader',
        description='A command-line tool for fast and reliable image downloading from supported sources.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  halal-image-downloader "https://instagram.com/p/ABC123"
  halal-image-downloader "https://pinterest.com/pin/123456789"
  halal-image-downloader "https://x.com/username/status/123456789" -o ~/Downloads
  halal-image-downloader "https://reddit.com/r/Art" --format jpg --quality best

Tip:
  You can run this tool using either the short command "hi-dlp" or the full
  "halal-image-downloader" name.
        '''
    )
    
    # Positional argument
    parser.add_argument(
        'url',
        nargs='?',
        help='URL of the social media post to download images from'
    )
    
    # General Options
    general = parser.add_argument_group('General Options')
    # Use -v as short flag for version (common shorthand). Move verbose to -V to avoid
    # clash with the version short flag.
    general.add_argument(
        '-v', '--version',
        action='version',
        version=f'%(prog)s {__version__}',
        help='Show program version and exit'
    )
    general.add_argument(
        '-U', '--update',
        action='store_true',
        help='Update this program to latest version'
    )
    # Use -V as short flag for verbose to avoid colliding with -v (version)
    general.add_argument(
        '-V', '--verbose',
        action='store_true',
        help='Print various debugging information'
    )
    general.add_argument(
        '--debug',
        action='store_true',
        help='Run in debug (headful) mode'
    )
    general.add_argument(
        '--ig-chrome-channel',
        action='store_true',
        help='Instagram only: launch Chrome stable channel for Playwright (requires Google Chrome installed)'
    )
    general.add_argument(
        '--ig-accept-cookies',
        action='store_true',
        help='Instagram only: accept cookie banner if present (may be required for media playback)'
    )
    general.add_argument(
        '--debug-wait',
        type=float,
        default=0.0,
        metavar='SECONDS',
        help='When --debug is used, keep the browser open for SECONDS (default: 0). If used alone, run headless but delay close and save screenshots.'
    )
    general.add_argument(
        '--install-all-browsers',
        action='store_true',
        help='Install all Playwright browsers (chromium, firefox, webkit) and exit if no URL is provided'
    )
    general.add_argument(
        '--install-browser',
        choices=['chromium', 'firefox', 'webkit'],
        help='Install a single Playwright browser and exit if no URL is provided'
    )
    general.add_argument(
        '--install-browsers',
        nargs='+',
        choices=['chromium', 'firefox', 'webkit'],
        help='Install multiple Playwright browsers and exit if no URL is provided'
    )
    # Mode argument removed - only browser mode supported
    general.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Activate quiet mode'
    )
    general.add_argument(
        '--no-warnings',
        action='store_true',
        help='Ignore warnings'
    )
    general.add_argument(
        '-s', '--simulate',
        action='store_true',
        help='Do not download images, simulate only'
    )
    general.add_argument(
        '--skip-download',
        action='store_true',
        help='Do not download images'
    )
    general.add_argument(
        '--print-json',
        action='store_true',
        help='Output progress information as JSON'
    )
    general.add_argument(
        '-J', '--dump-json',
        action='store_true',
        help='Dump JSON metadata and exit (no downloading, like yt-dlp -J)'
    )
    
    # Network Options
    network = parser.add_argument_group('Network Options')
    network.add_argument(
        '--proxy',
        metavar='URL',
        help='Use the specified HTTP/HTTPS/SOCKS proxy'
    )
    network.add_argument(
        '--socket-timeout',
        type=float,
        metavar='SECONDS',
        help='Time to wait before giving up, in seconds'
    )
    network.add_argument(
        '--source-address',
        metavar='IP',
        help='Client-side IP address to bind to'
    )
    network.add_argument(
        '-4', '--force-ipv4',
        action='store_true',
        help='Make all connections via IPv4'
    )
    network.add_argument(
        '-6', '--force-ipv6',
        action='store_true',
        help='Make all connections via IPv6'
    )
    
    # Selection Options
    selection = parser.add_argument_group('Selection Options')
    selection.add_argument(
        '--playlist-items',
        metavar='ITEM_SPEC',
        help='Playlist items to download. Specify indices of the items in the playlist'
    )
    selection.add_argument(
        '--min-filesize',
        metavar='SIZE',
        help='Do not download any files smaller than SIZE'
    )
    selection.add_argument(
        '--max-filesize',
        metavar='SIZE',
        help='Do not download any files larger than SIZE'
    )
    selection.add_argument(
        '--date',
        metavar='DATE',
        help='Download only images uploaded on this date'
    )
    selection.add_argument(
        '--datebefore',
        metavar='DATE',
        help='Download only images uploaded on or before this date'
    )
    selection.add_argument(
        '--dateafter',
        metavar='DATE',
        help='Download only images uploaded on or after this date'
    )
    selection.add_argument(
        '--match-filter',
        metavar='FILTER',
        help='Generic filter for matching images'
    )
    
    # Download Options
    download = parser.add_argument_group('Download Options')
    download.add_argument(
        '-r', '--limit-rate',
        metavar='RATE',
        help='Maximum download rate in bytes per second'
    )
    download.add_argument(
        '-R', '--retries',
        type=int,
        metavar='RETRIES',
        default=10,
        help='Number of retries (default is 10)'
    )
    download.add_argument(
        '--fragment-retries',
        type=int,
        metavar='RETRIES',
        default=10,
        help='Number of retries for a fragment (default is 10)'
    )
    download.add_argument(
        '--skip-unavailable-fragments',
        action='store_true',
        help='Skip unavailable fragments for DASH, hlsnative and ISM'
    )
    download.add_argument(
        '--keep-fragments',
        action='store_true',
        help='Keep downloaded fragments on disk after downloading is finished'
    )
    download.add_argument(
        '--buffer-size',
        type=int,
        metavar='SIZE',
        default=1024,
        help='Size of download buffer (default is 1024)'
    )
    download.add_argument(
        '--resize-buffer',
        action='store_false',
        help='The buffer size is automatically resized from an initial value of --buffer-size'
    )
    download.add_argument(
        '--http-chunk-size',
        type=int,
        metavar='SIZE',
        help='Size of a chunk for chunk-based HTTP downloading'
    )
    download.add_argument(
        '--concurrent-fragments',
        type=int,
        metavar='N',
        default=1,
        help='Number of fragments to download concurrently (default is 1)'
    )
    
    # Filesystem Options
    filesystem = parser.add_argument_group('Filesystem Options')
    filesystem.add_argument(
        '-o', '--output',
        metavar='TEMPLATE',
        help=('Output filename template. Supports full templates like "%%(uploader)s/%%(title)s.%%(ext)s", ' \
             'or a simple readable format using tokens: author, title, date, id, ext. ' \
             'Special path rules: leading "/" = home, "./" = cwd, "../" = parent. ' \
             'If filename has no extension, ".%%(ext)s" is appended automatically.')
    )
    filesystem.add_argument(
        '-E', '--ensure-output-dir',
        action='store_true',
        help='Ensure the output directory (and parents) exists by creating it if missing. Default: error if missing.'
    )
    filesystem.add_argument(
        '--output-na-placeholder',
        metavar='TEXT',
        default='NA',
        help='Placeholder value for unavailable meta fields'
    )
    filesystem.add_argument(
        '--restrict-filenames',
        action='store_true',
        help='Restrict filenames to only ASCII characters'
    )
    filesystem.add_argument(
        '--windows-filenames',
        action='store_true',
        help='Force filenames to be Windows-compatible'
    )
    filesystem.add_argument(
        '--trim-names',
        type=int,
        metavar='LENGTH',
        help='Limit the filename length (excluding extension) to the specified number of characters'
    )
    filesystem.add_argument(
        '-w', '--no-overwrites',
        action='store_true',
        help='Do not overwrite files'
    )
    filesystem.add_argument(
        '-c', '--continue',
        action='store_true',
        help='Force resume of partially downloaded files'
    )
    filesystem.add_argument(
        '--no-continue',
        action='store_true',
        help='Do not resume partially downloaded files'
    )
    filesystem.add_argument(
        '--no-part',
        action='store_true',
        help='Do not use .part files - write directly into output file'
    )
    filesystem.add_argument(
        '--no-mtime',
        action='store_true',
        help='Do not use the Last-modified header to set the file modification time'
    )
    filesystem.add_argument(
        '--write-description',
        action='store_true',
        help='Write image description to a .description file'
    )
    filesystem.add_argument(
        '--write-info-json',
        action='store_true',
        help='Write image metadata to a .info.json file'
    )
    filesystem.add_argument(
        '--write-comments',
        action='store_true',
        help='Write image comments to a .comments file'
    )
    filesystem.add_argument(
        '--load-info-json',
        metavar='FILE',
        help='JSON file containing the image information'
    )
    filesystem.add_argument(
        '--cookies',
        metavar='FILE',
        help='File to read cookies from and dump cookie jar in'
    )
    filesystem.add_argument(
        '--cookies-from-browser',
        metavar='BROWSER',
        help='Load cookies from browser'
    )
    filesystem.add_argument(
        '--no-cookies-from-browser',
        action='store_true',
        help='Do not load cookies from browser'
    )
    filesystem.add_argument(
        '--cache-dir',
        metavar='DIR',
        help='Location in the filesystem where cached files are stored'
    )
    filesystem.add_argument(
        '--no-cache-dir',
        action='store_true',
        help='Disable filesystem caching'
    )
    filesystem.add_argument(
        '--rm-cache-dir',
        action='store_true',
        help='Delete all filesystem cache files'
    )
    
    # Image Format Options
    format_opts = parser.add_argument_group('Image Format Options')
    format_opts.add_argument(
        '-f', '--format',
        metavar='FORMAT',
        help='Image format code, see "FORMAT SELECTION" for more details'
    )
    format_opts.add_argument(
        '--format-sort',
        metavar='SORTORDER',
        help='Sort the formats by the fields given'
    )
    format_opts.add_argument(
        '--format-sort-force',
        action='store_true',
        help='Force the given format_sort'
    )
    format_opts.add_argument(
        '--no-format-sort-force',
        action='store_true',
        help='Some fields have precedence over the user defined format_sort'
    )
    format_opts.add_argument(
        '-S', '--format-selector',
        metavar='SELECTOR',
        help='Format selector expression'
    )
    
    # Image Quality Options
    quality = parser.add_argument_group('Image Quality Options')
    quality.add_argument(
        '--quality',
        choices=['best', 'worst', 'original'],
        default='best',
        help='Image quality preference (default: best)'
    )
    quality.add_argument(
        '--max-width',
        type=int,
        metavar='WIDTH',
        help='Maximum image width'
    )
    quality.add_argument(
        '--max-height',
        type=int,
        metavar='HEIGHT',
        help='Maximum image height'
    )
    quality.add_argument(
        '--min-width',
        type=int,
        metavar='WIDTH',
        help='Minimum image width'
    )
    quality.add_argument(
        '--min-height',
        type=int,
        metavar='HEIGHT',
        help='Minimum image height'
    )
    
    # Authentication Options
    auth = parser.add_argument_group('Authentication Options')
    auth.add_argument(
        '-u', '--username',
        metavar='USERNAME',
        help='Login with this account ID'
    )
    auth.add_argument(
        '-p', '--password',
        metavar='PASSWORD',
        help='Account password'
    )
    auth.add_argument(
        '-2', '--twofactor',
        metavar='TWOFACTOR',
        help='Two-factor authentication code'
    )
    auth.add_argument(
        '-n', '--netrc',
        action='store_true',
        help='Use .netrc authentication data'
    )
    auth.add_argument(
        '--netrc-location',
        metavar='PATH',
        help='Location of .netrc authentication data'
    )
    auth.add_argument(
        '--netrc-cmd',
        metavar='NETRC_CMD',
        help='Command to execute to get the credentials'
    )
    
    # Post-Processing Options
    postproc = parser.add_argument_group('Post-Processing Options')
    postproc.add_argument(
        '--convert-images',
        metavar='FORMAT',
        help='Convert images to another format'
    )
    postproc.add_argument(
        '--image-quality',
        type=int,
        metavar='QUALITY',
        help='Specify image quality for conversion (0-100)'
    )
    postproc.add_argument(
        '--embed-metadata',
        action='store_true',
        help='Embed metadata in image files'
    )
    postproc.add_argument(
        '--no-embed-metadata',
        action='store_true',
        help='Do not embed metadata in image files'
    )
    postproc.add_argument(
        '--parse-metadata',
        metavar='FIELD:FORMAT',
        action='append',
        help='Parse additional metadata from the image filename'
    )
    postproc.add_argument(
        '--replace-in-metadata',
        metavar='FIELDS REGEX REPLACE',
        action='append',
        nargs=3,
        help='Replace text in a metadata field using a regex'
    )
    postproc.add_argument(
        '--exec',
        metavar='CMD',
        help='Execute a command on the file after downloading'
    )
    postproc.add_argument(
        '--exec-before-download',
        metavar='CMD',
        help='Execute a command before each download'
    )
    postproc.add_argument(
        '--no-exec',
        action='store_true',
        help='Do not execute any commands'
    )
    
    # Configuration Options
    config = parser.add_argument_group('Configuration Options')
    config.add_argument(
        '--config-location',
        metavar='PATH',
        help='Location of the configuration file'
    )
    config.add_argument(
        '--no-config',
        action='store_true',
        help='Do not read configuration files'
    )
    config.add_argument(
        '--config-locations',
        metavar='PATH',
        action='append',
        help='Location of the configuration files'
    )
    config.add_argument(
        '--flat-playlist',
        action='store_true',
        help='Do not extract the images of a playlist, only list them'
    )
    config.add_argument(
        '--no-flat-playlist',
        action='store_true',
        help='Extract the images of a playlist'
    )
    
    # Hide unimplemented/placeholder options from help output (keep parsing intact)
    unsupported = {
        # Network
        '--proxy', '--socket-timeout', '--source-address', '-4', '--force-ipv4', '-6', '--force-ipv6',
        # Selection
        '--playlist-items', '--min-filesize', '--max-filesize', '--date', '--datebefore', '--dateafter', '--match-filter',
        # Download
        '-r', '--limit-rate', '-R', '--retries', '--fragment-retries', '--skip-unavailable-fragments', '--keep-fragments',
        '--buffer-size', '--resize-buffer', '--http-chunk-size', '--concurrent-fragments',
        # Filesystem (keep -o and -E visible)
        '--output-na-placeholder', '--restrict-filenames', '--windows-filenames', '--trim-names', '-w', '--no-overwrites',
        '-c', '--continue', '--no-continue', '--no-part', '--no-mtime', '--write-description', '--write-info-json', '--write-comments',
        '--load-info-json', '--cookies', '--cookies-from-browser', '--no-cookies-from-browser', '--cache-dir', '--no-cache-dir', '--rm-cache-dir',
        # Format
        '-f', '--format', '--format-sort', '--format-sort-force', '--no-format-sort-force', '-S', '--format-selector',
        # Quality (keep --quality visible)
        '--max-width', '--max-height', '--min-width', '--min-height',
        # Authentication
        '-u', '--username', '-p', '--password', '-2', '--twofactor', '-n', '--netrc', '--netrc-location', '--netrc-cmd',
        # Post-Processing
        '--convert-images', '--image-quality', '--embed-metadata', '--no-embed-metadata', '--parse-metadata', '--replace-in-metadata', '--exec', '--exec-before-download', '--no-exec',
        # Configuration
        '--config-location', '--no-config', '--config-locations', '--flat-playlist', '--no-flat-playlist',
    }
    for action in parser._actions:
        try:
            if any(opt in unsupported for opt in getattr(action, 'option_strings', [])):
                action.help = argparse.SUPPRESS
        except Exception:
            pass

    return parser


def _resolve_output_dir(output: Optional[str]) -> Path:
    """
    Expand environment variables and ~ in the provided output template/path,
    determine the directory portion, create it if necessary, and return the Path.

    If output contains a template placeholder like "%(title)s" we treat the
    provided string as a filename template and use its parent directory.
    """
    if not output:
        return Path('.')
    # Expand env vars (Windows %VAR% and Unix $VAR) and user (~)
    expanded = os.path.expandvars(output)
    expanded = os.path.expanduser(expanded)
    p = Path(expanded)
    # If the original (or expanded) contains format placeholders, use parent
    if '%(' in output or '%(' in expanded:
        out_dir = p.parent
    else:
        # If path ends with a separator or is an existing dir, treat as dir
        if expanded.endswith(os.sep) or (p.exists() and p.is_dir()):
            out_dir = p
        else:
            out_dir = p.parent
    # Ensure directory exists
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _parse_output_option(output: Optional[str], create_dirs: bool = True) -> tuple[str, Path]:
    """
    Parse -o/--output value and return (output_template, output_dir).

    Rules implemented:
    - Expand env vars and ~.
    - Leading '/' or '\\' is treated as user's home (not filesystem root).
    - './' and '../' are resolved against the current working directory.
    - If input contains full-style templates ("%(...)s" or "{...}") it is
      returned unchanged (but the parent dir is created).
    - Support simple readable tokens (author, title, date, id, ext, idx, cnt)
      and short letter mnemonics (u,t,d,i,e,n,c). Example: 'author/title.ext'
      or 'u_t_e'.
    - If the filename part lacks an extension, append '.%(ext)s'.
    - If the path resolves to a directory (ends with separator or looks like a
      directory) use default filename '%(title)s.%(ext)s'.
    Parameters:
    - create_dirs: when True, ensure the resolved output directory exists. Set to False to avoid
      side-effects (e.g., in --simulate mode).

    """
    default_filename = "post_by_%(uploader)s.%(ext)s"
    # No output provided -> cwd + default name
    if not output:
        out_dir = Path('.').resolve()
        if create_dirs:
            out_dir.mkdir(parents=True, exist_ok=True)
        return default_filename, out_dir

    raw = output
    # Expand env vars and user (~)
    expanded = os.path.expandvars(os.path.expanduser(raw))

    # Leading '/' or '\\' -> user's home
    if raw.startswith('/') or raw.startswith('\\'):
        rest = raw.lstrip('/\\')
        expanded = str(Path.home() / rest)

    # If it starts with './' or '.\\' keep it relative to cwd
    if raw.startswith('./') or raw.startswith('.\\'):
        expanded = str(Path.cwd() / raw[2:])

    # Resolve ../ segments against cwd (do not require existing files)
    cand = Path(expanded)
    if not cand.is_absolute():
        cand = (Path.cwd() / expanded).resolve(strict=False)
    else:
        cand = cand.resolve(strict=False)

    # Detect full template markers
    if '%(' in raw or '%(' in expanded or '{' in raw or '{' in expanded:
        out_template = str(cand)
        out_dir = cand.parent if cand.name else cand
        if create_dirs:
            out_dir.mkdir(parents=True, exist_ok=True)
        return out_template, out_dir

    # Convert path to forward-slash style for token processing
    path_str = cand.as_posix()

    # Token maps
    word_map = {
        'author': '%(uploader)s',
        'title': '%(title)s',
        'date': '%(upload_date)s',
        'id': '%(id)s',
        'ext': '%(ext)s',
        'idx': '%(playlist_index)s',
        'cnt': '%(autonumber)s',
    }
    letter_map = {'u': '%(uploader)s', 't': '%(title)s', 'd': '%(upload_date)s', 'i': '%(id)s', 'e': '%(ext)s', 'n': '%(playlist_index)s', 'c': '%(autonumber)s'}

    # If filename part contains underscores like u_t_e, treat as letter mnemonic
    dir_part = str(cand.parent.as_posix()) if cand.parent else ''
    name_part = cand.name

    def expand_segment(seg: str) -> str:
        # Try letter mnemonic (underscores)
        if '_' in seg and all(len(p) == 1 for p in seg.split('_')):
            parts_keys = seg.split('_')
            parts = [letter_map.get(p) for p in parts_keys]
            if any(p is None for p in parts):
                missing = [parts_keys[i] for i,p in enumerate(parts) if p is None]
                raise ValueError(f"Unknown token(s): {','.join(missing)}")
            # join with ' - ' for readability
            return ' - '.join(cast(str, p) for p in parts)

        # Replace whole word tokens (author, title, etc.)
        def word_repl(m: re.Match) -> str:
            key = m.group(0)
            return word_map.get(key, key) or key

        seg2 = re.sub(r'\b(' + '|'.join(map(re.escape, word_map.keys())) + r')\b', word_repl, seg)
        # If seg2 unchanged but contains letters with no separators, try letters
        if seg2 == seg and len(seg) <= 4 and all(ch.isalpha() for ch in seg):
            # treat as sequence of letters
            parts = [letter_map.get(ch) for ch in seg]
            if all(p is not None for p in parts):
                return ' - '.join(cast(str, p) for p in parts)
        return seg2

    try:
        expanded_name = expand_segment(name_part) if name_part else ''
    except ValueError as e:
        raise

    # Determine if candidate is directory-like
    # Treat as directory when:
    # - ends with path separator
    # - exists as a directory
    # - has empty name part (path ends with separator)
    # - or, it does not exist yet and the last segment has no dot (no extension)
    is_dir_like = (
        raw.endswith('/') or raw.endswith('\\') or
        (cand.exists() and cand.is_dir()) or
        name_part == '' or
        (not cand.exists() and '.' not in name_part)
    )
    if is_dir_like:
        out_dir = cand
        filename = default_filename
    else:
        out_dir = cand.parent
        filename = expanded_name if expanded_name else name_part
        # if filename contains no extension-like part, append .%(ext)s
        if '.' not in filename:
            filename = filename + '.%(ext)s'

    if create_dirs:
        out_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(Path(out_dir) / filename)
    return out_template, out_dir


def _render_output_path(
    out_template: str,
    mapping: Dict[str, Any],
    index: Optional[int] = None,
    total: Optional[int] = None,
    image_url: Optional[str] = None,
) -> Path:
    """Render destination path from a printf-style template and a mapping.

    Supported keys: uploader, title, upload_date, id, ext, playlist_index, autonumber.
    If template has no index token and total>1, append __{index}of{total} to filename.
    Ensures parent directories exist.
    """
    # Derive extension from mapping or image_url
    ext = (str(mapping.get("ext")) if mapping.get("ext") else None) or ""
    if not ext:
        candidate = image_url or ""
        m = re.search(r"\.([a-zA-Z0-9]{3,4})(?:[?#].*)?$", candidate)
        if m:
            ext = m.group(1).lower()
    if not ext:
        ext = "jpg"

    local_map = {
        "uploader": mapping.get("uploader") or "unknown",
        "title": mapping.get("title") or mapping.get("fallback_title") or "instagram_image",
        "upload_date": mapping.get("upload_date") or mapping.get("date") or "NA",
        "id": mapping.get("id") or "",
        "ext": ext,
        "playlist_index": str(index) if index is not None else "",
        "autonumber": str(index) if index is not None else "",
    }

    def repl(mo: re.Match) -> str:
        key = mo.group(1)
        return str(local_map.get(key, mapping.get("na_placeholder", "NA")))

    rendered = re.sub(r"%\(([^)]+)\)s", repl, out_template)
    dest = Path(rendered)
    # Auto-append index suffix if multi-image and no index tokens present
    if total and total > 1 and index is not None and (
        "%(playlist_index)s" not in out_template and "%(autonumber)s" not in out_template
    ):
        dest = dest.with_name(f"{dest.stem}__{index}of{total}{dest.suffix}")

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return dest

def get_platform_name(url: str) -> str:
    """Determine platform name from URL."""
    if "instagram.com" in url:
        return "instagram"
    elif "pinterest.com" in url:
        return "pinterest"
    elif "reddit.com" in url:
        return "reddit"
    elif "twitter.com" in url or "x.com" in url:
        return "twitter"
    else:
        return "unknown"


def create_extractor(platform: str, args) -> Any:
    """Create appropriate extractor based on platform."""
    if platform == "instagram":
        return InstagramExtractor(
            headless=not args.debug,
            debug_wait_seconds=args.debug_wait,
            browser="chromium",
        )
    elif platform == "pinterest":
        return PinterestExtractor()
    elif platform == "reddit":
        return RedditExtractor()
    elif platform == "twitter":
        return TwitterExtractor()
    else:
        raise ValueError(f"Unsupported platform: {platform}")


async def analyze_instagram_post(url: str, output_dir: Path, args) -> tuple[Any, bool, List[Dict], Any]:
    """Analyze Instagram post using direct method for metadata + carousel detection.
    Returns: (metadata, is_carousel, images_info, browser_context)
    Note: Uses analysis-only path that fully closes Playwright to avoid dangling tasks.
    """
    direct_extractor = InstagramDirectExtractor(
        output_dir=str(output_dir),
        headless=not args.debug,
        debug_wait_seconds=args.debug_wait,
        browser="chromium",
        skip_download=True,
        interactive_pauses=False,
        use_chrome_channel=getattr(args, 'ig_chrome_channel', False),
        ig_accept_cookies=getattr(args, 'ig_accept_cookies', False),
        quiet=(not args.verbose),
    )

    try:
        # Extract metadata and detect content type (no browser reuse; Playwright closed inside)
        metadata, images = await direct_extractor._navigate_and_collect_analysis_only(url)

        # Detect carousel based on analysis results (analysis-only path uses sentinel URLs)
        is_carousel = (len(images) >= 1 and images[0].get('url') == 'carousel_detected')

        print(f"📊 Analysis complete:")
        if metadata.author:
            print(f"   👤 Author: {metadata.author}{'✓' if metadata.verified else ''}")
        if metadata.caption:
            print(f"   📝 Caption: {metadata.caption[:50]}{'...' if len(metadata.caption) > 50 else ''}")
        print(f"   🖼️  Content: {'Carousel' if is_carousel else 'Single image'}")

        # Return None for browser_context since we didn't keep it open
        return metadata, is_carousel, images, None

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        # Do not print here; outer handler will show a single user-facing error line.
        # Preserve the error message so outer handlers don't print an empty string
        raise PermanentError(str(e)) from e


def rename_saveclip_files_with_metadata(downloaded_files: List[Path], metadata, post_id: str, out_template: str) -> List[Path]:
    """Rename SaveClip downloaded files using the user's output template and IG metadata."""
    if not metadata or not metadata.author:
        return downloaded_files  # No metadata to apply
    
    renamed_files = []
    total = len(downloaded_files)
    
    for i, old_path in enumerate(downloaded_files, 1):
        try:
            # Ensure old_path is a Path object
            old_path = Path(old_path)
            
            # Prepare mapping for template rendering
            # Derive date in YYYYMMDD if available
            upload_date = None
            if getattr(metadata, 'published_on', None):
                try:
                    from datetime import datetime as _dt
                    dt = _dt.fromisoformat(metadata.published_on.replace("Z", "+00:00"))
                    upload_date = dt.strftime("%Y%m%d")
                except Exception:
                    digits = re.sub(r"\D", "", metadata.published_on)
                    upload_date = digits[:8] if len(digits) >= 8 else (digits or None)

            mapping = {
                "uploader": metadata.author or "unknown",
                "title": (metadata.caption or "instagram_image"),
                "upload_date": upload_date or "NA",
                "id": post_id or "",
                "ext": (old_path.suffix[1:] if old_path.suffix else "jpg"),
                "na_placeholder": getattr(metadata, 'na_placeholder', 'NA'),
            }

            new_path = _render_output_path(
                out_template,
                mapping,
                index=i if total > 1 else None,
                total=total if total > 1 else None,
                image_url=None,
            )
            # Keep files in same directory if template produced a different dir than current
            if new_path.parent != old_path.parent and str(new_path).startswith(str(old_path.parent)):
                pass  # already under same root
            
            # Rename file
            if old_path != new_path:
                old_path.rename(new_path)
                try:
                    print(f"📝 Renamed: {old_path.name} → {new_path.name}")
                except Exception:
                    pass
                renamed_files.append(new_path)
            else:
                renamed_files.append(old_path)
                
        except Exception as e:
            logger.error(f"Failed to rename {old_path}: {e}")
            raise PermanentError(f"File rename failed: {e}") from e
    
    return renamed_files


def handle_json_dump(args) -> None:
    """Handle --dump-json mode for all extractors."""
    try:
        url = args.url
        platform = get_platform_name(url)
        
        if platform == "unknown":
            error_json = {
                "error": "Unsupported platform",
                "url": url,
                "supported_platforms": ["instagram", "pinterest", "reddit", "twitter"]
            }
            print(json.dumps(error_json, indent=2))
            sys.exit(1)
        
        # Create extractor
        extractor = create_extractor(platform, args)
        
        # Try to get JSON metadata if supported
        if hasattr(extractor, 'extract_json_metadata'):
            json_data = extractor.extract_json_metadata(url)
        else:
            # Explicit platform-specific fallback (no generic extract())
            if args.verbose:
                print("Using platform-specific fallback method for JSON dump", file=sys.stderr)

            images: List[Dict[str, Any]] = []
            extraction_method = "fallback"

            if platform == "pinterest":
                # Pinterest uses extract_images()
                images = extractor.extract_images(url)
                extraction_method = "pinterest_extract_images"
            elif platform == "twitter":
                # Twitter uses extract_images()
                images = extractor.extract_images(url)
                extraction_method = "twitter_extract_images"
            elif platform == "reddit":
                # Reddit uses extract_images()
                images = extractor.extract_images(url)
                extraction_method = "reddit_extract_images"
            elif platform == "instagram":
                # Instagram should have extract_json_metadata; if not, return empty images
                images = []
                extraction_method = "instagram_no_fallback"

            json_data = {
                "platform": platform,
                "url": url,
                "extraction_method": extraction_method,
                "images": images,
                "extractor_version": __version__
            }
        
        # Output JSON
        print(json.dumps(json_data, indent=2))
        
    except Exception as e:
        error_json = {
            "error": str(e),
            "url": args.url,
            "platform": get_platform_name(args.url) if args.url else "unknown"
        }
        print(json.dumps(error_json, indent=2))
        sys.exit(1)


def main() -> None:
    """Main entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Friendly startup tip (avoid printing during JSON modes or when quiet)
    # Show this only when a URL is provided to avoid duplicating tips in no-args flow
    if (
        not getattr(args, 'quiet', False)
        and not getattr(args, 'print_json', False)
        and not getattr(args, 'dump_json', False)
        and getattr(args, 'url', None)
    ):
        print("Tip: You can run this tool as 'hi-dlp' (short) or 'halal-image-downloader' (full).")

    # Playwright browsers install helpers
    install_all = bool(getattr(args, 'install_all_browsers', False))
    install_one = getattr(args, 'install_browser', None)
    install_many = getattr(args, 'install_browsers', None) or []

    # Conflict checks
    if install_all and (install_one or install_many):
        parser.error("Use only one of: --install-all-browsers OR --install-browser <name> OR --install-browsers <names>.")
    if install_one and install_many:
        parser.error("Use either --install-browser <name> (single) OR --install-browsers <names> (multiple), not both.")

    to_install: list[str] = []
    if install_all:
        to_install = ['chromium', 'firefox', 'webkit']
    elif install_one:
        to_install = [install_one]
    elif install_many:
        to_install = list(dict.fromkeys(install_many))  # de-dup preserving order

    if to_install:
        try:
            print(f"Installing Playwright browsers: {', '.join(to_install)} ...")
            for b in to_install:
                result = subprocess.run([sys.executable, '-m', 'playwright', 'install', b])
                if result.returncode != 0:
                    print(f"Playwright install for {b} exited with code {result.returncode}. You can try: playwright install {b}")
            print("Playwright browser install complete.")
        except Exception as e:
            print(f"Failed to install Playwright browser(s): {e}")
        # If no URL was provided, exit after installation
        if not getattr(args, 'url', None):
            sys.exit(0)

    # Handle invocation without arguments: print only Examples and Tip (epilog), not full help
    if not args.url and not args.update:
        if not getattr(args, 'quiet', False):
            epilog = getattr(parser, 'epilog', '') or ''
            if epilog:
                print(epilog.strip("\n"))
        sys.exit(1)
    
    # Handle update command
    if args.update:
        print("Updating halal-image-downloader to the latest version...")
        use_uv = shutil.which("uv") is not None
        try:
            if use_uv:
                cmd = ["uv", "pip", "install", "-U", "halal-image-downloader"]
            else:
                cmd = [sys.executable, "-m", "pip", "install", "-U", "halal-image-downloader"]
            result = subprocess.run(cmd)
            if result.returncode == 0:
                try:
                    from importlib.metadata import version as _pkg_version  # type: ignore
                    new_version = _pkg_version("halal-image-downloader")
                    print(f"Update complete. Installed version: {new_version}")
                except Exception:
                    print("Update complete.")
                print("Please re-run the command to use the updated version.")
                sys.exit(0)
            else:
                print("Update failed. You can try running the following command:")
                if use_uv:
                    print("  uv pip install -U halal-image-downloader")
                else:
                    print(f"  {sys.executable} -m pip install -U halal-image-downloader")
                sys.exit(result.returncode)
        except Exception as e:
            print(f"Update failed: {e}")
            print("Try running manually:")
            if use_uv:
                print("  uv pip install -U halal-image-downloader")
            else:
                print(f"  {sys.executable} -m pip install -U halal-image-downloader")
            sys.exit(1)
    
    # Handle simulation mode
    if args.simulate:
        print(f"[simulate] Would download from: {args.url}")
        # Resolve output without creating directories in simulate mode
        out_template, out_dir = _parse_output_option(args.output, create_dirs=False)
        print(f"[simulate] Output directory (absolute): {out_dir}")
        print(f"[simulate] Output template (absolute): {out_template}")
        if args.format:
            print(f"[simulate] Format: {args.format}")
        if args.quality:
            print(f"[simulate] Quality: {args.quality}")
        sys.exit(0)
    
    # Validate required arguments
    if not args.url:
        parser.error("URL is required")
    
    # Handle JSON dump mode early (no need for output directory validation)
    if args.dump_json:
        handle_json_dump(args)
        return
    
    # Resolve output (absolute) respecting --ensure-output-dir and validate existence when not set
    out_template, out_dir = _parse_output_option(args.output, create_dirs=bool(getattr(args, 'ensure_output_dir', False)))
    if not out_dir.exists():
        parser.error(f"Output directory does not exist: {out_dir}. Use --ensure-output-dir to create it.")

    # Print configuration for now
    print(f"halal-image-downloader {__version__}")
    print(f"URL: {args.url}")
    print(f"Output directory (absolute): {out_dir}")
    print(f"Output template (absolute): {out_template}")

    if args.verbose:
        print("Verbose mode enabled")
        print(f"Arguments: {vars(args)}")
    
    if args.format:
        print(f"Format: {args.format}")
    
    if args.quality:
        print(f"Quality: {args.quality}")
    
    # Determine platform and extract images
    try:
        if "instagram.com" in args.url:
            print("🔍 Platform: Instagram")
            headless = not args.debug
            output_dir = out_dir
            
            if args.verbose:
                print(f"Browser mode: {'headless' if headless else 'visible (debug)'}")
                print("Browser engine: chromium")
                print(f"Output directory (absolute): {output_dir}")
            
            start_ts = time.perf_counter()
            
            try:
                # Analyze post (minimal)
                print("\n🔎 Analyzing post...")
                # Use analysis-only path that fully closes Playwright (no context reuse)
                # to avoid TargetClosedError warnings from dangling tasks.
                metadata, is_carousel, images_info, browser_context = asyncio.run(
                    analyze_instagram_post(args.url, output_dir, args)
                )
                # Minimal status
                try:
                    print("Found: " + ("carousel" if is_carousel else "single image"))
                except Exception:
                    pass
                
                async def phase2_download():
                    """Async wrapper for Phase 2 downloads"""
                    if args.skip_download:
                        # Close browser since we're not downloading
                        if browser_context:
                            try:
                                await browser_context.close()
                            except:
                                pass
                        return []
                    
                    # Phase 2: Choose download method based on content type
                    if is_carousel:
                        print(f"\n⬇️  Downloading...")
                        # Use SaveClip extractor for carousel downloads
                        saveclip_extractor = InstagramExtractor(
                            output_dir=str(output_dir),
                            headless=headless,
                            debug_wait_seconds=args.debug_wait,
                            browser="chromium",
                            quiet=(not args.verbose),
                        )
                        files = await saveclip_extractor.extract_with_saveclip(args.url)
                        return files
                    else:
                        print("\n⬇️  Downloading...")
                        # Use direct extractor for fast single image download
                        direct_extractor = InstagramDirectExtractor(
                            output_dir=str(output_dir),
                            headless=headless,
                            debug_wait_seconds=args.debug_wait,
                            browser="chromium",
                            output_template=out_template,
                            skip_download=False,  # Enable download
                            interactive_pauses=False,
                            use_chrome_channel=getattr(args, 'ig_chrome_channel', False),
                            ig_accept_cookies=getattr(args, 'ig_accept_cookies', False),
                            quiet=(not args.verbose),
                        )
                        files = await direct_extractor._download_from_analysis(args.url, metadata, images_info)
                        return files
                
                if args.skip_download:
                    # For carousels, we can't easily list URLs without full SaveClip navigation
                    # Show a summary instead
                    if is_carousel:
                        print("\n--skip-download specified for carousel:")
                        print(f"   📦 Carousel detected (multiple images)")
                        print(f"   👤 Author: {metadata.author or 'unknown'}")
                        if metadata.caption:
                            print(f"   📝 Caption: {metadata.caption[:60]}{'...' if len(metadata.caption) > 60 else ''}")
                        print(f"\n   ℹ️  Carousel images will be downloaded via SaveClip when --skip-download is not used")
                        print(f"   📁 Destination pattern: {out_template}")
                    else:
                        # Single image - use direct extractor data
                        if not images_info:
                            print("❌ No downloadable images found on this Instagram post.")
                            sys.exit(1)

                        print("\n--skip-download specified; planned downloads:")
                        total = len(images_info)
                        for idx, item in enumerate(images_info, start=1):
                            img_url = item.get('url', '')
                            mapping = {
                                "uploader": metadata.author or "unknown",
                                "title": metadata.caption or "instagram_image",
                                "upload_date": "NA",
                                "id": InstagramDirectExtractor.extract_post_id(args.url) or "",
                                "ext": None,
                            }
                            dest = _render_output_path(
                                out_template,
                                mapping,
                                index=(idx if total > 1 else None),
                                total=(total if total > 1 else None),
                                image_url=img_url,
                            )
                            try:
                                dest_show = dest.resolve()
                            except Exception:
                                dest_show = dest
                            print(f"  🖼  {img_url} -> {dest_show}")

                    elapsed = time.perf_counter() - start_ts
                    print(f"\n⏱ Total time: {elapsed:.2f}s")
                    sys.exit(0)
                
                # Run Phase 2 downloads
                downloaded_files = asyncio.run(phase2_download())
                
                # Apply rich metadata to filenames for carousel
                if downloaded_files and metadata and is_carousel:
                    post_id = InstagramDirectExtractor.extract_post_id(args.url)
                    downloaded_files = rename_saveclip_files_with_metadata(
                        downloaded_files, metadata, post_id or "unknown", out_template
                    )
            
            except Exception as e:
                # Minimal error and fallback to SaveClip if analysis couldn't locate image
                err_msg = str(e)
                if ("Could not locate main image" in err_msg) and (not args.skip_download):
                    try:
                        print("Analyzer couldn't locate image. Falling back to SaveClip...")
                        # Use SaveClip JSON analysis to avoid verbose output, then download quietly
                        saveclip = InstagramExtractor(
                            output_dir=str(output_dir),
                            headless=headless,
                            debug_wait_seconds=args.debug_wait,
                            browser="chromium",
                            quiet=True,
                        )
                        data = saveclip.extract_json_metadata(args.url)
                        downloads = [d for d in data.get('available_downloads', []) if isinstance(d, dict) and d.get('type') == 'image' and d.get('download_url')]
                        if not downloads:
                            raise PermanentError("No image links found via SaveClip")
                        total = len(downloads)
                        downloaded_files = []
                        print(f"⬇️  Downloading {total} image(s)...")
                        for i, item in enumerate(downloads, start=1):
                            durl = item.get('download_url')
                            mapping = {
                                "uploader": "unknown",
                                "title": "instagram_image",
                                "upload_date": "NA",
                                "id": data.get('post_id') or "",
                                "ext": None,
                            }
                            dest = _render_output_path(
                                out_template,
                                mapping,
                                index=(i if total > 1 else None),
                                total=(total if total > 1 else None),
                                image_url=durl,
                            )
                            # Compute relative filename under output_dir
                            try:
                                rel = dest.relative_to(output_dir)
                            except Exception:
                                rel = dest.name
                            # Use SaveClip core downloader (quiet)
                            try:
                                path_str = saveclip.download_image(durl, str(rel))
                                downloaded_files.append(Path(path_str))
                            except Exception as de:
                                raise PermanentError(f"Download failed: {de}")
                        print("✅ Done.")
                    except Exception as fe:
                        logger.error(f"Fallback failed: {fe}")
                        print(f"❌ Error: {fe}")
                        if args.verbose:
                            import traceback
                            traceback.print_exc()
                        sys.exit(1)
                else:
                    logger.error(f"Hybrid Instagram extraction failed: {e}")
                    print(f"❌ Error: {e}")
                    if args.verbose:
                        import traceback
                        traceback.print_exc()
                    sys.exit(1)
            
            elapsed = time.perf_counter() - start_ts
            
            if downloaded_files:
                print(f"\n✅ Successfully downloaded {len(downloaded_files)} image(s):")
                for file_path in downloaded_files:
                    # Ensure printed paths are absolute
                    try:
                        print(f"  📁 {Path(file_path).resolve()}")
                    except Exception:
                        print(f"  📁 {file_path}")
                print(f"\n⏱ Total time: {elapsed:.2f}s")
            else:
                print("❌ No images were downloaded")
                print(f"\n⏱ Total time: {elapsed:.2f}s")
                sys.exit(1)
        elif "pinterest.com" in args.url:
            print("Detected Pinterest URL")
            # Use the already resolved absolute output directory
            output_dir = out_dir
            if args.verbose:
                print(f"Output directory (absolute): {output_dir}")

            start_ts = time.perf_counter()
            extractor = PinterestExtractor()
            # Get pin info for templating and extract only images (videos auto-skipped)
            pin_info = extractor.get_pin_info(args.url)
            images = extractor.extract_images(args.url)

            if not images:
                print("❌ No downloadable images found on this Pin (it may be video-only or unavailable).")
                sys.exit(1)

            saved: List[Path] = []
            if args.skip_download:
                print("--skip-download specified; listing images only:")
                total = len(images)
                for idx, item in enumerate(images, start=1):
                    img_url = item['url']
                    # Build mapping for template
                    m = re.search(r"\.([a-zA-Z0-9]{3,4})(?:[?#].*)?$", img_url)
                    ext = (m.group(1).lower() if m else (item.get('format') or 'jpg'))
                    mapping = {
                        "uploader": "unknown",
                        "title": pin_info.get('title') or f"Pinterest Pin {pin_info.get('id','pin')}",
                        "upload_date": "NA",
                        "id": pin_info.get('id') or "",
                        "ext": ext,
                    }
                    dest = _render_output_path(out_template, mapping, index=idx if total > 1 else None, total=total if total > 1 else None, image_url=img_url)
                    try:
                        print(f"  🖼  {img_url} -> {dest.resolve()}")
                    except Exception:
                        print(f"  🖼  {img_url} -> {dest}")
            else:
                total = len(images)
                for idx, item in enumerate(images, start=1):
                    img_url = item['url']
                    m = re.search(r"\.([a-zA-Z0-9]{3,4})(?:[?#].*)?$", img_url)
                    ext = (m.group(1).lower() if m else (item.get('format') or 'jpg'))
                    mapping = {
                        "uploader": "unknown",
                        "title": pin_info.get('title') or f"Pinterest Pin {pin_info.get('id','pin')}",
                        "upload_date": "NA",
                        "id": pin_info.get('id') or "",
                        "ext": ext,
                    }
                    dest = _render_output_path(out_template, mapping, index=idx if total > 1 else None, total=total if total > 1 else None, image_url=img_url)
                    ok = extractor.download_image(img_url, str(dest))
                    if ok:
                        saved.append(Path(dest))
                    else:
                        print(f"⚠️  Failed to download {img_url}")

            elapsed = time.perf_counter() - start_ts
            if saved:
                print(f"\n✅ Successfully downloaded {len(saved)} image(s):")
                for p in saved:
                    try:
                        print(f"  📁 {p.resolve()}")
                    except Exception:
                        print(f"  📁 {p}")
                print(f"\n⏱ Total time: {elapsed:.2f}s")
            else:
                print("❌ No images were downloaded")
                print(f"\n⏱ Total time: {elapsed:.2f}s")
                sys.exit(1)
        elif "reddit.com" in args.url:
            print("Detected Reddit URL")
            # Use the already resolved absolute output directory
            output_dir = out_dir
            if args.verbose:
                print(f"Output directory (absolute): {output_dir}")

            start_ts = time.perf_counter()
            extractor = RedditExtractor()
            # Extract images from Reddit post or subreddit (no generic extract())
            json_url = extractor.convert_to_json_url(args.url)
            reddit_json = extractor._fetch_json(json_url)
            images = extractor.extract_images_from_post_data(reddit_json)

            if not images:
                print("❌ No downloadable images found on this Reddit post/subreddit.")
                sys.exit(1)

            saved: List[Path] = []
            if args.skip_download:
                print("--skip-download specified; listing images only:")
                total = len(images)
                for idx, item in enumerate(images, start=1):
                    img_url = item['url']
                    # Build mapping from item fields
                    m = re.search(r"\.([a-zA-Z0-9]{3,4})(?:[?#].*)?$", img_url)
                    ext = (m.group(1).lower() if m else 'jpg')
                    mapping = {
                        "uploader": item.get('author') or 'unknown',
                        "title": item.get('title') or 'reddit_image',
                        "upload_date": 'NA',
                        "id": item.get('post_id') or '',
                        "ext": ext,
                    }
                    dest = _render_output_path(out_template, mapping, index=idx if total > 1 else None, total=total if total > 1 else None, image_url=img_url)
                    try:
                        print(f"  🖼  {img_url} -> {dest.resolve()}")
                    except Exception:
                        print(f"  🖼  {img_url} -> {dest}")
            else:
                total = len(images)
                for idx, item in enumerate(images, start=1):
                    img_url = item['url']
                    m = re.search(r"\.([a-zA-Z0-9]{3,4})(?:[?#].*)?$", img_url)
                    ext = (m.group(1).lower() if m else 'jpg')
                    mapping = {
                        "uploader": item.get('author') or 'unknown',
                        "title": item.get('title') or 'reddit_image',
                        "upload_date": 'NA',
                        "id": item.get('post_id') or '',
                        "ext": ext,
                    }
                    dest = _render_output_path(out_template, mapping, index=idx if total > 1 else None, total=total if total > 1 else None, image_url=img_url)
                    ok = extractor.download_image(img_url, str(dest))
                    if ok:
                        saved.append(Path(dest))
                    else:
                        print(f"⚠️  Failed to download {img_url}")

            elapsed = time.perf_counter() - start_ts
            if saved:
                print(f"\n✅ Successfully downloaded {len(saved)} image(s):")
                for p in saved:
                    try:
                        print(f"  📁 {p.resolve()}")
                    except Exception:
                        print(f"  📁 {p}")
                print(f"\n⏱ Total time: {elapsed:.2f}s")
            else:
                print("❌ No images were downloaded")
                print(f"\n⏱ Total time: {elapsed:.2f}s")
                sys.exit(1)
        elif "twitter.com" in args.url or "x.com" in args.url:
            print("Detected Twitter/X.com URL")
            # Use the already resolved absolute output directory
            output_dir = out_dir
            if args.verbose:
                print(f"Output directory (absolute): {output_dir}")

            start_ts = time.perf_counter()
            extractor = TwitterExtractor()
            # Respect quality preference
            try:
                setattr(extractor, 'preferred_quality', getattr(args, 'quality', 'best'))
            except Exception:
                pass
            # Extract images from Twitter post (with interactive mixed media handling)
            images = extractor.extract_images(args.url)

            if not images:
                print("❌ No downloadable images found on this tweet.")
                sys.exit(1)

            saved: List[Path] = []
            if args.skip_download:
                print("--skip-download specified; listing images only:")
                total = len(images)
                # Gather minimal meta for templating
                try:
                    tweet_id = extractor.extract_tweet_id(args.url) or ""
                    username = extractor.extract_username(args.url) or "unknown"
                except Exception:
                    tweet_id, username = "", "unknown"
                for idx, item in enumerate(images, start=1):
                    img_url = item['url']
                    # Determine ext via query param or path
                    m_q = re.search(r"[?&]format=([a-zA-Z0-9]{3,4})", img_url)
                    m_p = re.search(r"\.([a-zA-Z0-9]{3,4})(?:[?#].*)?$", img_url)
                    ext = (m_q.group(1).lower() if m_q else (m_p.group(1).lower() if m_p else 'jpg'))
                    mapping = {
                        "uploader": username,
                        "title": "twitter_image",
                        "upload_date": 'NA',
                        "id": tweet_id,
                        "ext": ext,
                    }
                    dest = _render_output_path(out_template, mapping, index=idx if total > 1 else None, total=total if total > 1 else None, image_url=img_url)
                    try:
                        print(f"  🖼  {img_url} -> {dest.resolve()}")
                    except Exception:
                        print(f"  🖼  {img_url} -> {dest}")
            else:
                total = len(images)
                try:
                    tweet_id = extractor.extract_tweet_id(args.url) or ""
                    username = extractor.extract_username(args.url) or "unknown"
                except Exception:
                    tweet_id, username = "", "unknown"
                for idx, item in enumerate(images, start=1):
                    img_url = item['url']
                    m_q = re.search(r"[?&]format=([a-zA-Z0-9]{3,4})", img_url)
                    m_p = re.search(r"\.([a-zA-Z0-9]{3,4})(?:[?#].*)?$", img_url)
                    ext = (m_q.group(1).lower() if m_q else (m_p.group(1).lower() if m_p else 'jpg'))
                    mapping = {
                        "uploader": username,
                        "title": "twitter_image",
                        "upload_date": 'NA',
                        "id": tweet_id,
                        "ext": ext,
                    }
                    dest = _render_output_path(out_template, mapping, index=idx if total > 1 else None, total=total if total > 1 else None, image_url=img_url)
                    ok = extractor.download_image(img_url, str(dest))
                    if ok:
                        saved.append(Path(dest))
                    else:
                        print(f"⚠️  Failed to download {img_url}")

            elapsed = time.perf_counter() - start_ts
            if saved:
                print(f"\n✅ Successfully downloaded {len(saved)} image(s):")
                for p in saved:
                    try:
                        print(f"  📁 {p.resolve()}")
                    except Exception:
                        print(f"  📁 {p}")
                print(f"\n⏱ Total time: {elapsed:.2f}s")
            else:
                print("❌ No images were downloaded")
                print(f"\n⏱ Total time: {elapsed:.2f}s")
                sys.exit(1)
        else:
            print("❌ Unsupported platform. Currently Instagram, Pinterest, Reddit, and Twitter/X.com are supported.")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
