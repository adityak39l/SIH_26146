"""
Builds the analyst console as one self-contained HTML file (no external assets), so it
opens from disk on an air-gapped machine and can also be served by any static host.

Usage:
    python -m src.pipeline.export            # writes docs/index.html
"""
import json
from pathlib import Path
from typing import Any, Dict

from config.settings import BASE_DIR, DOCS_DIR

DASHBOARD_DIR = BASE_DIR / "src" / "dashboard"
PLACEHOLDER = "__VIGIL_DATA__"


def render_dashboard(result: Dict[str, Any]) -> str:
    # "<" is escaped so that no value from an ingested file can close the script element.
    payload = json.dumps(result, separators=(",", ":")).replace("<", "\\u003c")
    html = (DASHBOARD_DIR / "template.html").read_text(encoding="utf-8")
    html = html.replace("/*__CSS__*/", (DASHBOARD_DIR / "console.css").read_text(encoding="utf-8"))
    html = html.replace("/*__JS__*/", (DASHBOARD_DIR / "console.js").read_text(encoding="utf-8"))
    return html.replace(PLACEHOLDER, payload)


def export(out_file: Path = DOCS_DIR / "index.html", source=None) -> Path:
    from src.pipeline.engine import analyze

    out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(render_dashboard(analyze(source)), encoding="utf-8", newline="\n")
    return out_file


if __name__ == "__main__":
    path = export()
    print(f"[+] Analyst console written to {path} ({path.stat().st_size / 1024:.0f} KB)")
