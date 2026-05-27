# Use Cases & Industry Applications

## What Problem Does This Solve?

When processing recurring document types (invoices, forms, applications), every document is extracted from scratch. The OCR system has no memory of where fields appeared on the last 1,000 identical forms. This leads to:

- Wasted compute re-discovering field positions every time
- No validation that fields are where they should be
- No automatic detection of form version changes or tampering
- Manual template configuration for each document type
- No visibility into template health or processing pipeline quality
- No proactive alerting when document layouts change

`textract-field-memory` solves this by learning field positions automatically, monitoring template health over time, and providing observability features for document processing pipelines.

## Template Identification (Clustering) — Built-In

A common question: "Does clustering need to be added?" No — it's already a core feature.

When processing documents at scale, you encounter many layout variants:
- Invoice from Vendor A vs Invoice from Vendor B
- Employment Form v1 vs Employment Form v2
- Tax forms, contracts, receipts — all different layouts

Template identification answers: **"Have I seen this type of document before?"**

When you call `memory.record(document)` without specifying a `template_id`:

1. The system loads all stored templates
2. Scores the document against each using a combined metric:
   `combined_score = 0.6 × structural_similarity + 0.4 × spatial_similarity`
3. If best score ≥ 0.7 → merges into that template (same cluster)
4. If no match → creates a new template (new cluster)

```python
from field_memory import TemplateMemory

memory = TemplateMemory()

# Feed documents without specifying template_id — clustering is automatic
memory.record(invoice_vendor_a_doc_1)  # Creates template: "invoice-number-date-a3f2b1c4"
memory.record(invoice_vendor_a_doc_2)  # Matches & merges into same template
memory.record(employment_form_doc_1)   # No match → creates new template: "name-ssn-address-7e4d9f01"
memory.record(invoice_vendor_a_doc_3)  # Matches invoice template again

# Check what templates exist
print(memory.list_templates())
# → ["invoice-number-date-a3f2b1c4", "name-ssn-address-7e4d9f01"]

# Identify an unknown document
match = memory.identify_template(new_document)
if match:
    print(f"Recognized as: {match.template_id} (score={match.similarity_score:.2f})")
else:
    print("Unknown document type — route to manual review")
```

This enables spatial field lookup, drift detection, and extraction validation — all without manual template configuration.

---

## Industry Context: Adaptive Zonal OCR

Traditional Zonal OCR (offered by Nanonets, Klippa, Docsumo, Klearstack) requires manual zone definition — someone draws boxes on a template to define where fields are. This library does it automatically: it learns zones from processed documents and refines them over time.

Sources:
- [Nanonets: Zonal OCR explained](https://nanonets.com/blog/zonal-ocr/)
- [Klippa: Zonal OCR](https://www.klippa.com/en/blog/information/zonal-ocr/)
- [Lido: What Is Zonal OCR](https://lido.app/blog/what-is-zonal-ocr)

## Use Cases

### 1. Insurance Claims Processing

Insurance companies process thousands of claim forms daily. Same form type, same field positions.

**How it helps:**
- After training on 10 claims, the system knows "Claim Number" is always at position (0.60, 0.05) and "Policy Holder" at (0.05, 0.12)
- Anomaly detection catches fraudulently modified forms where fields have been moved
- Auto-identifies claim type (auto, health, property) by spatial layout
- Drift detection alerts when an insurer updates their claim form layout
- Batch processing handles daily claim volumes in a single call

**Metrics:** Zonal extraction reduces document handling time by 30% and data entry errors by 25% in financial services. Source: [Docsumo](https://docsumo.com/glossary/zonal-ocr)

---

### 2. Banking & Financial Services

Banks process loan applications, account opening forms, and KYC documents at scale.

**How it helps:**
- Validates that "Account Number" and "Signature" fields are in expected positions (compliance requirement)
- Detects when a form version changes (spatial scores drop across all documents)
- Routes documents to correct processing pipeline by spatial layout
- Template health reports provide audit evidence for compliance teams
- Field stability scores identify which fields are reliable vs. unreliable for automated processing

---

### 3. Invoice Processing at Scale

Companies receiving invoices from 50+ vendors, each with a different layout.

**How it helps:**
- Auto-learns one template per vendor after 5-10 invoices
- New invoices auto-route to the correct extraction pipeline without manual classification
- Flags invoices from unknown vendors (no template match) for manual review
- Detects vendor form changes (template drift)
- System-wide dashboard shows health across all vendor templates at a glance
- Batch processing handles daily invoice volumes efficiently

**Metrics:** Zone-based extraction improves processing speed by up to 90%. Source: [Klippa](https://www.klippa.com/en/blog/information/zonal-ocr/)

---

### 4. Healthcare & Pharma

Patient intake forms, lab reports, prescription forms — all highly structured, recurring templates.

**How it helps:**
- Validates that "Patient Name" and "DOB" are in expected positions (critical for compliance)
- Detects when a lab changes their report format
- Ensures correct field-to-value mapping when multiple similar fields exist (e.g., "Patient Address" vs "Provider Address")
- Confidence decay ensures templates adapt when labs gradually update their forms
- Export/import enables sharing templates between hospital systems

---

### 5. Legal Contract Management

Contract review requires linking every extraction to its exact source location.

**How it helps:**
- Provides spatial provenance for every extracted field (page number, bounding box, confidence)
- Detects when contract templates change between versions
- Validates that signature blocks, dates, and party names are in expected positions
- Field stability scoring identifies which contract fields are reliably positioned vs. variable

**Context:** [Ironclad's research](https://ironcladapp.com/resources/articles/grounding-systems) shows legal AI needs "grounding" — linking extractions to exact source locations with bounding boxes. This library provides that spatial grounding layer.

---

### 6. Logistics & Shipping

Bills of lading, customs declarations, shipping labels — high volume, predictable layouts.

**How it helps:**
- Fast extraction without full-page OCR on every document
- Auto-identifies document type (BOL vs customs form vs packing slip)
- Validates that critical fields (weight, destination, hazmat codes) are in expected positions
- Batch processing handles high-volume shipping document flows

---

### 7. Government & Public Sector

Tax forms, permit applications, census forms — millions of identical templates processed annually.

**How it helps:**
- Eliminates redundant processing of known template types
- Detects form version changes when government agencies update their forms
- Validates submissions against expected spatial layout
- System-wide analytics provide oversight across all form types in the pipeline

---

### 8. Reducing LLM/Bedrock API Costs

When using LLMs (Amazon Bedrock, OpenAI) for field extraction on top of OCR.

**How it helps:**
- If spatial memory confirms a field is at its expected position with high confidence, skip the LLM call and use the OCR result directly
- At $0.003–0.01 per field per LLM call, this saves real money at scale
- Example: 100 documents × 12 fields × $0.005 = $6/batch. If spatial memory handles 60% of fields, saves $3.60/batch
- Template health grades tell you which templates are mature enough to skip LLM calls
- Field stability scores identify which specific fields can be trusted without LLM verification

---

### 9. Document Version Detection & Change Management

When form templates get redesigned (fields move, new fields added).

**How it helps:**
- Drift detection proactively alerts when a template is changing
- Per-field drift scores pinpoint exactly which fields moved
- New fields and missing fields are tracked separately from positional drift
- Confidence decay ensures the template gradually adapts to the new layout
- Spatial scores drop automatically when a template changes
- Tracks template evolution over time (sample_count, updated_at)

---

### 10. Fraud & Tampering Detection

Detecting when someone edits a PDF and moves fields to hide modifications.

**How it helps:**
- If "Total Amount" appears at (0.70, 0.85) instead of its normal (0.60, 0.80), spatial_score drops and `within_expected_region=False`
- Financial compliance teams can flag documents where field positions deviate from the template
- Provides auditable spatial confidence scores for each extraction
- Drift detection distinguishes between gradual template evolution and sudden suspicious changes

---

### 11. Production Pipeline Monitoring

Operations teams managing document processing pipelines at scale.

**How it helps:**
- System-wide dashboard shows total templates, documents processed, and health distribution
- Templates ranked by activity help identify which document types dominate the pipeline
- Health grades provide at-a-glance quality assessment without diving into individual templates
- Field stability scores surface unreliable fields before they cause downstream errors
- Drift detection provides early warning when upstream document sources change

```python
# Daily health check
summary = memory.get_system_summary()
print(f"Pipeline health: {summary.mean_template_health_grade}")
print(f"Templates: {summary.total_template_count}")
print(f"Documents processed: {summary.total_documents_processed}")

# Alert on unhealthy templates
for template in summary.templates_ranked:
    if template["health_grade"] == "insufficient":
        alert(f"Template {template['template_id']} needs attention")
```

---

### 12. Multi-Environment Template Management

Teams running document processing across dev, staging, and production environments.

**How it helps:**
- Export templates from production as JSON or CSV
- Import into staging/dev for testing without retraining
- CSV export enables non-technical stakeholders to review template data in spreadsheets
- Round-trip guarantee ensures no data loss during transfer

```python
# Export from production
prod_data = prod_memory.export_template("invoice-vendor-a", fmt="json")

# Import into staging
staging_memory.import_template(prod_data)

# Export for business review
csv_report = prod_memory.export_template("invoice-vendor-a", fmt="csv")
```

---

### 13. High-Volume Batch Ingestion

Processing large document backlogs or daily batch uploads.

**How it helps:**
- Process hundreds of documents in a single call
- Automatic error isolation — one bad document doesn't stop the batch
- Per-document results with template assignment and status
- Supports both explicit template assignment and auto-identification per document

```python
# Process daily batch
result = memory.batch_record(daily_documents, template_id="claim-form")
print(f"Success: {result.success_count}/{result.total_count}")

# Handle failures
for item in result.results:
    if item.status == "failed":
        route_to_manual_review(daily_documents[item.index], item.error)
```

---

### 14. Heterogeneous Document Routing & Layout Discovery

When your pipeline receives documents in the same category (e.g., "invoices") but with wildly different layouts from different sources.

**The problem:** Traditional spatial memory assumes documents share a layout. But if you receive invoices from 50 vendors, each with a different design, there's no single spatial pattern to learn across all of them.

**How this library still helps:**
- Answers the question "have I seen this layout before?" instantly via `identify_template()`
- Auto-discovers sub-types within a broad category — you feed in "invoices" and the library finds 12 distinct layout groups
- Routes known layouts to fast spatial extraction, unknown layouts to expensive LLM/human review
- Reduces expensive processing over time as more layouts become "known"
- Provides a natural clustering of documents by structural similarity without any manual configuration

**The pattern:**

```python
from field_memory import TemplateMemory

memory = TemplateMemory()

def process_document(document, category="invoice"):
    """Smart routing based on layout recognition."""
    match = memory.identify_template(document)

    if match is not None:
        # Known layout — fast path using spatial memory
        print(f"Recognized: {match.template_id} (score={match.similarity_score:.2f})")
        fields = memory.locate(document, "Total Amount")
        if fields and fields[0].within_expected_region:
            return extract_with_spatial_confidence(document, fields)

    # Unknown layout — expensive path, but learn it for next time
    template_id = memory.record(document)
    print(f"New layout discovered: {template_id}")
    return route_to_llm_extraction(document)

# Over time:
# Day 1: 50 documents → 50 LLM calls (all unknown)
# Day 30: 50 documents → 8 LLM calls (42 recognized from prior layouts)
# Day 90: 50 documents → 2 LLM calls (48 recognized)
```

**Key insight:** The library doesn't need documents to be identical — it needs them to be *recognizable*. After seeing 3-5 documents from the same vendor, it recognizes that vendor's layout. The heterogeneous stream naturally partitions itself into homogeneous clusters.

**Metrics:**
- In a pipeline with 50 vendor layouts, after 1 month of learning, 80-90% of documents match a known template
- Each recognized document saves one LLM call ($0.003–0.01 per field)
- Unknown layouts are flagged immediately rather than silently producing bad extractions

---

### 15. Audit Trail — Document Processing History

Track which documents were processed, when, and into which template cluster. Useful for compliance reporting, debugging extraction issues, and understanding pipeline throughput.

**How it helps:**
- Full processing history for any document across all templates
- Trace a document's journey through re-classification or re-processing
- Compliance teams can demonstrate exactly when a document was ingested
- Debugging: if a field extraction looks wrong, check which template the document was assigned to and when

```python
from field_memory import TemplateMemory

memory = TemplateMemory(store_path="/tmp/templates")

# Record documents with explicit IDs for traceability
memory.record(invoice_doc, doc_id="INV-2024-0042")
memory.record(claim_doc, doc_id="CLM-2024-1001")

# Later: trace a document's full processing history
history = memory.get_document_history("INV-2024-0042")
for record in history:
    print(f"  Template: {record.template_id}")
    print(f"  Recorded: {record.recorded_at}")
    print(f"  Confidence: {record.confidence:.2f}")
```

---

### 16. Privacy & GDPR Cleanup

Remove specific document records from clusters when privacy deletion requests come in. Supports "right to be forgotten" compliance without disrupting the rest of the cluster.

**How it helps:**
- Targeted removal of a single document's tracking records from any cluster
- No need to rebuild or delete the entire template — only the specific document reference is removed
- Subsequent queries (cluster members, document history) no longer return the deleted record
- Audit-friendly: removal returns True/False so you can log whether the record existed

```python
from field_memory import TemplateMemory

memory = TemplateMemory(store_path="/tmp/templates")

# Privacy request: remove all traces of a specific document
doc_id_to_forget = "INV-2024-0042"

# Find which clusters this document belongs to
history = memory.get_document_history(doc_id_to_forget)
for record in history:
    removed = memory.remove_cluster_member(record.template_id, doc_id_to_forget)
    if removed:
        print(f"Removed from cluster: {record.template_id}")

# Verify: document no longer appears in history
assert memory.get_document_history(doc_id_to_forget) == []
```

---

### 17. Cluster Health Monitoring

Monitor cluster quality over time by checking statistics. Detect clusters with low confidence scores that might indicate template drift, poor training data, or documents being assigned to the wrong template.

**How it helps:**
- Mean confidence score reveals overall cluster quality — low values suggest misclassified documents
- Min confidence highlights the worst-fit document in a cluster
- Member count tracks cluster growth over time
- Oldest/newest timestamps show cluster activity and staleness
- Enables proactive alerting before extraction quality degrades

```python
from field_memory import TemplateMemory

memory = TemplateMemory(store_path="/tmp/templates")

# Check health of a specific cluster
stats = memory.get_cluster_stats("invoice-vendor-a")
print(f"Members: {stats.member_count}")
print(f"Confidence: mean={stats.mean_confidence:.2f}, "
      f"min={stats.min_confidence:.2f}, max={stats.max_confidence:.2f}")
print(f"Active: {stats.oldest_record} → {stats.newest_record}")

# Alert on low-quality clusters
if stats.mean_confidence < 0.75:
    print(f"WARNING: Cluster 'invoice-vendor-a' has low mean confidence "
          f"({stats.mean_confidence:.2f}). Consider retraining or splitting.")

if stats.min_confidence < 0.5:
    print(f"WARNING: Cluster has poorly-matched documents. "
          f"Review members with low confidence scores.")
```

---

### 18. Document Re-processing Tracking

Track when documents get re-processed and assigned to different templates over time. Useful for understanding how classification improves, detecting oscillating assignments, and ensuring re-processing produces better results.

**How it helps:**
- See all template assignments for a single document across its lifecycle
- Detect re-classification: a document moving from one template to another after retraining
- Identify oscillating documents that keep switching clusters (indicates ambiguous layout)
- Compare confidence scores across assignments to verify improvement

```python
from field_memory import TemplateMemory

memory = TemplateMemory(store_path="/tmp/templates")

# Document processed multiple times (e.g., after pipeline improvements)
memory.record(document, doc_id="DOC-2024-500")
# ... later, after retraining templates ...
memory.record(document, doc_id="DOC-2024-500")

# Check all assignments for this document
history = memory.get_document_history("DOC-2024-500")
print(f"Document processed {len(history)} time(s):")
for i, record in enumerate(history, 1):
    print(f"  {i}. Template: {record.template_id}, "
          f"Confidence: {record.confidence:.2f}, "
          f"At: {record.recorded_at}")

# Detect if document changed clusters (re-classification)
templates_seen = set(r.template_id for r in history)
if len(templates_seen) > 1:
    print(f"Document was re-classified across templates: {templates_seen}")
```

---

## Differentiator vs Existing Solutions

| Feature | Traditional Zonal OCR | textract-field-memory |
|---|---|---|
| Zone definition | Manual (draw boxes on template) | Automatic (learns from documents) |
| Template updates | Manual reconfiguration required | Self-refining (weighted averaging + decay) |
| New template types | Requires manual setup | Auto-detected and created |
| Anomaly detection | Not available | Built-in (spatial score drops) |
| Drift detection | Not available | Built-in (per-field drift scoring) |
| Template health monitoring | Not available | Built-in (health grades, stability scores) |
| Batch processing | Platform-dependent | Built-in with error isolation |
| Export/Import | Platform-specific | JSON and CSV, round-trip guaranteed |
| System-wide analytics | Separate monitoring tools | Built-in dashboard |
| Dependencies | Proprietary SaaS platform | Zero (pure Python stdlib) |
| Cost | Monthly SaaS subscription | Free, open-source |
| Integration | Platform-specific APIs | Works with any OCR output |
| Learning curve | Platform training required | 3 lines of code |

## Academic Foundation

The approach is grounded in research on spatial document understanding:

- [Spatial Dependency Parsing for Semi-Structured Document Information Extraction](https://aclanthology.org/2021.findings-acl.28/) (ACL 2021) — confirms spatial position is a strong signal for document field extraction
- [Spatially-Grounded Document Retrieval](https://arxiv.org/abs/2512.02660) — shows spatial grounding reduces context tokens by 28.8% compared to returning all OCR regions
- [AWS Intelligent Document Processing guidance](https://aws.amazon.com/solutions/guidance/intelligent-document-processing-on-aws3/) — the broader IDP architecture this library fits into

## Quick Integration

```python
from field_memory import TemplateMemory

memory = TemplateMemory()

# Train (once per document type, 5-10 documents)
memory.record(document, template_id="invoice-vendor-a")

# Use (every subsequent document)
doc_type = memory.identify_template(new_doc)       # → "invoice-vendor-a"
matches = memory.locate(new_doc, "Invoice Number") # → spatial + name scoring
if matches[0].within_expected_region:
    # High confidence — use OCR result directly
    value = matches[0].key_value.value
else:
    # Anomaly — flag for review or fall back to LLM
    flag_for_review(new_doc, "Invoice Number")

# Monitor (periodic health checks)
stats = memory.get_stats("invoice-vendor-a")
drift = memory.detect_drift(new_doc, "invoice-vendor-a")
summary = memory.get_system_summary()
```
