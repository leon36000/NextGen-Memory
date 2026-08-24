from __future__ import annotations

import nextgen_memory
from nextgen_memory.policy_promotion_gate import (
    AdvisoryPolicyPromotionGate,
    PairedPolicyEvidence,
    PolicyIdentity,
    PolicyOperationalReadiness,
    PolicyPromotionDecision,
    PolicyPromotionGateConfig,
    PolicyPromotionReason,
    PolicyPromotionRecord,
    PolicyPromotionRequest,
    PolicyPromotionValidationError,
)


def test_policy_promotion_gate_contract_is_exported_from_package_root() -> None:
    expected = {
        "AdvisoryPolicyPromotionGate": AdvisoryPolicyPromotionGate,
        "PairedPolicyEvidence": PairedPolicyEvidence,
        "PolicyIdentity": PolicyIdentity,
        "PolicyOperationalReadiness": PolicyOperationalReadiness,
        "PolicyPromotionDecision": PolicyPromotionDecision,
        "PolicyPromotionGateConfig": PolicyPromotionGateConfig,
        "PolicyPromotionReason": PolicyPromotionReason,
        "PolicyPromotionRecord": PolicyPromotionRecord,
        "PolicyPromotionRequest": PolicyPromotionRequest,
        "PolicyPromotionValidationError": PolicyPromotionValidationError,
    }

    for name, value in expected.items():
        assert getattr(nextgen_memory, name) is value
        assert name in nextgen_memory.__all__
