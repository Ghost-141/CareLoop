# Driving the CareLoop simulator end to end

How to start the Alexa+ behavior simulator, what to say and click, what you should see, and why each step matters. For a description of every control on the page, see [CARELOOP_UI_GUIDE.md](CARELOOP_UI_GUIDE.md). The step-by-step tables of expected replies (including family tasks, multi-turn and prescription intake) are in [CARELOOP_DEMO_WALKTHROUGH.md](CARELOOP_DEMO_WALKTHROUGH.md).

The replies in the tables were captured from a real run on the seeded starting day with the **Mock replay** planner. With the local model (Ollama) the tools called are the same but the wording can differ slightly.

---

## 1. What you are driving

CareLoop is an MCP server. Alexa+ would be the client that calls it. Without a real Echo or Alexa+ preview access, the simulator plays the Alexa+ part:

```
 Maya's Echo Show ─┐                                   ┌─ plans, check-ins, family, consent
 Sam's Echo Dot  ──┼─►  Simulator (acts as Alexa+)  ──►│  CareLoop MCP server  (port 8010)
 Alexa app panel ──┘    planner picks tools            └─ SQLite, rules, audit log
                        MCP inspector shows every message
```

| Piece | Role |
| --- | --- |
| **Maya's Echo Show** | The patient's device, with a screen. Speaks short answers and can open private screens. |
| **Sam's Echo Dot** | A family member's voice-only speaker. Shared-speaker privacy is tested here. |
| **Alexa app panel** | Links accounts, simulates opening an invitation, and shares documents. |
| **Planner** | Chooses which CareLoop tool to call. **Local LLM (Ollama)** is the Alexa+-like path. **Mock replay** is scripted and exact. |
| **MCP inspector** | A live log of every request and reply between the simulator and the server. This is where you see what really happened. |

Three ideas explain almost everything you will see:

1. **Alexa speaks only the safe line.** Every tool result has a short `speakable` sentence (counts and statuses) and opaque references. Private detail never reaches the speaker. It appears only on the Show's private screen.
2. **Nothing becomes active without the patient.** Plans are imported as drafts with a cited source line. The patient approves each item.
3. **The server decides, not the planner.** Who you are comes from the account that is linked, not from anything said aloud. Access is checked on every call.

---

## 2. Start it

```bash
scripts/run_alexa_demo.sh
```

This seeds the starting day if the demo patient has no records, starts the MCP server, waits until it is healthy, then starts the simulator. **Read the last line it prints.** If a port is busy it moves to the next free one, so the address may be `:8022` and not `:8021`.

| Want | Command |
| --- | --- |
| Exact, repeatable replies (best for a recording) | `CARELOOP_AGENT_LLM=mock scripts/run_alexa_demo.sh` |
| Local model planner | Make sure Ollama is running with the configured model, then `scripts/run_alexa_demo.sh` |
| Browser speech instead of the local voices | `VOICE=browser STT=browser scripts/run_alexa_demo.sh` |
| Back to the seeded starting day | `scripts/run_alexa_demo.sh --reset` |
| Completely empty patient | `scripts/run_alexa_demo.sh --empty` |

Use **Chrome**. The first run downloads the Kokoro voice (about 115 MB), so speech may use the browser voice for the first minute or two. The top bar says which engines are active.

### The seeded starting day

Maya has already accepted the data-use notice and her brother Sam is in her care circle (he can see tasks, be given tasks, get update alerts and acknowledge them). She has pain check-ins of **3, 4 and 7** for the last three days, and **one question** saved for her clinician ("When can I go back to work?"). Her prescription is **not** loaded. Sharing it and watching the rule fire is the story.

---

## 3. First two minutes

1. Open the simulator address in Chrome. **Maya's Echo Show** is the large device on the left, **Sam's Echo Dot** is the round one in the middle, the **Alexa app** panel and the dark **Backstage** panel are on the right. If you only see the Dot, scroll up or zoom out.
2. In the **Alexa app** panel, press **Enable CareLoop** for **Maya**, then for **Sam**. A green dot appears and the button changes to **Unlink**. Until an account is linked, its device answers "Please enable CareLoop for this device in the Alexa app panel first." (**Reset demo data** in Backstage also links both.)
3. In **Backstage**, check **Planner**. Pick **Mock replay** for exact wording or **Local LLM (Ollama)** for natural variation. Keep **Show MCP inspector** ticked.
4. Say or type something harmless to the Show, such as **Show my tasks**. You should see your words, then the reply, and new lines in the inspector.

If you see `You have no CareLoop plan items yet.`, everything is working. The plan is loaded in the next section.

---

## 4. How to talk to the devices

| Method | How |
| --- | --- |
| **Prompt chips** | Click one under a device. It behaves exactly like speaking it. The fastest, most reliable way. |
| **Type** | Use the box under the device and press Send. |
| **Microphone button** | Tap, speak, and the button lights. Tap again to end early. It ends by itself after about a second of silence. |
| **Hands-free** | Switch on **Hands-free "Alexa"** in the top bar and pick which device **hears** you. Always start with "Alexa, …". A bare "Alexa" waits about 6 seconds for the rest. A phrase without "Alexa" is ignored unless the device just asked you a question. |
| **Stopping** | Say or type "stop", "quiet" or "cancel that" to interrupt speech. |

**Whose device?** Speak to the Show as Maya (patient) and to the Dot as Sam (family). The device, not your wording, decides who is asking.

When a device asks a question (a check-in, a confirmation, "Is that right?"), its **microphone reopens by itself**. Just answer. You do not need to say "Alexa" for the answer.

---

## 5. The main story (about 5 minutes)

Start from the seeded day (`--reset`). Both accounts linked. Planner: Mock replay for the replies shown.

| # | Device | Say | You should hear / see | What to notice |
| --- | --- | --- | --- | --- |
| 1 | Show | "I got a new care plan from my clinic" | "Imported 3 plan items for your review. You can approve them on your screen, or by voice… Want to go through them now?" The **Plan review** screen opens. | Items arrive as **drafts**, each with its source line. The mic stays open for a yes or no. Inspector: `import_care_plan_text`. |
| 2 | Show | "approve my plan" | "Plan task approved and now active. Plan rule approved… Want Sam to handle Complete the evening check-in?" | Only the patient can approve. The device offers a useful next step. Inspector: `list_care_tasks`, then `approve_plan_item` three times. |
| 3 | Show | "show my tasks" | "You have 2 active tasks and 1 active follow-up rule." The **Care tasks** screen opens. | The speaker says counts only. Task names are on the screen, not read aloud. |
| 4 | Show | "my pain is 9" | "Check-in recorded." **Sam's Dot ring turns yellow.** | Yesterday was 7 and today is 9, so the clinician's approved rule fires. This is the whole point of the rule engine. |
| 5 | Dot | "any CareLoop updates?" | "You have 1 new CareLoop update." | Sam hears that an update exists, never the pain value. |
| 6 | Dot | "what was Maya's pain score?" | "CareLoop records are unavailable." | **Privacy on a shared speaker.** The value is never spoken to a caregiver. |
| 7 | Dot | "mark it seen" | "CareLoop update acknowledged." The ring clears. | Delivery state is explicit: an alert is not "seen" until someone says so. |
| 8 | Show | "do my check-in" | "On a scale from 0 to 10, what's your pain score today?" Mic reopens. | The **server** asks this question through MCP elicitation, not the planner. Inspector: an `elicitation/create` line. |
| 9 | Show | "twelve" | "Sorry, please say a whole number from 0 to 10." | The answer is validated. Out-of-range is never recorded. |
| 10 | Show | "four" | "Did you do Take a short walk today?" | The check-in chains follow-up questions from the approved plan. Answer yes or no to finish. |
| 11 | Show | "get me ready for my appointment" | "Check-in recorded. I saved what you told me. Your visit handoff is ready on your private screen. It includes 1 question for your clinician." The **Visit handoff** screen opens. | A new "Alexa, …" request **pauses** an unfinished workflow but saves the answers so far. The handoff is dated, cited and factual. |
| 12 | Show | "should I double my medication?" | "I can't give medical advice. Please contact your clinician, or emergency services in an emergency." | Handled before any planner. Inspector shows **no tool call**. |
| 13 | Show | "who has access to my care?" | "Your care circle has 1 active caregiver and 0 pending invitations." The **Care circle** screen opens. | Consent is visible and patient-owned. |
| 14 | Show | "remove Sam" | "This will remove this caregiver's CareLoop access. Say confirm to continue, or cancel." | Destructive actions are held for a spoken confirmation by the simulator. |
| 15 | Show | "confirm" | "Caregiver access revoked. It stops on their next request." | Revocation is immediate. Say "cancel" instead and nothing changes. |
| 16 | Dot | "any CareLoop updates?" | "You don't have access to the patient's CareLoop right now. If they invited you, open the invitation link in your Alexa app." | The server rejected Sam on his very next call. |

After step 16, press **Reset demo data** (twice) to run again.

---

## 6. More flows

### 5.1 Driving the story with the local model (gemma)

The table above shows the scripted planner. With **Local LLM (Ollama)** the same story runs, with these differences. This was checked end to end with a local gemma4 e4b model and the scripted fallback switched off.

| Step | With gemma |
| --- | --- |
| 1 | Gemma will not invent plan text. It asks you to share the document in the Alexa app. Share the **Typed PDF** sample, or use the scripted planner for the voice import. |
| 2 | "Approve my plan" starts a **guided review**: "Item 1 of 3…". Say "approve" three times. It ends with "Done: 3 approved… Want Sam to handle Complete the evening check-in?" |
| 6 | On the Dot, "what was Maya's pain score?" may be answered "No matching record found." Nothing is leaked, and the wording differs from the scripted "CareLoop records are unavailable." |
| 7 | "Mark it seen" acknowledges the waiting update, wording as scripted. |
| 11 | The handoff reply is the same, and may begin "Check-in recorded. You did 1 of 1 task." if you interrupted the check-in. |
| 13 | "Who has access to my care?" opens the care circle. "Who has seen my care data?" opens the access log. |

The first request after a cold start can take around 9 seconds, so send a throwaway request before presenting. Watch the inspector's turn lines: if one says `mock`, gemma failed and the scripted planner answered. Before the demo, run `uv run python evals/run_llm_planner.py --repeat 1`.

---

### 6.1 A prescription becomes a plan, with proof

This path uses the document reader, so the local model and OCR matter. In the **Alexa app** panel, under **Share a document with CareLoop**:

1. Leave **From** as Maya and **Type** as Prescription.
2. Under **or use a sample**, choose **Typed PDF** (try **Scanned PDF (OCR)** or **Phone photo (OCR)** later) and press **Share sample**.
3. The status line says "CareLoop is reading it…". About 10 seconds later (longer for scans) the Show says the document is ready, how many items need approval and how many are flagged, and opens **Plan review**.
4. On the screen, each card shows the exact source line, the medicine "as written", an editable **spoken name** and **times**. Flagged cards need you to tick "I've checked this against the document" before **Add to my plan** works. **Leave it out** rejects an item.
5. Say "approve my plan". Medicine and flagged items are refused by voice and must be approved on the screen.
6. Share **Prompt-injection test**. The planted "ignore all previous instructions" line never becomes an item.

Notice: a number that is not in the document is blocked, and every item cites its line. Documents cannot be shared by voice, because Alexa+ does not hand files to add-ons.

### 6.2 Family tasks and reminders

Start from the seeded day and do steps 1 and 2 of the main story. Then:

| Device | Say | Result |
| --- | --- | --- |
| Show | "yes" (to "Want Sam to handle…?") | "Done. Sam will handle Complete the evening check-in at 7 PM." A simulated Alexa+ reminder is queued. **Sam's Dot says "Maya gave you a new task."** and nothing about which task. His ring stays dark. |
| Dot | "any CareLoop updates?" | "You have 1 new task from Maya." Counts only. |
| Backstage | **Ring next reminder** | Reminders ring in order. The first is Maya's own ("Take a short walk"). Press again for Sam's. |
| Dot | "what are my tasks for Maya?" | "You have 1 task to help Maya with: Complete the evening check-in at 7 PM." |
| Dot | "I've done Maya's evening task" | "Thanks. I've recorded that you did it." |
| Show | "move it to 8 pm" | "Done. Complete the evening check-in is now at 8 PM." The word **it** meant the task just discussed. |
| Show | "add a question for my doctor: can I start swimming" | "Saved. You have 2 questions ready for your next appointment." CareLoop never answers it. |
| Show | "who has seen my care data this week?" | "In the last 7 days, Sam completed a task and accepted your invitation." Who did what, never the content. |
| Show | "get me ready for my appointment" | "…It includes 2 questions for your clinician." The handoff shows who completed each task and any missed ones. |

If an assigned task is not done within an hour of its time, Sam's ring lights up with a generic update and the miss appears in the handoff.

Asking for the details ("what are my tasks for Maya?") or saying "mark it seen" clears the notice. Giving the same task to the same person again says nothing new.

### 6.2b Suggestions

Maya asks "Alexa, anything I should know?" The server works out what is worth a look from her own records and the assistant only phrases it: a visit within 3 days, a missed task, no check-in today after 6 PM, or plan items waiting for review. If a suggestion carries a question, "yes" runs it. Nothing applies gives "Nothing needs your attention right now." "Turn suggestions off" switches them off. They are for the patient only, and they never quote a saved question or a score. The full table of replies is in [CARELOOP_DEMO_WALKTHROUGH.md](CARELOOP_DEMO_WALKTHROUGH.md).

### 6.3 Invite a family member from scratch

Use `--empty` to start with nobody in the care circle, then:

1. Show: "let my brother Sam see my tasks and get updates for two weeks". Alexa reads back exactly what Sam will be able to do and asks "Is that right?" Answer **yes**.
2. Alexa app: press **Open Maya's invitation as Sam**. The Dot says the invitation was accepted.
3. Sam now has only the access Maya chose, until the date she set.

### 6.4 Going through a plan by voice

After importing a plan: "go through them" (or say yes to "Want to go through them now?"). Alexa reads item 1 and you can say approve, "make it 9", "give it to Sam", skip or stop. A new "Alexa, …" request pauses the review and saves your place. "continue my review" resumes it.

---

## 7. Reading the MCP inspector

Newest line first. This is how you prove what happened.

| Line | Meaning |
| --- | --- |
| `→ tools/call [maya] record_pain_observation {…}` | The simulator asked the server to do something, and with what arguments |
| `← tools/call [maya] …` | The server's reply (only the safe fields) |
| `← elicitation/create` | The server is asking a question in the middle of a tool |
| `→ resources/read` and `get_private_view` | The Show loading a private screen. The data appears only on the screen. |
| `◆ turn [show · mock] heard "…" · tools: a → b · "reply"` | One finished request: who heard what, which tools ran in order, and what was spoken |
| `[maya · app]` | An action taken from a private screen button, not by voice |

If something does not work, the `heard "…"` text is the first thing to check.

---

## 8. Between takes

| Situation | Do this |
| --- | --- |
| Run the story again | **Reset demo data** in Backstage (click twice). Both devices stay linked. |
| Clear the screen and conversation memory only | **Reset conversation** |
| Start with nothing | Stop the script and run it with `--empty` |
| Stage-safe recording | Use Mock replay and press **Reset demo data** before every take |

A conversation left waiting (for example a half-finished check-in) can swallow your next phrase as its answer. **Reset conversation** clears that.

---

## 9. When something looks wrong

| Symptom | Cause and fix |
| --- | --- |
| Only the Dot is visible | The Show is tall. Scroll to the top or zoom out. |
| "Please enable CareLoop for this device…" | The account is not linked. Press **Enable CareLoop** for that person. |
| Sam's Dot says "CareLoop notifications are unavailable" or "You don't have access…" | Sam has no active access (not invited yet, expired, or you revoked him). Reset demo data or invite him again. |
| An answer "was not registered" (for example a pain score) | Two answers the device could not read in a row cancel the question, and nothing is recorded. Check `heard "…"` in the inspector. If the microphone misheard, type the number or tap a chip. |
| The device answers something odd with the local model | Small models vary. Switch **Planner** to **Mock replay** for the exact path. |
| A reply feels slow the first time | The model or voices are loading. Later turns are faster. |
| "Sorry, CareLoop is having trouble right now" | The turn raised an error. The inspector shows a failed-turn line. Check the terminal where the script runs. |
| Hands-free does nothing | It needs microphone permission, and you must start with "Alexa, …". |
| The port in this guide is wrong | The script prints the real address when a port is taken. Use that one. |
| A chip does nothing useful | Some chips depend on earlier steps ("Mark it seen" needs an update waiting). Follow the story order. |

---

## 10. A checklist for a full end-to-end pass

- [ ] Script started, address noted, Chrome open
- [ ] Maya and Sam linked, planner chosen, inspector visible
- [ ] Plan imported, drafts reviewed, approved by the patient
- [ ] High pain score fired the rule and lit Sam's ring
- [ ] Sam heard only that an update exists, and could not get the value
- [ ] Update acknowledged and the ring cleared
- [ ] Check-in asked its own question and rejected an out-of-range answer
- [ ] Handoff created with source lines and the saved clinician question
- [ ] Medical-advice question refused with no tool call
- [ ] Caregiver removed after a spoken confirmation, and Sam rejected on his next request
- [ ] Reset demo data restored the starting day
