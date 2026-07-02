# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
textract-field-memory — Interactive Dashboard
==============================================

A Streamlit dashboard for visualizing template health, field positions,
drift detection, cluster membership, document recording, field lookup,
template identification, and export/import.

Usage:
    pip install textract-field-memory[dashboard]
    streamlit run dashboard/app.py
"""

import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List

import plotly.graph_objects as go
import streamlit as st

from field_memory import TemplateMemory

# =============================================================================
# Mock document helpers (for demo mode)
# =============================================================================


@dataclass
class Word:
    text: str


@dataclass
class BBox:
    x: float
    y: float
    width: float
    height: float


@dataclass
class KeyValue:
    key: List[Word]
    bbox: BBox
    page: int
    confidence: float = 0.95


@dataclass
class Page:
    key_values: List[KeyValue]


@dataclass
class Document:
    pages: List[Page]


def make_employment_form(variation: float = 0.01) -> Document:
    """Generate a synthetic employment form."""

    def jitter(v):
        return max(
            0.001, min(0.95, v + random.uniform(-variation, variation))
        )  # nosec B311

    fields = [
        ("Employee Name", 0.05, 0.08, 0.35, 0.03),
        ("Date of Birth", 0.05, 0.14, 0.20, 0.03),
        ("SSN", 0.05, 0.20, 0.15, 0.03),
        ("Address", 0.05, 0.26, 0.45, 0.03),
        ("City", 0.05, 0.32, 0.20, 0.03),
        ("State", 0.30, 0.32, 0.10, 0.03),
        ("Zip Code", 0.45, 0.32, 0.12, 0.03),
        ("Phone Number", 0.05, 0.38, 0.20, 0.03),
        ("Email", 0.05, 0.44, 0.30, 0.03),
        ("Position Applied For", 0.05, 0.50, 0.30, 0.03),
        ("Start Date", 0.05, 0.56, 0.15, 0.03),
        ("Salary Expected", 0.30, 0.56, 0.15, 0.03),
    ]
    kvs = [
        KeyValue(
            key=[Word(w) for w in name.split()],
            bbox=BBox(jitter(x), jitter(y), w, h),
            page=1,
            confidence=random.uniform(0.88, 0.99),  # nosec B311
        )
        for name, x, y, w, h in fields
    ]
    return Document(pages=[Page(key_values=kvs)])


def make_invoice(variation: float = 0.01) -> Document:
    """Generate a synthetic invoice."""

    def jitter(v):
        return max(
            0.001, min(0.95, v + random.uniform(-variation, variation))
        )  # nosec B311

    fields = [
        ("Invoice Number", 0.60, 0.05, 0.20, 0.03),
        ("Invoice Date", 0.60, 0.10, 0.15, 0.03),
        ("Due Date", 0.60, 0.15, 0.15, 0.03),
        ("Bill To", 0.05, 0.20, 0.30, 0.03),
        ("Ship To", 0.45, 0.20, 0.30, 0.03),
        ("Subtotal", 0.60, 0.70, 0.15, 0.03),
        ("Tax", 0.60, 0.75, 0.15, 0.03),
        ("Total", 0.60, 0.80, 0.15, 0.03),
    ]
    kvs = [
        KeyValue(
            key=[Word(w) for w in name.split()],
            bbox=BBox(jitter(x), jitter(y), w, h),
            page=1,
            confidence=random.uniform(0.88, 0.99),  # nosec B311
        )
        for name, x, y, w, h in fields
    ]
    return Document(pages=[Page(key_values=kvs)])


def json_to_document(data: dict) -> Document:
    """Convert a JSON dictionary to a Document object for processing."""
    pages = []
    for page_data in data.get("pages", []):
        kvs = []
        for kv_data in page_data.get("key_values", []):
            key_words = [Word(text=w) for w in kv_data.get("key", "").split()]
            bbox = kv_data.get("bbox", {})
            kvs.append(
                KeyValue(
                    key=key_words,
                    bbox=BBox(
                        x=float(bbox.get("x", 0)),
                        y=float(bbox.get("y", 0)),
                        width=float(bbox.get("width", 0.1)),
                        height=float(bbox.get("height", 0.03)),
                    ),
                    page=int(kv_data.get("page", 1)),
                    confidence=float(kv_data.get("confidence", 0.95)),
                )
            )
        pages.append(Page(key_values=kvs))
    return Document(pages=pages)


# =============================================================================
# Dashboard Setup
# =============================================================================


def get_memory():
    """Get or create a TemplateMemory instance in session state.

    Supports FIELD_MEMORY_STORE environment variable for production use:
        FIELD_MEMORY_STORE=/path/to/templates streamlit run dashboard/app.py

    If not set, defaults to dashboard/store_path/ with auto-seeded demo data.
    """
    if "memory" not in st.session_state:
        # Use env var if set, otherwise default to local store_path
        env_store = os.environ.get("FIELD_MEMORY_STORE")
        if env_store:
            store_path = Path(env_store)
            store_path.mkdir(parents=True, exist_ok=True)
            st.session_state["using_production_store"] = True
        else:
            store_path = Path(__file__).parent / "store_path"
            store_path.mkdir(parents=True, exist_ok=True)
            st.session_state["using_production_store"] = False

        memory = TemplateMemory(
            store_path=store_path,
            similarity_threshold=0.5,
            decay_factor=0.95,
            drift_threshold=0.1,
        )
        # Seed with demo data if store is empty
        # Seed with demo data only if using default store and it's empty
        if (
            not st.session_state["using_production_store"]
            and not memory.list_templates()
        ):
            random.seed(42)
            for i in range(12):
                memory.record(
                    make_employment_form(variation=0.01),
                    template_id="employment-form",
                    doc_id=f"emp-{i+1:03d}",
                )
            for i in range(8):
                memory.record(
                    make_invoice(variation=0.01),
                    template_id="invoice",
                    doc_id=f"inv-{i+1:03d}",
                )
        st.session_state["memory"] = memory
    return st.session_state["memory"]


# =============================================================================
# Render Functions
# =============================================================================


def render_field_positions(memory, template_id):
    """Render field bounding boxes as a plotly figure."""
    template = memory.get_template(template_id)
    if template is None:
        st.warning(f"Template '{template_id}' not found.")
        return

    fig = go.Figure()
    colors = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
        "#aec7e8",
        "#ffbb78",
    ]

    for idx, (field_name, regions) in enumerate(template.fields.items()):
        color = colors[idx % len(colors)]
        for region in regions:
            bbox = region.bbox
            x0, y0 = bbox["x"], bbox["y"]
            x1, y1 = x0 + bbox["width"], y0 + bbox["height"]
            fig.add_shape(
                type="rect",
                x0=x0,
                y0=1 - y1,
                x1=x1,
                y1=1 - y0,
                line=dict(color=color, width=2),
                fillcolor=color,
                opacity=0.3,
            )
            fig.add_annotation(
                x=(x0 + x1) / 2,
                y=1 - y0 + 0.01,
                text=field_name,
                showarrow=False,
                font=dict(size=9, color=color),
            )

    fig.update_layout(
        title=f"Field Positions — {template_id}",
        xaxis=dict(range=[0, 1], title="X (normalized)"),
        yaxis=dict(range=[0, 1], title="Y (normalized)"),
        width=700,
        height=800,
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_health_dashboard(memory):
    """Render the system-wide health dashboard."""
    summary = memory.get_system_summary()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Templates", summary.total_template_count)
    col2.metric("Documents Processed", summary.total_documents_processed)
    col3.metric("Overall Health", summary.mean_template_health_grade.title())
    col4.metric("Most Active", summary.most_active_template or "None")

    if summary.templates_by_health_grade:
        st.subheader("Templates by Health Grade")
        grade_data = summary.templates_by_health_grade
        fig = go.Figure(
            data=[
                go.Bar(
                    x=list(grade_data.keys()),
                    y=list(grade_data.values()),
                    marker_color=[
                        (
                            "#2ca02c"
                            if g == "excellent"
                            else (
                                "#1f77b4"
                                if g == "good"
                                else "#ff7f0e" if g == "developing" else "#d62728"
                            )
                        )
                        for g in grade_data.keys()
                    ],
                )
            ]
        )
        fig.update_layout(xaxis_title="Health Grade", yaxis_title="Count", height=300)
        st.plotly_chart(fig, use_container_width=True)

    if summary.templates_ranked:
        st.subheader("Templates Ranked by Activity")
        st.dataframe(
            summary.templates_ranked, use_container_width=True, hide_index=True
        )


def render_template_detail(memory, template_id):
    """Render detailed view for a single template."""
    stats = memory.get_stats(template_id)

    col1, col2, col3 = st.columns(3)
    col1.metric("Health Grade", stats.overall_health_grade.title())
    col2.metric("Fields", stats.field_count)
    col3.metric("Samples", stats.sample_count)

    col4, col5, col6 = st.columns(3)
    col4.metric("Mean Confidence", f"{stats.mean_confidence:.4f}")
    col5.metric("Min Confidence", f"{stats.min_confidence:.4f}")
    col6.metric("Max Confidence", f"{stats.max_confidence:.4f}")

    st.subheader("Field Stability Scores")
    stability = memory.get_field_stability(template_id)
    stability_data = [
        {
            "Field": name,
            "Stability": f"{score:.3f}",
            "Status": "✓ Stable" if score > 0.8 else "⚠️ Unstable",
        }
        for name, score in sorted(stability.items(), key=lambda x: x[1], reverse=True)
    ]
    st.dataframe(stability_data, use_container_width=True, hide_index=True)

    fig = go.Figure(
        data=[
            go.Bar(
                x=[d["Field"] for d in stability_data],
                y=[float(d["Stability"]) for d in stability_data],
                marker_color=[
                    "#2ca02c" if float(d["Stability"]) > 0.8 else "#ff7f0e"
                    for d in stability_data
                ],
            )
        ]
    )
    fig.update_layout(
        title="Field Stability",
        xaxis_title="Field",
        yaxis_title="Score",
        yaxis=dict(range=[0, 1]),
        height=350,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_drift_analysis(memory, template_id):
    """Render drift detection for a template."""
    st.subheader("Drift Detection")
    st.markdown(
        "Compare a **normal** document vs a **drifted** one against the stored template."
    )

    random.seed(99)
    if template_id == "employment-form":
        normal_doc = make_employment_form(variation=0.02)
        drifted_doc = make_employment_form(variation=0.15)
    else:
        normal_doc = make_invoice(variation=0.02)
        drifted_doc = make_invoice(variation=0.15)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Normal Document** (low variation)")
        drift_normal = memory.detect_drift(normal_doc, template_id)
        st.metric("Overall Drift", f"{drift_normal.overall_drift_score:.4f}")
        st.metric("Is Drifting", "No" if not drift_normal.is_drifting else "Yes")

    with col2:
        st.markdown("**Drifted Document** (high variation)")
        drift_drifted = memory.detect_drift(drifted_doc, template_id)
        st.metric("Overall Drift", f"{drift_drifted.overall_drift_score:.4f}")
        st.metric("Is Drifting", "⚠️ Yes" if drift_drifted.is_drifting else "No")

    if drift_drifted.field_drifts:
        st.subheader("Per-Field Drift Scores (Drifted Document)")
        drift_data = [
            {
                "Field": fd.field_name,
                "Drift Score": f"{fd.drift_score:.4f}",
                "Drifting": "⚠️" if fd.is_drifting else "✓",
            }
            for fd in sorted(
                drift_drifted.field_drifts, key=lambda x: x.drift_score, reverse=True
            )
        ]
        st.dataframe(drift_data, use_container_width=True, hide_index=True)


def render_cluster_view(memory, template_id):
    """Render cluster membership view."""
    st.subheader("Cluster Membership")
    cluster_stats = memory.get_cluster_stats(template_id)

    col1, col2, col3 = st.columns(3)
    col1.metric("Members", cluster_stats.member_count)
    col2.metric("Mean Confidence", f"{cluster_stats.mean_confidence:.3f}")
    col3.metric(
        "Newest Record",
        cluster_stats.newest_record[:10] if cluster_stats.newest_record else "N/A",
    )

    members = memory.get_cluster_members(template_id)
    if members:
        member_data = [
            {
                "Doc ID": m.doc_id,
                "Confidence": f"{m.confidence:.3f}",
                "Recorded At": m.recorded_at[:19],
            }
            for m in members
        ]
        st.dataframe(member_data, use_container_width=True, hide_index=True)


def render_record_document(memory):
    """Render document recording interface."""
    st.markdown(
        "Record new documents to train spatial memory. Use synthetic generators or upload JSON."
    )

    tab_synth, tab_json = st.tabs(["Generate Synthetic", "Upload JSON"])

    with tab_synth:
        col1, col2 = st.columns(2)
        with col1:
            doc_type = st.selectbox("Document Type", ["Employment Form", "Invoice"])
            variation = st.slider("Position Variation", 0.001, 0.10, 0.01, 0.005)
            num_docs = st.slider("Number of Documents", 1, 20, 5)
        with col2:
            template_id = st.text_input(
                "Template ID",
                value="employment-form" if doc_type == "Employment Form" else "invoice",
            )
            doc_id_prefix = st.text_input("Doc ID Prefix", value="doc")

        if st.button("Record Documents", type="primary"):
            with st.spinner(f"Recording {num_docs} documents..."):
                for i in range(num_docs):
                    if doc_type == "Employment Form":
                        doc = make_employment_form(variation=variation)
                    else:
                        doc = make_invoice(variation=variation)
                    memory.record(
                        doc,
                        template_id=template_id,
                        doc_id=f"{doc_id_prefix}-{i+1:03d}",
                    )
            st.success(f"✓ Recorded {num_docs} documents to template '{template_id}'")

    with tab_json:
        st.markdown("""
        Upload a JSON file representing a document. Expected format:
        ```json
        {
          "pages": [{
            "key_values": [
              {"key": "Employee Name", "bbox": {"x": 0.05, "y": 0.10, "width": 0.35, "height": 0.03}, "page": 1, "confidence": 0.95}
            ]
          }]
        }
        ```
        """)
        uploaded = st.file_uploader("Upload Document JSON", type=["json"])
        json_template_id = st.text_input(
            "Template ID for JSON upload", value="uploaded-template", key="json_tid"
        )

        if uploaded and st.button("Record Uploaded Document"):
            try:
                data = json.loads(uploaded.read())
                doc = json_to_document(data)
                tid = memory.record(doc, template_id=json_template_id)
                st.success(f"✓ Recorded document to template '{tid}'")
            except Exception as e:
                st.error(f"Error: {e}")


def render_locate_field(memory):
    """Render field lookup interface."""
    st.markdown(
        "Search for a field by name using spatial memory. The system scores candidates by position + name similarity."
    )

    templates = memory.list_templates()
    if not templates:
        st.info("No templates recorded. Record documents first.")
        return

    col1, col2 = st.columns(2)
    with col1:
        field_name = st.text_input("Field Name to Locate", value="Employee Name")
        template_id = st.selectbox(
            "Search in Template", templates, key="locate_template"
        )
    with col2:
        doc_type = st.selectbox(
            "Test Document Type", ["Employment Form", "Invoice"], key="locate_type"
        )
        variation = st.slider(
            "Test Doc Variation", 0.001, 0.05, 0.01, 0.005, key="locate_var"
        )

    if st.button("Locate Field"):
        doc = (
            make_employment_form(variation=variation)
            if doc_type == "Employment Form"
            else make_invoice(variation=variation)
        )

        # Use the matcher directly against the selected template for accurate spatial scoring
        field_location_map = memory.get_template(template_id)
        if field_location_map is None:
            st.warning(f"Template '{template_id}' not found.")
            return

        # Case-insensitive field name matching against template
        lookup_name = field_name
        for stored_name in field_location_map.fields.keys():
            if stored_name.lower() == field_name.lower():
                lookup_name = stored_name
                break

        matches = memory.matcher.find_field(lookup_name, doc, field_location_map)

        if matches:
            st.success(
                f"Found {len(matches)} candidate(s) for '{field_name}' in template '{template_id}'"
            )
            match_data = [
                {
                    "Field": " ".join(w.text for w in m.key_value.key),
                    "Combined Score": f"{m.combined_score:.3f}",
                    "Spatial Score": f"{m.spatial_score:.3f}",
                    "Name Score": f"{m.name_score:.3f}",
                    "In Region": "✓" if m.within_expected_region else "✗",
                }
                for m in matches[:10]
            ]
            st.dataframe(match_data, use_container_width=True, hide_index=True)

            # Highlight the best match
            best = matches[0]
            st.markdown(
                f"**Best match:** `{' '.join(w.text for w in best.key_value.key)}` "
                f"(combined={best.combined_score:.3f}, spatial={best.spatial_score:.3f}, "
                f"in_region={'Yes' if best.within_expected_region else 'No'})"
            )
        else:
            st.warning(f"No candidates found for '{field_name}'.")


def render_identify_template(memory):
    """Render template identification interface."""
    st.markdown(
        "Submit a document and the system identifies which stored template it matches based on field layout."
    )

    tab_gen, tab_upload = st.tabs(["Generate Test Document", "Upload Document JSON"])

    with tab_gen:
        templates = memory.list_templates()
        doc_type_options = ["Employment Form", "Invoice", "Unknown (mixed fields)"] + [
            f"Template: {t}"
            for t in templates
            if t not in ("employment-form", "invoice")
        ]
        doc_type = st.selectbox("Document Type", doc_type_options, key="identify_type")
        variation = st.slider(
            "Position Variation", 0.001, 0.15, 0.02, 0.005, key="identify_var"
        )

        if st.button("Identify Template", key="identify_gen_btn"):
            if doc_type == "Employment Form":
                doc = make_employment_form(variation=variation)
            elif doc_type == "Invoice":
                doc = make_invoice(variation=variation)
            elif doc_type == "Unknown (mixed fields)":
                doc = Document(
                    pages=[
                        Page(
                            key_values=[
                                KeyValue(
                                    key=[Word("Unknown"), Word("Field")],
                                    bbox=BBox(0.1, 0.1, 0.2, 0.03),
                                    page=1,
                                ),
                                KeyValue(
                                    key=[Word("Random"), Word("Data")],
                                    bbox=BBox(0.5, 0.5, 0.2, 0.03),
                                    page=1,
                                ),
                            ]
                        )
                    ]
                )
            else:
                # Generate doc from a stored template's field positions
                tid = doc_type.replace("Template: ", "")
                template = memory.get_template(tid)
                if template:
                    kvs = []
                    for field_name, regions in template.fields.items():
                        for region in regions:
                            kvs.append(
                                KeyValue(
                                    key=[Word(w) for w in field_name.split()],
                                    bbox=BBox(
                                        max(
                                            0.001,
                                            min(
                                                0.95,
                                                region.bbox["x"]
                                                + random.uniform(-variation, variation),
                                            ),
                                        ),
                                        max(
                                            0.001,
                                            min(
                                                0.95,
                                                region.bbox["y"]
                                                + random.uniform(-variation, variation),
                                            ),
                                        ),
                                        region.bbox["width"],
                                        region.bbox["height"],
                                    ),
                                    page=region.page,
                                    confidence=region.confidence,
                                )
                            )
                    doc = Document(pages=[Page(key_values=kvs)])
                else:
                    st.error(f"Template '{tid}' not found.")
                    return

            match = memory.identify_template(doc)
            if match:
                st.success(f"Matched: **{match.template_id}**")
                col1, col2, col3 = st.columns(3)
                col1.metric("Similarity Score", f"{match.similarity_score:.3f}")
                col2.metric("Field Overlap", f"{match.field_overlap_ratio:.3f}")
                col3.metric("Spatial Similarity", f"{match.spatial_similarity:.3f}")
            else:
                st.warning(
                    "No template matched. This appears to be an unknown document layout."
                )

    with tab_upload:
        st.markdown("""
        Upload a JSON document to identify which template it belongs to:
        ```json
        {"pages": [{"key_values": [{"key": "Invoice Number", "bbox": {"x": 0.6, "y": 0.05, "width": 0.2, "height": 0.03}, "page": 1}]}]}
        ```
        """)
        uploaded_doc = st.file_uploader(
            "Upload Document JSON", type=["json"], key="identify_upload"
        )

        if uploaded_doc and st.button(
            "Identify Uploaded Document", key="identify_upload_btn"
        ):
            try:
                data = json.loads(uploaded_doc.read())
                doc = json_to_document(data)
                match = memory.identify_template(doc)
                if match:
                    st.success(f"Matched: **{match.template_id}**")
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Similarity Score", f"{match.similarity_score:.3f}")
                    col2.metric("Field Overlap", f"{match.field_overlap_ratio:.3f}")
                    col3.metric("Spatial Similarity", f"{match.spatial_similarity:.3f}")
                else:
                    st.warning(
                        "No template matched. This is an unknown document layout."
                    )
            except Exception as e:
                st.error(f"Error: {e}")


def render_export_import(memory):
    """Render template export/import interface."""
    templates = memory.list_templates()
    if not templates:
        st.info("No templates to export.")
        return

    st.subheader("Export Template")
    col1, col2 = st.columns(2)
    with col1:
        export_tid = st.selectbox("Template to Export", templates, key="export_select")
        export_fmt = st.radio("Format", ["JSON", "CSV"], horizontal=True)

    if st.button("Export"):
        fmt = "json" if export_fmt == "JSON" else "csv"
        data = memory.export_template(export_tid, fmt=fmt)
        if fmt == "json":
            content = json.dumps(data, indent=2)
            st.download_button(
                "Download JSON", content, f"{export_tid}.json", "application/json"
            )
        else:
            st.download_button("Download CSV", data, f"{export_tid}.csv", "text/csv")
        st.code(
            content if fmt == "json" else data,
            language="json" if fmt == "json" else None,
        )

    st.subheader("Import Template")
    uploaded_template = st.file_uploader(
        "Upload Template JSON", type=["json"], key="import_file"
    )
    if uploaded_template and st.button("Import Template"):
        try:
            data = json.loads(uploaded_template.read())
            tid = memory.import_template(data)
            st.success(f"✓ Imported template: '{tid}'")
        except Exception as e:
            st.error(f"Import failed: {e}")

    st.subheader("Delete Template")
    delete_tid = st.selectbox("Template to Delete", templates, key="delete_select")
    if st.button("Delete Template", type="secondary"):
        memory.delete_template(delete_tid)
        st.success(f"✓ Deleted template: '{delete_tid}'")


# =============================================================================
# Main Application
# =============================================================================


def main():
    """Main dashboard application."""
    st.set_page_config(
        page_title="textract-field-memory Dashboard",
        page_icon="🧠",
        layout="wide",
    )

    st.title("🧠 textract-field-memory Dashboard")
    st.caption("Spatial field location memory for document processing pipelines")

    memory = get_memory()
    templates = memory.list_templates()

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select View",
        [
            "System Overview",
            "Record Documents",
            "Field Lookup",
            "Identify Template",
            "Template Detail",
            "Field Positions",
            "Drift Analysis",
            "Cluster Membership",
            "Export / Import",
        ],
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Templates:** {len(templates)}")
    if templates:
        summary = memory.get_system_summary()
        st.sidebar.markdown(f"**Documents:** {summary.total_documents_processed}")
        st.sidebar.markdown(f"**Health:** {summary.mean_template_health_grade.title()}")

    # Page routing
    if page == "System Overview":
        st.header("System Overview")
        render_health_dashboard(memory)

    elif page == "Record Documents":
        st.header("Record Documents")
        render_record_document(memory)

    elif page == "Field Lookup":
        st.header("Field Lookup (Spatial Search)")
        render_locate_field(memory)

    elif page == "Identify Template":
        st.header("Template Identification")
        render_identify_template(memory)

    elif page == "Template Detail":
        st.header("Template Detail")
        if templates:
            selected = st.selectbox("Select Template", templates)
            render_template_detail(memory, selected)
        else:
            st.info("No templates recorded yet.")

    elif page == "Field Positions":
        st.header("Field Positions (Spatial Map)")
        if templates:
            selected = st.selectbox("Select Template", templates, key="positions")
            render_field_positions(memory, selected)
        else:
            st.info("No templates recorded yet.")

    elif page == "Drift Analysis":
        st.header("Drift Analysis")
        if templates:
            selected = st.selectbox("Select Template", templates, key="drift")
            render_drift_analysis(memory, selected)
        else:
            st.info("No templates recorded yet.")

    elif page == "Cluster Membership":
        st.header("Cluster Membership")
        if templates:
            selected = st.selectbox("Select Template", templates, key="cluster")
            render_cluster_view(memory, selected)
        else:
            st.info("No templates recorded yet.")

    elif page == "Export / Import":
        st.header("Export / Import Templates")
        render_export_import(memory)

    # Footer
    st.sidebar.markdown("---")
    store_info = os.environ.get("FIELD_MEMORY_STORE", "demo (local)")
    st.sidebar.markdown(
        f"**textract-field-memory** v0.2.0\n\n"
        f"Store: `{store_info}`\n\n"
        "Zero dependencies. Pure Python.\n\n"
        "[GitHub](https://github.com/aws-samples/sample-textract-field-memory)"
    )


if __name__ == "__main__":
    main()
