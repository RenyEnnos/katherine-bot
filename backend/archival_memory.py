import re
import hashlib
import math
from dataclasses import dataclass
from typing import List

ARCHIVAL_SCHEMA_VERSION = 1
EXTRACTOR_VERSION = 1

class ArchivalValidationError(Exception):
    """Domain exception for failed validation checks on archival memories."""
    pass

class ArchivalDuplicateError(Exception):
    """Exception raised when an archival extraction for a turn already exists (uniqueness violation)."""
    pass

@dataclass(frozen=True)
class PersistedTurnRef:
    user_id: str
    source_chat_log_id: int
    assistant_chat_log_id: int

@dataclass(frozen=True)
class ArchivalFact:
    content: str
    importance: float
    tags: List[str]

@dataclass(frozen=True)
class ArchivalExtractionEnvelope:
    facts: List[ArchivalFact]
    schema_version: int = ARCHIVAL_SCHEMA_VERSION
    extractor_version: int = EXTRACTOR_VERSION

def compute_idempotency_key(user_id: str, source_chat_log_id: int, extractor_version: int) -> str:
    input_str = f"{user_id}:{source_chat_log_id}:{extractor_version}"
    return hashlib.sha256(input_str.encode("utf-8")).hexdigest()

def parse_archival_extraction(raw_dict: dict) -> ArchivalExtractionEnvelope:
    if not isinstance(raw_dict, dict):
        raise ArchivalValidationError("Envelope must be a dictionary.")

    # Check for unknown keys in raw_dict
    allowed_keys = {"facts", "schema_version", "extractor_version"}
    if set(raw_dict.keys()) - allowed_keys:
        raise ArchivalValidationError("Unknown keys in envelope.")

    schema_version = raw_dict.get("schema_version", ARCHIVAL_SCHEMA_VERSION)
    extractor_version = raw_dict.get("extractor_version", EXTRACTOR_VERSION)

    # Versions must match exact int values
    if type(schema_version) is not int or schema_version != ARCHIVAL_SCHEMA_VERSION:
        raise ArchivalValidationError("Invalid or unsupported schema version.")
    if type(extractor_version) is not int or extractor_version != EXTRACTOR_VERSION:
        raise ArchivalValidationError("Invalid or unsupported extractor version.")

    facts_list = raw_dict.get("facts")
    if not isinstance(facts_list, list):
        raise ArchivalValidationError("Facts must be a list.")
    if len(facts_list) > 5:
        raise ArchivalValidationError("At most 5 facts are allowed per turn.")

    parsed_facts = []
    for fact_dict in facts_list:
        if not isinstance(fact_dict, dict):
            raise ArchivalValidationError("Fact must be a dictionary.")
        
        # Unknown keys in fact
        fact_keys = {"content", "importance", "tags"}
        if set(fact_dict.keys()) - fact_keys:
            raise ArchivalValidationError("Unknown keys in fact dictionary.")

        content = fact_dict.get("content")
        importance = fact_dict.get("importance")
        tags = fact_dict.get("tags")

        if content is None or not isinstance(content, str):
            raise ArchivalValidationError("Fact content must be a non-empty string.")
        
        trimmed_content = content.strip()
        if not trimmed_content:
            raise ArchivalValidationError("Fact content cannot be empty after trim.")
        if len(trimmed_content) > 500:
            raise ArchivalValidationError("Fact content exceeds maximum of 500 characters.")

        # Rejects boolean types
        if isinstance(importance, bool) or not isinstance(importance, (int, float)):
            raise ArchivalValidationError("Fact importance must be a float.")
        
        if not math.isfinite(importance) or not (0.0 <= importance <= 1.0):
            raise ArchivalValidationError("Fact importance must be finite and between 0.0 and 1.0.")

        if not isinstance(tags, list):
            raise ArchivalValidationError("Tags must be a list of strings.")
        if len(tags) > 8:
            raise ArchivalValidationError("At most 8 tags are allowed per fact.")

        seen_tags = {}
        deduplicated_tags = []
        for tag in tags:
            if not isinstance(tag, str):
                raise ArchivalValidationError("Tag must be a string.")
            norm_tag = tag.strip().lower()
            if not norm_tag:
                raise ArchivalValidationError("Tag cannot be empty.")
            if len(norm_tag) > 32:
                raise ArchivalValidationError("Tag exceeds 32 characters.")
            if not re.match(r"^[a-z0-9][a-z0-9_-]*$", norm_tag):
                raise ArchivalValidationError(f"Tag '{norm_tag}' does not match pattern [a-z0-9][a-z0-9_-]*.")
            
            if norm_tag not in seen_tags:
                seen_tags[norm_tag] = True
                deduplicated_tags.append(norm_tag)

        parsed_facts.append(
            ArchivalFact(
                content=trimmed_content,
                importance=float(importance),
                tags=deduplicated_tags
            )
        )

    return ArchivalExtractionEnvelope(
        facts=parsed_facts,
        schema_version=schema_version,
        extractor_version=extractor_version
    )
