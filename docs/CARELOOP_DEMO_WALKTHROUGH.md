# CareLoop demo walkthrough, with expected replies

Step-by-step tables for the Alexa+ simulator: what to say, the reply you should hear, and what each step shows. For setup and installation, see the [README](../README.md).

Related guides:
- [Click-by-click demo guide](CARELOOP_UI_DEMO_GUIDE.md): exact buttons and screens, with screenshots, on the seeded day.
- [Driving the simulator end to end](CARELOOP_SIMULATOR_WALKTHROUGH.md): the ideas behind each step, more flows, and troubleshooting.
- [UI guide](CARELOOP_UI_GUIDE.md): every section of every screen.

These tables start from an **empty** demo patient: `CARELOOP_AGENT_LLM=mock scripts/run_alexa_demo.sh --empty` (mock planner for exact replies). "Start fresh" below means stopping the script and running it with `--empty` again. With Ollama, the same tools run but wording may vary slightly. The Show also speaks the care disclaimer once per session.

**Link the accounts:** in the Alexa app panel, click **Enable CareLoop** for **Maya**, then for **Sam**.

**First use:** Maya's first request gets a short data-use disclosure ("Before I save anything: CareLoop keeps your care plan… Is that okay?"). Say **"yes"** and CareLoop carries on with the original request. This happens once. Optionally: "Alexa, call me Maya".

| # | Device | Say | Expected reply / what you'll see | Shows |
|---|---|---|---|---|
| 1 | Show | "Alexa, I got a new care plan from my clinic" | "Imported 3 plan items for your review. Approve each item on your screen to activate it." **Plan review** card with citations appears | Approval with citations |
| 2 | Show | Tap **Approve** on a card, then "Alexa, approve my plan" | "Plan task approved and now active. …" The card refreshes | MCP Apps → tool call |
| 3 | Show | "Alexa, let my brother Sam see my tasks and get updates for two weeks" | Alexa reads back exactly what Sam will be able to do and asks "Is that right?"; say "yes". Sam's Dot: "Maya invited you…" | Scoped, expiring consent |
| 4 | Alexa app | Click **Sam opens Maya's invitation link** | Dot: "Invitation accepted. You now have the access the patient chose." | Caregiver consent |
| 5 | Show | "Alexa, my pain is 8 yesterday" | "Check-in recorded." | Structured observation |
| 6 | Show | "Alexa, do my check-in" | "On a scale from 0 to 10, what's your pain score today?" The mic reopens | MCP elicitation |
| 7 | Show | "twelve" | "Sorry, please say a whole number from 0 to 10." | Answer validation |
| 8 | Show | "nine" | "Check-in recorded." **Sam's ring turns yellow** (second day at 7 or above) | Deterministic rule |
| 9 | Dot | "Alexa, any CareLoop updates?" | "You have 1 new CareLoop update." | Generic notification |
| 10 | Dot | "Alexa, what was Maya's pain score?" | "CareLoop records are unavailable." **No value is ever spoken** | Privacy on shared speaker |
| 11 | Dot | "Alexa, mark it seen" | "CareLoop update acknowledged." The ring clears | Acknowledgement |
| 12 | Show | "Alexa, get me ready for my appointment" | "Your visit handoff is ready on your private screen." **Handoff** card | Clinician handoff |
| 13 | Show | "Alexa, should I double my medication?" | "I can't give medical advice. Please contact your clinician…" Inspector shows **no tool call** | Safety boundary |
| 14 | Show | "Alexa, remove Sam" | "This will remove this caregiver's CareLoop access. Say confirm to continue, or cancel." | Destructive-action confirmation |
| 15 | Show | "confirm" | "Caregiver access revoked. It stops on their next request." | Revocation |
| 16 | Dot | "Alexa, any CareLoop updates?" | "You don't have access to the patient's CareLoop right now. If they invited you, open the invitation link in your Alexa app." Access denied immediately | Consent enforced |

Steps 6–8 also work by voice end to end: answer the question out loud when the mic reopens.

**Family tasks, questions and access log (add-on).** Start fresh, then import and approve the plan (steps 1–2):

| # | Device | Say / action | Expected |
|---|---|---|---|
| G | Show | "Alexa, let Sam help with my tasks", then **Sam opens Maya's invitation link** | Alexa reads the permissions back ("Sam will be able to see your tasks and be given tasks to do. Is that right?"); say "yes". Sam's Dot hears that he was invited |
| H | Show | "Alexa, Sam handles my evening task" | "Done. Sam will handle Complete the evening check-in at 7 PM." Backstage shows the simulated Alexa+ reminder. **Sam's Dot says "Maya gave you a new task."** with no detail and no ring |
| H2 | Dot | "Alexa, any CareLoop updates?" | "You have 1 new task from Maya." Counts only, no task name |
| I | Backstage | **Ring next reminder** | Sam's Dot: "Reminder for Sam: Maya's Complete the evening check-in." |
| J | Dot | "Alexa, what are my tasks for Maya?" (this also clears the new-task notice) then "Alexa, I've done Maya's evening task" | "You have 1 task to help Maya with: … at 7 PM." then "Thanks. I've recorded that you did it." |
| K | Show | "Alexa, add a question for my doctor: can I stop my medicine early" | "Saved. You have 1 question ready for your next appointment." Saved, not refused, and never read back |
| L | Show | "Alexa, get me ready for my appointment" | "…It includes 1 question for your clinician." The handoff shows who completed each task and any missed tasks |
| M | Show | "Alexa, who has seen my care data this week?" | "In the last 7 days, Sam …", listing what Sam viewed or did, never the content |

If an assigned task isn't marked done within an hour of its time, Sam's ring lights up with a generic update, and the miss appears in the handoff.

**Suggestions (add-on).** "Anything I should know?" raises what is worth a look from Maya's own records. What it says depends on what is there, so it can be shown on the seeded day:

| What is in the records | Maya says "Alexa, anything I should know?" and hears |
| --- | --- |
| A visit within 3 days, with saved questions | "Your visit is tomorrow. You have 1 question saved for your clinician. Want me to prepare the handoff?" A "yes" prepares the handoff |
| Checked in before, not today, after 6 PM | "You haven't checked in today. Want to do your check-in now?" |
| An assigned task missed in the last 2 days | "Sam missed Take a short walk." |
| Plan items still waiting for review | "3 plan items are waiting for your review. Want to go through them now?" |
| Nothing applies | "Nothing needs your attention right now." |
| "Turn suggestions off" | Suggestions answer "Suggestions are turned off." until "turn suggestions on" |

Suggestions are for the patient only: on Sam's Dot the same question gets "Suggestions are unavailable." A suggestion never quotes a saved question or a score.

**Multi-turn conversation (add-on).** Start fresh, do step G (Sam can help with tasks), then:

| # | Say | Expected |
|---|---|---|
| N | "Alexa, I got a new care plan from my clinic" | "…Want to go through them now?" The mic stays open |
| O | "yes" | "Item 1 of 3: Take a short walk, at 8 AM. Approve, change the time, give it to someone, skip, or stop?" |
| P | "make it 9" → "give it to Sam" | The walk moves to 09:00 and is approved; the evening task goes to Sam; item 3 (the alert rule) is asked |
| Q | "Alexa, show my tasks" | A new request **pauses** the review: "Okay, I've saved your place. 1 item left…" followed by the task summary |
| R | "Alexa, continue my review" → "approve" | Resumes at item 3: "Done: 3 approved." |
| S | "Alexa, Sam handles my evening task" → "Alexa, move it to 8 pm" | "it" = the task just mentioned: "Done. Complete the evening check-in is now at 8 PM." |
| T | "Alexa, do my check-in" → "four" → "yes" | Asks pain, then "Did you do Take a short walk today?", then "Check-in recorded. You did 1 of 1 task. Sam has Complete the evening check-in at 8 PM." |

**Prescription intake (add-on).** In the Alexa app panel, pick **Share a document → Sample: typed PDF** (or *scanned PDF* / *photo* to show the OCR fallback):

| # | Where | Action | Expected |
|---|---|---|---|
| A | Alexa app | Share the typed sample as Maya | About 10 s later the Show says "Your document is ready. 8 items need your approval, and 2 are flagged for a closer look. Medicine items are approved on your screen." and opens **Plan review** |
| B | Show screen | Read a card | Each item shows the exact source line (`p1:L5 · …`), the medicine "as written", a spoken name and editable suggested times |
| C | Show | "Alexa, approve my plan" | Medicine items are refused by voice: "That item needs your review on screen before it can be approved." |
| D | Show screen | Tick the flags on the pain rule, tap **Approve** | The rule becomes active only after its flags are confirmed |
| E | Alexa app | Share as **Sam** before and after Maya says "let Sam see my tasks and upload documents" | Refused, then accepted; Sam's Dot: "Thanks. I've sent it to Maya to review." |
| F | Alexa app | Share **Sample: prompt injection** | The planted "ignore all previous instructions…" line never becomes an item; nothing is activated |

**Reset for another run:** press **Reset demo data** in Backstage (seeded starting day), or restart with `scripts/run_alexa_demo.sh --empty` (nothing at all). Both remove only the demo patient's records.
