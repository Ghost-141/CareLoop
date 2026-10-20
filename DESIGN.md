---
name: CareLoop
description: Every care instruction Alexa says can be traced back to the page it came from.
colors:
  prescription-ink: "#1c2b45"
  graphite: "#5b6475"
  ward-white: "#f4f6f5"
  sheet: "#ffffff"
  hairline: "#dadfe3"
  hairline-soft: "#e9ecee"
  highlighter: "#ffe873"
  highlighter-ink: "#5c4a00"
  confirm-green: "#1f7a5a"
  confirm-green-soft: "#e3f2eb"
  caution-amber: "#9a6200"
  caution-amber-soft: "#fff4d1"
  alert-red: "#b42318"
  alert-red-soft: "#fdecea"
  focus-blue: "#2f6fde"
  alexa-cyan: "#19c3f0"
  voice-teal: "#1690a6"
  voice-teal-text: "#0e6f81"
  night-page: "#10161f"
  night-sheet: "#18212d"
  night-ink: "#e6ebf2"
typography:
  display:
    fontFamily: "ui-rounded, SF Pro Rounded, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "ui-rounded, SF Pro Rounded, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.1875rem"
    fontWeight: 600
    lineHeight: 1.3
  title:
    fontFamily: "ui-rounded, SF Pro Rounded, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.4
  source:
    fontFamily: "Charter, Bitstream Charter, Iowan Old Style, Georgia, serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  time:
    fontFamily: "ui-rounded, SF Pro Rounded, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 600
    lineHeight: 1.3
    fontFeature: "tnum"
rounded:
  slip: "4px"
  field: "8px"
  button: "10px"
  surface: "14px"
  device: "22px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "22px"
components:
  button-primary:
    backgroundColor: "{colors.prescription-ink}"
    textColor: "{colors.sheet}"
    typography: "{typography.title}"
    rounded: "{rounded.button}"
    padding: "0 18px"
    height: "44px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.prescription-ink}"
    rounded: "{rounded.button}"
    padding: "0 18px"
    height: "44px"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.alert-red}"
    rounded: "{rounded.button}"
    padding: "0 18px"
    height: "44px"
  button-danger-hover:
    backgroundColor: "{colors.alert-red-soft}"
    textColor: "{colors.alert-red}"
  input:
    backgroundColor: "{colors.ward-white}"
    textColor: "{colors.prescription-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.field}"
    padding: "9px 11px"
    height: "42px"
  ruled-list:
    backgroundColor: "{colors.sheet}"
    rounded: "{rounded.surface}"
    padding: "14px 16px"
  review-card:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.prescription-ink}"
    rounded: "{rounded.surface}"
    padding: "16px"
  source-slip:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.prescription-ink}"
    typography: "{typography.source}"
    rounded: "{rounded.slip}"
  prompt-chip:
    backgroundColor: "transparent"
    textColor: "{colors.prescription-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.field}"
    padding: "4px 11px"
    height: "32px"
---

# Design System: CareLoop

## Overview

**Creative North Star: "The Paper Trail"**

CareLoop begins with a page from the clinic, and its visual system never lets go of that page. Every plan item can show the exact line it came from, set in print type beside its line number with a highlighter swipe across it. The system borrows from what a patient actually holds after a visit: a prescription written in blue-black ink, a page someone has gone over with a yellow highlighter, a schedule organized by time of day.

Everything around the paper trail is calm and disciplined. Surfaces are white sheets on a cool ward-white page, divided by hairlines rather than lifted by shadows. Color is rationed: ink for text and primary actions, highlighter only where something came from the source or still needs the patient's eye, and green, amber and red only to report a state. The density suits a patient reading an Echo Show at arm's length, with large touch targets, generous rows and plain sentences.

The same world runs through three surfaces: the private Echo Show screens (MCP Apps views), the browser simulator, and the product page. The private screens are canonical; the simulator and product page follow their tokens.

**Key Characteristics:**
- The source slip (print type, line-number gutter, highlighter swipe) is the system's signature.
- Prescription-ink blue-black instead of black; cool ward-white instead of cream.
- Flat: hairline rules and white sheets carry structure; shadows belong only to physical objects.
- Ruled lists for records; standalone cards only for items that need a decision.
- Status is a colored dot plus a sentence-case word, never a filled badge.
- Light and dark themes are both first-class; the host decides.

## Colors

A cool, near-monochrome ink-on-paper palette with one bright yellow, rationed hard.

### Primary
- **Prescription Ink** (#1c2b45): all body text, headings, and the primary button fill. Also the chart line. It stands in for black everywhere.

### Secondary
- **Highlighter Yellow** (#ffe873): the swipe behind a cited source line, the tab on a review card, and the busy state of a document being read. In dark theme the swipe darkens and its text turns **Highlighter Ink** (#5c4a00 in light, its night counterpart in dark).

### Tertiary
- **Alexa Cyan** (#19c3f0): device-light vernacular only, in the simulator: the listening light bar and the Echo Dot ring. Never used for UI chrome or actions.
- **Voice Teal** (#1690a6): the product page's mark for Alexa speaking: the speaker label, the dashed thread from a spoken line to its source, the cited line number, and the scanning beam in the loop animation. As text it darkens to **Voice Teal Text** (#0e6f81) to stay above 4.5:1.

### Neutral
- **Ward White** (#f4f6f5): the page behind everything, and the input fill.
- **Sheet** (#ffffff): surfaces, lists, cards, slips.
- **Graphite** (#5b6475): secondary text, metadata, line numbers, legends.
- **Hairline** (#dadfe3) and **Soft Hairline** (#e9ecee): surface borders and the rules between rows.
- **Night Page** (#10161f), **Night Sheet** (#18212d), **Night Ink** (#e6ebf2): the dark theme's page, surface and text.

### State colors
- **Confirm Green** (#1f7a5a, soft #e3f2eb): active, approved, done, linked.
- **Caution Amber** (#9a6200, soft #fff4d1): draft, needs review, pending, processing; the review flag box.
- **Alert Red** (#b42318, soft #fdecea): revoked, failed, missed; destructive actions; low-confidence OCR.
- **Focus Blue** (#2f6fde): the keyboard focus ring and nothing else.

### Named Rules
**The Highlighter Rule.** Yellow means "this came from the page" or "this still needs your eye." It never decorates, never fills a button, and never marks something the patient has already settled.

**The No-Black Rule.** Text and fills use Prescription Ink, never #000 or a tinted near-black.

**The States-Only Rule.** Green, amber and red report a record's state. They never brand, decorate or fill large areas.

## Typography

**Display Font:** the system rounded face (ui-rounded / SF Pro Rounded, falling back to system-ui)
**Body Font:** the system UI face (system-ui, -apple-system, Segoe UI, Roboto)
**Source Font:** a print serif (Charter, falling back to Iowan Old Style and Georgia)

**Character:** a friendly rounded face for titles and times, a neutral system face for reading, and a print serif that appears only when quoting the source document, so the patient can tell at a glance which words came from the clinic.

The private screens run in a sandboxed frame that cannot load web fonts, so they use system stacks. The simulator uses **Atkinson Hyperlegible Next** (designed for low-vision readers) for its UI and **Atkinson Hyperlegible Mono** for the MCP inspector trace. The product page uses **Atkinson Hyperlegible**, sets its source slip in the same print serif as the screens, and uses **Courier Prime** only for code blocks.

### Hierarchy
- **Display** (600, 1.5rem, 1.2): the view title at the top of each private screen.
- **Headline** (600, 1.1875rem, 1.3): the name of an item under review.
- **Title** (600, 1rem, 1.3): section headings and row titles.
- **Body** (400, 1rem, 1.5): instructions and record text.
- **Label** (400, 0.875rem, 1.4): metadata, field labels, status words (0.8125rem).
- **Source** (400, 1rem, 1.5, print serif): quoted document lines inside a source slip.
- **Time** (600, 1.0625rem, tabular figures): the time column of the task schedule.

### Named Rules
**The Print-Means-Source Rule.** The print serif is reserved for words quoted from the patient's document. Never use it for headings, UI copy or emphasis.

**The Sentence-Case Rule.** Headings, buttons and statuses are sentence case. No all-caps labels, no tracked-out eyebrows.

## Layout

Private screens are a single column inside the Echo Show's frame: 20px page padding (16px under 520px), sections stacked 22px apart, and 12px between a section heading and its content. Rows inside a ruled list have 14px by 16px padding.

Task rows switch to a two-column grid: a fixed time column (5.25rem, 4.25rem on narrow screens) and the item's content, so a list scans like a medication schedule. Source slips inside a timed row align with the content column.

Review cards and form fields use a label/value grid (labels at least 120px wide) that collapses to one column under 520px.

The simulator is a three-column stage (Echo Show 2fr, Echo Dot 1fr, Alexa app and Backstage 1fr) that collapses to two columns under 1180px and one under 760px.

### Named Rules
**The Schedule Rule.** Anything that happens at a time leads with the time, in tabular figures, in its own column.

## Elevation & Depth

The system is flat. Depth comes from tonal layering (white Sheet on Ward White) and 1px hairlines, never from shadows on UI surfaces. Shadows are reserved for objects that exist physically: the Echo Show bezel, the Echo Dot, and the product page's paper slip.

### Shadow Vocabulary
- **Device drop** (`box-shadow: 0 1px 0 #ffffff14 inset, 0 24px 40px -18px #1c2b4566`): the Echo Show bezel in the simulator.
- **Dot drop** (`box-shadow: 0 10px 22px -8px #1c2b4580`): the Echo Dot body.
- **Paper slip** (`box-shadow: 0 1px 0 var(--rule), 0 18px 40px -28px rgba(28, 43, 69, .45)`): the product page's source slip, which is also rotated -0.6deg.

### Named Rules
**The Hairline Rule.** If a UI surface needs separating, use a 1px Hairline border or Soft Hairline rule. Reaching for a shadow means the element should be a physical object.

## Shapes

Corners follow hierarchy rather than one radius everywhere. Surfaces (lists, review cards, charts, empty states) use 14px; buttons 10px; inputs and prompt chips 8px; device frames 18–22px. Status dots and switch tracks are fully round.

The source slip has its own silhouette: a nearly square top (4px) with softer bottom corners (10px), and a perforated top edge drawn as a dashed hairline, like a strip torn from a page.

## Components

### Buttons
Plain and steady: one filled action, everything else quiet.
- **Shape:** gently rounded (10px), at least 44px tall (36px for the small variant in list rows).
- **Primary:** Prescription Ink fill, white text, weight 600. Labels say exactly what happens: "Add to my plan", "Mark done", "Mark as seen".
- **Quiet:** transparent with a Hairline border and ink text, for the alternative choice ("Leave it out").
- **Danger:** transparent red text; a soft red wash on hover ("Remove").
- **Hover / Focus:** hover brightens slightly; focus is a 3px Focus Blue ring offset 2px. Disabled drops to 40% opacity.

### Status
- **Style:** an 8px dot in the state color followed by a sentence-case word in the same color ("Active", "Needs review", "Revoked"). No pill, no fill.

### Ruled List
- **Corner Style:** 14px on the outer surface only.
- **Background:** Sheet on Ward White, 1px Hairline border.
- **Rows:** separated by Soft Hairline rules; 14px by 16px padding; title, then Graphite metadata, then any action or status on the right.

### Review Card
The one block that stands alone, because it asks the patient for a decision.
- **Shape:** 14px Sheet surface with a Hairline border and a 5px Highlighter tab on the left edge.
- **Contents:** kind in Graphite, item name as a Headline, the instruction, then its source slip, editable fields, any amber review flags with a confirmation checkbox, and the actions. The primary action stays disabled until flagged items are confirmed.

### Source Slip (signature)
- **Structure:** a "From <document>" caption, then one row per cited line: a 56px right-aligned line-number gutter ("p1:L5") with a hairline divider, and the quoted text in the print serif.
- **Highlight:** cited text sits on a highlighter swipe (a gradient band from 12% to 88% of the line height) that wraps cleanly across lines.
- **OCR:** lines read by OCR show their confidence. Below 85% the swipe is replaced by a wavy red underline with "Check this line."
- **Unhighlighted variant:** when showing a whole document rather than a citation, lines are set without the swipe.

### Inputs / Fields
- **Style:** Ward White fill, 1px Hairline border, 8px radius, at least 42px tall.
- **Focus:** a 2px Focus Blue outline replaces the border.
- **Checkboxes:** 20px, tinted Prescription Ink.

### Prompt Chips (simulator)
- **Style:** transparent, 1px Hairline border, 8px radius, ink text in sentence case; the border darkens to ink on hover.

### Devices (simulator)
- **Echo Show:** a charcoal bezel (#22262b) with a camera dot, the screen in Ward White, and a 4px light bar that glows Alexa Cyan when listening, sweeps while thinking, and pulses while speaking. It shows only the latest exchange: the user's words small, italic and quoted; Alexa's reply large.
- **Echo Dot:** seen from above, a dotted fabric top inside a light ring: cyan for listening, spinning while thinking, yellow pulsing when a notification waits.
- **Backstage:** demo tooling sits in its own dark column (#141a22), clearly labeled as not part of the product.

## Do's and Don'ts

### Do:
- **Do** trace every plan item back to its source line with a source slip, and show only the lines that item came from.
- **Do** lead task rows with the time, in tabular figures.
- **Do** keep primary actions at least 44px tall and body text at least 16px; patients read the Echo Show at arm's length.
- **Do** express state as a dot plus a sentence-case word in the state color.
- **Do** define colors as tokens on `:root` with a matching `[data-theme="dark"]` set, and let the host's theme choose.
- **Do** use system font stacks inside MCP Apps views; they cannot load web fonts.

### Don't:
- **Don't** use the highlighter for decoration, buttons, or anything the patient has already settled.
- **Don't** use pure black, a tinted near-black, or a warm cream background.
- **Don't** put shadows on UI surfaces; use hairlines and tonal layers.
- **Don't** stack records as identical cards; use a ruled list, and save standalone cards for decisions.
- **Don't** use all-caps labels, tracked-out eyebrows, or middle-dot meta strings.
- **Don't** set UI copy in the print serif; it belongs to quoted source text.
- **Don't** use Alexa Cyan outside device lights, or Voice Teal for anything but Alexa's voice.
