# Архитектура проекта

Проект разделён на доменную логику, хранение и интерфейс.

```text
app/domain/parser.py        импорт текстового файла
app/domain/tournament.py    турнирная механика
app/domain/ranking.py       построение итогового рейтинга
app/domain/scoring_light.py лайтовое оценивание
app/domain/scoring_hard.py  хардовое оценивание
app/domain/export.py        экспорт результатов
app/storage/                autosave и JSON-сохранение
app/ui/                     PySide6-интерфейс
```

GUI не принимает решений о победителях, рейтинге и новых оценках. Он только отображает данные и передаёт действия пользователя в `TournamentEngine`.
