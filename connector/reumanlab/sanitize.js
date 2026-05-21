"use strict";

// Error sanitization per connector contract §4.2.
// Strips host info, IPs, user@host, long tokens, and caps at 512 chars.

const MAX_ERROR_LENGTH = 512;

function sanitize(message) {
  if (!message) return "internal error";
  let s = String(message);

  // 1. Remove absolute path components outside the allowlist
  s = s.replace(/(?:\/[A-Za-z0-9._-]+){2,}/g, "[REDACTED]");

  // 2. Remove user@host strings
  s = s.replace(/[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+/g, "[REDACTED]");

  // 2b. Remove FQDN-style hostnames (word.word.word with 2+ dots)
  s = s.replace(/\b[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?){2,}\b/g, "[REDACTED]");

  // 3. Remove IPv4 addresses
  s = s.replace(/\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b/g, "[REDACTED]");

  // 4. Remove IPv6 addresses (simplified)
  s = s.replace(/\b[0-9a-fA-F]{1,4}(:[0-9a-fA-F]{1,4}){2,7}\b/g, "[REDACTED]");

  // 5. Truncate strings that look like tokens (>= 20 hex/base64 chars)
  s = s.replace(/\b[A-Za-z0-9+/=_-]{20,}\b/g, "[REDACTED]");

  // 6. Truncate to 512 characters
  if (s.length > MAX_ERROR_LENGTH) {
    s = s.slice(0, MAX_ERROR_LENGTH);
  }

  return s.trim() || "internal error";
}

module.exports = { sanitize, MAX_ERROR_LENGTH };
