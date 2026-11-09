"""Published auxiliary views must remain usable outside the main browser."""

import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest
import yaml

from kg_microbe_discussions.export import write_browser
from kg_microbe_qc.generator import generate_dashboard

DIRECTORY = "https://culturebotai.github.io/mechs/"


class Elements(HTMLParser):
    def __init__(self, text: str):
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.feed(text)

    def find(self, tag: str, **attrs: str):
        return [values for name, values in self.tags if name == tag
                and all(values.get(key.replace("_", "-")) == value
                        for key, value in attrs.items())]

    def handle_starttag(self, tag: str, attrs):
        self.tags.append((tag, dict(attrs)))


def test_dashboard_preserves_data_in_a_responsive_navigable_table(tmp_path: Path):
    records = tmp_path / "records"
    records.mkdir()
    (records / "one.yaml").write_text("name: '<biology> & evidence'\n")
    config = tmp_path / "qc.yaml"
    config.write_text(yaml.safe_dump({
        "repo_name": "FixtureMech", "yaml_dir": str(records),
        "slots": [{"path": "name", "required": True, "threshold": 0.9}],
    }))
    target = tmp_path / "dashboard"
    stats = generate_dashboard(config_path=config, output_dir=target)
    page = Elements((target / "index.html").read_text())
    assert stats.record_count == 1 and stats.scores[0].populated == 1
    assert page.find("meta", name="viewport", content="width=device-width, initial-scale=1")
    assert len(page.find("main", id="main-content")) == 1
    assert page.find("a", href=DIRECTORY)
    assert page.find("a", href="#main-content")
    assert page.find("div", role="region", tabindex="0", aria_label="Per-slot coverage")
    assert page.find("caption")
    assert len(page.find("th", scope="col")) == 5


def test_discussion_browser_exposes_named_controls_and_dynamic_status(tmp_path: Path):
    write_browser([], {"total_discussions": 0}, "FixtureMech", tmp_path)
    page = Elements((tmp_path / "index.html").read_text())
    assert page.find("a", href=DIRECTORY)
    assert page.find("label", **{"for": "q"})
    assert page.find("button", id="clear-filters", type="button")
    assert page.find("div", id="count", role="status", aria_live="polite")
    assert len(page.find("main", id="main-content")) == 1
    assert page.find("noscript")


def test_discussion_load_states_literal_text_and_keyboard_reset(tmp_path: Path):
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node is required to verify the generated browser script")
    write_browser([], {"total_discussions": 0}, "FixtureMech", tmp_path)
    harness = Path(__file__).with_name("shared_html_browser_harness.cjs")
    subprocess.run([node, str(harness), str(tmp_path / "index.html")], check=True)
