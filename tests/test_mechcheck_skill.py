"""Feature-review skills' linked resources must survive a clean checkout."""

from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from markdown_it import MarkdownIt

SKILLS = Path(__file__).resolve().parents[1] / ".claude" / "skills"


@pytest.mark.parametrize("skill_name", ["mechcheck", "mech-html-review"])
def test_linked_resources_exist_and_are_reachable_from_entrypoint(skill_name):
    skill = SKILLS / skill_name
    parser = MarkdownIt()
    pending = [skill / "SKILL.md"]
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
                assert target.is_relative_to(skill), (document, link.path)
                assert target.is_file(), (document, link.path)
                if target.suffix == ".md":
                    pending.append(target)

    resources = {path.resolve() for path in (skill / "references").rglob("*.md")}
    assert resources
    assert resources <= visited
