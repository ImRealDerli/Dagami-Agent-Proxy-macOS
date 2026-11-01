# mac.26 — проверка версий и обновление приложения

- Проверка macOS-релизов, включая бета-версии, при запуске и каждые 6 часов; ручная проверка в настройках.
- Плашка с версией, описанием, критичностью и рекомендацией автора. «Обновить» запускает установку, «Позже» откладывает уведомление на сутки.
- Проверяются SHA-256, структура ZIP, bundle ID, версия, минимальная macOS, архитектуры и подпись. Подмена выполняется после выхода GUI. Нет подтверждения запуска — восстанавливается предыдущая копия.
- Профили и аккаунты сохраняются; установки без нажатия «Обновить» нет.

# mac.25 — автоввод кода Antigravity CLI

- Исправлен захват официального callback, который очищает адресную строку до опроса Selenium. State сохраняется в изолированном контексте своего браузерного окна до выполнения скрипта страницы; добавлен data-code-box.

- Служебные ответы Terminal и события фокуса больше не блокируют автовставку кода. Настоящий ручной ввод по-прежнему останавливает автоматику.
- Добавлены обезличенные этапы CLI-входа в журнал: получение ссылки, получение кода, ожидание приглашения и отправка Enter.

# mac.24 — кнопка «Починить IDE»

- Повторная подготовка из установленного оригинала, включая повреждённые копии, без требования успешной проверки старого патча.
- Проверяются SHA-256 и подпись новой копии; при отказе сохраняется прежняя запись. Перед ремонтом запрашивается закрытие процессов.

# mac.23 — отдельная Antigravity IDE и исправление загрузчика CLI

- Antigravity IDE com.google.antigravity-ide / Electron распознаётся отдельно от Antigravity App, включая ручное добавление и существующие custom-записи.
- Сетевой патч подтверждён по официальной IDE 2.6.0: запросы установки идут через локальный CONNECT-мост, штатные TLS-проверки сохраняются, тайм-аут manifest увеличен с 5 до 30 секунд. Неизвестные версии не меняются.
- В отдельной подписанной копии перехватываются исходные OAuth-ссылки; приложение и браузер используют один профиль. Оригинал сохраняется.
- Обязательные setup-домены включены в область Smart DNS. В журнал запуска добавлены имя, путь и PID приложения.

# mac.22 — проверка архитектуры и веб-версия ChatGPT

- Архитектура Mach-O проверяется до запуска и подготовки. ARM64-only приложение на Intel объясняется явно, кнопка запуска отключается; откат доступен.
- Веб-версия ChatGPT запускается через выбранный профиль в отдельном окне Chromium. Профиль браузера отделён от обычного браузера; его процессы не закрываются.

# mac.21 — ChatGPT Desktop

- Добавлено обнаружение ChatGPT в /Applications, ~/Applications и Spotlight с проверкой Info.plist.
- Для Electron-версии добавлены прокси-флаги, окружение backend, кнопки «Патч» и «Откат» для управляемого ярлыка. Оригинал и подпись не меняются.
- Нативные версии определяются отдельно: неподдерживаемый upstream-прокси не объявляется рабочим.

# mac.20 — Selenium-код входа, процессы и полные ошибки

- Selenium WebDriver подключается только к отдельному браузеру входа CLI. Код принимается с официального callback при совпадении state и вводится с Enter только в ожидающий CLI; ручной ввод не перезаписывается.
- Поставляются Selenium и ChromeDriver 156 для Intel/Apple Silicon; ввод паролей и подтверждение Google выполняет пользователь.
- Перед запуском и патчем десктопных приложений показываются найденные процессы с кнопками закрытия и отмены. CLI исключены; действие выполняется только после подтверждённого выхода.
- Журнал сохраняет полные traceback, команды, exit code и stderr с удалением паролей и OAuth-параметров.
- Серверы manifest, необходимые для установки IDE, исключены из необязательной блокировки обновлений; добавлена проверка сервера IDE через профиль.

# mac.19 — региональный Google-вход через шлюз Dagami

- После HTTP 403 на accounts.google.ru:443 от dns.dagami.ru / test-dns.dagami.ru выполняется один повтор через тот же upstream к общему endpoint accounts.google.com:443.
- Внутренний TLS, исходный SNI, HTTP Host и OAuth/Cookie URL не меняются; проверка сертификатов сохраняется. Прямой резерв не используется.
- Повтор ограничен этим доменом, портом и провайдером. Другие ошибки, домены и прокси сохраняют прежнее поведение.

# mac.18 — официальный callback Antigravity CLI

- Исправлен отказ перехвата реального CLI OAuth-запроса с https://antigravity.google/oauth-callback.
- Разрешение ограничено Antigravity CLI, точным HTTPS-доменом и путём без произвольного порта, query и fragment.
- Добавлен обезличенный пример фактического многострочного вывода CLI и проверки поддельных callback. IDE сохраняет прежние ограничения callback.

# mac.17 — полная OAuth-ссылка из терминала

- Перехватчик собирает URL, разбитый CLI на строки, удаляя только оформление терминала.
- Частичные client_id, отсутствующие state/callback и неполные PKCE больше не открываются в браузере.
- Проверены переносы, цветовые escape-последовательности и разрывы percent-encoding; исходные OAuth-параметры сохраняются.

# mac.16 — прямой перехват Antigravity CLI

- Управляемый CLI запускается в настоящем PTY с передачей клавиатуры и изменения размера окна.
- Включён host URL mode; исходная OAuth-ссылка из вывода CLI и вызовов BROWSER/open открывается через тот же LocalTunnel.
- Сохраняются аргументы и код выхода CLI. При завершении восстанавливается терминал и закрываются собственные ресурсы входа.
- В авторизации добавлена кнопка запуска Antigravity CLI с перехватом. Оригинальные бинарники и аккаунты не меняются.

# mac.15 — исходная OAuth-ссылка из backend IDE

- Backend подготовленной IDE передаёт исходную ссылку хосту, откуда она поступает в сессию Dagami. Буфер обмена не требуется.
- После загрузки shell-env восстанавливаются proxy-переменные выбранного профиля.
- Промежуточные страницы Google accountchooser/consent не открываются повторно; исходные state, PKCE и callback не изменяются.
- Старые подготовленные копии требуют обновления через «Настроить вход в IDE». Подписи и целостность ASAR сохраняются.

# mac.14 — OAuth из буфера обмена и проверка маршрута

- Во время активного ожидания входа отслеживаются изменения буфера обмена macOS; принимаются только подходящие OAuth-ссылки с state, client_id и callback клиента.
- Добавлены отдельный Antigravity CLI и кнопка проверки маршрута входа. Выбранный профиль сохраняется между перезапусками.
- До открытия браузера проверяется CONNECT и строгий TLS через выбранный маршрут. Отказ прокси объясняется с именем профиля и HTTP-кодом; прямой резерв не добавлялся.
- Перехватчик IDE показывает причину отказа маршрута. Повторная ссылка автоматически не открывается; ручное открытие остаётся доступным.

# mac.13 — маршрут входа Antigravity

- В совместимой приватной копии IDE ссылки OAuth передаются в активную сессию Dagami; браузер использует тот же маршрут, что и IDE.
- Обновляются целостность ASAR и подпись; оригинал не меняется. Неизвестная структура отклоняется.
- Antigravity IDE и веб-вход Gemini разделены. Добавлена настройка входа в IDE с подтверждением закрытия сессии.
- Ручное открытие ссылки работает повторно; ранний сбой браузера показывается как ошибка. Закрытие пустой группы процессов больше не блокирует новый вход.

# mac.12 — подпись подготовленной Antigravity IDE

- Изменённые language_server явно переподписываются и проверяются до подписи bundle.
- Для приватной ad-hoc копии сохраняются entitlements и runtime; требования исходной подписи издателя не переносятся.
- Ошибка codesign теперь показывает причину из stderr; при неудаче подготовка удаляется и состояние не меняется.

# mac.11 — повторный запуск Antigravity

- Процессы приложения учитываются отдельно от браузера входа. Оставшийся браузер больше не блокирует повторный запуск IDE.
- Завершённые процессы zombie не считаются работающим приложением; немедленный выход при старте сообщает ошибку.
- Ошибка доступа при завершении пустой группы процессов не блокирует очистку сессии; для живых процессов ошибка сохраняется.
- Повторное открытие работающей macOS IDE выводит её окно на передний план.

# mac.10 — единая авторизация, ключ Dagami и подготовка Codex

Добавлены отдельный браузер через профиль, штатный CLI-вход Codex/Claude Code, device-auth Codex, временный браузерный hook и подхват свежих ссылок из вывода/журналов. OAuth-ссылки и коды хранятся в памяти, журнал Dagami их не записывает. В настройках добавлены смена и сброс ключа Dagami. Кнопки патча/отката Codex управляют обратимыми ярлыками и прокси-запуском. Серверные ограничения и sandbox не изменяются.

# mac.9 — журнал и раздельный системный DNS

Добавлены журнал с ротацией и скрытием секретов, ссылки официального репозитория и Mac-портера. Раздельный DNS для ИИ выбран по умолчанию; кнопка исправления браузера восстанавливает общий DNS и оставляет Smart DNS только доменам ИИ с копией и откатом.

# mac.8 — кнопки патча и отката

Добавлена явная кнопка подготовки IDE и CLI. Для совместимого Mach-O x86_64 CLI перенесены локальная ветвь проверки, восемь protobuf-изменений и приватная proxy-env. Применение выполняется в копии с SHA-256 и проверкой подписи; оригинал сохраняется. ARM64 CLI и неизвестные структуры не патчатся.

# mac.6 — DNS для ИИ-сервисов

DNS-профиль по умолчанию охватывает основные ИИ-сервисы и их поддомены: OpenAI/ChatGPT, Anthropic/Claude, Google, DeepSeek, Qwen, Grok, Perplexity, Mistral, Copilot и другие. Есть свои точные домены и явные wildcard-правила. Набор Google/Antigravity остаётся отдельным выбором; старые профили автоматически не расширяются. Совместимость конкретного сервиса зависит от DNS-провайдера.

# mac.5 — создание Smart DNS-профилей

В меню «Добавить профиль» добавлен режим «Smart DNS без прокси». Доступны провайдеры и свои HTTPS/DoT/UDP/TCP endpoints. Применение к существующему профилю сохраняет выключенные реквизиты upstream и не требует Keychain при запуске DNS-only. Проверка DNS-only проверяет Google AI и Antigravity; остальные адреса используют сеть macOS. Системный DNS не меняется.

# mac.4 — проверка HTTPS CONNECT

Проверка HTTPS-прокси использует локальный мост, сохраняя внешний TLS к прокси при проверке TLS целевого сайта. Ошибки HTTP, TLS и тайм-ауты выводятся для конкретного target вместо общего сообщения. Проверка сертификатов сохранена.

# mac.3 — однозначная запись Keychain

Пароли записываются и читаются по service и фиксированному account dagami-profile-v2, чтобы старые записи с другими логинами не участвовали в чтении нового пароля. Для чтения старых профилей сохранён fallback. Добавлена настоящая проверка Security.framework на отдельном временном Keychain с дубликатами аккаунтов; пользовательский Keychain в проверке не меняется.

# mac.2 — единый импорт полной ссылки прокси

Добавлен редактор полной proxy URL для новых и существующих профилей с заполнением протокола, сервера, порта и реквизитов. При замене подключения сохраняются настройки маршрутизации и DNS; пароль подтверждается чтением Keychain, при ошибке выполняется откат. CLI profile add использует тот же путь сохранения. В заголовке окна показана локальная версия mac.2.

# mac.1 — авторизация upstream-прокси

Исправлен устаревший пароль в памяти после успешной записи в Keychain. Добавлена смена реквизитов выбранного профиля через отдельные поля без URL-кодирования; при ошибке сохранения выполняется откат. HTTP 407 сообщает схему Proxy-Authenticate и наличие реквизитов без их вывода; одинаковая ошибка не повторяется для всех API. Это исправление не подтверждает причину отказа конкретного провайдера.

# Локальный порт macOS 0.4.0 beta

Активация через Keychain, прямой и scoped Smart DNS маршруты, DNS endpoints и импорт профилей, поиск OAuth-ссылки, ручные приложения, флаги маршрута, ограничение моста, приватная подготовка совместимого Mach-O backend и откат. Границы проверки и отличия Windows: [MACOS_PORT.md](MACOS_PORT.md).

# Changelog

## 0.4.0 beta — 2026-10-31

- Use a shared GUI/CLI binary restore path; report partial rollback explicitly
  and distinguish restored ownership records from active patches.
- Stop conflicting processes only by verified executable paths; wait for exit
  before patch/launch. Remove leaking basename-only process enumeration.
- Make unknown applications launcher/environment-only, honor actual console PE
  type, explain capabilities on add, avoid duplicate EXE entries and reject
  removing active/patched custom entries. Check custom-list save failures.
- Bound bridge work to 128 concurrent connections, return 503 under saturation,
  serialize expensive binary status checks, remove repeated verification from
  the 300 ms status refresh, and use skip-based binary signature search.
- Document per-application settings, CLI wrapper limits, Google-only scoped DNS,
  remote/daemon boundaries and the manual-add workflow in APPLICATIONS.md.
- Resolve Node entrypoints only from recognized invocation lines, skipping
  quoted paths in echo/comments; retain native CLI argument/stdin handling.

- Offer to force-close the listed active Dagami sessions before switching
  proxy/DNS or saving a changed connection. Wait for managed processes to exit;
  cancellation or stop failure leaves connection settings unchanged.

- Keep proxy failures explicit instead of silently connecting directly when Smart
  DNS is also enabled. Local backend/OAuth loopback routing remains available.
- Fix the OAuth route/resolver allowlist mismatch for `accounts.google.com`;
  direct connections use the Windows route without a second Smart DNS lookup.
- Preserve disabled proxy settings on save, honor the proxy flag in diagnostic
  and CLI patch routes, and retain DNS nodes in cooldown as final reserves.
- Preserve configured DNS provider order for AI dependencies. Clarify that an
  unauthenticated userinfo check does not verify Gemini model responses/region.
- Distinguish server-side model/region refusals from local routing failures;
  login success and fixture checks do not prove availability of every model.


- Prioritize active Dagami (`89.22.224.205`) and MagicDNS (`2.56.175.196`) DoH
  seeds, verify candidate nodes in parallel and prune unreachable fallback seeds
  when official `.mobileconfig` downloads fail.
- Require a two-target HTTPS preflight quorum in `SystemDns.ps1`, remove the
  broad `microsoft.com` wildcard from NRPT rules and add the ten Antigravity /
  Google Cloud Companion domains to NRPT and Unix split-DNS presets.
- Support `direct` and Smart DNS-only routes in `NativeCliApps.Run`,
  `diagnose login` and `patch`; support EDNS0 UDP payloads up to 1232 bytes and
  cache `dns-custom.json` by timestamp in `LocalDnsAgent`.
- Improve `ActivationForm` text contrast, add `<dpiAware>true</dpiAware>` to the
  Windows manifest, rotate `devproxy.log` at 2 MB and prune stale staged updates
  and DNS job history.
- Prepare the eight verified regional protobuf metadata signatures in supported
  combined CLI/IDE backends as well as the CLI gate; detect incomplete older
  CLI preparation instead of reporting the IDE ready.
- Normalize legacy UTF-8 BOM settings even when their JSON text is unchanged.

- Refuse Low-integrity startup before opening the bridge or launching children;
  explain how to use a normal user copy and add `--permissions-info` diagnostics.

- Restore the selected Smart DNS route for Cloud Code. A configured upstream no
  longer overrides it for the two core Antigravity API hosts.
- Check TLS/userinfo through the actual Dagami bridge, including direct Windows/VPN
  mode. A failed diagnostic no longer replaces or blocks the launch action.
- Launch using saved connection settings without rewriting the configuration.
- Keep Dagami → MagicDNS as the default chain. Other providers require explicit
  selection; DNS attempt budgets leave time for reserve nodes.
- Disable experimental TLS splitting and update blocking when loading older,
  unversioned settings. Explicit choices saved with the new policy are retained.
- Save settings atomically without changing ACLs/attributes or truncating the
  destination after a replacement failure. Report save failures, keep the active
  connection unchanged and avoid writing a second configuration that is not loaded.
- Restore only managed proxy fields; preserve unrelated update/extension settings.
- Do not adopt managed local proxy settings as an upstream during discovery.
- After a failed optional client preparation, verify rollback and allow ordinary
  proxy launch. A failed rollback still stops launch.
- Remove recursive elevation/deletion fallback for legacy startup tasks.
- CLI connection setup supports `direct` and reports failed persistence.
- Preserve prior fixes for late DNS probe completion, metadata requests, normal
  Windows privileges, optional shortcuts and GUI lifetime after a proxy crash.

## 0.3.6 alpha — 2026-10-28

- Show whether the selected Antigravity backend is actually prepared and make
  ordinary-launch setup the primary action until a shortcut or CLI shim exists.
  Report setup results explicitly and explain automatic background startup.
- Simplify Windows navigation to Applications, DNS and Settings; put diagnostics,
  journal, launch preferences and system DNS controls in the settings pages.
- Add encrypted DNS for managed application routes and an optional Windows
  loopback DNS service. Refresh verified addresses from official Dagami and
  MagicDNS profiles, retain the last working list and use Dagami before MagicDNS.
  The whole-network option requires selected adapters and verified IPv4/IPv6.
- Recognize the local eligibility gate in compatible x64 Antigravity CLI builds,
  preserve the original file with hash-checked rollback and reject unknown shapes.
  Server-side account, region and subscription decisions are not changed.
- Add CLI doctor, error classification, a read-only patch preview and DNS commands.
- Detect the IDE-downloaded backend at `%USERPROFILE%/.gemini/bin/agy.exe` in
  native IDE preparation/CLI discovery and the portable CLI adapter. Keep fixture
  profile roots separate from installed user backends during regression checks.

- Managed Smart DNS uses verified DNS-over-HTTPS nodes; custom resolvers stay
  separate and retry over TCP when UDP fails.
- Validate DNS question/answer ownership and CNAME chains; respect short/zero TTL.
- System DNS/NRPT can store several verified addresses. Unavailable nodes are
  excluded before any changes; old single-server backups remain restorable.
- Replace the obsolete system DNS default with `45.147.31.32`.
- TLS diagnostics identify the host, connection layer and certificate policy/chain
  error codes while retaining validation and omitting certificate identities.
- Login diagnostics expose upstream CONNECT failures such as HTTP 407 instead
  of reporting only the bridge's HTTP 502.
- Add loopback DNS/TLS regression suites and reject native test runs without a
  PASS report, including silent execution failures.

## 0.3.0 alpha — 2026-10-28

- Fixed Codex Desktop detection for Microsoft Store/MSIX installations whose main
  executable is `app/ChatGPT.exe`: query current-user package registration and
  validate package identity/manifest, independent of a running process.
- Added detection of `Antigravity IDE.exe` alongside Manager, separate IDE settings,
  the `extensions/agy/bin` layout and the shared per-user `agy/bin/agy.exe` backend.
- Kept local RPC/CONNECT traffic on loopback in the native and Python bridges;
  preserved CSRF/auth, request bodies and streaming trailers without proxy credentials.
- Rejected a proxy bridge used as `antigravity.serverUrl`; stopped old active
  bridge connections on shutdown and kept partial preparation warnings visible.
- Removed the shortcut toggle, duplicate journal bug-report button and duplicate
  Antigravity action menu. Preparation/rollback now use the application actions.
- Added confirmation before resetting managed settings or restoring a backend.
- Added IDE 2.6 regression fixtures and repaired the static UI-preview check.
- Followed up on previous-version user logs: CONNECT/authentication checks replace
  TCP-only checks, bridge startup falls back to a Windows-assigned port, synthetic
  OAuth diagnostics compare routes, and UI/updater errors retain sanitized reasons.

## 0.2.0 alpha — 2026-10-22

- Native C# sources, manifest and DNS resource moved into `src/`.
- Build/install scripts moved into `tools/`; packaging, tests and guides updated.
- Added project agent guidance and empty hook/MCP configuration templates.
- Added a global bug-report button and journal export with a Save File dialog.
- Admin website/API removed from public access; administration requires an SSH
  tunnel to a loopback-only interface. Public report submission remains available.

- Repaired shortcut discovery/recovery and partial-failure rollback.
- Expanded application policies and compatible Antigravity/agy preparation.
- Preserved interactive CLI console/input through a console-subsystem launcher.
- Added report submission with sanitized logs, optional image and protected queue.
- Added the report service, private authenticated viewer and status management.
- Preserved source cleanup and kept license issuance/private data outside Git.

See `RELEASE_NOTES.md` for installation details and remaining alpha limitations.
