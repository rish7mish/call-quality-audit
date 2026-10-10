# Root-cause grouping (turns individual failures into named problems)

- **Code:** `root_causes.py` -> `CLUSTER_SYSTEM`
- **Model:** Claude Sonnet 5.5, one call for all failures
- **Input:** Numbered list of every Fatal / Non-Fatal check: check name, cause type, one-line root cause
- **Output:** JSON groups. Ranking is done by code, not the AI: priority = % of calls with the problem x severity (Fatal 3, Non-Fatal 1)
- **Exported:** 2026-10-10

## The prompt (system instructions)

````text
You group call-quality failures of an AI voice bot into ROOT CAUSES.
You get a numbered list of failures. Each has: the checklist item that failed, a cause type, and a one-line root cause.
Group failures that share the same underlying reason (something one fix to the bot, its speech recognition, its knowledge
or its call flow would solve) into 5-15 groups. Failures of different checklist items CAN share a root cause
(e.g. 'bot does not read back numbers' can cause both quantity and spec errors).
Every failure number must appear in exactly one group. Use a final group 'Other / one-off' only for true leftovers.
Reply with ONLY JSON:
{"groups": [{"name": "<short problem name, max 8 words>",
             "description": "<one sentence: what goes wrong and why>",
             "cause_type": "<one of: prompt, asr_stt, knowledge, flow_logic, tts_voice, data_mapping>",
             "fixable_by_prompt": true/false,
             "members": [<failure numbers>]}]}
````

