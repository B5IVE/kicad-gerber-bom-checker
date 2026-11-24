# kicad-gerber-bom-checker

A zero-dependency Python 3.10+ CLI utility for **pre-fabrication PCB Bill of Materials (BOM) auditing, designator/footprint/MPN verification, and KiCad-style Gerber/drill stackup checks**.

Built for hardware engineering workflows across 4–8+ layer boards, HDI/rigid-flex handoffs, and DFM/DFA pre-release checks before sending fabrication packages to a board house.

## Checks Performed

- **BOM Integrity (`BOM-001`–`BOM-006`):** Detects missing designators, duplicate reference designators, non-standard designator prefixes for component categories, missing footprints, missing/placeholder MPNs on populated parts, and missing values.
- **Gerber & Drill Stackup Validation (`GBR-001`–`GBR-002`, `STK-001`):** Validates standard layer naming (`F_Cu`, `InN_Cu`, `B_Cu`, `Edge_Cuts`, `Drill`) and verifies minimum copper layer count (`--min-copper-layers`).
- **Dual Output & CI Exit Codes:** Generates `pcb_handoff_audit.json` and `pcb_handoff_checklist.md`, returning exit code `1` when `CRITICAL` handoff issues exist.

## Quickstart

Requires **Python 3.10+** (standard library only).

```bash
git clone https://github.com/B5IVE/kicad-gerber-bom-checker.git
cd kicad-gerber-bom-checker

python3 check_pcb.py sample_manifest.jsonl --min-copper-layers 4
```

## License

MIT

