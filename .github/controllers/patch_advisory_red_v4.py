from __future__ import annotations

import sys
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_advisory_red_v4.py TEST_FILE")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")

    source = replace_once(
        source,
        '''def identity(
    *,
    version: str = "control-v1",
    fingerprint: str = CURRENT_FP,
    source_sha: str = CURRENT_SHA,
) -> PolicyIdentity:
    return PolicyIdentity(
        policy_version=version,
        policy_fingerprint=fingerprint,
        source_sha=source_sha,
    )
''',
        '''def identity(
    *,
    version: str = "control-v1",
    fingerprint: str = CURRENT_FP,
    source_sha: str = CURRENT_SHA,
    **overrides: object,
) -> PolicyIdentity:
    values: dict[str, object] = {
        "policy_version": version,
        "policy_fingerprint": fingerprint,
        "source_sha": source_sha,
    }
    values.update(overrides)
    return PolicyIdentity(**values)  # type: ignore[arg-type]
''',
        "identity helper",
    )

    source = replace_once(
        source,
        "request(evaluation=paired_evidence(registry_completed_trial_count=23)),",
        '''request(
    evaluation=paired_evidence(
        registry_completed_trial_count=23,
        registry_active_count=1,
    )
),''',
        "registry/evaluation mismatch fixture",
    )

    source = replace_once(
        source,
        "request(evaluation=paired_evidence(mean_score_effect=-0.001)),",
        '''request(
    evaluation=paired_evidence(
        mean_score_effect=-0.001,
        score_confidence_lower_bound=-0.01,
        score_confidence_upper_bound=0.01,
    )
),''',
        "negative-effect fixture",
    )

    source = replace_once(
        source,
        "request(evaluation=paired_evidence(matched_pair_count=19)),",
        '''request(
    evaluation=paired_evidence(
        matched_pair_count=19,
        registry_pair_count=19,
        registry_completed_trial_count=19,
    )
),''',
        "insufficient-pairs fixture",
    )

    path.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
