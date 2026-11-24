"""The note: a markdown file with YAML frontmatter. This is the atom of the system."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import yaml

ID_FORMAT = "%Y%m%d%H%M%S"
CREATED_FORMAT = "%Y-%m-%d %H:%M"

FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
# Fenced blocks and inline code are stripped before looking for links,
# so documentation like `[[example]]` doesn't count as a link.
CODE_RE = re.compile(r"```.*?(?:```|\Z)|~~~.*?(?:~~~|\Z)|`[^`\n]*`", re.S)
# [[target]], [[target|alias]], [[target#heading]]
LINK_RE = re.compile(r"\[\[([^\[\]|#\n]+)(?:[#|][^\[\]\n]*)?\]\]")
HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
ID_PREFIX_RE = re.compile(r"^(\d{14})")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "-", text).strip("-") or "note"


def new_id(taken: Iterable[str] = ()) -> str:
    """Timestamp ID (YYYYMMDDHHMMSS), bumped if it collides with an existing one."""
    taken = set(taken)
    candidate = int(datetime.now().strftime(ID_FORMAT))
    while str(candidate) in taken:
        candidate += 1
    return str(candidate)


def now_created() -> str:
    return datetime.now().strftime(CREATED_FORMAT)


def _yaml_line(key: str, value) -> str:
    opts = dict(allow_unicode=True, sort_keys=False, width=10**6)
    if isinstance(value, list) and all(isinstance(v, (str, int, float, bool)) for v in value):
        # Lists of scalars stay on one line: `tags: [a, b]`
        return f"{key}: " + yaml.safe_dump(value, default_flow_style=True, **opts).strip()
    return yaml.safe_dump({key: value}, default_flow_style=False, **opts).rstrip("\n")


@dataclass
class Note:
    id: str | None
    title: str
    tags: list[str] = field(default_factory=list)
    created: str = ""
    body: str = ""
    extra: dict = field(default_factory=dict)
    path: Path | None = None

    @classmethod
    def parse(cls, text: str, path: Path | None = None) -> "Note":
        meta: dict = {}
        body = text
        match = FRONTMATTER_RE.match(text)
        if match:
            try:
                loaded = yaml.safe_load(match.group(1)) or {}
            except yaml.YAMLError:
                loaded = None
            if isinstance(loaded, dict):
                meta = dict(loaded)
                body = text[match.end():]

        note_id = meta.pop("id", None)
        if note_id is None and path is not None:
            prefix = ID_PREFIX_RE.match(path.name)
            note_id = prefix.group(1) if prefix else None

        title = meta.pop("title", None)
        if not title:
            heading = HEADING_RE.search(body)
            title = heading.group(1) if heading else (path.stem if path else "untitled")

        tags = meta.pop("tags", None) or []
        if isinstance(tags, str):
            tags = [t for t in re.split(r"[,\s]+", tags) if t]
        elif not isinstance(tags, list):
            tags = [tags]

        created = meta.pop("created", "") or ""

        return cls(
            id=str(note_id) if note_id is not None else None,
            title=str(title),
            tags=[str(t).lstrip("#") for t in tags],
            created=str(created),
            body=body,
            extra=meta,
            path=path,
        )

    @classmethod
    def load(cls, path: Path) -> "Note":
        return cls.parse(path.read_text(encoding="utf-8"), path)

    def render(self) -> str:
        lines = [
            "---",
            f"id: {self.id}",
            _yaml_line("title", self.title),
            _yaml_line("tags", self.tags),
        ]
        if self.created:
            lines.append(f"created: {self.created}")
        lines.extend(_yaml_line(k, v) for k, v in self.extra.items())
        lines.append("---")
        return "\n".join(lines) + "\n" + self.body

    @property
    def links(self) -> list[str]:
        """Link targets in the body, in order, without duplicates."""
        text = CODE_RE.sub("", self.body)
        found = dict.fromkeys(m.group(1).strip() for m in LINK_RE.finditer(text))
        return [t for t in found if t]

    @property
    def slug(self) -> str:
        return slugify(self.title)

    @property
    def filename(self) -> str:
        return f"{self.id}-{self.slug}.md"
