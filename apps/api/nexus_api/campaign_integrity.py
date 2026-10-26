"""Manifest interpretation is server-side and verified again before runtime creation."""

from uuid import UUID

from nexus_api.campaign_schemas import AttackCorpus, BluePolicy, CampaignBudget, ModelManifest
from nexus_api.models import Comparison
from nexus_api.versioning import canonical, sha


def verify_campaign(db, evaluation, contents):
    profile = evaluation.manifest.get("security_profile", "STANDARD")
    if profile not in {"STANDARD", "REDUCED_INTERFERENCE"} or (
        profile == "REDUCED_INTERFERENCE" and evaluation.execution_mode != "isolated_docker"
    ):
        raise ValueError("INVALID_SECURITY_PROFILE")
    corpus = AttackCorpus.model_validate(contents[0])
    BluePolicy.model_validate(contents[1])
    model = ModelManifest.model_validate(contents[2])
    budget = CampaignBudget.model_validate(evaluation.manifest["budget"])
    binding = evaluation.manifest["campaign"]
    if (
        set(binding) != {"schema_version", "arm", "comparison_id", "scoring_version"}
        or binding["schema_version"] != "campaign-v1"
        or binding["arm"] not in {"baseline", "defended"}
        or binding["scoring_version"]
        != (
            "deterministic-v2"
            if corpus.schema_version == "campaign-corpus-v2"
            else "deterministic-v1"
        )
    ):
        raise ValueError("CAMPAIGN_BINDING_MISMATCH")
    if evaluation.manifest.get("model") != model.model_dump(mode="json"):
        raise ValueError("MODEL_MANIFEST_MISMATCH")
    if (
        model.provider == "local" and evaluation.execution_mode != "isolated_docker"
    ) or model.isolation != (
        "isolated_container" if evaluation.execution_mode == "isolated_docker" else "in_process"
    ):
        raise ValueError("PROVIDER_ISOLATION_MISMATCH")
    if budget.model_timeout_ms > budget.case_timeout_ms or budget.max_messages < 8 * min(
        budget.max_cases, len(corpus.cases)
    ):
        raise ValueError("INVALID_CAMPAIGN_BUDGET")
    comparison_id = binding["comparison_id"]
    if comparison_id is None:
        if binding["arm"] != "defended":
            raise ValueError("BASELINE_REQUIRES_APPROVED_COMPARISON")
    else:
        comparison = db.get(Comparison, UUID(comparison_id))
        if (
            comparison is None
            or comparison.owner_id != evaluation.owner_id
            or sha(canonical(comparison.manifest)) != comparison.manifest_digest
        ):
            raise ValueError("COMPARISON_BINDING_MISMATCH")
        expected_id = (
            comparison.baseline_id if binding["arm"] == "baseline" else comparison.defended_id
        )
        expected = comparison.manifest
        if (
            expected_id != evaluation.id
            or any(
                str(getattr(evaluation, field)) != expected[field]
                for field in (
                    "red_version_id",
                    "blue_version_id",
                    "model_version_id",
                    "flow_policy_version_id",
                )
            )
            or evaluation.manifest.get("security_profile", "STANDARD")
            != expected.get("security_profile", "STANDARD")
            or evaluation.manifest["budget"] != expected["budget"]
            or evaluation.manifest["model"] != expected["model"]
            or evaluation.manifest.get("runtime_images") != expected["runtime_images"]
        ):
            raise ValueError("COMPARISON_CONFIGURATION_MISMATCH")
    return contents
