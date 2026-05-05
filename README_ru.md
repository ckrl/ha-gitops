# HA GitOps

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-41BDF5.svg)](https://www.home-assistant.io/)
[![Validate](https://github.com/ckrl/ha-gitops/actions/workflows/validate.yml/badge.svg)](https://github.com/ckrl/ha-gitops/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/ckrl/ha-gitops?include_prereleases&sort=semver)](https://github.com/ckrl/ha-gitops/releases)

[English](./README.md) | Русский

<p align="center">
  <img src="custom_components/ha_gitops/brand/icon.png" alt="HA GitOps icon" width="128" />
</p>

**HA GitOps** превращает каталог конфигурации Home Assistant `/config` в полноценное
git-рабочее дерево и позволяет выполнять `pull`, `fetch`, `push`, а также наблюдать
статус синхронизации прямо из интерфейса HA — без отдельного аддона, внешнего
редактора или доступа к shell.

Это HACS custom integration: настройка полностью через **Settings → Devices & services**,
аутентификация по SSH, безопасность по умолчанию (`secrets.yaml` и runtime-state HA
никогда не коммитятся), полный набор тестов на `pytest-homeassistant-custom-component`.

---

## Содержание

- [Зачем эта интеграция](#зачем-эта-интеграция)
- [Возможности](#возможности)
- [Как это работает](#как-это-работает)
- [Требования](#требования)
- [Установка](#установка)
- [Первичная настройка](#первичная-настройка)
- [Сущности и сервисы](#сущности-и-сервисы)
- [Справочник статусов](#справочник-статусов)
- [Модель безопасности](#модель-безопасности)
- [Опции и переконфигурирование](#опции-и-переконфигурирование)
- [Решение проблем](#решение-проблем)
- [Разработка](#разработка)
- [Архитектура и дизайн](#архитектура-и-дизайн)
- [Roadmap](#roadmap)
- [Вклад в проект](#вклад-в-проект)
- [Лицензия](#лицензия)

---

## Зачем эта интеграция

Из коробки YAML-файлы в `/config/*.yaml` не версионируются. Случайная правка,
неудачная замена устройства или экспериментальная автоматизация — и нет ни истории,
ни возможности откатиться, сравнить состояния или провести аудит.

Существующие альтернативы оставляют пробелы:

- **Studio Code Server / File Editor** — это редакторы, не система контроля версий.
- **Git pull add-on** — только pull, без push, без UI-сенсоров, аддон (а не
  интеграция), с ограниченной настройкой.
- **Ручной `git` через SSH** — работает, но невидим для Home Assistant: нет сигнала
  на дашборде, нет уведомлений, нет кнопки на устройстве и нет защиты от случайного
  коммита `secrets.yaml`.

`ha_gitops` закрывает эту нишу: компактная HACS-интеграция, которая следует
стандартному GitOps-паттерну (каталог конфигурации **является** рабочим деревом),
выводит git-операции как first-class сущности HA и встраивает правила безопасности,
которые иначе пришлось бы поддерживать вручную.

## Возможности

- **UI Config Flow** — добавление через **Settings → Devices & services**, без блока
  в `configuration.yaml`. Один экземпляр на инстанс HA.
- **Умный автоподхват** — если в `/config/.git` уже есть git-репозиторий, форма
  setup-а автоматически подставляет URL remote, активную ветку, `user.name`,
  `user.email` и стандартный путь к SSH-ключу.
- **Управление SSH-ключом из UI** — генерация ED25519 deploy key прямо из
  интеграции; публичный ключ показывается в persistent notification — копируйте и
  вставляйте в GitHub / GitLab / Forgejo / самохостинг.
- **Test connection** — однокликовый `git ls-remote origin`, чтобы проверить
  аутентификацию и URL до того, как им доверять.
- **Три кнопки** — `Pull` (только fast-forward), `Fetch` (только обновление remote
  refs), `Push` (атомарное автокоммит+push одним действием).
- **Пять диагностических сенсоров** — статус синхронизации, локальный HEAD, remote
  HEAD, число изменённых YAML-файлов, время последней успешной remote-синхронизации.
- **Сервис `ha_gitops.commit`** — локальный коммит без push (например, snapshot
  перед экспериментом); поддерживает опциональное собственное сообщение.
- **Repairs flow для pull** — если pull принёс YAML-изменения, HA GitOps создаёт
  Repairs-запись с однокликовой починкой "Reload core configuration". Опционально —
  автоперезагрузка.
- **Адаптивные сообщения коммитов** — subject формируется из списка изменённых
  файлов; body содержит полный diff-stat и трейлер `Co-authored-by: HA GitOps` для
  ясной атрибуции.
- **Безопасность по умолчанию** — `secrets.yaml`, `secrets_backup.yaml`, `.storage/`,
  `.cloud/`, `core_*` и SQLite-БД HA исключаются управляемым блоком в `.gitignore`,
  плюс in-code panic guard, который прерывает push, если `secrets.yaml` всё-таки
  попал в staged.
- **Не блокирует event loop** — каждый git-вызов идёт через GitPython в worker
  thread; HA event loop никогда не блокируется сетевым I/O.
- **Локализация** — английский и русский (`strings.json` + `translations/ru.json`).
- **Покрыто тестами** — полный pytest-suite на
  `pytest-homeassistant-custom-component`, hassfest, HACS validation, lint
  (ruff + black) — всё проходит CI.

## Как это работает

```
┌──────────────────────── Home Assistant ────────────────────────┐
│                                                                │
│   Кнопки                Сенсоры                Сервис          │
│   ─────────             ─────────              ─────────       │
│   button.pull           sensor.sync_status     ha_gitops.      │
│   button.fetch          sensor.local_commit       commit       │
│   button.push           sensor.remote_commit                   │
│                         sensor.changed_files                   │
│                         sensor.last_sync                       │
│            │                  │                  │             │
│            └────────┬─────────┴──────────────────┘             │
│                     ▼                                          │
│              ┌────────────────┐                                │
│              │  GitManager    │  (asyncio.to_thread)           │
│              └───────┬────────┘                                │
│                      │ GitPython                               │
│                      ▼                                         │
│              ┌────────────────┐                                │
│              │  git CLI       │  GIT_SSH_COMMAND               │
│              └───────┬────────┘                                │
└──────────────────────┼─────────────────────────────────────────┘
                       │   SSH (ED25519, изолированный known_hosts)
                       ▼
              ┌────────────────┐
              │  Remote Git    │  GitHub / GitLab / Forgejo /
              │  репозиторий   │  self-hosted
              └────────────────┘
```

Каталог `/config` сам является git-рабочим деревом: `.git/` живёт в `/config/.git`,
интеграция управляет `/config/.gitignore`, а SSH-ключи лежат в `/config/.ha_gitops/`
(исключены из репозитория).

## Требования

- **Home Assistant** `2024.1.0` или новее.
- **Python** `3.11+` (соответствует HA Core).
- **Бинарник `git`** в окружении HA. По умолчанию доступен на Home Assistant OS,
  Supervised и в официальном Container-образе. На голом HA Core / venv может
  потребоваться установка через пакетный менеджер ОС.
- **Удалённый git-репозиторий** (GitHub, GitLab, Forgejo, Bitbucket, self-hosted
  Gitea, обычный SSH-сервер — всё, что доступно по SSH).
- **SSH-ключевая пара** с правом на запись в этот репозиторий — либо ваша, либо
  сгенерированная самой интеграцией.

## Установка

### Вариант 1 — HACS (рекомендуется)

[![Открыть репозиторий в HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ckrl&repository=ha-gitops&category=integration)

1. Нажмите на бейдж выше (откроется HACS в вашем Home Assistant с уже подставленным репозиторием), **либо** добавьте вручную:
   - **HACS → Integrations → ⋮ → Custom repositories**
   - URL: `https://github.com/ckrl/ha-gitops`
   - Категория: **Integration**
2. Установите **HA GitOps**.
3. Перезапустите Home Assistant.

### Вариант 2 — Вручную

```bash
# на хосте, где работает Home Assistant
cd /config
mkdir -p custom_components
git clone https://github.com/ckrl/ha-gitops /tmp/ha-gitops
cp -r /tmp/ha-gitops/custom_components/ha_gitops custom_components/
```

Затем перезапустите Home Assistant.

### Добавление интеграции в Home Assistant

После установки и перезапуска:

[![Добавить интеграцию в ваш Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ha_gitops)

Бейдж выше открывает **Add integration → HA GitOps** прямо в вашем инстансе. Тот же путь доступен вручную: **Settings → Devices & services → Add integration → HA GitOps**.

## Первичная настройка

1. **Settings → Devices & services → Add integration → HA GitOps.**
2. Заполните форму (если `/config/.git` уже существует, значения подставятся
   автоматически):
   - **Git remote URL** — SSH-форма, например `git@github.com:owner/ha-config.git`.
   - **Branch** — по умолчанию `main`.
   - **Git commit author name / email** — по умолчанию `Home Assistant` /
     `homeassistant@local`.
   - **Private SSH key path** — оставьте пустым для значения по умолчанию
     (`/config/.ha_gitops/id_ed25519`); поддерживаются абсолютные и относительные
     (от `/config`) пути.
3. Submit. Интеграция выполнит `GitManager.initialize()` для `/config`:
   `git init` (если нужно) → настройка `origin` → запись управляемого блока в
   `.gitignore` → `git fetch origin`.
4. Если deploy key ещё не создан — откройте **Settings → Devices & services →
   HA GitOps → Configure → Generate SSH key**. Интеграция сгенерирует ED25519
   ключевую пару и покажет публичный ключ в persistent notification — добавьте его
   в deploy keys на git-хосте.
5. Проверьте всё через **Configure → Test connection** (запускает
   `git ls-remote origin`).
6. Используйте **Pull / Fetch / Push** на странице устройства интеграции; следите
   за состоянием через сенсор `Sync status`.

> **Совет.** Типовой bootstrap: создаёте пустой репозиторий на git-хосте, генерируете
> SSH-ключ из интеграции, добавляете публичный ключ как deploy key с правом записи,
> жмёте **Push** — и текущий `/config` уезжает в репозиторий.

## Сущности и сервисы

Все сущности группируются на одном устройстве **HA GitOps**. Сенсоры имеют категорию
`diagnostic`, кнопки — `config`.

### Сенсоры

| Сущность | Тип | Описание |
| --- | --- | --- |
| `sensor.ha_gitops_sync_status` | enum | Текущий статус синхронизации — см. [справочник ниже](#справочник-статусов). Атрибуты: `last_operation`, `last_operation_time`, `last_error`, `local_commit`, `remote_commit`, `changed_files_count`, `changed_files`, `last_sync`. |
| `sensor.ha_gitops_commit_local` | text | Короткий хэш локального `HEAD`. Атрибуты: `full_hash`, `message`, `author`, `timestamp`. |
| `sensor.ha_gitops_commit_remote` | text | Короткий хэш `origin/<branch>`. Атрибуты: те же. |
| `sensor.ha_gitops_changed_files` | numeric | Число корневых YAML-файлов с изменениями в working tree. Атрибут `files`: список `{name, status}`. |
| `sensor.ha_gitops_last_sync` | timestamp | Время завершения последней успешной remote-операции. |

### Кнопки

| Сущность | Действие |
| --- | --- |
| `button.pull` | `git fetch origin` + fast-forward merge `origin/<branch>`. Никогда не делает rebase или auto-merge. При YAML-изменениях: persistent notification + Repairs-запись с однокликовой починкой "Reload core configuration", либо автоперезагрузка, если включена в опциях. |
| `button.fetch` | Только `git fetch origin` — обновляет remote refs, не трогая working tree. Удобно для обновления `Sync status` без применения изменений. |
| `button.push` | Стейджит корневые `*.yaml` (исключая `secrets.yaml`) и `.gitignore`, коммитит при наличии изменений, затем пушит. Если коммитить нечего, но есть незапушенный локальный коммит — выполняется только push. Если делать вообще нечего — чистый no-op. |

### Сервисы

| Сервис | Назначение |
| --- | --- |
| `ha_gitops.commit` | Стейдж и коммит по тем же правилам, что у Push, но **без push**. Опциональное поле `message` переопределяет адаптивное сообщение коммита — удобно для snapshot-ов перед рискованными изменениями. |

## Справочник статусов

| Значение | Смысл | Рекомендуемое действие |
| --- | --- | --- |
| `clean` | Локальный `HEAD` совпадает с `origin/<branch>`; нет незакоммиченных YAML-изменений. | Ничего — всё синхронно. |
| `modified` | В отслеживаемых YAML-файлах есть незакоммиченные изменения. | Нажмите **Push**, когда готовы. |
| `ahead` | Локальные коммиты ещё не на remote. | Нажмите **Push**. |
| `behind` | Remote ушёл вперёд, fast-forward возможен. | Нажмите **Pull**. |
| `diverged` | Локальная и удалённая истории разошлись — fast-forward невозможен. | Разрешите вручную (rebase / merge / reset через SSH). |
| `error` | Последняя git-операция завершилась ошибкой. См. атрибут `last_error` и логи HA. | Устраните причину и повторите. |
| `unknown` | Репозиторий ещё не инициализирован, либо первичная проверка не завершена. | Подождите или проверьте setup. |

## Модель безопасности

`ha_gitops` придерживается жёсткой позиции по тому, что **никогда** не должно
попасть в репозиторий:

- **Секреты не коммитятся.** `.gitignore` исключает `secrets.yaml`,
  `secrets_backup.yaml`, `*.secrets.yaml`. Дополнительный in-code **panic guard**
  перед каждым `git commit` сверяет staged-набор и прерывает операцию, если
  secrets-файл всё-таки прошёл.
- **Runtime-state HA не коммитится.** `.storage/`, `.cloud/`, `core_*`,
  `home-assistant_v2.db*`, `home-assistant.log*` — исключены.
- **Pull только fast-forward.** Конфликты выходят как `diverged` и требуют ручного
  вмешательства; авто-merge / авто-rebase не выполняются.
- **SSH-ключевой материал изолирован.** Путь по умолчанию —
  `/config/.ha_gitops/id_ed25519`, права `0600`, директория `/config/.ha_gitops/` в
  `.gitignore`. Отдельный `known_hosts` поддерживается интеграцией
  (`StrictHostKeyChecking=accept-new`) — никаких записей в `~/.ssh` пользователя.
- **Глобальный gitconfig хоста не трогается.** "Dubious ownership" (Git 2.35+) и
  идентичность автора коммита настраиваются через `GIT_CONFIG_KEY_*` /
  `GIT_CONFIG_VALUE_*` и `-c user.name=… -c user.email=…` — без записей в global
  `git config`.
- **Авто-push отсутствует.** Каждый push явный (кнопка или сервис). Нужно по
  расписанию — поднимите HA-автоматизацию, дёргающую кнопку.

## Опции и переконфигурирование

**Settings → Devices & services → HA GitOps → Configure** открывает меню действий:

- **Settings** — изменить URL remote, ветку, идентичность автора, путь к SSH-ключу,
  интервал опроса статусного сенсора (`30…86400 с`, по умолчанию `300 с`) и
  переключатель **Automatically reload core configuration after a pull that changes
  YAML**.
- **Generate SSH key** — создать ED25519 ключевую пару по выбранному пути.
  Прерывается, если непустой приватный ключ уже существует. После успеха публичный
  ключ доставляется через persistent notification.
- **Test connection** — запускает `git ls-remote origin` и сообщает результат.

## Решение проблем

### Setup падает с "Could not initialize the Git repository"

Откройте логи HA (фильтр `custom_components.ha_gitops`) и проверьте:

- **Права на SSH-ключ** — должны быть `0600` и читаемы процессом HA.
- **Доступ deploy key** — публичный ключ должен быть добавлен на git-хост с правом
  **записи**, если планируется push.
- **Remote URL** — SSH-форма (`git@host:owner/repo.git`); HTTPS пока не
  поддерживается.
- **Имя ветки** — должна существовать на remote либо быть той веткой, которую вы
  создадите при первом push.
- **Бинарник `git`** — `which git` на хосте HA; установите при отсутствии.

### "detected dubious ownership" на Git 2.35+

`HA GitOps` уже передаёт `safe.directory` для `/config` каждому git-вызову,
который запускает сама. Если ошибка прилетает извне (например, ручной `git status`
из shell-аддона) — пометьте каталог safe только в этой shell:

```bash
git config --global --add safe.directory /config
```

### Pull прошёл, но YAML-изменения не применились

Home Assistant загружает YAML только при старте или явной перезагрузке. Варианты:

- **Settings → System → Repairs** → починка "HA GitOps: configuration updated from
  Git" (вызывает `homeassistant.reload_core_config`), **или**
- Включите **Automatically reload core configuration after a pull** в опциях
  интеграции, **или**
- Перезапустите Home Assistant вручную.

### Push отклонён: "remote has new changes"

Remote ушёл вперёд. Сначала **Pull**, разрешите `diverged` при необходимости,
потом снова **Push**.

### Сенсор показывает `unknown` после долгого fetch

Обновления статуса привязаны к `scan_interval` сенсора (по умолчанию 5 мин).
Нажмите **Fetch** для немедленного обновления remote refs или уменьшите интервал
опроса в опциях.

### Entity ID не меняются после обновления интеграции

Home Assistant фиксирует `entity_id` к стабильному `unique_id` в
`core.entity_registry`. Поскольку `unique_id` намеренно стабилен между версиями,
старые `entity_id` сохраняются. Переименуйте их в **Settings → Devices & services
→ HA GitOps**.

## Разработка

Этот репозиторий **не** упакованный Python-проект — интеграция живёт в
`custom_components/ha_gitops/` и подгружается Home Assistant в runtime.
`pyproject.toml` объявляет только dev-окружение.

```bash
# uv-based workflow (как в CI)
uv sync --extra dev

# Lint и форматирование
uv run ruff check .
uv run black --check .

# Тесты (с покрытием)
uv run pytest -v --cov=custom_components/ha_gitops --cov-report=term-missing
```

CI запускается на каждый push и PR (`.github/workflows/validate.yml`):

- **hassfest** — валидатор HA-манифестов
- **HACS validation** — `category: integration`
- **Lint** — `ruff` + `black --check`
- **Tests** — pytest matrix на Python 3.11 и 3.12

Полный архитектурный design-of-record (нумерация совпадает с docstring-ссылками)
находится в [`docs/architecture.md`](./docs/architecture.md). Каталог
`.cursor/rules/` содержит соглашения для AI-ассистентов в IDE.

## Архитектура и дизайн

Подробный разбор — диаграмма компонентов, публичный API `GitManager`, формат
сообщений коммитов, алгоритм определения статуса, таксономия ошибок и компромиссы
безопасности — в [`docs/architecture.md`](./docs/architecture.md).

Ключевые проектные решения одним абзацем: `/config` сам является git-рабочим
деревом (без staging-копии, без shadow-директории). Git-операции идут через
GitPython, который шеллится в системный `git` binary; вызовы выполняются в worker
thread, чтобы HA event loop оставался отзывчивым. SSH — единственная схема
аутентификации в MVP, путь к ключу и `known_hosts` управляются интеграцией. Pull
только fast-forward; push — атомарное автокоммит+push одним действием с
адаптивным сообщением коммита и трейлером `Co-authored-by: HA GitOps` для ясной
атрибуции.

## Roadmap

Запланировано в будущих релизах (трекинг — в `docs/architecture.md` §12):

- HTTPS-аутентификация с хранением токена через HA credential storage.
- Поддержка нескольких веток и переключение ветки на лету.
- "Force pull" как явное high-friction действие для diverged-состояний.
- Подача в HACS Default Store после стабилизации API и контракта сущностей.

Вне скоупа (намеренные non-goals):

- Синхронизация `.storage/`, `.cloud/`, `core_*` и любого другого runtime-state HA.
- Включение `secrets.yaml` в репозиторий — это жёсткая политика.
- Авто-merge при конфликтах.
- Управление несколькими репозиториями из одного инстанса HA.

## Вклад в проект

Issues и pull requests приветствуются на
[github.com/ckrl/ha-gitops](https://github.com/ckrl/ha-gitops).

Перед открытием PR:

1. Прочтите [`docs/architecture.md`](./docs/architecture.md) — публичный API
   `GitManager` и контракт сущностей трекаются там.
2. Прогоните локально `ruff`, `black --check` и `pytest`; CI запустит то же.
3. Держите изменения в рамках задокументированного дизайна или включайте поправку
   в архитектуру тем же PR.

## Лицензия

[MIT](./LICENSE) © Constantine Krylov
