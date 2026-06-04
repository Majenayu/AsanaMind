"""
Auto-extract every asana entry from static/poses.js and emit a markdown
table that becomes Annexure A of the patent specification.

Outputs docs/research/annexure-a.md.

Usage:
    python docs/research/extract_annexure_a.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "static" / "poses.js"
OUT = ROOT / "docs" / "research" / "annexure-a.md"


def slurp_poses_block(text: str) -> str:
    """Find the 'asanaData = [' array body."""
    m = re.search(r"asanaData\s*=\s*\[", text)
    if not m:
        # poses.js exposes the array via window.asanaData = [...]; older
        # naming is asanaData; try both.
        m = re.search(r"window\.asanaData\s*=\s*\[", text)
    if not m:
        # Try ASANA_LIBRARY name.
        m = re.search(r"ASANA_LIBRARY\s*=\s*\[", text)
    if not m:
        return text  # last resort, scan whole file
    return text[m.end():]


def split_asanas(body: str) -> list[str]:
    """Split the array body into per-asana JS object literals.

    The literals are nested with their own braces, so we walk depth.
    """
    out: list[str] = []
    depth = 0
    start = None
    in_str = None  # ' or " or `
    escape = False
    for i, ch in enumerate(body):
        if escape:
            escape = False
            continue
        if in_str:
            if ch == "\\":
                escape = True
                continue
            if ch == in_str:
                in_str = None
            continue
        if ch in "\"'`":
            in_str = ch
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                out.append(body[start:i + 1])
                start = None
            continue
    return out


def extract_field(obj_src: str, key: str) -> str | None:
    """Pull `key: '...'` or `key: "..."` from an object literal."""
    pat = re.compile(
        rf"\b{key}\s*:\s*(?:'([^']*)'|\"([^\"]*)\")"
    )
    m = pat.search(obj_src)
    if not m:
        return None
    return m.group(1) or m.group(2)


def extract_rules(obj_src: str) -> list[dict]:
    """Extract the rules: [...] array from a pose literal as parsed dicts."""
    rules_match = re.search(r"rules\s*:\s*\[", obj_src)
    if not rules_match:
        return []
    body = obj_src[rules_match.end():]
    # Walk to matching close bracket
    depth = 1
    in_str = None
    escape = False
    end_idx = None
    for i, ch in enumerate(body):
        if escape:
            escape = False
            continue
        if in_str:
            if ch == "\\":
                escape = True
                continue
            if ch == in_str:
                in_str = None
            continue
        if ch in "\"'`":
            in_str = ch
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end_idx = i
                break
    if end_idx is None:
        return []
    rules_body = body[:end_idx]

    # Split into per-rule object literals
    rule_objs = split_asanas(rules_body)
    parsed: list[dict] = []
    for r in rule_objs:
        d: dict = {}
        for k in ("type", "message"):
            v = extract_field(r, k)
            if v is not None:
                d[k] = v
        # joints: ['a', 'b', 'c']
        jm = re.search(r"joints\s*:\s*\[([^\]]+)\]", r)
        if jm:
            d["joints"] = re.findall(r"'([^']+)'|\"([^\"]+)\"", jm.group(1))
            d["joints"] = [a or b for a, b in d["joints"]]
        # range: [a, b]
        rm = re.search(r"range\s*:\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]", r)
        if rm:
            d["range"] = (rm.group(1), rm.group(2))
        # priority
        pm = re.search(r"priority\s*:\s*(\d+)", r)
        if pm:
            d["priority"] = int(pm.group(1))
        # tolFrac, tolDeg, minFrac, maxFrac, bufferFrac
        for nk in ("tolFrac", "tolDeg", "minFrac", "maxFrac", "bufferFrac",
                  "minDx", "maxDy"):
            nm = re.search(rf"{nk}\s*:\s*(-?\d+(?:\.\d+)?)", r)
            if nm:
                d[nk] = nm.group(1)
        parsed.append(d)
    return parsed


def render_md(asanas: list[dict]) -> str:
    lines: list[str] = []
    lines.append("# ANNEXURE A — Pose Rule Sets for the 20 Curated Asanas")
    lines.append("")
    lines.append(
        "This annexure enumerates the rule grammar instances for each of the"
        " twenty curated asanas in the AsanMinds programme. Rules are"
        " auto-extracted from the production source `static/poses.js`."
        " Each rule comprises a predicate type, the keypoints it operates on,"
        " a numeric range or tolerance, the corrective natural-language"
        " message emitted on failure, and a priority class (1 = highest)."
    )
    lines.append("")

    for i, a in enumerate(asanas, 1):
        lines.append(f"## A.{i} {a['name']} — {a.get('sanskrit') or ''}")
        meta_bits = []
        if a.get("category"):
            meta_bits.append(f"**Difficulty:** {a['category']}")
        if a.get("view"):
            meta_bits.append(f"**View:** {a['view']}")
        if a.get("targeted"):
            meta_bits.append(f"**Target:** {a['targeted']}")
        if meta_bits:
            lines.append(" · ".join(meta_bits))
            lines.append("")
        if a.get("benefits"):
            lines.append(f"_{a['benefits']}_")
            lines.append("")
        if a.get("rules"):
            lines.append("| # | Type | Joints | Range/Tolerance | P | Correction message |")
            lines.append("|---|------|--------|-----------------|---|--------------------|")
            for j, r in enumerate(a["rules"], 1):
                joints = ", ".join(r.get("joints") or [])
                # Range/tolerance string
                rt = ""
                if "range" in r:
                    rt = f"{r['range'][0]}°–{r['range'][1]}°"
                elif "tolFrac" in r:
                    rt = f"tol={r['tolFrac']}"
                elif "tolDeg" in r:
                    rt = f"tol={r['tolDeg']}°"
                elif "minFrac" in r and "maxFrac" in r:
                    rt = f"{r['minFrac']}–{r['maxFrac']}"
                elif "bufferFrac" in r:
                    rt = f"buf={r['bufferFrac']}"
                elif "minDx" in r:
                    rt = f"dx≥{r['minDx']} dy≤{r.get('maxDy','-')}"
                priority = r.get("priority", "—")
                msg = (r.get("message") or "").replace("|", "\\|")
                lines.append(
                    f"| {j} | `{r.get('type','?')}` | {joints} | {rt} | {priority} | {msg} |"
                )
            lines.append("")

    return "\n".join(lines)


def main():
    text = SRC.read_text(encoding="utf-8")
    body = slurp_poses_block(text)
    objects = split_asanas(body)
    asanas: list[dict] = []
    for obj in objects:
        nm = extract_field(obj, "name")
        if not nm:
            continue
        # Skip nested objects that aren't pose entries (rules, etc.)
        if not extract_field(obj, "category"):
            continue
        a = {
            "name": nm,
            "sanskrit": extract_field(obj, "sanskrit"),
            "category": extract_field(obj, "category"),
            "view": extract_field(obj, "view"),
            "targeted": extract_field(obj, "targeted"),
            "benefits": extract_field(obj, "benefits"),
            "rules": extract_rules(obj),
        }
        asanas.append(a)

    print(f"Extracted {len(asanas)} asanas with "
          f"{sum(len(a['rules']) for a in asanas)} total rules.")

    out = render_md(asanas)
    OUT.write_text(out, encoding="utf-8")
    print(f"  [ok] wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
