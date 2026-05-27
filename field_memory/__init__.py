# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""textract-field-memory: Spatial field location memory for document processing.

Records WHERE fields appear on document templates and uses that knowledge
to validate extractions, identify document types, and detect anomalies.
"""

from field_memory.analytics import (
    SystemSummary,
    TemplateAnalytics,
    TemplateHealthReport,
)
from field_memory.batch import BatchItemResult, BatchProcessor, BatchResult
from field_memory.cluster_models import ClusterData, ClusterStats, MembershipRecord
from field_memory.drift import DriftDetector, DriftReport, FieldDriftResult
from field_memory.export import TemplateExporter
from field_memory.facade import TemplateMemory
from field_memory.identifier import TemplateIdentifier, TemplateMatch
from field_memory.matcher import FieldMatch, SpatialMatcher
from field_memory.models import FieldLocationMap, FieldRegion
from field_memory.store import TemplateStore

__version__ = "0.1.0"

__all__ = [
    "TemplateMemory",
    "FieldLocationMap",
    "FieldRegion",
    "FieldMatch",
    "TemplateMatch",
    "TemplateStore",
    "SpatialMatcher",
    "TemplateIdentifier",
    "TemplateAnalytics",
    "TemplateHealthReport",
    "SystemSummary",
    "DriftDetector",
    "DriftReport",
    "FieldDriftResult",
    "BatchProcessor",
    "BatchResult",
    "BatchItemResult",
    "TemplateExporter",
    "MembershipRecord",
    "ClusterData",
    "ClusterStats",
]
