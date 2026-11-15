# Select one pinned transport for a real read-only canary, claw issue 1238.
# Input: proposed private tmux registry; --arg key selects one exact target.
# Output: one-target registry on stdout. No live config is written. 2026-11-15.
if .schema_version != 1 or .role != "observer_only" then
  error("invalid observation registry")
else
  .targets = [.targets[] | select(.key == $key)]
  | if (.targets | length) != 1 then error("canary key is missing or ambiguous") else . end
end
