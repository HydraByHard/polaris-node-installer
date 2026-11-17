# Публикация v1.0.0 и последующих релизов

Репозиторий создан владельцем: https://github.com/HydraByHard/polaris-node-installer . [Релиз v1.0.0](https://github.com/HydraByHard/polaris-node-installer/releases/tag/v1.0.0) предназначен для изолированного первого теста. CURL28 не устранён; публикация исходников и подписанных файлов не является подтверждением полноценного VPN.

Для push исходников/тегов и создания Release/upload assets интеграции нужны доступ именно к этому репозиторию и **Contents: Read and write**; Metadata read предоставляется GitHub автоматически. Права Administration, Workflows и доступ к production VPS не требуются. Создание самого репозитория через интеграцию ранее было недоступно; владелец выполнил этот шаг вручную.

Далее приведён порядок выпуска. Для уже опубликованного v1.0.0 повторно не создавайте/не заменяйте tag или assets: для исправлений нужен новый versioned release.

## Доставка файлов v1.0.0

`git push` и создание Release работают; нативный upload на `uploads.github.com` возвращает401 Bad credentials с текущей runtime-авторизацией. Это не свидетельство отсутствия Contents write: запись исходников уже проверена. Причина различия авторизации по hostname не установлена.

Подписанные файлы v1.0.0 размещены в `release/v1.0.0/` и доступны по Git tag `v1.0.0`; Release содержит прямые ссылки. Команды README используют фактические tagged raw URLs и проверяют известные SHA256+Ed25519 signature. Нативные Release Assets не заявляются загруженными.

Если требуется именно прикрепление через Upload a release asset, нужна авторизация GitHub, принимаемая `uploads.github.com`, с Contents Read and write только для этого репозитория (либо исправленная маршрутизация связанной identity в среде). Repository Administration/Workflows не нужны. Не передавайте токен в чат или командной строке; используйте защищённые настройки подключения/секрета. Можно также прикрепить готовые файлы через веб-интерфейс GitHub владельцем.

## Подготовленные каталоги Cloud

- `/workspace/work/polaris-node-installer-public` — самостоятельный исходный репозиторий, новый Git root без истории родителя.
- `/workspace/work/node-installer-lab/release` — installer, Ed25519 signature/public key, source archive, отчёт и SHA256SUMS с подписью.

Никогда не выполняйте push из родительского `follow-your-polaris`: это другой, приватный репозиторий. Перед push проверьте, что `git rev-parse --show-toplevel` указывает именно на подготовленный public-export и `git ls-tree -r HEAD` содержит только установщик. История экспорта начинается с собственного нового root commit.

## Push проверенного самостоятельного экспорта

Следующие команды выполняются в существующем Cloud workspace после финальной упаковки. Они не обращаются к production VPS.

```bash
cd /workspace/work/polaris-node-installer-public
git status --short
git rev-list --count HEAD
git remote add origin https://github.com/HydraByHard/polaris-node-installer.git
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push -u origin main
```

Если origin уже добавлен, сначала проверьте `git remote get-url origin`; повторно добавлять его не надо. Не используйте force-push. При непустом чужом репозитории остановитесь, не заменяйте его историю.

Проверьте локальный пакет и подпись:

```bash
cd /workspace/work/node-installer-lab/release
openssl pkeyutl -verify -rawin -pubin -inkey release-signing-public.pem -in SHA256SUMS -sigfile SHA256SUMS.sig
sha256sum -c SHA256SUMS
```

Fingerprint публичного signing key закреплён в доверенном отчёте и docs/release.md. Не доверяйте впервые скачанному рядом ключу без сверки.

Ниже стандартная процедура для среды с рабочей upload-авторизацией. Для текущего v1.0.0 используются tagged repository files; повторно не создавайте опубликованный release. В новой версии сначала создают draft, загружают только перечисленные безопасные файлы и публикуют prerelease:

```bash
gh release create v1.0.0 --repo HydraByHard/polaris-node-installer --target main --draft --title 'Polaris Node Installer 1.0.0' --notes-file release-notes.md
gh release upload v1.0.0 --repo HydraByHard/polaris-node-installer polaris-install.sh polaris-install.sh.sig release-signing-public.pem polaris-node-installer-1.0.0-source.tar.gz polaris-node-installer-1.0.0.tar.gz test-report.md report.txt security-scan.json release-notes.md SHA256SUMS SHA256SUMS.sig
gh release edit v1.0.0 --repo HydraByHard/polaris-node-installer --draft=false --prerelease
gh release view v1.0.0 --repo HydraByHard/polaris-node-installer --json url,assets
```

Не используйте --clobber для уже опубликованного релиза. Если draft с таким тегом существует, сначала проверьте его target/asset-хеши, затем продолжите только собственную незавершённую публикацию.

Последняя проверка: скачайте installer и остальные артефакты по фактическим публичным URLs без авторизации, сравните доверенные SHA256 и проверьте подписи. Для v1.0.0 это tagged raw URLs, а не несуществующие releases/download URLs. Наличие draft или push само по себе не доказывает публичное скачивание.
