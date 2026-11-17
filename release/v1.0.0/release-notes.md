# Polaris Node Installer v1.0.0 — prerelease

**Полноценная работа VPN НЕ подтверждена.** Контрольный HTTPS roundtrip через XHTTP завершился CURL28. Причина оставшегося timeout не установлена; публикация не устраняет и не объясняет этот сбой. Используйте только новую изолированную VPS и тестового пользователя. Основной Host остаётся disabled+hidden до успешной независимой проверки.

## Что проверено

- Ubuntu Server22.04/24.04 AMD64: настоящие изолированные VM; установка Docker/Compose, идемпотентность, restart/reboot, SIGTERM и локальный rollback/restore.
- Native Remnawave3.4.11 API:29 реальных assertions; регистрация отдельного Node/Profile/hiddenHost, отдельные publish/unpublish.
- 83 unit/release tests и54 родительских regression tests; тесты повторены при упаковке, runtime installer byte-identical.
- ACME HTTP01: полный CLI и реальный установленный systemd timer→service→renew→atomic TLS pair→Nginx; strictTLS/h2.
- Источники и история самостоятельного экспорта просканированы Gitleaks; private keys, API tokens, VM disks и private evidence в release не включены.

## Безопасная установка

README содержит три команды: HTTPS download installer/signature/public key; сверка двух заранее известных SHA256; Ed25519 verification и запуск только при успехе.

Installer SHA256: `556a5ba3df35892cac49bf946fe8889640bea538522996a32e303544bdc5d69a`.

Доверенный fingerprint публичного PEM-файла:

```text
0ee4e2704e97c16fa647296eed27b7332bf382da498fe08d637b583a24cc2400  release-signing-public.pem
```

Scopes и первый live-тест: README и docs/first-live.md. Временный native API-токен на1день вводится скрыто, в installer не сохраняется; он повторно применим до отзыва/expiry. Требуется его отзыв владельцем.

## Доставка и файлы

Нативный Upload a release asset на uploads.github.com вернул401 Bad credentials с текущей runtime-авторизацией. Запись в репозиторий и управление Release работают. Файлы ниже размещены в Git tag v1.0.0 в каталоге release/v1.0.0; **они не являются нативными Release Assets**. Для таких attachments требуется принимаемая uploads.github.com авторизация с Contents Read/write для этого репозитория; более широкие admin/workflow права не требуются.

`polaris-install.sh`, его signature и public key; source archive; полный offline bundle; test-report.md/report.txt/security-scan.json; SHA256SUMS и его Ed25519 signature. Runtime installer не изменён относительно проверенного556a5ba3… . Архивы пересобраны для этой публикации и обновлённой документации.

Production-инфраструктура при публикации не используется и не изменяется. Существующий VPN не затронут. Старый приватный follow-your-polaris и его Git history не публикуются.

### Versioned installation files

- [polaris-install.sh](https://raw.githubusercontent.com/HydraByHard/polaris-node-installer/v1.0.0/release/v1.0.0/polaris-install.sh)
- [polaris-install.sh.sig](https://raw.githubusercontent.com/HydraByHard/polaris-node-installer/v1.0.0/release/v1.0.0/polaris-install.sh.sig)
- [release-signing-public.pem](https://raw.githubusercontent.com/HydraByHard/polaris-node-installer/v1.0.0/release/v1.0.0/release-signing-public.pem)
- [polaris-node-installer-1.0.0-source.tar.gz](https://raw.githubusercontent.com/HydraByHard/polaris-node-installer/v1.0.0/release/v1.0.0/polaris-node-installer-1.0.0-source.tar.gz)
- [polaris-node-installer-1.0.0.tar.gz](https://raw.githubusercontent.com/HydraByHard/polaris-node-installer/v1.0.0/release/v1.0.0/polaris-node-installer-1.0.0.tar.gz)
- [test-report.md](https://raw.githubusercontent.com/HydraByHard/polaris-node-installer/v1.0.0/release/v1.0.0/test-report.md)
- [report.txt](https://raw.githubusercontent.com/HydraByHard/polaris-node-installer/v1.0.0/release/v1.0.0/report.txt)
- [security-scan.json](https://raw.githubusercontent.com/HydraByHard/polaris-node-installer/v1.0.0/release/v1.0.0/security-scan.json)
- [SHA256SUMS](https://raw.githubusercontent.com/HydraByHard/polaris-node-installer/v1.0.0/release/v1.0.0/SHA256SUMS)
- [SHA256SUMS.sig](https://raw.githubusercontent.com/HydraByHard/polaris-node-installer/v1.0.0/release/v1.0.0/SHA256SUMS.sig)
