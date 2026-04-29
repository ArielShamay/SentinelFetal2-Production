# Problems

No known unresolved problems at this time.

---

> **ISSUE-09 — גרפים לא חלקים (נפתר)**
>
> בוצע ב-5 רבדים (commits בסניף `refactor/uv-migration-pack-hardening`):
>
> - **רובד 1**: `default_replay_speed` הורד מ-10× ל-1×. `push_chart_tick` הועבר
>   מ-thread pool לevent loop — הגרף לא תלוי יותר בעומס ה-AI.
>   תור נפרד ל-ticks ב-`AsyncBroadcaster`.
> - **רובד 2**: פרוטוקול WebSocket הורחב: `ward_chart_ticks` (≤4 Hz, לכל הלקוחות)
>   + `chart_ticks` (קצב מלא, רק ללקוח עם focused bed). לקוחות שולחים
>   `{"type":"focus","bed_id":"..."}` בעת פתיחת DetailView.
> - **רובד 3**: כרטיסי ward עברו מ-`lightweight-charts` ל-`Sparkline.tsx` — canvas
>   גולמי עם RAF loop ו-dirty flag. 16 מיטות = 16 canvas פשוטים במקום 16 chart instances.
> - **רובד 4**: `useCTGChart` — `setData` ההיסטוריה נדחה לפריים הבא (shell מצטייר קודם).
>   live ticks מצטברים ב-buffer ומתרוקנים ב-RAF יחיד (max 1 repaint לפריים).
> - **רובד 5**: `chartUpdateBus` עבר ל-`RingBuffer` — push הוא O(1) ללא slice.
>   `initializeFromSnapshot` מזריע את ה-bus בנתוני ה-snapshot (24 דגימות לכל מיטה)
>   כדי ש-Sparklines ו-detail chart יתחילו עם הקשר מיידי אחרי רענון עמוד.
