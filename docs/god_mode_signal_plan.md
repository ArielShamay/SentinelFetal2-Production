# God Mode — תכנית שדרוג: נתונים אמיתיים על הגרף

**גרסה:** 1.0 | **תאריך:** 2026-03-06 | **סטטוס:** ✅ **COMPLETED — Phase 4 מומש במלואו**
**מחליף:** PLAN.md §10.11 (signal_synthesizer.py — מבוטל)

---

## הבעיה

בתכנון המקורי (PLAN.md §10), God Mode עובד אך ורק ברמת ה-features:
- כשמזריקים אירוע (למשל "late decelerations"), המערכת מבצעת **override על 25 ה-features** שמגיעים ל-LR
- ה-risk score עולה, alert נדלק — **אבל הגרף עצמו לא משתנה**
- רופא שמסתכל על ה-CTG יראה trace תקין לחלוטין, למרות ש-risk score מראה 0.85

**זה פוגע ב-demo** — חוסר עקביות מוחלט בין מה שהגרף מראה לבין מה שהמערכת מדווחת.

---

## הפתרון: גישה דו-שכבתית

### שכבה 1 — החלפת הקלטה (Signal Swap)

כשמפעילים God Mode על מיטה מסוימת עם סוג אירוע (למשל "late decelerations"):

1. **חיפוש בקטלוג:** המערכת מחפשת הקלטה אמיתית מתוך 100 ההקלטות שמכילה **late decelerations אמיתיות**
2. **החלפה:** ה-ReplayEngine מחליף את ההקלטה שהמיטה מנגנת — במקום ההקלטה הרגילה, מנגנים את ההקלטה עם הפתולוגיה
3. **תוצאה:** הגרף מציג **נתוני CTG אמיתיים** עם דיצלרציות מאוחרות — בדיוק כמו שרופא היה רואה אצל יולדת עם בעיה

### שכבה 2 — Feature Override (קיים, ללא שינוי)

במקביל להחלפת ההקלטה, ה-feature override הקיים (PLAN.md §10.5) ממשיך לפעול:
- נותן **אפקט מיידי** על ה-risk score תוך 6 שניות
- משמש כ-"רצפה" — מבטיח שהמודל תמיד יזהה את הבעיה
- אחרי שה-PatchTST מעבד מספיק נתונים מההקלטה הפתולוגית, הזיהוי הטבעי עולה על ה-override

### ציר זמן של ההזרקה

```
t=0      הזרקת אירוע
  ↓
t=6s     Feature override → risk_score עולה מיידית
         ההקלטה מוחלפת → הגרף מתחיל להציג נתונים פתולוגיים
  ↓
t=45s    (ב-10x speed) / t=7.5min (ב-1x speed)
         PatchTST מעבד חלון מלא של נתונים פתולוגיים
         זיהוי טבעי של המודל → feature override הופך מיותר
  ↓
t=end    סיום אירוע → הקלטה חוזרת למקורית
         risk_score יורד בהדרגה ככל שנתונים תקינים ממלאים את ה-buffer
```

---

## מרכיבים טכניים

### 1. סקריפט קטלוג — `scripts/catalog_pathologies.py` ✅

סריקה חד-פעמית של כל ההקלטות (הורץ בהצלחה):

```
לכל recording (552 הקלטות, IDs 1001-1506 + 2001-2046):
  1. טעינת הנתונים (shape 2, T)
  2. הרצת extract_clinical_features() על חלונות sliding (1800 samples, stride 900)
  3. זיהוי פתולוגיות בכל חלון:
     - late_decelerations:    n_late_decelerations > 0
     - variable_decelerations: n_variable_decelerations > 0
     - prolonged_deceleration: n_prolonged_decelerations > 0
     - sinusoidal_pattern:    sinusoidal_detected == 1
     - tachysystole:          tachysystole_detected == 1
     - bradycardia:           is_bradycardia == 1
     - tachycardia:           is_tachycardia == 1
     - low_variability:       variability_category == 0
     - combined_severe:       מספר פתולוגיות בו-זמנית
  4. שמירת המיקום עם הכי הרבה ממצאים / הכי חמור
```

**תוצאות הרצה (2026-03-06):**
```
late_decelerations           220 recordings
variable_decelerations       526 recordings
prolonged_deceleration       182 recordings
sinusoidal_pattern           298 recordings
tachysystole                 521 recordings
bradycardia                  240 recordings
tachycardia                  118 recordings
low_variability              186 recordings
combined_severe              188 recordings
```

**פלט:** `data/god_mode_catalog.json`
```json
{
  "version": 1,
  "generated_at": "2026-03-06T...",
  "catalog": {
    "late_decelerations": [
      {
        "recording_id": "1023",
        "best_start_sample": 4000,
        "n_detections": 5,
        "max_depth_bpm": 32.5,
        "window_count": 3
      }
    ],
    "bradycardia": [...],
    "combined_severe": [...]
  }
}
```

> **combined_severe** — הקלטות שבהן מופיעות מספר פתולוגיות בו-זמנית (late decels + low variability וכו').

### 2. Segment Store — `src/god_mode/segment_store.py`

```python
class SegmentStore:
    """Loaded at startup. Provides recording selection per event type."""

    def __init__(self, catalog_path: Path):
        with open(catalog_path) as f:
            data = json.load(f)
        self._catalog = data["catalog"]

    def get_segment(self, event_type: str) -> dict | None:
        """Returns best matching segment, or None if not found.
        Selects randomly from top 3 matches for variety."""
        entries = self._catalog.get(event_type, [])
        if not entries:
            return None
        top = entries[:min(3, len(entries))]
        return random.choice(top)

    def has_segments(self, event_type: str) -> bool:
        return bool(self._catalog.get(event_type))

    def available_types(self) -> list[str]:
        return [k for k, v in self._catalog.items() if v]
```

### 3. שינויים ב-ReplayEngine — `generator/replay.py`

**הוספת מתודות:**

```python
# RecordingReplay
def seek(self, sample_index: int) -> None:
    """Set playback position to specific sample."""
    self._position = max(0, min(sample_index, len(self._fhr) - 1))

# ReplayEngine
def swap_recording(self, bed_id: str, recording_id: str,
                   start_sample: int = 0) -> str | None:
    """
    Switch recording source for a bed mid-stream.
    Returns previous recording_id for restore, or None if bed not found.
    """
    if bed_id not in self._beds:
        return None
    old_id = self._beds[bed_id].recording_id
    new_replay = RecordingReplay(recording_id, self._recordings_dir)
    new_replay.seek(start_sample)
    self._beds[bed_id] = new_replay
    return old_id
```

### 4. שינויים ב-InjectionEvent — `src/god_mode/types.py`

```python
@dataclass
class InjectionEvent:
    ...  # כל השדות הקיימים מ-PLAN.md §10.3
    original_recording_id: str | None = None  # חדש — לשחזור בסיום
    signal_swapped: bool = False               # חדש — האם הוחלפה הקלטה
```

### 5. זרימת ההזרקה — `api/routers/god_mode.py` ✅

```python
@router.post("/inject", response_model=InjectResponse)
async def inject_event(req: InjectRequest, manager=Depends(get_manager), engine=Depends(get_engine)):
    pipeline = manager.get_pipeline(req.bed_id)
    current_sample = pipeline.current_sample_count

    # 1. Create injection event
    event = InjectionEvent.create(
        bed_id=req.bed_id,
        event_type=req.event_type,
        start_sample=current_sample,
        severity=req.severity,
    )

    # 2. Signal swap — segment_store stored on manager (not app.state)
    segment_store = getattr(manager, "_segment_store", None)
    if segment_store is not None:
        segment = segment_store.get_segment(req.event_type.value)
        if segment is not None:
            # BUG-11: always store TRUE baseline, not current (possibly swapped) recording
            event.original_recording_id = manager.get_baseline_recording(req.bed_id)
            engine.swap_recording(
                req.bed_id,
                segment["recording_id"],
                segment.get("best_start_sample", 0),
            )
            event.signal_swapped = True

    # 3. Register feature override (immediate effect on risk score)
    GodModeInjector.get().add_event(event)

    return InjectResponse(
        event_id=event.event_id,
        status="injected",
        signal_swapped=event.signal_swapped,
        start_sample=current_sample,
    )
```

```python
@router.delete("/events/{event_id}", response_model=EndEventResponse)
async def end_event(event_id: str, bed_id: str = Query(...), manager=Depends(get_manager), engine=Depends(get_engine)):
    injector = GodModeInjector.get()
    pipeline = manager.get_pipeline(bed_id)
    current_sample = pipeline.current_sample_count

    # 1. Get event before ending (to access original_recording_id)
    event = injector.get_event(bed_id, event_id)
    recording_restored = False

    ok = injector.end_event(bed_id, event_id, current_sample)

    # 2. BUG-11: only restore if NO other active swapped events remain
    if event and event.original_recording_id:
        remaining = [e for e in injector.get_events(bed_id)
                     if e.event_id != event_id and e.signal_swapped and e.end_sample is None]
        if not remaining:
            engine.swap_recording(bed_id, event.original_recording_id, 0)
            recording_restored = True

    return EndEventResponse(status="ended" if ok else "not_found", recording_restored=recording_restored)
```

---

## למה הגישה הזו עדיפה על סינתזה

| קריטריון | סינתזה (signal_synthesizer.py) | החלפת הקלטה (הגישה החדשה) |
|-----------|-------------------------------|--------------------------|
| מראה ריאליסטי | ❌ דפוסים מלאכותיים שרופא יזהה כמזויפים | ✅ נתונים אמיתיים מהקלטות CTG |
| זיהוי מודל | ❓ PatchTST לא אומן על נתונים סינתטיים — לא מובטח | ✅ מובטח — אלה אותם נתונים שהמודל ראה באימון |
| מורכבות פיתוח | ❌ גבוהה — צריך לסנתז כל דפוס בנפרד + crossfade | ✅ נמוכה — swap recording + seek |
| תחזוקה | ❌ צריך לכוונן פרמטרים לכל סוג אירוע | ✅ אוטומטי — הקטלוג נוצר מהנתונים |
| עקביות | ❌ סינתזה אולי לא תואמת את מה שה-clinical extractor מצפה | ✅ מלאה — אותם נתונים, אותו pipeline |

---

## מה לא משתנה

- **Feature override** (PLAN.md §10.5) — נשאר בדיוק כפי שהוא. `build_feature_override()` ממשיך לשמש כ-floor.
- **GodModeInjector** (PLAN.md §10.4) — `compute_override()` זהה. הוספת `get_event()` helper.
- **EventAnnotation** (PLAN.md §10.3) — ללא שינוי.
- **PIN Guard** (PLAN.md §11.6) — ללא שינוי.
- **BedState** — שדות `god_mode_active`, `active_events` — ללא שינוי.

---

## מקרי קצה

| מצב | פתרון |
|-----|-------|
| לא נמצאה הקלטה עם הפתולוגיה המבוקשת | feature override בלבד (fallback) — כמו התכנון המקורי |
| קפיצה בגרף ברגע ההחלפה | מינורית — נקודת מעבר אחת שנגללת מהגרף תוך שניות |
| אירוע נגמר אבל buffer עדיין מלא בנתונים פתולוגיים | הנתונים התקינים ממלאים את ה-buffer בהדרגה — risk_score יורד טבעית |
| מספר אירועים על אותה מיטה | BUG-11 fix: `PipelineManager._baseline_recordings` שומר את ההקלטה המקורית. כל event מקבל את ה-baseline (לא chain). בסיום — שחזור רק אם אין אירועים חופפים פעילים. `clear_bed` משחזר ישירות ל-baseline |
| הקלטה פתולוגית שבמקרה "מבריאה" באמצע | feature override מבטיח שה-risk נשאר גבוה |

---

## הסתייגויות עיצוב ידועות (Design Caveats)

### Caveat 1 — Feature Mixing (Signal + Override)

כש-signal swap פעיל, ה-feature override גם פועל. התוצאה: וקטור features היברידי — חלק מהערכים מגיעים מהאות האמיתי (ההקלטה הפתולוגית), וחלק מוזרקים ע"י ה-override.

**למה זה קורה:** ה-override משנה רק תת-קבוצה קטנה של הפיצ'רים (למשל, `LATE_DECELERATIONS` משנה רק `n_late_decelerations` ו-`max_deceleration_depth_bpm`). שאר 9 הפיצ'רים מחושבים מהאות.

**למה זה בסדר:**
- ה-override דוחף פיצ'רים **באותו כיוון** שהאות הפתולוגי מייצר טבעית
- `max()` semantics: ברגע שהאות מייצר ערך חזק יותר, ה-override הופך ל-no-op
- ביטול ה-override בזמן swap ישבור את ה-demo: ה-override נותן **תגובה מיידית** (6s) בעוד שלאות לוקח זמן למלא את ה-buffer
- תקופת ה-hybrid קצרה: 45s ב-10x / 7.5 דקות ב-1x

**חריגים:** `BRADYCARDIA` ו-`LOW_VARIABILITY` משתמשים ב-`min()` (מורידים baseline/variability) — אלה **כן** דורסים את הערך הטבעי. אבל ההקלטה הפתולוגית שנבחרה מהקטלוג כבר מכילה baseline נמוך / variability נמוך, כך שההפרש בפועל קטן.

### Caveat 2 — Transition Windows

מיד אחרי swap, ה-ring buffer מכיל תמהיל של נתונים ישנים וחדשים. חלון הפיצ'רים הראשון עלול לייצר ערכים לא מייצגים.

**למה זה בסדר:**
- Ring buffer = 7200 samples (30 דקות). כמה samples חדשים כמעט לא משפיעים על אגרגציה של 30 דקות
- תוך 1-2 חלונות (6-12 שניות) כבר נכנסים מספיק נתונים חדשים
- Feature override ממסך כל רעש זמני ב-risk score
- לא צפויים false negatives — רק רעש מינורי שנגלל תוך שניות

### Caveat 3 — Demo Bias

הדגמות God Mode מזריקות דפוסים פתולוגיים **נקיים** (מהקטלוג) לתוך הקלטות יציבות. נתוני CTG אמיתיים הם רועשים יותר: ארטיפקטים מחיישנים, תנועת אם, drift בקו בסיס, דפוסים חופפים.

**השלכה:** ב-demo המודל נראה טוב יותר ממה שיהיה במציאות. אלרטים מגיעים בדיוק, risk score עולה חלק.

**הקלה:** ההקלטות בקטלוג הן **הקלטות אמיתיות** (לא סינתטיות) — כך שהרעש הטבעי של ההקלטה נשמר. השלב הבא לשיפור: בחירת הקלטות בסיס רועשות יותר, או הוספת ארטיפקטים אקראיים.

---

## signal_synthesizer.py — מבוטל

הגישה של סינתזת אות CTG (PLAN.md §10.11) **מבוטלת**. הקובץ `src/god_mode/signal_synthesizer.py` **לא ייווצר**. במקום זה — `src/god_mode/segment_store.py`.

---

## סטטוס מימוש — Phase 4 ✅ COMPLETED

כל הקבצים נכתבו ונבדקו:

| קובץ | סטטוס |
|------|-------|
| `scripts/catalog_pathologies.py` | ✅ הורץ — 552 הקלטות נסרקו |
| `data/god_mode_catalog.json` | ✅ נוצר — 9 סוגי אירועים |
| `src/god_mode/__init__.py` | ✅ |
| `src/god_mode/types.py` | ✅ EventType, InjectionEvent + original_recording_id |
| `src/god_mode/overrides.py` | ✅ build_feature_override() לכל 9 סוגים |
| `src/god_mode/segment_store.py` | ✅ SegmentStore טוען קטלוג בזמן startup |
| `src/god_mode/injector.py` | ✅ singleton, compute_override, get_event, clear_bed |
| `generator/replay.py` | ✅ + seek() + swap_recording() |
| `api/middleware/god_mode_guard.py` | ✅ PIN auth, SHA-256, constant-time compare |
| `api/routers/god_mode.py` | ✅ 6 endpoints כולל enable/status |
| `api/services/pipeline_manager.py` | ✅ SegmentStore אתחול |
| `api/main.py` | ✅ GodModeGuard + god_mode router רשומים |

### השלב הבא
**Phase 5 — Frontend Core** ← הבא בתור. ראה AGENTS.md Phase 5.

---

## ניתוח הקטלוג — מה בדיוק יש במחסן (2026-03-08)

> נתונים אלה חושבו בסשן ניפוי, בשילוב קובץ `data/god_mode_catalog.json` עם תוצאות OOF מהמודל המלא (PatchTST + LR, n=552).

---

### מבנה רשומת קטלוג

```json
{
  "recording_id":      "1286",
  "best_start_sample": 11520,
  "window_count":      8,
  "n_detections":      2,
  "max_depth_bpm":     85.2
}
```

| שדה | משמעות |
|-----|--------|
| `recording_id` | מזהה הקובץ `.npy` (למשל `data/recordings/1286.npy`) |
| `best_start_sample` | האינדקס **בתוך** ההקלטה שבו הפתולוגיה הכי חזקה מתחילה. ב-4Hz: ÷4 = שניות, ÷240 = דקות |
| `window_count` | כמה חלונות 7.5-דק (sliding) זיהו את הפתולוגיה בקליניקה. גבוה = פתולוגיה עקבית ואיכותית |
| `n_detections` | כמה אירועים בודדים זוהו בחלון הטוב ביותר (רק לדצלרציות) |
| `max_depth_bpm` | העומק המקסימלי של הירידה ב-bpm (רק לדצלרציות) |
| `baseline_bpm` | קו בסיס FHR שמדד הכלל הקליני (bradycardia / tachycardia) |
| `amplitude_bpm` | משרעת variability (low_variability בלבד) |
| `n_issues` | כמה פתולוגיות שונות מופיעות בו-זמנית (combined_severe בלבד) |

---

### ניתוח מפורט לפי סוג אירוע

#### late_decelerations — 220 הקלטות

| מדד | ערך |
|-----|-----|
| מיקום בהקלטה (best_start_sample) | ממוצע **דקה 44**, טווח 0–82 דק |
| window_count | ממוצע 1.9 — בד"כ אירוע קצר ב-1–2 חלונות |
| max_depth_bpm | ממוצע 56.6 bpm, מינ 21, מקס 103 |
| אחוז זיהוי ע"י המודל המלא | **53.2%** מעל threshold של 46.1% |
| ממוצע risk_score | 0.495 |
| % חמצת אמיתית בהקלטות אלה | 17.7% |

**מה יש בהקלטות:** ירידות FHR שמתחילות **אחרי** שיא הצירה (nadir מגיע ≥30s לאחר peak UC). מייצגות מחסור בחמצן עקב insufficiency שלייתי. מופיעות בממוצע בדקה 44 של ההקלטה — כלומר אחרי warmup מלא של המודל.

---

#### variable_decelerations — 526 הקלטות (הכי נפוץ)

| מדד | ערך |
|-----|-----|
| מיקום | ממוצע **דקה 46**, טווח 0–82 דק |
| window_count | ממוצע 6.5 — **פתולוגיה ממושכת**, נמשכת לאורך ההקלטה |
| max_depth_bpm | ממוצע 55.0, מינ 20, מקס 115 |
| אחוז זיהוי | **39.9%** |
| ממוצע risk_score | 0.435 |
| % חמצת אמיתית | 12.0% |

**מה יש בהקלטות:** ירידות FHR פתאומיות (onset < 30s) — לחיצה על חבל הטבור. שכיחות מאוד בלידה תקינה, לכן אחוז הזיהוי נמוך יחסית (המודל לא ממהר להתריע). ככל שהן עמוקות יותר (wc=8+), אחוז הזיהוי עולה ל-58%.

---

#### prolonged_deceleration — 182 הקלטות

| מדד | ערך |
|-----|-----|
| מיקום | ממוצע **דקה 48**, טווח 0–82 דק |
| window_count | ממוצע 1.7 — בד"כ אירוע אחד ממושך |
| max_depth_bpm | ממוצע 61.3, מינ 17, מקס 118 |
| אחוז זיהוי | **63.7%** |
| ממוצע risk_score | 0.530 |
| % חמצת אמיתית | 19.8% |

**מה יש בהקלטות:** FHR יורד ל-≤-15bpm מהבסיס ונשאר כך **≥2 דקות**. אחד האירועים החמורים ביותר. אחוז זיהוי גבוה יחסית כי הכלל הקליני מזהה זאת ברורות.

---

#### sinusoidal_pattern — 298 הקלטות

| מדד | ערך |
|-----|-----|
| מיקום | ממוצע **דקה 23**, טווח 0–79 דק |
| window_count | ממוצע 2.8 |
| אחוז זיהוי | **37.9%** |
| ממוצע risk_score | 0.420 |
| % חמצת אמיתית | 10.4% |

**מה יש בהקלטות:** גל סינוסואידי חלק ב-FHR (3–5 מחזורים לדקה, משרעת 3–25 bpm) — סימן לאנמיה עוברית חמורה. מופיע מוקדם (דקה 23 בממוצע). **77 הקלטות מתחילות לפני ה-warmup של 7.5 דק.** מוזרק מיידית ב-god mode ע"י feature override עד שהמודל מתחמם.

---

#### tachysystole — 521 הקלטות

| מדד | ערך |
|-----|-----|
| מיקום | ממוצע **דקה 11** — **הכי מוקדם** |
| window_count | ממוצע 8.5 — **הפתולוגיה הכי עקבית** לאורך ההקלטה |
| אחוז זיהוי | **38.8%** |
| ממוצע risk_score | 0.427 |
| % חמצת אמיתית | 12.1% |

**מה יש בהקלטות:** >5 צירות ב-10 דקות. 264 מתוך 521 הקלטות **מתחילות לפני דקה 7.5** — הפתולוגיה קיימת מתחילת ההקלטה. אחוז זיהוי נמוך יחסית כי tachysystole לבד לא מנבא חמצת באופן ישיר.

---

#### bradycardia — 240 הקלטות

| מדד | ערך |
|-----|-----|
| מיקום | ממוצע **דקה 46**, טווח 0–82 דק |
| window_count | ממוצע 2.6 |
| baseline_bpm | ממוצע 95.6, מינ 55, מקס 105 bpm |
| אחוז זיהוי | **50.8%** |
| ממוצע risk_score | 0.478 |
| % חמצת אמיתית | 17.9% |

**מה יש בהקלטות:** baseline FHR < 110 bpm. 19 הקלטות מתחילות לפני ה-warmup. ב-streaming test שהורץ, latency ממוצע לזיהוי היה ~24 דקות אחרי ה-best_start_sample — כי LR צריך לצבור window_scores רבים.

---

#### tachycardia — 118 הקלטות

| מדד | ערך |
|-----|-----|
| מיקום | ממוצע **דקה 22**, טווח 0–82 דק |
| window_count | ממוצע 4.9 |
| baseline_bpm | ממוצע 167.7, מינ 165, מקס 195 bpm |
| אחוז זיהוי | **72.0%** — הכי גבוה מכולם |
| ממוצע risk_score | 0.574 |
| % חמצת אמיתית | 18.6% |

**מה יש בהקלטות:** baseline FHR > 160 bpm. הכלל הקליני מזהה זאת ברורות, ולכן זיהוי הגבוה ביותר. 44 הקלטות מתחילות לפני ה-warmup.

---

#### low_variability — 186 הקלטות

| מדד | ערך |
|-----|-----|
| מיקום | ממוצע **דקה 24**, טווח 0–71 דק |
| window_count | ממוצע 2.5 |
| amplitude_bpm | ממוצע 0.4 bpm (נורמלי = 6–25 bpm) — כמעט קו ישר |
| אחוז זיהוי | **38.7%** |
| ממוצע risk_score | 0.435 |
| % חמצת אמיתית | 13.4% |

**מה יש בהקלטות:** FHR יציב כמעט לחלוטין, ללא תנודות. 75 מתוך 186 הקלטות מתחילות לפני ה-warmup. Low variability לבד לא מספיקה לzיהוי חזק.

---

#### combined_severe — 188 הקלטות

| מדד | ערך |
|-----|-----|
| מיקום | ממוצע **דקה 40**, טווח 0–82 דק |
| window_count | ממוצע 1.8 |
| n_issues | 2–3 פתולוגיות במקביל |
| אחוז זיהוי | **55.9%** |
| ממוצע risk_score | 0.505 |
| % חמצת אמיתית | 18.6% |

**מה יש בהקלטות:** שילוב של ≥2 מהבאות: late decelerations + low variability + prolonged deceleration + tachysystole. הסט הכי חמור קלינית.

---

### טבלת סיכום — כל סוגי האירועים

| סוג אירוע | הקלטות | זיהוי% | AvgRisk | מתחיל (דק) | window_count |
|-----------|--------|--------|---------|------------|-------------|
| tachycardia | 118 | **72.0%** | 0.574 | 22 | 4.9 |
| prolonged_decel | 182 | **63.7%** | 0.530 | 48 | 1.7 |
| combined_severe | 188 | 55.9% | 0.505 | 40 | 1.8 |
| late_decelerations | 220 | 53.2% | 0.495 | 44 | 1.9 |
| bradycardia | 240 | 50.8% | 0.478 | 46 | 2.6 |
| variable_decels | 526 | 39.9% | 0.435 | 46 | 6.5 |
| low_variability | 186 | 38.7% | 0.435 | 24 | 2.5 |
| tachysystole | 521 | 38.8% | 0.427 | 11 | 8.5 |
| sinusoidal | 298 | 37.9% | 0.420 | 23 | 2.8 |

**Alert מופיע מ-risk_score > 0.4605 (46.1%)**

---

### ביצועי המודל המלא על כל הנתונים (n=552)

| מדד | ערך |
|-----|-----|
| OOF AUC | **0.7386** [95% CI: 0.678–0.797] |
| Sensitivity | **70.8%** — 46/65 מקרי חמצת אמיתית זוהו |
| Specificity | **65.9%** — 321/487 תקינים זוהו נכון |
| False Positive Rate | 34.1% (166 FP) |
| False Negative Rate | 29.2% (19 FN) |

---

### מיפוי: מתי הפתולוגיה מופיעה בהקלטה

```
             0        10       20       30       40       50       60       70       80 דקות
             |        |        |        |        |        |        |        |        |
tachysystole |====================================================================|  avg 11'
tachycardia  |         =======================================================|      avg 22'
low_var.     |          ======================================================|      avg 24'
sinusoidal   |          =======================================================|     avg 23'
combined_sev |                          ======================================|      avg 40'
late_decels  |                           ======================================|     avg 44'
bradycardia  |                            ========================================|  avg 46'
variable_dec |                            ========================================|  avg 46'
prolonged    |                              =====================================|  avg 48'

warmup גבול: |====7.5====|  (המודל לא יכול לזהות לפני כאן)
```

הקלטות שמתחילות **לפני** ה-warmup:
- tachysystole: 264/521 (51%) ← feature override קריטי עבורן
- sinusoidal: 77/298 (26%)
- low_variability: 75/186 (40%)
- tachycardia: 44/118 (37%)
- bradycardia: 19/240 (8%)
- כל השאר: < 10%
