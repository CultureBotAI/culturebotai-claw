# Bounded metadata failure diagnostics — issue 1223

This change adds diagnostic context; it does not repair the transport cause or
retrospectively explain a failed runner request. It starts from protected main
`23899092a4a2aedf53ff4435c0bdc03ebd79e6be` on a separate feature branch.

## Observed boundary

PR1219's [governance run 43674807125](https://github.com/CultureBotAI/culturebotai-claw/actions/runs/43674807125)
used that current protected main and candidate merge
`be40733fdca92407a9434ea561400d9ca031f627`. Its public component then failed with
`stage=public_metadata code=transport_refused`. The log omits the repository,
HTTP status and transport category. No rate-limit, redirect or network cause
can be established from that log. The private retained public-fleet log has
SHA256 `f9677f548e50a5efd819a444f74be2fb506ce4429ce0c402f624f1a2e8170ba9`.

One anonymous local GET of the fixed AIMech metadata endpoint returned HTTP200
and the exact public/main identity (6,420 response bytes). That local result
does not reproduce the runner environment or verify every consumer. Its private
response SHA256 is `d2ba85f88ba19b99b9be85f17336b70ae837ba3eacdc7ab7a232d6a087d63cdc`;
header SHA256 is `763ec2c823c05bad1881a7fa9d4e7c291f9aba98dd71fca90ba5b41a60150799`.

The public component fails before fleet source preparation/auditing; this is a
governance transport blocker, not evidence that the SupportingReference schema
change failed its scientific or contract checks. The full PR1219 pytest run
remains a separate result and is not certified by this report.

## Change and validation

Only the admitted public repository identity, a closed category, numeric HTTP
status and bounded numeric quota fields may be appended to the existing fatal
CLI message. URLs, exception messages, response bodies and arbitrary headers
are omitted. Failure code, exit2, anonymous access, one-request behavior,
redirect refusal and all validation guards are preserved. Unexpected diagnostic
fields suppress the entire suffix. Legacy response-validation failures retain
their fatal `transport_refused` code with an additional category.

The real CLI/metadata-client regression replaces HTTP I/O with a synthetic
HTTP403 response. It failed before the change, then passed while verifying one
request, exit2, no success receipt and no secret/URL output. It is a local
failure-path canary, not a successful live governance audit.

| Private retained evidence under `.temp/metadata-diagnostics-1223-20261115/` | Result | SHA256 |
|---|---|---|
| `canary-before-001.log` | 1 failed as expected; diagnostic details absent | `19cdf207d95ae75cd8a99c66a1effcee0a4b021b4c72b129cd56541540b66554` |
| `canary-after-001.log` | 1 passed | `59b8cce6c619cad8af361976843b6c11a066cbd2f1d1075b5b21cfa948dfbeec` |
| `bounded-controls-002.log` | 199 passed in six relevant test modules | `5d421c7135753c5faec1b306f61387eb7e0ba8546369bd315edcd5db13aba41d` |

The six modules cover metadata diagnostics, public metadata transport, CLI
diagnostics, the automatic fleet component, historical adapter compatibility
and public materialization. Ruff and mypy on the changed production modules
passed. No workflow, token scope, runtime selection, fallback or manifest pin
changed.

Candidate code cannot become its own trusted runtime. These diagnostics can
affect later authoritative runs only after a separately approved merge to
protected main. Issue1223 remains unresolved until an actual diagnostic run
identifies the cause and a subsequent valid fleet run succeeds. Neither this
diagnostics branch nor PR1219 has merge approval.
