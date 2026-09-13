# AUDIT_07 — Business Requirements Fit Check

This phase does not re-inspect code. It translates AUDIT_00 through AUDIT_06's already-cited
findings into direct answers for a non-technical stakeholder. Every citation below points back to
the phase/file where the underlying evidence was established.

---

### 1. SCALE: Can one search actually return 10,000–40,000+ results today?

**No.**

For a single term the way most users would type it, the realistic number today is in the **tens
to low hundreds per source per year**, not thousands. A real example measured live during this
project's own development: one broad term, one language, run for a full year, returned about 70
kept results out of roughly 900 raw candidates the search engine offered — the rest were removed
because they weren't actually relevant to the target market. (AUDIT_05 §1, citing AUDIT_02 §3 and
`scrapers/news.py`)

This isn't a bug to fix with more time — it's an external limit set by the news search services
themselves (they simply won't hand back more than about 100 results for one search at a time, no
matter how the request is made). The system's only way around that limit is to ask the same
question a different way many times over (different wording, different languages, different
brand names) — which is a **separate, optional feature (§5/§6 below)**, not something that happens
automatically when someone searches.

**What kind of change would be needed to get closer to 10,000–40,000:** running that optional
expansion feature at full strength (already built and demonstrated — one real test took a single
project from 2 active searches to 174) **and** combining several data sources together, not just
one. Whether that combination can reliably reach 10,000–40,000 in practice for a real topic is
**not yet proven** — it depends on how much real content actually exists out there for that topic,
which no software change can guarantee. (AUDIT_05 §1)

---

### 2. MULTI-LANGUAGE OUTPUT: Does searching in English return content natively written in Hindi/Bangla/Telugu/etc.?

**Partial.**

The capability genuinely exists and has been proven to work — real Telugu-language news articles
from real Indian publishers were returned in a live test this session. But it only happens **if**
someone has specifically told the system to also search in that language *and* provided (or had
the system generate) the right search term in that language. Left untouched, a study configured
for "English + Hindi + Telugu" will search all three — but only if someone filled in the Hindi and
Telugu search terms; otherwise those two languages sit empty and return nothing at all, not
English content mislabeled as something else. (AUDIT_02 §1a Section 3, §2)

**What's missing to make this automatic:** nothing needs to be invented — the translation
mechanism already works. It would need to be **wired to run automatically** whenever a language is
added to a study, instead of requiring someone to click a separate "expand" button and manually
approve each suggestion.

---

### 3. MULTI-COUNTRY IN ONE RUN: Can one search cover multiple countries at once?

**No.**

Every study is locked to exactly one country. This is enforced deliberately, not an oversight —
the system actively rejects an attempt to set more than one country for the same study.
(AUDIT_02 §2, citing `app.py`'s wizard validation)

**What kind of change would be needed:** this would require reworking a core assumption that runs
through most of the system (search filters, relevance checks, and the market-matching logic all
currently expect exactly one country per study) — a moderate-to-large redesign, not a quick
setting change. Today, covering India + Bangladesh + the US means creating three separate
studies.

---

### 4. CROSS-LANGUAGE TERM MATCHING: If a concept has a different word in another language, does the system find and use it automatically?

**No, by default — only if someone manually runs it and approves the suggestions.**

Out of the box, the system searches exactly what was typed, nothing more. It does not
automatically know that a concept has a different name in another language.

There is a separate, working feature that **can** do this — you give it one term, and it comes
back with the equivalent word in every other language configured for the study, ready for someone
to review and approve. But that's a deliberate, manual step someone has to take; it's not
something that happens quietly in the background whenever a search runs. (AUDIT_02 §1b, §2)

---

### 5. SEMANTIC/CONCEPTUAL EXPANSION: Does searching "coffee" automatically pull in instant coffee, cold coffee, americano, latte, etc.?

**No, not automatically — but this exact feature exists and works very well when triggered.**

Left alone, "coffee" only ever means the literal word "coffee." There's a one-click feature that
expands it into related terms, and it was tested live during this project: it correctly returned
things like instant coffee, cold coffee, filter coffee, cappuccino, espresso, and iced coffee —
without anyone having typed those words anywhere in the system beforehand. It also suggested real,
market-specific brand names (not generic guesses) that someone can choose to track as competitors.
(AUDIT_02 §1b, live-verified result cited in AUDIT_04 §3 and AUDIT_06 §2)

The gap is only that **this doesn't happen by default** — someone has to know the button exists and
click it, once per term, per study.

---

### 6. AI-DRIVEN VS. STATIC: Is that expansion coming from an AI reasoning about the concept, or a fixed list someone wrote?

**Both exist, and it is important to know which one is running by default.**

- The **automatic, always-on** part of the system (what runs the moment a study is created, with
  zero extra clicks) is **not AI at all** — it's a simple mechanical step that just splits whatever
  words were typed into a category name. It has no understanding of the concept; "coffee" never
  becomes "espresso" here, ever. (AUDIT_02 §2, citing `config.py`'s `derive_relevance_terms`)
- The **optional, one-click** expansion feature described in §5 above **is genuinely AI-driven** —
  it makes a real call to an AI model, and the results it returns (espresso, cappuccino, specific
  real brand names) were never written into the software anywhere; the model generated them from
  its own understanding. This has been proven to generalize to things nobody explicitly
  programmed the system to know about. (AUDIT_02 §2, AUDIT_04 §3)

**Plainly: the system is only as smart as its optional AI feature, and only when a person chooses
to use it.** The default, hands-off behavior is simple and literal, not intelligent.

---

### 7. RATE-LIMIT / COST EFFICIENCY AT SCALE: Which happens first — getting blocked, or getting expensive?

**Getting blocked or slowed down happens first, well before AI cost becomes a real concern.**

Several of the data sources this system relies on (in particular one social platform and the
trends-tracking source) were observed, during real testing on this exact project, to slow down or
temporarily refuse requests after fairly light use — not because of any wrongdoing, just because
those platforms have tight limits for free, unauthenticated access. One e-commerce source blocks
essentially every attempt outright. (AUDIT_03 §1/§2, AUDIT_05 §1, all citing live-observed
behavior from this session, not assumptions)

The AI cost side, by contrast, is efficient by design for the main use case — the system bundles
up to 12 items into a single AI request rather than paying for one request per item, so cost
grows much more slowly than the amount of data collected. The one exception is a smaller feature
(reading text off product images) which does cost roughly one AI call per image — but that only
applies to images gathered from the e-commerce channel specifically, which is itself one of the
most-blocked data sources. (AUDIT_04 §3, AUDIT_05 §1)

**Bottom line: to meaningfully raise the volume ceiling, the bottleneck to solve first is access
to those data sources (rate limits and blocking), not AI spend.**

---

## Closing summary

Overall, this is currently **a narrower, precision-focused, single-language-by-default research
tool that has a genuinely smart, AI-driven expansion capability built in but switched off by
default** — not yet the smart, automatically-multilingual, high-volume research platform implied
by the questions above. Every one of the capabilities asked about (semantic expansion, cross-
language matching, native-language content) has already been built and proven to work in real,
live tests — the single biggest gap between what exists today and what's being asked for is that
**these capabilities are opt-in, manual, one-term-at-a-time actions instead of automatic behavior
that runs the moment a study is created** — closing that gap is a matter of wiring already-working
pieces together and defaulting them on, not inventing new AI capability from scratch. The volume
ceiling (question 1) is the one exception that goes deeper than "turn it on": it is genuinely
constrained by how many data sources actively resist automated access at any real scale, which is
an external-world limitation this system documents and reports honestly rather than tries to
silently push through.
