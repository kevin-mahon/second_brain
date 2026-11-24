"""The knowledge graph: force-directed layout, drawn in the terminal.

Edges are drawn with braille characters (each cell is a 2x4 grid of dots, so
lines look smooth); notes are markers sized by how connected they are, and
colored by cluster or tag.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, deque
from dataclasses import dataclass

import numpy as np

from .note import Note
from .vault import Vault

# -- graph --------------------------------------------------------------------


@dataclass
class Graph:
    notes: list[Note]
    edges: list[tuple[int, int]]  # undirected, i < j, unique
    broken: list[tuple[Note, str]]  # (note, link target that resolves to nothing)

    @classmethod
    def from_vault(cls, vault: Vault) -> "Graph":
        notes = [n for n in vault.notes() if n.id]
        index = {n.id: i for i, n in enumerate(notes)}
        edges: set[tuple[int, int]] = set()
        broken = []
        for i, note in enumerate(notes):
            for target in note.links:
                linked = vault.resolve_link(target)
                if linked is None or linked.id not in index:
                    broken.append((note, target))
                    continue
                j = index[linked.id]
                if j != i:
                    edges.add((min(i, j), max(i, j)))
        return cls(notes, sorted(edges), broken)

    def neighbors(self) -> list[set[int]]:
        nbrs: list[set[int]] = [set() for _ in self.notes]
        for i, j in self.edges:
            nbrs[i].add(j)
            nbrs[j].add(i)
        return nbrs

    def degrees(self) -> list[int]:
        return [len(n) for n in self.neighbors()]

    def orphans(self) -> list[int]:
        return [i for i, d in enumerate(self.degrees()) if d == 0]

    def neighborhood(self, center: int, depth: int) -> list[int]:
        nbrs = self.neighbors()
        dist = {center: 0}
        queue = deque([center])
        while queue:
            i = queue.popleft()
            if dist[i] >= depth:
                continue
            for j in nbrs[i]:
                if j not in dist:
                    dist[j] = dist[i] + 1
                    queue.append(j)
        return sorted(dist)

    def subgraph(self, keep: list[int]) -> "Graph":
        remap = {old: new for new, old in enumerate(keep)}
        kept = {id(self.notes[i]) for i in keep}
        return Graph(
            notes=[self.notes[i] for i in keep],
            edges=[(remap[i], remap[j]) for i, j in self.edges if i in remap and j in remap],
            broken=[(n, t) for n, t in self.broken if id(n) in kept],
        )

    def clusters(self) -> list[int]:
        """Label propagation: each note repeatedly adopts its neighbours' most common label."""
        nbrs = self.neighbors()
        labels = list(range(len(self.notes)))
        order = sorted(range(len(self.notes)), key=lambda i: (-len(nbrs[i]), self.notes[i].id))
        for _ in range(50):
            changed = False
            for i in order:
                if not nbrs[i]:
                    continue
                counts = Counter(labels[j] for j in nbrs[i])
                best = max(counts.values())
                candidates = [label for label, c in counts.items() if c == best]
                new = labels[i] if labels[i] in candidates else min(candidates)
                if new != labels[i]:
                    labels[i] = new
                    changed = True
            if not changed:
                break
        return labels


# -- layout -------------------------------------------------------------------


def _seed_point(key: str) -> tuple[float, float]:
    """A stable pseudo-random start position, so the picture doesn't reshuffle every run."""
    h = hashlib.sha256(key.encode()).digest()
    return (int.from_bytes(h[:4], "big") / 2**31 - 1, int.from_bytes(h[4:8], "big") / 2**31 - 1)


def _force_component(keys: list[str], edges: list[tuple[int, int]], iterations: int | None) -> np.ndarray:
    """Fruchterman-Reingold on one connected component: links attract, all notes repel."""
    n = len(keys)
    pos = np.array([_seed_point(k) for k in keys], dtype=float)
    if n == 1:
        return pos * 0
    k = math.sqrt(4.0 / n)  # ideal edge length for a [-1, 1]^2 area
    iterations = iterations or (300 if n <= 300 else 150 if n <= 1500 else 60)
    temperature = 0.3
    cooling = temperature / (iterations + 1)
    gravity = 0.05
    edge_arr = np.array(edges, dtype=int).reshape(-1, 2)

    for _ in range(iterations):
        delta = pos[:, None, :] - pos[None, :, :]
        dist2 = np.maximum((delta**2).sum(-1), 1e-6)
        disp = (delta * (k * k / dist2)[:, :, None]).sum(axis=1)  # repulsion k²/d

        d = pos[edge_arr[:, 0]] - pos[edge_arr[:, 1]]
        length = np.sqrt(np.maximum((d**2).sum(1), 1e-12))
        pull = d * (length / k)[:, None]  # attraction d²/k
        np.add.at(disp, edge_arr[:, 0], -pull)
        np.add.at(disp, edge_arr[:, 1], pull)

        disp -= pos * gravity * n * k
        step = np.sqrt(np.maximum((disp**2).sum(1), 1e-18))
        pos += disp / step[:, None] * np.minimum(step, temperature)[:, None]
        temperature = max(temperature - cooling, 0.002)
    return pos


def force_layout(
    keys: list[str], edges: list[tuple[int, int]], iterations: int | None = None, aspect: float = 2.0
) -> np.ndarray:
    """Lay out each connected component on its own, then pack them in rows.

    Laying out components separately stops unrelated groups of notes from
    drifting into each other. `aspect` is the target width/height of the result.
    """
    n = len(keys)
    if n == 0:
        return np.zeros((0, 2))
    nbrs: list[list[int]] = [[] for _ in range(n)]
    for i, j in edges:
        nbrs[i].append(j)
        nbrs[j].append(i)
    seen, components = set(), []
    for start in range(n):
        if start in seen:
            continue
        comp, queue = [], [start]
        seen.add(start)
        while queue:
            i = queue.pop()
            comp.append(i)
            for j in nbrs[i]:
                if j not in seen:
                    seen.add(j)
                    queue.append(j)
        components.append(sorted(comp))
    components.sort(key=lambda c: (-len(c), keys[c[0]]))

    # Each component gets a box whose side grows with sqrt(size), so density is even.
    boxes = []
    for comp in components:
        local = {old: new for new, old in enumerate(comp)}
        comp_edges = [(local[i], local[j]) for i, j in edges if i in local and j in local]
        pos = _force_component([keys[i] for i in comp], comp_edges, iterations)
        lo, hi = pos.min(axis=0), pos.max(axis=0)
        side = math.sqrt(len(comp))
        span = np.maximum(hi - lo, 1e-9)
        scale = side / span.max() if len(comp) > 1 else 0
        boxes.append((comp, (pos - lo) * scale, np.maximum(span * scale, 0.5)))

    # Shelf packing: fill rows left to right up to a width that gives the target aspect.
    total_area = sum((b[2][0] + 1) * (b[2][1] + 1) for b in boxes)
    row_width = max(math.sqrt(total_area * aspect), max(b[2][0] for b in boxes))
    out = np.zeros((n, 2))
    x = y = row_height = 0.0
    for comp, pos, size in boxes:
        if x > 0 and x + size[0] > row_width:
            x, y, row_height = 0.0, y + row_height + 1, 0.0
        out[comp] = pos + np.array([x, y])
        x += size[0] + 1
        row_height = max(row_height, size[1])
    return out


# -- canvas -------------------------------------------------------------------

# Braille dot bit for sub-pixel (x, y) inside a cell, x in 0..1, y in 0..3.
_BRAILLE = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))

NODE_COLORS = [96, 95, 93, 92, 94, 91]  # bright cyan, magenta, yellow, green, blue, red
EDGE_COLORS = {96: 36, 95: 35, 93: 33, 92: 32, 94: 34, 91: 31}
OTHER_NODE, OTHER_EDGE = 37, 90


class Canvas:
    def __init__(self, width: int, height: int):
        self.width, self.height = width, height
        self.dots = [[0] * width for _ in range(height)]
        self.dot_style: list[list[str]] = [[""] * width for _ in range(height)]
        self.text: list[list[tuple[str, str] | None]] = [[None] * width for _ in range(height)]

    def dot(self, x: int, y: int, style: str) -> None:
        col, row = x // 2, y // 4
        if 0 <= col < self.width and 0 <= row < self.height:
            self.dots[row][col] |= _BRAILLE[y % 4][x % 2]
            self.dot_style[row][col] = style

    def line(self, x0: int, y0: int, x1: int, y1: int, style: str) -> None:
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.dot(x0, y0, style)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def is_free(self, col: int, row: int, length: int) -> bool:
        if row < 0 or row >= self.height or col < 0 or col + length > self.width:
            return False
        return all(self.text[row][c] is None for c in range(col, col + length))

    def put(self, col: int, row: int, text: str, style: str) -> None:
        for offset, ch in enumerate(text):
            c = col + offset
            if 0 <= c < self.width and 0 <= row < self.height:
                self.text[row][c] = (ch, style)

    def render(self, color: bool) -> list[str]:
        lines = []
        for row in range(self.height):
            out, current = [], ""
            for col in range(self.width):
                cell = self.text[row][col]
                if cell:
                    ch, style = cell
                elif self.dots[row][col]:
                    ch, style = chr(0x2800 + self.dots[row][col]), self.dot_style[row][col]
                else:
                    ch, style = " ", ""
                if color and style != current:
                    out.append("\033[0m" + (f"\033[{style}m" if style else ""))
                    current = style
                out.append(ch)
            if color and current:
                out.append("\033[0m")
            lines.append("".join(out).rstrip())
        return lines


# -- rendering ----------------------------------------------------------------


def _marker(degree: int, hub_degree: int) -> str:
    if degree >= max(4, hub_degree * 0.6):
        return "◉"
    if degree >= 3:
        return "●"
    if degree >= 1:
        return "•"
    return "·"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _groups(graph: Graph, by: str) -> tuple[list[str], list[tuple[str, int, int]]]:
    """Assign each note a color. Returns (style per note, legend [(name, color, count)])."""
    degrees = graph.degrees()
    if by == "tag":
        counts = Counter(t for n in graph.notes for t in n.tags)
        key = [min(n.tags, key=lambda t: (-counts[t], t)) if n.tags else None for n in graph.notes]
        name_of = {k: f"#{k}" for k in key if k}
    else:
        key = graph.clusters()
        hubs: dict[int, int] = {}
        for i, label in enumerate(key):
            if label not in hubs or degrees[i] > degrees[hubs[label]]:
                hubs[label] = i
        name_of = {label: graph.notes[i].title for label, i in hubs.items()}
        # A cluster of one isolated note isn't a cluster.
        key = [k if degrees[i] else None for i, k in enumerate(key)]

    sizes = Counter(k for k in key if k is not None)
    ranked = [k for k, size in sizes.most_common() if size > 1 or by == "tag"]
    color_of = {k: NODE_COLORS[i] for i, k in enumerate(ranked[: len(NODE_COLORS)])}
    styles = [str(color_of.get(k, OTHER_NODE)) for k in key]
    legend = [(name_of[k], color_of[k], sizes[k]) for k in ranked[: len(NODE_COLORS)]]
    return styles, legend


def render(
    graph: Graph,
    width: int,
    height: int,
    *,
    center: int | None = None,
    by: str = "cluster",
    labels: bool = True,
    color: bool = True,
    footer: list[str] | None = None,
) -> str:
    """Draw the graph into a width x height block of text, plus a legend underneath."""
    styles, legend = _groups(graph, by)
    legend_lines = _legend(graph, legend, width, color, footer or [])
    height = max(5, height - len(legend_lines))
    canvas = Canvas(width, height)
    n = len(graph.notes)
    if n == 0:
        return "\n".join(["(no notes to draw)", *legend_lines])

    # Character cells are about twice as tall as wide, so a 2:1 sub-pixel area
    # matches the canvas when its cells are (width x height) -> (2w x 4h).
    pos = force_layout(
        [note.id or str(i) for i, note in enumerate(graph.notes)],
        graph.edges,
        aspect=(width * 2) / (height * 4),
    )

    # Fit into sub-pixel space (2 x 4 per cell). Each axis gets its own scale, but
    # neither may stretch more than 2x relative to the other, so shapes stay recognisable.
    sub_w, sub_h = width * 2, height * 4
    margin_x, margin_y = 4, 4
    lo, hi = pos.min(axis=0), pos.max(axis=0)
    span = np.maximum(hi - lo, 1e-9)
    sx = (sub_w - 1 - 2 * margin_x) / span[0]
    sy = (sub_h - 1 - 2 * margin_y) / span[1]
    sx, sy = min(sx, 2 * sy), min(sy, 2 * sx)
    if n == 1:
        sx = sy = 0
    offset = np.array([(sub_w - span[0] * sx) / 2, (sub_h - span[1] * sy) / 2])
    pts = ((pos - lo) * np.array([sx, sy]) + offset).round().astype(int)
    pts[:, 0] = pts[:, 0].clip(0, sub_w - 1)
    pts[:, 1] = pts[:, 1].clip(0, sub_h - 1)

    for i, j in graph.edges:
        same = styles[i] == styles[j] and styles[i] != str(OTHER_NODE)
        edge = EDGE_COLORS.get(int(styles[i]), OTHER_EDGE) if same else OTHER_EDGE
        if center is not None and center in (i, j):
            edge = int(styles[center])
        canvas.line(*pts[i], *pts[j], style=str(edge))

    degrees = graph.degrees()
    hub_degree = max(degrees) if degrees else 0
    cells = [(int(x) // 2, int(y) // 4) for x, y in pts]
    for i, (col, row) in enumerate(cells):
        marker = "◎" if i == center else _marker(degrees[i], hub_degree)
        style = f"1;{styles[i]}" + (";7" if i == center else "")
        canvas.put(col, row, marker, style)

    if labels:
        # Best-connected notes get first pick of label space.
        order = sorted(range(n), key=lambda i: (i != center, -degrees[i], graph.notes[i].title))
        limit = max(8, min(28, width // 6))
        for i in order:
            col, row = cells[i]
            text = _truncate(graph.notes[i].title, 40 if i == center else limit)
            style = f"1;{styles[i]}" if i == center or degrees[i] >= hub_degree * 0.6 else styles[i]
            for start in (col + 1, col - len(text) - 1):
                # Pad by one cell on both sides so labels never touch each other.
                if canvas.is_free(start - (start < col), row, len(text) + 1):
                    canvas.put(start, row, (" " + text) if start > col else (text + " "), style)
                    break

    return "\n".join(canvas.render(color) + legend_lines)


def _legend(graph: Graph, legend: list[tuple[str, int, int]], width: int, color: bool, footer: list[str]) -> list[str]:
    def paint(text: str, code: int | str) -> str:
        return f"\033[{code}m{text}\033[0m" if color else text

    summary = f"{len(graph.notes)} notes · {len(graph.edges)} links"
    if graph.broken:
        summary += f" · {len(graph.broken)} broken"
    lines = [paint(" · ".join([summary, *footer]), 2)]

    row, row_len = [], 0
    for name, code, count in legend:
        item = f"● {_truncate(name, 24)} ({count})"
        if row and row_len + len(item) + 3 > width:
            lines.append("   ".join(row))
            row, row_len = [], 0
        row.append(paint(item, code))
        row_len += len(item) + 3
    if row:
        lines.append("   ".join(row))
    return lines


def stats(graph: Graph) -> str:
    degrees = graph.degrees()
    labels = graph.clusters()
    connected = [i for i, d in enumerate(degrees) if d]
    lines = [
        f"{len(graph.notes)} notes, {len(graph.edges)} links, "
        f"{len({labels[i] for i in connected})} clusters, {len(graph.orphans())} orphans",
        "",
        "Hubs (most connected):",
    ]
    for i in sorted(connected, key=lambda i: (-degrees[i], graph.notes[i].title))[:10]:
        lines.append(f"  {degrees[i]:3d}  {graph.notes[i].title}")
    if graph.orphans():
        lines += ["", "Orphans (no links in or out):"]
        lines += [f"       {graph.notes[i].title}" for i in graph.orphans()]
    if graph.broken:
        lines += ["", "Broken links:"]
        lines += [f"       {note.title} → [[{target}]]" for note, target in graph.broken]
    return "\n".join(lines)
