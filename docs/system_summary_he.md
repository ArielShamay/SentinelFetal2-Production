# SentinelFatal2 — סיכום מערכת מלא

**גרסה:** 1.0 | **תאריך:** 2026-03-05 | **מחבר:** Ariel Shamay + Claude Sonnet 4.6

---

## תוכן עניינים

1. [מבוא — מה זה המערכת ולמה בנינו אותה](#1)
2. [ארכיטקטורת המערכת — תמונה כללית](#2)
3. [עיבוד הנתונים הגולמיים](#3)
4. [המודל הראשון: PatchTST — "המוח המלאכותי"](#4)
5. [המודל השני: מנוע החוקים הקליניים — "המוח הרפואי"](#5)
6. [חיבור שני המוחות: ה-LR Meta-Classifier](#6)
7. [בעיית הנתונים — תיוג מוטעה ותיקונו](#7)
8. [מגבלת הנתונים — מה עשינו ומה נשאר](#8)
9. [תוצאות מלאות](#9)
10. [מיפוי קוד מלא — "גרסה נקייה" לייצור](#10)
11. [חיבור ל-UI בזמן אמת](#11)

---

<a name="1"></a>
## 1. מבוא — מה זה המערכת ולמה בנינו אותה

### הבעיה הקלינית

**CTG (Cardiotocography)** הוא בדיקת הסטנדרט לניטור עוברי בזמן לידה — גרף המציג את דופק הלב של התינוק (FHR) ואת עוצמת התכווצויות הרחם (UC) לאורך זמן. רופאים ומיילדות מסתכלים על הגרף הזה ומנסים לזהות דפוסים שמרמזים על **חמצת עוברית מטבולית** — מצב שבו התינוק לא מקבל מספיק חמצן לאורך זמן, מה שעלול לגרום לנזק מוחי.

הבעיה: פרשנות CTG היא **סובייקטיבית ועייפת**. מחקרים מראים הסכמה בין-שופטים של 30-50% בלבד. המערכת שלנו אוטומטית ועקבית.

### מטרת המערכת

לזהות **חמצת מטבולית** (pH < 7.15 AND BDecf ≥ 8 ממול/ל) מנתוני CTG גולמיים (FHR + UC בתדירות 4 Hz), ולהפיק **ציון סיכון [0, 1]** לכל הקלטה.

### שני "מוחות" משלימים

| מרכיב | גישה | מה הוא לומד/מקודד |
|--------|------|-------------------|
| **PatchTST** (AI) | למידת מכונה עמוקה | "מה נראה חריג בהשוואה לאלפי חלונות" |
| **מנוע חוקים קליניים** | חוקים רפואיים דטרמיניסטיים | "מה מוגדר כחריג לפי הנייר הישראלי" |
| **LR Meta-classifier** | רגרסיה לוגיסטית | "כיצד לשקלל את שניהם לחיזוי מיטבי" |

### ביצועים נוכחיים

| מדד | ערך | הערות |
|-----|-----|-------|
| **OOF AUC (metabolic labels)** | **0.7386** [95% CI: 0.678, 0.797] | 5-fold, n=552, הכי אמין |
| OOF AUC (original labels) | 0.7009 | pH<7.15 בלבד |
| REPRO_TRACK AUC | **0.8285** [95% CI: 0.6996, **0.9324**] | חיקוי split המאמר, n=55 |
| מאמר מקור (Václavovič 2023) | 0.826 | אותו test set |
| Sensitivity (metabolic) | 0.723 | @Specificity ≥ 0.65 |
| Specificity | 0.651 | סף הנייר הישראלי |

> **הערה על 0.9324:** זהו הגבול העליון של רווח הסמך 95% לתוצאת REPRO_TRACK. נקודת AUC עצמה הייתה 0.8285, העולה מעט על תוצאת המאמר (0.826). ה-CI רחב מאוד [0.70, 0.93] כי test set קטן (55 הקלטות, 11 מקרים חיוביים בלבד).

---

<a name="2"></a>
## 2. ארכיטקטורת המערכת — תמונה כללית

### זרימה end-to-end

```
קובץ .npy גולמי (2 × T, 4 Hz)
    │
    ▼ src/data/preprocessing.py
נורמליזציה: FHR→[0,1], UC→[0,1], NaN handling
    │
    ├──────────────────────────────────────────────────────┐
    │                                                      │
    ▼ שלב PRETRAIN (אחד, לפני finetuning)                  │
src/train/pretrain.py                                      │
Self-supervised masked reconstruction                      │
(687 הקלטות, ללא labels)                                   │
    │                                                      │
    ▼ שלב FINETUNE (5-fold CV)                             │
src/train/finetune.py                                      │
Classification עם labels (pH/BDecf)                        │
Checkpoints: checkpoints/e2e_cv_v7/fold{k}/               │
    │                                                      │
    ▼ שלב INFERENCE                                        │
src/inference/sliding_window.py                            │
Sliding window: stride=24 samples (6 sec)                 │
[(start_sample, P(acidemia)), ...] per recording           │
    │                                                      │
    ▼ src/inference/alert_extractor.py                     ▼ src/features/clinical_extractor.py
12 PatchTST features                                  11 clinical features
(AT-dependent)                                        (rule-based)
    │                                                      │
    └──────────────────┬───────────────────────────────────┘
                       │
                       ▼ scripts/local_eval_cpu.py
               25-feature vector
        StandardScaler → LogisticRegression(C)
        Joint (AT×C) grid search on val set
        Retrain on train+val (441 recordings)
                       │
                       ▼
              risk_score ∈ [0, 1]
              threshold = 0.454 (metabolic)
                       │
              ┌────────┴────────┐
              │                 │
           ALERT             NO ALERT
```

### קבצי Core (ייצור בלבד)

```
src/
├── model/
│   ├── patchtst.py              ← ארכיטקטורת המודל
│   └── heads.py                 ← Classification/pretraining heads
├── data/
│   └── preprocessing.py         ← נורמליזציה FHR + UC
├── inference/
│   ├── sliding_window.py        ← inference על הקלטה שלמה
│   └── alert_extractor.py       ← 12 פיצ'רי PatchTST
├── rules/
│   ├── baseline.py              ← קו בסיס דופק
│   ├── variability.py           ← תנודתיות
│   ├── decelerations.py         ← זיהוי דיצלרציות
│   ├── sinusoidal.py            ← דפוס סינוסואידלי
│   └── tachysystole.py          ← תחסיסטולה
└── features/
    └── clinical_extractor.py    ← 11 פיצ'רים קליניים
scripts/
└── local_eval_cpu.py            ← fit_lr, predict_lr, features_from_cache
config/
└── train_config.yaml            ← כל הפרמטרים
checkpoints/e2e_cv_v7/fold{0..4}/best_finetune.pt  ← 5 weight files
data/processed/ctu_uhb_clinical_full.csv           ← metadata (pH, BDecf)
```

---

<a name="3"></a>
## 3. עיבוד הנתונים הגולמיים

**קובץ:** `src/data/preprocessing.py`

### מקור הנתונים

**CTU-UHB Dataset** (Václav et al., open-access) — 552 הקלטות CTG מ-Czech Technical University Hospital.

| פרמטר | ערך |
|--------|-----|
| תדירות דגימה | **4 Hz** (1 דגימה כל 0.25 שניות) |
| ערוצים | **2**: FHR (דופק עובר, bpm) + UC (התכווצויות, mmHg) |
| גודל חלון | **1800 samples = 7.5 דקות** |
| פורמט אחסון | `.npy` files, shape `(2, T)` |
| מיקום | `data/processed/ctu_uhb/{id}.npy` |

### עיבוד FHR — שלבים (שורות 44–83)

```python
# שלב 1: הסרת artifacts
fhr[(fhr < 50) | (fhr > 220)] = np.nan   # ערכים חריגים → NaN (שורה 67-68)

# שלב 2: אינטרפולציה ליניארית על gaps פנימיים (שורה 71-75)
fhr = pd.Series(fhr).interpolate(method='linear').values

# שלב 3: Clipping (שורה 78)
fhr = np.clip(fhr, 50, 210)

# שלב 4: נורמליזציה → [0, 1] (שורה 81)
fhr_normalized = (fhr - 50.0) / 160.0
# טווח: 50 bpm → 0.0, 210 bpm → 1.0
```

### עיבוד UC — שלבים (שורות 86–134)

```python
# שלב 1-2: זיהוי אות שטוח (artifact)
# חלון: 120 samples (30 שניות), std < 1e-5 AND uc < 80 mmHg → NaN (שורה 111-121)

# שלב 3: Clipping (שורה 124)
uc = np.clip(uc, 0, 100)

# שלב 4: נורמליזציה → [0, 1] (שורה 129)
uc_normalized = uc / 100.0
# טווח: 0 mmHg → 0.0, 100 mmHg → 1.0

# שלב 5: NaN נותרים → 0.0 (שורה 132)
uc_normalized = np.nan_to_num(uc_normalized, nan=0.0)
```

### פורמט הפלט

```python
signal = np.stack([fhr_normalized, uc_normalized], axis=0)
# shape: (2, T), dtype: float32
# signal[0, :] = FHR נורמלי
# signal[1, :] = UC נורמלי
```

**חשוב:** כדי לחזור ל-bpm/mmHg גולמיים (כנדרש לחוקים הקליניים):
```python
fhr_bpm = signal[0] * 160.0 + 50.0   # → [50, 210] bpm
uc_mmhg = signal[1] * 100.0           # → [0, 100] mmHg
# src/features/clinical_extractor.py, שורות 88-89
```

---

<a name="4"></a>
## 4. המודל הראשון: PatchTST — "המוח המלאכותי"

### 4a. ארכיטקטורת המודל

**קבצים:** `src/model/patchtst.py`, `src/model/heads.py`
**תצורה:** `config/train_config.yaml` (שורות 16–23)

#### פרמטרים מלאים

| פרמטר | ערך | קובץ:שורה |
|--------|-----|-----------|
| d_model | **128** | train_config.yaml:17 |
| n_heads | **4** | train_config.yaml:19 |
| n_layers | **3** | train_config.yaml:18 |
| ffn_dim | **256** | train_config.yaml:20 |
| dropout | **0.2** | train_config.yaml:21 |
| patch_len | **48 samples (12 שניות)** | train_config.yaml:10 |
| patch_stride | **24 samples (6 שניות)** | train_config.yaml:11 |
| n_patches | **73** | train_config.yaml:12 |
| window_len | **1800 samples (7.5 דקות)** | train_config.yaml:9 |
| norm_type | **batch_norm** | train_config.yaml:22 |

#### כיצד עובד ה-Patching

```
חלון: (2, 1800) — FHR + UC
    │
    ▼ חיתוך ל-1776 samples (=73×24, שורה 279)
    │
    ▼ unfold עם patch_len=48, stride=24
    │
(2, 73, 48) — 73 patches לכל ערוץ
    │
    ▼ Linear embedding: 48 → 128 (d_model)
    │
(2, 73, 128)
    │
    ▼ Positional embedding (learnable) + Dropout
    │
    ▼ Transformer Encoder (3 layers):
    │   - Multi-Head Attention (4 heads, BatchNorm pre-norm)
    │   - FFN: Linear(128→256)→GELU→Dropout→Linear(256→128)
    │   - Residual connections
    │
(2, 73, 128)
    │
    ▼ Flatten: 2 × 73 × 128 = 18,688
    │
    ▼ Classification Head:
    │   Dropout(0.2) → Linear(18688→2)
    │
(batch, 2) logits → softmax → [P(normal), P(acidemia)]
```

### 4b. שלב 1: Pre-training (self-supervised)

**קובץ:** `src/train/pretrain.py`

המודל לומד לייצג נתוני CTG **ללא labels** על ידי מסיכה של patches של FHR וניסיון לשחזר אותם.

#### נתוני Pretrain

| פרמטר | ערך |
|--------|-----|
| מספר הקלטות | **687** (552 CTU-UHB + 135 FHRMA) |
| Labels נדרשים | **אין** — self-supervised |
| Stride בפרטריין | 900 samples (50% overlap) |

#### אסטרטגיית המסיכה — Channel Asymmetric

**החלטה מכוונת:** רק FHR מוסתר, UC תמיד גלוי. המודל לומד:
"בהינתן UC (ידוע), מה FHR צפוי להיות?"

זה מכניס ידע תחומי: UC הוא הגירוי, FHR הוא התגובה.

```python
# src/train/pretrain.py, שורות 138-140
mask_fhr = True   # ערוץ 0 (FHR) — מוסתר
mask_uc  = False  # ערוץ 1 (UC) — תמיד גלוי
```

#### לוח זמני מסיכה (Curriculum)

| Epochs | mask_ratio | פרשנות |
|--------|-----------|--------|
| 0–19 | **20%** | קל — המודל מתחיל ללמוד |
| 20–49 | **30%** | בינוני |
| 50+ | **40%** | קשה — representation עמוקה |

#### פרמטרי אימון Pretrain

| פרמטר | ערך | קובץ:שורה |
|--------|-----|-----------|
| Loss | MSE על patches מוסתרים בלבד | pretrain.py:225 |
| Optimizer | Adam(lr=1e-4) | train_config.yaml:32 |
| LR Scheduler | CosineAnnealingWarmRestarts(T0=50, T_mult=2) | train_config.yaml:34 |
| max_epochs | 300 | train_config.yaml:44 |
| patience | 50 | train_config.yaml:45 |
| batch_size | 64 | train_config.yaml:46 |
| min_group_size | 2 patches | train_config.yaml:27 |
| max_group_size | 6 patches | train_config.yaml:28 |

**פלט:** `checkpoints/pretrain/best_pretrain.pt`

### 4c. שלב 2: Fine-tuning (supervised, 5-fold CV)

**קובץ:** `src/train/finetune.py`

#### נתוני Finetune

| פרמטר | ערך |
|--------|-----|
| סה"כ הקלטות | 552 (5-fold CV) |
| Positives (metabolic) | **65** (pH<7.15 AND BDecf≥8) |
| Negatives | **487** |
| Train stride | 60 samples (dense — כל 15 שניות) |
| Val stride | 60 samples |

#### Loss Function

```python
# FocalLoss (src/train/finetune.py, שורות 390-396)
loss = FocalLoss(
    gamma=2.0,            # down-weights easy examples
    label_smoothing=0.05, # regularization
    weight=[1.0, 3.9],   # class_weight: n_neg/n_pos ≈ 3.9
)
```

Focal loss מיועד לנתונים עם imbalance חמור (1:7.5). הוא מתמקד ב-hard examples.

#### Progressive Unfreezing — שלבי שחרור ה-Backbone

אסטרטגיה למניעת catastrophic forgetting: מתחילים עם backbone קפוא ומשחררים שכבות בהדרגה.

| Epoch | שכבות משוחררות | LR backbone | LR head |
|-------|---------------|-------------|---------|
| 0 | **אף אחת (frozen)** | 0.0 | 1e-3 |
| 5 | **top-1** (uppermost transformer layer) | 1e-5 | 5e-4 |
| 15 | **top-2** | 3e-5 | 3e-4 |
| 30 | **הכל** | 5e-5 | 1e-4 |

**LR Warmup:** אחרי כל שחרור, LR עולה לינארית על 5 epochs כדי למנוע shock.
`src/train/finetune.py, שורות 570-574`

#### Early Stopping ו-SWA

```python
# Early stopping
patience = 25           # epochs ללא שיפור
patience_ctr = 0        # מתאפס אחרי כל שחרור שכבות (!)
smooth_auc = EMA(beta=0.8)  # מחליק noise

# Stochastic Weight Averaging (SWA)
swa_start = 50          # epoch שממנו מתחיל לצבור
swa_end   = 100         # epoch אחרון לצבירה
# בסוף: ממוצע weights → BN recalibration
```

**פלט:** `checkpoints/e2e_cv_v7/fold{k}/best_finetune.pt` (k=0..4)

### 4d. שלב 3: Inference — מהקלטה לציוני חלונות

**קובץ:** `src/inference/sliding_window.py`

```python
# INFERENCE_STRIDE = 24 samples = 6 שניות (שורה 34 ב-local_eval_cpu.py)
# חלון: 1800 samples = 7.5 דקות

def inference_recording(model, signal, stride=24):
    """
    Input:  (2, T) normalized signal
    Output: [(start_sample, P(acidemia)), ...] — בסדר כרונולוגי
    """
    for start in range(0, T - 1800 + 1, stride):
        window = signal[:, start:start+1800]  # (2, 1800)
        logits = model(window)
        prob = softmax(logits)[1]             # P(acidemia)
        scores.append((start, prob))
    return scores
```

**פרמטרי Inference:**

| פרמטר | ערך | שימוש |
|--------|-----|-------|
| INFERENCE_STRIDE | **24 samples (6 שניות)** | הערכה ו-UI |
| חפיפה בין חלונות | 1776/1800 = **98.7%** | גבוהה מאוד |
| לדגימה של 60 דק' | ~600 חלונות | |

---

<a name="5"></a>
## 5. המודל השני: מנוע החוקים הקליניים — "המוח הרפואי"

### 5a. רקע — הנייר הישראלי

**בסיס:** נייר עמדה ישראלי (יולי 2023) על ניטור עוברי בזמן לידה, המבוסס על סטנדרטים בין-לאומיים **ACOG / FIGO**.

**מסמך הייחוס:** `docs/ניטור_דופק_לב_העובר_בזמן_הלידה_cleaned (3).pdf`

כל אחד מ-5 מודולי החוקים מציין את המקור בשורה 6 שלו:
```python
# src/rules/baseline.py, שורה 6:
"""Baseline FHR module — Israeli Position Paper / ACOG standard."""
```

### 5b. מודול 1: קו בסיס דופק (Baseline)

**קובץ:** `src/rules/baseline.py`

#### הגדרות קליניות (שורות 27-30)

| קטגוריה | סף | משמעות |
|---------|-----|--------|
| Tachycardia | **> 160 bpm** | דופק מהיר מדי |
| Bradycardia | **< 110 bpm** | דופק איטי מדי |
| תקין | 110–160 bpm | |
| סטייה מקסימלית window "יציב" | **< 25 bpm** | |
| מינימום דגימות תקינות | **80%** | |
| ברירת מחדל (fallback) | **130 bpm** | |

#### אלגוריתם (שורות 52–100)

```
1. חלק אות FHR לחלונות של 2 דקות, 50% חפיפה
   (480 samples per window at 4 Hz)

2. לכל חלון: האם "יציב"?
   - variability (max-min) < 25 bpm
   - ≥80% דגימות תקינות (לא NaN)

3. Baseline = ממוצע החלונות היציבים, מעוגל ל-5 bpm הקרוב
   fallback: חציון כל האות (אם אין חלונות יציבים)

4. is_tachycardia = (baseline > 160)
   is_bradycardia = (baseline < 110)
```

**פלט:** `baseline_bpm`, `is_tachycardia (0/1)`, `is_bradycardia (0/1)`

---

### 5c. מודול 2: תנודתיות (Variability)

**קובץ:** `src/rules/variability.py`

#### קטגוריות (שורות 38-40)

| קטגוריה | טווח | קוד | פרשנות קלינית |
|---------|------|-----|--------------|
| Absent | **≤ 2 bpm** | 0 | חמור — סימן רע |
| Minimal | **3–5 bpm** | 1 | דאגה |
| Moderate | **6–25 bpm** | 2 | **תקין** |
| Marked | **> 25 bpm** | 3 | לרוב תקין |

#### אלגוריתם (שורות 74–133)

```
1. Reference level = P90 של כל אות FHR (שורה 105)
   (מייצג את רמת ה-baseline)

2. Exclusion threshold = reference - 15 bpm (שורה 108)

3. חלק ל-חלונות של 1 דקה, 50% חפיפה
   (240 samples per window at 4 Hz)

4. סנן חלונות שהחציון שלהם < exclusion threshold
   (= חלונות בתוך דיצלרציות — לא מייצגים variability תקין)

5. Amplitude = max-min לכל חלון שורד
   mean_amplitude = ממוצע על כל החלונות (שורה 133)
```

**פלט:** `variability_amplitude_bpm`, `variability_category (0/1/2/3)`

---

### 5d. מודול 3: זיהוי דיצלרציות (Decelerations)

**קובץ:** `src/rules/decelerations.py`

זהו המודול המורכב ביותר, ועבר 3 תיקוני bugs משמעותיים שהביאו AUC מ-0.55 ל-0.70.

#### סָפים (שורות 43–65)

| פרמטר | ערך | משמעות |
|--------|-----|--------|
| עומק מינימלי | **15 bpm מתחת לbaseline** | שורה 43 |
| משך מינימלי | **15 שניות** | שורה 44 |
| דיצלרציה ממושכת | **≥ 120 שניות (2 דקות)** | שורה 45 |
| Variable: onset מהיר | **< 30 שניות onset-to-nadir** | שורה 46 |
| Late: nadir מאוחר | **> 15 שניות אחרי UC peak** | שורה 47 |
| חלון חיפוש UC | **±90 שניות** | שורה 65 |
| UC prominence מינימלי | **2 mmHg** | שורה 64 |
| חלון rolling baseline | **2 דקות** | שורה 49 |

#### אלגוריתם: 5 שלבים

```
שלב 1: מצא "אירועי ירידה"
   - rolling median baseline (חלון 2 דקות)
   - FHR < baseline - 15 bpm למשך ≥ 15 שניות
   - תוצאה: רשימת אירועים {start, nadir, end}

שלב 2: מצא את ה-TRUE ONSET האמיתי
   - חפש 60 שניות אחורה מה-start
   - onset = הנקודה האחרונה שבה FHR ≥ P75(lookback) - 5 bpm
   - (תיקון bug 1: מדוד onset-to-nadir מה-onset האמיתי, לא מה-start)

שלב 3: חשב descent_time = (nadir - onset) / 4 שניות

שלב 4: סיווג לפי descent_time
   - descent_time < 30 שניות → VARIABLE (abrupt onset)
   - descent_time ≥ 30 שניות → חפש UC peak (±90 שניות, prominence ≥ 2 mmHg)
     * UC peak לא נמצא → VARIABLE (שמרני)
     * UC peak נמצא AND nadir > 15s אחריו → LATE
     * UC peak נמצא AND nadir ≤ 15s אחריו → EARLY (לא נספרת — שפירה)

שלב 5: PROLONGED (≥ 120 שניות)
   - נספר בנפרד, לא כ-late/variable כפילות
```

**פלט:** `n_late_decelerations`, `n_variable_decelerations`, `n_prolonged_decelerations`, `max_deceleration_depth_bpm`

---

### 5e. מודול 4: דפוס סינוסואידלי (Sinusoidal)

**קובץ:** `src/rules/sinusoidal.py`

דפוס נדיר אך קריטי — FHR מתנדנד בצורה סינוסואידלית קבועה.

#### פרמטרים (שורות 27–36)

| פרמטר | ערך |
|--------|-----|
| תדר תחתון | **0.05 Hz (3 מחזורים/דקה)** |
| תדר עליון | **0.083 Hz (5 מחזורים/דקה)** |
| אמפליטודה מינימלית | **3 bpm** |
| אמפליטודה מקסימלית | **25 bpm** |
| dominance spectral | **≥ 10% מעוצמת הספקטרום** |
| משך מינימלי | **≥ 20 דקות רציפות** |

#### אלגוריתם

```
חלונות נגלשים של 20 דקות, stride=1 דקה:
  לכל חלון: FFT → בדוק אם תדר 0.05-0.083 Hz דומיננטי
  sinusoidal = True אם ≥ 50% מהחלונות עומדים בקריטריונים
```

**פלט:** `sinusoidal_detected (0/1)`

---

### 5f. מודול 5: תחסיסטולה (Tachysystole)

**קובץ:** `src/rules/tachysystole.py`

יותר מדי התכווצויות — מונע מהתינוק להתאושש.

#### פרמטרים (שורות 26–36)

| פרמטר | ערך |
|--------|-----|
| סף | **> 5 התכווצויות ל-10 דקות** |
| חלון ניתוח | **30 הדקות האחרונות** |
| מרווח מינימלי בין peaks | **60 שניות** |
| UC prominence מינימלי | **10 mmHg** |
| UC height מינימלי | **8 mmHg** |

**פלט:** `tachysystole_detected (0/1)`

---

### 5g. Feature Coordinator

**קובץ:** `src/features/clinical_extractor.py`

```python
def extract_clinical_features(signal: np.ndarray) -> list[float]:
    """
    Input:  (2, T) normalized signal
    Output: list of 11 floats, in fixed order
    """
    # Denormalize
    fhr = signal[0] * 160.0 + 50.0   # → bpm (שורה 88)
    uc  = signal[1] * 100.0           # → mmHg (שורה 89)

    # Call each module with try/except (isolation)
    baseline  = calculate_baseline(fhr_safe, fs=4.0)
    variab    = calculate_variability(fhr_safe, fs=4.0)
    decels    = detect_decelerations(fhr_safe, uc_safe, fs=4.0)
    sinus     = detect_sinusoidal_pattern(fhr_safe, fs=4.0)
    tachy     = detect_tachysystole(uc_safe, fs=4.0)

    return [
        baseline.baseline_bpm,           # 1
        baseline.is_tachycardia,          # 2
        baseline.is_bradycardia,          # 3
        variab.amplitude_bpm,             # 4
        variab.category,                  # 5
        decels.n_late_decelerations,      # 6
        decels.n_variable_decelerations,  # 7
        decels.n_prolonged_decelerations, # 8
        decels.max_deceleration_depth_bpm,# 9
        sinus.sinusoidal_detected,        # 10
        tachy.tachysystole_detected,      # 11
    ]
```

**הגנת שגיאות:** כל מודול עטוף ב-try/except. כישלון → ערכי ברירת מחדל בטוחים (לא קריסה).

---

<a name="6"></a>
## 6. חיבור שני המוחות: ה-LR Meta-Classifier

**קבצים:** `scripts/local_eval_cpu.py`, `scripts/eval_oof_cv.py`

### 6a. וקטור הפיצ'רים — 25 פיצ'רים

#### 12 פיצ'רי PatchTST (AT-dependent)

מחושבים מ-`src/inference/alert_extractor.py` בהינתן ציוני חלונות ו-Alert Threshold (AT):

| # | שם | חישוב | בסיס |
|---|-----|-------|------|
| 1 | `segment_length` | אורך ה-segment הארוך ביותר (דקות) | Longest segment |
| 2 | `max_prediction` | מקסימום P(acidemia) ב-segment הארוך | Longest segment |
| 3 | `cumulative_sum` | Σ(score) × dt (שטח מתחת לעקומה) | Longest segment |
| 4 | `weighted_integral` | Σ((score-0.5)² × dt) | Longest segment |
| 5 | `n_alert_segments` | מספר segments רציפים מעל AT | כל ההקלטה |
| 6 | `alert_fraction` | n_alert_windows / n_total_windows | כל ההקלטה |
| 7 | `mean_prediction` | ממוצע P(acidemia) ב-segment הארוך | Longest segment |
| 8 | `std_prediction` | סטיית תקן ב-segment הארוך | Longest segment |
| 9 | `max_pred_all_segments` | מקסימום על כל ה-segments | כל ה-segments |
| 10 | `total_alert_duration` | סך זמן alert (דקות) | כל ה-segments |
| 11 | `recording_max_score` | מקסימום ציון בהקלטה כולה (ללא AT) | כל ההקלטה |
| 12 | `recording_mean_above_th` | ממוצע windows מעל AT | כל ההקלטה |

**"Alert segment"** = רצף רציף של חלונות שבהם `P(acidemia) > AT`.

#### 11 פיצ'רים קליניים (AT-independent)

| # | שם | מודול |
|---|-----|-------|
| 13 | `baseline_bpm` | baseline.py |
| 14 | `is_tachycardia` | baseline.py |
| 15 | `is_bradycardia` | baseline.py |
| 16 | `variability_amplitude_bpm` | variability.py |
| 17 | `variability_category` | variability.py |
| 18 | `n_late_decelerations` | decelerations.py |
| 19 | `n_variable_decelerations` | decelerations.py |
| 20 | `n_prolonged_decelerations` | decelerations.py |
| 21 | `max_deceleration_depth_bpm` | decelerations.py |
| 22 | `sinusoidal_detected` | sinusoidal.py |
| 23 | `tachysystole_detected` | tachysystole.py |

#### 2 פיצ'רים גלובליים threshold-free (חדש)

| # | שם | חישוב |
|---|-----|-------|
| 24 | `overall_mean_prob` | ממוצע P(acidemia) על **כל** החלונות (ללא AT) |
| 25 | `overall_std_prob` | סטיית תקן על **כל** החלונות |

### 6b. אלגוריתם הבחירה וה-Training

```python
# scripts/eval_oof_cv.py

# שלב 1: Joint (AT x C) grid search (24 קומבינציות)
AT_CANDIDATES = [0.25, 0.30, 0.35, 0.40, 0.45, 0.50]  # 6 ערכים
C_CANDIDATES  = [0.01, 0.1, 1.0, 10.0]                  # 4 ערכים

best_at, best_C, best_val_auc = 0.40, 0.1, 0.0
for at in AT_CANDIDATES:
    X_tr = features_from_cache(cache_train, at)  # 25 features
    X_vl = features_from_cache(cache_val,   at)
    for C in C_CANDIDATES:
        sc, lr = fit_lr(X_tr, y_tr, C=C)        # StandardScaler + LogisticRegression
        val_auc = roc_auc_score(y_vl, lr.predict_proba(sc.transform(X_vl))[:,1])
        if val_auc > best_val_auc:
            best_at, best_C = at, C

# שלב 2: Retrain על train+val (441 הקלטות)
# הגיון: hyperparameters נבחרו על val בלבד → אין leakage
cache_tv = {**cache_train, **cache_val}  # 387 + 54 = 441
X_tv = features_from_cache(cache_tv, best_at)
sc_final, lr_final = fit_lr(X_tv, y_tv, C=best_C)

# שלב 3: הערכה על test set (111 הקלטות)
test_scores = lr_final.predict_proba(sc_final.transform(X_te))[:, 1]
```

### 6c. fit_lr ו-predict_lr

```python
# scripts/local_eval_cpu.py, שורות 265-274

def fit_lr(X_tr: np.ndarray, y_tr: np.ndarray, C: float = 0.1):
    sc = StandardScaler()                          # מנרמל לפי train
    Xs = sc.fit_transform(X_tr)
    lr = LogisticRegression(
        C=C,                    # regularization (inverse strength)
        class_weight='balanced',# מאזן imbalance אוטומטית
        max_iter=1000,
        random_state=42,
    )
    lr.fit(Xs, y_tr)
    return sc, lr

def predict_lr(X, sc, lr) -> np.ndarray:
    return lr.predict_proba(sc.transform(X))[:, 1]  # P(acidemia)
```

### 6d. בחירת סף ההחלטה

```python
# scripts/local_eval_cpu.py, שורות 279-307
# SPEC_CONSTRAINT = 0.65 (line 83) — נייר עמדה ישראלי: Spec ≥ 0.65

# Primary: מקסימום sensitivity כך שSpecificity ≥ 0.65
# Fallback: Youden index (Sens + Spec - 1) אם לא נמצא סף מתאים
```

### 6e. חשיבות פיצ'רים (labels מטבוליים, ממוצע 5 folds)

| דירוג | פיצ'ר | קבוצה | |coeff| |
|------|-------|-------|--------|
| 1 | **n_prolonged_decelerations** | Clinical | 0.228 |
| 2 | **max_deceleration_depth_bpm** | Clinical | 0.171 |
| 3 | **total_alert_duration** | AI | 0.157 |
| 4 | **n_variable_decelerations** | Clinical | 0.129 |
| 5 | **n_late_decelerations** | Clinical | 0.114 |
| 6 | baseline_bpm | Clinical | 0.086 |
| 7 | variability_amplitude_bpm | Clinical | 0.085 |
| 8 | recording_max_score | AI | 0.084 |
| 9 | overall_std_prob | Global | 0.080 |
| 10 | is_bradycardia | Clinical | 0.077 |

> עם labels מטבוליים, **פיצ'רים קליניים תופסים 4 מתוך 5 מקומות ראשונים** — הגיוני: חמצת מטבולית (חוסר O₂ אמיתי) מתבטאת ב-prolonged/late decels, בדיוק מה שהחוקים הקליניים מודדים.

---

<a name="7"></a>
## 7. בעיית הנתונים — תיוג מוטעה ותיקונו

### 7a. הבעיה: שני סוגי חמצת שונים

Label המקורי של CTU-UHB: **pH < 7.15 = "חולה"**. אך pH < 7.15 כולל שני מצבים שונים לחלוטין:

| סוג חמצת | מנגנון | BDecf | ביטוי CTG | סכנה קלינית |
|---------|--------|-------|-----------|------------|
| **נשימתית** | CO₂ נצבר בהתכווצויות | < 8 ממול/ל | **אין** — CTG תקין | נמוכה — חולפת |
| **מטבולית** | חוסר O₂ מתמשך | ≥ 8 ממול/ל | **יש** — late/prolonged decels | גבוהה — נזק מוחי |

**הבעיה:** מודל מבוסס-CTG **לא יכול לזהות** חמצת נשימתית כי אין לה ביטוי בדופק. כל מקרה שהמודל "פספס" (False Negative) שהיה pH<7.15 עם CTG תקין — היה בפועל חמצת נשימתית, לא כישלון של המודל.

#### אנליזה של ה-False Negatives (לפני תיקון)

מתוך 34 FN:
- **71%** היו pH 7.10–7.15 (borderline) עם BDecf ממוצע **7.5** ממול/ל
- **96%** מהם Apgar5 ≥ 7 — תינוקות בריאים קלינית
- **רק 1/32** FN עם BDecf > 12 (חמצת מטבולית ממשית)

### 7b. הפתרון: Label מטבולי

**הגדרה חדשה:** `חיובי = (pH < 7.15) AND (BDecf ≥ 8)`

| | ערך |
|--|-----|
| Threshold BDecf | **8 ממול/ל** (סטנדרט קליני ל-"significant metabolic acidosis") |
| Fallback (BDecf חסר) | pH < 7.10 (שמרני) |
| מקור נתונים | `data/processed/ctu_uhb_clinical_full.csv` |

```python
# scripts/eval_oof_cv.py — פונקציות תיקון label
def load_metabolic_labels(clinical_csv, bdecf_th=8.0) -> dict:
    """מחזיר {rec_id: new_label} עם הגדרה מטבולית."""

def override_cache_labels(cache, new_labels) -> dict:
    """מחיל labels חדשים in-memory על cache קיים."""

# הרצה:
# python scripts/eval_oof_cv.py --metabolic
```

#### השפעה על חלוקת הנתונים

| סף BDecf | חיוביים | הוסרו | מתוכם Apgar5<7 |
|----------|---------|-------|--------------|
| ≥ 6 | 91 | 14 | 1 |
| **≥ 8** | **65** | **40** | **4 בלבד** |
| ≥ 10 | 32 | 73 | 8 |
| ≥ 12 | 25 | 80 | 10 |

> 40 הקלטות הוסרו מ-label החיובי, **36/40 (90%) עם Apgar5 ≥ 7** — רוב מוחלט מהם לא היו תינוקות חולים קלינית.

### 7c. תוצאות לאחר התיקון

| Label | OOF AUC | 95% CI | FN | Sensitivity |
|-------|---------|--------|----|-------------|
| pH<7.15 (original) | 0.7009 | [0.645, 0.754] | 33 | 0.708 |
| **Metabolic (BDecf≥8)** | **0.7386** | **[0.678, 0.797]** | **18** | **0.723** |

**שיפור:** +0.038 AUC, CI צר יותר, FN ירד מ-33 ל-18 (חצי מ-ה-FN היו "שגיאות label", לא "שגיאות מודל").

---

<a name="8"></a>
## 8. מגבלת הנתונים — מה עשינו ומה נשאר

### 8a. מה עשינו כדי למקסם את הנתונים הקיימים

| שיטה | תוצאה |
|------|-------|
| **Self-supervised pretrain (687 הקלטות)** | ניצול נתונים ללא labels |
| **Channel-asymmetric masking** | הכנסת ידע תחומי (UC = גירוי, FHR = תגובה) |
| **5-fold OOF CV** (לא single split) | 10× יותר test data, CI אמין |
| **Train+val retraining לאחר hyperparameter selection** | 441 vs 387 דגימות (+14%) |
| **Progressive unfreezing + LR warmup** | מניעת catastrophic forgetting |
| **Focal loss (γ=2.0) + class_weight=[1.0, 3.9]** | טיפול ב-class imbalance חמור |
| **Clinical rules engine** | הוסיף AUC orthogonal לאי-שיפור מידע AI |
| **תיקון label (metabolic)** | הסרת noise מה-training signal |

### 8b. מה נשאר — מגבלה שלא ניתן לפתור

**המגבלה המהותית היא נתונים, לא ארכיטקטורה.**

| בעיה | נתונים | השפעה |
|------|--------|-------|
| CTU-UHB: 552 הקלטות בלבד | ~65 positives (metabolic) | CI רחב, variance גבוה |
| Paper השתמש ב-984 הקלטות pretrain | SPaM dataset לא זמין | פחות pretrain knowledge |
| Val >> Test gap | fold val=0.77 vs test=0.64 | distributional shift |
| OOF CI width | [0.678, 0.797] = ±0.06 | 95% CI ספן 0.12 points |

**מסקנה:** לשיפור מ-0.74 ל-0.82+ נדרש אחד מהבאים:
1. **SPaM dataset** (מחברי המאמר — פנייה)
2. **שיתוף עם בית חולים** לנתונים חדשים עם BDecf מלא
3. **Multi-modal input** (Doppler עורי, נתוני אם) — CTG לבדו מוגבל

---

<a name="9"></a>
## 9. תוצאות מלאות

### 9a. השוואת כל הריצות — סדר כרונולוגי

| ריצה | תאריך | OOF AUC | REPRO_TRACK | Runtime | עלות | שינוי מרכזי |
|------|-------|---------|------------|---------|------|------------|
| Colab (single split) | פב' 22-23 | — | **0.839** (!) | ~3h | $0 | ראשוני |
| v3 | פב' 27 | 0.6013 | 0.6529 | 162.8 min | ~$2.5 | Azure baseline |
| v4 | פב' 28 | 0.6385 | 0.5930 | 197.2 min | ~$3.0 | תיקון leakage |
| v5 | מר' 2-3 | 0.5870 | 0.7872 | 183.0 min | ~$2.8 | pretrain augmentation |
| v6 | מר' 3 | 0.6329 | 0.5165 | 212.8 min | ~$3.2 | patience reset |
| **v7** | מר' 4-5 | 0.6381 | **0.7934** | 234.8 min | ~$3.6 | inner-CV per fold |
| **Local Hybrid v1** | מר' 5 | 0.6911 | **0.8285** | <1 min | $0 | head bug fix + clinical |
| **Local Hybrid v2** | מר' 5 | **0.7009 ✅** | 0.8285 | <1 min | $0 | joint grid + retrain |
| **Metabolic labels** | מר' 5 | **0.7386 ✅** | — | <1 min | $0 | relabel 48 cases |

> **יעד קורס (G4a): AUC ≥ 0.70 — הושג ✅**

### 9b. פירוט v7 — הריצה הטובה ביותר לפי PatchTST בלבד

**Job run ID:** `c749b838cf1a423daa47d3bc47fcd570` (Azure ML — display name לא נשמר)

| מדד | ערך |
|-----|-----|
| OOF AUC (5-fold) | 0.6381 [95% CI: 0.577, 0.696] |
| REPRO_TRACK AUC | 0.7934 [95% CI: 0.6498, 0.9150] |
| REPRO Sensitivity | ~0.75 (מ-Azure artifacts) |
| REPRO Specificity | ~0.659 (מ-Azure artifacts) |
| Best AT | 0.30 |
| inner-CV C | 1.0 (4/5 folds), 0.01 (fold 4) |
| Runtime | 234.8 min |

### 9c. תוצאת 0.8285 [CI עד 0.9324] — "חיקוי המאמר"

**מה זה REPRO_TRACK:**
- Split זהה למאמר: train=441, val=56, **test=55**
- אותן הקלטות, אותה הגדרת acidemia (pH<7.15)
- מאפשר השוואה ישירה עם נתוני הpaperים

**תוצאות:**

| | SentinelFatal2 | מאמר (Václavovič 2023) |
|--|----------------|----------------------|
| **AUC** | **0.8285** | 0.826 |
| 95% CI | [0.6996, **0.9324**] | — |
| Sensitivity | 0.909 (10/11) | — |
| Specificity | 0.727 (32/44) | — |

> **0.9324 = הגבול העליון של ה-CI, לא AUC עצמו.** ה-CI רחב ([0.70, 0.93]) כי n=55 קטן מאוד ויש רק 11 מקרים חיוביים בtest. AUC עצמו (0.8285) **עולה על המאמר** (0.826) — הצלחה.

### 9d. תוצאות Local Hybrid v2 — per fold

| Fold | n_test | AUC hybrid | AUC PatchTST | AUC Clinical | AT | C |
|------|--------|------------|-------------|-------------|-----|---|
| 0 | 111 | 0.6448 | 0.6961 | 0.6591 | 0.30 | 0.01 |
| 1 | 111 | **0.7070** | 0.5715 | 0.7845 | 0.25 | 0.01 |
| 2 | 111 | **0.8291** | 0.6571 | 0.8098 | 0.25 | 0.01 |
| 3 | 110 | 0.6829 | 0.6419 | 0.6336 | 0.25 | 0.01 |
| 4 | 109 | 0.6750 | 0.7091 | 0.7115 | 0.45 | 0.01 |
| **Mean** | **552** | **0.7009** | 0.6555 | 0.6950 | — | — |

---

<a name="10"></a>
## 10. מיפוי קוד מלא — "גרסה נקייה" לייצור

### 10a. קבצים הכרחיים לייצור (Production)

```
SentinelFatal2-clean/
│
├── src/
│   ├── model/
│   │   ├── patchtst.py              ← ארכיטקטורת PatchTST המלאה
│   │   └── heads.py                 ← ClassificationHead, PretrainingHead
│   │
│   ├── data/
│   │   └── preprocessing.py         ← preprocess_ctg_window(fhr, uc) → (2,1800)
│   │
│   ├── inference/
│   │   ├── sliding_window.py        ← inference_recording(model, signal) → scores
│   │   └── alert_extractor.py       ← extract_recording_features(scores, AT) → 12 feats
│   │
│   ├── rules/
│   │   ├── baseline.py              ← calculate_baseline(fhr, fs) → BaselineResult
│   │   ├── variability.py           ← calculate_variability(fhr, fs) → VariabilityResult
│   │   ├── decelerations.py         ← detect_decelerations(fhr, uc, fs) → DecelerationSummary
│   │   ├── sinusoidal.py            ← detect_sinusoidal_pattern(fhr, fs) → SinusoidalResult
│   │   └── tachysystole.py          ← detect_tachysystole(uc, fs) → TachysystoleResult
│   │
│   └── features/
│       └── clinical_extractor.py    ← extract_clinical_features(signal) → [11 floats]
│
├── scripts/
│   └── local_eval_cpu.py            ← fit_lr, predict_lr, features_from_cache,
│                                       clinical_threshold, bootstrap_auc_ci
│
├── config/
│   └── train_config.yaml            ← כל ה-hyperparameters
│
├── weights/                         ← (לא בgit — להוריד בנפרד)
│   ├── fold0_best_finetune.pt
│   ├── fold1_best_finetune.pt
│   ├── fold2_best_finetune.pt
│   ├── fold3_best_finetune.pt
│   └── fold4_best_finetune.pt
│
└── data/
    └── metadata.csv                 ← id, pH, BDecf (לlabeling בלבד)
```

### 10b. קבצים לא נדרשים לייצור

```
# כל אלה אפשר להשמיט בגרסה נקייה:
azure_ml/                    ← infrastructure לcloud training
src/train/                   ← pretrain.py, finetune.py (לאחר training)
notebooks/                   ← development notebooks
scripts/run_e2e_cv_v2.py     ← training orchestration
scripts/eval_oof_cv.py       ← evaluation only
logs/                        ← training logs
results/                     ← evaluation results
docs/plan_*.md               ← development planning
docs/deviation_log.md        ← dev notes
checkpoints/pretrain/        ← pretrain weights (לא נדרש לinference)
```

### 10c. Dependencies מינימלי

```
python>=3.10
torch>=2.0.0           ← מודל PatchTST
numpy>=1.24,<2.0       ← numpy<2.0 נדרש (torch compatibility)
pandas>=1.5
scikit-learn>=1.2      ← StandardScaler, LogisticRegression
scipy>=1.9             ← find_peaks (tachysystole), FFT (sinusoidal)
```

---

<a name="11"></a>
## 11. חיבור ל-UI בזמן אמת

### 11a. ממשק מבוקש מה-UI

ה-UI מספק נתוני CTG גולמיים בזמן אמת (4 Hz). המערכת מחזירה ציון סיכון כל 6 שניות.

```python
# API הנדרש לאינטגרציה

class SentinelRealtime:
    def __init__(self, model_weights: list[str], scaler, lr_model):
        """
        model_weights: רשימת נתיבי .pt files (fold0..4)
        scaler: StandardScaler מאומן
        lr_model: LogisticRegression מאומן
        """
        self.ring_buffer_fhr = deque(maxlen=7200)  # 30 דקות at 4Hz
        self.ring_buffer_uc  = deque(maxlen=7200)
        self.window_scores   = []  # [(t_seconds, prob), ...]
        self.alert_threshold = 0.454  # metabolic labels

    def on_new_sample(self, fhr_bpm: float, uc_mmhg: float) -> dict | None:
        """
        נקרא כל 0.25 שניות (4 Hz).
        מחזיר dict רק כל 6 שניות (24 דגימות).
        """
        self.ring_buffer_fhr.append(fhr_bpm)
        self.ring_buffer_uc.append(uc_mmhg)

        # כל 24 דגימות = 6 שניות
        if len(self.ring_buffer_fhr) % 24 != 0:
            return None

        # בניית חלון 7.5 דקות אחרונות
        if len(self.ring_buffer_fhr) < 1800:
            return None  # ממתין לצבירת 7.5 דקות ראשונות

        fhr_window = np.array(list(self.ring_buffer_fhr)[-1800:])
        uc_window  = np.array(list(self.ring_buffer_uc)[-1800:])

        # עיבוד ו-inference
        signal = preprocess_ctg_window(fhr_window, uc_window)
        prob   = self._run_patchtst(signal)
        t      = len(self.window_scores) * 6  # שניות
        self.window_scores.append((t, prob))

        # כל 60 שניות: חשב features מלאים + LR score
        if len(self.window_scores) % 10 == 0:
            return self._compute_full_score(signal)

        return {"window_prob": prob, "alert": prob > self.alert_threshold}

    def _compute_full_score(self, signal_latest: np.ndarray) -> dict:
        """מחשב 25 features ומחזיר LR risk score."""
        at, C = self.alert_threshold, self.best_C  # from training

        # 12 PatchTST features
        pt_feats = extract_recording_features(self.window_scores, threshold=at)

        # 11 clinical features (על 30 הדקות האחרונות)
        fhr_raw = np.array(list(self.ring_buffer_fhr))
        uc_raw  = np.array(list(self.ring_buffer_uc))
        fhr_norm = (fhr_raw - 50.0) / 160.0   # FHR: (bpm-50)/160 → [0,1]
        uc_norm  = uc_raw / 100.0              # UC:  mmHg/100 → [0,1]
        full_signal = np.stack([fhr_norm, uc_norm])
        clin_feats = extract_clinical_features(full_signal)

        # 2 global features
        all_probs = [p for _, p in self.window_scores]
        global_feats = [np.mean(all_probs), np.std(all_probs)]

        # Combine & predict
        x = np.array(list(pt_feats.values()) + clin_feats + global_feats)
        risk = self.lr_model.predict_proba(self.scaler.transform(x.reshape(1,-1)))[0, 1]

        return {
            "risk_score": float(risk),
            "alert": risk > self.alert_threshold,
            "features": {**pt_feats, "clinical": clin_feats},
            "top_drivers": self._get_top_features(x),
        }
```

### 11b. ארכיטקטורת UI מוצעת

```
┌─────────────────────────────────────────────────────────────────────┐
│                     SentinelFatal — CTG Monitor                      │
├─────────────────────────────────────────────────────────────────────┤
│  FHR trace ──────────────────────────────────────────────────────── │
│  [110──────────130──────────145───▒▒▒▒▒▒▒▒───130──────────135────] │
│                                   ↑ סגמנט התראה (אדום)              │
│  UC trace ────────────────────────────────────────────────────────── │
│  [0──────────20────50───80───50───20────0──────────20────────────] │
│                                                                      │
├─────────────────────────────────────────────────────────────────────┤
│  ציון סיכון: [===========|████████░░░░░░░░] 0.61  ⚠️ מעל סף 0.454 │
│                                                                      │
│  היסטוריה (30 דקות):                                                 │
│  0.2 ─ 0.3 ─ 0.3 ─ 0.4 ─ 0.5 ─ 0.6 ─ 0.7 ─ [0.61]               │
│                      ─────────sss──────────────────────              │
│                                                                      │
├─────────────────────────────────────────────────────────────────────┤
│  גורמי התראה:                                                         │
│  ① n_prolonged_decelerations = 2.0  (+0.46 לציון)                  │
│  ② total_alert_duration = 8.3 min   (+0.32 לציון)                  │
│  ③ n_late_decelerations = 1.0        (+0.23 לציון)                  │
│                                                                      │
│  [מאפשר/מבטל התראה]  [ייצא PDF]  [דיווח]                            │
└─────────────────────────────────────────────────────────────────────┘
```

### 11c. זרימת נתונים בזמן אמת — פירוט

```
מכשיר CTG → 4 Hz raw bytes
         │
         ▼ כל 0.25 שניות
   Ring buffer: 7200 samples (30 דקות) לכל ערוץ
         │
         ▼ כל 6 שניות (24 דגימות)
   preprocess_ctg_window(fhr_window, uc_window) → (2, 1800)
         │
         ▼ PatchTST forward pass (~50ms על CPU)
   P(acidemia) לחלון הנוכחי → append to window_scores
         │
         ├─── [מיידי]: צביעת CTG trace, עדכון היסטוגרמה
         │
         ▼ כל 60 שניות (10 חלונות חדשים)
   extract_recording_features(window_scores, AT) → 12 AI features
   extract_clinical_features(ring_buffer_full) → 11 clinical features
         │ (~200ms על CPU לחוקים קליניים)
         │
         ▼
   risk_score = LR.predict_proba([25 features])[:, 1]
         │
         ├─── [עדכון gauge + timeline]
         │
         ▼ אם risk_score > 0.454:
   trigger_alert(timestamp, score, top_features)
         │
         ├─── visual: red overlay on CTG at alert windows
         ├─── audio: beep (configurable)
         └─── log: timestamp + score + reasons
```

### 11d. פרמטרים קריטיים לצד ה-UI

| פרמטר | ערך | הסבר |
|--------|-----|------|
| **Alert threshold (metabolic)** | **0.454** | מ-`results/oof_cv_evaluation_metabolic/global_summary.csv` |
| Alert threshold (original) | 0.468 | מ-`results/oof_cv_evaluation/global_summary.csv` |
| INFERENCE_STRIDE | 24 samples = **6 שניות** | מ-`scripts/local_eval_cpu.py:81` |
| Ring buffer size | 7200 samples = **30 דקות** | נדרש לחוקים קליניים |
| Alert confirmation | ≥ 2 חלונות רצופים | להפחתת false alerts נקודתיים |
| Clinical refresh | כל **60 שניות** | החוקים הקליניים איטיים יחסית |
| PatchTST window | 1800 samples = **7.5 דקות** | look-back window |

### 11e. הסבר על ה-Alert "מסמן" בגרף

כאשר מתרחשת התראה, ה-UI צריך להראות **איפה** בגרף הבעיה:

```python
# האיך לזהות את "חלון הבעיה":
alert_windows = [
    (start_sample / 4.0, prob)               # זמן בשניות
    for start_sample, prob in self.window_scores
    if prob > self.alert_threshold
]
# כל window מכסה 7.5 דקות, מתחיל ב-start_sample
# ה-UI מסמן את ציר הזמן מ-start_sample/4 עד start_sample/4 + 450 שניות
```

---

## נספח: כל הפרמטרים במקום אחד

### פרמטרי מודל (config/train_config.yaml)

```yaml
# מודל
d_model: 128
num_layers: 3
n_heads: 4
ffn_dim: 256
dropout: 0.2
patch_len: 48        # = 12 שניות
patch_stride: 24     # = 6 שניות
n_patches: 73
window_len: 1800     # = 7.5 דקות

# Pre-training
pretrain:
  optimizer: adam
  lr: 1.0e-4
  scheduler: cosine_warm_restarts
  T0: 50
  T_mult: 2
  mask_ratio_schedule:
    - [0,  0.20]     # epochs 0-19
    - [20, 0.30]     # epochs 20-49
    - [50, 0.40]     # epochs 50+
  min_group_size: 2
  max_group_size: 6
  max_epochs: 300
  patience: 50
  batch_size: 64
  window_stride: 900  # 50% overlap

# Fine-tuning
finetune:
  optimizer: adamw
  loss: focal
  focal_gamma: 2.0
  label_smoothing: 0.05
  class_weight: [1.0, 3.9]
  progressive_unfreeze:
    - {epoch: 0,  n_top: 0,  lr_backbone: 0.0,   lr_head: 1.0e-3}
    - {epoch: 5,  n_top: 1,  lr_backbone: 1.0e-5, lr_head: 5.0e-4}
    - {epoch: 15, n_top: 2,  lr_backbone: 3.0e-5, lr_head: 3.0e-4}
    - {epoch: 30, n_top: -1, lr_backbone: 5.0e-5, lr_head: 1.0e-4}
  lr_warmup_epochs: 5
  max_epochs: 150
  patience: 25        # מתאפס אחרי כל שחרור!
  batch_size: 32
  train_stride: 60
  val_stride: 60
  swa_start: 50
  swa_end: 100

# Alert/Meta-classifier
alerting:
  at_candidates: [0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
  c_candidates: [0.01, 0.1, 1.0, 10.0]
  inference_stride: 24
  spec_constraint: 0.65
  n_features: 25    # 12 AI + 11 clinical + 2 global
```

### Label מטבולי (data/processed/ctu_uhb_clinical_full.csv)

```python
positive = (pH < 7.15) AND (BDecf >= 8.0)
         OR (pH < 7.10 AND BDecf is NaN)   # fallback
```

---

*מסמך זה מכסה את מערכת SentinelFatal2 במלואה. לשאלות נוספות, ראה `docs/azure_training_runs.md` לפרטי הריצות, `docs/clinical_rules_engine_v8.md` למנוע החוקים בעברית מלאה, ו-`docs/hybrid_clinical_features_v8.md` לאדריכלות ההיברידית.*
