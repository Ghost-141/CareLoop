# CareLoop: three-minute video demo

The video uses the Alexa+ behavior simulator (`scripts/run_alexa_demo.sh`) on **seeded synthetic data**. Every reply quoted below came from a dry run on seeded data on Oct 16, 2026, using the mock planner. With a model as the planner the same tools run, but the wording can vary slightly. Task names such as "Evening dressing change" come from the document-reading model, so they can differ too.

**Don't name a model in the video.** In production Alexa+ supplies its own language model and chooses the tools; the simulator stands in for it. If asked: "CareLoop works with whatever model is behind Alexa+. To run the simulator, any OpenAI-compatible API works." The plan review card says only "organised by an AI model".

Never show `.env`, tokens or database paths on screen. All people and documents are fictional.

## The seeded starting day

`scripts/run_alexa_demo.sh --reset` (or **Reset demo data** in Backstage) puts the demo patient in this state:

| What | Seeded value | Why it's there |
|---|---|---|
| Maya | Has accepted data use; spoken name "Maya" | The video skips the one-time disclosure |
| Sam | In Maya's care circle: see tasks, do tasks, get and acknowledge updates | The video skips the invite steps |
| Pain check-ins | 3, 4 and 7 on the three days before today | Today's 8 is the second day at 7 or higher, so the prescription's rule fires on camera |
| Question for the clinician | "When can I go back to work?" | The handoff has more than one question |
| Prescription | **Not loaded** | Sharing and reviewing it is the opening of the video |

The check-in dates are relative to the day you reset. **Reset on the day you record.**

## Before recording

```bash
# a model for the simulator: any OpenAI-compatible API in .env (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL), or Ollama running
scripts/run_alexa_demo.sh --reset             # seeds the starting day, starts both servers
```

1. Open the printed URL (usually http://127.0.0.1:8021) in Chrome at 1440×900.
2. Press **Reset demo data** twice in Backstage. Both devices are linked and the screens are clear.
3. Do a full practice run if you like. Then press **Reset demo data** again just before you record.
4. Keep **Show MCP inspector** on. It shows judges the real MCP traffic.

## Shot list

| Time | Do | You'll see and hear | Say (voice-over) |
|---|---|---|---|
| 0:00–0:15 | Start on the simulator with both devices idle | Maya's Echo Show and Sam's Echo Dot | "Alexa+ can remember a prescription. CareLoop makes every instruction Alexa says traceable to the line it came from, approved by the patient." |
| 0:15–0:40 | Alexa app panel: **Share a document**, from Maya, **Typed PDF**, **Share sample** | The Show answers at once ("Got it. I'm reading your document now. I'll tell you as soon as it's ready."). About 10 to 30 s later it says: "Your document is ready. 8 items need your approval, and 2 are flagged for a closer look. Medicine items are approved on your screen. Want to go through them now?" The **Plan review** opens with the cited source lines | "The PDF is read on CareLoop's own server: text first, OCR for scans, then a local model proposes items. Code checks every number against the page." |
| 0:40–1:10 | Show: "Alexa, go through them" → "make it 9" → "give it to Sam" → "approve" → "approve" | "Item 1 of 4: Take a short walk every morning, at 8 AM. Approve, change the time, give it to someone, skip, or stop?" … then "Done: 4 approved. 4 items are waiting on your screen." Sam's Dot says "Maya gave you a new task." (no detail, no ring) | "Everyday tasks can be reviewed by voice. Sam now owns the evening dressing change." |
| 1:10–1:30 | On the Show's screen, approve the medicine items. On the pain rule, tick its flags, then approve | Each card shows the medicine as written and its source line | "Medicines and flagged items can only be approved on Maya's own screen, never by voice." |
| 1:30–1:50 | Backstage: **Ring next reminder** twice. Then Dot: "Alexa, what was Maya's pain score?" | Dot: "Reminder for Sam: Maya's Evening dressing change." Then "CareLoop records are unavailable." | "Alexa+ sets the reminders natively, for whoever the task belongs to. Sam's shared speaker never hears a symptom or a dose." |
| 1:50–2:15 | Show: "Alexa, my pain is 8 today". Point at Sam's ring. Dot: "Alexa, any CareLoop updates?" → "Alexa, mark it seen" | "Check-in recorded." **Sam's ring lights up.** "You have 1 new CareLoop update and 1 new task from Maya." "CareLoop updates acknowledged." | "Yesterday was a 7. Two days at 7 or higher is the rule Maya approved from line 11 of her prescription, so Sam is told there's an update, and nothing more." |
| 2:15–2:30 | Show: "Alexa, should I double my ibuprofen?" | "I can't give medical advice. Please contact your clinician, or emergency services in an emergency." The inspector shows **no tool call** | "CareLoop coordinates care. It never gives medical advice." |
| 2:30–2:50 | Show: "Alexa, add a question for my doctor: can I shower with the dressing on" → "Alexa, get me ready for my appointment" | "Saved. You have 2 questions ready for your next appointment." Then "Your visit handoff is ready on your private screen. It includes 2 questions for your clinician." The **Handoff** card opens | "Before the visit, Maya gets a dated summary for her clinician: source lines, who did what, the check-ins and her questions." |
| 2:50–3:00 | Show: "Alexa, who has seen my care data this week?" | "In the last 7 days, Sam accepted your invitation and acknowledged an update." | "Alexa+ remembers. CareLoop proves." |

The first **Ring next reminder** is Maya's own morning walk ("Reminder: Morning activity."). The second is Sam's.

## If something goes wrong

- **Wrong state:** press **Reset demo data** in Backstage. It wipes only the demo patient and reseeds the starting day.
- **A model reply is off:** switch the Planner to **Mock replay** and repeat the line. It's deterministic, and the replies above come from it.
- **The document-reading model is unavailable:** start with `CARELOOP_INTAKE_LLM=none`. Pattern matching still produces cited items, and every item then needs review.

## For testers and judges

Anyone running the repo gets the same starting day from `scripts/run_alexa_demo.sh` (it seeds an empty demo patient automatically). The prompt chips under each device cover the shot list. **Reset demo data** restores the starting day at any time. For a shared machine, set `CARELOOP_DEMO_IDLE_RESET_MINUTES=15` so the demo restores itself after 15 minutes without use.
