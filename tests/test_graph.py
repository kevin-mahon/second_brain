import re

import numpy as np

from secondbrain.graph import Canvas, Graph, force_layout, render, stats
from secondbrain.vault import Vault

ANSI = re.compile(r"\033\[[0-9;]*m")


def make_graph(machine) -> Graph:
    vault = Vault(machine("g"))
    vault.create("Hub", body="[[A]] [[B]] [[C]] [[Nowhere]]\n")
    vault.create("A", body="[[B]]\n")
    vault.create("B")
    vault.create("C", body="[[D]]\n")
    vault.create("D")
    vault.create("Island one", body="[[Island two]]\n")
    vault.create("Island two")
    vault.create("Loner")
    return Graph.from_vault(vault)


def titles(graph, indices):
    return {graph.notes[i].title for i in indices}


def test_edges_are_undirected_and_deduplicated(machine):
    g = make_graph(machine)
    assert len(g.edges) == 6  # Hub-A Hub-B Hub-C A-B C-D Island
    assert [(n.title, t) for n, t in g.broken] == [("Hub", "Nowhere")]
    assert titles(g, g.orphans()) == {"Loner"}


def test_neighborhood_depth(machine):
    g = make_graph(machine)
    hub = next(i for i, n in enumerate(g.notes) if n.title == "Hub")
    assert titles(g, g.neighborhood(hub, 1)) == {"Hub", "A", "B", "C"}
    assert titles(g, g.neighborhood(hub, 2)) == {"Hub", "A", "B", "C", "D"}
    sub = g.subgraph(g.neighborhood(hub, 1))
    assert len(sub.notes) == 4 and len(sub.edges) == 4


def test_layout_is_deterministic_and_separates_components(machine):
    g = make_graph(machine)
    keys = [n.id for n in g.notes]
    a, b = force_layout(keys, g.edges), force_layout(keys, g.edges)
    assert np.allclose(a, b)
    # Islands don't overlap the main component's bounding box.
    main = [i for i, n in enumerate(g.notes) if n.title in {"Hub", "A", "B", "C", "D"}]
    island = [i for i, n in enumerate(g.notes) if n.title.startswith("Island")]
    lo, hi = a[main].min(0), a[main].max(0)
    assert not any((lo <= a[i]).all() and (a[i] <= hi).all() for i in island)


def test_render_fits_the_terminal(machine):
    g = make_graph(machine)
    for color in (True, False):
        out = render(g, 60, 20, color=color)
        lines = ANSI.sub("", out).split("\n")
        assert len(lines) <= 20
        assert max(len(line) for line in lines) <= 60
        assert "Hub" in out and "8 notes" in out


def test_braille_line():
    canvas = Canvas(2, 1)
    canvas.line(0, 0, 3, 0, "")
    assert canvas.render(color=False) == ["⠉⠉"]


def test_stats_lists_hubs_orphans_and_broken(machine):
    text = stats(make_graph(machine))
    assert "Hub" in text.split("Hubs")[1].split("\n")[1]
    assert "Loner" in text and "[[Nowhere]]" in text
