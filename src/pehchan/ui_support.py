"""UI adapter and graph rendering, separate from investigation decisions."""

import html
import json
import os

import requests


class ApiClient:
    def __init__(self):
        self.base = os.getenv("PEHCHAN_API_URL", "http://127.0.0.1:8000").rstrip("/")
        self.token = (
            os.getenv("PEHCHAN_UI_TOKEN")
            or os.getenv("PEHCHAN_WRITE_TOKEN")
            or os.getenv("PEHCHAN_API_TOKEN", "")
        )

    def request(self, method, path, **kwargs):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        response = requests.request(
            method, self.base + path, headers=headers, timeout=180, **kwargs
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", "Request failed")
            except ValueError:
                detail = "Request failed"
            raise RuntimeError(str(detail))
        return response.json()


def render_graph(data: dict) -> str:
    from pyvis.network import Network

    network = Network(
        height="560px",
        width="100%",
        directed=True,
        bgcolor="#0d1b24",
        font_color="#eaf4ef",
        cdn_resources="in_line",
    )
    colors = {
        "ClaimVariant": "#81e6c3",
        "Claim": "#3cb9a3",
        "NarrativeFrame": "#ffc878",
        "Entity": "#a5a0ff",
        "FactCheck": "#85bafa",
        "Publisher": "#eaafc8",
        "Topic": "#9fb7bf",
    }
    for node in data["nodes"]:
        label = str(node["label"])
        # PyVis serializes labels with Jinja's HTML-safe tojson filter. Titles are HTML tooltips.
        network.add_node(
            node["id"],
            label=label[:70],
            title=html.escape(node["type"] + ": " + label),
            color=colors.get(node["type"], "#a0a9b3"),
            shape="dot",
            size=16,
        )
    for edge in data["edges"]:
        inferred = edge["basis"] == "curated_inference"
        network.add_edge(
            edge["source"],
            edge["target"],
            label=edge["type"],
            title=html.escape(edge["basis"] + ": " + edge.get("rationale", "")),
            dashes=inferred,
            color="#d4ac68" if inferred else "#648e9c",
        )
    network.set_options(
        json.dumps(
            {
                "physics": {"solver": "forceAtlas2Based", "stabilization": {"iterations": 100}},
                "interaction": {"hover": True, "navigationButtons": True},
                "edges": {
                    "font": {"size": 10, "color": "#c4d4d8"},
                    "arrows": {"to": {"enabled": True}},
                },
            }
        )
    )
    return network.generate_html()


def downloadable_report(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
