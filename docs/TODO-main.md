# Перенести в main

Исправления, сделанные в ветке `redesign`, которые нужны в `main` независимо от редизайна.

- [ ] **fix: frontend route /api conflicts with backend API** (коммит `504cb36`).
  Вкладка «Интеграция API» была на адресе `/api`, а это префикс API бэкенда. При обновлении
  страницы на вкладке запрос уходил в бэкенд и показывалось `{"detail":"Not Found"}`.
  Вкладка переехала на `/integrations` (`frontend/src/App.tsx`, `frontend/src/components/Layout.tsx`).
  Перенести: `git switch main && git cherry-pick 504cb36`.
