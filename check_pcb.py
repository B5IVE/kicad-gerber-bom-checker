#!/usr/bin/env python3
"""
kicad-gerber-bom-checker: Pre-Fab PCB BOM, Designator & Gerber Manifest Auditor.

Validates JSONL Bill of Materials (BOM) entries and Gerber/drill/assembly file
manifests for 4 to 8+ layer and HDI/rigid-flex PCB handoffs, checking required
MPN/footprint/value fields, reference designator prefixes, duplicate or non-
standard layer names, and emitting a JSON audit report plus Markdown checklist.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_PREFIX_BY_CATEGORY = {
    "resistor": "R",
    "capacitor": "C",
    "inductor": "L",
    "ic": "U",
    "mcu": "U",
    "connector": "J",
    "diode": "D",
    "led": "D",
    "transistor": "Q",
    "mosfet": "Q",
    "crystal": "Y",
    "ferrite": "FB",
    "testpoint": "TP",
}

LAYER_FILE_PATTERN = re.compile(
    r"^(?P<board>[A-Za-z0-9_-]+)-(?P<layer>F_Cu|In[1-9][0-9]*_Cu|B_Cu|F_SilkS|B_SilkS|F_Mask|B_Mask|F_Paste|B_Paste|Edge_Cuts|Drill)\.(?P<ext>gbr|ger|drl|gbrjob)$",
    re.IGNORECASE,
)


@dataclass
class PcbFinding:
    line_number: int
    item_id: str
    severity: str  # CRITICAL, WARN
    code: str
    message: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit PCB BOM and Gerber/drill handoff manifests prior to fabrication."
    )
    parser.add_argument("manifest_file", type=Path, help="Path to BOM/Gerber JSONL manifest")
    parser.add_argument(
        "--min-copper-layers",
        type=int,
        default=4,
        help="Minimum expected copper layers (e.g., 4, 6, 8; default: 4)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path("pcb_handoff_audit.json"),
        help="Output JSON report path (default: pcb_handoff_audit.json)",
    )
    parser.add_argument(
        "--md-out",
        type=Path,
        default=Path("pcb_handoff_checklist.md"),
        help="Output Markdown checklist path (default: pcb_handoff_checklist.md)",
    )
    args = parser.parse_args()

    if not args.manifest_file.is_file():
        print(f"Error: Manifest file not found: {args.manifest_file}", file=sys.stderr)
        return 2

    findings: list[PcbFinding] = []
    seen_designators: dict[str, int] = {}
    copper_layers_seen: set[str] = set()
    category_counts: Counter[str] = Counter()
    total_records = 0
    bom_count = 0
    gerber_count = 0

    with args.manifest_file.open("r", encoding="utf-8") as handle:
        for line_num, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            total_records += 1

            try:
                rec: dict[str, Any] = json.loads(stripped)
            except json.JSONDecodeError as exc:
                findings.append(
                    PcbFinding(line_num, f"line-{line_num}", "CRITICAL", "PCB-001", f"Malformed JSON line: {exc}")
                )
                continue

            record_type = str(rec.get("record_type", "")).strip().lower()

            if record_type == "bom_item":
                bom_count += 1
                ref = str(rec.get("designator", "")).strip()
                cat = str(rec.get("category", "")).strip().lower()
                mpn = str(rec.get("mpn", "")).strip()
                footprint = str(rec.get("footprint", "")).strip()
                value = str(rec.get("value", "")).strip()
                dnp = bool(rec.get("dnp", False))

                if not ref:
                    findings.append(
                        PcbFinding(line_num, f"bom-{line_num}", "CRITICAL", "BOM-001", "Missing component designator.")
                    )
                    continue

                if ref in seen_designators:
                    findings.append(
                        PcbFinding(
                            line_num,
                            ref,
                            "CRITICAL",
                            "BOM-002",
                            f"Duplicate designator '{ref}' (first seen on line {seen_designators[ref]}).",
                        )
                    )
                else:
                    seen_designators[ref] = line_num

                if cat:
                    category_counts[cat] += 1
                    expected_prefix = EXPECTED_PREFIX_BY_CATEGORY.get(cat)
                    ref_prefix = re.match(r"^[A-Za-z]+", ref)
                    actual_prefix = ref_prefix.group(0).upper() if ref_prefix else ""
                    if expected_prefix and actual_prefix != expected_prefix:
                        findings.append(
                            PcbFinding(
                                line_num,
                                ref,
                                "WARN",
                                "BOM-003",
                                f"Category '{cat}' expects prefix '{expected_prefix}', got '{actual_prefix or 'none'}'.",
                            )
                        )

                if not footprint:
                    findings.append(
                        PcbFinding(line_num, ref, "CRITICAL", "BOM-004", f"Missing PCB footprint for '{ref}'.")
                    )

                if not dnp and (not mpn or mpn.upper() in {"TBD", "N/A", "NONE"}):
                    findings.append(
                        PcbFinding(line_num, ref, "CRITICAL", "BOM-005", f"Missing or placeholder MPN for populated part '{ref}'.")
                    )

                if not value:
                    findings.append(
                        PcbFinding(line_num, ref, "WARN", "BOM-006", f"Missing component value for '{ref}'.")
                    )

            elif record_type == "gerber_file":
                gerber_count += 1
                filename = str(rec.get("filename", "")).strip()
                if not filename:
                    findings.append(
                        PcbFinding(line_num, f"gbr-{line_num}", "CRITICAL", "GBR-001", "Missing Gerber/drill filename.")
                    )
                    continue

                match = LAYER_FILE_PATTERN.match(filename)
                if not match:
                    findings.append(
                        PcbFinding(
                            line_num,
                            filename,
                            "WARN",
                            "GBR-002",
                            f"Filename '{filename}' does not match standard KiCad layer naming convention.",
                        )
                    )
                else:
                    layer = match.group("layer")
                    if layer == "F_Cu" or layer == "B_Cu" or re.match(r"^In[1-9][0-9]*_Cu$", layer):
                        copper_layers_seen.add(layer)

            else:
                findings.append(
                    PcbFinding(
                        line_num,
                        f"line-{line_num}",
                        "CRITICAL",
                        "PCB-002",
                        f"Unsupported record_type {record_type!r} (expected 'bom_item' or 'gerber_file').",
                    )
                )

    if gerber_count > 0 and len(copper_layers_seen) < args.min_copper_layers:
        findings.append(
            PcbFinding(
                0,
                "stackup",
                "WARN",
                "STK-001",
                f"Detected {len(copper_layers_seen)} copper layer(s) ({sorted(copper_layers_seen)}); "
                f"expected at least {args.min_copper_layers} for target stackup.",
            )
        )

    crit_count = sum(1 for f in findings if f.severity == "CRITICAL")
    warn_count = sum(1 for f in findings if f.severity == "WARN")

    audit_payload = {
        "metadata": {
            "source_file": str(args.manifest_file),
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "total_records": total_records,
            "bom_items": bom_count,
            "gerber_files": gerber_count,
            "copper_layers_detected": sorted(copper_layers_seen),
            "min_copper_layers_expected": args.min_copper_layers,
            "category_counts": dict(category_counts),
            "critical_count": crit_count,
            "warning_count": warn_count,
        },
        "findings": [asdict(f) for f in findings],
    }

    args.json_out.write_text(json.dumps(audit_payload, indent=2), encoding="utf-8")

    md_lines = [
        "# Pre-Fab PCB BOM & Gerber Handoff Checklist",
        "",
        f"- **Manifest:** `{args.manifest_file.name}` | **Generated (UTC):** `{audit_payload['metadata']['generated_utc']}`",
        f"- **BOM Items:** `{bom_count}` | **Gerber/Drill Files:** `{gerber_count}` | **Copper Layers:** `{len(copper_layers_seen)}`",
        f"- **Status:** `{'HOLD - CRITICAL ISSUES' if crit_count else 'REVIEW - WARNINGS ONLY' if warn_count else 'READY FOR FAB'}` "
        f"(`{crit_count}` critical, `{warn_count}` warnings)",
        "",
        "## Audit Findings",
        "",
    ]

    if not findings:
        md_lines.append("_All BOM and Gerber manifest checks passed._")
    else:
        md_lines.extend(
            [
                "| Line | Item / Layer | Severity | Code | Diagnostic Detail |",
                "| :---: | :--- | :---: | :--- | :--- |",
            ]
        )
        for item in findings:
            md_lines.append(
                f"| {item.line_number} | `{item.item_id}` | **{item.severity}** | `{item.code}` | {item.message} |"
            )

    args.md_out.write_text("\n".join(md_lines).strip() + "\n", encoding="utf-8")

    print(
        f"[+] PCB Handoff Audit: {bom_count} BOM items, {gerber_count} Gerber/drill entries, "
        f"{crit_count} critical, {warn_count} warnings."
    )
    print(f"[+] Wrote {args.json_out} and {args.md_out}")

    return 1 if crit_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
