# Release Template for halal-image-downloader

## Release Format Guidelines

Use this template when creating new releases for the project. This ensures consistency and provides all necessary information to users.

---

## Template Structure

```markdown
# 🎉 v{VERSION} - {RELEASE_NAME}

> **{ONE_LINE_SUMMARY}**

## 🚀 What's New

### {CATEGORY_1}
- **{FEATURE_1}** - {Description}
- **{FEATURE_2}** - {Description}
- **{FEATURE_3}** - {Description}

### {CATEGORY_2}
- **{FEATURE_1}** - {Description}
- **{FEATURE_2}** - {Description}

### 🎯 Quick Install
```bash
# Using pip
pip install halal-image-downloader

# Using uv (faster)
uv pip install halal-image-downloader

# Using pipx (isolated environment)
pipx install halal-image-downloader
```

### ✨ Usage Examples
```bash
# {Example description}
hi-dlp "{example_url}"

# {Example description}
hi-dlp "{example_url}" {flags}
```

## 🔧 Supported Platforms
- 📸 **Instagram** - Posts & carousels (images only)
- 📌 **Pinterest** - Pins & boards
- 🤖 **Reddit** - Post images & galleries
- 🐦 **Twitter/X** - Tweet images with quality selection

## 📊 Features
- ⚡ Fast concurrent downloads
- 🎨 Custom output templates
- 🔍 Simulation mode (`--simulate`)
- 🌐 Smart browser selection (Chrome → Edge → Chromium)
- 🔒 Age-restricted content handling
- 📱 Multi-image carousel support

## 🐛 Bug Fixes (if any)
- Fixed {bug description} (#issue_number)
- Resolved {bug description} (#issue_number)

## 📚 Documentation
- [Installation Guide](https://github.com/Asdmir786/halal-image-downloader#installation)
- [Usage Examples](https://github.com/Asdmir786/halal-image-downloader#usage-examples)
- [Command Options](https://github.com/Asdmir786/halal-image-downloader#command-line-options)

## 🔗 Links
- **PyPI**: https://pypi.org/project/halal-image-downloader/
- **Repository**: https://github.com/Asdmir786/halal-image-downloader
- **Issues**: https://github.com/Asdmir786/halal-image-downloader/issues

## 💡 Requirements
- Python 3.11+ (tested up to 3.14)
- Playwright browsers (auto-installed on first Instagram use)

## ⚠️ Breaking Changes (if any)
- {Description of breaking change}
- {Migration instructions}

---

**Full Changelog**: https://github.com/Asdmir786/halal-image-downloader/commits/v{VERSION}
```

---

## Category Examples

Use these categories based on what's in the release:

### Common Categories:
- 📦 **PyPI Distribution** - For packaging/distribution changes
- ✨ **New Features** - For new functionality
- 🐛 **Bug Fixes** - For bug fixes
- 🔧 **Improvements** - For enhancements to existing features
- 📝 **Documentation** - For documentation updates
- 🚀 **Performance** - For performance improvements
- 🔒 **Security** - For security fixes
- 🎨 **UI/UX** - For interface improvements
- 🧪 **Testing** - For test additions/improvements
- 🔨 **Refactoring** - For code refactoring
- 📱 **Platform Support** - For new platform additions
- ⚙️ **Configuration** - For config/setup changes

---

## Version Naming Convention

- **Format**: `YYYY.MM.DD` or `YYYY.MM.DD.N` (where N is the build number if multiple releases in one day)
- **Examples**: `2025.10.13`, `2025.10.13.1`, `2025.10.13.2`

---

## Release Name Ideas

- **Major releases**: "PyPI Release", "Major Update", "Complete Rewrite"
- **Feature releases**: "New Platform Support", "Enhanced Features"
- **Bug fix releases**: "Bug Fix Release", "Stability Update"
- **Minor releases**: "Improvements & Fixes", "Polish Update"

---

## Emoji Guide

Use these emojis for visual consistency:

- 🎉 - Major release/celebration
- 🚀 - New features/improvements
- 📦 - Package/distribution
- 🐛 - Bug fixes
- 🔧 - Tools/configuration
- 📸 - Instagram related
- 📌 - Pinterest related
- 🤖 - Reddit related
- 🐦 - Twitter related
- ⚡ - Performance
- 🎨 - Design/UI
- 🔒 - Security
- 📚 - Documentation
- 💡 - Tips/requirements
- ⚠️ - Warnings/breaking changes
- ✨ - New/shiny features
- 🔍 - Search/discovery
- 🌐 - Browser/web related
- 📱 - Mobile/platform

---

## Checklist Before Release

- [ ] Update version in `pyproject.toml`
- [ ] Update version badge in `README.md`
- [ ] Update any version references in documentation
- [ ] Test installation from built package
- [ ] Commit all changes
- [ ] Create and push git tag: `git tag v{VERSION} && git push origin v{VERSION}`
- [ ] Create GitHub release with this template
- [ ] Verify GitHub Action runs successfully
- [ ] Verify package appears on PyPI
- [ ] Test installation from PyPI: `pip install halal-image-downloader=={VERSION}`
- [ ] Announce release (if applicable)

---

## Example Release (v2025.10.13)

See `RELEASE_NOTES.md` for the actual v2025.10.13 release notes as a reference example.
