# CareLoop: three-minute video demo

The video is two clips joined by a title card.

1. **The first visit (about 40 seconds).** Maya shares her prescription. CareLoop reads it into items, each beside the line it came from, and Maya approves them all on her screen.
2. **Day four at home (about 2 minutes 15 seconds).** Three days later, CareLoop has her history to work from.

In that time it shows what CareLoop adds to Alexa+, in the order a judge should remember it:

| # | What CareLoop adds | Where in the video |
|---|---|---|
| 1 | **A prescription becomes a plan she approves**, each item beside its source line, numbers checked, medicines approved only on her screen | 0:00 |
| 2 | **Suggestions from her own history**, each saying which record it came from | 0:43 |
| 3 | **Teach-back**: approved is not the same as understood, and code checks the answer | 1:08 |
| 4 | **A clinician's rule decides**, and a shared speaker hears that something changed, never the value | 1:35 |
| 5 | **Family tasks**: Sam hears that a task is waiting, and what it is only when he asks | 1:57 |
| 6 | **A boundary**: no medical advice, and no tool call at all | 2:17 |
| 7 | **A source for every claim** in the clinician handoff | 2:25 |

Alexa+ can already read a document you share and answer questions about it. The first clip shows what it does not do: turn the page into items the patient approves one by one, each traceable to its line.

**Where the replies come from:**
- **Clip 1:** a run on Oct 21, 2026 with the hosted model from `.env` reading the document. The model writes the items, so a label or a count can differ between runs.
- **Clip 2:** full runs on Oct 20, 2026 on a freshly reset story, one with the **Mock replay** planner and two with the hosted model. All three gave the same words.

**Don't name a model in the video.** In production Alexa+ supplies its own language model and chooses the tools; the simulator stands in for it. If asked: "CareLoop works with whatever model is behind Alexa+. To run the simulator, any OpenAI-compatible API works."

Never show `.env`, tokens or database paths on screen. All people and documents are fictional.

## The two starting states

**Clip 1, the first visit:** `scripts/run_alexa_demo.sh --reset`. Maya has accepted data use, Sam is in her care circle, and her prescription is not loaded yet.

**Clip 2, day four at home:** `scripts/run_alexa_demo.sh --reset --story=history`. While it runs, **Reset demo data** in Backstage reseeds the same story.

| When | What happened | Why it's there |
|---|---|---|
| 3 days ago | Maya shared the typed prescription and approved all 8 items on her screen; this is clip 1. Each item keeps its line (p1:L5 to p1:L13). She moved the dressing change to 9 PM and gave it to Sam. Sam asked what his task was | The plan is approved and cited |
| 3 days ago to yesterday | Pain check-ins of 3, 4 and 7 | Yesterday's 7 means a high score today is the second day at 7 or higher, so the rule from line 11 fires on camera |
| 2 days ago | A teach-back: 5 of 6 right. Omeprazole's time was wrong: "8:00 AM", where the plan says 7:30 AM | "Part of your plan needs another look" |
| 2 days ago | Sam did the 9 PM dressing change. Maya saved a question: "When can I go back to work?" | The handoff has a completed task and her question |
| Yesterday | Nobody recorded the 9 PM dressing change, so CareLoop raised a missed-task update. Sam saw it | "Sam missed Evening dressing change", and Sam's ring is dark this morning |
| This morning | Maya took the dressing back and checked in with a 5 | Nothing can count as missed today, and "you haven't checked in" never appears, whatever time you record |
| In 6 days | Her follow-up visit (line 13 carries the date) | The handoff is for that visit. It is too far off to be raised as a suggestion, so the suggestion's question is the teach-back |

Clip 2 works at any time of day; the story was tested from 6:30 AM to 11:45 PM. **Reset just before you record.** The dates in clip 2 follow the day you reset, so its follow-up date differs from the 2026-10-24 printed on the sample prescription in clip 1. Don't linger on line 13 in either clip. Avoid recording between midnight and 6 AM, because the rule counts calendar days in UTC.

## Before recording

```bash
# a model for the simulator and the document reader: any OpenAI-compatible API in .env
# (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL), or Ollama running
scripts/run_alexa_demo.sh --reset                    # clip 1
# stop it with Ctrl+C, then
scripts/run_alexa_demo.sh --reset --story=history    # clip 2
```

1. Open the printed URL (usually http://127.0.0.1:8021) in Chrome at 1440×900.
2. Press **Reset demo data** twice in Backstage. Both devices are linked and the screens are clear.
3. Do a full practice run of each clip. Send any request once before your final **Reset demo data**, so the first line on camera isn't the slow cold start.
4. Keep **Show MCP inspector** on. It shows judges the real MCP traffic.
5. Type the lines into each device's box, or speak them. Answers to a question need no "Alexa".
6. **Wait for each reply to finish** (the device's state word goes back to `idle` or `listening`) before the next line. A line sent while Alexa is still thinking can arrive before the question it answers. Requests that go through the model take about 5 to 8 seconds with a hosted model; answers to CareLoop's own questions are immediate.

## Shot list

### Clip 1: the first visit (0:00–0:40)

| Time | Do | You'll see and hear | Say (voice-over) |
|---|---|---|---|
| 0:00–0:08 | Alexa app panel: **Share a document**, from Maya, type Prescription, **Typed PDF**, **Share sample** | The Show: "Got it. I'm reading your document now. I'll tell you as soon as it's ready." | "Maya is home from the clinic with her prescription. Alexa+ can read it. CareLoop turns it into a plan she approves." |
| *cut* | Reading takes about 45 seconds with a hosted model. Cut it out | | |
| 0:08–0:22 | Wait for the announcement. Let the **Plan review** sit on screen | "Your document is ready. 8 items need your approval, and 2 are flagged for a closer look. Medicine items are approved on your screen. Want to go through them now?" Each card shows the instruction and its line, for example p1:L5 for the antibiotic. Two cards carry an amber flag and a box to tick | "Each item keeps the exact line it came from. Code checks every number against the page, and anything doubtful is flagged for a second look." |
| 0:22–0:40 | Don't answer the question. On the screen, tap **Add to my plan** on every card, scrolling inside the screen. On the two flagged cards, tick **I've checked this against the document** first. Speed this up 2x in editing | Each card turns **Active**. The screen ends with all 8 items in her plan | "Nothing is active until Maya approves it, and medicines and flagged items can only be approved on her own screen. Here she approves them all." |

Then a title card for about 3 seconds: **Three days later.**

### Clip 2: day four at home (0:43–3:00)

| Time | Do | You'll see and hear | Say (voice-over) |
|---|---|---|---|
| 0:43–1:08 | Show: "Alexa, anything I should know?" | "You have 2 things worth a look. Sam missed Evening dressing change. Part of your plan needs another look. CareLoop is not medical advice or emergency monitoring. Want to do that now?" The screen shows **Worth raising**, each with a **Because**: "Evening dressing change was due, Oct 19, 9:00 PM" with line 10, and "From your approved plan" with line 6 | "CareLoop doesn't guess. It works from Maya's own records: last night's missed dressing change, and an answer she got wrong two days ago. Code decides what to raise, and each one says where it came from." |
| 1:08–1:35 | Show: "yes" → "8 am" → "7:30 in the morning" | "Let's check 1 thing. When do you take Omeprazole?" → "Not quite. Try again: When do you take Omeprazole?" → "That's right. Done. You got 1 of 1 right." The **Understanding check** screen opens: Omeprazole is now **Understood**, with line 6 | "Approved isn't the same as understood. CareLoop asks Maya to say her plan back and checks the answer in code against line 6. A miss is answered by reading the line back, never by explaining it." |
| 1:35–1:57 | Show: "Alexa, my pain is 8 today". Point at Sam's ring. Dot: "Alexa, any CareLoop updates?" → "Alexa, what was Maya's pain score?" | "Check-in recorded." The chart shows the dashed rule line. **Sam's ring lights up.** "You have 1 new CareLoop update." "CareLoop records are unavailable." | "Yesterday was a 7. Two days at 7 or higher is the rule from line 11 of her prescription, so Sam is told there's an update. His shared speaker never hears the score." |
| 1:57–2:17 | Show: "Alexa, Sam handles the dressing change". Then Dot: "Alexa, what are my tasks for Maya?" | "Done. Sam will handle Evening dressing change at 9 PM." Sam's Dot says "Maya gave you a new task." with no detail. Then "You have 1 task to help Maya with: Evening dressing change at 9 PM." | "Maya hands the dressing back to Sam. His speaker says only that a task is waiting. What it is, he hears when he asks." |
| 2:17–2:25 | Show: "Alexa, should I double my ibuprofen?" | "I can't give medical advice. Please contact your clinician, or emergency services in an emergency." The inspector shows **no tool call** | "CareLoop coordinates care. It never gives medical advice." |
| 2:25–3:00 | Show: "Alexa, get me ready for my appointment". Scroll slowly inside the screen | "Your visit handoff is ready on your private screen. It includes 1 question for your clinician." The **Visit handoff** shows, in order: her question "in your words", the plan with its lines, the **Understanding check** with each answer and its line, the missed dressing change with line 10, and the alert with **Because** "pain 7 on …, pain 8 on …" and line 11 | "Before the visit, Maya gets a dated summary for her clinician. Every claim in it says where it came from: the line in her prescription, or the record it was counted from. Alexa+ remembers. CareLoop proves." |

The disclaimer in the first reply of clip 2 is required by the Alexa+ policy and is said once per session; keep it in.

## If something goes wrong

- **Wrong state:** press **Reset demo data** in Backstage. It wipes only the demo patient and reseeds the story the demo was started with.
- **The document is not ready after 2 minutes:** the model behind the document reader is unreachable. Start clip 1 with `CARELOOP_INTAKE_LLM=none`: pattern matching still produces cited items. Every item then needs a tick, and Alexa's counts differ from the ones quoted above.
- **A model reply is off in clip 2:** switch the Planner to **Mock replay** and repeat the line. It is deterministic and gave the replies above.
- **"Yes" does nothing after "anything I should know?":** a new "Alexa, …" request was spoken in between. Ask "Alexa, check my understanding" instead; it starts the same check.
- **"2 tasks were missed":** the story was not reset today. Press **Reset demo data**.

## For testers and judges

Anyone running the repo can start either story: `scripts/run_alexa_demo.sh --reset` for the first visit, or `--story=history` for day four at home. The prompt chips under each device cover both. [CARELOOP_UI_DEMO_GUIDE.md](CARELOOP_UI_DEMO_GUIDE.md) walks through the first visit click by click, including the voice review this video skips. For a shared machine, set `CARELOOP_DEMO_IDLE_RESET_MINUTES=15` so the demo restores itself after 15 minutes without use.
