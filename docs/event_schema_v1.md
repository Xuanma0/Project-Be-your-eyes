# BYES Event Schema v1

Canonical references:
- English: `docs/English/event_schema_v1.md`
- Chinese: `docs/Chinese/event_schema_v1.md`

Name catalog highlights (tool events):
- `ocr.read`
- `risk.hazards`
- `seg.segment`
- `depth.estimate`
- `slam.pose`
- `map.costmap`
- `map.costmap_fused`
- `plan.request`
- `plan.context_alignment`
- `frame.input`
- `frame.ack`
- `frame.user_e2e`

`v4.82` highlight:
- `depth.estimate` payload can include optional `meta.refViewStrategy/provider/poseUsed`.
- Temporal depth consistency is reported in `report.json -> quality.depthTemporal`.

Version timeline:
- `docs/English/RELEASE_NOTES.md`
- `docs/Chinese/RELEASE_NOTES.md`

This page is a lightweight index so links to `docs/event_schema_v1.md` stay stable.
