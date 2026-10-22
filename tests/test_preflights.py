"""Grades /app/output/preflights.json against the gateway's own record of OPTIONS arrivals.

The artifact is only read as JSON; nothing the agent produced is executed. Requests are graded
in six groups of four workstations each; every group test reports how many of its requests
are answered wrongly.
"""
import json
import os
import stat

import pytest

ARTIFACT = "/app/output/preflights.json"
EXPECTED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expected.json")
MAX_BYTES = 64 * 1024 * 1024

with open(EXPECTED, encoding="utf-8") as _fh:
    _SEALED = json.load(_fh)
TRUTH = _SEALED["preflighted"]
GROUPS = _SEALED["groups"]


def _load_answer():
    st = os.lstat(ARTIFACT)
    assert stat.S_ISREG(st.st_mode), "the artifact must be a regular file"
    assert st.st_size <= MAX_BYTES, "the artifact is too large"
    with open(ARTIFACT, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert isinstance(doc, dict) and isinstance(doc.get("preflighted"), dict), \
        'expected an object with a "preflighted" object'
    return doc["preflighted"]


@pytest.fixture(scope="module")
def answer():
    return _load_answer()


def test_every_request_answered_with_a_boolean(answer):
    bad = [rid for rid in sorted(TRUTH) if not isinstance(answer.get(rid), bool)]
    assert not bad, f"{len(bad)} of {len(TRUTH)} requests missing or not true/false, first: {bad[:3]}"


def _group_test(group):
    def test(answer):
        rids = GROUPS[group]
        wrong = [rid for rid in rids if answer.get(rid) is not TRUTH[rid]]
        assert not wrong, f"{len(wrong)} of {len(rids)} facts wrong, first: {wrong[:3]}"
    return test


# one test per group of four workstations, in order of first appearance in the API log
for _g in sorted(GROUPS, key=int):
    _lo = 4 * int(_g) - 3
    globals()[f"test_workstations_{_lo:02d}_to_{_lo + 3:02d}"] = _group_test(_g)
