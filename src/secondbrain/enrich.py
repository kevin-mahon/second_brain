"""Turn raw captured text (often dictation) into a connected note, locally.

No network, no models: plain text statistics over your own vault.

- links:    mentions of existing note titles become [[links]] in place
- tags:     tags of the most similar notes (TF-IDF cosine), plus tags named in the text
- related:  the closest notes that weren't already mentioned
- mentions: capitalised multi-word names ("Sarah Chen") that have no note yet
- title:    the first sentence, minus dictation filler
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .note import Note
from .vault import Vault

STOPWORDS = set(
    """a about above after again against all also am an and any are aren as at be because been before
    being below between both but by can cannot could did didn do does doesn doing don down during each
    few for from further get got had hadn has hasn have haven having he her here hers herself him
    himself his how however i if in into is isn it its itself just let like ll me might more most much
    must my myself no nor not now of off on once one only or other ought our ours ourselves out over own
    really same shall she should shouldn so some such than that the their theirs them themselves then
    there these they thing things think this those though through to too under until up us use used
    using very via was wasn way we well were weren what when where which while who whom why will with
    won would wouldn yeah yes yet you your yours yourself yourselves maybe okay ok um uh gonna wanna
    something someone stuff want need make made know going note notes thought thoughts idea ideas
    quick help""".split()
)

FILLER_RE = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|so|um+|uh+|hey|alright|right|well)[\s,.]+|"
    r"(?:note to self|remind me(?: to)?|new note|quick (?:note|thought|idea)|(?:an? )?(?:thought|idea))[\s,:.-]+)+",
    re.I,
)
NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3})\b")
NOT_NAMES = set(
    """monday tuesday wednesday thursday friday saturday sunday january february march april may june
    july august september october november december i the a an this that these those my our today
    tomorrow yesterday""".split()
)


@dataclass
class Enrichment:
    text: str
    tags: list[str] = field(default_factory=list)
    linked: list[Note] = field(default_factory=list)
    related: list[Note] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)


# -- text basics ------------------------------------------------------------------


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z][a-z0-9]+", text.casefold())
    return [_stem(w) for w in words if len(w) > 2 and w not in STOPWORDS]


def strip_filler(text: str) -> str:
    """Drop dictation lead-ins like "Okay so note to self." from the start."""
    stripped = FILLER_RE.sub("", text.strip())
    stripped = stripped[:1].upper() + stripped[1:]
    return stripped or text.strip()


def make_title(text: str, limit: int = 60) -> str:
    text = strip_filler(text)
    first = re.split(r"(?<=[.!?])\s+|\n", text, maxsplit=1)[0].strip().rstrip(".!?,;:")
    if len(first) > limit:
        cut = first[:limit].rsplit(" ", 1)[0]
        first = (cut if len(cut) > limit // 2 else first[:limit]).rstrip(",;:-") + "…"
    return (first[:1].upper() + first[1:]) or "Captured note"


# -- similarity -------------------------------------------------------------------


class Index:
    """TF-IDF vectors for every note. Titles and tags count extra."""

    def __init__(self, notes: list[Note]):
        self.notes = notes
        counts = [
            Counter(tokens(n.title) * 3 + tokens(" ".join(n.tags)) * 2 + tokens(n.body)) for n in notes
        ]
        df = Counter(t for c in counts for t in c)
        self.n = len(notes)
        self.idf = {t: math.log((self.n + 1) / (d + 1)) + 1 for t, d in df.items()}
        self.vectors = [self._vector(c) for c in counts]

    def _vector(self, counts: Counter) -> dict[str, float]:
        default = math.log(self.n + 1) + 1
        vec = {t: (1 + math.log(c)) * self.idf.get(t, default) for t, c in counts.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def similar(self, text: str) -> list[tuple[float, Note]]:
        """Notes by cosine similarity. A single shared word only counts if the match is strong."""
        query = self._vector(Counter(tokens(text)))
        scored = []
        for note, vec in zip(self.notes, self.vectors):
            shared = [t for t in query if t in vec]
            score = sum(query[t] * vec[t] for t in shared)
            if score > 0 and (len(shared) >= 2 or score >= 0.35):
                scored.append((score, note))
        scored.sort(key=lambda sn: -sn[0])
        return scored


# -- the pieces ---------------------------------------------------------------------


def link_mentions(text: str, notes: list[Note]) -> tuple[str, list[Note]]:
    """Wrap the first mention of each existing note title in [[ ]]. Longest titles win."""
    spans: list[tuple[int, int, Note]] = []
    for note in sorted(notes, key=lambda n: -len(n.title)):
        title = note.title.strip()
        if len(title) < 3 or title.casefold() in STOPWORDS:
            continue
        pattern = re.compile(r"(?<![\w\[|])" + re.escape(title) + r"(?:s|es)?(?![\w\]|])", re.I)
        for m in pattern.finditer(text):
            if not any(m.start() < e and s < m.end() for s, e, _ in spans) and not _inside_link(text, m.start()):
                spans.append((m.start(), m.end(), note))
                break
    out = text
    for start, end, note in sorted(spans, key=lambda s: -s[0]):
        surface = text[start:end]
        # Links resolve case-insensitively, so keep the writer's own words where possible.
        link = f"[[{surface}]]" if surface.casefold() == note.title.casefold() else f"[[{note.title}|{surface}]]"
        out = out[:start] + link + out[end:]
    return out, [n for _, _, n in sorted(spans, key=lambda s: s[0])]


def _inside_link(text: str, pos: int) -> bool:
    before = text[:pos]
    return before.rfind("[[") > before.rfind("]]")


def find_names(text: str, known: set[str]) -> list[str]:
    """Capitalised multi-word names not already linked or known as notes."""
    plain = re.sub(r"\[\[[^\]]*\]\]", " | ", text)  # don't look inside links
    names = []
    for m in NAME_RE.finditer(plain):
        words = m.group(1).split()
        at_sentence_start = not plain[: m.start()].strip() or plain[: m.start()].rstrip()[-1] in ".!?\n"
        if at_sentence_start and len(words) >= 3:
            words = words[1:]  # "Met Sarah Chen": the first capital is just grammar
        while words and words[0].casefold() in NOT_NAMES | STOPWORDS:
            words = words[1:]
        while words and words[-1].casefold() in NOT_NAMES | STOPWORDS:
            words = words[:-1]
        name = " ".join(words)
        if len(words) >= 2 and name.casefold() not in known and name not in names:
            names.append(name)
    return names


def suggest_tags(text: str, neighbours: list[tuple[float, Note]], vocabulary: set[str],
                 exclude: set[str], limit: int = 3) -> list[str]:
    scores: Counter = Counter()
    for score, note in neighbours[:5]:
        for tag in note.tags:
            scores[tag] += score
    text_tokens = set(tokens(text))
    for tag in vocabulary:
        if set(tokens(tag.replace("-", " "))) & text_tokens:
            scores[tag] += 0.3  # alone this isn't enough; similar notes must agree
    scores = Counter({t: s for t, s in scores.items() if t not in exclude})
    if not scores:
        return []
    top = max(scores.values())
    # Weak, scattered evidence isn't a tag: require an absolute and a relative bar.
    return [t for t, s in scores.most_common(limit) if s >= max(0.35, 0.4 * top)]


def enrich(vault: Vault, text: str, exclude_tags: set[str] = frozenset()) -> Enrichment:
    notes = vault.notes()
    if not notes:
        return Enrichment(text=text)
    linked_text, linked = link_mentions(text, notes)
    index = Index(notes)
    neighbours = index.similar(text)
    vocabulary = {t for n in notes for t in n.tags}
    linked_ids = {n.id for n in linked}
    related = [n for s, n in neighbours if s >= 0.15 and n.id not in linked_ids][:3]
    known = {n.title.casefold() for n in notes}
    return Enrichment(
        text=linked_text,
        tags=suggest_tags(text, neighbours, vocabulary, set(exclude_tags)),
        linked=linked,
        related=related,
        mentions=find_names(linked_text, known),
    )
