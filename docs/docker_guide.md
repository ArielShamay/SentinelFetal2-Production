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
docker pull python:3.12-slim

# הצגת כל ה-images המקומיים
docker images

# מחיקת image
docker rmi python:3.12-slim

# בניית image מ-Dockerfile בתיקייה הנוכחית
docker build -t my-app:latest .

# בניית עם שם ספציפי
docker build -t my-app:v1.0 -f Dockerfile.prod .
```

### Containers
```bash
# הרצת קונטיינר (יוצא אחרי הרצה)
docker run python:3.12-slim python --version

# הרצה ברקע (detached)
docker run -d --name my-backend -p 8000:8000 my-app:latest

# הרצה אינטראקטיבית (נכנס ל-shell)
docker run -it python:3.12-slim bash

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
FROM python:3.12-slim

# הגדרת תיקיית עבודה בתוך הקונטיינר
WORKDIR /app

# התקנת uv והעתקת קבצי התלויות
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./

# הרצת פקודות בשלב הבנייה
RUN uv sync --frozen --no-dev

# העתקת שאר הקוד
COPY . .

# חשיפת פורט (תיעוד בלבד — לא מחייב)
EXPOSE 8000

# הפקודה שרצה כשהקונטיינר מתחיל
CMD ["uv", "run", "--frozen", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
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
FROM python:3.12-slim
```

### 2. סדר שכבות לפי תדירות שינוי
```dockerfile
# קבועים קודם (נכנסים ל-cache)
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

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
FROM python:3.12 AS builder
RUN pip install build
COPY . .
RUN python -m build

# שלב production: ~200MB (רק runtime)
FROM python:3.12-slim
COPY --from=builder /app/dist/*.whl .
RUN pip install *.whl
```

---

## 11. SentinelFetal2 — הארכיטקטורה שלנו ב-Docker

### מבט על

הפרויקט עבר למבנה של שני מסלולי Docker ברורים:

- `docker-compose.yml` הוא מסלול **פיתוח**: backend עם `uvicorn --reload`, frontend עם Vite על פורט `5173`, ו-bind mounts לקוד כדי לראות שינויים מיד.
- `docker-compose.prod.yml` הוא מסלול **prod-like**: backend self-contained, frontend דרך nginx על פורט `80`, וללא bind mounts של קוד, recordings או weights.

**מודל מנטלי קצר:**
- יש תמיד **2 services**: `backend` ו-`frontend`
- יש **3 image definitions**:
  - backend מ-`Dockerfile`
  - frontend dev מ-`frontend/Dockerfile.dev`
  - frontend prod מ-`frontend/Dockerfile.frontend`
- יש **2 מצבי הרצה**:
  - `dev` = backend image + frontend dev image
  - `prod-like` = backend image + frontend prod image

בנוסף, לכל mode יש Compose project name נפרד, כדי שמעבר בין `just dev` ל-`just prod` לא יעשה reuse ל-image הלא נכון.

### שכבת הפעלה קצרה עם `just`

במקום לזכור פקודות `docker compose` ארוכות, הריפו מספק:

- `setup` ברוט של הריפו
- `justfile` עם ה-recipes
- `.tools/just` בתור binary מקומי לריפו
- wrapper לוקאלי בשם `./just`, בלי שינוי `PATH`

זרימה מומלצת:

```bash
./setup just
./just dev
./just dev-build
./just dev-down
./just prod
./just prod-build
./just prod-down
```

המשמעות:
- `./just dev` = `docker compose up`
- `./just dev-build` = `docker compose up --build`
- `./just prod` = `docker compose -f docker-compose.prod.yml up -d`
- `./just prod-build` = `docker compose -f docker-compose.prod.yml up --build -d`

ה-wrapper תמיד מפעיל את ה-`just` המקומי של הריפו, בלי לגעת ב-`PATH` הגלובלי.

```
┌────────────── dev: docker-compose.yml ──────────────┐
│ backend: uvicorn --reload + bind mounts            │
│ frontend: Vite dev server (5173)                   │
│ קוד מקומי → משתקף מיד בתוך הקונטיינרים            │
└─────────────────────────────────────────────────────┘

┌────────── prod-like: docker-compose.prod.yml ───────┐
│ backend: image self-contained                       │
│ frontend: nginx serving dist/                       │
│ named volume רק ל-logs                              │
└─────────────────────────────────────────────────────┘
```

### Dockerfile (Backend)

```dockerfile
FROM python:3.12-slim AS backend
WORKDIR /app

ARG UV_VERSION=0.9.7
RUN pip install --no-cache-dir "uv==$UV_VERSION"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

RUN mkdir -p data/recordings logs

# רק משטח הריצה של ה-backend נכנס ל-image
COPY api ./api
COPY src ./src
COPY generator ./generator
COPY scripts ./scripts
COPY config ./config
COPY artifacts ./artifacts
COPY weights ./weights
COPY data/god_mode_catalog.json ./data/god_mode_catalog.json
COPY data/recordings ./data/recordings

RUN uv run --frozen python scripts/validate_artifacts.py

EXPOSE 8000
CMD ["uv", "run", "--frozen", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

**למה זה חשוב?**
- `uv` מותקן בגרסה נעולה (`0.9.7`), כדי שה-build לא ישתנה בעתיד רק בגלל שיצאה גרסה חדשה של הכלי.
- אנחנו כבר לא עושים `COPY . .`, ולכן frontend, docs וקבצי פיתוח לא נכנסים ל-backend image.
- יש ולידציה בבנייה, כך שחסר ב-`artifacts/` או `weights/` מפיל את ה-build מוקדם.

**למה `--workers 1`?**
- `PipelineManager` שומר state בזיכרון.
- יותר מ-worker אחד היה יוצר state נפרד לכל process.
- לכן backend runtime נשאר single-process בכוונה.

### frontend/Dockerfile.dev

```dockerfile
FROM node:20-slim
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
```

זה image לפיתוח בלבד:
- מריץ את Vite dev server
- עובד עם bind mount של `./frontend`
- מתאים ל-hot reload

### frontend/Dockerfile.frontend

```dockerfile
FROM node:20-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

זה image לפריסה:
- שלב build נפרד עם Node
- runtime קטן עם nginx בלבד
- הפרונט נבנה פעם אחת ומוגש כקבצים סטטיים

### docker-compose.yml שלנו (פיתוח)

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    command: ["uv", "run", "--frozen", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
    ports:
      - "8000:8000"
    volumes:
      - ./api:/app/api
      - ./src:/app/src
      - ./generator:/app/generator
      - ./scripts:/app/scripts
      - ./config:/app/config
      - ./artifacts:/app/artifacts
      - ./data:/app/data
      - ./weights:/app/weights
      - ./logs:/app/logs
    environment:
      - GOD_MODE_ENABLED=${GOD_MODE_ENABLED:-false}
      - LOG_LEVEL=${LOG_LEVEL:-info}
      - WATCHFILES_FORCE_POLLING=true
      - 'CORS_ORIGINS=["http://localhost:5173","http://localhost:3000","http://localhost:80"]'

  frontend:
    build:
      context: frontend
      dockerfile: Dockerfile.dev
    ports:
      - "5173:5173"
    environment:
      - CHOKIDAR_USEPOLLING=true
      - VITE_PROXY_TARGET=http://backend:8000
      - VITE_WS_PROXY_TARGET=ws://backend:8000
    volumes:
      - ./frontend:/app
      - frontend_node_modules:/app/node_modules
```

**למה זה נכון לפיתוח?**
- backend רואה שינויים בקוד דרך bind mounts
- frontend רץ ב-Vite ולכן יש reload מהיר
- ה-proxy של Vite מצביע ל-`backend:8000` בתוך הרשת של compose, לא ל-`localhost`

### docker-compose.prod.yml שלנו (prod-like)

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    restart: unless-stopped
    volumes:
      - backend_logs:/app/logs
    environment:
      - GOD_MODE_ENABLED=${GOD_MODE_ENABLED:-false}
      - LOG_LEVEL=${LOG_LEVEL:-info}
      - 'CORS_ORIGINS=["http://localhost","http://localhost:80"]'

  frontend:
    build:
      context: frontend
      dockerfile: Dockerfile.frontend
    ports:
      - "80:80"
    restart: unless-stopped
    depends_on:
      backend:
        condition: service_healthy

volumes:
  backend_logs:
```

**למה זה נכון להרצה יציבה יותר?**
- ה-backend image מכיל את כל runtime surface שהוא צריך.
- אין תלות בתיקיות מקומיות בשביל קוד, recordings או weights.
- רק `logs` נשמרים ב-named volume כדי לא לאבד אותם בין הפעלות.

### nginx.conf שלנו

```nginx
server {
    listen 80;

    location /api/ {
        proxy_pass http://backend:8000;
    }

    location /ws/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }
}
```

`backend` הוא hostname חוקי בתוך רשת ה-compose.

---

## 12. הרצת הפרויקט מאפס

אם אתה מחפש מדריך כניסה מלא לכל מסלולי ההפעלה של הפרויקט, כולל הרצה לוקאלית רגילה וגם Docker, ראה את [docs/getting_started.md](getting_started.md). הקטע כאן נשאר ממוקד במסלולי Docker בלבד.

### דרישות מוקדמות
- Docker Desktop מותקן
- Git מותקן

### שכבת `just` האופציונלית

אם אתה רוצה עטיפה קצרה יותר לפקודות Docker:

```bash
./setup just
```

זה יוריד את `just` לתוך `.tools/just` ויאפשר להשתמש ב-`./just ...` מתוך הריפו, בלי לגעת ב-`PATH` הגלובלי.

### מסלול פיתוח

```bash
git clone https://github.com/ArielShamay/SentinelFetal2-Production.git
cd SentinelFetal2-Production

docker compose up --build
```

או:

```bash
./setup just
./just dev-build
```

כתובות:
- `http://localhost:5173` → frontend דרך Vite
- `http://localhost:8000` → backend API

זה המסלול הנכון כשאתה עובד על הקוד ורוצה לראות שינויים בזמן אמת.

### מסלול prod-like

```bash
git clone https://github.com/ArielShamay/SentinelFetal2-Production.git
cd SentinelFetal2-Production

docker compose -f docker-compose.prod.yml up --build -d
```

או:

```bash
./setup just
./just prod-build
```

כתובות:
- `http://localhost` → frontend דרך nginx
- `http://localhost:8000` → backend API

זה המסלול הנכון כשאתה רוצה לבדוק image דומה יותר לפריסה אמיתית.

### עצירה

```bash
docker compose down
docker compose -f docker-compose.prod.yml down
```

או:

```bash
./just dev-down
./just prod-down
```

### עדכון קוד

במסלול הפיתוח:

```bash
docker compose up --build backend
docker compose up --build frontend
```

במסלול prod-like:

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

---

## 13. פתרון בעיות נפוצות

### backend לא עולה

```bash
docker compose logs backend
docker compose -f docker-compose.prod.yml logs backend
```

סיבות נפוצות:
- `artifacts/` חסר → `validate_artifacts.py` מפיל את ה-build
- `weights/` חסר → טעינת המודלים נכשלת
- פורט `8000` תפוס → שנה את מיפוי הפורטים ב-compose

### frontend לא מתחבר ל-backend

במסלול הפיתוח:
- ודא ש-`VITE_PROXY_TARGET=http://backend:8000`
- ודא שה-frontend וה-backend יושבים באותו compose network

במסלול prod-like:
- ודא שב-`nginx.conf` ה-proxy מכוון ל-`http://backend:8000`

### שינויים בקוד לא נראים

אם אתה רוצה hot reload, השתמש רק במסלול הפיתוח:

```bash
docker compose up --build
```

אם אתה במסלול prod-like, כל שינוי קוד דורש rebuild:

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

### image גדול מדי

```bash
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
```

בדוק:
- האם `.dockerignore` מוציא קבצים לא רלוונטיים
- האם backend Dockerfile עדיין מעתיק רק את runtime surface
- האם weights ו-recordings באמת צריכים להיות בתוך ה-image שאתה בונה

### בדיקת healthcheck

```bash
docker inspect sentinelfetal2-production-backend-1 | grep -A 10 Health
```

השם המדויק יכול להשתנות לפי שם הפרויקט/הספרייה.

### כניסה לקונטיינר לדיבאג

```bash
docker compose exec backend bash
# או במסלול prod-like:
docker compose -f docker-compose.prod.yml exec backend bash
```

פקודות שימושיות:

```bash
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
