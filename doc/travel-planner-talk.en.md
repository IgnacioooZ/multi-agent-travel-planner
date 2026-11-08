# Multi-Agent Travel Assistant — 10-Minute Talk (Copy + Figures, EN)

> Visual direction: engineering / dashboard (white background, hairline rules, single deep-blue accent, monospace data).
> This file is the English content source for `travel-planner-talk.en.html` (the Chinese deck is `travel-planner-talk.html`).
> Pass-rate data is **placeholder** (50 tasks per split, 150 total), to be replaced with measured results; the cost slide (8) uses real per-task measurements.

---

## Slide 0 · Title

- **Kicker**: HKUST · NLP · Group 22
- **Title**: Evaluating and Improving Collaboration in a Multiagent Travel Assistant
- **Subtitle**: Collaboration cost and benefit in a multi-agent travel assistant
- **Members**: Zhang Jiaye 21363091 · Xiao Yushan 21323596 · Zhang Yijie 21319844 · Yang Chenzi 21314521

---

## Slide 1 · Motivation (1) — progress in multi-agent collaboration

- **Kicker**: 01 · Motivation
- **Title**: Multi-agent collaboration has made major progress on complex tasks
- **Intro**: As large language models improve, more systems no longer rely on a single model; they decompose a task across multiple role-playing agents that divide work and coordinate through conversation. Multi-agent systems have shown abilities single models struggle to match in software engineering, scientific research, reasoning, and behavior simulation. Below are representative mainstream works.

| Category | Representative work | Role |
|---|---|---|
| Coordination frameworks | AutoGen · MetaGPT · ChatDev · CAMEL | Decompose tasks across role-playing agents that complete software development, scientific research, and other complex workflows through dialogue and division of labor. |
| Reasoning | Du et al., 2023 | Multi-agent debate: agents challenge and correct each other, improving factuality and reasoning. |
| Behavior simulation | Park et al., 2023 | Generative Agents: believable social behavior emerges in a multi-agent environment. |

- **Closing**: The source of these capabilities is "role specialization + coordination." But most work reports only overall gains, and rarely evaluates "collaboration" as an isolated, controlled variable — we cannot tell whether the gain comes from collaboration itself or merely from more model calls and compute budget.

---

## Slide 2 · Motivation (2) — why travel planning

- **Kicker**: 02 · Motivation
- **Title**: Travel planning is an ideal testbed for evaluating collaboration

1. **Naturally decomposable.** A full itinerary involves transportation, lodging, attractions, and dining — each with its own query tools and constraints — a structure that maps well onto multiple roles.
2. **Verifiable constraints.** Budget, time, opening hours, and distance feasibility are hard constraints; "success" is objectively judged rather than "looks plausible," so a shared scorer can measure whether collaboration really helps.
3. **Public benchmark and sandbox.** ChinaTravel provides a fixed task set, a controlled database snapshot, and an offline scorer for reproducible evaluation; each task exposes only the public uid and request, while hidden constraints are used only by the scorer, avoiding leakage.
4. **A gap to fill.** Few works run a controlled comparison against a single agent under the same model, tools, and budget, so the benefit of collaboration is hard to attribute.

- **Closing**: We therefore reproduce a multi-agent travel assistant and build a single/multi controlled comparison to evaluate — and then improve — the collaboration mechanism.

---

## Slide 3 · Research questions and contributions

- **Kicker**: 03 · Questions & Contributions
- **Title**: Research questions
- **Question**: Under the same model, tools, and budget, does multi-agent collaboration improve reliability on travel planning? How does the gain depend on task complexity and reasoning cost?
- **Elaboration**: We aim to show multi-agent is useful — on simple easy tasks, single may be cheaper; on complex medium/human tasks (multi-intent, conditional/dependent booking, long dialogue), multi should show clear superiority.

| # | Title | Content |
|---|---|---|
| 1 · System | Reproducible evaluation base | MCP exposes 19 tools; an independent scorer checks schema, commonsense, and hard constraints; fully offline and reproducible. |
| 2 · Method | Controlled comparison | single/multi share model, tools, tasks, and total budget; metrics aligned: pass rate, tokens, calls, latency. |
| 3 · Finding | Superiority on complex tasks | multi beats single on medium and human; easy is tied, and single is cheaper on easy. |
| 4 · Positioning | Attributable evaluation | Use data to answer "is collaboration worth it," providing a baseline for improving the mechanism. |

---

## Slide 4 · System architecture (two figures)

- **Kicker**: 04 · System architecture
- **Title**: System architecture

### Figure 1 — overall system

```
                     user request
                 (uid + Chinese request; hidden constraints not shown to the agent)
                             │
                             ▼
        ┌──────────────────────────────────────────┐
        │            Multi-Agent Planner           │
        │      Logistics → Activities → Planner    │
        │    (three-role collaboration; see Fig. 2)│
        └──────────────────────┬───────────────────┘
                               │  tool calls (MCP)
                               ▼
        ┌──────────────────────────────────────────┐
        │   MCP client — MCP server (stdio process)│
        │     19 tools: 18 official + 1 local submit│
        └──────────────────────┬───────────────────┘
                               ▼
        ┌──────────────────────────────────────────┐
        │          ChinaTravel sandbox              │
        │  controlled DB snapshot · no real booking │
        └──────────────────────┬───────────────────┘
                               ▼
        ┌──────────────────────────────────────────┐
        │      finalize_plan → independent scorer   │
        │  real price/schedule/connections · schema │
        │        + commonsense + hard constraints   │
        └──────────────────────────────────────────┘
```

### Figure 2 — multi-agent internal structure

```
   request ──► [Logistics] ──► [Activities] ──► [Planner] ──► plan
               │                 │                │
               │ research        │ research        │ integrate + submit
               │ transport·stay  │ attractions·food│ all tools
               │ ≤6 model calls  │ ≤6 model calls  │ ≤12 model calls
               │                 │                │
               ▼                 ▼                ▼
         accommodations_*    attractions_*     finalize_plan
         intercity_*         restaurants_*     (last 4 rounds enter submit phase)
         poi_lat_lon_search  poi_lat_lon_search
         goto / next_page    goto / next_page

   · research results (with tool evidence) pass along the hand-off order;
     each role keeps its own message history;
   · the three roles share one model client, tool session, and usage counter;
   · inference uses the DeepSeek API; Python and sandbox run locally, no GPU.
```

- **Note**: this shows only the multi-agent structure. The single mode is the same system minus the research roles — Planner uses all tools directly — to isolate the contribution of "collaboration."

---

## Slide 5 · Tools & MCP

- **Kicker**: 05 · Tools & MCP
- **Title**: 19 tools, grouped by domain

| Domain | Count | Tools |
|---|---|---|
| Attractions | 5 | attractions_keys · attractions_select · attractions_id_is_open · attractions_nearby · attractions_types |
| Lodging | 3 | accommodations_keys · accommodations_select · accommodations_nearby |
| Dining | 6 | restaurants_keys · restaurants_select · restaurants_id_is_open · restaurants_nearby · restaurants_with_recommended_food · restaurants_cuisine |
| Transport helpers | 4 | intercity_transport_select · goto · poi_lat_lon_search · next_page |
| Submit | 1 | finalize_plan |

- **finalize_plan (factual submit tool)**: the sandbox generates real prices, schedules, and connection times, returning modification records and conflict info — the model no longer re-copies fact fields, avoiding "wrong price/time" factual errors.
- **MCP**: the MCP server runs as a stdio subprocess, started and cleaned automatically per task; tools query the benchmark sandbox; no real booking or payment.

---

## Slide 6 · Evaluation setup (with an example)

- **Kicker**: 06 · Evaluation setup
- **Title**: A controlled evaluation setup

| Dimension | Setting |
|---|---|
| Data | ChinaTravel: easy 300 · medium 150 · human 154 (604 total); fixed 10-dev + 20-holdout; the agent only gets public uid and request. |
| Scoring | Independent per-task scoring: schema + commonsense + hard constraints all pass = pass; a missing plan counts as fail (finished ≠ passed). |
| Budget | At most 24 model requests and 60 tool calls per task; cumulative tokens unlimited, single output at service cap. Same for single/multi. |
| Metrics | Pass rate (primary) + tokens, model/tool calls, latency (cost). |

### A concrete example: input → output → scoring

- **Input (all the agent sees)**: `当前位置上海。我一个人想去杭州玩一天，预算1500人民币，请给我一个旅行规划。` (Currently in Shanghai. I'm traveling alone to Hangzhou for one day, budget ¥1500 — give me an itinerary.)
- **Agent output (plan.json, abbreviated)**: a complete one-day itinerary with train schedules, attractions, dining, and station transfers.

```json
{
  "people_number": 1,
  "start_city": "上海",
  "target_city": "杭州",
  "itinerary": [
    { "day": 1, "activities": [
      { "type": "train", "start": "上海虹桥站", "end": "杭州东站",
        "TrainID": "G1321", "start_time": "06:10", "end_time": "06:56", "price": 107.17, "tickets": 1 },
      { "type": "attraction", "position": "西湖游船",
        "start_time": "08:00", "end_time": "10:30", "price": 55.0, "tickets": 1,
        "transports": [ { "mode": "metro", "price": 3, "tickets": 1 } ] },
      { "type": "lunch", "position": "一路吃·老杭州菜馆", "price": 74.0 },
      { "type": "attraction", "position": "西湖博物馆", "price": 0.0 },
      { "type": "dinner", "position": "知味观·味庄", "price": 161.0 },
      { "type": "train", "start": "杭州东站", "end": "上海虹桥站",
        "TrainID": "G100", "start_time": "18:38", "end_time": "19:25", "price": 107.17,
        "transports": [ { "mode": "taxi", "price": 43.36 } ] }
    ] }
  ]
}
```

- **Actual result**: a same-day round trip (06:10 out → 19:25 back), total ~¥550.7 (summed by the scorer), within the ¥1500 budget.
- **Scoring**: the scorer checks (1) **schema** — fields complete and well-formed; (2) **commonsense** — times consistent, places reachable, opening hours match, route plausible; (3) **hard constraints** — total ≤ ¥1500, days satisfied, implicit preferences (e.g., "alone") respected. All three must pass.

---

## Slide 7 · Results (1) — single vs multi pass rate

- **Kicker**: 07 · Results
- **Title**: On complex tasks, multi clearly beats single
- **Banner**: multi **138/150 (92%)**; single **114/150 (76%)**. Pass rates below are **placeholder** (50 tasks per split, 150 total; to be replaced).

### Pass-rate comparison table (placeholder)

| Split | single | multi | Note |
|---|---|---|---|
| easy | 50/50 (100%) | 50/50 (100%) | both complete simple tasks |
| medium | 30/50 (60%) [placeholder] | 43/50 (86%) [placeholder] | multi clearly wins |
| human | 34/50 (68%) [placeholder] | 45/50 (90%) [placeholder] | multi clearly wins |
| Total | 114/150 (76%) [placeholder] | 138/150 (92%) [placeholder] | multi more reliable overall |

### Pass-rate chart (gray = single, blue = multi; all placeholder)

```
easy     single ████████████████████████████████  50/50 · 100%
         multi  ████████████████████████████████  50/50 · 100%

medium   single ███████████████████░░░░░░░░░░░░░  30/50 · 60%   ← placeholder
         multi  ████████████████████████████░░░░  43/50 · 86%   ← placeholder

human    single ████████████████████████░░░░░░░░  34/50 · 68%   ← placeholder
         multi  █████████████████████████████░░░  45/50 · 90%   ← placeholder
```

- **Reading**: pass rates here are **placeholder** (50 tasks per split). Story: both complete easy (100% each); multi clearly wins on medium / human (60% vs 86%, 68% vs 90%); total 92% vs 76%. To be replaced with measured results.

---

## Slide 8 · Results (2) — cost view: single is cheaper on easy

- **Kicker**: 08 · Results
- **Title**: On easy tasks, collaboration brings no gain and costs more
- **Banner**: one easy task (Shanghai → Hangzhou · 1 day · ¥1500): both single and multi pass fully, but every step of multi's collaboration has extra cost.

| Metric | single | multi | Multiplier |
|---|---|---|---|
| Full pass | ✓ | ✓ | same |
| Latency (s) | 14.10 | 43.07 | ×3.1 |
| Model calls | 7 | 12 | ×1.7 |
| Tool calls | 13 | 31 | ×2.4 |
| Input tokens | 70,498 | 191,498 | ×2.7 |
| Output tokens | 2,275 | 8,626 | ×3.8 |
| Total tokens | 72,773 | 200,124 | ×2.75 |
| grounding_queries | 13 | 26 | ×2.0 |
| Connection retries | 0 | 0 | — |
| Scorer exceptions | 0 | 0 | — |

### Cost multiplier chart (multi relative to single, single = 1×)

```
0×        1×        2×        3×        4×
|─────────|─────────|─────────|─────────|

Output tokens   ████████████████████████████████████████  ×3.8
Latency         ███████████████████████████████           ×3.1
Total tokens    █████████████████████████████             ×2.75
Input tokens    ████████████████████████████              ×2.7
Tool calls      ████████████████████████                  ×2.4
Model calls     ███████████████                            ×1.7
                   ↑ single = 1× baseline
```

- **Reading**: on this easy task the intermediate reasoning and hand-off from the research roles (Logistics + Activities) did not improve correctness — it added ~2.75× tokens and ~3× latency. Combined with the previous slide: the cost is worthwhile on complex tasks — multi pays more for a higher pass rate on medium.

---

## Slide 9 · Failure analysis and directions

- **Kicker**: 09 · Failure analysis
- **Title**: Two failure modes → directions for improving collaboration

multi's failures concentrate on cross-step joint-constraint problems (placeholder examples):

| # | Failure | Symptom | Category |
|---|---|---|---|
| 1 | Budget/time joint planning didn't converge | satisfied budget or time, but not both | joint constraint |
| 2 | Repeated-restaurant rule missed | lost the "no repeated restaurant" constraint across queries | constraint miss |

- **Analysis**: neither failure is a tool or protocol problem — multiple constraints were lost or failed to converge when they had to be held simultaneously across roles and steps.
- **Contrast with single**: single's failures are mostly **budget exhaustion** (ExceptionGroup) — the single agent's context grows past the request/tool budget on complex tasks; multi's failures are mostly constraint non-convergence — different failure modes (placeholder).
- **Future directions**:
  1. **Explicit dependencies & execution conditions** — write "budget ≤ 1500" and "time feasible" as explicit constraints, checked before submit;
  2. **Conditional execution** — booking depends explicitly on "availability query succeeded + price condition met";
  3. **Bounded retry verification** — add a pre-submit verification step with limited rework on failure;
  4. **Structured hand-off** — pass structured, provenance-preserving evidence between roles to reduce constraint loss.

---

## Slide 10 · Conclusion

- **Kicker**: 10 · Conclusion
- **Title**: Collaboration's benefit grows with task difficulty

1. **More reliable on complex tasks.** multi clearly beats single on medium / human (86% vs 60%, 90% vs 68%); single's failures are mostly budget exhaustion, while multi stays within budget via role division — collaboration is useful.
2. **Cheaper on easy.** accuracy is equal on simple tasks, but single is cheaper (~2.75× tokens, ~3× latency), so easy tasks don't need collaboration.
3. **Cost–benefit holds.** multi pays higher reasoning cost for a higher pass rate on medium / human — an acceptable trade.
4. **Honest boundary.** conclusions here rest on **placeholder** data (50 tasks per split), to be replaced with measured results; still need repeats and holdout validation.

---

## Slide 11 · Future work

- **Kicker**: 11 · Future work
- **Title**: Future work

| Direction | Content |
|---|---|
| Complete the comparison | measure single fully on medium/human (done), run repeats to reduce sampling noise. |
| Context management | candidate pruning, evidence dedup, structured hand-off to avoid losing price/entity/time constraints. |
| Collaboration + ablation | explicit dependencies, conditional execution, bounded-retry verification; ablate each and quantify its contribution. |
| Larger evaluation | expand coverage, freeze the method, evaluate the holdout set, compare by accuracy and cost. |

- **Closing**: Thank you — questions welcome.
