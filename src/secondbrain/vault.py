"""The vault: the folder of notes *is* the index. Every query scans and parses the files."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

from .config import Config
from .note import ID_PREFIX_RE, Note, new_id, now_created, slugify


class Vault:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._notes: list[Note] | None = None
        self._lookup: dict[str, Note] = {}

    # -- scanning -----------------------------------------------------------

    def notes(self) -> list[Note]:
        if self._notes is None:
            self._scan()
        return self._notes  # type: ignore[return-value]

    def refresh(self) -> None:
        self._notes = None

    def _scan(self) -> None:
        notes = []
        for path in sorted(self.cfg.notes_dir.glob("*.md")):
            try:
                notes.append(Note.load(path))
            except (OSError, UnicodeDecodeError) as exc:
                print(f"sb: skipping unreadable note {path.name}: {exc}", file=sys.stderr)
        notes.sort(key=lambda n: (n.id or "", n.path.name))
        self._notes = notes

        # Link targets resolve in priority order: id, title, file stem, slug.
        # Insert lowest priority first so higher priority keys overwrite.
        lookup: dict[str, Note] = {}
        for key_of in (
            lambda n: "slug:" + n.slug,
            lambda n: "stem:" + n.path.stem,
            lambda n: "title:" + n.title.casefold(),
            lambda n: "id:" + (n.id or ""),
        ):
            for note in reversed(notes):
                lookup[key_of(note)] = note
        self._lookup = lookup

    def ids(self) -> set[str]:
        return {n.id for n in self.notes() if n.id}

    # -- lookup -------------------------------------------------------------

    def resolve_link(self, target: str) -> Note | None:
        """What a [[target]] points at, or None if it is a broken link."""
        self.notes()
        target = target.strip()
        if target.endswith(".md"):
            target = target[:-3]
        keys = ["id:" + target, "title:" + target.casefold(), "stem:" + target, "slug:" + slugify(target)]
        prefix = ID_PREFIX_RE.match(target)
        if prefix:
            # `20261124123000-old-title` still finds the note after a rename.
            keys.append("id:" + prefix.group(1))
        for key in keys:
            if key in self._lookup:
                return self._lookup[key]
        return None

    def find(self, query: str) -> list[Note]:
        """Notes matching a user query: an exact link match, otherwise substring matches."""
        exact = self.resolve_link(query)
        if exact:
            return [exact]
        q = query.casefold()
        return [n for n in self.notes() if q in n.title.casefold() or q in n.path.name.casefold()]

    def backlinks(self, note: Note) -> list[Note]:
        return [
            other
            for other in self.notes()
            if other is not note and any(self.resolve_link(t) is note for t in other.links)
        ]

    def search(self, query: str | None, tags: Iterable[str] = ()) -> list[tuple[Note, str | None]]:
        """Match title, tags and body. Returns (note, matching body line or None)."""
        wanted = {t.casefold().lstrip("#") for t in tags}
        q = (query or "").casefold()
        results = []
        for note in self.notes():
            note_tags = {t.casefold() for t in note.tags}
            if not wanted <= note_tags:
                continue
            if not q or q in note.title.casefold() or q in note_tags:
                results.append((note, None))
                continue
            for line in note.body.splitlines():
                if q in line.casefold():
                    results.append((note, line.strip()))
                    break
        return results

    def tags(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for note in self.notes():
            for tag in note.tags:
                counts[tag] = counts.get(tag, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    # -- writing ------------------------------------------------------------

    def create(self, title: str, tags: Iterable[str] = (), body: str | None = None) -> Note:
        self.cfg.notes_dir.mkdir(parents=True, exist_ok=True)
        note = Note(
            id=new_id(self.ids()),
            title=title,
            tags=list(tags),
            created=now_created(),
            body=body if body is not None else f"\n# {title}\n\n",
        )
        note.path = self.cfg.notes_dir / note.filename
        note.path.write_text(note.render(), encoding="utf-8")
        self.refresh()
        return note

    def ensure_ids(self) -> list[Note]:
        """Give an ID to any note created outside sb (e.g. a plain `foo.md`)."""
        fixed = []
        taken = self.ids()
        for note in self.notes():
            if note.id:
                continue
            note.id = new_id(taken)
            taken.add(note.id)
            note.created = note.created or now_created()
            old_path: Path = note.path  # type: ignore[assignment]
            note.path = old_path.with_name(note.filename)
            note.path.write_text(note.render(), encoding="utf-8")
            if note.path != old_path:
                old_path.unlink()
            fixed.append(note)
        if fixed:
            self.refresh()
        return fixed
