# Security Policy

## Supported Versions

We support the current version and the previous minor version. Security fixes are backported to all supported versions.

## Reporting a Vulnerability

We take security seriously. If you discover a vulnerability, please report it responsibly.

**How to report:**
1. Open an issue with the `security` label
2. Describe the vulnerability in detail:
   - Affected version(s)
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if you have one)

**What to expect:**
- Acknowledgment within 48 hours
- Initial assessment within 7 days
- Fix timeline based on severity
- Credit in CHANGELOG and release notes for responsible disclosure

## Security Best Practices for Users

### API Keys and Credentials
- Never commit `.env` files or API keys to version control
- Use environment variables or secret management systems
- Rotate keys regularly

### Browser Profiles
- Chrome profile data contains cookies, login sessions, and browsing history
- Never share browser profiles that contain authenticated sessions
- Use isolated profiles per-account when doing multi-account automation

### CDP Port
- The default CDP port (19222) is bound to 127.0.0.1 only
- Do not expose this port on public network interfaces
- In distributed/gateway mode, use authentication on the API layer

## Known Security Considerations

This project automates browsers for legitimate use cases (data collection with proper rate limiting, testing, research). Users are responsible for:

1. **Compliance** -- Ensure your automation complies with target websites' Terms of Service
2. **Rate Limiting** -- Be respectful of server resources; aggressive automation harms everyone
3. **Data Handling** -- Follow applicable data protection regulations (GDPR, CCPA, etc.)

## Dependencies

We depend on [browser-use](https://github.com/browser-use/browser-use) (MIT licensed), [Playwright](https://github.com/microsoft/playwright), and other open-source projects. We monitor their security advisories and update dependencies promptly.

## Security Audits

Periodic security audits are welcome. If you perform a security review of this codebase, we'd love to hear about it (open an issue or PR).
