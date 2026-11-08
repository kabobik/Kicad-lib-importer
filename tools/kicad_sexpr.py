"""Small span-preserving reader for KiCad S-expressions; never reserializes input."""
from __future__ import annotations

from dataclasses import dataclass


def skip_string(text: str, i: int) -> int:
    i += 1
    while i < len(text):
        if text[i] == '\\':
            i += 2
        elif text[i] == '"':
            return i + 1
        else:
            i += 1
    raise ValueError('Unterminated quoted string')


def read_quoted(text: str, i: int) -> tuple[str, int]:
    end = skip_string(text, i)
    out = []
    i += 1
    while i < end - 1:
        if text[i] == '\\':
            i += 1
            out.append({'n': '\n', 'r': '\r', 't': '\t'}.get(text[i], text[i]))
        else:
            out.append(text[i])
        i += 1
    return ''.join(out), end


def matching_paren(text: str, start: int) -> int:
    depth = 0
    i = start
    while i < len(text):
        if text[i] == '"':
            i = skip_string(text, i)
            continue
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError(f'Unclosed list at offset {start}')


@dataclass
class Node:
    start: int
    end: int
    atoms: list[str]
    children: list[Node]

    @property
    def tag(self):
        return self.atoms[0] if self.atoms else ''

    def all(self, tag):
        return [c for c in self.children if c.tag == tag]

    def one(self, tag):
        matches = self.all(tag)
        if len(matches) != 1:
            raise ValueError(f'Expected one {tag} in {self.tag}, got {len(matches)}')
        return matches[0]

    def value(self, tag, default=None):
        matches = self.all(tag)
        if not matches:
            return default
        return matches[0].atoms[1]


def parse(text: str) -> Node:
    stack = []
    roots = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch == '(':
            node = Node(i, -1, [], [])
            (stack[-1].children if stack else roots).append(node)
            stack.append(node)
            i += 1
        elif ch == ')':
            if not stack:
                raise ValueError('Unexpected closing parenthesis')
            stack.pop().end = i + 1
            i += 1
        elif ch == '"':
            if not stack:
                raise ValueError('Atom outside root')
            value, i = read_quoted(text, i)
            stack[-1].atoms.append(value)
        else:
            end = i
            while end < len(text) and not text[end].isspace() and text[end] not in '()':
                end += 1
            if not stack:
                raise ValueError('Atom outside root')
            stack[-1].atoms.append(text[i:end])
            i = end
    if stack or len(roots) != 1:
        raise ValueError('Incomplete or multiple S-expression roots')
    return roots[0]


def quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') + '"'


def edit(text: str, changes: list[tuple[int, int, str]]) -> str:
    """Apply non-overlapping edits without changing any other input bytes."""
    parts = []
    cursor = 0
    for start, end, replacement in sorted(changes, key=lambda c: (c[0], c[1])):
        if start < cursor or end < start:
            raise ValueError('Overlapping document edits')
        parts.extend((text[cursor:start], replacement))
        cursor = end
    parts.append(text[cursor:])
    return ''.join(parts)
