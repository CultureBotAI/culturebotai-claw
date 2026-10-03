"""MechCheck's linked local resources must survive a clean checkout."""

from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

SKILL = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "mechcheck"


def test_linked_resources_exist_and_are_reachable_from_entrypoint():
    parser = MarkdownIt()
    pending = [SKILL / "SKILL.md"]
    visited = set()
    while pending:
        document = pending.pop().resolve()
        if document in visited:
            continue
        visited.add(document)
        for block in parser.parse(document.read_text(encoding="utf-8")):
            for token in block.children or ():
                if token.type != "link_open":
                    continue
                link = urlsplit(token.attrGet("href") or "")
                if link.scheme or link.netloc or not link.path:
                    continue
                target = (document.parent / unquote(link.path)).resolve()
                assert target.is_relative_to(SKILL), (document, link.path)
                assert target.is_file(), (document, link.path)
                if target.suffix == ".md":
                    pending.append(target)

    resources = {path.resolve() for path in (SKILL / "references").rglob("*.md")}
    assert resources
    assert resources <= visited
