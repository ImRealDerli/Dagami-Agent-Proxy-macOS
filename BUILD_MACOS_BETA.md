# Сборка macOS-порта

Собирать нужно на Mac. Для SwiftUI-приложения нужны Xcode Command Line Tools (`xcode-select --install`) и SDK с поддержкой macOS 13. Для Python-движка используется Python.org **3.12 universal2**, установленный в `/Library/Frameworks/Python.framework/Versions/3.12`.

После установки Python выполните штатный `Install Certificates.command` из папки Python 3.12. Сборщик ожидает certifi и его корневые сертификаты в этом framework.

Из корня репозитория:

```sh
python3 tools/check_source_hygiene.py
python3 -m unittest discover -s tools -p test_source_hygiene.py
python3 tools/verify_macos.py --headless
python3 tools/build_universal.py
```

Для работы `check_source_hygiene.py` файлы должны быть добавлены в индекс Git. Тесты используют временные хранилища и подменяют запись Keychain. Не проверяйте их на настоящих аккаунтах или изменением системного DNS.

Сборщик компилирует интерфейс для x86_64 и arm64, объединяет его через lipo, добавляет Python universal2, движок и сертификаты. Нативные части runtime проверяются на обе архитектуры. Затем применяется локальная подпись и выполняется `codesign --verify --deep --strict`.

Результат находится в `../Release`, временные файлы — в `../Build`. Само приложение, ZIP и полный архив исходников создаёт `tools/build_universal.py`.

Для DMG нужны дополнительные пакеты:

```sh
python3 -m pip install --target ../BuildTools ds-store mac-alias
PYTHONPATH=../BuildTools python3 tools/build_dmg.py
```

Сборщик DMG добавляет фон и ссылку на «Программы», затем проверяет готовый образ. Перед публикацией пересчитайте SHA256SUMS.txt для окончательных ZIP и DMG, поскольку исходный сборщик APP записывает суммы ZIP-файлов до создания DMG.

## Selenium

Проверенные зависимости и драйверы двух архитектур находятся в `devproxy_pkg/assets/webdriver`. Для их обновления есть `tools/prepare_webdriver.py` и `tools/requirements-webdriver.txt`. Обновление драйвера требует проверки его совместимости с браузером, SHA-256 в manifest и записей доверенных бинарников в `tools/source-policy.json`.

Сборки сейчас не нотарифицированы Apple. Ad-hoc подпись проверяет целостность пакета, но не подтверждает личность разработчика. Не публикуйте артефакты со сбоями проверки подписи.

## Логотипы интерфейса

Готовые логотипы не требуют дополнительных библиотек при запуске. Чтобы повторно подготовить их из исходных SVG, установите зависимости из `tools/requirements-brand-icons.txt` в отдельное окружение и запустите `python3 tools/prepare_brand_icons.py`. Используется resvg, поскольку нативный ImageIO некорректно масштабирует некоторые SVG-маски. SVG, лицензии, URL и SHA-256 сохранены в `native/macos/BrandIcons`. VS Code использует официальный PNG 1024 px.

Маленькие иконки для реальных размеров интерфейса готовит `python3 tools/prepare_icon_rasters.py` (Pillow из requirements-brand-icons.txt). Скрипт загрузки логотипов вызывает его автоматически. Готовые размеры и SHA-256 сохранены в BrandIcons/raster-manifest.json. При запуске приложение использует AppKit и готовые варианты, дополнительных Python-зависимостей для иконок не требуется.

Если Xcode требует незавершённую настройку, сборку можно выполнить с установленными Command Line Tools: `DEVELOPER_DIR=/Library/Developer/CommandLineTools python3 tools/build_universal.py`.

## Сборка на GitHub

В Actions доступен ручной workflow «macOS Universal release». Он собирает существующий macOS-тег на отдельном Mac, проверяет подпись APP и образ DMG, вычисляет SHA-256 и загружает четыре файла в подготовленный черновик релиза. Для запуска нужен черновик с этим тегом; опубликованные релизы workflow не заменяет. Исходники берутся из тега, а не из незакоммиченных файлов.

## Rust-транспорт

Начиная с mac.28 сборка APP требует Rust 1.99.1 и обе цели: `rustup target add x86_64-apple-darwin aarch64-apple-darwin`. `tools/build_universal.py` вызывает `tools/build_network.py`, собирает Tokio/rustls с `Cargo.lock`, объединяет архитектуры и подписывает `DagamiNetwork`. В APP добавляется `ThirdPartyRust.txt` с лицензиями зависимостей. Cargo target и служебные материалы хранятся в `../Build`, в исходники не включаются.

Отдельная сборка: `DEVELOPER_DIR=/Library/Developer/CommandLineTools python3 tools/build_network.py`. Для фикстур: `DAGAMI_TEST_RUST_BINARY=../Build/DagamiNetwork python3 -m unittest tests.test_rust_transport`. Фикстуры поднимают только локальные прокси и временный CA. Исходный Python-запуск без собранного помощника сохраняет совместимый транспорт; в основной macOS APP помощник входит в пакет.
