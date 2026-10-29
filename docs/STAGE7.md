# Этап 7 — уборка перед проверкой

- [x] Удалить старые псевдонимы токенов из `frontend/src/styles/tokens.css` (`--panel`, `--panel-solid`,
  `--panel-raised`, `--row-hover`, `--line`, `--line-strong`, `--muted`, `--signal`, `--signal-ink`,
  `--signal-soft`, `--primary`, `--primary-ink`, `--entry`, `--exit`, `--screen`, `--hud`, `--shadow`,
  `--font`, `--rail`, `--rail-collapsed`, `--r-tile`, `--r-pill`) и заменить их использования в CSS
  на новые токены.
- [x] Удалить неиспользуемые ключи i18n во всех 4 языках: `api.body` и все, что найдутся поиском по коду.
- [x] Удалить CSS-правила, которые больше ничему не соответствуют: `.lang-switch` (заменён меню языков),
  `.split`, `.card-head` / `.card-body` на страницах, где их больше нет, `.channel-tag` и другие — найти
  поиском классов из `app.css` по разметке.
