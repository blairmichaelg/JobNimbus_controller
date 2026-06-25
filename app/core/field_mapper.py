"""
Bi-directional custom field mapper for JobNimbus.

Translates obfuscated CRM field keys (e.g., cf_string_1, cf_date_1)
to human-readable keys (e.g., date_of_loss, claim_number) and vice versa.

This translation layer is critical because:
- The LLM needs human-readable field names to reason about the data
- Outbound PUT requests to JobNimbus require the obfuscated keys
- The mapping must be maintained as custom fields are added/renamed
"""

import json
from pathlib import Path
import structlog

logger = structlog.get_logger("app.core.field_mapper")


def load_default_mapping() -> dict[str, str]:
    """Load the field mapping configuration from field_mapping.json."""
    try:
        # Assuming field_mapping.json is in the root directory
        config_path = Path(__file__).parent.parent.parent / "field_mapping.json"
        if config_path.exists():
            return json.loads(config_path.read_text())
        else:
            logger.warning("field_mapping_file_not_found", path=str(config_path))
            return {}
    except Exception as exc:
        logger.error("field_mapping_load_error", error=str(exc))
        return {}


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
        self._obfuscated_to_readable = mapping if mapping is not None else load_default_mapping()
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
