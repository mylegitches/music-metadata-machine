# Music Metadata Machine

A utility script to prepare music libraries by:

- Normalizing album folder names and track filenames.
- Setting audio metadata tags from directory + filename structure.

## Script

- `prep_files.py`

## Requirements

- Python 3.9+
- [`mutagen`](https://mutagen.readthedocs.io/) (required for metadata mode)

Install dependency:

```bash
pip install mutagen
```

## Usage

Show help:

```bash
./prep_files.py
```

Rename folders/files only (interactive):

```bash
./prep_files.py --filenames --root "/path/to/music"
```

Apply rename only (non-interactive):

```bash
./prep_files.py --filenames --root "/path/to/music" --yes
```

Set metadata only (interactive):

```bash
./prep_files.py --metadata --root "/path/to/music"
```

Run full pipeline (rename then metadata) with no prompts:

```bash
./prep_files.py --apply --root "/path/to/music"
```

## Expected naming formats

Input folder format for album rename:

- `YYYY - Album Name`

Output album format (default):

- `{album} ({year})` → e.g. `Discovery (2001)`

Input filename stem for track rename:

- `N - Track Title`

Output track format (default):

- `{track:02d} {title}` → e.g. `01 One More Time`

Metadata derivation expects final path structure:

- `Artist/Album (YYYY)/NN Track Title.ext`

## Git quick start

If you need to initialize and push this project from scratch:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```
