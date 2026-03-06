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
            old_id = engine.swap_recording(
                req.bed_id,
                segment["recording_id"],
                segment.get("best_start_sample", 0),
            )
            event.original_recording_id = old_id
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

    # 2. Restore original recording
    if event and event.original_recording_id:
        engine.swap_recording(bed_id, event.original_recording_id, 0)
        recording_restored = True

    ok = injector.end_event(bed_id, event_id, current_sample)

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
| מספר אירועים על אותה מיטה | ההקלטה מוחלפת לאחרון שהוזרק; בסיום — חוזרת למקורית |
| הקלטה פתולוגית שבמקרה "מבריאה" באמצע | feature override מבטיח שה-risk נשאר גבוה |

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
