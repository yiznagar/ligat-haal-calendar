# יומן ליגת העל (WINNER) 2026/27 — אוטומטי וחינמי

יומן `.ics` שמתעדכן לבד כל שעה עם כל משחקי ליגת העל בכדורגל בישראל
(קבוצות, תאריך, שעה, אצטדיון), ישירות מהאתר הרשמי של ההתאחדות לכדורגל —
`football.org.il`. מתארח בחינם על GitHub Actions + GitHub Pages.
אפשר להירשם אליו ב-Outlook / Google Calendar / Apple Calendar בכתובת אחת.

---

## איך זה עובד (מאומת מול נתוני 2026/27 האמיתיים — לא ניחוש)

עמוד הליגה `https://www.football.org.il/leagues/league/?league_id=40` הוא server-rendered
ומכיל:

* `<select id="season_choose">` — ממפה תווית עונה (`2026/27`) ל-`season_id` מספרי
  (כרגע `28`). ה-scraper קורא את זה דינמית, לא מקבע מספר.
* אלמנט/י placeholder לרשימת המשחקים:
  `<section class="… league-game-table" data-table-index="10" data-table-type="games" …>`.
  `data-table-index` הוא ה-`box` (שלב) שבו משתמש שירות הנתונים:
  * `box=10` — עונה סדירה (מחזורים 1–26)
  * `box=30` — פלייאוף תחתון (27–33) — מופיע באמצע העונה
  * `box=40` — פלייאוף עליון (27–36) — מופיע באמצע העונה

  ה-scraper קורא את ה-box-ים שהאתר חושף באותו רגע, כך שמשחקי הפלייאוף נכנסים
  אוטומטית ברגע שההתאחדות יוצרת אותם.

* המשחקים עצמם נמשכים מאותו web-service ש-JS של האתר קורא לו:

  ```
  https://www.football.org.il/Components.asmx/LeagueGamesList
      ?league_id=40&season_id=28&box=10&round_id=<מחזור>&componentTitle=cal
  ```

  התשובה היא XML עם קטע HTML מקודד בתוך `<HtmlData>`, ובו שורת `<a class="table_row">`
  לכל משחק: תאריך (`DD/MM/YYYY`), שני שמות קבוצות, אצטדיון, שעה (`HH:MM`),
  ו-`href="/leagues/games/game/?game_id=NNNNN"`.

* **`game_id`** הוא המזהה הקבוע של ההתאחדות למשחק. ה-UID ביומן נבנה ממנו:
  `ligat-haal-28-game-1120561@yiznagar.github.io`. לכן שינוי תאריך / שעה / אצטדיון
  **מעדכן** את האירוע הקיים ולא יוצר כפילות.

זמנים: השעה המקומית מהאתר מומרת ל-UTC דרך אזור הזמן `Asia/Jerusalem`
(מטפל ב-DST של ישראל), כך שהקובץ נושא חותמות `…Z` חד-משמעיות.

---

## מבנה הריפו

```
ligat-haal-calendar/
├── scraper.py                       # מושך את המשחקים מ-football.org.il -> data/games.json
├── ics_generator.py                 # data/games.json -> docs/league.ics (UID קבוע, פלט דטרמיניסטי)
├── requirements.txt                 # tzdata (בשביל Asia/Jerusalem)
├── .gitignore
├── .github/
│   └── workflows/
│       └── update-calendar.yml      # רץ כל שעה, מייצר מחדש, ו-commit רק אם משהו השתנה
└── docs/                            # ← GitHub Pages מגיש מכאן
    ├── index.html                   # עמוד נחיתה עם כתובת ההרשמה
    └── league.ics                   # ← הקובץ שנרשמים אליו
```

---

## הקמה — שלב אחר שלב

### 1. ליצור את ה-Repository

1. היכנס ל-<https://github.com/new> (מחובר כ-`yiznagar`).
2. **Repository name:** `ligat-haal-calendar`
3. **Public** (חובה — GitHub Pages חינמי דורש ריפו ציבורי).
4. אל תסמן שום דבר (בלי README / .gitignore / license) — נדחוף הכל ידנית.
5. **Create repository**.

### 2. להעלות את הקבצים

הכי פשוט — דרך הדפדפן, **Add file → Upload files**, וגרור את כל תוכן התיקייה
`ligat-haal-calendar/` (כולל `.github/`). שמור על אותו מבנה תיקיות בדיוק:

| הקובץ במחשב שלך | היעד בריפו (זהה) |
|---|---|
| `scraper.py` | `scraper.py` (שורש הריפו) |
| `ics_generator.py` | `ics_generator.py` (שורש הריפו) |
| `requirements.txt` | `requirements.txt` (שורש הריפו) |
| `.gitignore` | `.gitignore` (שורש הריפו) |
| `.github/workflows/update-calendar.yml` | `.github/workflows/update-calendar.yml` |
| `docs/index.html` | `docs/index.html` |
| `docs/league.ics` | `docs/league.ics` |

> אם מעדיפים שורת פקודה:
> ```bash
> git clone https://github.com/yiznagar/ligat-haal-calendar.git
> cd ligat-haal-calendar
> # להעתיק לכאן את כל הקבצים מהתיקייה שקיבלת
> git add .
> git commit -m "Initial: Ligat ha'Al 2026/27 auto calendar"
> git push
> ```

### 3. להפעיל GitHub Actions

1. בריפו → לשונית **Actions**.
2. אם מופיעה הודעה "Workflows aren't being run on this repository" → **I understand my workflows, enable them**.
3. פתח את **Update Ligat ha'Al calendar** → **Run workflow** → **Run workflow**
   (הרצה ידנית ראשונה כדי לוודא שהכל עובד; אחר כך זה רץ לבד כל שעה).
4. אחרי ~דקה, ה-run צריך להסתיים ירוק, ו-`docs/league.ics` יתעדכן/יידחף.

> אם ה-push מה-Action נכשל עם שגיאת הרשאה: **Settings → Actions → General →
> Workflow permissions → Read and write permissions → Save**, ואז הרץ שוב.

### 4. להפעיל GitHub Pages

1. בריפו → **Settings → Pages**.
2. **Source:** *Deploy from a branch*.
3. **Branch:** `main` , **Folder:** `/docs` → **Save**.
4. תוך דקה-שתיים העמוד יעלה בכתובת
   `https://yiznagar.github.io/ligat-haal-calendar/`.

### 5. הכתובת המדויקת ל-Outlook

```
https://yiznagar.github.io/ligat-haal-calendar/league.ics
```

**Outlook בדפדפן (Subscribe from web):**

1. <https://outlook.office.com/calendar/> (או `outlook.live.com`).
2. בצד: **Add calendar → Subscribe from web**.
3. הדבק את הכתובת שלמעלה, תן שם ("ליגת העל 2026/27"), **Import / Subscribe**.
4. Outlook מרענן את היומן מעצמו כל כמה שעות.

(Google Calendar: *Other calendars → From URL*. Apple Calendar: *File → New
Calendar Subscription*. אותה כתובת בדיוק.)

---

## עדכונים אוטומטיים

* ה-workflow רץ **כל שעה** (`cron: "17 * * * *"`), וגם בכל push ל-`scraper.py` /
  `ics_generator.py`, וגם ידנית מ-**Actions → Run workflow**.
* כל הרצה מושכת מחדש את כל המחזורים ומייצרת מחדש את `league.ics`.
* הפלט דטרמיניסטי: אם שום משחק לא השתנה — הקובץ זהה בית-לבית ואין commit.
* אם משחק חדש נוסף / תאריך / שעה / אצטדיון השתנו — רק האירועים הרלוונטיים
  מקבלים `DTSTAMP` חדש ו-`SEQUENCE+1`, ה-UID נשאר, וה-Action עושה commit אחד
  עם התיאור `chore: refresh league.ics (...)`.
* GitHub Pages מגיש אוטומטית את הגרסה החדשה של `docs/league.ics`.

GitHub עלול לעכב הרצות cron בכמה דקות בשעות עומס — זה בסדר ליומן שעתי.
בריפו ללא פעילות במשך ~60 יום, GitHub משהה הרצות מתוזמנות; כל push או הרצה
ידנית מפעיל אותן מחדש.

---

## הרצה מקומית (בדיקה)

```bash
pip install -r requirements.txt
python scraper.py --season "2026/27" --out data/games.json
python ics_generator.py --in data/games.json --out docs/league.ics
```

* `--season current` — לעקוב אחרי מה שהאתר מגדיר כעונה נוכחית במקום לקבע `2026/27`.
* ה-scraper נכשל בכוונה (exit 1) אם לא נמצא אף משחק, כדי לא לדרוס פלט תקין.

---

## מגבלות ידועות

* **מחזורים עתידיים:** ההתאחדות מפרסמת רק כמה מחזורים קדימה. כרגע קיימים
  מחזורים 1–3. השאר ייכנסו אוטומטית בהרצות הבאות ברגע שיפורסמו.
* **פלייאוף:** ה-box-ים 30/40 מזוהים אוטומטית כשההתאחדות תיצור אותם באתר
  (בערך אחרי מחזור 26). אין צורך בשינוי קוד.
* **משחק בלי שעה עדיין:** נוצר כאירוע של יום שלם עם הערה "השעה טרם פורסמה".
* **משחק בלי תאריך:** מדולג (אין מה לתזמן) ונרשם ל-log של ה-Action.
* אם ההתאחדות תשנה מהיסוד את מבנה `Components.asmx` / מחלקות ה-HTML,
  ה-scraper ייכשל בבירור (exit 1, ה-Action אדום) במקום להוציא יומן שגוי.
