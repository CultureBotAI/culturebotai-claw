"""What a Mech's data-source queue must hold to, checked once for the fleet.

`curation/source_queue.tsv` is the ranked list of data sources a corpus draws on
or might adopt: what gap each closes, whether its licence permits redistribution,
and whether it has been verified. AntibioticMech wrote one and
CellStructureMech adapted it, and the request to give the other five the same
skill is the reason to write this now rather than after seven copies exist.

The two are already diverging, with only two copies:

* their checkers are 174 and 137 lines and differ by 133;
* AntibioticMech's queue carries a `structures` column, CellStructureMech's
  carries `taxon_link`, `item_id` and `script`; and
* the same licence class is spelled `NON_COMMERCIAL` in one and `NONCOMMERCIAL`
  in the other.

That last one is the argument in miniature. Nothing catches it, both are
plausible, and a reader comparing the two queues has no way to know they mean
the same thing. Phase 7 found the same shape in `audit_writers.py` after four
copies had drifted; this is the same situation caught two copies in.

Eleven columns appear in both queues and are treated as the contract. What each
repository adds past them is its own -- declared, not guessed -- because a
corpus that hosts images needs `item_id` and one that ranks chemical structures
needs `structures`, and neither should have to carry the other's column.

The adoption gate is the part worth sharing most. `ADOPTED` is a claim that the
pipeline actually reads the source under terms someone checked, so it requires a
verified redistribution class and the date it was verified. A row that says
`ADOPTED` with `UNVERIFIED` terms is the failure this file exists to make loud.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

__all__ = [
    "ACCESS",
    "CORE_COLUMNS",
    "Finding",
    "REDISTRIBUTION",
    "STATUS",
    "SourceQueueProfile",
    "USE",
    "check_queue",
    "read_queue",
    "summarise",
]

#: Present in both queues that exist, and the shape any new one should start from.
CORE_COLUMNS = (
    "source_id",
    "name",
    "closes_gap",
    "use",
    "redistribution",
    "access",
    "priority",
    "status",
    "verified_on",
    "url",
    "rationale",
)

#: The union of what both queues use today. `NONCOMMERCIAL` is the spelling kept
#: -- it is the one in the more recent queue, and picking either is better than
#: letting both stand, which is how the divergence started.
REDISTRIBUTION = ("CC0_OK", "ATTRIBUTION", "SHARE_ALIKE", "NONCOMMERCIAL", "RESTRICTED", "UNVERIFIED")
#: `NON_COMMERCIAL` is reported as a spelling of NONCOMMERCIAL rather than as an
#: unknown value, so the message says what to change instead of only that it is wrong.
REDISTRIBUTION_ALIASES = {"NON_COMMERCIAL": "NONCOMMERCIAL"}

STATUS = ("CANDIDATE", "EVALUATING", "ADOPTED", "BLOCKED", "REJECTED")
ACCESS = ("BULK", "API", "BOTH", "MANUAL", "UNVERIFIED")
USE = ("SEED", "CURATE_ONLY", "REFERENCE", "LINK_ONLY")

#: Terms under which an *adopted* source must not be copied into the repository.
#: A candidate may intend to seed before anyone has read its licence; that is
#: what verification is for.
_NO_SEED = {"UNVERIFIED", "RESTRICTED", "NONCOMMERCIAL"}


@dataclass(frozen=True)
class Finding:
    code: str
    detail: str
    row: int | None = None
    source_id: str = ""

    def __str__(self) -> str:
        where = f" ({self.source_id or f'row {self.row}'})" if (self.source_id or self.row) else ""
        return f"{self.code}: {self.detail}{where}"


@dataclass(frozen=True)
class SourceQueueProfile:
    """The per-repository half."""

    #: Columns this corpus adds past the shared eleven.
    extensions: tuple[str, ...] = ()
    #: Columns an ADOPTED row must have filled -- CellStructureMech requires a
    #: `script`, because a source nothing reads is not adopted.
    required_when_adopted: tuple[str, ...] = ()


def read_queue(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        columns = tuple(reader.fieldnames or ())
        return columns, [dict(row) for row in reader]


def _value(row: dict[str, str], column: str) -> str:
    return (row.get(column) or "").strip()


def check_queue(
    path: Path, profile: SourceQueueProfile | None = None
) -> list[Finding]:
    profile = profile or SourceQueueProfile()
    columns, rows = read_queue(path)
    findings: list[Finding] = []

    if not columns:
        return [Finding("EMPTY_QUEUE", "no header row")]

    missing = [c for c in CORE_COLUMNS if c not in columns]
    if missing:
        findings.append(
            Finding("MISSING_CORE_COLUMN", f"{missing} absent from the queue")
        )
    undeclared = [
        c for c in columns if c not in CORE_COLUMNS and c not in profile.extensions
    ]
    if undeclared:
        findings.append(
            Finding(
                "UNDECLARED_COLUMN",
                f"{undeclared} is neither a shared column nor a declared "
                f"extension of this repository's queue",
            )
        )

    seen: dict[str, int] = {}
    for number, row in enumerate(rows, start=1):
        source_id = _value(row, "source_id")
        if not source_id:
            findings.append(Finding("MISSING_SOURCE_ID", "row has no source_id", row=number))
            continue
        first = seen.setdefault(source_id, number)
        if first != number:
            findings.append(
                Finding("DUPLICATE_SOURCE_ID", f"already at row {first}", row=number, source_id=source_id)
            )

        status = _value(row, "status").upper()
        redistribution = _value(row, "redistribution").upper()
        use = _value(row, "use").upper()
        access = _value(row, "access").upper()
        priority = _value(row, "priority")

        alias = REDISTRIBUTION_ALIASES.get(redistribution)
        if alias:
            findings.append(
                Finding(
                    "REDISTRIBUTION_SPELLING",
                    f"{redistribution!r} means {alias!r}; the fleet spells it "
                    f"{alias!r} so two queues can be compared",
                    source_id=source_id,
                )
            )
            redistribution = alias

        for label, value, allowed in (
            ("status", status, STATUS),
            ("redistribution", redistribution, REDISTRIBUTION),
            ("access", access, ACCESS),
            ("use", use, USE),
        ):
            if value and value not in allowed:
                findings.append(
                    Finding(
                        "UNKNOWN_VALUE",
                        f"{label}={value!r}; expected one of {list(allowed)}",
                        source_id=source_id,
                    )
                )

        if priority and priority not in {"1", "2", "3", "4", "5"}:
            findings.append(
                Finding("BAD_PRIORITY", f"priority={priority!r}", source_id=source_id)
            )

        verified_on = _value(row, "verified_on")
        if verified_on:
            try:
                dt.date.fromisoformat(verified_on[:10])
            except ValueError:
                findings.append(
                    Finding("BAD_VERIFIED_ON", f"{verified_on!r} is not a date", source_id=source_id)
                )

        # The adoption gate.
        if status == "ADOPTED":
            if redistribution == "UNVERIFIED":
                findings.append(
                    Finding(
                        "ADOPTED_BUT_UNVERIFIED",
                        "claims the pipeline reads this source, while its terms "
                        "have not been checked against the licence page",
                        source_id=source_id,
                    )
                )
            if not verified_on:
                findings.append(
                    Finding(
                        "ADOPTED_WITHOUT_A_DATE",
                        "no verified_on, so nothing records when the terms were read",
                        source_id=source_id,
                    )
                )
            for column in profile.required_when_adopted:
                if not _value(row, column):
                    findings.append(
                        Finding(
                            "ADOPTED_WITHOUT_" + column.upper(),
                            f"this repository requires {column} on an adopted source",
                            source_id=source_id,
                        )
                    )

        # Only once adopted. `use` on a candidate is an intention, and
        # "we would copy this if the licence allows" is the normal state before
        # anyone has read the licence: every SEED row with unverified terms in
        # both queues is CANDIDATE, EVALUATING or BLOCKED, and every adopted one
        # is already verified. Judging intent reported twelve correct rows.
        if status == "ADOPTED" and use == "SEED" and redistribution in _NO_SEED:
            findings.append(
                Finding(
                    "SEED_UNDER_TERMS_THAT_FORBID_IT",
                    f"use=SEED copies the source into this repository, and its "
                    f"terms are {redistribution}",
                    source_id=source_id,
                )
            )

    return findings


def summarise(findings: Sequence[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.code] = counts.get(finding.code, 0) + 1
    return counts
