"""Map the values a question mentions to the values actually stored.

"سارا القحطانى" -> "سارة القحطاني", "دبى" -> "Dubai", "محمد" -> two agents, ask which.
The model is told the exact spellings, so this is a safety net, not the main path.
"""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process

from .text import fold


@dataclass
class Ambiguous(Exception):
    dimension: str
    said: str
    options: list[str]


@dataclass
class NotFound(Exception):
    dimension: str
    said: str
    known: list[str]


class Linker:
    def __init__(self, values: dict[str, list[str]], aliases: dict[str, dict[str, str]]):
        """values: dimension -> stored values. aliases: dimension -> {alias: stored value}."""
        self.values = values
        self.index: dict[str, dict[str, str]] = {}
        for dim, vals in values.items():
            idx = {fold(v): v for v in vals}
            for alias, target in aliases.get(dim, {}).items():
                idx.setdefault(fold(alias), target)
            self.index[dim] = idx

    def resolve(self, dim: str, said):
        if isinstance(said, bool) or dim not in self.index:
            return said
        idx = self.index[dim]
        key = fold(said)
        if key in idx:
            return idx[key]
        # a first name alone: "محمد" matches every agent whose name starts with it
        starts = sorted({v for k, v in idx.items() if k.split(" ")[0] == key})
        if len(starts) == 1:
            return starts[0]
        if len(starts) > 1:
            raise Ambiguous(dim, said, starts)
        best = process.extract(key, list(idx), scorer=fuzz.WRatio, limit=2)
        # one letter off in a 7-letter word scores ~86; demand a clear winner over the runner-up
        if best and best[0][1] >= 80 and (len(best) == 1 or best[0][1] - best[1][1] >= 8):
            return idx[best[0][0]]
        raise NotFound(dim, said, sorted(set(idx.values())))
