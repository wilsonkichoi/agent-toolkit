---
name: security-scan
description: >
  On-demand security audit of the current repository. Scans for secrets/credentials,
  code vulnerabilities, infrastructure misconfigs, dependency risks, and optionally
  git history for leaked secrets. Triggered by /security-scan or /sec-scan.
  Use whenever the user wants to check if a repo is safe to push, publish, or share,
  or asks about secrets, vulnerabilities, sensitive info, or security posture.
  Also trigger when user says "is this safe?", "anything sensitive?", "audit this",
  or "check for leaks".
---

# Security Scan

Perform a comprehensive, on-demand security audit of the current repository.
The goal is to find anything that would be dangerous to push, deploy, or leave in code:
leaked secrets, exploitable vulnerabilities, misconfigured infrastructure, risky dependencies.

## Scan Categories

Think about security from five angles. Each category exists because different threat models
produce different findings. Don't skip categories unless the repo clearly doesn't contain
that kind of code.

### 1. Secrets and Credentials

Things that grant access if exposed.

**Look for:**
- API keys, tokens, passwords hardcoded in source
- Private keys (.pem, .key, RSA/SSH blocks in files)
- Connection strings with embedded credentials
- .env files or similar credential stores committed to the repo
- OAuth client secrets, webhook secrets
- Cloud credentials (AWS `AKIA...`, GCP service account JSON, Azure connection strings)
- Tokens in URLs, comments, config, test fixtures, or documentation
- Base64-encoded secrets (decode suspicious base64 blobs if short enough)

**Context judgment:**
- `password = "example"` or `"changeme"` or `"xxx"` → placeholder, not a finding
- `password = "j8#kL9$mN2"` → likely real
- Test fixtures with realistic-looking keys → flag but note it's in test code
- Tokens in `.example` files → low severity, but still note it

### 2. Code Vulnerabilities

Exploitable patterns in application code.

**Look for:**
- **Injection**: SQL, command (os.system, exec, child_process), template, LDAP, XPath
- **XSS**: innerHTML, dangerouslySetInnerHTML, document.write, unescaped output
- **Deserialization**: pickle, marshal, yaml.load (without SafeLoader), torch.load, joblib.load
- **Path traversal**: user input in file paths without sanitization
- **SSRF**: user-controlled URLs passed to HTTP clients
- **Auth issues**: hardcoded JWTs, disabled CSRF, missing auth middleware on sensitive routes
- **Crypto weakness**: ECB mode, createCipher (no IV), MD5/SHA1 for passwords, disabled TLS verification
- **Eval-family**: eval(), new Function(), exec() with user-controlled input
- **Race conditions**: TOCTOU in file operations, unguarded shared state

**Context judgment:**
- eval() in a build tool or REPL → low risk
- eval() in a web server handling user input → critical
- Disabled TLS verification in test setup → note but low severity
- Disabled TLS verification in production client → high severity

### 3. Infrastructure and Configuration

Settings that weaken the security posture when deployed.

**Look for:**
- **CORS**: overly permissive (allow *, credentials: true with wildcard origin)
- **IAM/permissions**: wildcard permissions, admin policies, overly broad service roles
- **Debug/dev mode**: debug=True in production configs, verbose error pages, stack traces exposed
- **Network**: ports open to 0.0.0.0/0, security groups allowing all traffic
- **Secrets management**: secrets in docker-compose.yml, Kubernetes manifests, Terraform without vault
- **Headers**: missing security headers (CSP, HSTS, X-Frame-Options) in server config
- **Logging**: sensitive data in log statements (passwords, tokens, PII)
- **Docker**: running as root, no USER directive, ADD with remote URLs

**Context judgment:**
- `debug=True` in `settings.py` → check if there's a separate production config
- Open ports in docker-compose for local dev → note, low severity
- Open ports in Kubernetes manifests → high severity

### 4. Git History

Secrets that were committed and "deleted" but remain in history.

**How to check:**
- Run `git log --all --oneline -50` to get recent history scope
- Run `git log --all --diff-filter=D -- "*.env" "*.pem" "*.key" "*.secret"` for deleted secret files
- Run `git log -p --all -S "AKIA" -S "sk-" -S "password" --max-count=10` for key patterns in history
- Check if `.gitignore` currently excludes `.env` but `.env` exists in past commits

**Context judgment:**
- If a secret was in history but has since been rotated (can't verify this), note it but explain
  the risk: anyone who cloned the repo before rotation has the old secret
- This category is expensive. If the user says "quick scan" or the repo is huge, skip or sample.

### 5. Dependencies and Configuration Risks

Supply chain and configuration surface area.

**Look for:**
- **Unpinned dependencies**: `*` or `latest` versions in package.json, requirements.txt, etc.
- **Known vulnerable packages**: check if lockfiles reference packages with well-known CVEs
  (e.g. log4j, lodash prototype pollution, older versions of auth libraries)
- **Typosquat risk**: package names that are one character off from popular packages
- **Install scripts**: postinstall hooks that download or execute external code
- **Outdated lockfiles**: lockfile missing or diverged significantly from manifest

**Context judgment:**
- Dev-only dependencies with vulnerabilities → low severity
- Production dependencies with known exploits → high severity
- No lockfile in a library (vs. application) → acceptable, just note it

## Execution Flow

1. **Orient** - read the repo structure (`find . -type f`, `.gitignore`, README) to understand
   what kind of project this is (web app, CLI, library, infra-as-code, etc.)
2. **Target** - based on project type, decide which categories deserve most attention.
   A Terraform repo needs heavy infra focus. A web app needs XSS/injection focus.
3. **Scan** - work through each category. Use grep/find for fast sweeps, then read suspicious
   files with judgment. Don't just pattern-match; understand whether a finding is real.
4. **Classify** - assign each finding a severity and confidence level.
5. **Report** - structured output (see below).

## Scan Depth

By default, do a thorough scan of all five categories. If the user specifies:
- `/security-scan quick` - skip git history, sample only high-risk files, 2-3 minutes max
- `/security-scan deep` - include git history, read more files, check dependencies thoroughly
- `/security-scan secrets` - focus only on category 1
- `/security-scan vulns` - focus on categories 2 and 3

## Output Format

```
## Security Scan Results

**Project:** <name/path>
**Scope:** <what was scanned, any categories skipped and why>
**Risk Level:** Critical / High / Medium / Low / Clean

### Findings

#### [CRITICAL] <title>
- **Category:** Secrets / Vulnerability / Infra / History / Dependencies
- **File:** <path>:<line>
- **What:** <what was found>
- **Risk:** <what an attacker could do with this>
- **Fix:** <specific remediation>

#### [HIGH] <title>
...

#### [MEDIUM] <title>
...

#### [LOW] <title>
...

### Summary
- X critical, Y high, Z medium, W low findings
- Top priority: <the one thing to fix first>
- <any categories that were clean>
```

## Important Principles

- **Real findings over volume.** Ten confident findings beat fifty maybes. If uncertain,
  say so explicitly: "[Uncertain] This looks like it might be a real key but could be a test fixture."
- **Context determines severity.** The same pattern is critical in production code and
  informational in a test helper. Always check surrounding context.
- **Actionable fixes.** Every finding should have a specific remediation, not just "fix this."
- **No false comfort.** If you couldn't scan something (binary files, encrypted configs, external
  dependencies), say what you skipped. A clean report should mean clean, not "I didn't look hard enough."
- **Prioritize by exploitability.** A credential that grants immediate access is more critical
  than a theoretical XSS that requires three preconditions.
