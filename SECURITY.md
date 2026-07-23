# Security

## Supported code

Security fixes target the current `main` branch. Historical commits, generated demo media, and
third-party services are not maintained as separate supported releases.

## Report a vulnerability

Please report vulnerabilities privately rather than opening a public issue. Use
[GitHub's private vulnerability reporting form](https://github.com/crimeacs/product-demo-director/security/advisories/new).
If that form is unavailable, use a private contact method listed on the
[maintainer's GitHub profile](https://github.com/crimeacs).

Include the affected commit, impact, reproduction steps, and any practical mitigation. Remove API
keys, customer data, and private footage from the report. Please allow the maintainer time to
investigate and coordinate a fix before publishing details.

Relevant reports include command or path injection, unsafe handling of captured browser or terminal
data, secret exposure, dependency compromise, and provenance checks that can be bypassed to make an
unverified artifact appear trusted.

Product footage can contain customer data, credentials, browser state, and internal URLs. Redact
recordings before sharing, keep generated media out of Git, and rotate any credential that appears
in a recording or commit. `.env` files and common private-key formats should remain local.
