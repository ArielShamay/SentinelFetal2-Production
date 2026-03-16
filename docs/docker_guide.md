# מדריך Docker מלא — SentinelFetal2

> מדריך זה מכסה שני נושאים במקביל:
> 1. **Docker מאפס עד מקצוען** — תיאוריה, פקודות, שיטות עבודה
> 2. **אצלנו בפרויקט** — בדיוק מה בנינו ואיך זה עובד

---

## תוכן עניינים

1. [מה זה Docker ולמה צריך אותו](#1-מה-זה-docker-ולמה-צריך-אותו)
2. [מושגי יסוד](#2-מושגי-יסוד)
3. [התקנה](#3-התקנה)
4. [פקודות בסיסיות](#4-פקודות-בסיסיות)
5. [Dockerfile — איך בונים image](#5-dockerfile--איך-בונים-image)
6. [docker-compose — ריצת כמה שירותים יחד](#6-docker-compose--ריצת-כמה-שירותים-יחד)
7. [Volumes — נתונים שנשמרים](#7-volumes--נתונים-שנשמרים)
8. [Networks — תקשורת בין קונטיינרים](#8-networks--תקשורת-בין-קונטיינרים)
9. [יתרונות ומגבלות](#9-יתרונות-ומגבלות)
10. [שיטות עבודה מקצועיות](#10-שיטות-עבודה-מקצועיות)
11. [SentinelFetal2 — הארכיטקטורה שלנו ב-Docker](#11-sentinelfetal2--הארכיטקטורה-שלנו-ב-docker)
12. [הרצת הפרויקט מאפס](#12-הרצת-הפרויקט-מאפס)
13. [פתרון בעיות נפוצות](#13-פתרון-בעיות-נפוצות)

---

## 1. מה זה Docker ולמה צריך אותו

### הבעיה שהוא פותר

לפני Docker, הבעיה הקלאסית הייתה:

> *"אצלי זה עובד, אצלך לא"*

סיבות אפשריות: גרסת Python שונה, ספריות שונות, משתני סביבה חסרים, הגדרות OS שונות.

### הפתרון

Docker עוטף את האפליקציה ו**כל מה שהיא צריכה** בתוך יחידה אחת נייחה — **קונטיינר**. הקונטיינר רץ אותו דבר בדיוק בכל מחשב, כל שרת, כל ענן.

```
בלי Docker:                    עם Docker:
─────────────                  ─────────────
מחשב מפתח A ──┐               ┌──────────────────────────┐
  Python 3.11  │  עשוי        │  קונטיינר                │
  sklearn 1.6  │  לא          │  Python 3.11              │
               │  לעבוד       │  sklearn 1.6              │
מחשב מפתח B ──┤  בשרת        │  כל הספריות              │  ← רץ אותו דבר
  Python 3.12  │              │  בכל מקום               │     בכל מקום
  sklearn 1.8  │              └──────────────────────────┘
               │
שרת ייצור ─────┘
  Python 3.9
  sklearn 1.4
```

---

## 2. מושגי יסוד

### Image (תמונה)
תבנית לקריאה בלבד. כמו ISO של תוכנה — קובץ קפוא שמגדיר מה יהיה בקונטיינר.
- נבנית מ-`Dockerfile`
- מאוחסנת ב-registry (Docker Hub, GitHub Container Registry וכו')
- ניתנת לשיתוף

### Container (קונטיינר)
מופע רץ של image. כמו תהליך — קל משקל, מבודד, ניתן לעצור ולמחוק.
- ניתן להריץ אלפי קונטיינרים מאותו image
- כל קונטיינר מבודד — שינויים בתוכו לא משפיעים על ה-image

```
Image    ──[docker run]──▶  Container 1 (רץ)
                       ──▶  Container 2 (רץ)
                       ──▶  Container 3 (עצור)
```

### Dockerfile
קובץ הוראות לבניית image. כמו מתכון בישול — שורה אחר שורה.

### docker-compose
כלי להרצת **כמה קונטיינרים ביחד** עם קונפיגורציה אחת (YAML). מתאים לאפליקציות שמורכבות מכמה שירותים (backend + frontend + database).

### Registry
מחסן ל-images. Docker Hub הוא הציבורי הפופולרי ביותר. גם GitHub, AWS ECR, Google GCR.

### Volume
מנגנון לשמירת נתונים **מחוץ** לקונטיינר. בלי volume — כשקונטיינר נמחק, הנתונים נמחקים איתו.

### Port Mapping
קישור בין פורט של המחשב המארח לפורט של הקונטיינר.
`-p 8000:8000` ← `[מחשב]:[קונטיינר]`

---

## 3. התקנה

### Windows
1. הורד [Docker Desktop](https://www.docker.com/products/docker-desktop/)
2. הפעל — מריץ daemon ברקע
3. ודא שـ WSL2 מופעל (Docker Desktop יציג הוראות אם לא)
4. פתח Terminal ובדוק: `docker --version`

### Mac
1. הורד Docker Desktop למק
2. גרור ל-Applications
3. הפעל ובדוק: `docker --version`

### Linux (Ubuntu/Debian)
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # הוסף את עצמך לקבוצה
newgrp docker                    # החל את השינוי
docker --version
```

### בדיקת התקנה
```bash
docker run hello-world
# אמור להדפיס: "Hello from Docker!"
```

---

## 4. פקודות בסיסיות

### Images
```bash
# הורדת image מ-Docker Hub
docker pull python:3.11-slim

# הצגת כל ה-images המקומיים
docker images

# מחיקת image
docker rmi python:3.11-slim

# בניית image מ-Dockerfile בתיקייה הנוכחית
docker build -t my-app:latest .

# בניית עם שם ספציפי
docker build -t my-app:v1.0 -f Dockerfile.prod .
```

### Containers
```bash
# הרצת קונטיינר (יוצא אחרי הרצה)
docker run python:3.11-slim python --version

# הרצה ברקע (detached)
docker run -d --name my-backend -p 8000:8000 my-app:latest

# הרצה אינטראקטיבית (נכנס ל-shell)
docker run -it python:3.11-slim bash

# הצגת קונטיינרים רצים
docker ps

# הצגת כל הקונטיינרים (כולל עצורים)
docker ps -a

# עצירת קונטיינר
docker stop my-backend

# הפעלה מחדש
docker start my-backend

# מחיקת קונטיינר
docker rm my-backend

# הדפסת לוגים
docker logs my-backend

# לוגים בזמן אמת
docker logs -f my-backend

# כניסה לקונטיינר רץ
docker exec -it my-backend bash
```

### ניקוי
```bash
# מחיקת קונטיינרים עצורים
docker container prune

# מחיקת images שאינם בשימוש
docker image prune

# ניקוי מלא (קונטיינרים, images, networks, cache)
docker system prune -a
```

---

## 5. Dockerfile — איך בונים image

### מבנה בסיסי
```dockerfile
# שכבת בסיס — מה ה-OS/runtime
FROM python:3.11-slim

# הגדרת תיקיית עבודה בתוך הקונטיינר
WORKDIR /app

# העתקת קבצים מהמחשב לקונטיינר
COPY requirements.txt .

# הרצת פקודות בשלב הבנייה
RUN pip install --no-cache-dir -r requirements.txt

# העתקת שאר הקוד
COPY . .

# חשיפת פורט (תיעוד בלבד — לא מחייב)
EXPOSE 8000

# הפקודה שרצה כשהקונטיינר מתחיל
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Multi-Stage Build — בנייה בשלבים
טכניקה חשובה: כל שלב בנוי בנפרד, רק תוצרים חשובים עוברים לשלב הבא. התוצאה: image **הרבה יותר קטן**.

```dockerfile
# שלב 1: בנייה (כולל כלי build, node_modules וכו')
FROM node:20-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci                  # מתקין כל הספריות
COPY . .
RUN npm run build           # מייצר dist/

# שלב 2: ייצור (רק nginx + קבצים סטטיים)
FROM nginx:alpine           # image קטן מאוד (~5MB)
COPY --from=build /app/dist /usr/share/nginx/html
# node_modules לא עוברים! image הסופי קטן

EXPOSE 80
```

### הוראות חשובות ב-Dockerfile

| הוראה | שימוש |
|-------|-------|
| `FROM` | image בסיס |
| `WORKDIR` | תיקיית עבודה |
| `COPY` | העתקת קבצים |
| `ADD` | כמו COPY + תמיכה ב-URLs וארכיבים |
| `RUN` | הרצת פקודות בשלב בנייה |
| `CMD` | פקודה ברירת מחדל בהרצה |
| `ENTRYPOINT` | נקודת כניסה קבועה |
| `ENV` | משתני סביבה |
| `ARG` | משתני build-time |
| `EXPOSE` | תיעוד פורטים |
| `VOLUME` | הגדרת volume points |
| `USER` | משתמש להרצה (אבטחה) |

### .dockerignore
כמו `.gitignore` — מונע העתקת קבצים מיותרים לimage:
```
.git
.venv
node_modules
__pycache__
*.pyc
logs/
.env
*.key
```

---

## 6. docker-compose — ריצת כמה שירותים יחד

### מבנה בסיסי של docker-compose.yml
```yaml
services:
  backend:
    build: .                        # בנה מ-Dockerfile בתיקייה זו
    ports:
      - "8000:8000"                 # [מחשב]:[קונטיינר]
    environment:
      - DATABASE_URL=postgres://... # משתני סביבה
    volumes:
      - ./data:/app/data            # [מחשב]:[קונטיינר]
    depends_on:
      - database                    # מחכה ל-database לקום

  frontend:
    build:
      context: frontend
      dockerfile: Dockerfile.frontend
    ports:
      - "80:80"
    depends_on:
      - backend

  database:
    image: postgres:15-alpine       # image מוכן מ-Docker Hub
    environment:
      - POSTGRES_PASSWORD=secret
    volumes:
      - db_data:/var/lib/postgresql/data  # volume ששמו db_data

volumes:
  db_data:                          # הגדרת named volume
```

### פקודות docker-compose
```bash
# הפעלת כל השירותים (בונה images אם צריך)
docker-compose up

# הפעלה ברקע
docker-compose up -d

# הפעלה עם בנייה מחדש
docker-compose up --build

# עצירה
docker-compose down

# עצירה + מחיקת volumes
docker-compose down -v

# לוגים
docker-compose logs
docker-compose logs -f backend     # רק backend, בזמן אמת

# כניסה לשירות ספציפי
docker-compose exec backend bash

# הרצת פקודה חד-פעמית
docker-compose run backend python scripts/validate_artifacts.py

# סטטוס
docker-compose ps
```

---

## 7. Volumes — נתונים שנשמרים

### הבעיה
קונטיינר הוא **זמני** — כשנמחק, כל הנתונים שבתוכו נמחקים.
למסד נתונים, לוגים, קבצים שהמשתמש מעלה — זה בעיה.

### סוגי Volumes

**Named Volume** — Docker מנהל את המיקום:
```yaml
volumes:
  - db_data:/var/lib/postgresql/data
```
```bash
# Docker שומר ב: /var/lib/docker/volumes/db_data/
docker volume ls
docker volume inspect db_data
```

**Bind Mount** — אתה בוחר את המיקום:
```yaml
volumes:
  - ./data:/app/data        # תיקייה מהמחשב
  - ./logs:/app/logs
```
שימושי לפיתוח — שינויים בקוד נראים מיד בקונטיינר.

**tmpfs** — זיכרון בלבד, לא נשמר:
```yaml
volumes:
  - type: tmpfs
    target: /tmp
```

---

## 8. Networks — תקשורת בין קונטיינרים

ברירת מחדל: קונטיינרים ב-compose אותו שירות יכולים לתקשר לפי **שם השירות**:

```python
# ב-backend Python — מתחבר ל-database בשם "database"
conn = psycopg2.connect("host=database port=5432 ...")
```

```yaml
# ב-docker-compose.yml
services:
  backend:
    networks:
      - app_network
  database:
    networks:
      - app_network

networks:
  app_network:
    driver: bridge
```

---

## 9. יתרונות ומגבלות

### יתרונות

| יתרון | הסבר |
|-------|-------|
| **Reproducibility** | אותו image = אותה התנהגות בכל מקום |
| **Isolation** | כל שירות בסביבה נפרדת, ללא התנגשויות |
| **Portability** | רץ ב-Windows, Mac, Linux, AWS, GCP, Azure |
| **Scaling** | קל לגדול: `docker-compose up --scale backend=3` |
| **Rollback** | חזרה לגרסה ישנה: `docker run my-app:v1.2` |
| **CI/CD** | GitHub Actions בונה ודוחף image אוטומטית |
| **Dev/Prod parity** | סביבת פיתוח זהה לייצור |
| **Dependency management** | לא צריך להתקין Python/Node/כלום על השרת |

### מגבלות

| מגבלה | הסבר | פתרון |
|-------|-------|-------|
| **גודל** | Images יכולים להיות גדולים (GB) | Multi-stage build, Alpine images |
| **עלות אחסון** | images גדולים = עלות registry | `docker image prune` תקופתי |
| **GPU** | צריך הגדרה מיוחדת | `nvidia-docker`, `--gpus all` |
| **State** | קונטיינרים stateless — נתונים אובדים | Volumes תמיד לנתונים קבועים |
| **Debug** | קצת קשה יותר מ-localhost | `docker exec -it bash` |
| **Windows quirks** | line endings, paths | `.dockerignore`, ENTRYPOINT scripts |
| **Learning curve** | קונספטים חדשים | מדריך זה :) |
| **overhead** | קצת יותר זיכרון/CPU מ-bare metal | זניח ב-99% מהמקרים |

---

## 10. שיטות עבודה מקצועיות

### 1. השתמש ב-specific tags, לא ב-latest
```dockerfile
# לא מומלץ
FROM python:latest

# מומלץ — גרסה קבועה, reproducible
FROM python:3.11-slim
```

### 2. סדר שכבות לפי תדירות שינוי
```dockerfile
# קבועים קודם (נכנסים ל-cache)
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# משתנים אחרונים (קוד משתנה הכי הרבה)
COPY . .
```
כך שינוי בקוד לא יגרום להתקנה מחדש של כל הספריות.

### 3. אל תריץ כ-root
```dockerfile
RUN adduser --disabled-password appuser
USER appuser
CMD ["uvicorn", "api.main:app"]
```

### 4. השתמש ב-.dockerignore
מניעת העתקת `.git`, `__pycache__`, `node_modules`, `.env` לimage.

### 5. Health checks
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
```

### 6. משתני סביבה לסודות
```yaml
# docker-compose.yml
services:
  backend:
    environment:
      - DB_PASSWORD=${DB_PASSWORD}   # מ-.env מקומי
```
```bash
# .env (לא ב-git!)
DB_PASSWORD=my_secret_password
```

### 7. Multi-stage build תמיד לפרויקטים גדולים
```dockerfile
# שלב build: ~1GB (כולל compilers, dev dependencies)
FROM python:3.11 AS builder
RUN pip install build
COPY . .
RUN python -m build

# שלב production: ~200MB (רק runtime)
FROM python:3.11-slim
COPY --from=builder /app/dist/*.whl .
RUN pip install *.whl
```

---

## 11. SentinelFetal2 — הארכיטקטורה שלנו ב-Docker

### מבט על

```
┌─────────────────── docker-compose.yml ───────────────────┐
│                                                           │
│  ┌────────────────────┐    ┌──────────────────────────┐  │
│  │  backend           │    │  frontend                │  │
│  │  python:3.12-slim  │    │  node:20 → nginx:alpine  │  │
│  │  port 8000         │◄───│  port 80                 │  │
│  │                    │    │  (proxy → backend)       │  │
│  │  uv + FastAPI      │    └──────────────────────────┘  │
│  │  PatchTST (torch)  │                                  │
│  │  WebSocket stream  │                                  │
│  └────────────────────┘                                  │
│          │  volumes                                       │
│    ┌─────┴──────────────────────────┐                    │
│    │  ./data    → /app/data         │                    │
│    │  ./weights → /app/weights      │                    │
│    │  ./logs    → /app/logs         │                    │
│    └────────────────────────────────┘                    │
└───────────────────────────────────────────────────────────┘
```

### Dockerfile (Backend)

```dockerfile
FROM python:3.12-slim AS backend
WORKDIR /app

# שכבה 1: ספריות (משתנות לעיתים רחוקות)
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# שכבה 2: קוד (משתנה לעיתים קרובות)
COPY . .

# ולידציה בשלב הבנייה — נכשל מוקדם אם artifacts חסרים
RUN uv run --frozen python scripts/validate_artifacts.py

EXPOSE 8000
CMD ["uv", "run", "--frozen", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

**למה `python:3.12-slim` ולא `python:3.12`?**
- `slim` = גרסה מינימלית ללא כלי build מיותרים
- גודל: ~50MB במקום ~900MB
- תלויות נסנכרנות דטרמיניסטית דרך `uv.lock`

**למה `--workers 1`?**
- PipelineManager שומר state בזיכרון (ring buffers, קונטיינרי מיטות)
- עם workers > 1 כל process היה ממופה לזיכרון נפרד — מיטות לא היו מסונכרנות
- פתרון: worker יחיד + async event loop

### frontend/Dockerfile.frontend (Multi-Stage)

```dockerfile
# שלב 1: Build — node:20 עם כל הספריות
FROM node:20-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci                   # התקנה מדויקת מ-package-lock.json
COPY . .
RUN npm run build            # Vite מייצר dist/

# שלב 2: Production — nginx קטן
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

**תוצאה:**
- שלב build: ~800MB (node + כל הספריות)
- image סופי: ~25MB (nginx + קבצים סטטיים בלבד)

### docker-compose.yml שלנו

```yaml
services:
  backend:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data        # הקלטות ה-.npy ו-alert_log
      - ./weights:/app/weights  # משקולות PatchTST
      - ./logs:/app/logs        # לוגים נשמרים על המחשב
    environment:
      - GOD_MODE_PIN=${GOD_MODE_PIN:-change_me}
      - GOD_MODE_ENABLED=${GOD_MODE_ENABLED:-false}
      - LOG_LEVEL=${LOG_LEVEL:-info}
      - 'CORS_ORIGINS=["http://localhost","http://localhost:80"]'
    healthcheck:
      test: ["CMD", "uv", "run", "--frozen", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s         # מאפשר לPatchTST להיטען (~5s)

  frontend:
    build:
      context: frontend
      dockerfile: Dockerfile.frontend
    ports:
      - "80:80"
    depends_on:
      backend:
        condition: service_healthy  # מחכה ל-backend להיות healthy
```

**למה volumes ל-data ו-weights?**
הם גדולים (~86MB) ומשתנים לעיתים רחוקות. שמירתם כ-bind mounts על המחשב:
- מאפשר עדכון הקלטות/משקולות ללא rebuild
- שומר על alert_log.jsonl בין הפעלות

### nginx.conf שלנו

```nginx
server {
    listen 80;

    # כל קריאה ל-/api/ → backend
    location /api/ {
        proxy_pass http://backend:8000;
    }

    # WebSocket stream
    location /ws/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # כל שאר → React app
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }
}
```

`http://backend:8000` עובד כי ב-docker network, שם השירות (`backend`) הוא ה-hostname.

---

## 12. הרצת הפרויקט מאפס

### דרישות מוקדמות
- Docker Desktop מותקן
- Git מותקן

### צעדים

```bash
# 1. שכפול הפרויקט
git clone https://github.com/ArielShamay/SentinelFetal2-Production.git
cd SentinelFetal2-Production

# 2. הגדרת משתני סביבה (אופציונלי)
cp .env.example .env
# ערוך .env אם רוצה לשנות GOD_MODE_PIN וכו'

# 3. בנייה והפעלה
docker-compose up --build

# 4. המתן לhealthcheck לעבור (~60 שניות — טעינת מודלים)
# תראה: backend | SentinelFetal2 startup complete. beds=4

# 5. פתח בדפדפן
# http://localhost       ← frontend (דרך nginx)
# http://localhost:8000  ← backend API ישירות
```

### הפעלה בפעמים הבאות (ללא rebuild)
```bash
docker-compose up
```

### עצירה
```bash
# עצירה שומרת נתונים (volumes)
docker-compose down

# עצירה ומחיקת הכל כולל logs ו-data
docker-compose down -v
```

### שינוי מספר מיטות
```bash
# ב-docker-compose.yml תחת backend environment:
DEFAULT_BED_COUNT=8

# או בזמן ריצה:
curl -X POST http://localhost:8000/api/simulation/start \
  -H "Content-Type: application/json" \
  -d '{"beds": [{"bed_id":"bed1"},{"bed_id":"bed2"},...]}'
```

### עדכון קוד ללא rebuild מלא
```bash
# רק backend השתנה
docker-compose up --build backend

# רק frontend השתנה
docker-compose up --build frontend
```

---

## 13. פתרון בעיות נפוצות

### backend לא עולה
```bash
docker-compose logs backend
```
סיבות נפוצות:
- `artifacts/` חסר → validate_artifacts.py נכשל בשלב build
- `weights/` חסר → load_production_models נכשל
- פורט 8000 תפוס → שנה ל-`"8001:8000"` ב-compose

### frontend לא מתחבר ל-backend
```bash
docker-compose logs frontend
```
ודא שב-nginx.conf:
```nginx
proxy_pass http://backend:8000;  # ← שם השירות ב-compose, לא localhost
```

### שינויים בקוד לא נראים
Build חדש דרוש:
```bash
docker-compose up --build
```
או אם רוצה שינויים בזמן אמת בפיתוח — השתמש ב-bind mount:
```yaml
volumes:
  - ./api:/app/api        # קוד backend ישר מהמחשב
```

### image גדול מדי
```bash
docker images | sort -k7 -h
# בדוק מה גדול, השתמש ב-multi-stage ו-.dockerignore
```

### בדיקת healthcheck
```bash
docker inspect sentinelfetal2-backend | grep -A 10 Health
```

### כניסה לקונטיינר לדיבאג
```bash
docker-compose exec backend bash
# עכשיו אתה בתוך הקונטיינר
python -c "import torch; print(torch.__version__)"
ls data/recordings/ | wc -l
```

---

## נספח: קיצורי דרך שימושיים

```bash
# עצור את כל הקונטיינרים הרצים
docker stop $(docker ps -q)

# מחק את כל הקונטיינרים
docker rm $(docker ps -aq)

# הצגת גודל images
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

# בדיקת משאבים בזמן אמת
docker stats

# העתקת קובץ מקונטיינר למחשב
docker cp backend:/app/logs/sentinel.log ./local_log.txt

# העתקת קובץ מהמחשב לקונטיינר
docker cp ./new_model.pkl backend:/app/artifacts/production_lr.pkl
```

---

*נכתב עבור SentinelFetal2-Production | עודכן: 2026-03*
