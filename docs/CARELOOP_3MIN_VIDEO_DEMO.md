# CareLoop: three-minute video demo

The video opens on **day four at home**. Maya approved her prescription three days ago, and CareLoop has three days of her history to work from. In three minutes it shows what CareLoop adds to Alexa+, in the order a judge should remember it:

| # | What CareLoop adds | Where in the video |
|---|---|---|
| 1 | **Suggestions from her own history**, each saying which record it came from | 0:15 |
| 2 | **Teach-back**: approved is not the same as understood, and code checks the answer | 0:40 |
| 3 | **A clinician's rule decides**, and a shared speaker hears that something changed, never the value | 1:10 |
| 4 | **Family tasks**: Sam hears that a task is waiting, and what it is only when he asks | 1:35 |
| 5 | **A boundary**: no medical advice, and no tool call at all | 2:00 |
| 6 | **A source for every claim** in the clinician handoff | 2:10 |
| 7 | **Access transparency**: who looked at her data | 2:45 |

Every reply quoted below came from full runs of this shot list on Oct 20, 2026, on a freshly reset story: one with the **Mock replay** planner and two with a hosted model as the planner. All three gave the same words. Task names such as "Evening dressing change" are part of the seeded story, so they do not vary.

**Don't name a model in the video.** In production Alexa+ supplies its own language model and chooses the tools; the simulator stands in for it. If asked: "CareLoop works with whatever model is behind Alexa+. To run the simulator, any OpenAI-compatible API works."

Never show `.env`, tokens or database paths on screen. All people and documents are fictional.

## The starting day: day four at home

`scripts/run_alexa_demo.sh --reset --story=history` seeds this. While the demo runs, **Reset demo data** in Backstage reseeds the same story.

| When | What happened | Why it's there |
|---|---|---|
| 3 days ago | Maya shared the typed prescription and approved all 8 items on her screen. Each one keeps its line (p1:L5 to p1:L13). She moved the dressing change to 9 PM and gave it to Sam. Sam asked what his task was | The plan is approved and cited, so the video starts with history |
| 3 days ago to yesterday | Pain check-ins of 3, 4 and 7 | Yesterday's 7 means a high score today is the second day at 7 or higher, so the rule from line 11 fires on camera |
| 2 days ago | A teach-back: 5 of 6 right; Omeprazole's time was wrong ("8:00 AM", the plan says 7:30 AM) | "Part of your plan needs another look" |
| 2 days ago | Sam did the 9 PM dressing change. Maya saved a question: "When can I go back to work?" | The handoff has a completed task and her question |
| Yesterday | Nobody recorded the 9 PM dressing change, so CareLoop raised a missed-task update. Sam saw it | "Sam missed Evening dressing change", and Sam's ring is dark this morning |
| This morning | Maya took the dressing back and checked in with a 5 | Nothing can count as missed today, and "you haven't checked in" never appears, whatever time you record |
| In 6 days | Her follow-up visit (line 13 carries the date) | The handoff is for that visit. It is too far off to be raised as a suggestion, so the suggestion's question is the teach-back |

Recording works at any time of day; the story was tested from 6:30 AM to 11:45 PM. **Reset just before you record.** The dates in the story follow the day you reset. Avoid recording between midnight and 6 AM: the rule counts calendar days in UTC.

## Before recording

```bash
# a model for the simulator: any OpenAI-compatible API in .env (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL), or Ollama running
scripts/run_alexa_demo.sh --reset --story=history
```

1. Open the printed URL (usually http://127.0.0.1:8021) in Chrome at 1440×900.
2. Press **Reset demo data** twice in Backstage. Both devices are linked and the screens are clear.
3. Do a full practice run. Then press **Reset demo data** again just before you record.
4. Keep **Show MCP inspector** on. It shows judges the real MCP traffic.
5. Type the lines into each device's box, or speak them. Answers to a question need no "Alexa".
6. **Wait for each reply to finish** (the device's state word goes back to `idle` or `listening`) before the next line. A line sent while Alexa is still thinking can arrive before the question it answers. Requests that go through the model take about 5 to 8 seconds with a hosted model; answers to CareLoop's own questions are immediate.
7. Send any request once before your final **Reset demo data**, so the first line on camera isn't the slow cold start.

## Shot list

| Time | Do | You'll see and hear | Say (voice-over) |
|---|---|---|---|
| 0:00–0:15 | Show: "Alexa, show my plan" | "You have 5 active tasks and 1 active follow-up rule. CareLoop is not medical advice or emergency monitoring." The **Care tasks** screen lists each item beside the line it came from | "Maya came home from the clinic three days ago. She approved her prescription line by line, and every item on her screen points back to the line it came from." |
| 0:15–0:40 | Show: "Alexa, anything I should know?" | "You have 2 things worth a look. Sam missed Evening dressing change. Part of your plan needs another look. Want to do that now?" The screen shows **Worth raising**, each with a **Because**: "Evening dressing change was due, Oct 19, 9:00 PM" with line 10, and "From your approved plan" with line 6 | "CareLoop doesn't guess. It works from Maya's own records: last night's missed dressing change, and an answer she got wrong two days ago. Code decides what to raise, and each one says where it came from." |
| 0:40–1:10 | Show: "yes" → "8 am" → "7:30 in the morning" | "Let's check 1 thing. When do you take Omeprazole?" → "Not quite. Try again: When do you take Omeprazole?" → "That's right. Done. You got 1 of 1 right." The **Understanding check** screen opens: Omeprazole is now **Understood**, with line 6 | "Approved isn't the same as understood. CareLoop asks Maya to say her plan back and checks the answer in code against line 6. A miss is answered by reading the line back, never by explaining it." |
| 1:10–1:35 | Show: "Alexa, my pain is 8 today". Point at Sam's ring. Dot: "Alexa, any CareLoop updates?" → "Alexa, what was Maya's pain score?" | "Check-in recorded." The chart shows the dashed rule line. **Sam's ring lights up.** "You have 1 new CareLoop update." "CareLoop records are unavailable." | "Yesterday was a 7. Two days at 7 or higher is the rule from line 11 of her prescription, so Sam is told there's an update. His shared speaker never hears the score." |
| 1:35–2:00 | Show: "Alexa, Sam handles the dressing change". Then Dot: "Alexa, what are my tasks for Maya?" | "Done. Sam will handle Evening dressing change at 9 PM." Sam's Dot says "Maya gave you a new task." with no detail. Then "You have 1 task to help Maya with: Evening dressing change at 9 PM." | "Maya hands the dressing back to Sam. His speaker says only that a task is waiting. What it is, he hears when he asks." |
| 2:00–2:10 | Show: "Alexa, should I double my ibuprofen?" | "I can't give medical advice. Please contact your clinician, or emergency services in an emergency." The inspector shows **no tool call** | "CareLoop coordinates care. It never gives medical advice." |
| 2:10–2:45 | Show: "Alexa, get me ready for my appointment". Scroll slowly inside the screen | "Your visit handoff is ready on your private screen. It includes 1 question for your clinician." The **Visit handoff** shows: her question "in your words", the plan with its lines, the **Understanding check** with each answer and its line, the missed dressing change with line 10, and the alert with **Because** "pain 7 on …, pain 8 on …" and line 11 | "Before the visit, Maya gets a dated summary for her clinician. Every claim in it says where it came from: the line in her prescription, or the record it was counted from." |
| 2:45–3:00 | Show: "Alexa, who has seen my care data this week?" | "In the last 7 days, Sam acknowledged an update 2 times, accepted your invitation and completed a task." The **Care circle** screen opens | "And Maya can always see who looked. Alexa+ remembers. CareLoop proves." |

## If something goes wrong

- **Wrong state:** press **Reset demo data** in Backstage. It wipes only the demo patient and reseeds day four.
- **A model reply is off:** switch the Planner to **Mock replay** and repeat the line. It is deterministic and gave the replies above.
- **"Yes" does nothing after "anything I should know?":** a new "Alexa, …" request was spoken in between. Ask "Alexa, check my understanding" instead; it starts the same check.
- **"2 tasks were missed":** the story was not reset today, or it was seeded with an older version. Press **Reset demo data**.

## A longer cut with the document reading

The three minutes above skip reading the prescription, which already happened three days before in the story. To show it, record a second clip from the first-visit story (`scripts/run_alexa_demo.sh --reset`): in the Alexa app panel, **Share a document**, from Maya, **Typed PDF**, **Share sample**. The Show answers "Got it. I'm reading your document now. I'll tell you as soon as it's ready." and, about 10 to 30 seconds later, "Your document is ready. 8 items need your approval, and 2 are flagged for a closer look. Medicine items are approved on your screen. Want to go through them now?" The **Plan review** shows each draft beside its line. [CARELOOP_UI_DEMO_GUIDE.md](CARELOOP_UI_DEMO_GUIDE.md) has that flow click by click.

## For testers and judges

Anyone running the repo can start either story: `scripts/run_alexa_demo.sh --reset` for the first visit (the prescription is shared and reviewed in the demo), or `--story=history` for day four at home. The prompt chips under each device cover both. For a shared machine, set `CARELOOP_DEMO_IDLE_RESET_MINUTES=15` so the demo restores itself after 15 minutes without use.
