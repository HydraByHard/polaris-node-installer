# Однократная публикация владельцем

На17.11.2026 GitHub-релиз отсутствует. Создание репозитория через текущую авторизованную интеграцию завершилось:

```text
GraphQL: Resource not accessible by integration (createRepository)
```

Это ограничение GitHub-прав, а не запрос новых sudo-прав или доступа к VPS. Исходники и подписанный пакет подготовлены. Нельзя выдавать планируемый download URL за существующий.

## Минимальное действие владельца

В GitHub создайте **пустой публичный** репозиторий `HydraByHard/polaris-node-installer`, без начальных README/license/gitignore. Добавьте его в разрешённые репозитории текущего GitHub-подключения ChatGPT. Приватный `follow-your-polaris` и его история остаются приватными.

После этого подготовленный экспорт можно опубликовать из текущего Cloud workspace. Новые программы на домашнем ПК не нужны. Альтернатива — скачать подготовленные файлы, загрузить исходники и release-assets через штатный веб-интерфейс GitHub.

## Подготовленные каталоги Cloud

- `/workspace/work/polaris-node-installer-public` — самостоятельный исходный репозиторий, новый Git root без истории родителя.
- `/workspace/work/node-installer-lab/release` — installer, Ed25519 signature/public key, source archive, отчёт и SHA256SUMS с подписью.

Никогда не выполняйте push из родительского `follow-your-polaris`: это другой, приватный репозиторий. Перед push проверьте, что `git rev-parse --show-toplevel` указывает именно на подготовленный public-export и `git ls-tree -r HEAD` содержит только установщик. История экспорта начинается с собственного нового root commit.

## Команды после выдачи GitHub-доступа

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

Создайте draft, загрузите только перечисленные безопасные файлы и опубликуйте его как prerelease для первого live-теста:

```bash
gh release create v1.0.0 --repo HydraByHard/polaris-node-installer --target main --draft --title 'Polaris Node Installer 1.0.0' --notes-file release-notes.md
gh release upload v1.0.0 --repo HydraByHard/polaris-node-installer polaris-install.sh polaris-install.sh.sig release-signing-public.pem polaris-node-installer-1.0.0-source.tar.gz polaris-node-installer-1.0.0.tar.gz test-report.md report.txt security-scan.json release-notes.md SHA256SUMS SHA256SUMS.sig
gh release edit v1.0.0 --repo HydraByHard/polaris-node-installer --draft=false --prerelease
gh release view v1.0.0 --repo HydraByHard/polaris-node-installer --json url,assets
```

Не используйте --clobber для уже опубликованного релиза. Если draft с таким тегом существует, сначала проверьте его target/asset-хеши, затем продолжите только собственную незавершённую публикацию.

Последняя проверка: скачайте installer по **фактическому** browser_download_url без авторизации, сравните доверенный SHA256 и проверьте подпись. Только после этого вставьте подтверждённый URL в команды установки и README. Наличие draft или push само по себе не доказывает публичное скачивание.
