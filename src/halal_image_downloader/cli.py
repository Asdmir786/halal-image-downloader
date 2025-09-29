#!/usr/bin/env python3
"""
Command-line interface for halal-image-downloader
"""

import argparse
import sys
from pathlib import Path
import time
import json
from typing import List, Optional, cast, Dict, Any
from .extractors.instagram import InstagramExtractor
from .extractors.pinterest import PinterestExtractor
from .extractors.reddit import RedditExtractor
from .extractors.twitter import TwitterExtractor
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
        '--debug-browser',
        action='store_true',
        help='Run the embedded browser in non-headless (visible) mode for debugging'
    )
    general.add_argument(
        '--debug-wait',
        type=float,
        default=0.0,
        metavar='SECONDS',
        help='When --debug-browser is used, keep the browser open for SECONDS before closing (default: 0)'
    )
    general.add_argument(
        '--browser',
        choices=['chromium', 'firefox', 'webkit'],
        default='firefox',
        help='Select browser engine for Playwright automation (default: firefox)'
    )
    general.add_argument(
        '--install-browsers',
        action='store_true',
        help='Install Playwright browser binaries (for the selected --browser) and exit if no URL is provided'
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
    default_filename = "%(title)s.%(ext)s"
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
            headless=not args.debug_browser,
            debug_wait_seconds=args.debug_wait,
            browser=args.browser
        )
    elif platform == "pinterest":
        return PinterestExtractor()
    elif platform == "reddit":
        return RedditExtractor()
    elif platform == "twitter":
        return TwitterExtractor()
    else:
        raise ValueError(f"Unsupported platform: {platform}")


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
            # Fallback: use regular extract() and format as JSON
            if args.verbose:
                print("Extractor doesn't support JSON metadata, using fallback method", file=sys.stderr)
            
            images = extractor.extract(url)
            json_data = {
                "platform": platform,
                "url": url,
                "extraction_method": "fallback",
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

    # Allow installing Playwright browsers as a convenience
    if getattr(args, 'install_browsers', False):
        browser_to_install = getattr(args, 'browser', 'chromium') or 'chromium'
        try:
            print(f"Installing Playwright browser: {browser_to_install} ...")
            result = subprocess.run([sys.executable, '-m', 'playwright', 'install', browser_to_install])
            if result.returncode == 0:
                print("Playwright browser install complete.")
            else:
                print(f"Playwright install exited with code {result.returncode}. You can try running: playwright install {browser_to_install}")
        except Exception as e:
            print(f"Failed to install Playwright browser: {e}")
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
            print("Detected Instagram URL")
            headless = not args.debug_browser
            # Use the already resolved absolute output directory
            output_dir = out_dir
            if args.verbose:
                print(f"Browser mode: {'headless' if headless else 'visible (debug)'}")
                print(f"Browser engine: {args.browser}")
                print(f"Output directory (absolute): {output_dir}")
            # Timer start
            start_ts = time.perf_counter()
            downloaded_files: List[Path] = []
            # Use browser-based extraction only
            browser_extractor = InstagramExtractor(output_dir=str(output_dir), headless=headless, debug_wait_seconds=args.debug_wait, browser=args.browser)
            downloaded_files = browser_extractor.extract(args.url)
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
            # Extract only images (videos auto-skipped inside the extractor)
            images = extractor.extract_images(args.url)

            if not images:
                print("❌ No downloadable images found on this Pin (it may be video-only or unavailable).")
                sys.exit(1)

            saved: List[Path] = []
            if args.skip_download:
                print("--skip-download specified; listing images only:")
                for item in images:
                    print(f"  🖼  {item['url']} -> {item['filename']}")
            else:
                for item in images:
                    dest = output_dir / item['filename']
                    ok = extractor.download_image(item['url'], str(dest))
                    if ok:
                        saved.append(dest)
                    else:
                        print(f"⚠️  Failed to download {item['url']}")

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
            # Extract images from Reddit post or subreddit
            images = extractor.extract(args.url)

            if not images:
                print("❌ No downloadable images found on this Reddit post/subreddit.")
                sys.exit(1)

            saved: List[Path] = []
            if args.skip_download:
                print("--skip-download specified; listing images only:")
                for item in images:
                    print(f"  🖼  {item['url']} -> {item['filename']}")
            else:
                for item in images:
                    dest = output_dir / item['filename']
                    ok = extractor.download_image(item['url'], str(dest))
                    if ok:
                        saved.append(dest)
                    else:
                        print(f"⚠️  Failed to download {item['url']}")

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
            # Extract images from Twitter post (with interactive mixed media handling)
            images = extractor.extract(args.url)

            if not images:
                print("❌ No downloadable images found on this tweet.")
                sys.exit(1)

            saved: List[Path] = []
            if args.skip_download:
                print("--skip-download specified; listing images only:")
                for item in images:
                    print(f"  🖼  {item['url']} -> {item['filename']}")
            else:
                for item in images:
                    dest = output_dir / item['filename']
                    ok = extractor.download_image(item['url'], str(dest))
                    if ok:
                        saved.append(dest)
                    else:
                        print(f"⚠️  Failed to download {item['url']}")

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
