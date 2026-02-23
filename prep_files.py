#!/usr/bin/env python3
"""
prep_files.py

Combined utility:
- Rename music library folders/files to a normalized format (rename_media.py behavior)
- Set media metadata tags based on directory + filename structure (metadata_setter.py behavior)

Modes:
- (no args): show help (with examples)
- --apply: run rename then metadata back-to-back with NO confirmations (automation-friendly)
- --filenames: rename only (interactive preview/confirm unless --yes)
- --metadata: metadata only (interactive preview/confirm unless --yes)
"""

from __future__ import annotations

import argparse
import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


# ----------------------------
# Rename logic (from rename_media.py)
# ----------------------------

ALBUM_DIR_PATTERN = re.compile(r"^(?P<year>\d{4})\s*-\s*(?P<album>.+)$")
TRACK_FILE_PATTERN = re.compile(r"^(?P<num>\d{1,3})\s*-\s*(?P<title>.+)$")


@dataclass(frozen=True)
class RenameAction:
    kind: str  # "dir" or "file"
    source: Path
    target: Path

    @property
    def relative_source(self) -> str:
        return str(self.source)

    @property
    def relative_target(self) -> str:
        return str(self.target)


def normalized_album_name(name: str, album_format: str) -> Optional[str]:
    """
    Expected input folder format:
      YYYY - Album Name
    Example:
      2001 - Discovery
    """
    match = ALBUM_DIR_PATTERN.match(name)
    if not match:
        return None

    album = match.group("album").strip()
    year = match.group("year")
    normalized = album_format.format(album=album, year=year)
    return normalized if normalized != name else None


def normalized_track_name(stem: str, track_format: str) -> Optional[str]:
    """
    Expected input filename stem format:
      N - Track Title
    Example:
      1 - One More Time
    """
    match = TRACK_FILE_PATTERN.match(stem)
    if not match:
        return None

    track_no_raw = match.group("num")
    track_no = int(track_no_raw)
    title = match.group("title").strip()
    normalized = track_format.format(track=track_no, title=title)
    return normalized if normalized != stem else None


def gather_rename_actions(root: Path, album_format: str, track_format: str) -> List[RenameAction]:
    actions: List[RenameAction] = []

    # Files first
    for path in root.rglob("*"):
        if not path.is_file():
            continue

        normalized_stem = normalized_track_name(path.stem, track_format)
        if normalized_stem is None:
            continue

        target = path.with_name(f"{normalized_stem}{path.suffix}")
        if target != path:
            actions.append(
                RenameAction(
                    kind="file",
                    source=path.relative_to(root),
                    target=target.relative_to(root),
                )
            )

    # Dirs second
    for path in root.rglob("*"):
        if not path.is_dir():
            continue

        normalized_dir = normalized_album_name(path.name, album_format)
        if normalized_dir is None:
            continue

        target = path.with_name(normalized_dir)
        if target != path:
            actions.append(
                RenameAction(
                    kind="dir",
                    source=path.relative_to(root),
                    target=target.relative_to(root),
                )
            )

    return actions


def print_rename_preview(actions: Iterable[RenameAction]) -> None:
    actions = list(actions)
    if not actions:
        print("No matching folders/files found. Nothing to rename.")
        return

    dir_actions = [a for a in actions if a.kind == "dir"]
    file_actions = [a for a in actions if a.kind == "file"]

    print("Preview of planned renames")
    print("=" * 26)

    if dir_actions:
        print("\nFolders:")
        for action in sorted(dir_actions, key=lambda a: a.relative_source):
            print(f"  {action.relative_source} -> {action.relative_target}")

    if file_actions:
        print("\nFiles:")
        for action in sorted(file_actions, key=lambda a: a.relative_source):
            print(f"  {action.relative_source} -> {action.relative_target}")

    print(f"\nTotal: {len(actions)} rename(s)")


def apply_rename_actions(root: Path, actions: Iterable[RenameAction]) -> int:
    """
    Applies renames.
    - Files are renamed first.
    - Directories are renamed after, deepest-first to avoid path conflicts.
    """
    actions = list(actions)
    applied = 0

    files = sorted((a for a in actions if a.kind == "file"), key=lambda a: a.relative_source)
    dirs = sorted(
        (a for a in actions if a.kind == "dir"),
        key=lambda a: len(Path(a.relative_source).parts),
        reverse=True,
    )

    for action in [*files, *dirs]:
        src = root / action.source
        dst = root / action.target

        if not src.exists():
            print(f"[SKIP] source missing: {action.relative_source}")
            continue

        if dst.exists():
            print(f"[SKIP] target already exists: {action.relative_target}")
            continue

        src.rename(dst)
        applied += 1
        print(f"[OK] {action.relative_source} -> {action.relative_target}")

    return applied


def run_filenames(root: Path, album_format: str, track_format: str, yes: bool) -> int:
    actions = gather_rename_actions(root, album_format, track_format)
    print_rename_preview(actions)

    if not actions:
        return 0

    if not yes:
        answer = input("\nApply these changes? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Aborted. No changes applied.")
            return 0

    print("\nApplying changes...")
    applied = apply_rename_actions(root, actions)
    print(f"\nDone. Applied {applied} rename(s).")
    return 0


# ----------------------------
# Metadata logic (from metadata_setter.py)
# ----------------------------

AUDIO_EXTENSIONS = {
    ".aac",
    ".aiff",
    ".alac",
    ".ape",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".ogg",
    ".oga",
    ".opus",
    ".wav",
    ".wma",
}

ALBUM_PATTERN = re.compile(r"^(?P<album>.+?)\s*\((?P<year>\d{4})\)$")
TRACK_PATTERN = re.compile(r"^(?P<track>\d{2})\b")


@dataclass(frozen=True)
class MetadataAction:
    file_path: Path
    updates: Dict[str, str]
    current: Dict[str, str]


def is_audio_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS


def derive_metadata_for_file(path: Path) -> Optional[Dict[str, str]]:
    """
    Expected directory format:
      Artist/Album (YYYY)/NN Track Title.ext

    Example:
      Daft Punk/Discovery (2001)/01 One More Time.flac
    """
    album_dir = path.parent
    author_dir = album_dir.parent

    album_match = ALBUM_PATTERN.match(album_dir.name)
    if not album_match:
        return None

    track_match = TRACK_PATTERN.match(path.stem)
    if not track_match:
        return None

    album = album_match.group("album").strip()
    year = album_match.group("year")
    track = track_match.group("track")
    author = author_dir.name.strip()

    if not album or not author:
        return None

    return {
        "album": album,
        "date": year,
        "year": year,
        "tracknumber": track,
        "artist": author,
        "albumartist": author,
        "author": author,
    }


def mutagen_file(path: Path):
    from mutagen import File as _MutagenFile  # type: ignore

    return _MutagenFile(path, easy=True)


def read_current_tags(path: Path, desired_keys: Iterable[str]) -> Dict[str, str]:
    audio = mutagen_file(path)
    if audio is None:
        return {}

    current: Dict[str, str] = {}
    for key in desired_keys:
        value = audio.get(key)
        if isinstance(value, list):
            current[key] = value[0] if value else ""
        elif isinstance(value, str):
            current[key] = value
    return current


def gather_metadata_actions(root: Path) -> List[MetadataAction]:
    actions: List[MetadataAction] = []

    for path in root.rglob("*"):
        if not is_audio_file(path):
            continue

        updates = derive_metadata_for_file(path)
        if updates is None:
            continue

        current = read_current_tags(path, updates.keys())
        effective_updates = {k: v for k, v in updates.items() if current.get(k, "") != v}
        if not effective_updates:
            continue

        actions.append(
            MetadataAction(
                file_path=path.relative_to(root),
                updates=effective_updates,
                current=current,
            )
        )

    return actions


def print_metadata_preview(actions: Iterable[MetadataAction]) -> None:
    actions = list(actions)
    if not actions:
        print("No metadata updates required.")
        return

    print("Metadata update preview")
    print("=" * 23)
    for idx, action in enumerate(sorted(actions, key=lambda a: str(a.file_path)), start=1):
        print(f"\n[{idx}] {action.file_path}")
        print("    tag          current                      -> new")
        print("    -------------------------------------------------------------")
        for key in sorted(action.updates):
            current = action.current.get(key, "")
            new_val = action.updates[key]
            print(f"    {key:<12} {current[:28]:<28} -> {new_val}")

    print(f"\nTotal files to update: {len(actions)}")


def apply_metadata_actions(root: Path, actions: Iterable[MetadataAction]) -> int:
    applied = 0

    for action in sorted(actions, key=lambda a: str(a.file_path)):
        file_path = root / action.file_path
        audio = mutagen_file(file_path)
        if audio is None:
            print(f"[SKIP] unsupported format: {action.file_path}")
            continue

        for key, value in action.updates.items():
            audio[key] = [value]

        audio.save()
        applied += 1
        print(f"[OK] updated tags: {action.file_path}")

    return applied


def run_metadata(root: Path, yes: bool) -> int:
    if importlib.util.find_spec("mutagen") is None:
        print("Error: missing dependency 'mutagen'. Install it with: pip install mutagen")
        return 1

    try:
        actions = gather_metadata_actions(root)
    except Exception as exc:  # noqa: BLE001
        print(f"Error while reading media files: {exc}")
        return 1

    print_metadata_preview(actions)
    if not actions:
        return 0

    if not yes:
        answer = input("\nApply these metadata changes? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Aborted. No changes applied.")
            return 0

    print("\nApplying metadata updates...")
    try:
        applied = apply_metadata_actions(root, actions)
    except Exception as exc:  # noqa: BLE001
        print(f"Error while writing media files: {exc}")
        return 1

    print(f"\nDone. Updated {applied} file(s).")
    return 0


# ----------------------------
# CLI / Dispatch
# ----------------------------

def build_parser() -> argparse.ArgumentParser:
    examples = r"""
Examples:
  prep_files.py
      Show help.

  prep_files.py --filenames --root "D:\media\import"
      Preview/confirm renames only.

  prep_files.py --metadata --root "D:\media\import"
      Preview/confirm metadata tagging only.

  prep_files.py --apply --root "D:\media\import"
      Run renames THEN metadata tagging, no prompts (automation).

  prep_files.py --filenames --root "D:\media\import" --yes
      Rename-only, non-interactive.

  prep_files.py --metadata --root "D:\media\import" --yes
      Metadata-only, non-interactive.
"""

    parser = argparse.ArgumentParser(
        description="Prepare music files: normalize filenames/folders and set metadata tags.",
        epilog=examples,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=True,
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Run filenames then metadata with no confirmations.")
    mode.add_argument("--filenames", action="store_true", help="Run filename/folder normalization only.")
    mode.add_argument("--metadata", action="store_true", help="Run metadata tagging only.")

    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Root directory to scan (default: current working directory).",
    )

    # Rename options
    parser.add_argument(
        "--album-format",
        default="{album} ({year})",
        help='Album folder output format. Fields: {album}, {year}. Default: "{album} ({year})".',
    )
    parser.add_argument(
        "--track-format",
        default="{track:02d} {title}",
        help='Track filename output format (no extension). Fields: {track}, {title}. Default: "{track:02d} {title}".',
    )

    # Shared "yes"
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Apply changes without interactive confirmation (for --filenames / --metadata modes).",
    )

    return parser


def main() -> int:
    parser = build_parser()

    # If no args were provided, show help + exit 0
    import sys
    if len(sys.argv) == 1:
        parser.print_help()
        return 0

    args = parser.parse_args()
    root = args.root.resolve()

    if not root.exists() or not root.is_dir():
        print(f"Error: root is not a directory: {root}")
        return 1

    # --apply: always non-interactive, regardless of --yes
    if args.apply:
        rc = run_filenames(root, args.album_format, args.track_format, yes=True)
        if rc != 0:
            return rc
        return run_metadata(root, yes=True)

    # rename-only
    if args.filenames:
        return run_filenames(root, args.album_format, args.track_format, yes=args.yes)

    # metadata-only
    if args.metadata:
        return run_metadata(root, yes=args.yes)

    # If somehow no mode selected (shouldn't happen due to early help), show help
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
