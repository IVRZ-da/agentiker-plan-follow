# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |

## Reporting a Vulnerability

Please report security vulnerabilities to **johannes@ivory.green**.

You will receive a response within 48 hours. If the issue is confirmed, a hotfix
will be released as soon as possible, typically within 24 hours.

## Scope

This plugin runs inside Hermes Agent and has access to:
- File system operations via configured tool permissions
- Network access for LSP servers and structured output
- Environment variables and configuration files

Any vulnerability that allows:
- Arbitrary code execution outside tool boundaries
- Unauthorized file system access
- Credential leakage via tool output
- Remote code injection through LSP server bridges

...is considered in scope.

## Security Measures

- Pre-commit hooks scan for secrets and tokens before every commit
- All tool registrations are validated at plugin load time
- LSP bridges run with `--stderr=DEVNULL` to prevent information leakage
