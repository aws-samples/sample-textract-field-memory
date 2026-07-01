# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Shared utility functions for the field_memory package."""

import re


def normalize_field_name(name: str) -> str:
    """Normalize field names for consistent matching.

    Strips trailing colons, punctuation, extra whitespace.
    Handles common OCR artifacts like trailing colons from form labels.

    Args:
        name: Raw field name (e.g., "Employee Name:", "  Invoice  Number  ")

    Returns:
        Normalized name (e.g., "Employee Name", "Invoice Number")
    """
    # Strip trailing colons and common punctuation
    name = re.sub(r"[:\-\.\?\*]+$", "", name)
    # Collapse multiple whitespace
    name = re.sub(r"\s+", " ", name)
    return name.strip()
