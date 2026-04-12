# AscenAI Prompt Engineering Standard

**Version:** 2.0  
**Applies to:** All agents built on the AscenAI platform  
**Owner:** Platform Engineering

---

## 1. Overview

Every agent prompt on AscenAI is assembled at runtime by `build_xml_system_prompt()` in `app/prompts/system_prompts.py`. The output is a single XML document wrapped in an `<agent>` root element with exactly **9 semantic sections**.

**Why XML?** XML gives the LLM explicit structural boundaries between concerns (identity vs. constraints vs. instructions). This produces more predictable, controllable behavior than free-form prose prompts, and makes it easy to audit what the model was told.

**Why 9 sections?** Each section has a single responsibility. When behavior is wrong, you look at one section — not a 400-line blob.

---

## 2. The 9 Sections — Reference

Every prompt follows this exact shape. Sections that have no content are omitted.

```xml
<agent>
  <identity>      — Who the agent is, tone, language rules          </identity>
  <objective>     — What success looks like (from playbook)         </objective>
  <instructions>  — Operator-defined custom behavior                </instructions>
  <constraints>   — Guardrails: blocked topics, keywords, rules     </constraints>
  <tools>         — Available tools and when to call them           </tools>
  <memory>        — Knowledge base, history, customer, variables    </memory>
  <redaction>     — PII handling rules (always present)             </redaction>
  <playbook>      — Step-by-step workflow for the active playbook   </playbook>
  <output_contract> — Source priority, format rules, never-do list  </output_contract>
</agent>
```

### 2.1 `<identity>`

**What goes here:**
- The agent's name and business type
- Personality description (if set on the Agent model)
- Tone (derived from the active playbook's `tone` field)
- Language protocol (auto-detect rules or fixed language)

**For voice agents**, identity includes the full voice delivery rules, scope enforcement, prompt injection resistance, emergency protocol, and confirmation gate rules. These live here because they define *who the agent is and how it behaves* — not what it's blocked from doing.

**What does NOT go here:** instructions, workflow steps, guardrails.

---

### 2.2 `<objective>`

**What goes here:**
- The playbook's `description` field, framed as a goal statement
- A success criterion

**Only emitted** when the active playbook has a non-empty `description`. If no playbook is active, this section is omitted.

**Example:**
```xml
<objective>
Your goal: Guides a customer through a refund request.
Success means: The customer's request is fully resolved within the scope of this playbook.
</objective>
```

---

### 2.3 `<instructions>`

**What goes here:**
- The `Agent.system_prompt` field — custom instructions set by the operator at agent creation time
- Supports variable references: `$[vars:name]`, `$[tools:name]`, `$[rag:name]`

**Only emitted** when `agent.system_prompt` is non-empty.

**Rules:**
- Max 2,000 characters (truncated with notice if exceeded)
- This is for *behavioral* instructions, not for workflow steps (those go in `<playbook>`)

---

### 2.4 `<constraints>`

**What goes here:**
- Three sub-sections: `<global>`, `<agent>`, `<custom>`
- `<global>` — platform-wide blocked topics and restricted keywords (from `global_rules`)
- `<agent>` — agent-specific blocked/allowed topics and restricted keywords
- `<custom>` — operator-defined freeform rules with category labels

**What does NOT go here:** PII/redaction rules (those go in `<redaction>`), workflow logic (goes in `<playbook>`).

---

### 2.5 `<tools>`

**What goes here:**
- List of available tools with name and description
- Usage priority rule
- Confirmation requirement for high-risk tools

**Only emitted** when `agent_config.tools` is non-empty.

**Important:** The LLM should never infer or hallucinate tool names. If a tool isn't listed here, it should not be called.

---

### 2.6 `<memory>`

**What goes here — as nested sub-tags:**

| Sub-tag | Content | Source |
|---|---|---|
| `<knowledge>` | RAG-retrieved knowledge base snippets (max 5, 500 chars each) | `context_items` with `type="knowledge"` |
| `<history>` | Recent conversation history summaries (max 3, 300 chars each) | `context_items` with `type="history"` |
| `<customer>` | Customer name from long-term memory | `business_info.customer_profile.name` |
| `<corrections>` | Few-shot examples from operator feedback (last 10) | `corrections` list |
| `<variables>` | Session and global variable values | `AgentVariable` list + `session_metadata.variables` |

Each sub-tag is only emitted when it has content.

---

### 2.7 `<redaction>`

**What goes here:**
- Platform baseline PII rules (always present, cannot be removed)
- Operator-defined additional PII rules from `guardrails.pii_redaction`

**Always emitted.** This section is non-negotiable — every agent gets it.

The baseline rules prohibit: full credit card numbers, SSNs, passwords, full DOBs, API keys, stack traces, internal URLs, database IDs.

---

### 2.8 `<playbook>`

**What goes here — as nested sub-tags:**

| Sub-tag | Content |
|---|---|
| `<step id="1">` | The playbook's main `instructions` field (expanded, max 3,000 chars) |
| `<rules>` | Always-do and never-do directives (from `dos` and `donts` lists) |
| `<scenarios>` | Up to 10 trigger → response pairs (from `scenarios` list) |
| `<out_of_scope>` | What to say when the user asks something out of scope |
| `<fallback>` | What to say when the agent cannot answer |

**Only emitted** when an `AgentPlaybook` is active and has a `config` dict.

---

### 2.9 `<output_contract>`

**What goes here:**
- Source priority ordering (playbook → knowledge → tools → "I don't know")
- Format rules (prose only, no markdown tables)
- Hallucination prohibition
- Tool call format requirement

**Always emitted.** This section tells the model *how to behave* regardless of what it knows.

---

## 3. Canonical Playbooks

The platform ships 7 built-in playbooks in `app/schemas/playbook.py`. These cover the universal SMB interaction patterns. Use them as-is or fork them for custom workflows.

| ID | Name | Use When |
|---|---|---|
| `refund_v1` | Refund & Returns | Customer wants a refund, return, or chargeback |
| `booking_v1` | Booking & Appointment | Customer wants to schedule an appointment or reservation |
| `lead_qualification_v1` | Lead Qualification | Inbound interest — collect contact info and route |
| `order_handling_v1` | Order Handling | Customer wants to place an order (e-commerce, restaurant) |
| `customer_support_v1` | Customer Support | General help request, issue, or complaint |
| `payment_checkout_v1` | Payment & Checkout | Customer wants to pay for something |
| `escalation_handoff_v1` | Escalation to Human | Customer explicitly asks for a human agent |

### When to use vs. fork

**Use a canonical playbook directly** when:
- The workflow matches the canonical description exactly
- You only need to change the `trigger_keywords`

**Fork a canonical playbook** (copy and give it a new `id`) when:
- The workflow has different steps or branching logic
- The tool names are different (e.g., `stripe_create_payment` → `square_charge`)
- You need industry-specific validation (e.g., NHS number validation for clinic bookings)

**Do NOT create a new playbook** when:
- The only difference is wording → use `AgentPlaybook.config.instructions` to override
- The difference is a blocked topic → use `AgentGuardrails`
- The difference is a custom rule → use `AgentGuardrails.config.custom_rules`

---

## 4. Reusable XML Modules

These are conceptual building blocks that appear inside `<playbook>` sub-tags. They are not separate files — they are patterns to follow when authoring playbook steps.

### `<confirmation_step>` pattern

Use inside a `WaitInputStep` when the action is irreversible (payment, booking, SMS):

```python
WaitInputStep(
    id="confirm_action",
    prompt_to_user=(
        "To confirm: {{action_summary}}. "
        "Shall I proceed? (yes / no)"
    ),
    variable_to_store="user_confirmation",
    validation_regex=r"^(yes|no|y|n)$",
    error_message="Please reply with 'yes' or 'no'.",
    next_step_id="route_confirmation",
)
```

Always follow with a `ConditionStep` that branches on `yes/y` vs `no/n`. Never skip this for high-risk tools.

### `<escalation_step>` pattern

Use a `ToolStep` calling `escalate_to_human` followed by an `EndStep` with `status="escalated"`:

```python
ToolStep(
    id="escalate",
    tool_name="escalate_to_human",
    argument_mapping={"issue_summary": "{{customer_issue}}"},
    output_variable="escalation_result",
    on_error="continue",  # Always continue — don't fail if escalation tool errors
    next_step_id="escalation_end",
)
EndStep(
    id="escalation_end",
    final_message_template="Your reference is {{escalation_result.ticket_id}}. An agent will be with you shortly.",
    status="escalated",
)
```

### `<tool_call_rule>` pattern

In `AgentPlaybook.config.dos`, add:
```
"Only call the `tool_name` tool when the customer has confirmed their intent"
```

In `AgentPlaybook.config.donts`, add:
```
"Never call `tool_name` without collecting [required_field] first"
```

---

## 5. Variable Reference Syntax

Use these inside `AgentPlaybook.config.instructions`, `dos`, `donts`, `scenarios`, and `Agent.system_prompt`:

| Syntax | Resolves to | Example |
|---|---|---|
| `$[vars:name]` | Runtime or default variable value | `$[vars:order_id]` → `ORD-12345 (variable: order_id)` |
| `$[tools:name]` | Tool name reference (existence check) | `$[tools:stripe_create_refund]` → `the \`stripe_create_refund\` tool` |
| `$[rag:name]` | Knowledge base reference | `$[rag:menu]` → `the 'menu' knowledge base` |

If a variable is unknown, it resolves to `[unknown variable: name]`. If a tool is unregistered, it resolves to `[unregistered tool: name]`.

---

## 6. How to Create a New Agent

### Step 1 — Create the Agent

Set `Agent.system_prompt` only if you need custom behavioral instructions that don't fit in a playbook. Leave it empty if a playbook covers all the behavior.

### Step 2 — Select or Fork a Canonical Playbook

Look at the table in Section 3. If a canonical playbook matches your use case, use it. If not, fork the closest one and change only what's different.

### Step 3 — Configure the Playbook

The `AgentPlaybook.config` dict is what the platform uses — NOT the `PlaybookDefinition` schemas (those are for the durable state machine). Set:

```json
{
  "instructions": "Main behavioral instructions for this playbook",
  "tone": "professional | friendly | casual | empathetic",
  "dos": ["Always verify X before Y"],
  "donts": ["Never reveal Z"],
  "scenarios": [{"trigger": "user phrase", "response": "agent response"}],
  "out_of_scope_response": "I can only help with ...",
  "fallback_response": "Let me connect you with someone who can help.",
  "tools": ["tool_name_1", "tool_name_2"]
}
```

### Step 4 — Set Guardrails

Use `AgentGuardrails` for blocked topics, blocked keywords, allowed topics, and PII redaction rules. Do not put guardrail logic into playbook instructions.

### Step 5 — Test

See Section 8 (Testing) for the verification checklist.

---

## 7. When NOT to Create a New Template

Before creating anything new, ask these questions:

| Question | If yes → |
|---|---|
| Does an existing canonical playbook cover this workflow? | Use it |
| Is the only difference the wording of instructions? | Edit `config.instructions` |
| Is the only difference a blocked topic or keyword? | Update `AgentGuardrails` |
| Is the only difference a custom rule? | Add to `AgentGuardrails.config.custom_rules` |
| Is the only difference a scenario (trigger → response)? | Add to `config.scenarios` |
| Does the workflow have different steps OR different tools? | Fork the closest canonical playbook |
| Is this a completely new interaction pattern not in the 7 canonical playbooks? | Create a new `PlaybookDefinition` |

**The rule:** 7 canonical playbooks should cover 90% of SMB use cases. New templates require a documented justification.

---

## 8. Governance

### 8.1 Versioning

Prompts are versioned via the `PromptVersion` model (`app/models/prompt.py`).

- Use `POST /agents/{id}/prompt-versions` to create a version snapshot before making changes
- Versions are immutable once created — never edit a deployed version
- To roll back, activate a previous version via `POST /prompt-versions/{id}/activate`
- Use semantic versioning in playbook `version` fields: `1.0.0`, `1.1.0`, `2.0.0`

### 8.2 Safety Review Checklist

Before deploying any new or modified prompt/playbook:

- [ ] No hardcoded PII (names, emails, phone numbers, card numbers)
- [ ] No instructions that reveal the system prompt to users
- [ ] Confirmation gate present for all high-risk tool calls (payment, SMS, email)
- [ ] `out_of_scope_response` is set and accurate
- [ ] `fallback_response` is set
- [ ] `donts` explicitly blocks the most likely misuse patterns for this use case
- [ ] For medical/health agents: emergency keywords trigger the emergency protocol (handled by the orchestrator, but verify it is not disabled)
- [ ] Tested against at least 3 adversarial inputs (see ANTIFRAILTY_CHECKLIST in `voice_agent_guardrails.py`)

### 8.3 Change Management

1. Create a `PromptVersion` snapshot of the current state
2. Make changes in `draft` or `staging` environment only
3. Run the safety checklist
4. Run the test cases (Section 8.4)
5. Activate in staging, monitor for 1 session cycle
6. Activate in production via the version activation API

**Never** edit the active production version directly.

### 8.4 Test Cases

For every playbook, write tests covering:

1. **Happy path** — complete the workflow successfully end to end
2. **Cancellation** — user says "no" at the confirmation step
3. **Out-of-scope request** — verify `out_of_scope_response` is returned
4. **Invalid input** — verify validation errors are surfaced correctly
5. **Tool failure** — verify graceful fallback when a tool errors
6. **Escalation trigger** — verify escalation happens at the right point

---

## 9. Common Mistakes

### Mistake 1 — Putting workflow logic in `instructions`

`Agent.system_prompt` is for behavioral rules ("always be polite", "never discuss competitors"). Multi-step workflow logic belongs in `AgentPlaybook` with proper `PlaybookDefinition` steps. Freeform instructions cannot be tracked or tested the same way.

### Mistake 2 — Creating a new template when a scenario would suffice

If you need a specific response to a specific trigger, add it to `config.scenarios`. Do not create a new playbook for every trigger variant.

### Mistake 3 — Not setting `out_of_scope_response`

Without this, the agent will attempt to answer anything — including questions it shouldn't. Always set it.

### Mistake 4 — Skipping the confirmation gate for high-risk tools

If your playbook calls `stripe_create_payment`, `send_sms`, or `send_email` and there is no `WaitInputStep` before it, that is a bug. Add a confirmation step.

### Mistake 5 — Using variable references that aren't registered

`$[vars:order_id]` only resolves if `order_id` is a registered `AgentVariable` or is set in `session_metadata.variables`. Unregistered references display as `[unknown variable: order_id]` in the prompt — confusing the model.

### Mistake 6 — Adding guardrail logic to playbook `donts`

`donts` are for workflow-specific rules ("never process without verification"). Platform-wide safety rules (content policy, PII) belong in `AgentGuardrails`, not in playbook config. Duplicating them creates maintenance burden and inconsistency.

### Mistake 7 — Editing the `PlaybookDefinition` constants for runtime behavior

`REFUND_PLAYBOOK`, `BOOKING_PLAYBOOK`, etc. are **templates** — static definitions used as starting points. Runtime behavior is controlled via `AgentPlaybook.config` in the database. Never modify the constants to customize a specific business's behavior.
