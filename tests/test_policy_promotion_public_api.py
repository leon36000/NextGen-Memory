from __future__ import annotations

from nextgen_memory.policy_promotion import (
    DeterministicPolicyPromotionGate,
    PolicyPromotionDecision,
    PolicyPromotionDisposition,
    PolicyPromotionEvidence,
    PolicyPromotionGateConfig,
    PolicyPromotionReason,
    PolicyPromotionSafeMetrics,
    PolicyPromotionValidationError,
    PolicyVerificationSignal,
    fingerprint_policy_promotion_config,
)

import nextgen_memory


def test_policy_promotion_contract_is_exported_from_package_root() -> None:
    expected = {
        "DeterministicPolicyPromotionGate": DeterministicPolicyPromotionGate,
        "PolicyPromotionDecision": PolicyPromotionDecision,
        "PolicyPromotionDisposition": PolicyPromotionDisposition,
        "PolicyPromotionEvidence": PolicyPromotionEvidence,
        "PolicyPromotionGateConfig": PolicyPromotionGateConfig,
        "PolicyPromotionReason": PolicyPromotionReason,
        "PolicyPromotionSafeMetrics": PolicyPromotionSafeMetrics,
        "PolicyPromotionValidationError": PolicyPromotionValidationError,
        "PolicyVerificationSignal": PolicyVerificationSignal,
        "fingerprint_policy_promotion_config": fingerprint_policy_promotion_config,
    }

    for name, value in expected.items():
        assert getattr(nextgen_memory, name) is value
        assert name in nextgen_memory.__all__
