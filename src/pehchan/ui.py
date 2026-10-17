"""Pehchan's local investigation, graph explorer and persistent case library."""

import uuid
from urllib.parse import quote

import requests
import streamlit as st
import streamlit.components.v1 as components

from pehchan.ui_support import ApiClient, downloadable_report, render_graph

st.set_page_config(page_title="Pehchan AI · Evidence desk", page_icon="◈", layout="wide")
st.markdown(
    """
<style>
.stApp {background: radial-gradient(ellipse at top right, #16372f 0%, #0d1721 55%);}
.block-container {max-width: 1250px; padding-top: 2rem;}
h1,h2,h3 {letter-spacing: -.035em;}
div[data-testid="stMetric"] {background:#13232b; border:1px solid #29433f; border-radius:14px; padding:16px;}
div[data-testid="stForm"] {background:#13232b; border:1px solid #29433f; border-radius:18px; padding:24px;}
section[data-testid="stSidebar"] {background:#101e26;}
</style>
""",
    unsafe_allow_html=True,
)

client = ApiClient()


def api(method, path, **kwargs):
    try:
        return client.request(method, path, **kwargs)
    except requests.RequestException:
        st.error("Could not reach the investigation service. Start the backend and try again.")
    except RuntimeError as exc:
        st.error(str(exc))
    return None


def show_dossier(report):
    status = report["status"]
    labels = {
        "EVIDENCE_DOSSIER_READY": "Evidence dossier ready",
        "NEEDS_HUMAN_REVIEW": "Human review needed",
        "INSUFFICIENT_EVIDENCE": "Evidence is insufficient",
    }
    findings = {
        "KNOWN_RECYCLED_CLAIM": ("Known recycled claim", st.success),
        "KNOWN_NARRATIVE_VARIANT": ("Variant of a known narrative", st.warning),
        "NEW_CLAIM": ("New claim · queued for a fact-checker", st.info),
    }
    if report.get("finding") in findings:
        label, banner = findings[report["finding"]]
        banner(f"**{label}** — {(report.get('review_queue') or {}).get('reason', '')}")
    prior = report.get("prior_submission")
    if prior and report.get("inference", {}).get("mode") == "graph_recall":
        st.caption(
            f"Recalled through the graph: this wording matches an earlier submission "
            f"(similarity {prior['similarity']:.3f}, case {prior['investigation_id']}) and was "
            "answered by following its MATCHES edges."
        )
    elif prior:
        st.caption(f"Seen before in case {prior['investigation_id']} ({prior.get('finding')}).")
    st.subheader(labels.get(status, status))
    st.write(report["recommended_action"])
    if report.get("draft_reply"):
        with st.container(border=True):
            st.markdown("**Drafted reply** · requires human approval")
            st.text(report["draft_reply"]["text"])
    inference = report.get("inference", {})
    if inference.get("mode") == "gemini":
        st.caption("Tool-calling inference: Google AI Studio · " + inference["model"])
        with st.expander("Model analyst note · requires review"):
            st.text(inference["analyst_note"])
            st.caption("Model commentary; citations and case status are validated separately.")
    st.caption(
        "Published ratings below describe the original reviewed claims; Pehchan assigns no new truth verdict."
    )
    a, b, c = st.columns(3)
    a.metric("Direct reviews", report["quality"]["direct_reviews"])
    b.metric("Reviewing publishers", report["quality"]["publisher_count"])
    c.metric("Narrative connections", len(report["graph_findings"]["narrative_paths"]))
    if report.get("investigation_id"):
        st.caption(f"Case {report['investigation_id']} · {report.get('review_state', 'OPEN')}")
    st.markdown("#### Published evidence")
    if not report["citations"]:
        st.info(
            "No sufficiently relevant recorded review was found. Further investigation is needed."
        )
    for n, source in enumerate(report["citations"], 1):
        rating_label = source["verdict_original"]
        if len(rating_label) > 100:
            rating_label = rating_label[:97] + "…"
        with st.expander(f"{n}. {source['publisher']} · {rating_label}", expanded=n == 1):
            st.write(source["reviewed_claim"])
            st.caption(
                "Relation to your submission: " + source["relevance"].replace("_", " ").lower()
            )
            st.write("Original publisher rating: " + source["verdict_original"])
            st.caption(
                "Published: " + (source["review_date"] or "Date unavailable in source markup")
            )
            st.link_button("Open publisher fact-check", source["url"])
            st.caption(
                f"Source record: {source['factcheck_id']} · File SHA-256: {source['source_sha256']}"
            )
    related = (report.get("widening") or {}).get("related", [])
    if related:
        st.markdown("#### Widened through shared entities and frames")
        st.caption(
            "No review of this exact claim. These fact-checked claims share rule-tagged entities "
            "or narrative frames with it; they are context, not evidence for this submission."
        )
        for item in related[:6]:
            shared = ", ".join(sorted({x["name"] for x in item["shared"]}))
            with st.expander(f"{item['publisher']} · {item['verdict_original'][:90]}"):
                st.write(item["text"])
                st.caption(f"Shared: {shared} · context score {item['score']:.3f}")
                for edge in item["shared"]:
                    st.caption(
                        f"Claim -[{edge['relation']}]-> {edge['label']} '{edge['name']}' · "
                        f"basis {edge['basis']} · {edge['reviewed_by']}"
                    )
                st.link_button("Open publisher fact-check", item["url"])
    if report["scout"]["context"]:
        with st.expander("Related context and uncertain matches"):
            for candidate in report["scout"]["context"]:
                st.write(candidate["text"])
                st.caption(
                    candidate["assessment"]["relation"] + " · " + candidate["assessment"]["reason"]
                )
    st.markdown("#### How the agents decided")
    for n, step in enumerate(report["agent_trace"], 1):
        tool = step.get("tool") or step.get("status", "")
        timing = f" · {step['duration_ms']} ms" if "duration_ms" in step else ""
        st.markdown(f"{n}. **{step['agent']}** → `{tool}`{timing}")
        if step.get("reason"):
            st.caption(step["reason"])
    with st.expander("Uncertainty and evidence quality"):
        for uncertainty in report["uncertainties"] + report["quality"]["warnings"]:
            st.write("• " + uncertainty)
    st.download_button(
        "Download evidence dossier",
        downloadable_report(report),
        file_name=(report.get("investigation_id") or "dossier") + ".json",
        mime="application/json",
    )


with st.sidebar:
    st.markdown("### ◈ PEHCHAN AI")
    st.caption("An evidence desk for connected claims")
    page = st.radio(
        "Workspace",
        ["Investigate", "Narrative explorer", "Dossiers & cases"],
        label_visibility="collapsed",
    )
    st.divider()
    health = api("GET", "/health")
    if health:
        inference = health.get("inference", {})
        if inference.get("mode") == "gemini" and not inference.get("configured"):
            st.warning(
                "Set GEMINI_API_KEY in the backend environment and restart the API to enable Gemma inference."
            )
        st.caption(
            f"Inference: Gemma ({inference.get('model')})"
            if inference.get("mode") == "gemini"
            else "Inference: offline specialists"
        )
        st.caption(f"Collection: {health['claims']} claim variants")
        st.caption(
            "Ready to investigate" if health["status"] == "ready" else "Collection setup required"
        )
    st.caption("Source evidence • explicit inference • visible uncertainty")

if page == "Investigate":
    st.caption("01 / INVESTIGATE")
    st.title("Follow the evidence.")
    st.write(
        "Find historical reviews, trace related narratives, and keep a source-backed record of what needs attention."
    )
    with st.form("claim_form"):
        claim = st.text_area(
            "What claim would you like to investigate?",
            placeholder="Example: A pet microchip scanner detected a chip in a woman's arm after a COVID-19 vaccination.",
            max_chars=4000,
            height=120,
        )
        submitted = st.form_submit_button("Start investigation", type="primary")
    if submitted:
        if not claim.strip():
            st.warning("Enter a claim to begin.")
        else:
            with st.spinner(
                "Finding candidate reviews, tracing graph context, and assembling evidence…"
            ):
                result = api(
                    "POST",
                    "/api/investigations",
                    json={"claim": claim, "request_id": uuid.uuid4().hex},
                )
            if result:
                st.session_state["report"] = result
    if st.session_state.get("report"):
        st.divider()
        show_dossier(st.session_state["report"])
elif page == "Narrative explorer":
    st.caption("02 / EXPLORE")
    st.title("See the connection.")
    st.write("Inspect recorded relationships and the inferences that connect claims.")
    report = st.session_state.get("report", {})
    options = {
        c["variant_id"]: c["text"]
        for c in report.get("scout", {}).get("matches", [])
        + report.get("scout", {}).get("context", [])
    }
    if options:
        selected = st.selectbox(
            "Focus on a candidate",
            ["", *options],
            format_func=lambda key: options.get(key, "Collection overview"),
        )
    else:
        selected = ""
        st.caption(
            "Run an investigation to focus this view on its candidates, or inspect the collection below."
        )
    graph = api(
        "GET",
        "/api/graph",
        params={"variant_id": selected, "limit": 80} if selected else {"limit": 80},
    )
    if graph:
        if graph["nodes"]:
            components.html(render_graph(graph), height=580, scrolling=False)
            st.caption(
                "Dashed amber edges are curated inferences. Solid edges represent source relationships or exact text grouping. Drag nodes, zoom, and hover for details."
            )
            nodes = {n["id"]: n for n in graph["nodes"]}
            node_id = st.selectbox(
                "Inspect a node", list(nodes), format_func=lambda key: nodes[key]["label"][:110]
            )
            st.write(nodes[node_id]["label"])
            st.caption(nodes[node_id]["type"] + " · " + node_id)
            st.dataframe(
                [e for e in graph["edges"] if node_id in {e["source"], e["target"]}],
                hide_index=True,
            )
            if nodes[node_id]["type"] == "ClaimVariant":
                evidence = api("GET", "/api/evidence/" + quote(node_id, safe=""))
                for source in evidence or []:
                    st.link_button(
                        source["publisher"] + " · " + source["verdict_original"], source["url"]
                    )
        else:
            st.info("No connected nodes are available for this selection.")
else:
    st.caption("03 / KEEP A RECORD")
    st.title("Dossiers & review cases.")
    st.write(
        "Return to the evidence, track follow-up, and preserve the distinction between a case state and a truth verdict."
    )
    cases = api("GET", "/api/investigations")
    if not cases:
        st.info("No saved investigations yet. Start with a claim in the investigation workspace.")
    else:
        st.dataframe(cases, hide_index=True, width="stretch")
        by_id = {c["id"]: c for c in cases}
        selected = st.selectbox(
            "Open a saved case",
            list(by_id),
            format_func=lambda key: by_id[key]["submitted_claim"][:100],
        )
        report = api("GET", "/api/investigations/" + quote(selected, safe=""))
        if report:
            st.write(report["submitted_claim"])
            show_dossier(report)
            with st.form("review_form"):
                states = ["OPEN", "IN_PROGRESS", "RESOLVED"]
                state = st.selectbox(
                    "Follow-up state",
                    states,
                    index=states.index(report.get("review_state", "OPEN")),
                )
                note = st.text_area(
                    "Research note", value=report.get("review_note", ""), max_chars=4000
                )
                save = st.form_submit_button("Save follow-up")
            if save:
                updated = api(
                    "PATCH",
                    "/api/investigations/" + quote(selected, safe=""),
                    json={"state": state, "note": note},
                )
                if updated:
                    st.success("Follow-up saved.")
