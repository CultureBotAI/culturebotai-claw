#!/bin/bash
# Historical review evidence: a Claude reviewer's probe for PR 851, the tenth round (8397708cd0); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
# Review probes for PR 851 round 10 (2026-11-07): pushInsteadOf prefix realism, empty pushInsteadOf,
# empty-star glob match, destination-less refspec on a push, valueless config key. Scratch only.
set -u
S=/Users/marcin/agent-work/culturebotai-claw/review851r10-scratch/gitprobe
rm -rf "$S"; mkdir -p "$S"; cd "$S"
export GIT_CONFIG_GLOBAL="$S/gitconfig" GIT_CONFIG_NOSYSTEM=1
printf '[user]\n\tname = test\n\temail = test\n[init]\n\tdefaultBranch = main\n' > "$S/gitconfig"
mkrepos() {
  rm -rf src origin.git fork.git clone
  git init -q src && (cd src && echo a > a && git add a && git commit -q -m init && git branch -q feature && echo b > b && git add b && git -c core.hooksPath=/dev/null commit -q -m two)
  git clone -q --bare src origin.git
  git clone -q --bare origin.git fork.git
  git clone -q origin.git clone
  (cd clone && git fetch -q origin)
}
echo "=== A: pushInsteadOf proper prefix (fixture shape) ==="
mkrepos
ORIG="$S/origin.git"; FORK="$S/fork.git"
git -C clone config remote.origin.pushurl "$ORIG"
git -C clone config "url.${FORK%.git}.pushInsteadOf" "${ORIG%.git}"
echo "get-url --push origin: $(git -C clone remote get-url --push origin)"
git -C clone push -q "$ORIG" HEAD:refs/heads/probeA 2>&1 | sed 's/^/  push: /'
echo "origin has probeA: $(git -C origin.git rev-parse --verify --quiet refs/heads/probeA || echo none)"
echo "fork   has probeA: $(git -C fork.git rev-parse --verify --quiet refs/heads/probeA || echo none)"
echo "--- and pushing by name 'origin' (explicit pushurl, so pushInsteadOf must not apply):"
git -C clone push -q origin HEAD:refs/heads/probeA2 2>&1 | sed 's/^/  push: /'
echo "origin has probeA2: $(git -C origin.git rev-parse --verify --quiet refs/heads/probeA2 || echo none)"
echo "fork   has probeA2: $(git -C fork.git rev-parse --verify --quiet refs/heads/probeA2 || echo none)"

echo; echo "=== B: EMPTY-valued pushInsteadOf (does git rewrite every URL?) ==="
mkrepos
git -C clone config remote.origin.pushurl "$ORIG"
git -C clone config "url.${FORK}.pushInsteadOf" ""
echo "config -z --get-regexp: $(git -C clone config -z --get-regexp '^url\..*\.pushinsteadof$' | od -c | head -3)"
echo "get-url --push origin: $(git -C clone remote get-url --push origin)"
git -C clone push -q "$ORIG" HEAD:refs/heads/probeB 2>&1 | sed 's/^/  push: /'
echo "origin has probeB: $(git -C origin.git rev-parse --verify --quiet refs/heads/probeB || echo none)"
echo "fork   has probeB: $(git -C fork.git rev-parse --verify --quiet refs/heads/probeB || echo none)"

echo; echo "=== C: empty-star glob  +refs/heads/feature*:refs/heads/victim*  on a named push --delete ==="
mkrepos
git -C clone branch -q victim origin/main
git -C clone config remote.origin.fetch '+refs/heads/feature*:refs/heads/victim*'
echo "victim before: $(git -C clone rev-parse --verify --quiet refs/heads/victim || echo none)"
git -C clone push origin --delete refs/heads/feature 2>&1 | sed 's/^/  push: /'; echo "  push exit=${PIPESTATUS[0]}"
echo "victim after : $(git -C clone rev-parse --verify --quiet refs/heads/victim || echo none)"
echo "origin feature: $(git -C origin.git rev-parse --verify --quiet refs/heads/feature || echo none)"

echo; echo "=== D1: destination-less  refs/heads/feature:  FIRST in fetch list, named push --delete ==="
mkrepos
git -C clone config remote.origin.fetch 'refs/heads/feature:'
git -C clone push origin --delete refs/heads/feature 2>&1 | sed 's/^/  push: /'; echo "  push exit=${PIPESTATUS[0]}"
echo "origin feature: $(git -C origin.git rev-parse --verify --quiet refs/heads/feature || echo none)"
echo "local refs: $(git -C clone for-each-ref --format='%(refname)' | tr '\n' ' ')"

echo; echo "=== D2: empty-source  :refs/heads/x  as fetch refspec: fetch, then named push --delete feature ==="
mkrepos
git -C clone config --add remote.origin.fetch ':refs/heads/x'
git -C clone fetch origin 2>&1 | sed 's/^/  fetch: /'; echo "  fetch exit=${PIPESTATUS[0]}"
echo "local x after fetch: $(git -C clone rev-parse --verify --quiet refs/heads/x || echo none)  (origin HEAD -> $(git -C origin.git symbolic-ref HEAD))"
git -C clone push -q origin --delete refs/heads/feature 2>&1 | sed 's/^/  push: /'
echo "local x after push : $(git -C clone rev-parse --verify --quiet refs/heads/x || echo none)"
echo "tracking feature   : $(git -C clone rev-parse --verify --quiet refs/remotes/origin/feature || echo none)"

echo; echo "=== D3: +refs/heads/feature: (leading plus, empty dst) FIRST, named push --delete ==="
mkrepos
git -C clone config remote.origin.fetch '+refs/heads/feature:'
git -C clone push origin --delete refs/heads/feature 2>&1 | sed 's/^/  push: /'; echo "  push exit=${PIPESTATUS[0]}"

echo; echo "=== E: valueless key in a config with other sections first ==="
mkrepos
git -C clone branch -q feature origin/feature
git -C clone config branch.feature.rebase true
echo "--- .git/config before:"; cat clone/.git/config | sed 's/^/  /'
python3 - "$S/clone/.git/config" <<'PY'
import sys; p=sys.argv[1]; t=open(p).read(); n=t.replace('[branch "feature"]\n','[branch "feature"]\n\tbare\n',1); open(p,'w').write(n); print("replaced:", t!=n)
PY
echo "--- .git/config after insert:"; cat clone/.git/config | sed 's/^/  /'
echo "type=bool bare: $(git -C clone config --type=bool branch.feature.bare)"
echo "-z get-regexp: $(git -C clone config -z --get-regexp '^branch\.feature\.' | od -c | tr -s ' ' | head -5)"
echo "plain get-regexp:"; git -C clone config --get-regexp '^branch\.feature\.' | sed 's/^/  /'
git -C clone config --remove-section branch.feature; echo "remove-section exit=$?"
git -C clone config --get-regexp '^branch\.feature\.'; echo "get-regexp after remove exit=$? (1 = nothing left)"
grep -n 'branch "feature"' clone/.git/config || echo "section header gone from file"
git -C clone config --add branch.feature.bare true; echo "restored type=bool: $(git -C clone config --type=bool branch.feature.bare)"
echo "--- empty-valued key 'bare =' round trip:"
git -C clone config branch.feature.empty ""
echo "-z: $(git -C clone config -z --get branch.feature.empty | od -c | head -2)"
echo "type=bool empty: $(git -C clone config --type=bool branch.feature.empty 2>&1)"
