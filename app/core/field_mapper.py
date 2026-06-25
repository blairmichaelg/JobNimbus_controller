"""
Bi-directional custom field mapper for JobNimbus.

Translates obfuscated CRM field keys (e.g., cf_string_1, cf_date_1)
to human-readable keys (e.g., date_of_loss, claim_number) and vice versa.

This translation layer is critical because:
- The LLM needs human-readable field names to reason about the data
- Outbound PUT requests to JobNimbus require the obfuscated keys
- The mapping must be maintained as custom fields are added/renamed
"""

import structlog

logger = structlog.get_logger("app.core.field_mapper")


# Hardcoded mapping for Phase 4 (can be moved to a config file or DB later)
DEFAULT_MAPPING = {
    "cf_string_1": "insurance_company",
    "cf_string_2": "claim_number",
    "cf_date_1": "date_of_loss",
    "cf_number_1": "deductible_amount",
    "cf_number_2": "rcv",
    "cf_number_3": "acv",
    "cf_string_3": "adjuster_name_phone",
    "cf_boolean_1": "contract_signed",
    "cf_string_4": "decking_condition",
    "cf_string_5": "shingle_manufacturer",
    "cf_string_6": "roof_age",
    "cf_string_7": "shingle_color",
    "cf_string_8": "roof_type",
    "cf_boolean_2": "inspection_completed",
    "cf_string_9": "gate_code",
    "cf_string_10": "damage_type",
    "cf_boolean_3": "gated_community",
    "cf_number_4": "total_squares",
    "cf_string_11": "roof_pitch",
    "cf_string_12": "eagleview_hover_order_id",
    "cf_string_13": "restoration_ai_link"
}


class FieldMapper:
    """
    Bi-directional dictionary for JobNimbus custom field translation.
    """

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        """
        Initialize the mapper.

        Args:
            mapping: A dict mapping obfuscated keys to human-readable keys.
                     If None, uses DEFAULT_MAPPING.
        """
        self._obfuscated_to_readable = mapping or DEFAULT_MAPPING
        self._readable_to_obfuscated = {
            v: k for k, v in self._obfuscated_to_readable.items()
        }
        logger.info(
            "field_mapper_initialized", mapping_count=len(self._obfuscated_to_readable)
        )

    def to_human(self, payload: dict) -> dict:
        """
        Translate obfuscated field keys to human-readable keys.

        Iterates over the payload. If a key is found in the mapping, it
        is replaced with the human-readable key. Unmapped keys are left intact.
        """
        translated = {}
        for key, value in payload.items():
            if key in self._obfuscated_to_readable:
                human_key = self._obfuscated_to_readable[key]
                translated[human_key] = value
            else:
                translated[key] = value

        # Log if any translation occurred
        if any(k in self._obfuscated_to_readable for k in payload):
            logger.debug(
                "payload_translated_to_human",
                keys_mapped=len(translated)
                - len(payload)
                + sum(1 for k in payload if k in self._obfuscated_to_readable),
            )

        return translated

    def to_api(self, payload: dict) -> dict:
        """
        Translate human-readable field keys back to obfuscated keys.

        Iterates over the payload. If a key is found in the reverse mapping,
        it is replaced with the obfuscated key. Unmapped keys are left intact.
        """
        translated = {}
        for key, value in payload.items():
            if key in self._readable_to_obfuscated:
                api_key = self._readable_to_obfuscated[key]
                translated[api_key] = value
            else:
                translated[key] = value

        # Log if any translation occurred
        if any(k in self._readable_to_obfuscated for k in payload):
            logger.debug("payload_translated_to_api")

        return translated
