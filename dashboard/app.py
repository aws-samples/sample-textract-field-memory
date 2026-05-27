# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
textract-field-memory — Interactive Dashboard
==============================================

A Streamlit dashboard for visualizing template health, field positions,
drift detection, cluster membership, and system-wide analytics.

Usage:
    pip install textract-field-memory[dashboard]
    streamlit run dashboard/app.py
"""

import json
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
            confidence=random.uniform(0.88, 0.99),  # nosec B311,
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
            confidence=random.uniform(0.88, 0.99),  # nosec B311,
        )
        for name, x, y, w, h in fields
    ]
    return Document(pages=[Page(key_values=kvs)])


# =============================================================================
# Dashboard
# =============================================================================


def get_memory():
    """Get or create a TemplateMemory instance in session state."""
    if "memory" not in st.session_state:
        store_path = Path(__file__).parent / "store_path"
        store_path.mkdir(parents=True, exist_ok=True)
        memory = TemplateMemory(
            store_path=store_path,
            similarity_threshold=0.5,
            decay_factor=0.95,
            drift_threshold=0.1,
        )
        # Seed with demo data if store is empty
        if not memory.list_templates():
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

            # Flip y-axis (document coordinates: top=0, bottom=1)
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
        fig.update_layout(
            xaxis_title="Health Grade",
            yaxis_title="Count",
            height=300,
        )
        st.plotly_chart(fig, use_container_width=True)

    if summary.templates_ranked:
        st.subheader("Templates Ranked by Activity")
        st.dataframe(
            summary.templates_ranked,
            use_container_width=True,
            hide_index=True,
        )


def render_template_detail(memory, template_id):
    """Render detailed view for a single template."""
    stats = memory.get_stats(template_id)

    # Health metrics
    col1, col2, col3 = st.columns(3)
    col1.metric("Health Grade", stats.overall_health_grade.title())
    col2.metric("Fields", stats.field_count)
    col3.metric("Samples", stats.sample_count)

    col4, col5, col6 = st.columns(3)
    col4.metric("Mean Confidence", f"{stats.mean_confidence:.4f}")
    col5.metric("Min Confidence", f"{stats.min_confidence:.4f}")
    col6.metric("Max Confidence", f"{stats.max_confidence:.4f}")

    # Field stability
    st.subheader("Field Stability Scores")
    stability = memory.get_field_stability(template_id)
    stability_data = [
        {
            "Field": name,
            "Stability": score,
            "Status": "✓ Stable" if score > 0.8 else "⚠️ Unstable",
        }
        for name, score in sorted(stability.items(), key=lambda x: x[1], reverse=True)
    ]
    st.dataframe(stability_data, use_container_width=True, hide_index=True)

    # Stability bar chart
    fig = go.Figure(
        data=[
            go.Bar(
                x=[d["Field"] for d in stability_data],
                y=[d["Stability"] for d in stability_data],
                marker_color=[
                    "#2ca02c" if d["Stability"] > 0.8 else "#ff7f0e"
                    for d in stability_data
                ],
            )
        ]
    )
    fig.update_layout(
        title="Field Stability",
        xaxis_title="Field",
        yaxis_title="Stability Score",
        yaxis=dict(range=[0, 1]),
        height=350,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_drift_analysis(memory, template_id):
    """Render drift detection for a template."""
    st.subheader("Drift Detection")

    # Normal document
    random.seed(99)
    if template_id == "employment-form":
        normal_doc = make_employment_form(variation=0.02)
        drifted_doc = make_employment_form(variation=0.15)
    else:
        normal_doc = make_invoice(variation=0.02)
        drifted_doc = make_invoice(variation=0.15)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Normal Document**")
        drift_normal = memory.detect_drift(normal_doc, template_id)
        st.metric("Overall Drift", f"{drift_normal.overall_drift_score:.4f}")
        st.metric("Is Drifting", "No" if not drift_normal.is_drifting else "Yes")

    with col2:
        st.markdown("**Drifted Document (high variation)**")
        drift_drifted = memory.detect_drift(drifted_doc, template_id)
        st.metric("Overall Drift", f"{drift_drifted.overall_drift_score:.4f}")
        st.metric("Is Drifting", "⚠️ Yes" if drift_drifted.is_drifting else "No")

    if drift_drifted.field_drifts:
        st.subheader("Per-Field Drift Scores (Drifted Document)")
        drift_data = [
            {
                "Field": fd.field_name,
                "Drift Score": fd.drift_score,
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


def main():
    """Main dashboard application."""
    st.set_page_config(
        page_title="textract-field-memory Dashboard",
        page_icon="🧠",
        layout="wide",
    )

    st.title("🧠 textract-field-memory Dashboard")
    st.caption("Spatial field location memory — interactive analytics")

    memory = get_memory()
    templates = memory.list_templates()

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select View",
        [
            "System Overview",
            "Template Detail",
            "Field Positions",
            "Drift Analysis",
            "Cluster Membership",
        ],
    )

    if page == "System Overview":
        st.header("System Overview")
        render_health_dashboard(memory)

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

    # Footer
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        "**textract-field-memory** v0.1.0\n\n"
        "Zero dependencies. Pure Python.\n\n"
        "[Source](https://code.aws.dev/proserve/aws-ml-companions/textract-field-memory)"
    )


if __name__ == "__main__":
    main()
