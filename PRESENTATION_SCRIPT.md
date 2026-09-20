# AgniDrishti — 5-minute technical talk

**Deck:** `AgniDrishti_Technical_Deck.pptx` (6 slides, speaker notes embedded on each slide)
**PS 26162 · NTRO · Disaster Management · Team AsyncMavericks_SIH0162**

---

## The spine of the talk

Everything hangs off one argument. If you remember nothing else, remember this shape:

> **Detection is solved. Interpretation is not.**
> A single snapshot cannot tell a refinery flare from a fire — so we classify **locations over time**, not individual detections.
> It runs on live data, it shows its evidence, and we do not claim accuracy we have not measured.

Four beats: **the gap → the insight → the machine → the honesty.** Slides 2, 3, 4–5, 6.

---

## Timing budget

| Slide | Time | Cumulative | Beat |
|---|---|---|---|
| 1 · Title | 35 s | 0:35 | The gap, in one line |
| 2 · One hot pixel | 45 s | 1:20 | The four classes + why raw FIRMS is unusable |
| 3 · Time, not temperature | 50 s | 2:10 | **The core insight** |
| 4 · The pipeline | 60 s | 3:10 | How it's built |
| 5 · It runs | 60 s | 4:10 | Proof, with real numbers |
| 6 · Real today / next | 50 s | 5:00 | Credibility + close |

**If you are running long,** cut from slide 4 (compress the five stages into one sentence) — never from 3 or 6. Slide 3 is the idea; slide 6 is the thing judges remember you for.

---

## Slide 1 — Title · 35 s

> Good morning. We're Team AsyncMavericks, on problem statement 26162 from NTRO.
>
> NASA's satellites already tell us **where** the Earth is hot. Every few hours, a fresh set of hot pixels appears over India.
>
> *(beat)*
>
> What they don't tell us is **why** that pixel is hot. AgniDrishti is the layer that answers the second question.

**Delivery:** Let the "why" land. Pause before moving. Don't read the problem-statement metadata aloud — it's on the slide.

---

## Slide 2 — One hot pixel, four different things · 45 s

> A thermal anomaly is not a fire alert. The same hot pixel could be any of four things — and they need completely different responses.
>
> A **persistent thermal source** — a refinery flare or a furnace that has burned routinely for years. That isn't an incident, it's noise, and it should be filtered out.
>
> An **industrial fire** — an unplanned event on industrial land. That's the one that matters. Escalate it.
>
> A **vegetation fire** — crop residue or scrub. Real, but not an industrial incident.
>
> Or **other / uncertain** — a landfill, an unmapped site, context too thin to call. That goes to a human.
>
> **These are the four classes our system outputs. Nothing else.**
>
> To the instrument, all four look identical. And the persistent sources fire the same alert every single day — so an operator stops reading alerts within a week, and genuine incidents are buried inside that noise.
>
> The gap is not detection. NASA has already solved detection. **The gap is interpretation** — and that's what we built.

**Delivery:** One card at a time, left to right, with your hand on each. The bold line under each card is the operational "so what" — that's what makes this a disaster-management slide rather than a data-science one. Then slow right down for the orange box.

**This slide introduces the four classes,** so say the names exactly as they appear. Slide 4 re-lists them under CLASSIFY as a reminder — you don't need to read them out a second time.

---

## Slide 3 — The discriminator is time · 50 s  ⭐ *the core slide*

> Look at the top three rows. A routine gas flare and an industrial fire are **identical**: both are hot, both sit on built-up land, both are next to a mapped factory. Any classifier looking at a single snapshot has nothing to separate them.
>
> The bottom two rows are where they diverge — and both are **temporal**. The flare recurs: in our live data, 48 days out of 90. The fire is episodic — one to three days, then gone.
>
> So the design decision follows directly: **we classify locations, not detections.**
>
> 1,522 raw detections collapse into 556 sites. Each site's timeline is then cut into distinct burning episodes wherever it falls quiet for more than ten days — 663 of them.

**Delivery:** This is the slide you slow down on. Physically point at the three grey "yes / yes" rows, then drop to the two highlighted rows. The visual argument does the work — let the contrast be seen before you explain it.

**If asked why the episode layer exists:** site statistics alone can't tell a furnace that ran for two months from a handful of unrelated one-day fires — both give the same recurrence count. Only cutting the timeline into episodes lets the system say *"the longest continuous burn here lasted 73 days."*

---

## Slide 4 — The pipeline · 60 s

> Five stages, end to end.
>
> **Ingest** — NASA FIRMS VIIRS at 375 metres. We merge all three platforms, Suomi-NPP, NOAA-20 and NOAA-21, because they cross at different local times and together give materially more observations per day.
>
> **Cluster** — detections snap to a grid so history accumulates per location, then each location's timeline is cut into episodes.
>
> **Enrich** — distance to the nearest mapped industrial feature from OpenStreetMap, and the land cover underneath. R-tree spatial indexes keep that linear rather than quadratic.
>
> **Classify** — four classes, always with the evidence attached.
>
> **Visualise** — a Leaflet map with filters, a per-site evidence panel, and Plotly analytics.
>
> *(point at the class list)* The model predicts **one of four classes and nothing else**: industrial fire, persistent thermal source, vegetation fire, or other/uncertain.
>
> *(stop — turn to the orange box)*
>
> One design rule matters more than the rest. **Distance to industry is a feature. It is never a label.** The obvious shortcut is "it's near a factory, so call it industrial" — but that's circular. If proximity decides the label *and* is also the model's input, the model has learned nothing. It has memorised a rule we wrote ourselves, and its reported accuracy would be meaningless.

**Delivery:** Top row fast — one breath per stage, don't linger. Bank the time and spend it on the orange box. That's a judge-facing line: it shows you understand a failure mode most teams walk straight into.

**Numbers you can add if you have room:** 3,595 industrial features and 33,488 land-use polygons cached for Gujarat.

---

## Slide 5 — It runs · 60 s

> This is not a mock-up. These are the numbers in our database right now — 90 days of live NASA data over Gujarat. 1,522 detections, 556 sites, 663 burning episodes.
>
> *(point at the orange box and the bar)*
>
> And here's the value proposition as a number. Of those 556 sites, 429 are vegetation fires and 113 are uncertain. **Only 14 are industrial.** That thin red sliver is what an industrial safety operator actually needs to look at. They read 14 rows instead of 556. **That reduction is the product.**
>
> And every label carries its evidence. Site 2, at Hazira: the system says persistent thermal source, high confidence — and shows why. Recurring on 48 of 90 days. A single continuous episode of 73 days that is *still ongoing*. 489 metres from a feature OpenStreetMap tags as ArcelorMittal Nippon Steel.
>
> A user never sees a bare label. They see the features that produced it.

**Delivery:** The red sliver on the proportion bar is your best visual moment in the deck — point at it directly. "556 down to 14" is the sentence to land.

**Critical nuance — say it if you have 5 spare seconds, and definitely if asked:**
> We did **not** predict "steel plant." The model predicts one of four classes, nothing more. The facility name is *retrieved* from OpenStreetMap and shown as supporting context. The difference between a prediction and a database lookup is exactly the kind of claim that shouldn't be blurred.

---

## Slide 6 — What's real, what's next · 50 s

> Two things to be straight about, and then I'll close.
>
> **First:** version one is a documented, transparent rule set. It is not a trained model, and we don't present it as one. We claim **no accuracy figure**, because no labelled test set exists yet. The rules make our domain hypothesis explicit so it can be argued with — and they pre-label the annotation queue, so reviewers *correct* predictions rather than label from scratch.
>
> **Second:** the rules are built to be replaced. The classifier sits behind a single interface, and the same feature vector feeds both versions — so the Random Forest drops in without touching ingestion, the data model, or the interface. The labelling work we do now stays valid.
>
> Next is the labelled dataset, then the trained model evaluated on a held-out split, then the operational layer.
>
> *(look up, to the room)*
>
> Satellites already report where the Earth is hot. **AgniDrishti reports what is burning, how urgent it is, and why — and it shows its evidence every time.** Thank you.

**Delivery:** The honesty beat is a strength, not an apology — deliver it with confidence, not hedging. Judges sit through inflated accuracy claims all day. "We haven't measured it yet, and here's why" is more credible than a number you can't defend, *and* it pre-empts the question they were about to ask.

Deliver the last two lines off the slide, to the room.

---

## Q&A preparation

### Near-certain questions

**"What's your accuracy?"**
> None claimed, deliberately. Accuracy against what? There is no labelled test set for this problem — so any number we gave you would be measured against our own rules, which is circular. Phase 2 is building that test set: 300–500 human-verified sites, labelled from Sentinel-2 imagery, not from proximity. The Random Forest is trained and evaluated on that, with per-class precision and recall published. We'd rather show you a working pipeline and an honest gap than a number we can't defend.

**"Why a rule set and not machine learning?"**
> It *is* going to be machine learning — the rules are v1 scaffolding. You can't train a supervised model without labels, and labels for this problem don't exist off the shelf. The rules do three jobs: they make the pipeline demonstrable end-to-end, they state our hypothesis explicitly so it can be criticised, and they pre-label the annotation queue so reviewers correct rather than label from scratch. That's how we get to a training set efficiently.

**"Why Random Forest and not deep learning?"**
> About twelve structured geospatial features over a few hundred examples. In that regime a Random Forest is more accurate than a neural network *and* it can show which feature drove each decision. For an operator acting on an alert, explainability isn't a bonus — it's the requirement. We'll evaluate XGBoost as a comparison.

**"Isn't 'near a factory → industrial' circular?"**
> Yes — which is exactly why we don't do it. Distance to industry is an input feature, never the label. Labels come from visual verification against Sentinel-2 imagery and map evidence. If proximity both decided the label and fed the model, the model would just be replaying a rule we wrote, and it would fail on the cases that matter — a crop fire 600 m from an industrial estate, or a landfill fire next to one.

**"Is this real-time fire detection?"**
> No, and we're explicit about that. A location is observed a handful of times per day, on satellite overpasses. A fire that starts and is put out between overpasses is never seen. Cloud and dense smoke suppress detections. This is a **screening and prioritisation layer** to direct attention — it does not replace ground sensors, plant safety systems, or the fire service.

**"Why only four classes? Shouldn't landfill or brick kiln be their own class?"**
> Four is deliberate. With a few hundred training examples, every extra class means fewer examples per class and Random Forest splits too thin to learn anything from — we'd be trading real accuracy for apparent granularity. A smouldering landfill lands in persistent thermal source or in other/uncertain depending on its recurrence and context, and the evidence panel still shows you it's a landfill, because the facility type is read from OpenStreetMap and displayed alongside the label. So you don't lose that information — it just isn't something the model claims to predict.

### Likely follow-ups

**"Why VIIRS only? Why not MODIS too?"**
> MODIS reports confidence as a 0–100 integer, VIIRS as low/nominal/high, and the footprints are very different — 1 km against 375 m. Supporting both means normalising two confidence schemes and deduplicating across mismatched pixel geometries. VIIRS alone is finer and gives more detections, so MODIS goes in later as a clean fusion step rather than a special case threaded through the ingestion code.

**"Why isn't Sentinel-2 in the app?"**
> Sentinel-2 isn't published as ready-made web tiles. Serving it means downloading scenes, building cloud-free composites — a raw monsoon scene over Gujarat is mostly cloud — then hosting tiles and matching acquisitions to detection timestamps. None of that improves classification. So we use Sentinel-2 where it genuinely adds value today: verifying labels by eye while building the dataset.

**"Why SQLite? That won't scale."**
> Agreed, and it's a prototype choice, not a preference. SQLite is sufficient for a bounded demo dataset. PostgreSQL with PostGIS is planned, and the trigger is dataset size — once spatial joins and nearest-neighbour queries run over large archives. The architecture is designed so the AI and geospatial pipeline isn't rewritten when that happens; only its surroundings change.

**"Why only Gujarat?"**
> The pipeline ingests the whole state — that's a config value, and widening it is a config change, not a redesign. What's *corridor-scoped* is validation. Our labelled data concentrates on Hazira–Ankleshwar because it contains all four classes in one map view: petrochemical flaring, chemical estates, surrounding cropland, and landfills as confounders. With a small labelling budget, depth beats breadth — spreading the same labels statewide gives a handful of examples per cluster and confidence in none of them.

**"What changed when you got more data?"** *(a strong answer — volunteer it if there's a lull)*
> Our original rules assumed a flare burns at *stable* radiative power, so we gated the persistent class on low variability. Over 90 days that turned out to be backwards: variability actually *rises* with recurrence, because a site observed more often is sampled across more viewing angles, atmospheres and times of day. That gate was rejecting precisely the most persistent sources — every one of the ten most recurrent sites failed it, and the class came back empty. We removed it. Nothing accidental burns on 48 of 90 days; recurrence in an industrial context is sufficient on its own. Variability is still reported and still shapes confidence — it just no longer decides the class.

### The question you don't want, and the answer that wins it

**"Some of your industrial fires are next to a solar park. A solar park doesn't burn."**
> Correct, and that's a real false positive — thank you. What it shows is the limitation we're explicit about: OpenStreetMap gives us the nearest *mapped* feature, and "nearest mapped feature" is not the same as "cause." Those detections are on bare land near Dholera; the solar park is simply the closest thing OSM has tagged. It's exactly the kind of case the annotation queue exists to catch and correct — and it's a good argument for why we won't publish an accuracy number before a human-verified test set exists.

**Do not get defensive here.** Conceding a genuine limitation accurately is the single most credible thing you can do in a technical Q&A.

### Other known limitations — have these ready, state them plainly

- A hotspot is a **pixel, not an address** — VIIRS resolves to ~375 m. We identify an affected area, not a building.
- **Cloud and dense smoke suppress detections**, which matters most during the monsoon.
- **Small or cool fires** fall below the detection threshold and are invisible to the whole pipeline.
- **OSM coverage is uneven** — an unmapped factory yields a misleading distance feature. We treat OSM as good evidence, not an authoritative industrial register.
- **Validation is corridor-scoped** — performance may not transfer cleanly to clusters with different thermal signatures, like ceramics at Morbi or ship-breaking at Alang.

---

## Delivery checklist

- [ ] **Open the deck in Presenter View** — every slide has full speaker notes with its timing band
- [ ] Rehearse **slide 3 and slide 6** aloud twice; they carry the argument
- [ ] Know the four headline numbers cold: **1,522 · 556 · 663 · 14**
- [ ] The four class names, exactly as the app renders them: **Persistent thermal source · Industrial fire · Vegetation fire · Other / uncertain**
- [ ] Know the hero example cold: **Hazira, 48 of 90 days, 73-day ongoing episode, 489 m, ArcelorMittal Nippon Steel**
- [ ] Have the **live app open in a second window** in case they ask for a demo
- [ ] If the numbers were re-ingested after 18 Sep 2026, re-run the figures before presenting (see caveat below)

### ⚠ Before you present — verify the numbers are current

Every figure in the deck comes from the live database as of **18 Sep 2026**. If anyone re-runs ingestion, re-check them:

```bash
cd /Users/preksha/work/projects/agnidrishti && .venv/bin/python -c "
import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings'); django.setup()
from hotspots.models import Site, Detection, Event
from django.db.models import Count
print('detections', Detection.objects.count(), 'sites', Site.objects.count(), 'events', Event.objects.count())
for r in Site.objects.values('label').annotate(n=Count('id')).order_by('-n'): print(' ', r['label'], r['n'])
"
```

Expected: 1,522 / 556 / 663 — vegetation 429, uncertain 113, industrial_fire 8, persistent_source 6 (8 + 6 = the 14 industrial).
