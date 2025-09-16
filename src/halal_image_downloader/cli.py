#!/usr/bin/env python3
"""
Command-line interface for halal-image-downloader
"""

import argparse
import sys
from pathlib import Path
import time
from typing import List, Optional
from .extractors.instagram import InstagramExtractor
from .extractors.pinterest import PinterestExtractor
from . import __version__


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser with yt-dlp style arguments."""
    
    parser = argparse.ArgumentParser(
        prog='halal-image-downloader',
        description='A command-line tool for fast and reliable image downloading from supported sources.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  halal-image-downloader "https://instagram.com/p/ABC123"
  halal-image-downloader "https://twitter.com/user/status/123" -o ~/Downloads
  halal-image-downloader "https://example.com/post" --format jpg --quality best
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
    general.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {__version__}',
        help='Show program version and exit'
    )
    general.add_argument(
        '-U', '--update',
        action='store_true',
        help='Update this program to latest version'
    )
    general.add_argument(
        '-v', '--verbose',
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
        help='Output filename template'
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


def main() -> None:
    """Main entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Handle special cases
    if not args.url and not args.update and not args.version:
        parser.print_help()
        sys.exit(1)
    
    # Handle update command
    if args.update:
        print("Update functionality not implemented yet")
        sys.exit(0)
    
    # Handle simulation mode
    if args.simulate:
        print(f"[simulate] Would download from: {args.url}")
        if args.output:
            print(f"[simulate] Output template: {args.output}")
        if args.format:
            print(f"[simulate] Format: {args.format}")
        if args.quality:
            print(f"[simulate] Quality: {args.quality}")
        sys.exit(0)
    
    # Validate required arguments
    if not args.url:
        parser.error("URL is required")
    
    # Print configuration for now
    print(f"halal-image-downloader {__version__}")
    print(f"URL: {args.url}")
    
    if args.verbose:
        print("Verbose mode enabled")
        print(f"Arguments: {vars(args)}")
    
    if args.output:
        print(f"Output: {args.output}")
    
    if args.format:
        print(f"Format: {args.format}")
    
    if args.quality:
        print(f"Quality: {args.quality}")
    
    # Determine platform and extract images
    try:
        if "instagram.com" in args.url:
            print("Detected Instagram URL")
            headless = not args.debug_browser
            output_dir = Path(args.output).expanduser() if args.output else Path('.')
            if args.verbose:
                print(f"Browser mode: {'headless' if headless else 'visible (debug)'}")
                print(f"Browser engine: {args.browser}")
                print(f"Output directory: {output_dir.resolve()}")
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
                    print(f"  📁 {file_path}")
                print(f"\n⏱ Total time: {elapsed:.2f}s")
            else:
                print("❌ No images were downloaded")
                print(f"\n⏱ Total time: {elapsed:.2f}s")
                sys.exit(1)
        elif "pinterest.com" in args.url:
            print("Detected Pinterest URL")
            output_dir = Path(args.output).expanduser() if args.output else Path('.')
            if args.verbose:
                print(f"Output directory: {output_dir.resolve()}")
            output_dir.mkdir(parents=True, exist_ok=True)

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
                    print(f"  📁 {p}")
                print(f"\n⏱ Total time: {elapsed:.2f}s")
            else:
                print("❌ No images were downloaded")
                print(f"\n⏱ Total time: {elapsed:.2f}s")
                sys.exit(1)
        else:
            print("❌ Unsupported platform. Currently only Instagram and Pinterest are supported.")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
