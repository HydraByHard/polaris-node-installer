# Проверка и сборка релиза

Основной bootstrap использует **заранее известный SHA256 из доверенного отчёта владельца**. Скачанный рядом SHA256SUMS обнаруживает повреждение, но не подмену источника. Встроенный payload также проверяется до исполнения/установки Python.

Релиз дополнительно имеет Ed25519 detached signature. Публичный ключ `release-signing-public.pem` не секретен. Его SHA256: `0ee4e2704e97c16fa647296eed27b7332bf382da498fe08d637b583a24cc2400`. Закрепите этот fingerprint из независимого доверенного отчёта, а не впервые доверяйте копии рядом с installer.

```bash
sha256sum release-signing-public.pem
openssl pkeyutl -verify -pubin -inkey release-signing-public.pem -rawin -in polaris-install.sh -sigfile polaris-install.sh.sig
```

Ожидается `Signature Verified Successfully`. При любом несовпадении ничего не запускать. Отдельный release-signing key не используется для SSH/администрирования и не включается в исходники или релиз.

Воспроизводимая сборка скрипта:

```bash
python3 scripts/build-release.py --output dist
sha256sum dist/polaris-install.sh
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

В zipapp включаются только `.py`/`.json` из src/polaris_node, фиксируются timestamps и порядок. Лабораторные credentials, VM-образы, private evidence и рабочий каталог не упаковываются. Для будущего обновления владелец должен обеспечить безопасное хранение signing key либо явно опубликовать новый доверенный fingerprint. Потеря ключа не разрешает обходить проверку подлинности.

Перед публикацией: Gitleaks с redaction, точечный поиск известных lab-секретов в source+распакованном payload, контроль package manifest, тесты, review. Приватный родительский follow-your-polaris и его история не становятся публичными: экспортируется только эта самостоятельная директория в новый репозиторий.

## Доставка v1.0.0

GitHub Release ссылается на подписанные файлы в `release/v1.0.0` по tag `v1.0.0`. Команды README проверяют два доверенных SHA256 и Ed25519 signature до исполнения. Нативные Release Assets не загружены: upload endpoint отклоняет текущую runtime-авторизацию с401. Пакет, manifest и signatures доступны как обычные versioned repository files; проверка подлинности не зависит от названия механизма доставки.
