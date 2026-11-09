"""Real Git distinguishes literal names from magic/glob pathspecs in closure proof."""
import subprocess

import pytest
from test_multi_pr_receipts import (  # noqa: F401 -- shared pytest fixtures
    EARLY_FIX,
    FIRST,
    LAST,
    ZERO,
    cycle_setup,
    duf,
    setup,
    supervisor,
    verify,
)


def repository_with_literal_name(tmp_path, path):
    root = tmp_path / "literal-tree"
    root.mkdir()

    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    git("init", "--quiet")
    (root / path).write_text("restored exact file bytes\n")
    (root / "ordinary.txt").write_text("unrelated file must never match\n")
    git("add", "--all")
    git("-c", "user.name=Synthetic reviewer", "-c", "user.email=synthetic@example.invalid",
        "commit", "--quiet", "-m", "literal path fixture")
    return root, git("rev-parse", "HEAD"), git("hash-object", "--", path)


@pytest.mark.parametrize("literal_environment", [None, "0", "1"])
@pytest.mark.parametrize("path", [
    ":(literal)restored.txt", ":(top,literal)restored.txt", ":(exclude)restored.txt",
    "*.txt", "[ab].txt", "file?.txt", "ordinary-looking.txt",
])
def test_exact_tree_entry_uses_literal_filename_not_pathspec(tmp_path, path, literal_environment, monkeypatch):
    if literal_environment is None:
        monkeypatch.delenv("GIT_LITERAL_PATHSPECS", raising=False)
    else:
        monkeypatch.setenv("GIT_LITERAL_PATHSPECS", literal_environment)
    root, head, blob = repository_with_literal_name(tmp_path, path)
    assert supervisor.tree_entry(str(root), head, path, supervisor.command) == ("100644", blob)
    assert supervisor.tree_entry(str(root), head, path + ".missing", supervisor.command) is None


@pytest.mark.parametrize("literal_environment", [None, "1"])
def test_ordered_closure_rejects_reintroduced_literal_deletion(duf, tmp_path, literal_environment, monkeypatch):  # noqa: F811 -- fixture
    """Run actual ls-tree in the full verifier; do not emulate pathspec parsing."""
    if literal_environment is None:
        monkeypatch.delenv("GIT_LITERAL_PATHSPECS", raising=False)
    else:
        monkeypatch.setenv("GIT_LITERAL_PATHSPECS", literal_environment)
    assert verify(duf)["pr_number"] == 367
    path = ":(literal)restored.txt"
    root, head, blob = repository_with_literal_name(tmp_path, path)
    duf.remote.raw_changes[EARLY_FIX] += f":100644 000000 {blob} {ZERO} D\0{path}\0"
    for reviewed in (FIRST["head_sha"], LAST["head_sha"]):
        duf.remote.trees[reviewed][path] = blob
    original = duf.remote

    def real_lookup(args, **kwargs):
        command = args[3:]
        flags = ["--literal-pathspecs"] if command[:1] == ["--literal-pathspecs"] else []
        if flags:
            command = command[1:]
        if args[0] == "git" and command[:1] == ["ls-tree"] and args[-1] == path:
            return supervisor.command(["git", "-C", str(root), *flags, "ls-tree", "-z", head, "--", path], **kwargs)
        return original(args, **kwargs)

    duf.remote = real_lookup
    with pytest.raises(supervisor.SupervisorError, match="member reviewed head"):
        verify(duf)
