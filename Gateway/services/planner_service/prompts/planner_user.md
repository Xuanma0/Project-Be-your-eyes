Prompt version: {{PROMPT_VERSION}}
runId={{RUN_ID}}, frameSeq={{FRAME_SEQ}}

ContextPack prompt:
{{CONTEXT_PROMPT}}

Risk summary (JSON):
{{RISK_SUMMARY_JSON}}

Constraints (JSON):
{{CONSTRAINTS_JSON}}

Hazard severity mapping:
- critical: immediate danger, prefer confirm/stop compatible outputs.
- warning/medium: caution, concise speak/overlay guidance.
- low: normal assistive guidance.

Output strictly one JSON object (byes.action_plan.v1).
