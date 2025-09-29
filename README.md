# halal-image-downloader

A command-line tool for fast and reliable image downloading from supported social media sources.

[![Version](https://img.shields.io/badge/version-2025.09.29.2-blue.svg)](https://github.com/Asdmir786/halal-image-downloader)
[![Python](https://img.shields.io/badge/python-3.11+-green.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-red.svg)](LICENSE)

## Description

`halal-image-downloader` is a powerful command-line utility designed for downloading images and carousels from various social media platforms. Built with the same philosophy as `yt-dlp` but specifically focused on image content, it provides a familiar interface for users who want to archive visual content from supported sources.

## Features

- 🚀 **Fast downloads** with concurrent processing
- 🎯 **Multiple format support** (JPG, PNG, WebP, original)
- 📱 **Social media platform support** (Instagram, Pinterest, Reddit)
- 🔄 **Carousel/album downloading** with selective item support
- 📊 **Quality selection** (best, worst, original, custom resolution)
- 🛡️ **Authentication support** (cookies, login credentials)
- 📝 **Metadata extraction** and embedding
- 🎨 **Post-processing** with image conversion
- ⚙️ **Extensive configuration** options
- 🔍 **Simulation mode** for testing without downloading

## Installation

### Using uv (Recommended)

```bash
# Clone the repository
git clone https://github.com/Asdmir786/halal-image-downloader.git
cd halal-image-downloader

# Create virtual environment and install
uv venv
uv sync
uv pip install -e .
```

### Build and install from source (fast, uv)

Use uv’s builder to quickly produce both the wheel and sdist, then install with uv (or pip):

```powershell
# Activate venv (Windows)
.venv\Scripts\activate

# Ensure uv's build backend is available in your venv (one-time)
uv pip install -U "uv-build>=0.8.17,<0.9.0"

# Build both wheel and sdist quickly (writes to dist/)
uv build

# Install the freshly built wheel (fastest)
uv pip install --force-reinstall --no-deps dist\*.whl

# Or install from sdist (tar.gz)
uv pip install --force-reinstall dist\*.tar.gz
```

Alternative (if you prefer Python’s build module but want speed):

```powershell
# With uv-build installed in your venv
python -m build --wheel --no-isolation
python -m build --sdist --no-isolation

# Then install
uv pip install --force-reinstall --no-deps dist\*.whl
```

Notes:
- Using uv build or --no-isolation avoids slow isolated env creation, making builds much faster.
- Use `--no-deps` on reinstall to skip re-resolving dependencies locally.

### Using pip

```bash
# Clone the repository
git clone https://github.com/Asdmir786/halal-image-downloader.git
cd halal-image-downloader

# Install dependencies
pip install -e .
```

## Quick Start

```bash
# Activate virtual environment (if using uv)
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/macOS

# Basic usage (short command)
hi-dlp "https://instagram.com/p/ABC123"

# Or use the full command
halal-image-downloader "https://instagram.com/p/ABC123"

# Download to specific directory
hi-dlp "https://instagram.com/p/ABC123" -o ~/Downloads

# Download Reddit images
hi-dlp "https://reddit.com/r/ABC/comments/abc123/beautiful_sunset"

# Download Pinterest pins
hi-dlp "https://pinterest.com/pin/123456789"

# Download with specific format and quality
hi-dlp "https://instagram.com/p/ABC123" --format jpg --quality best

# Simulate download (don't actually download)
hi-dlp "https://instagram.com/p/ABC123" --simulate
```

## Usage Examples

### Basic Downloads

```bash
# Download all images from a post
hi-dlp "https://instagram.com/p/ABC123"

# Download Reddit post images
hi-dlp "https://reddit.com/r/Art/comments/xyz123/my_latest_artwork"

# Download Pinterest pin
hi-dlp "https://pinterest.com/pin/987654321"

# Download with custom output directory
hi-dlp "https://reddit.com/r/Art" -o ./downloads

# Download specific items from carousel (items 1, 3, and 5-10)
hi-dlp "https://instagram.com/p/ABC123" --playlist-items "1,3,5-10"
```

### Quality and Format Control

```bash
# Download best quality images
hi-dlp "URL" --quality best

# Download in specific format
hi-dlp "URL" --format jpg

# Download with size constraints
hi-dlp "URL" --max-width 1920 --max-height 1080

# Convert images after download
hi-dlp "URL" --convert-images png --image-quality 95
```

### Advanced Options

```bash
# Download with metadata
hi-dlp "URL" --write-info-json --write-description

# Use cookies for authentication
hi-dlp "URL" --cookies cookies.txt

# Rate limiting
hi-dlp "URL" --limit-rate 1M

# Verbose output
hi-dlp "URL" --verbose

# Quiet mode
hi-dlp "URL" --quiet
```

### Date Filtering

```bash
# Download images from specific date (YYYYMMDD)
hi-dlp "URL" --date YYYYMMDD

# Download images after specific date (YYYYMMDD)
hi-dlp "URL" --dateafter YYYYMMDD

# Download images before specific date (YYYYMMDD)
hi-dlp "URL" --datebefore YYYYMMDD
```

## Command Line Options

### General Options
- `--version` - Show version and exit
- `-U, --update` - Update to latest version
- `-V, --verbose` - Enable verbose output
- `-q, --quiet` - Enable quiet mode
- `-s, --simulate` - Simulate download without actually downloading

### Download Options
- `-o, --output TEMPLATE` - Output filename template
- `-f, --format FORMAT` - Image format preference
- `--quality {best,worst,original}` - Quality selection
- `-r, --limit-rate RATE` - Download rate limit
- `-R, --retries RETRIES` - Number of retries (default: 10)

### Selection Options
- `--playlist-items ITEMS` - Specific items to download (e.g., "1,3,5-10")
- `--min-filesize SIZE` - Minimum file size filter
- `--max-filesize SIZE` - Maximum file size filter
- `--date DATE` - Download only from specific date
- `--datebefore DATE` - Download only before date
- `--dateafter DATE` - Download only after date

### Authentication Options
- `-u, --username USERNAME` - Login username
- `-p, --password PASSWORD` - Login password
- `--cookies FILE` - Cookie file path
- `--cookies-from-browser BROWSER` - Extract cookies from browser

### Post-Processing Options
- `--convert-images FORMAT` - Convert to different format
- `--image-quality QUALITY` - Image quality for conversion (0-100)
- `--embed-metadata` - Embed metadata in images
- `--write-info-json` - Write metadata to .info.json
- `--write-description` - Write description to .description file

For complete list of options, run:
```bash
hi-dlp --help
# or
halal-image-downloader --help
```

## Supported Platforms

- 📸 **Instagram** - Posts, carousels, galleries (images only, videos skipped)
- 📌 **Pinterest** - Pins, image boards (images only, videos skipped)
- 🤖 **Reddit** - Post images, galleries, subreddit images (pure image content)
- 🔗 **Generic** - Direct image URLs

### Platform-Specific Features

#### Instagram
- ✅ Single image posts
- ✅ Multi-image carousels
- ✅ High-resolution downloads
- ❌ Videos/Reels (automatically skipped)

#### Pinterest
- ✅ Individual pins
- ✅ Image boards
- ✅ Multiple resolutions
- ❌ Video pins (automatically skipped)

#### Reddit
- ✅ Post images (single and galleries)
- ✅ Subreddit browsing
- ✅ Mixed media handling (user choice)
- ❌ Videos (automatically skipped)
- 🎛️ **Interactive prompts** for mixed media galleries

*More platforms will be added in future releases*

## Configuration

### Output Templates

Use custom output templates with metadata fields:

```bash
# Custom filename template
hi-dlp "URL" -o "%(uploader)s/%(title)s.%(ext)s"

# Date-based organization
hi-dlp "URL" -o "%(upload_date)s/%(id)s.%(ext)s"
```

### Reddit Mixed Media Handling

When downloading from Reddit, the tool automatically detects mixed media galleries:

```bash
# If a Reddit gallery contains both images and videos:
⚠️  Mixed media gallery detected!
📝 Post: Cool Art and Animation Mix
🖼️  Images: 3
🎥 Videos/Animations: 2

This gallery contains both images and videos.
halal-image-downloader only downloads images.

Choose an option:
[C]ontinue (download images only)
[Q]uit program
Your choice (C/Q):
```

### Simple output templates (easy mode)

For quick, memorable templates you can use a simple readable format instead of the full `%(...)s` style. The simple format supports:

- Tokens: `author`, `title`, `date`, `id`, `ext`, `idx`, `cnt`
  - `author` -> `%(uploader)s`
  - `title`  -> `%(title)s`
  - `date`   -> `%(upload_date)s`
  - `id`     -> `%(id)s`
  - `ext`    -> `%(ext)s`
  - `idx`    -> `%(playlist_index)s`
  - `cnt`    -> `%(autonumber)s`

- Path rules:
  - Leading `/` or `\` is treated as your home directory (e.g. `/Downloads` -> `C:\Users\you\Downloads`).
  - `./` is relative to the current working directory.
  - `../` and `../../` move up parent directories like a normal shell path.
  - `~` still expands to your home directory.
  - If you give a directory (ends with `/` or `\` or has no filename), the default filename `%(title)s.%(ext)s` is used.
  - If you provide a filename without an extension, `.%(ext)s` is appended automatically.
Examples:

```bash
# Save to home Downloads with default name
hi-dlp "URL" -o "/Downloads"

# Save under home Downloads with author folder and title
hi-dlp "URL" -o "/Downloads/author/title.ext"

# Save two levels up into a sibling folder (cwd = project dir)
hi-dlp "URL" -o "../../Downloads"

# Use a short letter mnemonic (u=uploader, t=title, e=ext)
hi-dlp "URL" -o "u_t_e"
```

The full `%(...)s` templates are still supported and will be used unchanged when provided.

### Configuration File

Create a configuration file at `~/.config/halal-image-downloader/config` or use `--config-location`:

```ini
# Default output directory
--output ~/Downloads/%(uploader)s/%(title)s.%(ext)s

# Default quality
--quality best

# Always write metadata
--write-info-json
--embed-metadata

# Rate limiting
--limit-rate 2M
```

## Development

### Requirements

- Python 3.11+
- uv (recommended) or pip
- Required packages: requests, httpx, pillow, beautifulsoup4

### Setting up Development Environment

```bash
# Clone repository
git clone https://github.com/Asdmir786/halal-image-downloader.git
cd halal-image-downloader

# Create development environment
uv venv
uv sync --dev

# Install in editable mode
uv pip install -e .

# Run tests
uv run pytest

# Format code
uv run black src/
uv run ruff check src/
```

### Project Structure

```text
halal-image-downloader/
├── src/
│   └── halal_image_downloader/
│       ├── __init__.py
│       ├── cli.py              # Command-line interface
│       └── extractors/         # Platform-specific extractors
│           ├── __init__.py
│           ├── base_extractor.py  # Shared functionality
│           ├── instagram.py       # Instagram extractor
│           ├── pinterest.py       # Pinterest extractor
│           └── reddit.py          # Reddit extractor
├── tests/                      # Test suite
├── pyproject.toml             # Project configuration
├── uv.lock                    # Dependency lock file
└── README.md                  # This file
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Inspired by [yt-dlp](https://github.com/yt-dlp/yt-dlp) for the excellent CLI design
- Built with modern Python packaging using [uv](https://github.com/astral-sh/uv)
- Thanks to all contributors and users

## Disclaimer

This tool is for educational and personal use only. Please respect the terms of service of the platforms you're downloading from and ensure you have the right to download the content. The developers are not responsible for any misuse of this tool.

---

**Made with ❤️ by [Asdmir786](https://github.com/Asdmir786)**
